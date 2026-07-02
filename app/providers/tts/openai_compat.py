from __future__ import annotations

from typing import Optional

from openai import AsyncOpenAI

from app.config import settings
from .base import TTSProvider


class OpenAICompatTTS(TTSProvider):
    """标准 OpenAI /audio/speech 兼容 TTS（其它平台备用，返回 mp3）。"""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.tts_api_key,
            base_url=settings.tts_base_url,
        )
        self.model = settings.tts_model

    async def synthesize(self, text: str, *, voice: str, style: Optional[str] = None) -> bytes:
        resp = await self.client.audio.speech.create(
            model=self.model,
            voice=voice,
            input=text,
            response_format="mp3",
        )
        return resp.content
