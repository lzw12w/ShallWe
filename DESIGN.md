# 播客生成 Agent · 设计文档

> 上传文件或粘贴文章链接 → 自动生成播客 → 播放过程中可**随时打断提问或掌控后续重点**。

## 1. 目标与选型

- **交互模式**：分段式可引导。先生成完整脚本分多段，逐段播放音频；任意时刻可打断提问 / 改方向，agent 即时回答并调整剩余段落。
- **技术栈**：Python + FastAPI + 轻前端（vanilla HTML/JS，无构建步骤）。
- **LLM**：可配置/可插拔，默认走 OpenAI 兼容协议（豆包/GLM/DeepSeek/mimo/OpenAI 均兼容，只需配 `base_url+key+model`）。
- **TTS**：可配置/可插拔，默认 `mimo-v2.5-tts`（走 OpenAI chat completions + audio 输出协议）。

## 2. 架构总览

```
[前端 HTML/JS]  <-- WS(控制+脚本更新) + REST(建会话/取音频) -->  [FastAPI]
                                                                   |
                 +--------------------------+----------------------+
                 |                          |                      |
           extractor.py              agent.py (agent loop)     providers/
           (文件/URL→正文)           ┌─ LLM 决策 + 工具调用 ─┐   llm/  tts/
                 |                   │  lookup_source         │  (抽象+可插拔)
                 |                   │  insert_segments       │
                 |                   │  rewrite_remaining     │
                 |                   │  finish                │
                 |                   └────────────────────────┘
                 +----------- session.py (状态机/会话存储) ----------+
```

**Agent loop**（`app/agent.py`，核心）：每次打断/引导触发一次 `run()`，循环 `LLM 决策 → 工具调用 → 观察结果 → 再决策`，最多 6 步。通过 async generator 产出 `tool` / `done` 事件，WS 转发给前端。`scriptwriter.py` 退为工具层（`generate_script` 做初始单次生成；`to_segment`/`parse_segments` 供 agent 复用）。

**4 个工具**：
- `lookup_source(query)`：在源素材中按关键词检索相关片段（回答/改写前找依据，原型用关键词匹配无需向量）。
- `insert_segments(segments)`：在当前播放段之后插入新段（用于回答打断提问）。
- `rewrite_remaining(segments)`：替换当前段之后所有未播放段（用于引导重点）。
- `finish()`：完成本次任务。

**核心数据模型**（`app/schemas.py`）：
- `Segment`: `{id, speaker: "host"|"cohost", title, text, style?, status}`（`style` 为语气提示，供 mimo TTS 用作风格指令）
- `Session`: `{id, source_text, segments, current_index, history}`
- `InterruptCmd`: `{type: "ask"|"steer"|"state", payload}`

**会话状态机**（`app/session.py`）：内存 dict 存储会话 + 音频缓存（原型够用，后续可换 SQLite）。

## 3. 交互流程

1. **建会话**：`POST /api/sessions`（multipart 文件 或 `{url}`）→ `extractor.py` 抽正文 → `scriptwriter.py` 调 LLM 生成双人对话式脚本（JSON 结构化，分 N 段，默认 ~8 段）→ 返回 `session_id` + 初始脚本。
2. **播放**：前端按段请求 `GET /api/sessions/{id}/segments/{seg_id}/audio`（服务端按需合成 wav 并缓存），用 `<audio>` 顺序播放。WS 同步当前段索引 / 段状态。
3. **打断提问（ask）**：用户提问 → JS 停止当前 `<audio>` → WS 发 `{type:"ask", payload}` → `agent.py` 跑 loop：必要时先 `lookup_source` 检索素材，再 `insert_segments` 插入回答段，`finish` → WS 推送 `thinking`/`tool`/`script` 事件 → 回答段自动播放。
4. **掌控重点（steer）**：用户输入方向 → WS 发 `{type:"steer", payload}` → `agent.py` 跑 loop：必要时 `lookup_source`，再 `rewrite_remaining` 改写未播放段，`finish` → WS 推送更新 → 从当前段之后续播。
5. **预取**（可选优化）：播放当前段时后台预合成下一段，降低切换延迟。

## 4. Provider 抽象层（可配置/可插拔）

`app/config.py`（pydantic-settings，从 `.env` 读取）统一管理配置。切 provider 只改 `.env`，不改业务代码。

- **LLM**：`base.py`（ABC `chat()->str` + `chat_with_tools()->LLMResponse`，含 `ToolCall`/`LLMResponse` 数据类）/ `openai_compat.py`（`AsyncOpenAI`，base_url+key+model 全配置化，实现原生 function calling）/ `registry.py`。
- **TTS**：`base.py`（ABC `synthesize(text, *, voice, style=None)->bytes`）
  - `mimo.py`（默认）：chat completions + audio 输出——待播文本作为 `assistant` 消息、风格指令（取自 segment 的 `style`）作为 `user` 消息，传 `audio={"format":"wav","voice":...}`，返回 `message.audio.data`（base64）解码即得 wav。
  - `openai_compat.py`：标准 `/audio/speech` 兼容（其它平台备用）。
  - `edge.py`：免费免 key 的 Edge TTS，开发/测试 fallback。
  - `registry.py`：按配置实例化。

## 5. 关键文件

| 文件 | 职责 |
|---|---|
| `app/main.py` | FastAPI 应用、REST 路由（建会话/取音频）、WS 端点（控制+脚本推送）、静态托管前端 |
| `app/config.py` | pydantic-settings，集中读 `.env` |
| `app/schemas.py` | `Segment`/`Session`/`InterruptCmd` 等模型 |
| `app/agent.py` | **agent loop 核心**：LLM 决策 + 工具调用循环，4 个工具，async generator 产出事件 |
| `app/session.py` | 会话存储 + 状态机 + 音频缓存 |
| `app/scriptwriter.py` | 初始脚本生成（`generate_script`）+ `to_segment`/`parse_segments` 工具函数（供 agent 复用） |
| `app/extractor.py` | 文件（PDF/DOCX/TXT/MD）+ URL（trafilatura 抽正文）提取 |
| `app/providers/llm/*` | LLM 抽象 + openai_compat（含 tool calling）+ registry |
| `app/providers/tts/*` | TTS 抽象 + mimo + edge + openai_compat + registry |
| `static/index.html`, `static/app.js`, `static/style.css` | 输入区 / 播放器 / 段列表 / 打断栏 / 实时逐字稿 |

## 6. 依赖

`fastapi`, `uvicorn[standard]`, `websockets`, `pydantic`, `pydantic-settings`, `httpx`, `openai`, `python-multipart`, `pypdf`, `python-docx`, `trafilatura`, `edge-tts`, `pytest`, `pytest-asyncio`。

## 7. 验证（端到端）

1. `cp .env.example .env`，填 LLM key（TTS 默认 edge 免 key 即可跑通；切 mimo 填 mimo key）。
2. `pip install -r requirements.txt` → `uvicorn app.main:app --reload`。
3. 浏览器开 `http://localhost:8000`。
4. 上传短文 / 粘贴链接 → 生成 → 自动播放。
5. 播放中「提问」→ 看到回答段插入并播放。
6. 「引导重点」输入方向 → 看到剩余段被改写 → 续播。
7. `pytest` 跑脚本生成与提取器单测。

## 8. 备注

- **agent loop 要求 LLM 支持 function calling**（豆包/GLM/DeepSeek/OpenAI 均支持）。若所用 LLM 不支持，`chat_with_tools` 有退化实现（按普通 chat 返回），但工具调用不会触发——此时打断/引导退化为无效。`generate_script`（初始生成）不依赖 tool calling，任何兼容模型都能用。
- **mimo 音色**：双人播客需两个不同音色（如 `Chloe` + 另一个），填入 `TTS_VOICE_HOST`/`TTS_VOICE_COHOST`。
- **音频格式**：mimo 返回 wav（短段够用，后续可选 `pydub`+ffmpeg 转 mp3）。
- **LLM 结构化输出**（初始脚本）：JSON 模式 + 严格 prompt + 解析容错（正则提取 JSON、失败重试）。
