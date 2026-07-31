#!/usr/bin/env python3
"""
动态知识查询引擎 — 基于 pmp_knowledge_index.json 的分层检索。

retrieve_knowledge(query, level):
  L1 — 5-7 行精华摘要（微信一屏）
  L2 — 完整内容 + 公式/表格/易错点
  L3 — 情景套路（三十六种套路 PDF）
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

try:
    from pmp_athena.config import NOTES_DIR, PROJECT_ROOT
except ModuleNotFoundError:
    from config import NOTES_DIR, PROJECT_ROOT

try:
    from pmp_athena.knowledge_error_linkage import (
        append_error_hint_to_l1,
        find_errors_for_topic,
        format_error_detail_list,
    )
    from pmp_athena.knowledge_fuzzy_match import (
        FuzzyMatchResult,
        format_candidate_list,
        format_recognition_header,
        fuzzy_match_query,
    )
    from pmp_athena.knowledge_pdf_search import (
        format_full_content_hint,
        format_l1_pdf_header,
        format_pdf_source,
        is_priority_pdf,
    )
except ModuleNotFoundError:
    from knowledge_error_linkage import (
        append_error_hint_to_l1,
        find_errors_for_topic,
        format_error_detail_list,
    )
    from knowledge_fuzzy_match import (
        FuzzyMatchResult,
        format_candidate_list,
        format_recognition_header,
        fuzzy_match_query,
    )
    from knowledge_pdf_search import (
        format_full_content_hint,
        format_l1_pdf_header,
        format_pdf_source,
        is_priority_pdf,
    )

Level = Literal["L1", "L2", "L3"]

INDEX_PATH = PROJECT_ROOT / "pmp_knowledge_index.json"
STATE_PATH = NOTES_DIR / "knowledge_query_state.json"

# 模糊匹配别名
_QUERY_ALIASES: dict[str, list[str]] = {
    "挣值": ["挣值", "EVM", "挣值管理", "CPI", "SPI", "SV", "CV", "BAC"],
    "变更": ["变更", "CCB", "变更控制", "变更请求"],
    "风险": ["风险", "威胁", "机会", "应对"],
    "冲突": ["冲突", "塔克曼", "团队建设"],
    "质量": ["质量", "QA", "QC", "审计"],
    "敏捷": ["敏捷", "Scrum", "迭代", "燃尽"],
    "干系人": ["干系人", "相关方"],
    "WBS": ["WBS", "范围", "工作分解"],
    "采购": ["采购", "合同", "FFP", "工料"],
}

_L1_TRIGGERS = [
    re.compile(r"^(.+?)知识点$"),
    re.compile(r"^知识点\s*(.+)$"),
    re.compile(r"^(.+?)速查$"),
    re.compile(r"^(.+?)的考点$"),
    re.compile(r"^(.+?)有哪些考点$"),
    re.compile(r"^考点\s*(.+)$"),
    re.compile(r"^总结(.+)$"),
    re.compile(r"^(.+?)总结$"),
]

_FOLLOWUP = [
    (re.compile(r"^详细\s*(.*)$"), "L2"),
    (re.compile(r"^展开\s*(.*)$"), "L2"),
    (re.compile(r"^全文\s*(.*)$"), "L2"),
    (re.compile(r"^套路\s*(.*)$"), "L3"),
    (re.compile(r"^情景\s*(.*)$"), "L3"),
    (re.compile(r"^关联\s*(.*)$"), "L1"),  # 关联模式：返回相关条目 L1
]

# 错题详情 / 候选选择
_ERROR_DETAIL = re.compile(r"^错题$")
_CANDIDATE_PICK = re.compile(r"^[1-5]$")


def _load_index() -> dict[str, Any]:
    if not INDEX_PATH.exists():
        return {"entries": []}
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _expand_query(q: str) -> set[str]:
    tokens = {q.strip()}
    for key, aliases in _QUERY_ALIASES.items():
        if key in q or q in key:
            tokens.update(aliases)
        for a in aliases:
            if a.lower() in q.lower() or q.lower() in a.lower():
                tokens.add(key)
                tokens.update(aliases)
    return tokens


def _score_entry(query: str, entry: dict) -> float:
    tokens = _expand_query(query)
    name = entry.get("name") or ""
    kws = entry.get("keywords") or []
    domain = entry.get("domain") or ""
    blob = f"{name} {' '.join(kws)} {domain}"

    best = 0.0
    for t in tokens:
        if not t:
            continue
        if t in name or t in blob:
            best = max(best, 0.95)
        for kw in kws:
            if t in kw or kw in t:
                best = max(best, 0.9)
        best = max(best, SequenceMatcher(None, t.lower(), name.lower()).ratio())

    if entry.get("file_type") == "md":
        best += 0.15
    if entry.get("heading_level") == 2:
        best += 0.08
    if entry.get("is_pattern"):
        best += 0.05
    # 文件名含关键词
    fname = Path(entry.get("file") or "").name.lower()
    for t in tokens:
        tl = t.lower()
        if tl in fname or t in fname:
            best += 0.35
        if t in name or tl in name.lower():
            best += 0.1
    return min(best, 1.0)


def search_entries(
    query: str,
    *,
    pattern_only: bool = False,
    limit: int = 5,
) -> list[dict]:
    data = _load_index()
    entries = data.get("entries") or []
    if not entries:
        return []

    pool = entries
    if pattern_only:
        pool = [e for e in entries if e.get("is_pattern")]

    # 模糊匹配（优先）
    fm = fuzzy_match_query(query, pool if not pattern_only else pool)
    if fm.candidates:
        filtered: list[tuple[float, dict]] = []
        for score, e in fm.candidates:
            if pattern_only and not e.get("is_pattern"):
                continue
            if not pattern_only and e.get("is_pattern") and score < 50:
                continue
            filtered.append((score, e))
        if filtered:
            return [e for _, e in filtered[:limit]]

    # 降级：原有打分逻辑
    scored: list[tuple[float, dict]] = []
    for e in entries:
        if pattern_only and not e.get("is_pattern"):
            continue
        if not pattern_only and e.get("is_pattern") and _score_entry(query, e) < 0.5:
            continue
        s = _score_entry(query, e)
        if s >= 0.35:
            scored.append((s, e))

    scored.sort(
        key=lambda x: (
            -x[0],
            0 if x[1].get("file_type") == "md" else 1,
            0 if x[1].get("heading_level") == 2 else 1,
            x[1].get("name", ""),
        )
    )
    return [e for _, e in scored[:limit]]


def fuzzy_resolve(query: str) -> dict[str, Any]:
    """模糊匹配解析：direct / ambiguous / empty。"""
    data = _load_index()
    entries = [e for e in (data.get("entries") or []) if "_error" not in e]
    fm = fuzzy_match_query(query, entries)
    return {
        "score": fm.score,
        "entry": fm.entry,
        "candidates": fm.candidates,
        "direct": fm.direct,
        "ambiguous": fm.ambiguous,
        "matched_label": fm.matched_label,
    }


def _read_md_section(entry: dict) -> str:
    path = PROJECT_ROOT / entry["file"]
    text = path.read_text(encoding="utf-8")
    _, body = _parse_frontmatter_md(text)
    lines = body.splitlines()
    start = max(0, (entry.get("line_start") or 1) - 1)
    end = min(len(lines), entry.get("line_end") or len(lines))
    return "\n".join(lines[start:end]).strip()


def _parse_frontmatter_md(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}, text
    return {}, text[m.end():]


def _read_pdf_section(entry: dict) -> str:
    try:
        import pdfplumber
    except ImportError:
        return ""

    path = PROJECT_ROOT / entry["file"]
    ps = entry.get("page_start") or 1
    pe = entry.get("page_end") or ps

    # 套路 PDF：按行号切片（更精准）
    if entry.get("is_pattern") and entry.get("line_start") is not None:
        all_lines: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                raw = page.extract_text() or ""
                text = re.sub(r"[料资部内育教迹骐]\s*", "", raw)
                for ln in text.splitlines():
                    s = ln.strip()
                    if s:
                        all_lines.append(s)
        start = entry.get("line_start") or 0
        end = entry.get("line_end") or len(all_lines)
        return "\n".join(all_lines[start:end]).strip()

    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for p in range(ps, min(pe, len(pdf.pages)) + 1):
            t = pdf.pages[p - 1].extract_text() or ""
            t = re.sub(r"[料资部内育教迹骐]\s*", "", t)
            if t.strip():
                parts.append(t.strip())
    text = "\n\n".join(parts)
    # 截断练习题块
    text = re.split(r"\n请问\s*\n", text)[0]
    return text.strip()


def load_entry_content(entry: dict) -> str:
    if entry.get("file_type") == "md":
        return _read_md_section(entry)
    return _read_pdf_section(entry)


def _pick_summary_lines(content: str, max_lines: int = 5) -> list[str]:
    lines: list[str] = []
    for raw in content.splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("|") or s.startswith("---"):
            continue
        if re.match(r"^(tags|domain|date):", s, re.I):
            continue
        if s.startswith("##"):
            s = s.lstrip("#").strip()
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        s = re.sub(r"^[-*•●✅]\s*", "", s)
        s = re.sub(r"^\d+[\.、．]\s+", "", s)
        if len(s) >= 6:
            lines.append(s[:100])
        if len(lines) >= max_lines:
            break
    return lines


def _extract_traps(content: str) -> list[str]:
    traps: list[str] = []
    in_trap = False
    for line in content.splitlines():
        if re.search(r"陷阱|易错|注意|不要选", line):
            in_trap = True
        if in_trap:
            s = line.strip()
            if s and not s.startswith("#"):
                s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
                traps.append(s[:120])
            if len(traps) >= 5:
                break
    return traps


def format_l1(entry: dict, content: str, related: list[dict] | None = None, *, query: str = "") -> str:
    bullets = _pick_summary_lines(content, 5)
    if not bullets:
        bullets = [content[:100] + ("…" if len(content) > 100 else "")]

    # PDF 深度检索来源格式
    if entry.get("file_type") == "pdf" or entry.get("is_priority_pdf"):
        lines = [format_l1_pdf_header(entry), ""]
    else:
        lines = [
            f"📚 {entry.get('name', '知识点')} · 速查",
            f"📂 {entry.get('domain', '综合')} | {Path(entry.get('file', '')).name}",
            "",
        ]

    for i, b in enumerate(bullets[:5], 1):
        lines.append(f"{i}. {b}")

    if related:
        names = [r.get("name", "")[:20] for r in related[:3]]
        lines.extend(["", f"🔗 关联：{' / '.join(names)}"])

    if entry.get("file_type") == "pdf" or entry.get("is_priority_pdf"):
        lines.extend(["", format_pdf_source(entry), format_full_content_hint()])
    else:
        lines.extend([
            "",
            "💡 回复「详细」看公式表格 | 「套路」看情景题套路 | 「关联」看相关知识点",
        ])

    text = "\n".join(lines)
    # 错题联动（失败不影响主输出）
    q = query or entry.get("name", "")
    return append_error_hint_to_l1(text, q, entry)


def format_l2(entry: dict, content: str) -> str:
    traps = _extract_traps(content)
    fname = Path(entry.get("file") or "").name
    if entry.get("file_type") == "pdf" or entry.get("is_priority_pdf"):
        lines = [
            f"📖 {entry.get('name')} · 来自 {fname}",
            format_pdf_source(entry),
            "",
            content[:2500] + ("…" if len(content) > 2500 else ""),
        ]
    else:
        lines = [
            f"📖 {entry.get('name')} · 详解",
            f"📂 来源：{entry.get('file')}",
            "",
            content[:2500] + ("…" if len(content) > 2500 else ""),
        ]
    if traps:
        lines.extend(["", "⚠️ 易错点/陷阱："])
        for t in traps[:4]:
            lines.append(f"· {t}")
    lines.extend(["", "💡 回复「套路」看考试情景套路"])
    return "\n".join(lines)


def format_l3(entries: list[dict]) -> str:
    if not entries:
        return "⚠️ 未找到相关情景套路。试试「套路 变更」或「套路 挣值」。"

    lines = ["🎯 PMP 情景分析套路", ""]
    for e in entries[:2]:
        content = load_entry_content(e)
        preview = _pick_summary_lines(content, 4)
        lines.append(f"【{e.get('name')}】")
        for p in preview:
            lines.append(f"· {p}")
        lines.append("")
    lines.append("💡 完整版见：PMP考试情景分析题的三十六种套路.pdf")
    return "\n".join(lines)


def format_related(query: str, entries: list[dict]) -> str:
    lines = [f"🔗 「{query}」关联知识点", ""]
    for i, e in enumerate(entries[:5], 1):
        domain = e.get("domain", "")
        lines.append(f"{i}. [{domain}] {e.get('name', '')[:40]}")
    lines.extend(["", "💡 回复序号或「详细 XXX」深入查看"])
    return "\n".join(lines)


def retrieve_knowledge(query: str, level: Level = "L1") -> dict[str, Any]:
    """
    动态知识检索主入口。

    Returns:
        {"status": "ok"|"empty"|"error", "level": "L1", "text": "...", "entry_id": "..."}
    """
    query = (query or "").strip()
    if not query:
        return {"status": "error", "text": "⚠️ 请提供查询关键词，如「挣值」「变更管理」。"}

    if not INDEX_PATH.exists():
        return {
            "status": "error",
            "text": (
                "⚠️ 知识索引未构建。请先运行：\n"
                "`python build_knowledge_index.py`"
            ),
        }

    if level == "L3":
        patterns = search_entries(query, pattern_only=True, limit=2)
        # 套路条目额外加权
        if not patterns:
            patterns = [e for e in (_load_index().get("entries") or []) if e.get("is_pattern")]
            patterns = sorted(
                patterns,
                key=lambda e: _score_entry(query, e),
                reverse=True,
            )[:2]
        text = format_l3(patterns)
        _save_state({"last_query": query, "last_level": "L3", "entry_ids": [p["id"] for p in patterns]})
        return {"status": "ok", "level": "L3", "text": text, "entries": [p["id"] for p in patterns]}

    if level == "L1" and query.endswith("关联"):
        q = query.replace("关联", "").strip() or _load_state().get("last_query", "")
        related = search_entries(q, limit=6)
        text = format_related(q, related[1:] if related else related)
        return {"status": "ok", "level": "L1", "text": text, "mode": "related"}

    # 模糊匹配分流
    resolved = fuzzy_resolve(query)
    if resolved["ambiguous"] and not resolved["direct"]:
        fm = FuzzyMatchResult(
            query=query,
            score=resolved["score"],
            candidates=resolved["candidates"],
        )
        text = format_candidate_list(fm)
        _save_state({
            "last_query": query,
            "last_level": "L1",
            "candidate_entries": [e["id"] for _, e in resolved["candidates"]],
        })
        return {"status": "ambiguous", "level": "L1", "text": text}

    hits = search_entries(query, limit=3)
    if not hits:
        if resolved["score"] < 50:
            return {
                "status": "empty",
                "text": (
                    f"⚠️ 未找到「{query}」相关笔记。\n"
                    "建议：\n"
                    "- 运行 `python build_knowledge_index.py` 重建索引\n"
                    "- 换关键词：挣值/变更/风险/冲突/质量/敏捷"
                ),
            }
        hits = [resolved["entry"]] if resolved.get("entry") else []

    if not hits:
        return {
            "status": "empty",
            "text": (
                f"⚠️ 未找到「{query}」相关笔记。\n"
                "建议：\n"
                "- 运行 `python build_knowledge_index.py` 重建索引\n"
                "- 换关键词：挣值/变更/风险/冲突/质量/敏捷"
            ),
        }

    entry = hits[0]
    content = load_entry_content(entry)
    if level == "L1" and entry.get("heading_level") == 2:
        all_entries = _load_index().get("entries") or []
        children = [
            e for e in all_entries
            if e.get("file") == entry.get("file")
            and (e.get("heading_level") or 9) > 2
            and (e.get("line_start") or 0) > (entry.get("line_start") or 0)
        ]
        children.sort(key=lambda e: e.get("line_start") or 0)
        for c in children[:4]:
            content += "\n" + load_entry_content(c)
    related = hits[1:4] if level == "L1" else []

    if level == "L2":
        text = format_l2(entry, content)
    else:
        text = format_l1(entry, content, related, query=query)
        # 高置信度识别提示
        if resolved.get("direct") and resolved.get("matched_label"):
            fm_header = FuzzyMatchResult(
                query=query,
                score=resolved["score"],
                entry=entry,
                matched_label=resolved["matched_label"],
                direct=True,
            )
            header = format_recognition_header(fm_header)
            if header:
                text = header + text

    _save_state({
        "last_query": query,
        "last_level": level,
        "entry_ids": [entry["id"]],
        "entry_name": entry.get("name"),
    })

    return {
        "status": "ok",
        "level": level,
        "text": text,
        "entry_id": entry["id"],
        "entry_name": entry.get("name"),
    }


def _find_entry_by_id(entry_id: str) -> dict | None:
    for e in (_load_index().get("entries") or []):
        if e.get("id") == entry_id:
            return e
    return None


def parse_user_message(text: str) -> dict[str, Any] | None:
    """
    解析微信消息 → {query, level, mode}。
    mode: query | followup | related | error_detail | candidate_pick
    """
    t = text.strip().replace("\u200b", "").replace("\ufeff", "")
    if not t:
        return None

    state = _load_state()

    # 错题详情（需先查过知识点）
    if _ERROR_DETAIL.match(t):
        return {"query": state.get("last_query") or "", "level": "L1", "mode": "error_detail"}

    # 候选列表序号选择
    if _CANDIDATE_PICK.match(t) and state.get("candidate_entries"):
        return {"query": t, "level": "L1", "mode": "candidate_pick"}

    for pat, lvl in _FOLLOWUP:
        m = pat.match(t)
        if m:
            q = (m.group(1) or "").strip() or state.get("last_query") or state.get("entry_name", "")
            if not q:
                return {"query": "", "level": lvl, "mode": "followup", "need_query": True}
            mode = "related" if t.startswith("关联") else "followup"
            return {"query": q, "level": lvl, "mode": mode}

    for pat in _L1_TRIGGERS:
        m = pat.match(t)
        if m:
            return {"query": m.group(1).strip(), "level": "L1", "mode": "query"}

    # 裸关键词（2-20 字，非指令）— 模糊匹配 ≥50 分即触发
    if re.match(r"^[\u4e00-\u9fffA-Za-z0-9/]{2,20}$", t) and t not in {
        "复习错题", "每日一练", "薄弱点", "模考", "睡前复习", "错题",
    }:
        resolved = fuzzy_resolve(t)
        if resolved["score"] >= 50 or search_entries(t, limit=1):
            return {"query": t, "level": "L1", "mode": "query"}

    return None


def handle_message(text: str) -> dict[str, Any]:
    """微信硬路由入口。"""
    parsed = parse_user_message(text)
    if not parsed:
        return {"status": "skip"}

    if parsed.get("need_query"):
        return {
            "status": "ok",
            "text": "📌 请说明要查哪个知识点，如：「详细 挣值」或「套路 变更」",
        }

    mode = parsed.get("mode")

    # 错题详情
    if mode == "error_detail":
        state = _load_state()
        q = parsed["query"] or state.get("entry_name") or state.get("last_query", "")
        entry = None
        eids = state.get("entry_ids") or []
        if eids:
            entry = _find_entry_by_id(eids[0])
        try:
            errors = find_errors_for_topic(q, entry)
            text_out = format_error_detail_list(q, errors, entry)
        except Exception:
            text_out = "⚠️ 错题列表加载失败，请稍后重试。"
        return {"status": "ok", "text": text_out, "level": "L1", "mode": "error_detail"}

    # 候选序号
    if mode == "candidate_pick":
        state = _load_state()
        ids = state.get("candidate_entries") or []
        idx = int(parsed["query"]) - 1
        if 0 <= idx < len(ids):
            entry = _find_entry_by_id(ids[idx])
            if entry:
                content = load_entry_content(entry)
                text_out = format_l1(entry, content, query=entry.get("name", ""))
                _save_state({
                    "last_query": entry.get("name"),
                    "last_level": "L1",
                    "entry_ids": [entry["id"]],
                    "entry_name": entry.get("name"),
                })
                return {"status": "ok", "text": text_out, "level": "L1", "entry_id": entry["id"]}
        return {"status": "ok", "text": "⚠️ 无效选择，请回复 1-5 之间的序号。"}

    q = parsed["query"]
    level = parsed["level"]
    if mode == "related":
        related = search_entries(q, limit=6)
        return {
            "status": "ok",
            "text": format_related(q, related),
            "level": "L1",
        }

    return retrieve_knowledge(q, level)


def main() -> None:
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="动态知识查询")
    sub = parser.add_subparsers(dest="command")

    p_q = sub.add_parser("query", help="检索知识点")
    p_q.add_argument("text")
    p_q.add_argument("--level", "-l", default="L1", choices=["L1", "L2", "L3"])
    p_q.add_argument("--json", action="store_true")

    p_msg = sub.add_parser("message", help="解析并处理微信消息")
    p_msg.add_argument("--text", "-t", required=True)
    p_msg.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "query":
        result = retrieve_knowledge(args.text, args.level)
    else:
        result = handle_message(args.text)
        if result.get("status") == "skip":
            result = {"status": "skip", "text": ""}

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result.get("text") or json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
