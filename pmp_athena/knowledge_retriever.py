#!/usr/bin/env python3
"""
知识点快速检索 — 问哪个领域，就从 ChromaDB 向量库秒回 3-5 条核心知识点。

用法:
    python pmp_athena/knowledge_retriever.py retrieve --text "项目成本管理知识点"
    python pmp_athena/knowledge_retriever.py retrieve --text "知识点 范围管理" --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 标准领域 + 别名（长别名优先匹配）
AREA_ALIASES: list[tuple[str, list[str]]] = [
    ("整合管理", ["项目整合管理", "整合管理", "整体管理", "整合"]),
    ("范围管理", ["项目范围管理", "范围管理", "范围"]),
    ("进度管理", ["项目进度管理", "进度管理", "时间管理", "进度"]),
    ("成本管理", ["项目成本管理", "成本管理", "费用管理", "项目成本", "成本", "挣值"]),
    ("质量管理", ["项目质量管理", "质量管理", "质量"]),
    ("资源管理", ["项目资源管理", "资源管理", "资源", "团队管理"]),
    ("沟通管理", ["项目沟通管理", "沟通管理", "沟通"]),
    ("风险管理", ["项目风险管理", "风险管理", "风险"]),
    ("采购管理", ["项目采购管理", "采购管理", "采购", "合同管理"]),
    ("干系人管理", ["项目干系人管理", "干系人管理", "相关方管理", "干系人", "相关方"]),
    ("敏捷/混合方法", ["敏捷混合方法", "敏捷/混合方法", "混合方法", "敏捷", "Scrum", "迭代"]),
    ("商业环境", ["商业环境", "商业", "合规"]),
    ("领导力/人员", ["领导力人员", "领导力/人员", "领导力", "人员", "冲突管理", "团队建设"]),
]

_SUPPORTED_HINT = "整合/范围/进度/成本/质量/资源/沟通/风险/采购/干系人/敏捷/商业环境/领导力"

# (pattern, group_index for area text)
_TRIGGER_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"^(.+?)知识点$"), 1),
    (re.compile(r"^知识点\s*(.+)$"), 1),
    (re.compile(r"^总结(.+)$"), 1),
    (re.compile(r"^(.+?)总结$"), 1),
    (re.compile(r"^(.+?)的考点$"), 1),
    (re.compile(r"^(.+?)有哪些考点$"), 1),
    (re.compile(r"^考点\s*(.+)$"), 1),
    (re.compile(r"^(.+?)有哪些要点$"), 1),
    (re.compile(r"^(.+?)速查$"), 1),
    (re.compile(r"^详细知识点\s*(.+)$"), 1),  # 预留扩展
]

_SKIP_PATTERNS = re.compile(
    r"备注|输入和输出|本图提供|见第.*节|如下所示|如下图所示",
)

_MIN_POINTS = 1
_MAX_POINTS = 5
_MAX_DISTANCE = 0.85


def normalize_area(raw: str) -> str | None:
    """将用户输入映射到标准知识领域名。"""
    t = (raw or "").strip()
    t = re.sub(r"^[项目PMPpmp\s]+", "", t)
    t = re.sub(r"[的之\s]+$", "", t)
    if not t:
        return None

    for area, _ in AREA_ALIASES:
        if t == area or area in t:
            return area

    pairs = sorted(
        ((area, alias) for area, aliases in AREA_ALIASES for alias in aliases),
        key=lambda x: len(x[1]),
        reverse=True,
    )
    for area, alias in pairs:
        if alias in t or t in alias:
            return area
    return None


def parse_knowledge_request(text: str) -> str | None:
    """解析触发词，返回标准领域名。"""
    t = (text or "").strip().replace("\u200b", "").replace("\ufeff", "")
    if not t or len(t) < 3:
        return None

    for pat, grp in _TRIGGER_PATTERNS:
        m = pat.match(t)
        if m:
            return normalize_area(m.group(grp).strip())
    return None


def is_knowledge_retrieval_request(text: str) -> bool:
    return parse_knowledge_request(text) is not None


# 兼容旧名
is_knowledge_summary_request = is_knowledge_retrieval_request


def _empty_message(area: str) -> str:
    return "\n".join([
        f"⚠️ 未找到 {area} 的笔记。建议：",
        "- 先运行 `python -m pmp_athena.cli ingest` 导入笔记",
        f"- 或确认知识领域名称是否正确（支持：{_SUPPORTED_HINT}）",
    ])


def _clean_line(line: str) -> str:
    line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
    line = re.sub(r"`([^`]+)`", r"\1", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line[:120]


def _extract_point(doc: str, title: str = "") -> str:
    for line in doc.split("\n"):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("|") or s.startswith("---"):
            continue
        for pat in (
            r"^[●•\-*✅]\s*(.+)",
            r"^\d+[\.、．]\s+(.+)",
            r"^[-*•●]\s*\*\*(.+?)\*\*",
        ):
            m = re.match(pat, s)
            if m:
                text = _clean_line(m.group(1))
                if len(text) >= 8:
                    return text
        if len(s) >= 12 and not s.endswith(":") and not re.match(r"^\d+(\.\d+)+", s):
            return _clean_line(s)

    if title and len(title) >= 10 and not re.match(r"^\d+(\.\d+)+", title):
        return _clean_line(title)

    return _clean_line(doc.split("\n")[0]) if doc.strip() else ""


def _is_valid_point(text: str) -> bool:
    if len(text) < 8:
        return False
    return not _SKIP_PATTERNS.search(text)


def _dedup_points(points: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in points:
        key = re.sub(r"\W+", "", p)[:40]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _collect_points(results: list[dict]) -> list[str]:
    points: list[str] = []
    seen_ids: set[str] = set()
    for hit in results:
        if hit.get("distance", 1.0) > _MAX_DISTANCE:
            continue
        doc_id = str(hit.get("id") or "")
        if doc_id and doc_id in seen_ids:
            continue
        if doc_id:
            seen_ids.add(doc_id)
        meta = hit.get("metadata") or {}
        title = meta.get("title") or meta.get("heading") or ""
        doc = hit.get("document") or ""
        point = _extract_point(doc, title)
        if _is_valid_point(point):
            points.append(point)
    return _dedup_points(points)


def retrieve_area(area: str, *, n_results: int = 5) -> dict[str, Any]:
    """从向量库检索并格式化为知识点速查。"""
    from pmp_athena.db.vector_store import get_vector_store

    store = get_vector_store()
    if store.get_notes_count() == 0:
        return {"status": "empty", "area": area, "text": _empty_message(area)}

    queries = [
        f"{area} PMP 核心知识点 考点",
        f"{area} 工具 技术 过程",
        f"{area} 公式 定义",
    ]
    all_results: list[dict] = []
    for q in queries:
        all_results.extend(store.search_notes(q, n_results=n_results))

    points = _collect_points(all_results)[:_MAX_POINTS]

    if len(points) < _MIN_POINTS:
        return {"status": "empty", "area": area, "text": _empty_message(area)}

    lines = [f"📚 {area} 知识点速查", ""]
    for i, p in enumerate(points, 1):
        lines.append(f"{i}. {p}")
    lines.extend(["", f"💡 要更详细的内容？回复「详细知识点 {area}」"])

    text = "\n".join(lines)
    # 错题联动
    try:
        from pmp_athena.knowledge_error_linkage import append_error_hint_to_l1
        text = append_error_hint_to_l1(text, area, {"name": area, "domain": area})
    except Exception:
        pass

    return {
        "status": "ok",
        "area": area,
        "points": points,
        "text": text,
    }


# 兼容旧 API 名
summarize_area = retrieve_area


def retrieve_from_text(text: str) -> dict[str, Any]:
    area = parse_knowledge_request(text)
    if not area:
        return {
            "status": "error",
            "text": (
                "⚠️ 无法识别知识领域。示例：\n"
                "· 项目成本管理知识点\n"
                "· 知识点 范围管理\n"
                "· 敏捷有哪些考点"
            ),
        }
    return retrieve_area(area)


summarize_from_text = retrieve_from_text


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="知识点快速检索")
    sub = parser.add_subparsers(dest="command")

    p_ret = sub.add_parser("retrieve", help="按触发词检索知识点")
    p_ret.add_argument("--text", "-t", required=True)
    p_ret.add_argument("--json", action="store_true")

    p_parse = sub.add_parser("parse", help="仅解析领域名")
    p_parse.add_argument("--text", "-t", required=True)
    p_parse.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "retrieve":
        result = retrieve_from_text(args.text)
    else:
        area = parse_knowledge_request(args.text)
        result = {"status": "ok" if area else "error", "area": area}

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result.get("text") or json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
