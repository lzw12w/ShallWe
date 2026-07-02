from __future__ import annotations

from functools import lru_cache

from app.config import settings
from .base import LLMProvider
from .openai_compat import OpenAICompatLLM


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    name = settings.llm_provider.lower()
    if name == "openai_compat":
        return OpenAICompatLLM()
    raise ValueError(f"Unknown LLM provider: {name}")
