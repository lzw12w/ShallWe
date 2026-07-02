from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class TTSProvider(ABC):
    """TTS 抽象：文本 → 音频字节。style 为可选语气提示（mimo 用，其它忽略）。"""

    @abstractmethod
    async def synthesize(self, text: str, *, voice: str, style: Optional[str] = None) -> bytes:
        ...
