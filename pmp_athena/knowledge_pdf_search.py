#!/usr/bin/env python3
"""
PDF 深度检索：优先 PDF 章节索引 + 运行时内容提取与来源标注。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import NOTES_DIR, PROJECT_ROOT
except ModuleNotFoundError:
    from config import NOTES_DIR, PROJECT_ROOT

# 深度检索优先 PDF（文件名子串匹配）
PRIORITY_PDF_NAMES: list[str] = [
    "PMBOK指南第7版-中文版.pdf",
    "PMP考试情景分析题的三十六种套路.pdf",
    "敏捷实践指南中文版.pdf",
    "过程组实践指南中文版.pdf",
    "学霸PMP笔记.pdf",
]

# 中文序号 → 数字（套路 PDF）
_CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
    "十三": 13, "十四": 14, "十五": 15, "十六": 16,
    "十七": 17, "十八": 18, "十九": 19, "二十": 20,
}


def is_priority_pdf(path: Path | str) -> bool:
    name = Path(path).name
    return any(p in name for p in PRIORITY_PDF_NAMES)


def _strip_watermark(text: str) -> str:
    return re.sub(r"[料资部内育教迹骐]\s*", "", text)


def _extract_pdf_toc(path: Path) -> list[dict[str, Any]]:
    """
    尝试从 PDF 书签/目录提取章节。
    失败返回空列表。
    """
    items: list[dict[str, Any]] = []
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        outlines = reader.outline
        if not outlines:
            return []

        def walk(nodes, depth=0):
            for node in nodes:
                if isinstance(node, list):
                    walk(node, depth)
                    continue
                try:
                    title = node.title if hasattr(node, "title") else str(node)
                    page = reader.get_destination_page_number(node) + 1
                    items.append({"title": title.strip(), "page": page, "depth": depth})
                    if hasattr(node, "children") and node.children:
                        walk(node.children, depth + 1)
                except Exception:
                    continue

        walk(outlines)
    except Exception:
        pass
    return items


def _extract_text_pypdf(path: Path, page_start: int, page_end: int) -> str:
    """pypdf 降级读取（中文乱码时尝试）。"""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        parts: list[str] = []
        pe = min(page_end, len(reader.pages))
        for p in range(page_start, pe + 1):
            try:
                t = reader.pages[p - 1].extract_text() or ""
                t = _strip_watermark(t)
                if t.strip():
                    parts.append(t.strip())
            except Exception:
                continue
        return "\n\n".join(parts)
    except Exception:
        return ""


def extract_pdf_pages(path: Path, page_start: int, page_end: int) -> str:
    """优先 pdfplumber，失败降级 pypdf。"""
    text = ""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            parts: list[str] = []
            pe = min(page_end, len(pdf.pages))
            for p in range(page_start, pe + 1):
                t = pdf.pages[p - 1].extract_text() or ""
                t = _strip_watermark(t)
                if t.strip():
                    parts.append(t.strip())
            text = "\n\n".join(parts)
    except Exception:
        pass

    if not text or len(text.strip()) < 20:
        text = _extract_text_pypdf(path, page_start, page_end)
    return text


def scan_priority_pdf(path: Path, entries: list[dict], rel: str, counters: list[int]) -> bool:
    """
    对优先 PDF 建章节索引。
    返回 True 表示已成功处理（含文件名降级索引）。
    """
    from pmp_athena.knowledge_index_builder import (
        _extract_keywords,
        _guess_domain,
        _make_id,
    )

    toc = _extract_pdf_toc(path)
    file_ref = {"file": rel, "pages": "待人工补充" if not toc else f"TOC {len(toc)} 章"}

    if toc:
        for item in toc:
            title = item["title"]
            if len(title) < 2:
                continue
            page = item["page"]
            counters[0] += 1
            entries.append({
                "id": _make_id("pdf", title, counters[0]),
                "name": title[:100],
                "heading_level": 2,
                "parent_name": path.stem,
                "file": rel,
                "file_type": "pdf",
                "line_start": None,
                "line_end": None,
                "page_start": page,
                "page_end": page,
                "keywords": _extract_keywords(title, title),
                "domain": _guess_domain(title, title, []),
                "is_pattern": False,
                "is_priority_pdf": True,
                "file_references": [{"source": path.name, "page": page}],
            })
        return True

    # 无目录：尝试 pdfplumber 按页首标题，或文件名索引
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                raise ValueError("empty pdf")
            # 至少建一条文件名级索引
            counters[0] += 1
            entries.append({
                "id": _make_id("pdf", path.stem, counters[0]),
                "name": path.stem,
                "heading_level": 1,
                "parent_name": None,
                "file": rel,
                "file_type": "pdf",
                "line_start": None,
                "line_end": None,
                "page_start": 1,
                "page_end": len(pdf.pages),
                "keywords": _extract_keywords(path.stem, path.stem),
                "domain": _guess_domain(path.stem, path.stem, []),
                "is_pattern": False,
                "is_priority_pdf": True,
                "file_references": [file_ref],
            })
        return True
    except Exception:
        counters[0] += 1
        entries.append({
            "id": _make_id("pdf", path.stem, counters[0]),
            "name": path.stem,
            "heading_level": 1,
            "parent_name": None,
            "file": rel,
            "file_type": "pdf",
            "line_start": None,
            "line_end": None,
            "page_start": None,
            "page_end": None,
            "keywords": [path.stem],
            "domain": "综合",
            "is_pattern": False,
            "is_priority_pdf": True,
            "file_references": [file_ref],
        })
        return True


def format_pdf_source(entry: dict) -> str:
    """来源标注行。"""
    fname = Path(entry.get("file") or "").name
    ps = entry.get("page_start")
    pe = entry.get("page_end")
    if ps and pe and ps != pe:
        return f"📍 来源：{fname} 第{ps}-{pe}页"
    if ps:
        return f"📍 来源：{fname} 第{ps}页"
    refs = entry.get("file_references") or []
    if refs and refs[0].get("pages"):
        return f"📍 来源：{fname}（{refs[0]['pages']}）"
    return f"📍 来源：{fname}"


def format_l1_pdf_header(entry: dict) -> str:
    fname = Path(entry.get("file") or "").name
    return f"📚 {entry.get('name', '知识点')} · 来自 {fname}"


def format_full_content_hint() -> str:
    return "💡 回复「全文」获取更多内容"
