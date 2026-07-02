from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- LLM ----
    llm_provider: str = "openai_compat"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # ---- TTS ----
    tts_provider: str = "edge"
    tts_base_url: str = "https://api.xiaomimimo.com/v1"
    tts_api_key: str = ""
    tts_model: str = "mimo-v2.5-tts"
    tts_voice_host: str = "zh-CN-XiaoxiaoNeural"
    tts_voice_cohost: str = "zh-CN-YunxiNeural"
    tts_audio_format: str = "wav"

    # ---- Podcast defaults ----
    podcast_num_segments: int = 8
    podcast_host_name: str = "主持人"
    podcast_cohost_name: str = "嘉宾"

    # ---- Cache ----
    audio_cache_max: int = 200

    # ---- Persistence ----
    data_dir: str = "data/podcasts"  # 本地持久化根目录（相对项目根，或绝对路径）

    # ---- Observability ----
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"

    # ---- Server ----
    host: str = "0.0.0.0"
    port: int = 8000

    def voice_for(self, speaker: str) -> str:
        return self.tts_voice_host if speaker == "host" else self.tts_voice_cohost

    def audio_media_type(self) -> str:
        if self.tts_provider == "mimo":
            fmt = self.tts_audio_format or "wav"
            return "audio/wav" if fmt == "wav" else f"audio/{fmt}"
        # edge / openai_compat 都返回 mp3
        return "audio/mpeg"


settings = Settings()
