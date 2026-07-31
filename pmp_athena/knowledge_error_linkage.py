#!/usr/bin/env python3
"""
知识点 ↔ 错题联动：查询知识点时自动关联 error_log 中的错题。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import NOTES_DIR, PROJECT_ROOT
except ModuleNotFoundError:
    from config import NOTES_DIR, PROJECT_ROOT

ERROR_LOG_PATH = NOTES_DIR / "error_log.json"
QUESTION_BANK_PATH = NOTES_DIR / "question_bank.json"

# 查询词 → 匹配关键词（用于无 knowledge_area 时的内容匹配）
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "挣值": ["挣值", "EVM", "CPI", "SPI", "SV", "CV", "BAC", "TCPI", "成本偏差", "进度偏差"],
    "变更": ["变更", "CCB", "变更控制", "变更请求", "变更委员会"],
    "风险": ["风险", "威胁", "机会", "应对", "风险登记册", "应急储备"],
    "冲突": ["冲突", "塔克曼", "团队建设", "合作", "妥协", "强迫"],
    "质量": ["质量", "QA", "QC", "审计", "控制质量", "管理质量"],
    "敏捷": ["敏捷", "Scrum", "迭代", "燃尽", "回顾", "Sprint"],
    "干系人": ["干系人", "相关方", "权力利益"],
    "WBS": ["WBS", "范围", "工作分解", "范围基准"],
    "采购": ["采购", "合同", "FFP", "工料", "投标人"],
    "进度": ["进度", "关键路径", "赶工", "快速跟进", "工期"],
    "沟通": ["沟通", "报告", "交互式", "推式", "拉式"],
    "资源": ["资源", "RACI", "团队", "资源日历"],
    "整合": ["整合", "章程", "项目章程"],
    "商业": ["商业", "合规", "效益"],
    "成本": ["成本", "预算", "挣值", "EVM"],
    "范围": ["范围", "WBS", "需求", "范围蔓延"],
    "领导力": ["领导", "激励", "教练", "情商"],
}

# 标准知识领域名（与 error_log.knowledge_area 对齐）
_STANDARD_AREAS = [
    "整合管理", "范围管理", "进度管理", "成本管理", "质量管理",
    "资源管理", "沟通管理", "风险管理", "采购管理", "干系人管理",
    "敏捷/混合方法", "商业环境", "领导力/人员", "综合",
]

_AREA_ALIASES: dict[str, str] = {
    "整合": "整合管理", "整体": "整合管理",
    "范围": "范围管理", "WBS": "范围管理",
    "进度": "进度管理", "时间": "进度管理",
    "成本": "成本管理", "挣值": "成本管理", "EVM": "成本管理",
    "质量": "质量管理",
    "资源": "资源管理", "团队": "资源管理",
    "沟通": "沟通管理",
    "风险": "风险管理",
    "采购": "采购管理", "合同": "采购管理",
    "干系人": "干系人管理", "相关方": "干系人管理",
    "敏捷": "敏捷/混合方法", "Scrum": "敏捷/混合方法",
    "商业": "商业环境", "合规": "商业环境",
    "冲突": "领导力/人员", "领导": "领导力/人员",
}


def _load_json(path: Path) -> list | dict:
    if not path.exists():
        return [] if path.name.endswith(".json") and "bank" not in path.name else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [] if "error_log" in path.name else {}


def normalize_area(raw: str) -> str | None:
    t = (raw or "").strip()
    if not t:
        return None
    for area in _STANDARD_AREAS:
        if t == area or area in t or t in area:
            return area
    for alias, area in _AREA_ALIASES.items():
        if alias in t or t == alias:
            return area
    return None


def _expand_topic_tokens(query: str, entry: dict | None = None) -> set[str]:
    tokens: set[str] = {query.strip()}
    q_lower = query.lower()

    for key, kws in _TOPIC_KEYWORDS.items():
        if key in query or query in key:
            tokens.add(key)
            tokens.update(kws)
        for kw in kws:
            if kw.lower() in q_lower or q_lower in kw.lower():
                tokens.add(key)
                tokens.update(kws)

    area = normalize_area(query)
    if area:
        tokens.add(area)

    if entry:
        tokens.add(entry.get("name") or "")
        tokens.add(entry.get("domain") or "")
        tokens.update(entry.get("keywords") or [])

    return {t for t in tokens if t and len(t) >= 2}


_GENERIC_TOKENS = frozenset({
    "管理", "项目", "过程", "计划", "工作", "团队", "工具", "技术", "方法", "分析",
    "核心", "关键", "基本", "主要", "相关", "综合", "PMP", "PMI",
})


def _meaningful_tokens(tokens: set[str]) -> set[str]:
    return {t for t in tokens if t not in _GENERIC_TOKENS and len(t) >= 2}


def _error_matches_topic(err: dict, tokens: set[str]) -> bool:
    tokens = _meaningful_tokens(tokens)
    if not tokens:
        return False

    area = err.get("knowledge_area") or ""
    if area:
        for t in tokens:
            na = normalize_area(t)
            if na and (na == area or na in area or area in na):
                return True
            if len(t) >= 3 and (t in area or area in t):
                return True

    blob = f"{err.get('question', '')} {err.get('explanation', '')}"
    blob_lower = blob.lower()
    for t in tokens:
        if len(t) >= 3 and (t in blob or t.lower() in blob_lower):
            return True
    return False


def find_errors_for_topic(query: str, entry: dict | None = None) -> list[dict]:
    """查找与知识点/查询词相关的错题，按时间倒序。"""
    errors = _load_json(ERROR_LOG_PATH)
    if not isinstance(errors, list) or not errors:
        return []

    # 优先按知识领域精确匹配
    target_areas: set[str] = set()
    if entry and entry.get("domain"):
        na = normalize_area(entry["domain"])
        if na:
            target_areas.add(na)
    na = normalize_area(query)
    if na:
        target_areas.add(na)

    if target_areas:
        matched = [
            e for e in errors
            if normalize_area(e.get("knowledge_area") or "") in target_areas
            or any(a in (e.get("knowledge_area") or "") for a in target_areas)
        ]
    else:
        tokens = _expand_topic_tokens(query, entry)
        matched = [e for e in errors if _error_matches_topic(e, tokens)]

    matched.sort(key=lambda e: e.get("timestamp") or e.get("date") or "", reverse=True)
    return matched


def calc_area_accuracy(query: str, entry: dict | None = None) -> float | None:
    """计算该知识领域的做题正确率（来自 question_bank）。"""
    bank = _load_json(QUESTION_BANK_PATH)
    if not isinstance(bank, list) or not bank:
        return None

    tokens = _expand_topic_tokens(query, entry)
    areas: set[str] = set()
    for t in tokens:
        na = normalize_area(t)
        if na:
            areas.add(na)
    if entry and entry.get("domain"):
        areas.add(entry["domain"])

    if not areas:
        return None

    total, correct = 0, 0
    for rec in bank:
        ka = rec.get("knowledge_area") or ""
        if not any(a == ka or a in ka or ka in a for a in areas):
            continue
        total += 1
        if rec.get("is_correct"):
            correct += 1

    if total == 0:
        return None
    return round(correct / total * 100)


def format_error_hint(query: str, errors: list[dict], entry: dict | None = None) -> str:
    """L1 末尾追加的错题提示。"""
    if not errors:
        return ""

    topic = entry.get("name") if entry else query
    if entry and entry.get("domain"):
        topic = entry.get("domain") or topic

    n = len(errors)
    acc = calc_area_accuracy(query, entry)
    acc_str = f"{acc:.0f}%" if acc is not None else "—"

    return "\n".join([
        "",
        f"⚠️ 您有 {n} 道「{topic}」错题待复习（正确率 {acc_str}）",
        "💬 回复「错题」查看详情",
    ])


def _question_summary(q: str, max_len: int = 60) -> str:
    q = re.sub(r"\s+", " ", q.strip())
    q = q.split("\n")[0]
    return q[:max_len] + ("…" if len(q) > max_len else "")


def format_error_detail_list(query: str, errors: list[dict], entry: dict | None = None) -> str:
    """用户回复「错题」时的详情列表。"""
    if not errors:
        topic = entry.get("name") if entry else query
        return f"✅ 「{topic}」暂无关联错题记录。"

    topic = entry.get("domain") if entry else query
    if entry and entry.get("name"):
        topic = f"{entry.get('name')}（{entry.get('domain', '')}）"

    lines = [
        f"❌ 「{topic}」错题列表（共 {len(errors)} 道）",
        "══════════════════════",
        "",
    ]
    for i, err in enumerate(errors[:10], 1):
        eid = err.get("id", "?")
        summary = _question_summary(err.get("question", ""))
        my_a = err.get("my_answer", "?")
        correct = err.get("correct_answer", "?")
        date = err.get("date", "")
        lines.append(f"{i}. #{eid} [{err.get('knowledge_area', '综合')}] {summary}")
        lines.append(f"   ❌ 你的答案: {my_a} → ✅ 正确: {correct}  ({date})")
        lines.append("")

    if len(errors) > 10:
        lines.append(f"... 还有 {len(errors) - 10} 道，发送「复习错题」逐一练习")
    lines.append("💡 发送「复习错题」开始 SM-2 复习")
    return "\n".join(lines)


def append_error_hint_to_l1(text: str, query: str, entry: dict | None) -> str:
    """安全追加错题提示，失败时不影响原输出。"""
    try:
        errors = find_errors_for_topic(query, entry)
        hint = format_error_hint(query, errors, entry)
        return text + hint if hint else text
    except Exception:
        return text
