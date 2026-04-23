import asyncio
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.schemas.interview import (
    CreateSessionRequest,
    InterviewSessionSnapshot,
    InterviewTurn,
    JobAnalysisRequest,
    SessionStatus,
)
from app.services.intake.profile_analysis_service import ProfileAnalysisService
from app.services.interview.dashscope_realtime_adapter import DashScopeRealtimeAdapter
from app.services.interview.interview_orchestrator import InterviewOrchestrator
from app.services.interview.realtime_session_service import RealtimeSessionService
from app.services.qwen.dashscope_client import DashScopeClient
from app.services.report.report_generator import ReportGenerator

# FastAPI 应用入口。
# 你可以把这个文件理解成“后端总装配台”：
# - 在这里注册 REST / WebSocket 路由
# - 在这里把各种 service 组装起来
# - 在这里维护当前 Demo 版的内存态会话
app = FastAPI(title=settings.app_name)


# 允许前端从不同端口访问当前服务。
# 这是本地开发时最常见的需求：
# - 前端可能跑在 8080
# - 后端跑在 3001
allowed_origins = [
    origin.strip()
    for origin in settings.app_allowed_origins.split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_origin_regex=settings.app_allowed_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 这里先用一个最简单的内存字典保存会话。
# 这是 Demo 阶段最容易理解、最方便调试的方案。
# 后面如果你要做正式版，可以把它替换成 Redis + PostgreSQL。
session_store: dict[str, InterviewSessionSnapshot] = {}


def build_dashscope_client() -> DashScopeClient:
    """
    统一构建文本模型客户端。

    这样别的 service 就不需要反复关心：
    - api key
    - base url
    - chat model
    """

    return DashScopeClient(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        chat_model=settings.dashscope_chat_model,
    )


def build_profile_analysis_service() -> ProfileAnalysisService:
    """
    intake 层的组装函数。

    这个 service 负责两类“进入系统前”的解析：
    - 简历上传解析
    - JD 文本解析
    """

    return ProfileAnalysisService(ai_client=build_dashscope_client())


@app.get("/")
async def index() -> dict[str, Any]:
    """
    一个简单的首页说明接口。
    """

    return {
        "name": settings.app_name,
        "status": "running",
        "docsUrl": "/docs",
        "healthUrl": "/healthz",
    }


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    """
    健康检查接口。

    当你只想快速确认服务是不是启动成功时，
    访问这个接口最方便。
    """

    return {"status": "ok"}


@app.post("/api/v1/resumes/analyze")
async def analyze_resume(request: Request) -> dict[str, Any]:
    """
    简历上传解析接口。

    这里刻意没有使用 multipart/form-data，
    而是直接读取原始请求体，原因是：
    - 这样可以避免当前环境还没装 python-multipart 时接口直接起不来
    - 前端只要把文件二进制直接 POST 过来即可

    约定：
    - 请求体 body: 文件字节流
    - 请求头 X-Filename: 原始文件名
    - Content-Type: 浏览器自动带上的文件类型
    """

    file_bytes = await request.body()
    # 中文文件名最稳的方式是走 query 参数，因为浏览器对 header 值限制更严格。
    # 这里优先读取 ?filename=...，再兼容旧版 header 方案。
    encoded_filename = request.query_params.get("filename", "").strip()
    if not encoded_filename:
        encoded_filename = request.headers.get("x-filename-encoded", "").strip()
    filename = (
        unquote(encoded_filename)
        if encoded_filename
        else request.headers.get("x-filename", "resume.txt")
    )
    content_type = request.headers.get("content-type", "application/octet-stream")

    if not file_bytes:
        raise HTTPException(status_code=400, detail="上传文件为空。")

    analyzer = build_profile_analysis_service()

    try:
        result = await analyzer.analyze_resume(
            filename=filename,
            content_type=content_type,
            file_bytes=file_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "resumeProfile": result.resume_profile.model_dump(mode="json"),
        "extractedTextPreview": result.extracted_text_preview,
        "warnings": result.warnings,
    }


@app.post("/api/v1/jobs/analyze")
async def analyze_job(payload: JobAnalysisRequest) -> dict[str, Any]:
    """
    JD 文本解析接口。
    """

    analyzer = build_profile_analysis_service()

    try:
        result = await analyzer.analyze_job_text(payload.job_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "jobProfile": result.job_profile.model_dump(mode="json"),
        "normalizedTextPreview": result.normalized_text_preview,
        "warnings": result.warnings,
    }


@app.post("/api/v1/sessions")
async def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
    """
    创建面试会话。

    前端一般会在这一步把：
    - resume_profile
    - job_profile
    一起带进来。
    """

    snapshot = InterviewSessionSnapshot(
        session_id=payload.session_id,
        resume_profile=payload.resume_profile,
        job_profile=payload.job_profile,
    )
    session_store[snapshot.session_id] = snapshot
    return {"sessionId": snapshot.session_id, "status": snapshot.status.value}


@app.get("/api/v1/sessions")
async def list_sessions() -> dict[str, list[dict[str, Any]]]:
    """
    列出当前 Demo 内存中的所有会话。
    """

    return {
        "sessions": [
            {
                "sessionId": session.session_id,
                "status": session.status.value,
                "turnCount": len(session.turns),
            }
            for session in session_store.values()
        ]
    }


@app.get("/api/v1/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """
    获取单个会话详情。
    """

    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.model_dump(mode="json")


@app.get("/api/v1/sessions/{session_id}/report")
async def get_session_report(session_id: str) -> dict[str, Any]:
    """
    生成单场面试的复盘报告。
    """

    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    report_generator = ReportGenerator(build_dashscope_client())
    report = await report_generator.generate(session)
    return report.model_dump(mode="json")


@app.websocket("/ws/interview/{session_id}")
async def interview_room(websocket: WebSocket, session_id: str) -> None:
    """
    实时面试房间的 WebSocket 入口。

    这是整套 Realtime 语音链路的关键入口：
    - 浏览器连到这里
    - 这里再桥接到 DashScope Realtime
    """

    await websocket.accept()

    # 如果前端直接用某个 sessionId 建连，而会话还没创建，
    # 这里先兜底补一个最小会话，避免直接报错。
    if session_id not in session_store:
        session_store[session_id] = InterviewSessionSnapshot(session_id=session_id)

    loop = asyncio.get_running_loop()

    # transcript_lock 用来避免同一时刻多个最终转写并发进入评分闭环。
    transcript_lock = asyncio.Lock()

    async def process_candidate_transcript(candidate_answer: str) -> None:
        """
        当候选人这一轮回答完成后，执行整条业务闭环：
        1. 记录答案
        2. 生成评分
        3. 生成下一轮追问
        4. 再让 Realtime 把下一轮问题说出来
        """

        normalized_answer = candidate_answer.strip()
        if not normalized_answer:
            return

        async with transcript_lock:
            session = session_store[session_id]

            # 避免同一段最终转写被重复处理。
            if session.last_processed_transcript == normalized_answer:
                return
            session.last_processed_transcript = normalized_answer

            current_turn = session.current_turn

            # 如果当前没有问题，先补一个兜底题目，避免后续状态为空。
            if current_turn is None:
                current_turn = InterviewTurn(
                    turn_id=f"turn_{len(session.turns) + 1}",
                    turn_index=len(session.turns) + 1,
                    question="请先做一个简短的自我介绍。",
                )
                session.current_turn = current_turn
                session.turns.append(current_turn)

            current_turn.answer = normalized_answer

            next_turn, score_card = await orchestrator.handle_candidate_answer(
                session,
                normalized_answer,
            )
            current_turn.score_card = score_card

            emit(
                {
                    "type": "score.updated",
                    "sessionId": session_id,
                    "turnId": current_turn.turn_id,
                    "scoreCard": {
                        "completeness": score_card.completeness,
                        "star": score_card.star,
                        "jobMatch": score_card.job_match,
                        "clarity": score_card.clarity,
                        "speech": score_card.speech,
                        "summary": score_card.summary,
                        "starMissing": score_card.star_missing,
                        "improvementTips": score_card.improvement_tips,
                    },
                }
            )

            # 下一轮问题先进入 session 状态，再通过 Realtime 播报。
            session.current_turn = next_turn
            # 本轮评分完成后，再补一份“教练式复盘反馈”。
            # 这样前端不仅能显示分数，还能把“训练闭环”展示出来。
            turn_feedback = await report_generator.generate_turn_feedback(
                session=session,
                turn=current_turn,
            )

            emit(
                {
                    "type": "turn.feedback.generated",
                    "sessionId": session_id,
                    "turnId": current_turn.turn_id,
                    "feedback": {
                        "summary": turn_feedback.summary,
                        "strengths": turn_feedback.strengths,
                        "weakPoints": turn_feedback.weak_points,
                        "nextTrainingPlan": turn_feedback.next_training_plan,
                        "improvedAnswerExample": turn_feedback.improved_answer_example,
                    },
                }
            )

            session.current_turn = next_turn
            session.turns.append(next_turn)

            emit(
                {
                    "type": "interviewer.question",
                    "sessionId": session_id,
                    "turnId": next_turn.turn_id,
                    "text": next_turn.question,
                    "followUpReason": next_turn.follow_up_reason,
                }
            )

            await realtime_service.create_follow_up_question(session, next_turn.question)

    def emit(event: dict[str, Any]) -> None:
        """
        把事件回推给前端。

        注意这里不能直接 await，因为 DashScope SDK 回调不是 async 函数，
        所以我们把真正的发送动作交给事件循环去执行。
        """

        session = session_store.get(session_id)

        # 同步更新内存里的会话状态，保证后续查详情和生成报告时能读到最新数据。
        if session is not None:
            if event.get("type") == "session.connected":
                session.status = SessionStatus.IN_PROGRESS

            if event.get("type") == "interviewer.question":
                question_text = str(event.get("text", "")).strip()
                follow_up_reason = str(event.get("followUpReason", "")).strip() or None

                if question_text:
                    if session.current_turn is None:
                        new_turn = InterviewTurn(
                            turn_id=f"turn_{len(session.turns) + 1}",
                            turn_index=len(session.turns) + 1,
                            question=question_text,
                            follow_up_reason=follow_up_reason,
                        )
                        session.current_turn = new_turn
                        session.turns.append(new_turn)
                    else:
                        session.current_turn.question = question_text
                        session.current_turn.follow_up_reason = follow_up_reason

            if event.get("type") == "transcript.final":
                candidate_answer = str(event.get("text", "")).strip()
                if candidate_answer:
                    loop.create_task(process_candidate_transcript(candidate_answer))

        loop.create_task(websocket.send_json(event))

    # 下面开始组装“实时面试房间”所需的核心对象。
    dashscope_client = build_dashscope_client()
    orchestrator = InterviewOrchestrator(
        ai_client=dashscope_client,
        realtime_model=settings.dashscope_realtime_model,
        realtime_voice=settings.dashscope_realtime_voice,
    )
    realtime_adapter = DashScopeRealtimeAdapter(
        api_key=settings.dashscope_api_key,
        realtime_url=settings.dashscope_realtime_url,
        emitter=emit,
        turn_detection_type=settings.dashscope_turn_detection_type,
        turn_detection_threshold=settings.dashscope_turn_detection_threshold,
        turn_detection_silence_duration_ms=settings.dashscope_turn_detection_silence_duration_ms,
        turn_detection_prefix_padding_ms=settings.dashscope_turn_detection_prefix_padding_ms,
    )
    realtime_service = RealtimeSessionService(
        orchestrator=orchestrator,
        adapter=realtime_adapter,
    )
    report_generator = ReportGenerator(dashscope_client)

    try:
        # 建立 DashScope Realtime 会话，并自动发起第一题。
        await realtime_service.start_realtime_interview(session_store[session_id])
        await realtime_service.start_opening_question(session_store[session_id])

        while True:
            payload = await websocket.receive_json()
            await realtime_service.handle_client_event(payload)
    except WebSocketDisconnect:
        await realtime_service.stop_realtime_interview(session_id)
    except Exception as exc:
        await websocket.send_json(
            {
                "type": "provider.error",
                "sessionId": session_id,
                "message": f"WebSocket handler failed: {exc}",
                "retryable": True,
            }
        )
        await realtime_service.stop_realtime_interview(session_id)
