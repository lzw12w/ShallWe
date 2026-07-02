from __future__ import annotations

import io
from typing import Optional

import edge_tts

from .base import TTSProvider


class EdgeTTS(TTSProvider):
    """免费免 key 的 Edge TTS，开发/测试 fallback（返回 mp3）。"""

    async def synthesize(self, text: str, *, voice: str, style: Optional[str] = None) -> bytes:
        communicate = edge_tts.Communicate(text, voice)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()
