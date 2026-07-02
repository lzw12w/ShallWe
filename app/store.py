from __future__ import annotations

import json
import os
import time
from typing import Optional

from app.config import settings

_AUDIO_DIR = "audio"
_META = "meta.json"
_SCRIPT = "script.md"
_SOURCE = "source.txt"


def _root() -> str:
    return os.path.abspath(settings.data_dir)


def podcast_dir(sid: str) -> str:
    return os.path.join(_root(), sid)


def ensure_root() -> None:
    os.makedirs(_root(), exist_ok=True)


def audio_ext() -> str:
    # 与 settings.audio_media_type() 对齐的文件后缀
    mt = settings.audio_media_type()
    if mt == "audio/wav":
        return "wav"
    if mt == "audio/mpeg":
        return "mp3"
    return mt.split("/")[-1]


def _audio_path(sid: str, seg_id: str) -> str:
    return os.path.join(podcast_dir(sid), _AUDIO_DIR, seg_id + "." + audio_ext())


# ---- 写 ----

def save_text_files(sid: str, source_text: str, script_md: str) -> None:
    d = podcast_dir(sid)
    os.makedirs(os.path.join(d, _AUDIO_DIR), exist_ok=True)
    with open(os.path.join(d, _SOURCE), "w", encoding="utf-8") as f:
        f.write(source_text or "")
    with open(os.path.join(d, _SCRIPT), "w", encoding="utf-8") as f:
        f.write(script_md or "")


def save_meta(sid: str, title: str, segments: list, current_index: int = 0,
              created_at: Optional[float] = None) -> None:
    d = podcast_dir(sid)
    os.makedirs(d, exist_ok=True)
    meta_path = os.path.join(d, _META)
    if created_at is None:
        created_at = _existing_created_at(meta_path) or time.time()
    meta = {
        "id": sid,
        "title": title or "未命名播客",
        "created_at": created_at,
        "updated_at": time.time(),
        "num_segments": len(segments),
        "segments": segments,
        "current_index": current_index,
        "audio_ext": audio_ext(),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _existing_created_at(meta_path: str) -> Optional[float]:
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f).get("created_at")
    except Exception:
        return None


def save_audio(sid: str, seg_id: str, data: bytes) -> None:
    d = os.path.join(podcast_dir(sid), _AUDIO_DIR)
    os.makedirs(d, exist_ok=True)
    with open(_audio_path(sid, seg_id), "wb") as f:
        f.write(data)


# ---- 读 ----

def load_audio(sid: str, seg_id: str) -> Optional[bytes]:
    p = _audio_path(sid, seg_id)
    if os.path.isfile(p):
        with open(p, "rb") as f:
            return f.read()
    return None


def load_source(sid: str) -> Optional[str]:
    p = os.path.join(podcast_dir(sid), _SOURCE)
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    return None


def load_script(sid: str) -> Optional[str]:
    p = os.path.join(podcast_dir(sid), _SCRIPT)
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    return None


def load_meta(sid: str) -> Optional[dict]:
    p = os.path.join(podcast_dir(sid), _META)
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def list_podcasts() -> list:
    # 返回按更新时间倒序的元数据摘要
    ensure_root()
    out = []
    for name in os.listdir(_root()):
        d = os.path.join(_root(), name)
        if not os.path.isdir(d):
            continue
        meta = load_meta(name)
        if not meta:
            continue
        out.append({
            "id": meta.get("id", name),
            "title": meta.get("title", "未命名播客"),
            "created_at": meta.get("created_at", 0),
            "updated_at": meta.get("updated_at", 0),
            "num_segments": meta.get("num_segments", 0),
        })
    out.sort(key=lambda m: m.get("updated_at", 0), reverse=True)
    return out


def all_session_ids() -> list:
    ensure_root()
    ids = []
    for name in os.listdir(_root()):
        if os.path.isfile(os.path.join(_root(), name, _META)):
            ids.append(name)
    return ids
