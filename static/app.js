const $ = (sel) => document.querySelector(sel);

let sessionId = null;
let session = null;
let ws = null;
let currentIndex = 0;
let autoPlay = true;
let agentBusy = false;
let lastNowIndex = -1;
let toolLog = [];
const audio = new Audio();

const SPEAKER_LABEL = { host: "主持人", cohost: "嘉宾" };

const TOOL_ICONS = {
  list_files: "\u{1F4C2}",
  read_file: "\u{1F4D6}",
  write_file: "✍️",
  edit_file: "✏️",
  grep: "\u{1F50D}",
  finish: "✅",
};

// 大段文字的展示上限
const KV_INLINE_MAX = 120;   // 超过则改块状展示
const KV_PREVIEW_MAX = 400;  // 块状预览截断
const KV_FULL_MAX = 4000;    // 展开后的硬上限
const LIVE_STEP_KEEP = 6;    // 中央实时日志最多保留的条数

// ---------------- 状态控制 ----------------

function setBusy(busy, msg) {
  agentBusy = busy;
  $("#ask-btn").disabled = busy;
  $("#steer-btn").disabled = busy;
  $("#interrupt-input").disabled = busy;
  if (msg) setStatus(msg);
}

// ---------------- 输入 / 生成 ----------------

async function generate() {
  const fileInput = $("#file");
  const url = $("#url").value.trim();
  const fd = new FormData();
  if (fileInput.files && fileInput.files[0]) {
    fd.append("file", fileInput.files[0]);
  } else if (url) {
    fd.append("url", url);
  } else {
    setStatus("请上传文件或粘贴链接");
    return;
  }
  setStatus("正在提取内容…");
  $("#gen-btn").disabled = true;
  try {
    const resp = await fetch("/api/sessions", { method: "POST", body: fd });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    sessionId = data.id;
    session = data;
    currentIndex = 0;
    lastNowIndex = -1;
    showPlayer();
    render();
    connectWS();
  } catch (e) {
    setStatus("生成失败：" + e.message);
    $("#gen-btn").disabled = false;
  }
}

function showPlayer() {
  $("#input-view").classList.add("hidden");
  $("#player-view").classList.remove("hidden");
}

// ---------------- 往期播客库 ----------------

function fmtDate(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function loadLibrary() {
  const list = $("#library-list");
  const empty = $("#library-empty");
  if (!list) return;
  try {
    const resp = await fetch("/api/podcasts");
    if (!resp.ok) return;
    const data = await resp.json();
    const items = data.podcasts || [];
    list.innerHTML = "";
    if (empty) empty.classList.toggle("hidden", items.length > 0);
    items.forEach((p) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.className = "lib-item" + (p.id === sessionId ? " active" : "");
      btn.dataset.id = p.id;
      btn.innerHTML = "<span class=\"lib-play\">\u25B6</span>"
        + "<span class=\"lib-body\">"
        + "<span class=\"lib-title\">" + escapeHtml(p.title || "未命名播客") + "</span>"
        + "<span class=\"lib-meta\">" + (p.num_segments || 0) + " 段 · " + fmtDate(p.updated_at) + "</span>"
        + "</span>";
      btn.addEventListener("click", () => openSession(p.id));
      li.appendChild(btn);
      list.appendChild(li);
    });
  } catch (e) { /* 静默 */ }
}

function highlightLibrary() {
  document.querySelectorAll("#library-list .lib-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.id === sessionId);
  });
}

// 「创建播客」：回到输入页，重置状态
function newPodcast() {
  audio.pause();
  sessionId = null;
  session = null;
  currentIndex = 0;
  lastNowIndex = -1;
  autoPlay = true;
  if (ws) { try { ws.close(); } catch (e) {} ws = null; }
  document.body.classList.remove("playing");
  $("#player-view").classList.add("hidden");
  $("#input-view").classList.remove("hidden");
  $("#gen-btn").disabled = false;
  $("#file").value = "";
  $("#url").value = "";
  setStatus("");
  highlightLibrary();
}

async function openSession(sid) {
  setStatus("正在载入往期播客…");
  try {
    const resp = await fetch("/api/sessions/" + sid);
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    sessionId = sid;
    session = data;
    currentIndex = data.current_index || 0;
    lastNowIndex = -1;
    autoPlay = false; // 重听时不自动播放，等用户点 ▶
    showPlayer();
    render();
    connectWS();
    setStatus("");
    highlightLibrary();
  } catch (e) {
    setStatus("载入失败：" + e.message);
  }
}

// ---------------- WebSocket ----------------

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/${sessionId}`);
  ws.onopen = () => {
    setBusy(true, "正在生成播客脚本…");
    ws.send(JSON.stringify({ type: "generate" }));
  };
  ws.onmessage = (ev) => handleWS(JSON.parse(ev.data));
  ws.onclose = () => setStatus("连接已断开");
}

function handleWS(msg) {
  if (msg.event === "script") {
    session = msg.session;
    setBusy(false, "");
    finishThinking();
    render();
    loadLibrary();
    if (msg.play_index != null && autoPlay) {
      playIndex(msg.play_index);
    }
  } else if (msg.event === "thinking") {
    setBusy(true, msg.message || "思考中…");
    startThinking(msg.message || "思考中…");
  } else if (msg.event === "tool") {
    setStatus(msg.message || "调用工具…");
    onToolCall(msg.name, msg.message || msg.name, msg.arguments || "");
  } else if (msg.event === "tool_result") {
    onToolResult(msg.name, msg.result || "");
  } else if (msg.event === "error") {
    setBusy(false, "出错：" + msg.message);
    onToolError(msg.message);
    finishThinking();
  } else if (msg.event === "ack") {
    setStatus(msg.message);
  }
}

function sendState(i) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "state", payload: String(i) }));
  }
}

// ---------------- 播放 ----------------

function playIndex(i) {
  if (!session || i < 0 || i >= session.segments.length) {
    audio.pause();
    return;
  }
  currentIndex = i;
  const seg = session.segments[i];
  audio.src = `/api/sessions/${sessionId}/segments/${seg.id}/audio`;
  audio.play().catch(() => setStatus("浏览器阻止了自动播放，请点击 ▶"));
  sendState(i);
  render();
}

function togglePlay() {
  if (audio.paused) {
    if (!audio.src) playIndex(currentIndex);
    else audio.play();
  } else {
    audio.pause();
  }
}

audio.addEventListener("ended", () => {
  if (currentIndex + 1 < session.segments.length) {
    playIndex(currentIndex + 1);
  } else {
    setStatus("播客播放完毕");
    updatePlayBtn();
  }
});
audio.addEventListener("play", updatePlayBtn);
audio.addEventListener("pause", updatePlayBtn);
audio.addEventListener("play", teleStart);
audio.addEventListener("pause", teleStop);
audio.addEventListener("ended", teleStop);

// ---------------- 进度条 / 跳转 ----------------
let seekPreviewRatio = null;   // 拖动中预览比例,松手后清空
function fmtTime(s) {
  if (!isFinite(s) || s < 0) s = 0;
  const m = Math.floor(s / 60);
  const c = Math.floor(s % 60);
  return m + ":" + String(c).padStart(2, "0");
}

function updateProgress() {
  const fill = $("#seek-fill");
  const knob = $("#seek-knob");
  const d = audio.duration || 0;
  const c = (seekPreviewRatio != null && d) ? seekPreviewRatio * d : (audio.currentTime || 0);
  const pct = d ? Math.min(100, (c / d) * 100) : 0;
  if (fill) fill.style.width = pct + "%";
  if (knob) knob.style.left = pct + "%";
  const el = $("#time-elapsed"); if (el) el.textContent = fmtTime(c);
  const tot = $("#time-total"); if (tot) tot.textContent = fmtTime(d);
  const track = $("#seek-track"); if (track) track.setAttribute("aria-valuenow", Math.round(pct));
  teleKick();
}

audio.addEventListener("timeupdate", updateProgress);
audio.addEventListener("loadedmetadata", updateProgress);
audio.addEventListener("emptied", () => { audio.currentTime = 0; updateProgress(); });

// ---------------- 中央文字自动上推(提词器) ----------------
// 常驻 rAF 循环:每帧直接读 audio.currentTime 算目标位移,再对当前位移做
// 指数逼近后用 transform 应用。transform 支持亚像素 + GPU 合成,
// 不像 scrollTop 会被整数化,所以推进是真正连续平滑的。
let teleCurrent = 0;     // 当前实际位移(px,可为小数)
let teleRAF = null;      // 循环句柄

function teleReset() {
  teleCurrent = 0;
  const inner = $("#now-playing");
  if (inner) inner.style.transform = "translate3d(0,0,0)";
}

function teleLoop() {
  const view = $("#now-viewport");
  const inner = $("#now-playing");
  if (!view || !inner) { teleRAF = null; return; }

  // 可推进距离 = 内容高 - 窗口高(含首行的 padding-top 让开头留白)
  const scrollable = Math.max(0, inner.scrollHeight - view.clientHeight);
  const d = audio.duration || 0;
  const c = audio.currentTime || 0;
  const ratio = d ? Math.min(1, Math.max(0, c / d)) : 0;
  const target = ratio * scrollable;

  // 指数逼近,削掉 timeupdate 的秒级台阶,得到丝滑跟进
  teleCurrent += (target - teleCurrent) * 0.14;
  if (Math.abs(target - teleCurrent) < 0.15) teleCurrent = target;

  inner.style.transform = "translate3d(0," + (-teleCurrent).toFixed(2) + "px,0)";
  teleRAF = requestAnimationFrame(teleLoop);
}

function teleStart() {
  if (!teleRAF) teleRAF = requestAnimationFrame(teleLoop);
}
function teleStop() {
  if (teleRAF) { cancelAnimationFrame(teleRAF); teleRAF = null; }
}
// 暂停态下(拖动/键盘 seek)单次刷新到目标位移
function teleKick() {
  if (teleRAF) return;   // 播放中循环已在跑
  const view = $("#now-viewport");
  const inner = $("#now-playing");
  if (!view || !inner) return;
  const scrollable = Math.max(0, inner.scrollHeight - view.clientHeight);
  const d = audio.duration || 0;
  const c = (seekPreviewRatio != null && d) ? seekPreviewRatio * d : (audio.currentTime || 0);
  const ratio = d ? Math.min(1, Math.max(0, c / d)) : 0;
  teleCurrent = ratio * scrollable;
  inner.style.transform = "translate3d(0," + (-teleCurrent).toFixed(2) + "px,0)";
}

(function bindSeek() {
  const track = $("#seek-track");
  if (!track) return;
  let seeking = false;

  const ratioAt = (clientX) => {
    const r = track.getBoundingClientRect();
    return Math.min(1, Math.max(0, (clientX - r.left) / r.width));
  };
  // 拖动中:只更新预览,不写 audio.currentTime,避免频繁 seek 卡顿
  const preview = (clientX) => {
    seekPreviewRatio = ratioAt(clientX);
    updateProgress();
  };
  // 落定:真正跳转
  const commit = () => {
    if (seekPreviewRatio != null && audio.duration) {
      audio.currentTime = seekPreviewRatio * audio.duration;
    }
    seekPreviewRatio = null;
    seeking = false;
    updateProgress();
  };

  track.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    seeking = true;
    try { track.setPointerCapture(e.pointerId); } catch (_) {}
    preview(e.clientX);
  });
  track.addEventListener("pointermove", (e) => { if (seeking) preview(e.clientX); });
  track.addEventListener("pointerup", (e) => { if (seeking) { preview(e.clientX); commit(); } });
  track.addEventListener("pointercancel", () => { commit(); });
  track.addEventListener("keydown", (e) => {
    if (!audio.duration) return;
    if (e.key === "ArrowRight") { audio.currentTime = Math.min(audio.duration, audio.currentTime + 5); updateProgress(); }
    else if (e.key === "ArrowLeft") { audio.currentTime = Math.max(0, audio.currentTime - 5); updateProgress(); }
  });
})();

function updatePlayBtn() {
  const paused = audio.paused;
  $("#play-btn").textContent = paused ? "▶" : "⏸";
  document.body.classList.toggle("playing", !paused);
  const ds = $("#deck-status");
  if (ds) ds.textContent = paused ? "待播" : "ON AIR";
}

// ---------------- 打断 ----------------

function interrupt(type) {
  if (agentBusy) return;
  const input = $("#interrupt-input");
  const payload = input.value.trim();
  if (!payload) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    setStatus("未连接，无法发送");
    return;
  }
  audio.pause();
  autoPlay = true;
  setBusy(true, type === "ask" ? "正在生成回答…" : "正在调整后续重点…");
  ws.send(JSON.stringify({ type, payload }));
  input.value = "";
}

// ---------------- 工具日志：生成态(中央) / 完成态(底部) ----------------

function startThinking(message) {
  toolLog = [];
  // 中央实时日志出现，覆盖文字焦点区
  const live = $("#thinking-live");
  const liveSteps = $("#thinking-steps-live");
  liveSteps.innerHTML = "";
  $("#thinking-live-title").textContent = message;
  live.classList.remove("hidden");
  const focus = $("#focus");
  if (focus) focus.classList.add("generating");
  // 底部面板此刻收起隐藏
  const panel = $("#thinking-panel");
  panel.classList.add("hidden");
  panel.classList.add("active");
  addLiveStep("thinking", "思考", message);
}

function addLiveStep(type, name, message) {
  const steps = $("#thinking-steps-live");
  if (!steps) return;
  const li = document.createElement("li");
  li.className = "live-step";
  const icon = type === "thinking" ? "\u{1F4AD}"
    : type === "error" ? "❌"
    : (TOOL_ICONS[name] || "\u{1F527}");
  li.innerHTML = "<span class=\"step-icon\">" + icon + "</span>"
    + "<span>" + escapeHtml(message) + "</span>";
  steps.appendChild(li);
  // 只保留最近几条，避免堆叠抖动
  while (steps.children.length > LIVE_STEP_KEEP) {
    steps.removeChild(steps.firstChild);
  }
}

function onToolCall(name, message, argsStr) {
  toolLog.push({ type: "tool", name, message, arguments: argsStr, result: null });
  addLiveStep("tool", name, message);
}

function onToolResult(name, result) {
  // 结果挂到最近一条同名调用
  for (let i = toolLog.length - 1; i >= 0; i--) {
    if (toolLog[i].name === name && toolLog[i].result == null) {
      toolLog[i].result = result;
      break;
    }
  }
}

function onToolError(message) {
  toolLog.push({ type: "error", name: "error", message: message, arguments: "", result: null });
  addLiveStep("error", "error", message);
}

function finishThinking() {
  // 隐藏中央实时日志，文字焦点区回归
  const live = $("#thinking-live");
  if (live) live.classList.add("hidden");
  const fc = $("#focus");
  if (fc) fc.classList.remove("generating");
  // 把完整工具历史渲染到底部可展开面板
  const panel = $("#thinking-panel");
  if (!panel) return;
  panel.classList.remove("active");
  if (toolLog.length === 0) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  renderToolHistory();
}

function parseArgs(argsStr) {
  if (!argsStr) return {};
  try {
    const obj = JSON.parse(argsStr);
    return (obj && typeof obj === "object") ? obj : { "参数": String(obj) };
  } catch (e) {
    return { "参数": String(argsStr) };
  }
}

function renderKV(key, rawVal) {
  const val = String(rawVal == null ? "" : rawVal);
  const isLong = val.length > KV_INLINE_MAX || val.indexOf("\n") >= 0;
  if (!isLong) {
    return "<div class=\"kv-row\"><span class=\"kv-key\">" + escapeHtml(key) + "</span>"
      + "<span class=\"kv-val\">" + escapeHtml(val) + "</span></div>";
  }
  const preview = val.slice(0, KV_PREVIEW_MAX);
  const clipped = val.length > KV_PREVIEW_MAX;
  const full = val.slice(0, KV_FULL_MAX);
  return "<div class=\"kv-row\"><span class=\"kv-key\">" + escapeHtml(key) + "</span>"
    + "<span class=\"kv-val block\" data-full=\"" + encodeURIComponent(full) + "\">"
    + escapeHtml(preview) + (clipped ? "…" : "") + "</span>"
    + "<span class=\"kv-more\" role=\"button\">展开全部</span></div>";
}

function renderToolHistory() {
  const steps = $("#thinking-steps");
  steps.innerHTML = "";
  toolLog.forEach((e) => {
    const li = document.createElement("li");
    li.className = "thinking-step";
    const icon = e.type === "error" ? "❌" : (TOOL_ICONS[e.name] || "\u{1F527}");
    let kv = "";
    const args = parseArgs(e.arguments);
    Object.keys(args).forEach((k) => { kv += renderKV(k, args[k]); });
    if (e.result != null && e.result !== "") {
      kv += renderKV("结果", e.result);
    }
    const nameTag = e.name && e.name !== "error"
      ? "<span class=\"step-name\">" + escapeHtml(e.name) + "</span>" : "";
    li.innerHTML = "<span class=\"step-icon\">" + icon + "</span>"
      + "<span class=\"step-content\">"
      + "<span class=\"step-label\">" + escapeHtml(e.message || e.name || "") + "</span>"
      + nameTag
      + (kv ? "<div class=\"step-kv\">" + kv + "</div>" : "")
      + "</span>";
    steps.appendChild(li);
  });
  const cnt = $("#thinking-count");
  if (cnt) cnt.textContent = toolLog.length + " 步";
}

// ---------------- 渲染 ----------------

function render() {
  renderNow();
  const list = $("#segment-list");
  list.innerHTML = "";
  if (!session || !session.segments) return;
  session.segments.forEach((seg, i) => {
    const li = document.createElement("li");
    li.className = "segment" + (i === currentIndex ? " current" : "");
    li.dataset.index = i;
    li.innerHTML = `
      <div class="seg-head">
        <span class="badge ${seg.speaker}">${SPEAKER_LABEL[seg.speaker] || seg.speaker}</span>
        <span class="seg-title">${escapeHtml(seg.title || "")}</span>
        <button class="seg-play" title="播放此段">▶</button>
      </div>
      <div class="seg-text">${escapeHtml(seg.text)}</div>
    `;
    li.querySelector(".seg-play").addEventListener("click", () => playIndex(i));
    list.appendChild(li);
  });
  $("#seg-counter").textContent = session.segments.length
    ? `${currentIndex + 1} / ${session.segments.length}`
    : "0 / 0";
}

// 居中当前段落；切段时旧段向上淡出，新段自下浮现
function renderNow() {
  const stack = $("#now-stack");
  if (!stack || !session || !session.segments) return;
  const cur = session.segments[currentIndex];
  const card = $("#now-card");
  if (!cur) { if (card) card.style.opacity = "0"; return; }
  if (currentIndex === lastNowIndex) return;

  if (card && lastNowIndex !== -1) {
    const leaving = card.cloneNode(true);
    leaving.removeAttribute("id");
    leaving.classList.remove("enter");
    leaving.classList.add("leave");
    stack.appendChild(leaving);
    leaving.addEventListener("animationend", () => leaving.remove());
  }

  const badge = $("#now-badge");
  badge.className = "badge " + cur.speaker;
  badge.textContent = SPEAKER_LABEL[cur.speaker] || cur.speaker;
  $("#now-playing").textContent = cur.text;
  teleReset();

  card.classList.remove("enter");
  void card.offsetWidth; // 触发重排以重启动画
  card.classList.add("enter");
  lastNowIndex = currentIndex;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function setStatus(t) {
  $("#status").textContent = t;
}

// ---------------- 拖拽 ----------------

const dz = $("#dropzone");
dz.addEventListener("dragover", (e) => {
  e.preventDefault();
  dz.classList.add("drag");
});
dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
dz.addEventListener("drop", (e) => {
  e.preventDefault();
  dz.classList.remove("drag");
  if (e.dataTransfer.files.length) {
    $("#file").files = e.dataTransfer.files;
  }
});

// ---------------- 绑定 ----------------

$("#gen-btn").addEventListener("click", generate);
$("#play-btn").addEventListener("click", togglePlay);
$("#prev-btn").addEventListener("click", () => playIndex(currentIndex - 1));
$("#next-btn").addEventListener("click", () => playIndex(currentIndex + 1));
$("#ask-btn").addEventListener("click", () => interrupt("ask"));
$("#steer-btn").addEventListener("click", () => interrupt("steer"));
$("#interrupt-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") interrupt("ask");
});
$("#url").addEventListener("keydown", (e) => {
  if (e.key === "Enter") generate();
});

$("#new-btn").addEventListener("click", newPodcast);

// 启动时加载往期播客
loadLibrary();

// 底部工具历史：折叠 / 展开
function toggleHistory() {
  $("#thinking-steps").classList.toggle("collapsed");
  $("#thinking-toggle").classList.toggle("collapsed");
}
$("#thinking-toggle").addEventListener("click", (e) => { e.stopPropagation(); toggleHistory(); });
$("#thinking-panel .thinking-header").addEventListener("click", (e) => {
  if (e.target.id !== "thinking-toggle") toggleHistory();
});

// 大段文字「展开全部 / 收起」委托
$("#thinking-steps").addEventListener("click", (e) => {
  if (!e.target.classList.contains("kv-more")) return;
  const row = e.target.closest(".kv-row");
  const val = row.querySelector(".kv-val.block");
  if (!val) return;
  const expanded = val.classList.toggle("expanded");
  if (expanded) {
    val.textContent = decodeURIComponent(val.dataset.full || "");
    e.target.textContent = "收起";
  } else {
    const full = decodeURIComponent(val.dataset.full || "");
    val.textContent = full.slice(0, KV_PREVIEW_MAX) + (full.length > KV_PREVIEW_MAX ? "…" : "");
    e.target.textContent = "展开全部";
  }
});
