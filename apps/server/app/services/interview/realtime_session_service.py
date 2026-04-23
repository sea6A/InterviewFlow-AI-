"""
Realtime 会话服务层。

这个类的定位是“流程协调者”，它本身不负责：
- 直接和 DashScope SDK 细节打交道
- 直接决定问什么、怎么评分

它负责把两类对象串起来：
- `InterviewOrchestrator`：负责业务策略
- `DashScopeRealtimeAdapter`：负责底层实时通信
"""

from typing import Any

from app.schemas.interview import InterviewSessionSnapshot
from app.services.interview.dashscope_realtime_adapter import (
    DashScopeRealtimeAdapter,
    RealtimeSessionConfig,
)
from app.services.interview.interview_orchestrator import InterviewOrchestrator


class RealtimeSessionService:
    """
    实时面试流程服务层。

    这个类很适合你从“流程视角”来理解项目：
    1. start_realtime_interview()：建立实时会话
    2. start_opening_question()：让 AI 说出第一题
    3. create_follow_up_question()：在用户回答后继续追问
    4. handle_client_event()：转发前端事件
    5. stop_realtime_interview()：关闭会话
    """

    def __init__(
        self,
        orchestrator: InterviewOrchestrator,
        adapter: DashScopeRealtimeAdapter,
    ) -> None:
        self.orchestrator = orchestrator
        self.adapter = adapter

    async def start_realtime_interview(
        self,
        session: InterviewSessionSnapshot,
    ) -> RealtimeSessionConfig:
        """
        启动一场实时面试。

        分成两步：
        1. 编排器根据简历 / JD 生成 bootstrap 配置
        2. adapter 拿这份配置去真正连接 DashScope Realtime
        """

        bootstrap = self.orchestrator.build_realtime_bootstrap(session)
        config = RealtimeSessionConfig(
            session_id=session.session_id,
            provider=bootstrap.provider,
            model=bootstrap.model,
            voice=bootstrap.voice,
            instructions=bootstrap.instructions,
            output_modalities=bootstrap.output_modalities,
        )

        await self.adapter.connect(config)
        return config

    async def start_opening_question(self, session: InterviewSessionSnapshot) -> None:
        """
        会话建立完成后，主动触发第一题。

        注意：
        - 这里不是“前端手动发一条文本给模型”
        - 而是服务端根据业务场景主动触发一轮 Realtime response
        """

        opening_prompt = self.orchestrator.build_opening_prompt(session)
        await self.adapter.create_response(
            session_id=session.session_id,
            prompt=opening_prompt,
            modalities=["audio", "text"],
        )

    async def create_follow_up_question(
        self,
        session: InterviewSessionSnapshot,
        prompt: str,
    ) -> None:
        """
        让 AI 把下一轮追问说出来。

        这里的 prompt 一般来自 `InterviewOrchestrator.handle_candidate_answer()`，
        也就是候选人答完一题之后生成的新问题。
        """

        await self.adapter.create_response(
            session_id=session.session_id,
            prompt=prompt,
            modalities=["audio", "text"],
        )

    async def handle_client_event(self, event: dict[str, Any]) -> None:
        """
        转发前端事件。

        当前版本不在这里做复杂分发，而是统一交给 adapter：
        - `audio.chunk`
        - `answer.commit`
        - `assistant.interrupt`
        - `image.frame`
        都从这里进入
        """

        await self.adapter.handle_client_event(event)

    async def stop_realtime_interview(self, session_id: str) -> None:
        """
        结束实时会话。

        当前通常发生在：
        - 浏览器断开 WebSocket
        - 服务端异常，需要清理 Realtime 会话
        """

        await self.adapter.close(session_id)
