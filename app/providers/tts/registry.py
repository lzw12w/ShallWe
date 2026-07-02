from __future__ import annotations

from functools import lru_cache

from app.config import settings
from .base import TTSProvider
from .edge import EdgeTTS
from .mimo import MimoTTS
from .openai_compat import OpenAICompatTTS


@lru_cache(maxsize=1)
def get_tts() -> TTSProvider:
    name = settings.tts_provider.lower()
    if name == "mimo":
        return MimoTTS()
    if name == "edge":
        return EdgeTTS()
    if name == "openai_compat":
        return OpenAICompatTTS()
    raise ValueError(f"Unknown TTS provider: {name}")
