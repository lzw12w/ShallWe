# 播客生成 Agent
<img width="3449" height="1922" alt="image" src="https://github.com/user-attachments/assets/53c5574f-08a5-4375-909d-18ec95f64ee5" />

上传文件或粘贴文章链接 → 自动生成播客 → 播放过程中可**随时打断提问或掌控后续重点**。

架构与设计见 [DESIGN.md](./DESIGN.md)。

## 快速开始

```bash
# 1. 装依赖（建议用虚拟环境）
python3 -m venv .venv
source .venv/activate
pip install -r requirements.txt

# 2. 配置
cp .env.example .env
#   编辑 .env：
#   - 必填 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL（OpenAI 兼容协议均可）
#   - TTS 默认 edge（免 key 即可跑通）；切 mimo 填 TTS_API_KEY 并把两个 voice 改成 mimo 音色

# 3. 启动
uvicorn app.main:app --reload

# 4. 浏览器打开 http://localhost:8000
```

## 使用

1. 拖入文件（TXT/MD/PDF/DOCX）或粘贴文章链接 → 生成播客。
2. 自动逐段播放。段列表点 ▶ 可跳转。
3. **打断提问**：在底部输入框输入问题 → 点「提问」→ agent 先检索素材再生成回答段插入并续播。
4. **掌控重点**：输入方向（如「多讲讲 X」「跳过 Y」「更深入」）→ 点「引导重点」→ agent 改写剩余段落后续播。

## Agent 架构

打断/引导由 `app/agent.py` 的 ReAct 循环处理：`LLM 推理 → 工具调用 → 观察结果 → 再推理`，最多 10 步。6 个工具：list_files, read_file, write_file, edit_file, grep, finish。

Agent 通过通用文件操作工具维护工作区中的 `script.md` 播客脚本，参考只读的 `source.txt` 原始素材。

> 要求 LLM 支持 function calling（豆包/GLM/DeepSeek/OpenAI 均支持）。初始脚本生成不依赖它。

## 可插拔后端

LLM 与 TTS 均为 provider 抽象 + 配置驱动，切平台只改 `.env`：

- **LLM**：`LLM_PROVIDER=openai_compat`，配 `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL` 即适配豆包/GLM/DeepSeek/mimo/OpenAI 等。
- **TTS**：`TTS_PROVIDER` = `mimo` | `edge` | `openai_compat`。
  - `mimo`：走 chat completions + audio 输出协议，每段可带语气 `style` 提示，表现力强。
  - `edge`：免费免 key，开发/测试用。
  - `openai_compat`：标准 `/audio/speech` 协议，备用。

## 测试

```bash
pytest
```
