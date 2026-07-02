from __future__ import annotations

import asyncio

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app import extractor
from app import session as session_store
from app.agent import PodcastAgent
from app.config import settings
from app.providers.tts.registry import get_tts
from app import store

app = FastAPI(title="Podcast Agent")

_SNIPPET_LEN = 50


def _snippet(text: str) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:_SNIPPET_LEN]


# ---------------- REST ----------------

@app.post("/api/sessions")
async def create_session(
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
):
    """上传文件 或 粘贴链接 → 提取正文 → 创建 session（不生成脚本）。"""
    if file is not None and file.filename:
        content = await file.read()
        text = extractor.extract_from_bytes(content, file.filename)
    elif url:
        try:
            text = await extractor.extract_from_url(url)
        except Exception as e:
            raise HTTPException(400, f"抓取链接失败：{e}")
    else:
        raise HTTPException(400, "请提供文件或链接")

    text = (text or "").strip()
    if not text:
        raise HTTPException(400, "未能从输入中提取到任何文本")

    # 限制送入 LLM 的素材长度
    text = extractor.truncate(text, 12000)

    sess = session_store.create_session(text)
    return {"id": sess.id, "title": "", "segments": [], "current_index": 0}


@app.get("/api/podcasts")
async def list_podcasts():
    """往期播客列表（本地已保存的）。"""
    return {"podcasts": session_store.list_saved()}


@app.get("/api/sessions/{sid}")
async def get_session(sid: str):
    sess = session_store.get_session(sid)
    if not sess:
        raise HTTPException(404, "session not found")
    return sess.view_dict()


@app.get("/api/sessions/{sid}/segments/{seg_id}/audio")
async def segment_audio(sid: str, seg_id: str, request: Request):
    sess = session_store.get_session(sid)
    if not sess:
        raise HTTPException(404, "session not found")
    seg = sess.get_segment(seg_id)
    if not seg:
        raise HTTPException(404, "segment not found")

    data = session_store.get_cached_audio(seg_id)
    if data is None:
        data = store.load_audio(sid, seg_id)
        if data is not None:
            session_store.cache_audio(seg_id, data)
    if data is None:
        tts = get_tts()
        voice = settings.voice_for(seg.speaker)
        try:
            data = await tts.synthesize(seg.text, voice=voice, style=seg.style)
        except Exception as e:
            raise HTTPException(502, f"TTS 合成失败：{e}")
        session_store.cache_audio(seg_id, data)
        store.save_audio(sid, seg_id, data)

    media_type = settings.audio_media_type()
    total = len(data)
    range_header = request.headers.get("range") or request.headers.get("Range")

    # 无 Range:整段返回,但声明支持字节范围,浏览器才允许 seek
    if not range_header:
        return Response(
            content=data,
            media_type=media_type,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(total)},
        )

    # 解析 "bytes=start-end"
    start, end = 0, total - 1
    try:
        unit, _, rng = range_header.partition("=")
        if unit.strip().lower() == "bytes" and rng:
            s_str, _, e_str = rng.partition("-")
            if s_str.strip():
                start = int(s_str)
            if e_str.strip():
                end = int(e_str)
            if s_str.strip() == "" and e_str.strip():
                # 形如 "-500":最后 500 字节
                start = max(0, total - int(e_str))
                end = total - 1
    except (ValueError, TypeError):
        start, end = 0, total - 1

    if start > end or start >= total:
        return Response(
            status_code=416,
            media_type=media_type,
            headers={"Content-Range": f"bytes */{total}", "Accept-Ranges": "bytes"},
        )
    end = min(end, total - 1)
    chunk = data[start : end + 1]
    return Response(
        content=chunk,
        status_code=206,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Content-Length": str(len(chunk)),
        },
    )


# ---------------- WebSocket ----------------

async def _send(ws: WebSocket, obj: dict) -> None:
    await ws.send_json(obj)


async def _prefetch_audio(sess, current_idx: int) -> None:
    """后台预合成下一段音频。"""
    segs = sess.view.segments
    next_idx = current_idx + 1
    if next_idx >= len(segs):
        return
    seg = segs[next_idx]
    if session_store.get_cached_audio(seg.id) is not None:
        return
    tts = get_tts()
    voice = settings.voice_for(seg.speaker)
    try:
        data = await tts.synthesize(seg.text, voice=voice, style=seg.style)
        session_store.cache_audio(seg.id, data)
    except Exception:
        pass  # prefetch 失败不影响主流程


async def _run_generate(ws: WebSocket, sess) -> None:
    """首次生成播客脚本（WS 驱动，实时推送进度）。"""
    if sess.generated:
        await _send(ws, {"event": "script", "session": sess.view_dict(),
                         "current_index": 0, "play_index": 0})
        return

    await _send(ws, {"event": "thinking", "message": "正在生成播客脚本…"})
    async with sess.lock:
        if sess.generated:  # double-check
            await _send(ws, {"event": "script", "session": sess.view_dict(),
                             "current_index": 0, "play_index": 0})
            return
        try:
            async for ev in sess.agent.step(
                PodcastAgent.generate_prompt(settings.podcast_num_segments)
            ):
                if ev["event"] == "tool":
                    await _send(ws, {"event": "tool", "name": ev["name"],
                                     "message": ev.get("message", ev["name"]),
                                     "arguments": ev.get("arguments", "")})
                elif ev["event"] == "tool_result":
                    await _send(ws, {"event": "tool_result", "name": ev.get("name", ""),
                                     "result": ev.get("result", "")})
        except Exception as e:
            await _send(ws, {"event": "error", "message": f"脚本生成失败：{e}"})
            return

        if not sess.view.segments:
            await _send(ws, {"event": "error", "message": "脚本生成失败：agent 未产出有效脚本"})
            return

        sess.generated = True
        sess.persist()

    await _send(ws, {"event": "script", "session": sess.view_dict(),
                     "current_index": 0, "play_index": 0})
    # 预加载第一段音频
    asyncio.create_task(_prefetch_audio(sess, -1))


async def _run_agent(ws: WebSocket, sess, payload: str, mode: str) -> None:
    """打断提问 或 引导重点。"""
    await _send(ws, {"event": "thinking",
                     "message": "正在思考你的问题…" if mode == "ask" else "正在调整后续重点…"})

    async with sess.lock:
        k = sess.current_index
        segs_before = sess.view.segments
        snippet = _snippet(segs_before[k].text) if k < len(segs_before) else ""
        seg_no = k + 1
        baseline_ids = [s.id for s in segs_before]

        if mode == "ask":
            prompt = PodcastAgent.ask_prompt(payload, seg_no, snippet)
        else:
            prompt = PodcastAgent.steer_prompt(payload, seg_no, snippet)

        try:
            async for ev in sess.agent.step(prompt):
                if ev["event"] == "tool":
                    await _send(ws, {"event": "tool", "name": ev["name"],
                                     "message": ev.get("message", ev["name"]),
                                     "arguments": ev.get("arguments", "")})
                elif ev["event"] == "tool_result":
                    await _send(ws, {"event": "tool_result", "name": ev.get("name", ""),
                                     "result": ev.get("result", "")})
        except Exception as e:
            await _send(ws, {"event": "error", "message": str(e)})
            return

        # 定位
        if mode == "ask":
            new_idx = sess.first_new_index_after(baseline_ids, k + 1)
            if new_idx is not None:
                sess.current_index = new_idx
            play_index = sess.current_index
        else:
            sess.current_index = k
            play_index = min(k + 1, len(sess.view.segments) - 1) if sess.view.segments else k

    sess.persist()
    await _send(ws, {"event": "script", "session": sess.view_dict(),
                     "current_index": sess.current_index, "play_index": play_index})
    # 预加载下一段
    asyncio.create_task(_prefetch_audio(sess, play_index))


@app.websocket("/ws/{sid}")
async def ws_endpoint(ws: WebSocket, sid: str):
    sess = session_store.get_session(sid)
    if not sess:
        await ws.close(code=4404)
        return
    await ws.accept()
    # 如果已生成，直接推送脚本
    if sess.generated:
        await _send(ws, {"event": "script", "session": sess.view_dict(),
                         "current_index": sess.current_index, "play_index": sess.current_index})
    try:
        while True:
            msg = await ws.receive_json()
            t = msg.get("type")
            if t == "generate":
                await _run_generate(ws, sess)
            elif t == "state":
                try:
                    sess.current_index = int(msg.get("payload", sess.current_index))
                except (TypeError, ValueError):
                    pass
                # prefetch
                asyncio.create_task(_prefetch_audio(sess, sess.current_index))
            elif t == "ask":
                await _run_agent(ws, sess, msg.get("payload", ""), "ask")
            elif t == "steer":
                await _run_agent(ws, sess, msg.get("payload", ""), "steer")
            else:
                await _send(ws, {"event": "ack", "message": f"unknown type: {t}"})
    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await _send(ws, {"event": "error", "message": str(e)})
        except Exception:
            pass


# ---------------- 静态前端 ----------------
class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp


app.mount("/", NoCacheStaticFiles(directory="static", html=True), name="static")
