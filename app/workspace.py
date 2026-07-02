from __future__ import annotations

import hashlib
import re
from typing import Optional

from app.schemas import Segment

MAX_READ = 20000
MAX_GREP = 30
SCRIPT_PATH = "script.md"
SOURCE_PATH = "source.txt"


def segment_id(speaker: str, text: str) -> str:
    """文本不变则 id 不变 → 音频缓存命中；改写则重新合成。"""
    h = hashlib.sha1(f"{speaker}\n{text}".encode("utf-8")).hexdigest()
    return h[:10]


def parse_script_md(md: str) -> tuple[str, list[Segment]]:
    """把脚本 Markdown 解析为 (title, segments)。

    格式：
        # 播客标题（可选首行）
        ## host | 小标题 | warm and curious
        口播内容…
    speaker 必填，title/style 可省。
    """
    if not md:
        return "", []

    title = ""
    lines = md.splitlines()
    # 跳过空行，识别首行 # 标题
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx < len(lines) and lines[idx].lstrip().startswith("# ") and not lines[idx].lstrip().startswith("## "):
        title = lines[idx].lstrip()[2:].strip()
        idx += 1

    segments: list[Segment] = []
    cur_header: Optional[tuple[str, str, str]] = None  # (speaker, title, style)
    cur_body: list[str] = []

    def flush():
        if cur_header is None:
            return
        speaker, seg_title, style = cur_header
        text = "\n".join(cur_body).strip()
        if text:
            segments.append(
                Segment(
                    id=segment_id(speaker, text),
                    speaker=speaker if speaker in ("host", "cohost") else "host",
                    title=seg_title,
                    text=text,
                    style=style or None,
                )
            )

    for line in lines[idx:]:
        if line.lstrip().startswith("## "):
            flush()
            cur_body = []
            cur_header = _parse_header(line.lstrip()[3:].strip())
        else:
            cur_body.append(line)
    flush()
    return title, segments


def _parse_header(header: str) -> tuple[str, str, str]:
    parts = [p.strip() for p in header.split("|")]
    speaker = parts[0] if parts else "host"
    title = parts[1] if len(parts) > 1 else ""
    style = parts[2] if len(parts) > 2 else ""
    return speaker, title, style


class Workspace:
    """内存文件工作区。通用文件工具直接操作它。"""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    # ---- 文件操作（工具实现，返回字符串作为观察结果）----

    def list_files(self) -> str:
        if not self.files:
            return "(空)"
        return "\n".join(sorted(self.files.keys()))

    def read_file(self, path: str) -> str:
        if path not in self.files:
            return f"错误：文件不存在: {path}（可用：{self.list_files()}）"
        content = self.files[path]
        if len(content) > MAX_READ:
            return content[:MAX_READ] + f"\n…[已截断，共 {len(content)} 字符]"
        return content

    def write_file(self, path: str, content: str) -> str:
        self.files[path] = content
        return f"已写入 {len(content)} 字符到 {path}"

    def edit_file(self, path: str, old_string: str, new_string: str) -> str:
        if path not in self.files:
            return f"错误：文件不存在: {path}"
        content = self.files[path]
        if not old_string:
            return "错误：old_string 不能为空"
        count = content.count(old_string)
        if count == 0:
            return f"错误：未找到 old_string。请先用 read_file 查看 {path} 的实际内容。"
        if count > 1:
            return f"错误：old_string 出现 {count} 次，不唯一。请提供更长、更唯一的片段。"
        self.files[path] = content.replace(old_string, new_string, 1)
        return f"已在 {path} 中完成 1 处替换"

    def grep(self, pattern: str, path: Optional[str] = None) -> str:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"错误：非法正则: {e}"
        paths = [path] if path and path in self.files else list(self.files.keys())
        results: list[str] = []
        total = 0
        for p in sorted(paths):
            content = self.files.get(p, "")
            for lineno, line in enumerate(content.splitlines(), 1):
                if rx.search(line):
                    results.append(f"{p}:{lineno}: {line}")
                    total += 1
                    if total >= MAX_GREP:
                        results.append(f"…[已达上限 {MAX_GREP} 条]")
                        return "\n".join(results)
        if not results:
            return "(无匹配)"
        return "\n".join(results)

    # ---- 便捷 ----

    def script(self) -> str:
        return self.files.get(SCRIPT_PATH, "")
