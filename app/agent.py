from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from typing import Any, AsyncIterator, Optional

from app.config import settings
from app.providers.llm.base import LLMResponse, ToolCall
from app.providers.llm.registry import get_llm
from app.workspace import Workspace

MAX_STEPS = 10

# ---- OTel (可选) ----

_tracer = None
if settings.otel_enabled:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("podcast-agent")


def _span(name: str):
    if _tracer:
        return _tracer.start_as_current_span(name)
    return nullcontext()


# ---- 工具定义（OpenAI function calling 格式，全部作用于工作区）----

_TOOLS = [
    {"type": "function", "function": {
        "name": "list_files",
        "description": "列出工作区中的所有文件。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "读取工作区文件内容。",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string", "description": "如 source.txt / script.md"}},
                       "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "创建或覆盖工作区文件。",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "对文件做精确字符串替换（str_replace）。old_string 必须存在且唯一，否则会报错供你重试。",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"},
                                      "old_string": {"type": "string"},
                                      "new_string": {"type": "string"}},
                       "required": ["path", "old_string", "new_string"]},
    }},
    {"type": "function", "function": {
        "name": "grep",
        "description": "在工作区（或指定文件）中按正则搜索。返回 path:lineno: line 形式的命中。",
        "parameters": {"type": "object",
                       "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
                       "required": ["pattern"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "完成当前任务，停止工具调用。",
        "parameters": {"type": "object", "properties": {}},
    }},
]


_SYSTEM_PROMPT = (
    "你是一档双人播客的编排 agent。两位主播：主持人({host}) 与 嘉宾({cohost})，"
    "两人自然交替，带点打趣、悬念和清晰讲解，开篇要有钩子。\n\n"
    "你通过一个 ReAct 循环工作：推理 → 调用工具 → 观察结果 → 再推理，直到完成。\n\n"
    "工作区里有两个关键文件：\n"
    "- source.txt：原始素材（只读参考，可 grep/read，不要覆盖）。\n"
    "- script.md：你要维护的播客脚本，是唯一真相。\n\n"
    "脚本格式（严格遵守）：\n"
    "```\n"
    "# 播客标题\n\n"
    "## host | 小标题 | warm and curious\n"
    "这一段口播内容……\n\n"
    "## cohost | 小标题 | excited\n"
    "下一段口播内容……\n"
    "```\n"
    "每段 `## {speaker} | {title} | {style}`：speaker 必须是 host 或 cohost；"
    "title 是简短小标题；style 是给 TTS 的简短英文语气提示（如 warm and curious / excited and fast / calm summary）。"
    "段标题下是这一段的口播文本。\n\n"
    "你的对话历史跨任务保留：之前生成播客的上下文在你回答打断或调整时仍然可见。"
    "每次任务完成后调用 finish。"
)


def _build_system() -> str:
    return (
        _SYSTEM_PROMPT
        .replace("{host}", settings.podcast_host_name)
        .replace("{cohost}", settings.podcast_cohost_name)
    )


def _tool_label(name: str) -> str:
    return {
        "list_files": "查看工作区…",
        "read_file": "读取文件…",
        "write_file": "写入脚本…",
        "edit_file": "编辑脚本…",
        "grep": "检索素材…",
        "finish": "完成",
    }.get(name, name)


class PodcastAgent:
    """统一 ReAct agent：单一 loop 处理生成/打断/引导，工具为通用文件操作。

    messages 跨任务持久累积，共享整篇播客的生成上下文。
    """

    def __init__(self, workspace: Workspace, llm: Optional[Any] = None) -> None:
        self.workspace = workspace
        self.llm = llm or get_llm()
        self.messages: list[dict] = [{"role": "system", "content": _build_system()}]

    async def step(self, user_input: str) -> AsyncIterator[dict]:
        """跑一次 ReAct 任务。user_input 是任务指令；产出 tool/done 事件。"""
        self.messages.append({"role": "user", "content": user_input})
        for step_i in range(MAX_STEPS):
            with _span(f"agent_step_{step_i}"):
                resp: LLMResponse = await self.llm.chat_with_tools(self.messages, tools=_TOOLS)
                if not resp.has_tool_calls:
                    self.messages.append({"role": "assistant", "content": resp.content or ""})
                    yield {"event": "done", "content": resp.content or ""}
                    return
                self.messages.append(self._assistant_msg(resp))
                finished = False
                for tc in resp.tool_calls:
                    yield {"event": "tool", "name": tc.name,
                           "message": _tool_label(tc.name), "arguments": tc.arguments}
                    result = self._exec(tc)
                    self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                    yield {"event": "tool_result", "name": tc.name, "result": result}
                    if tc.name == "finish":
                        finished = True
                if finished:
                    yield {"event": "done", "content": "完成"}
                    return
        yield {"event": "done", "content": "(达到最大步数，停止)"}

    # ---- 任务指令构造（仅消息内容不同，loop/工具完全相同）----

    @staticmethod
    def generate_prompt(n: int) -> str:
        return (
            f"请基于 source.txt 生成整篇播客脚本，写入 script.md。"
            f"约 {n} 段，覆盖素材要点。完成后调用 finish。"
        )

    @staticmethod
    def ask_prompt(question: str, seg_no: int, snippet: str) -> str:
        return (
            f"听众在播放中途打断提问。当前正播放第 {seg_no} 段（首句：「{snippet}」）。\n"
            f"听众提问：{question}\n"
            f"请在该段之后插入 1-3 段回答。可先用 grep / read_file 在 source.txt 中找依据，"
            f"再用 edit_file 把回答段插入 script.md 的对应位置。完成后调用 finish。"
        )

    @staticmethod
    def steer_prompt(direction: str, seg_no: int, snippet: str) -> str:
        return (
            f"听众要求调整尚未播放的后续重点。当前正播放第 {seg_no} 段（首句：「{snippet}」）。\n"
            f"听众方向：{direction}\n"
            f"请重写该段之后的所有段，保持与已播放内容连贯。可先用 grep / read_file 在 source.txt 找依据，"
            f"再用 edit_file / write_file 修改 script.md。完成后调用 finish。"
        )

    # ---- 内部 ----

    def _assistant_msg(self, resp: LLMResponse) -> dict:
        return {
            "role": "assistant",
            "content": resp.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": tc.arguments}}
                for tc in resp.tool_calls
            ],
        }

    def _exec(self, tc: ToolCall) -> str:
        try:
            args = json.loads(tc.arguments) if tc.arguments else {}
        except json.JSONDecodeError:
            return f"错误：参数不是合法 JSON: {tc.arguments}"
        name = tc.name
        ws = self.workspace
        # source.txt 只读保护
        target_path = args.get("path", "")
        if name in ("write_file", "edit_file") and target_path == "source.txt":
            return "错误：source.txt 是原始素材，只读不可修改。请操作 script.md。"
        if name == "list_files":
            return ws.list_files()
        if name == "read_file":
            return ws.read_file(args.get("path", ""))
        if name == "write_file":
            return ws.write_file(args.get("path", ""), args.get("content", ""))
        if name == "edit_file":
            return ws.edit_file(args.get("path", ""), args.get("old_string", ""), args.get("new_string", ""))
        if name == "grep":
            return ws.grep(args.get("pattern", ""), args.get("path"))
        if name == "finish":
            return "完成"
        return f"错误：未知工具: {name}"
