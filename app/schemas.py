from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Speaker = Literal["host", "cohost"]
SegStatus = Literal["pending", "ready", "played"]


class Segment(BaseModel):
    id: str
    speaker: Speaker = "host"
    title: str = ""
    text: str
    style: Optional[str] = None  # 语气提示，供 mimo TTS 用作风格指令
    status: SegStatus = "pending"


class Session(BaseModel):
    """播客会话的可序列化视图（运行态由 PodcastSession 持有，脚本为唯一真相）。"""

    id: str
    title: str = ""
    segments: list[Segment] = Field(default_factory=list)
    current_index: int = 0


class InterruptCmd(BaseModel):
    type: Literal["ask", "steer", "state"]
    payload: str = ""
