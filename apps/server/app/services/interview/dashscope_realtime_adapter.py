import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import dashscope
from dashscope.audio.qwen_omni import MultiModality, OmniRealtimeCallback, OmniRealtimeConversation

from app.schemas.interview import RealtimeProvider, RoomPhase


# 这是一个“事件发送函数”的类型别名。
# 适配层不直接依赖 FastAPI，而是把事件通过 emitter 往外抛，
# 这样更容易替换为别的 WebSocket / 消息总线实现。
ServerEventEmitter = Callable[[dict[str, Any]], None]


@dataclass
class RealtimeSessionConfig:
    session_id: str
    provider: RealtimeProvider
    model: str
    voice: str
    instructions: str
    output_modalities: list[str]


@dataclass
class SessionRuntime:
    config: RealtimeSessionConfig
    conversation: OmniRealtimeConversation


class DashScopeRealtimeCallback(OmniRealtimeCallback):
    """
    DashScope Realtime SDK 的回调适配层。

    这里主要做两件事：
    1. 把 DashScope 原始事件翻译成前端更容易消费的 JSON 事件。
    2. 在“AI 说话中 + semantic_vad 确认用户新 turn”时，发出 interrupt.confirmed。
    """

    def __init__(self, session_id: str, emitter: ServerEventEmitter) -> None:
        super().__init__()
        self.session_id = session_id
        self.emitter = emitter
        self.assistant_speaking = False
        self.conversation: OmniRealtimeConversation | None = None

    def _build_turn_id(self) -> str:
        return f"turn_{int(time.time() * 1000)}"

    def on_open(self) -> None:
        self.emitter(
            {
                "type": "session.connected",
                "sessionId": self.session_id,
                "provider": "dashscope",
                "phase": RoomPhase.LISTENING.value,
            }
        )

    def on_event(self, response: dict[str, Any]) -> None:
        event_type = response.get("type")

        if event_type == "response.audio.delta":
            # AI 开始连续输出音频分片时，把房间切到 speaking。
            self.assistant_speaking = True
            self.emitter(
                {
                    "type": "assistant.audio.delta",
                    "sessionId": self.session_id,
                    "turnId": self._build_turn_id(),
                    "deltaBase64": response.get("delta", ""),
                }
            )
            self.emitter(
                {
                    "type": "room.phase.changed",
                    "sessionId": self.session_id,
                    "phase": RoomPhase.SPEAKING.value,
                }
            )
            return

        if event_type == "conversation.item.input_audio_transcription.completed":
            transcript = str(response.get("transcript", "")).strip()

            # 两级打断的第二级：
            # 前端先本地标记 possible_interrupt，真正是否构成“新轮次”
            # 由服务端这边收到 semantic_vad 确认后的转写完成事件来判断。
            if transcript and self.assistant_speaking and self.conversation is not None:
                try:
                    self.conversation.cancel_response()
                    self.conversation.clear_appended_audio()
                except Exception as exc:  # pragma: no cover - 依赖 SDK 实时行为
                    self.emitter(
                        {
                            "type": "provider.error",
                            "sessionId": self.session_id,
                            "message": f"DashScope interrupt cleanup failed: {exc}",
                            "retryable": True,
                        }
                    )
                else:
                    self.emitter(
                        {
                            "type": "interrupt.confirmed",
                            "sessionId": self.session_id,
                            "source": "semantic_vad",
                            "message": "semantic_vad 已确认用户开启了新的有效轮次，已中断当前 AI 回复。",
                        }
                    )

                self.assistant_speaking = False

            self.emitter(
                {
                    "type": "transcript.final",
                    "sessionId": self.session_id,
                    "turnId": self._build_turn_id(),
                    "text": transcript,
                }
            )
            self.emitter(
                {
                    "type": "room.phase.changed",
                    "sessionId": self.session_id,
                    "phase": RoomPhase.THINKING.value,
                }
            )
            return

        if event_type == "response.audio_transcript.done":
            self.assistant_speaking = False
            transcript = str(response.get("transcript", "")).strip()
            self.emitter(
                {
                    "type": "assistant.transcript.done",
                    "sessionId": self.session_id,
                    "turnId": self._build_turn_id(),
                    "text": transcript,
                }
            )
            self.emitter(
                {
                    "type": "interviewer.question",
                    "sessionId": self.session_id,
                    "turnId": self._build_turn_id(),
                    "text": transcript,
                }
            )
            self.emitter(
                {
                    "type": "room.phase.changed",
                    "sessionId": self.session_id,
                    "phase": RoomPhase.LISTENING.value,
                }
            )
            return

    def on_close(self, close_status_code, close_msg) -> None:
        self.assistant_speaking = False
        self.emitter(
            {
                "type": "provider.error",
                "sessionId": self.session_id,
                "message": f"DashScope Realtime closed: code={close_status_code}, message={close_msg}",
                "retryable": True,
            }
        )
        self.emitter(
            {
                "type": "room.phase.changed",
                "sessionId": self.session_id,
                "phase": RoomPhase.FINISHED.value,
            }
        )


class DashScopeRealtimeAdapter:
    """
    Browser -> FastAPI -> DashScope Realtime 的桥接层。

    这层负责：
    - 建立和关闭 DashScope Realtime 会话
    - 把前端音频/图片事件转给 SDK
    - 把 SDK 事件回推给前端
    """

    def __init__(
        self,
        api_key: str,
        realtime_url: str,
        emitter: ServerEventEmitter,
        turn_detection_type: str = "semantic_vad",
        turn_detection_threshold: float = 0.5,
        turn_detection_silence_duration_ms: int = 800,
        turn_detection_prefix_padding_ms: int = 300,
    ) -> None:
        self.api_key = api_key
        self.realtime_url = realtime_url
        self.emitter = emitter
        self.sessions: dict[str, SessionRuntime] = {}
        self.turn_detection_type = turn_detection_type
        self.turn_detection_threshold = turn_detection_threshold
        self.turn_detection_silence_duration_ms = turn_detection_silence_duration_ms
        self.turn_detection_prefix_padding_ms = turn_detection_prefix_padding_ms

    def _to_modalities(self, values: list[str] | None) -> list[MultiModality] | None:
        if not values:
            return None

        modalities: list[MultiModality] = []
        for value in values:
            if value == "audio":
                modalities.append(MultiModality.AUDIO)
            elif value == "text":
                modalities.append(MultiModality.TEXT)
        return modalities or None

    async def connect(self, config: RealtimeSessionConfig) -> None:
        if not self.api_key:
            self.emitter(
                {
                    "type": "provider.error",
                    "sessionId": config.session_id,
                    "message": "DashScope API Key 缺失，无法建立 Realtime 会话。",
                    "retryable": False,
                }
            )
            return

        try:
            dashscope.api_key = self.api_key
            callback = DashScopeRealtimeCallback(config.session_id, self.emitter)
            conversation = OmniRealtimeConversation(
                model=config.model,
                callback=callback,
                url=self.realtime_url,
            )
            callback.conversation = conversation

            conversation.connect()
            conversation.update_session(
                output_modalities=self._to_modalities(config.output_modalities)
                or [MultiModality.AUDIO, MultiModality.TEXT],
                voice=config.voice,
                instructions=config.instructions,
                enable_turn_detection=True,
                turn_detection_type=self.turn_detection_type,
                turn_detection_threshold=self.turn_detection_threshold,
                turn_detection_silence_duration_ms=self.turn_detection_silence_duration_ms,
                prefix_padding_ms=self.turn_detection_prefix_padding_ms,
            )

            self.sessions[config.session_id] = SessionRuntime(
                config=config,
                conversation=conversation,
            )
        except Exception as exc:
            self.emitter(
                {
                    "type": "provider.error",
                    "sessionId": config.session_id,
                    "message": f"DashScope Realtime connect failed: {exc}",
                    "retryable": True,
                }
            )
            raise

    async def handle_client_event(self, event: dict[str, Any]) -> None:
        session_id = str(event.get("sessionId", ""))
        runtime = self.sessions.get(session_id)
        if not runtime:
            self.emitter(
                {
                    "type": "provider.error",
                    "sessionId": session_id,
                    "message": "Realtime 会话尚未初始化。",
                    "retryable": True,
                }
            )
            return

        try:
            event_type = event.get("type")

            if event_type == "audio.chunk":
                self.emitter(
                    {
                        "type": "room.phase.changed",
                        "sessionId": session_id,
                        "phase": RoomPhase.TRANSCRIBING.value,
                    }
                )
                runtime.conversation.append_audio(str(event.get("payloadBase64", "")))
                return

            if event_type == "image.frame":
                image_base64 = str(event.get("imageBase64", "")).strip()
                if image_base64:
                    runtime.conversation.append_video(image_base64)
                    self.emitter(
                        {
                            "type": "context.image.received",
                            "sessionId": session_id,
                            "message": "已收到图片上下文，后续提问会结合图片内容。",
                        }
                    )
                return

            if event_type == "answer.commit":
                runtime.conversation.commit()
                self.emitter(
                    {
                        "type": "room.phase.changed",
                        "sessionId": session_id,
                        "phase": RoomPhase.THINKING.value,
                    }
                )
                return

            if event_type == "assistant.interrupt":
                runtime.conversation.cancel_response()
                runtime.conversation.clear_appended_audio()
                self.emitter(
                    {
                        "type": "interrupt.confirmed",
                        "sessionId": session_id,
                        "source": "manual",
                        "message": "已按你的手动指令中断当前 AI 回复。",
                    }
                )
                self.emitter(
                    {
                        "type": "room.phase.changed",
                        "sessionId": session_id,
                        "phase": RoomPhase.LISTENING.value,
                    }
                )
                return

            if event_type == "realtime.response.create":
                response_payload = event.get("response", {})
                prompt = (
                    str(response_payload.get("prompt", "")).strip()
                    if isinstance(response_payload, dict)
                    else ""
                )
                modalities = (
                    response_payload.get("modalities")
                    if isinstance(response_payload, dict)
                    else None
                )

                self.emitter(
                    {
                        "type": "room.phase.changed",
                        "sessionId": session_id,
                        "phase": RoomPhase.THINKING.value,
                    }
                )
                runtime.conversation.create_response(
                    instructions=prompt or None,
                    output_modalities=self._to_modalities(modalities),
                )
                self.emitter(
                    {
                        "type": "assistant.response.created",
                        "sessionId": session_id,
                        "message": prompt or "已触发 AI 回复。",
                    }
                )
                return
        except Exception as exc:
            self.emitter(
                {
                    "type": "provider.error",
                    "sessionId": session_id,
                    "message": f"DashScope Realtime event failed: {exc}",
                    "retryable": True,
                }
            )
            raise

    async def create_response(
        self,
        session_id: str,
        prompt: str | None = None,
        modalities: list[str] | None = None,
    ) -> None:
        runtime = self.sessions.get(session_id)
        if not runtime:
            self.emitter(
                {
                    "type": "provider.error",
                    "sessionId": session_id,
                    "message": "无法创建回复，因为 Realtime 会话不存在。",
                    "retryable": True,
                }
            )
            return

        try:
            self.emitter(
                {
                    "type": "room.phase.changed",
                    "sessionId": session_id,
                    "phase": RoomPhase.THINKING.value,
                }
            )
            runtime.conversation.create_response(
                instructions=prompt or None,
                output_modalities=self._to_modalities(modalities),
            )
        except Exception as exc:
            self.emitter(
                {
                    "type": "provider.error",
                    "sessionId": session_id,
                    "message": f"DashScope create_response failed: {exc}",
                    "retryable": True,
                }
            )
            raise

    async def close(self, session_id: str) -> None:
        runtime = self.sessions.pop(session_id, None)
        if runtime:
            runtime.conversation.close()
        self.emitter(
            {
                "type": "room.phase.changed",
                "sessionId": session_id,
                "phase": RoomPhase.FINISHED.value,
            }
        )
