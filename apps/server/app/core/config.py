from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "AI Interview Coach API"
    app_host: str = "0.0.0.0"
    app_port: int = 3001
    app_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000,null"
    app_allowed_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^null$"
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_chat_model: str = "qwen-plus"
    dashscope_realtime_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    dashscope_realtime_model: str = "qwen3.5-omni-plus-realtime"
    dashscope_realtime_voice: str = "Ethan"
    dashscope_turn_detection_type: str = "semantic_vad"
    dashscope_turn_detection_threshold: float = 0.5
    dashscope_turn_detection_silence_duration_ms: int = 800
    dashscope_turn_detection_prefix_padding_ms: int = 300


settings = Settings()
