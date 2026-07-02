from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from .base import LLMProvider, LLMResponse, ToolCall


class OpenAICompatLLM(LLMProvider):
    """OpenAI 兼容协议 adapter（豆包/GLM/DeepSeek/mimo/OpenAI 通用）。"""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        self.model = settings.llm_model

    async def chat(self, messages: list[dict], **opts: Any) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            **opts,
        )
        return resp.choices[0].message.content or ""

    async def chat_with_tools(
        self, messages: list[dict], tools: list[dict], **opts: Any
    ) -> LLMResponse:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            **opts,
        )
        msg = resp.choices[0].message
        tcs: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tcs.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=tc.function.arguments or "{}",
                    )
                )
        return LLMResponse(content=msg.content, tool_calls=tcs)
