#!/usr/bin/env python3
"""
扫描 pmp_notes 下 MD/PDF，构建 pmp_knowledge_index.json。

索引条目含：知识点名称、文件位置、关键词标签。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import NOTES_DIR, PROJECT_ROOT
except ModuleNotFoundError:
    from config import NOTES_DIR, PROJECT_ROOT

INDEX_PATH = PROJECT_ROOT / "pmp_knowledge_index.json"
PATTERN_PDF_NAME = "PMP考试情景分析题的三十六种套路.pdf"

# 深度检索优先 PDF（文件名子串）
PRIORITY_PDF_NAMES = [
    "PMBOK指南第7版-中文版.pdf",
    PATTERN_PDF_NAME,
    "敏捷实践指南中文版.pdf",
    "过程组实践指南中文版.pdf",
    "学霸PMP笔记.pdf",
]

_H1_MD = re.compile(r"^#\s+(.+)$")
_H2_MD = re.compile(r"^##\s+(.+)$")
_H3_MD = re.compile(r"^###\s+(.+)$")
_H4_MD = re.compile(r"^####\s+(.+)$")
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# PDF 标题：中文序号 / 数字章节
_PDF_SECTION = re.compile(
    r"^(?:第?[一二三四五六七八九十百]+[、．.]\s*.+|"
    r"\d+(?:\.\d+){1,3}\s+\S.+)$",
)
_PATTERN_SECTION = re.compile(r"^([一二三四五六七八九十百]+)[、．.]\s*(.+)$")

# 关键词：领域别名 + 从文本提取
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "整合管理": ["整合", "章程", "变更", "CCB"],
    "范围管理": ["范围", "WBS", "需求"],
    "进度管理": ["进度", "关键路径", "工期"],
    "成本管理": ["成本", "预算", "挣值", "EVM", "CPI", "SPI", "BAC"],
    "质量管理": ["质量", "审计", "QC", "QA"],
    "资源管理": ["资源", "团队", "RACI"],
    "沟通管理": ["沟通", "报告"],
    "风险管理": ["风险", "威胁", "机会", "应急"],
    "采购管理": ["采购", "合同", "投标人"],
    "干系人管理": ["干系人", "相关方"],
    "敏捷": ["敏捷", "Scrum", "迭代", "燃尽"],
    "商业环境": ["商业", "合规", "效益"],
    "领导力": ["冲突", "激励", "教练", "塔克曼"],
}

_ACRONYM = re.compile(r"\b[A-Z]{2,6}\b")
_CJK = re.compile(r"[\u4e00-\u9fff]{2,8}")


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"')
    return meta, text[m.end() :]


def _guess_domain(name: str, content: str, tags: list[str]) -> str:
    blob = f"{name} {' '.join(tags)} {content[:200]}"
    best, score = "综合", 0
    for domain, kws in _DOMAIN_KEYWORDS.items():
        s = sum(1 for k in kws if k.lower() in blob.lower() or k in blob)
        if s > score:
            score, best = s, domain
    return best


def _extract_keywords(name: str, content: str, tags: list[str] | None = None) -> list[str]:
    kws: set[str] = set(tags or [])
    kws.add(name.strip())
    for m in _ACRONYM.findall(name + " " + content[:300]):
        kws.add(m)
    for m in _CJK.findall(name):
        if len(m) >= 2:
            kws.add(m)
    for domain, aliases in _DOMAIN_KEYWORDS.items():
        if any(a in name or a in content[:200] for a in aliases):
            kws.add(domain)
    # 去掉过短
    return sorted(x for x in kws if x and len(x) >= 2)[:20]


def _make_id(prefix: str, name: str, idx: int) -> str:
    slug = re.sub(r"\W+", "-", name)[:40].strip("-") or "item"
    return f"{prefix}:{idx}:{slug}"


def scan_markdown(path: Path, entries: list[dict]) -> None:
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    tags = [t.strip() for t in (meta.get("tags") or "").split(",") if t.strip()]
    lines = body.splitlines()
    rel = _rel(path)

    stack: list[tuple[int, str, int]] = []  # level, name, line_start (0-based)
    counters = [0]

    def add_entry(lvl: int, name: str, start: int, end: int) -> None:
        if not name.strip() or end <= start:
            return
        content = "\n".join(lines[start:end])
        counters[0] += 1
        parent = stack[-2][1] if len(stack) >= 2 else None
        entries.append({
            "id": _make_id("md", name, counters[0]),
            "name": name.strip(),
            "heading_level": lvl,
            "parent_name": parent,
            "file": rel,
            "file_type": "md",
            "line_start": start + 1,
            "line_end": end,
            "page_start": None,
            "page_end": None,
            "keywords": _extract_keywords(name, content, tags),
            "domain": _guess_domain(name, content, tags),
            "is_pattern": False,
        })

    heading_spans: list[tuple[int, int, int, str]] = []  # start_line, end_line, lvl, name

    for i, line in enumerate(lines):
        for lvl, pat in ((2, _H2_MD), (3, _H3_MD), (4, _H4_MD)):
            m = pat.match(line)
            if m:
                heading_spans.append((i, i, lvl, m.group(1).strip()))
                break

    for idx, (start, _, lvl, name) in enumerate(heading_spans):
        end = heading_spans[idx + 1][0] if idx + 1 < len(heading_spans) else len(lines)
        add_entry(lvl, name, start, end)


def _strip_watermark(text: str) -> str:
    return re.sub(r"[料资部内育教迹骐]\s*", "", text)


def scan_pattern_pdf(path: Path, entries: list[dict]) -> None:
    try:
        import pdfplumber
    except ImportError:
        return

    rel = _rel(path)
    all_lines: list[str] = []
    page_map: list[int] = []  # line index -> page num
    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            raw = page.extract_text() or ""
            text = _strip_watermark(raw)
            for ln in text.splitlines():
                s = ln.strip()
                if s:
                    all_lines.append(s)
                    page_map.append(page_num)

    counters = [0]
    current_name: str | None = None
    current_start_page = 1
    current_lines: list[str] = []
    current_start_idx = 0

    def save(end_idx: int) -> None:
        nonlocal current_name, current_lines, current_start_page, current_start_idx
        if not current_name:
            return
        content = "\n".join(current_lines)
        counters[0] += 1
        pm = _PATTERN_SECTION.match(current_name)
        cn_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
                  "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
                  "十三": 13, "十四": 14, "十五": 15, "十六": 16}
        pnum = cn_map.get(pm.group(1), counters[0]) if pm else counters[0]
        end_page = page_map[end_idx - 1] if end_idx > 0 and end_idx <= len(page_map) else current_start_page
        entries.append({
            "id": _make_id("pattern", current_name, counters[0]),
            "name": current_name,
            "heading_level": 1,
            "parent_name": "PMP考试情景分析题三十六套路",
            "file": rel,
            "file_type": "pdf",
            "line_start": current_start_idx,
            "line_end": end_idx,
            "page_start": current_start_page,
            "page_end": end_page,
            "keywords": _extract_keywords(current_name, content),
            "domain": _guess_domain(current_name, content, []),
            "is_pattern": True,
            "pattern_number": pnum,
        })
        current_name = None
        current_lines = []

    for idx, ln in enumerate(all_lines):
        pm = _PATTERN_SECTION.match(ln)
        if pm and len(pm.group(2)) >= 3:
            save(idx)
            current_name = ln
            current_start_idx = idx
            current_start_page = page_map[idx]
            current_lines = []
        elif current_name:
            current_lines.append(ln)
    save(len(all_lines))


def scan_general_pdf(path: Path, entries: list[dict]) -> None:
    try:
        import pdfplumber
    except ImportError:
        return

    rel = _rel(path)
    counters = [0]
    skip_names = {"每日一练", "答案解析", "模考"}

    if any(s in path.name for s in skip_names):
        return

    with pdfplumber.open(path) as pdf:
        current_name: str | None = None
        current_lines: list[str] = []
        page_start = 1

        for page_num, page in enumerate(pdf.pages, 1):
            raw = page.extract_text() or ""
            text = _strip_watermark(raw)
            if not text.strip():
                continue
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            header = lines[0] if lines else f"第{page_num}页"

            if _PDF_SECTION.match(header) and len(header) <= 80:
                if current_name and current_lines:
                    counters[0] += 1
                    content = "\n".join(current_lines)
                    entries.append({
                        "id": _make_id("pdf", current_name, counters[0]),
                        "name": current_name[:100],
                        "heading_level": 2,
                        "parent_name": path.stem,
                        "file": rel,
                        "file_type": "pdf",
                        "line_start": None,
                        "line_end": None,
                        "page_start": page_start,
                        "page_end": page_num - 1,
                        "keywords": _extract_keywords(current_name, content),
                        "domain": _guess_domain(current_name, content, []),
                        "is_pattern": False,
                    })
                current_name = header
                current_lines = lines[1:]
                page_start = page_num
            else:
                if not current_name:
                    current_name = f"{path.stem} · 第{page_num}页"
                    page_start = page_num
                current_lines.extend(lines)

        if current_name and current_lines:
            counters[0] += 1
            content = "\n".join(current_lines)
            entries.append({
                "id": _make_id("pdf", current_name, counters[0]),
                "name": current_name[:100],
                "heading_level": 2,
                "parent_name": path.stem,
                "file": rel,
                "file_type": "pdf",
                "line_start": None,
                "line_end": None,
                "page_start": page_start,
                "page_end": len(pdf.pages),
                "keywords": _extract_keywords(current_name, content),
                "domain": _guess_domain(current_name, content, []),
                "is_pattern": False,
            })


def build_index(notes_dir: Path | None = None) -> dict[str, Any]:
    root = notes_dir or NOTES_DIR
    entries: list[dict] = []
    files_scanned: list[str] = []

    for md in sorted(root.rglob("*.md")):
        if md.name.startswith("_") or "wechat-system" in md.name:
            continue
        try:
            scan_markdown(md, entries)
            files_scanned.append(_rel(md))
        except OSError as e:
            entries.append({"_error": str(md), "detail": str(e)})

    priority_counters = [0]

    for pdf in sorted(root.rglob("*.pdf")):
        try:
            if PATTERN_PDF_NAME in pdf.name:
                scan_pattern_pdf(pdf, entries)
            elif any(p in pdf.name for p in PRIORITY_PDF_NAMES):
                from pmp_athena.knowledge_pdf_search import scan_priority_pdf
                rel = _rel(pdf)
                if not scan_priority_pdf(pdf, entries, rel, priority_counters):
                    scan_general_pdf(pdf, entries)
            else:
                scan_general_pdf(pdf, entries)
            files_scanned.append(_rel(pdf))
        except OSError as e:
            entries.append({"_error": str(pdf), "detail": str(e)})

    # 过滤 error 占位
    clean = [e for e in entries if "_error" not in e]
    return {
        "version": 1,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT).replace("\\", "/"),
        "notes_dir": _rel(root),
        "pattern_pdf": f"pmp_notes/{PATTERN_PDF_NAME}",
        "files_scanned": files_scanned,
        "entry_count": len(clean),
        "entries": clean,
    }


def save_index(data: dict[str, Any], path: Path | None = None) -> Path:
    out = path or INDEX_PATH
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="构建 PMP 知识点索引")
    parser.add_argument("--output", "-o", default=str(INDEX_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    data = build_index()
    path = save_index(data, Path(args.output))
    if args.json:
        print(json.dumps({"status": "ok", "path": str(path), "entries": data["entry_count"]}, ensure_ascii=False))
    else:
        print(f"✅ 索引已写入 {path}（{data['entry_count']} 条知识点）")


if __name__ == "__main__":
    main()
