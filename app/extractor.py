from __future__ import annotations

import io
from typing import Optional

import httpx
import trafilatura


def extract_from_bytes(content: bytes, filename: str) -> str:
    """根据文件后缀提取正文文本。文件解析为同步 CPU 操作，直接返回。"""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return _extract_pdf(content)
    if name.endswith(".docx"):
        return _extract_docx(content)
    # txt / md / 未知：直接按文本解码
    return content.decode("utf-8", errors="ignore")


def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def _extract_docx(content: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs).strip()


async def extract_from_url(url: str) -> str:
    """抓取 URL 并用 trafilatura 抽取正文。"""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PodcastAgent/1.0)"}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        html = resp.text
    text = trafilatura.extract(html, include_comments=False, include_tables=True)
    return text or ""


def truncate(text: str, limit: int = 8000) -> str:
    return text if len(text) <= limit else text[:limit]
