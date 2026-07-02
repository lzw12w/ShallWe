import json

from app.agent import PodcastAgent
from app.providers.llm.base import LLMResponse, ToolCall
from app.workspace import Workspace, SCRIPT_PATH, SOURCE_PATH, parse_script_md


class FakeLLM:
    """按预设序列返回 LLMResponse，模拟多步 ReAct。"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.i = 0

    async def chat_with_tools(self, messages, tools, **opts):
        r = self.responses[self.i]
        self.i += 1
        return r


def _tc(name, args=None, id_="tc"):
    return ToolCall(id=id_, name=name, arguments=json.dumps(args or {}))


def _make_agent():
    ws = Workspace()
    ws.files[SOURCE_PATH] = "人工智能是计算机科学的分支。机器学习是AI的子领域。"
    return PodcastAgent(ws)


# ---- 持久上下文：messages 跨 step 累积 ----

async def test_messages_persist_across_steps():
    agent = _make_agent()
    fake = FakeLLM(
        LLMResponse(tool_calls=[_tc("finish", id_="f1")]),
        LLMResponse(tool_calls=[_tc("finish", id_="f2")]),
    )
    agent.llm = fake
    base = len(agent.messages)
    [e async for e in agent.step("任务一")]
    # user + assistant(finish tool_call) + tool(result) = 3
    assert len(agent.messages) == base + 3
    [e async for e in agent.step("任务二")]
    # 第二次 step 的消息追加在第一次之后 → 上下文持久
    assert len(agent.messages) == base + 6
    assert agent.messages[base]["content"] == "任务一"
    assert agent.messages[base + 3]["content"] == "任务二"


# ---- generate：agent 写 script.md，解析出段 ----

async def test_generate_writes_script():
    agent = _make_agent()
    script = (
        "# 测试播客\n\n"
        "## host | 开场 | warm and curious\n"
        "欢迎收听。\n\n"
        "## cohost | 展开 | excited\n"
        "今天聊聊AI。\n"
    )
    fake = FakeLLM(LLMResponse(tool_calls=[_tc("write_file", {"path": SCRIPT_PATH, "content": script})]),
                   LLMResponse(tool_calls=[_tc("finish")]))
    agent.llm = fake
    events = [e async for e in agent.step(PodcastAgent.generate_prompt(2))]
    title, segs = parse_script_md(agent.workspace.script())
    assert title == "测试播客"
    assert len(segs) == 2
    assert segs[0].speaker == "host"
    assert events[-1]["event"] == "done"
    assert events[0]["event"] == "tool"
    assert events[0]["name"] == "write_file"
    assert events[0]["message"] == "写入脚本…"
    assert "arguments" in events[0]
    assert any(e["event"] == "tool_result" and e["name"] == "write_file" for e in events)


# ---- ask：grep 素材 → edit 插段，新段被检测 ----

async def test_ask_uses_grep_and_inserts():
    agent = _make_agent()
    # 预置已有脚本
    agent.workspace.write_file(SCRIPT_PATH,
                               "## host | 开场 | warm\n欢迎。\n\n## cohost | 下文 | calm\n继续。\n")
    from app.session import PodcastSession
    # 模拟插入：用 edit_file 在开场段后加一段
    fake = FakeLLM(
        LLMResponse(tool_calls=[_tc("grep", {"pattern": "机器学习"}, id_="g1")]),
        LLMResponse(tool_calls=[_tc("edit_file",
                                    {"path": SCRIPT_PATH, "old_string": "欢迎。\n",
                                     "new_string": "欢迎。\n\n## host | 回答 | curious\n好问题，AI就是…\n"}, id_="e1")]),
        LLMResponse(tool_calls=[_tc("finish", id_="f1")]),
    )
    agent.llm = fake
    events = [e async for e in agent.step(PodcastAgent.ask_prompt("什么是AI？", 1, "欢迎。"))]
    tool_names = [e["name"] for e in events if e["event"] == "tool"]
    assert tool_names == ["grep", "edit_file", "finish"]

    # 解析后应有 3 段，新段（回答）在索引 1
    _, segs = parse_script_md(agent.workspace.script())
    assert len(segs) == 3
    assert "好问题" in segs[1].text


# ---- steer：rewrite 剩余段 ----

async def test_steer_rewrites_via_write():
    agent = _make_agent()
    agent.workspace.write_file(SCRIPT_PATH,
                               "## host | 开场 | warm\n已播放。\n\n## cohost | 待改 | calm\n旧内容。\n")
    new_script = "## host | 开场 | warm\n已播放。\n\n## cohost | 新 | excited\n新内容。\n"
    fake = FakeLLM(
        LLMResponse(tool_calls=[_tc("write_file", {"path": SCRIPT_PATH, "content": new_script})]),
        LLMResponse(tool_calls=[_tc("finish")]),
    )
    agent.llm = fake
    [e async for e in agent.step(PodcastAgent.steer_prompt("更深入", 1, "已播放。"))]
    _, segs = parse_script_md(agent.workspace.script())
    assert len(segs) == 2
    assert segs[1].text == "新内容。"


# ---- 无工具直接完成 ----

async def test_finish_without_tools():
    agent = _make_agent()
    agent.llm = FakeLLM(LLMResponse(content="直接完成"))
    events = [e async for e in agent.step("hi")]
    assert events[-1] == {"event": "done", "content": "直接完成"}
