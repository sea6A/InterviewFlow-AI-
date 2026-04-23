from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    """
    整场面试会话的业务状态。

    这个状态更偏“后端视角”：
    - created: 会话对象已经创建
    - in_progress: 面试正在进行
    - finished: 整场面试已结束
    """

    CREATED = "created"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    FINISHED = "finished"


class RealtimeProvider(str, Enum):
    """
    当前项目支持的实时语音 Provider。

    先保留成枚举，是为了以后如果你想接别的平台，
    可以少改一些 schema 和业务判断。
    """

    DASHSCOPE = "dashscope"


class RoomPhase(str, Enum):
    """
    WebSocket 面试房间里的实时状态。

    它和 SessionStatus 不一样：
    - SessionStatus 更像一整场会话的生命周期
    - RoomPhase 更像当前 UI 应该显示什么
    """

    IDLE = "idle"
    CONNECTING = "connecting"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    FINISHED = "finished"


class ResumeProject(BaseModel):
    """
    简历里的一个项目经历。
    """

    name: str
    highlights: list[str] = Field(default_factory=list)


class ResumeProfile(BaseModel):
    """
    从简历中抽取出的结构化信息。

    这份对象很重要，因为后续追问、评分和报告都会拿它做上下文。
    """

    resume_id: str
    summary: str
    strengths: list[str] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)


class JobProfile(BaseModel):
    """
    从 JD 中抽出的岗位画像。
    """

    job_id: str
    title: str
    seniority: Literal["intern", "junior", "middle", "senior"] = "junior"
    keywords: list[str] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)


class ScoreCard(BaseModel):
    """
    单轮回答评分卡。
    """

    completeness: int
    star: int
    job_match: int
    clarity: int
    speech: int
    summary: str
    # star_missing 用于前端可视化显示：
    # 候选人这一轮回答里，STAR 哪些部分仍然缺失。
    # 可选值通常是 situation / task / action / result。
    star_missing: list[str] = Field(default_factory=list)
    improvement_tips: list[str] = Field(default_factory=list)


class InterviewTurn(BaseModel):
    """
    一轮问答记录。

    question: 面试官提问
    answer: 候选人回答
    follow_up_reason: 为什么会追问这一题
    score_card: 这轮回答的评分结果
    """

    turn_id: str
    turn_index: int
    question: str
    answer: str | None = None
    follow_up_reason: str | None = None
    score_card: ScoreCard | None = None


class InterviewSessionSnapshot(BaseModel):
    """
    整场会话在内存中的快照。

    目前还是 Demo 阶段，所以先保存在内存字典里。
    后面如果接 PostgreSQL / Redis，可以把这个对象映射到持久层。
    """

    session_id: str
    status: SessionStatus = SessionStatus.CREATED
    realtime_provider: RealtimeProvider = RealtimeProvider.DASHSCOPE
    resume_profile: ResumeProfile | None = None
    job_profile: JobProfile | None = None
    current_turn: InterviewTurn | None = None
    turns: list[InterviewTurn] = Field(default_factory=list)

    # 防止同一段最终转写被重复触发评分闭环。
    last_processed_transcript: str | None = None


class CreateSessionRequest(BaseModel):
    """
    创建面试会话时的请求体。
    """

    session_id: str
    resume_profile: ResumeProfile | None = None
    job_profile: JobProfile | None = None


class RealtimeSessionBootstrap(BaseModel):
    """
    建立 Realtime 会话时的初始化参数。
    """

    provider: RealtimeProvider
    model: str
    voice: str
    instructions: str
    output_modalities: list[Literal["audio", "text"]]


class JobAnalysisRequest(BaseModel):
    """
    JD 文本解析接口的请求体。
    """

    job_text: str


class ResumeAnalysisResponse(BaseModel):
    """
    简历解析接口的响应体。

    extracted_text_preview:
    - 给前端做调试和预览用
    - 不返回整份全文，避免页面太吵
    """

    resume_profile: ResumeProfile
    extracted_text_preview: str
    warnings: list[str] = Field(default_factory=list)


class JobAnalysisResponse(BaseModel):
    """
    JD 解析接口的响应体。
    """

    job_profile: JobProfile
    normalized_text_preview: str
    warnings: list[str] = Field(default_factory=list)
