from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON 字符串


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(ABC):
    """LLM 抽象：chat 返回纯文本；chat_with_tools 返回含 tool_calls 的结构化响应。"""

    @abstractmethod
    async def chat(self, messages: list[dict], **opts: Any) -> str:
        ...

    async def chat_with_tools(
        self, messages: list[dict], tools: list[dict], **opts: Any
    ) -> LLMResponse:
        """默认实现：不支持 tool calling 的 provider 退化为普通 chat。"""
        text = await self.chat(messages, **opts)
        return LLMResponse(content=text)
