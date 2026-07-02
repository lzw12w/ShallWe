from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from typing import Optional

from app.agent import PodcastAgent
from app.config import settings
from app.schemas import Session, Segment
from app.workspace import Workspace, parse_script_md, SCRIPT_PATH, SOURCE_PATH
from app import store

_sessions: dict[str, "PodcastSession"] = {}


class PodcastSession:
    """播客级 session：拥有工作区、持久 agent、派生脚本视图、播放状态。"""

    def __init__(self, source_text: str) -> None:
        self.id = str(uuid.uuid4())[:8]
        self.workspace = Workspace()
        self.workspace.files["source.txt"] = source_text
        self.agent = PodcastAgent(self.workspace)
        self.current_index = 0
        self.generated = False
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    @property
    def view(self) -> Session:
        title, segments = parse_script_md(self.workspace.script())
        return Session(
            id=self.id,
            title=title,
            segments=segments,
            current_index=self.current_index,
        )

    def view_dict(self) -> dict:
        return self.view.model_dump()

    def segment_ids(self) -> list[str]:
        return [s.id for s in self.view.segments]

    def first_new_index_after(self, baseline: list[str], from_index: int) -> Optional[int]:
        base = set(baseline)
        for i in range(from_index, len(self.view.segments)):
            if self.view.segments[i].id not in base:
                return i
        return None

    def get_segment(self, seg_id: str) -> Optional[Segment]:
        for s in self.view.segments:
            if s.id == seg_id:
                return s
        return None

    def persist(self) -> None:
        """把原文、脚本、元数据落盘到本地 data 目录。"""
        v = self.view
        store.save_text_files(
            self.id,
            self.workspace.files.get(SOURCE_PATH, ""),
            self.workspace.script(),
        )
        store.save_meta(
            self.id, v.title,
            [seg.model_dump() for seg in v.segments],
            self.current_index,
        )


def create_session(source_text: str) -> PodcastSession:
    sess = PodcastSession(source_text)
    _sessions[sess.id] = sess
    return sess


def get_session(sid: str) -> Optional[PodcastSession]:
    sess = _sessions.get(sid)
    if sess is not None:
        return sess
    return _restore_from_disk(sid)


def _restore_from_disk(sid: str) -> Optional[PodcastSession]:
    """进程重启或会话被淘汰后，从本地磁盘重建可回放的会话。"""
    meta = store.load_meta(sid)
    if not meta:
        return None
    source = store.load_source(sid) or ""
    script = store.load_script(sid) or ""
    sess = PodcastSession.__new__(PodcastSession)
    sess.id = sid
    sess.workspace = Workspace()
    sess.workspace.files[SOURCE_PATH] = source
    sess.workspace.files[SCRIPT_PATH] = script
    sess.agent = PodcastAgent(sess.workspace)
    sess.current_index = int(meta.get("current_index", 0) or 0)
    sess.generated = True
    sess._lock = asyncio.Lock()
    _sessions[sid] = sess
    return sess


def list_saved() -> list:
    return store.list_podcasts()


# ---- 音频 LRU 缓存 ----

class _LRUAudioCache:
    def __init__(self, maxsize: int = 200):
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[bytes]:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def set(self, key: str, value: bytes) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
        self._cache[key] = value


_audio_cache = _LRUAudioCache(maxsize=settings.audio_cache_max)


def cache_audio(seg_id: str, data: bytes) -> None:
    _audio_cache.set(seg_id, data)


def get_cached_audio(seg_id: str) -> Optional[bytes]:
    return _audio_cache.get(seg_id)
