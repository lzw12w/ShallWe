from __future__ import annotations

import base64
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings
from .base import TTSProvider


class MimoTTS(TTSProvider):
    """mimo-v2.5-tts：走 OpenAI chat completions + audio 输出协议。

    待播文本作为 assistant 消息、风格指令作为 user 消息，
    传 audio={"format","voice"}，返回 message.audio.data（base64）。
    """

    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.tts_api_key,
            base_url=settings.tts_base_url,
        )
        self.model = settings.tts_model
        self.fmt = settings.tts_audio_format or "wav"

    async def synthesize(self, text: str, *, voice: str, style: Optional[str] = None) -> bytes:
        user_msg = style or "自然、对话式的播客播报语气。"
        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": text},
            ],
            audio={"format": self.fmt, "voice": voice},
        )
        audio_obj = completion.choices[0].message.audio
        if not audio_obj or not getattr(audio_obj, "data", None):
            raise RuntimeError("mimo TTS 返回了空的音频")
        return base64.b64decode(audio_obj.data)
