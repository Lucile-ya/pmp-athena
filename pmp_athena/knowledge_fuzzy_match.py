#!/usr/bin/env python3
"""
知识点模糊匹配：别名 / 关键词 / 同义词 多级打分。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

# 别名 → 目标条目名（索引 entry.name 子串匹配）
ALIAS_TO_TARGET: dict[str, str] = {
    "挣值": "挣值管理EVM",
    "EVM": "挣值管理EVM",
    "evm": "挣值管理EVM",
    "成本": "成本管理",
    "项目成本": "成本管理",
    "风险": "风险管理",
    "冲突": "冲突解决",
    "商业环境": "商业环境",
    "商业": "商业环境",
    "合规": "商业环境",
    "49个过程": "PMP-49过程组",
    "49过程": "PMP-49过程组",
    "五大过程组": "五大过程组",
    "十大知识领域": "十大知识领域",
    "过程组": "五大过程组",
    "WBS": "WBS",
    "变更": "变更",
    "CCB": "变更",
    "敏捷": "敏捷",
    "Scrum": "敏捷",
    "干系人": "干系人",
    "相关方": "干系人",
    "采购": "采购",
    "质量": "质量",
    "进度": "进度",
    "沟通": "沟通",
    "资源": "资源",
    "整合": "整合",
    "PMBOK": "PMBOK",
    "套路": "套路",
}

# 同义词扩展（70 分档）
SYNONYMS: dict[str, list[str]] = {
    "挣值": [" earned value", "挣值分析", "偏差分析", "CPI", "SPI"],
    "变更": ["change control", "变更控制委员会", "变更流程"],
    "风险": ["risk register", "风险登记册", "威胁", "机会"],
    "冲突": ["conflict", "团队冲突", "塔克曼"],
    "敏捷": ["agile", "迭代开发", "燃尽图", "回顾会"],
    "干系人": ["stakeholder", "相关方管理"],
    "WBS": ["工作分解结构", "范围基准"],
    "采购": ["合同类型", "FFP", "工料合同"],
}

# 套路编号：「套路5」「套路 5」
_PATTERN_NUM = re.compile(r"^套路\s*(\d+)$", re.I)


@dataclass
class FuzzyMatchResult:
    query: str
    score: float  # 0-100
    entry: dict | None = None
    candidates: list[tuple[float, dict]] = field(default_factory=list)
    matched_label: str = ""
    direct: bool = False  # score > 80
    ambiguous: bool = False  # 50 <= score <= 80


def _normalize(q: str) -> str:
    return re.sub(r"\s+", "", (q or "").strip().lower())


def _entry_blob(entry: dict) -> str:
    name = entry.get("name") or ""
    kws = " ".join(entry.get("keywords") or [])
    domain = entry.get("domain") or ""
    fname = entry.get("file") or ""
    return f"{name} {kws} {domain} {fname}".lower()


def _score_one(query: str, entry: dict) -> tuple[float, str]:
    """对单条目打分 0-100，返回 (score, reason)。"""
    q = query.strip()
    qn = _normalize(q)
    name = entry.get("name") or ""
    name_n = _normalize(name)
    blob = _entry_blob(entry)

    # 精确匹配 name
    if qn == name_n or q == name:
        return 100.0, name

    # 别名匹配
    target = ALIAS_TO_TARGET.get(q) or ALIAS_TO_TARGET.get(qn)
    if target:
        fname = (entry.get("file") or "").lower()
        if target.lower() in fname or target.lower() in name.lower():
            # 主文档 H2 优先于子章节
            bonus = 5 if entry.get("heading_level") == 2 else 0
            return min(90.0 + bonus, 100.0), f"别名→{target}"
        if target.lower() in blob:
            return 90.0, f"别名→{target}"

    # 关键词匹配：query 在 name/keywords/domain/file
    if len(q) >= 2 and (q in name or q.lower() in blob):
        return 80.0, name

    for kw in entry.get("keywords") or []:
        if q in kw or kw in q:
            return 80.0, name

    # 同义词
    for key, syns in SYNONYMS.items():
        if key in q or q in key:
            for syn in syns:
                if syn.strip().lower() in blob or syn.strip() in name:
                    return 70.0, name

    # 模糊相似度
    ratio = SequenceMatcher(None, qn, name_n).ratio() * 100
    if ratio >= 60:
        return ratio, name

    # 别名表反向：entry name 含 alias key
    for alias, tgt in ALIAS_TO_TARGET.items():
        if alias in q and tgt.lower() in blob:
            return 85.0, name

    return 0.0, ""


def fuzzy_match_query(query: str, entries: list[dict]) -> FuzzyMatchResult:
    """
    对全部索引条目打分，返回最佳匹配与候选列表。

    > 80: direct
    50-80: ambiguous（候选列表）
    < 50: 无匹配
    """
    q = (query or "").strip()
    if not q or not entries:
        return FuzzyMatchResult(query=q, score=0)

    # 套路编号特殊处理
    pm = _PATTERN_NUM.match(q)
    if pm:
        num = int(pm.group(1))
        for e in entries:
            if e.get("is_pattern") and e.get("pattern_number") == num:
                return FuzzyMatchResult(
                    query=q, score=95, entry=e,
                    matched_label=e.get("name", ""), direct=True,
                    candidates=[(95, e)],
                )

    scored: list[tuple[float, dict, str]] = []
    for e in entries:
        if "_error" in e:
            continue
        s, label = _score_one(q, e)
        if s >= 35:
            scored.append((s, e, label))

    scored.sort(key=lambda x: (-x[0], 0 if x[1].get("file_type") == "md" else 1, x[1].get("name", "")))

    if not scored:
        return FuzzyMatchResult(query=q, score=0)

    best_score, best_entry, best_label = scored[0]
    candidates = [(s, e) for s, e, _ in scored[:5]]

    result = FuzzyMatchResult(
        query=q,
        score=best_score,
        entry=best_entry if best_score >= 50 else None,
        candidates=candidates,
        matched_label=best_label or best_entry.get("name", ""),
    )
    result.direct = best_score > 80
    result.ambiguous = 50 <= best_score <= 80
    return result


def format_candidate_list(result: FuzzyMatchResult) -> str:
    """50-80 分：返回候选让用户选择。"""
    lines = [
        f"🔍 「{result.query}」匹配到多个知识点，请选择：",
        "",
    ]
    for i, (score, e) in enumerate(result.candidates[:5], 1):
        domain = e.get("domain", "综合")
        name = e.get("name", "")[:40]
        lines.append(f"{i}. [{domain}] {name}（{score:.0f}分）")
    lines.extend([
        "",
        "💡 回复序号或更精确的关键词，如「挣值管理知识点」",
    ])
    return "\n".join(lines)


def format_recognition_header(result: FuzzyMatchResult) -> str:
    """> 80 分：识别提示行。"""
    if not result.matched_label or result.score <= 80:
        return ""
    label = result.entry.get("name", result.matched_label) if result.entry else result.matched_label
    return f"📚 识别到您想了解「{label}」\n"
