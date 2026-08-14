#!/usr/bin/env python3
"""
学习顾问 —— 薄弱点分析、今日错题复习、智能学习计划

用法:
    python pmp_athena/study_advisor.py weakness       # 总结薄弱点
    python pmp_athena/study_advisor.py review-today    # 今日复习错题
    python pmp_athena/study_advisor.py plan            # 制定学习计划
    python pmp_athena/study_advisor.py plan --days 7   # 未来N天计划
"""

try:
    from pmp_athena.config import ERROR_LOG_PATH, EXAM_CONFIG_PATH, OPTIONS_SUPPLEMENT_PATH, QUESTION_BANK_PATH, REVIEW_STATE_PATH
except ModuleNotFoundError:
    from config import ERROR_LOG_PATH, EXAM_CONFIG_PATH, OPTIONS_SUPPLEMENT_PATH, QUESTION_BANK_PATH, REVIEW_STATE_PATH

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# ── 路径 ──────────────────────────────────────────────────
QUESTION_BANK = QUESTION_BANK_PATH
ERROR_LOG = ERROR_LOG_PATH
REVIEW_STATE = REVIEW_STATE_PATH
EXAM_CONFIG = EXAM_CONFIG_PATH
OPTIONS_SUPPLEMENT = OPTIONS_SUPPLEMENT_PATH

# ── 错误类型标签（与 error_logger.ERROR_TYPES 同步）─────────
ERROR_TYPE_LABELS = {
    "概念混淆", "流程顺序错", "角色越权",
    "陷阱误导", "粗心", "知识盲区",
}

_OPTION_RE = re.compile(r"(?:^|\s)[A-D][\.、．\)]")

# ── 阶段日历（与 CLAUDE.md 同步）──────────────────────────
PHASE_CALENDAR = [
    # (开始, 结束, 名称, 图标)
    (date(2026, 8, 16), date(2026, 9, 1),  "强化刷题期", "⚡"),
    (date(2026, 9, 2),  date(2026, 9, 11), "冲刺模考期", "🔥"),
]
PHASE_FALLBACK = ("基础巩固期", "📖")


def get_current_phase(today: date | None = None) -> dict:
    """返回当前阶段的名称/图标/剩余天数"""
    if today is None:
        today = date.today()
    for start, end, name, icon in PHASE_CALENDAR:
        if start <= today <= end:
            remaining = (end - today).days
            return {
                "name": name,
                "icon": icon,
                "remaining_days": remaining,
                "end_date": end.isoformat(),
                "is_active": True,
            }
    # 默认：基础巩固期（考试前最后阶段之前的时间）
    first_phase_start = PHASE_CALENDAR[0][0]
    remaining = (first_phase_start - today).days
    remaining = max(0, remaining)
    return {
        "name": PHASE_FALLBACK[0],
        "icon": PHASE_FALLBACK[1],
        "remaining_days": remaining,
        "end_date": first_phase_start.isoformat(),
        "is_active": True,
    }


def get_phase_milestone(remaining_days: int) -> str | None:
    """关键里程碑提示"""
    if remaining_days in (30, 14, 7, 3, 1):
        if remaining_days <= 7:
            return f"🚨 距离考试仅剩 {remaining_days} 天！进入冲刺备战状态。"
        elif remaining_days <= 14:
            return f"🚨 距离考试仅剩 {remaining_days} 天！查漏补缺关键时刻。"
        else:
            return f"🚨 距离考试仅剩 {remaining_days} 天！进入强化阶段。"
    return None


# ── 知识领域 ──────────────────────────────────────────────
ALL_AREAS = [
    "整合管理", "范围管理", "进度管理", "成本管理", "质量管理",
    "资源管理", "沟通管理", "风险管理", "采购管理", "干系人管理",
    "敏捷/混合方法", "商业环境", "领导力/人员",
]


# ═══════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════

def load_json(path: Path) -> list | dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [] if path.suffix == ".json" and path.name != "exam_config.json" else {}


def get_exam_date() -> date | None:
    cfg = load_json(EXAM_CONFIG)
    if isinstance(cfg, dict):
        raw = cfg.get("exam_date", "")
        try:
            return datetime.strptime(str(raw), "%Y-%m-%d").date()
        except Exception:
            pass
    return None


# ═══════════════════════════════════════════════════════════
# 1. 总结薄弱点
# ═══════════════════════════════════════════════════════════

def analyze_weakness() -> str:
    """分析薄弱领域，输出诊断报告"""
    bank = load_json(QUESTION_BANK)
    errors = load_json(ERROR_LOG)
    review = load_json(REVIEW_STATE)

    if not isinstance(bank, list):
        bank = []
    if not isinstance(errors, list):
        errors = []
    if not isinstance(review, dict):
        review = {}

    lines = []
    lines.append("📊 薄弱点诊断报告")
    lines.append("=" * 30)

    # ── 按领域统计正确率 ──
    area_stats: dict[str, dict] = {}
    for r in bank:
        area = r.get("knowledge_area", "未分类")
        if area not in area_stats:
            area_stats[area] = {"total": 0, "correct": 0, "wrong": 0}
        area_stats[area]["total"] += 1
        if r.get("is_correct") is True:
            area_stats[area]["correct"] += 1
        elif r.get("is_correct") is False:
            area_stats[area]["wrong"] += 1

    # 找薄弱领域（按错误率降序，至少做过2题）
    weak_list = []
    for area, s in area_stats.items():
        judged = s["correct"] + s["wrong"]
        if judged >= 2:
            rate = s["wrong"] / judged
            weak_list.append((area, rate, s["total"], s["wrong"], s["correct"]))
    weak_list.sort(key=lambda x: x[1], reverse=True)

    if weak_list:
        lines.append("\n## 🎯 薄弱领域 TOP 3\n")
        lines.append("| 领域 | 错误率 | 错/总 | 风险 |")
        lines.append("|------|--------|-------|------|")
        for area, rate, total, wrong, correct in weak_list[:5]:
            risk = "🔴 高危" if rate >= 0.7 else ("🟡 注意" if rate >= 0.4 else "🟢 可接受")
            lines.append(f"| {area} | {rate:.0%} | {wrong}/{total} | {risk} |")

    # ── 错题本专项统计 ──
    if errors:
        err_area: dict[str, int] = {}
        for e in errors:
            a = e.get("knowledge_area", "未分类")
            err_area[a] = err_area.get(a, 0) + 1
        sorted_err = sorted(err_area.items(), key=lambda x: x[1], reverse=True)

        lines.append("\n## 📋 错题本分布\n")
        for area, count in sorted_err:
            bar = "█" * count
            lines.append(f"- {area}: {count} 题 {bar}")

    # ── 常见错误模式 ──
    patterns: dict[str, int] = {}
    for r in bank:
        if r.get("is_correct") is False:
            p = f"{r.get('my_answer', '?')}→{r.get('correct_answer', '?')}"
            patterns[p] = patterns.get(p, 0) + 1
    sorted_pt = sorted(patterns.items(), key=lambda x: x[1], reverse=True)

    if sorted_pt:
        lines.append("\n## 🔁 高频错误选项模式\n")
        for p, cnt in sorted_pt[:5]:
            lines.append(f"- {p}: {cnt} 次")

    # ── 错误类型分布 ──
    error_type_counts: dict[str, int] = {}
    for e in errors:
        et = e.get("error_type", "").strip()
        if et and et in ERROR_TYPE_LABELS:
            error_type_counts[et] = error_type_counts.get(et, 0) + 1

    if error_type_counts:
        sorted_et = sorted(error_type_counts.items(), key=lambda x: x[1], reverse=True)
        lines.append("\n## 📊 错误类型分布\n")
        lines.append("| 错误类型 | 数量 | 占比 | 含义 |")
        lines.append("|----------|------|------|------|")
        total_with_type = sum(error_type_counts.values())
        for et, cnt in sorted_et:
            pct = cnt / total_with_type * 100 if total_with_type else 0
            bar = "█" * max(1, int(pct / 5))
            desc_map = {
                "概念混淆": "两个概念记反了",
                "流程顺序错": "步骤顺序不对",
                "角色越权": "角色职责搞混",
                "陷阱误导": "被干扰项骗了",
                "粗心": "看漏/看错/手滑",
                "知识盲区": "完全没见过",
            }
            lines.append(f"| {et} | {cnt} | {bar} {pct:.0f}% | {desc_map.get(et, '')} |")

        lines.append("\n## 💡 错误类型诊断\n")
        if error_type_counts.get("概念混淆", 0) >= 3:
            lines.append("- 📚 概念混淆偏多：建议用对比表格梳理相似概念（如风险vs问题、QA vs QC）")
        if error_type_counts.get("陷阱误导", 0) >= 3:
            lines.append("- 🪤 陷阱误导偏多：做题时先不看选项，形成思路后再对照选项")
        if error_type_counts.get("流程顺序错", 0) >= 3:
            lines.append("- 🔄 流程顺序错偏多：注意问法意图（First vs Best），先分析再行动")
        if error_type_counts.get("角色越权", 0) >= 3:
            lines.append("- 🎭 角色越权偏多：牢记敏捷三角色（PO定优先级/SM清障碍/团队自组织）")
        if error_type_counts.get("粗心", 0) >= 3:
            lines.append("- 👀 粗心偏多：放慢做题速度，逐字审题干关键词")
        if error_type_counts.get("知识盲区", 0) >= 3:
            lines.append("- 📖 知识盲区偏多：建议回归PMBOK核心章节，补充基础概念")
    else:
        lines.append("\n## 📊 错误类型分布\n")
        lines.append("- 暂无错误类型标记数据（使用 `--error-type` 参数标记后可查看分布）")

    # ── 敏捷专项诊断 ──
    agile_wrong = sum(
        1 for r in bank
        if r.get("is_correct") is False and "敏捷" in r.get("knowledge_area", "")
    )
    agile_total = sum(
        1 for r in bank
        if "敏捷" in r.get("knowledge_area", "")
    )
    if agile_total > 0:
        lines.append(f"\n## ⚡ 敏捷专项\n")
        lines.append(f"- 敏捷题总数: {agile_total}")
        lines.append(f"- 敏捷错题: {agile_wrong}")
        lines.append(f"- 敏捷错误率: {agile_wrong / agile_total:.0%}" if agile_total else "")
        if agile_wrong >= 3:
            lines.append("- ⚠️ 敏捷场景是你的**持续弱点**，建议专题突破")

    # ── 复习待办 ──
    today_str = date.today().isoformat()
    overdue = sum(1 for v in review.values() if v.get("next_date", "9999") <= today_str)
    total_review = len(review)
    mastered = sum(1 for v in review.values() if v.get("interval", 0) >= 30)

    lines.append(f"\n## 🧠 间隔复习状态\n")
    lines.append(f"- 队列总数: {total_review}")
    lines.append(f"- 今日逾期未复习: **{overdue}** 题")
    lines.append(f"- 已掌握 (间隔≥30天): {mastered} 题")

    # ── 一句话建议 ──
    lines.append("\n## 💡 针对性建议\n")
    if weak_list:
        top_weak = weak_list[0][0]
        lines.append(f"1. 优先攻克 **{top_weak}**：每天专项练习 10 题")
    if agile_wrong >= 3:
        lines.append("2. 重点补强 **敏捷/混合方法**：回顾 Scrum 指南、敏捷 manifesto 四价值十二原则")
    if overdue > 0:
        lines.append(f"3. ⚠️ 有 {overdue} 道错题复习已逾期，今天优先处理！")
    lines.append("4. 练习时注意：选'看起来标准化的流程动作'前，先想'直接、务实、人本'的替代方案")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 2. 今日复习错题
# ═══════════════════════════════════════════════════════════

def _has_root_cause(error: dict) -> bool:
    """检查错题是否有可诊断的根因。"""
    try:
        from pmp_athena.root_cause_engine import diagnose
    except ImportError:
        from root_cause_engine import diagnose
    return diagnose(error) is not None


def review_today() -> str:
    """汇总今日需要复习的错题 — 智能排期版（分层 + 限量 + 进度）。"""
    errors = load_json(ERROR_LOG)
    review = load_json(REVIEW_STATE)
    bank = load_json(QUESTION_BANK)

    if not isinstance(errors, list):
        errors = []
    if not isinstance(review, dict):
        review = {}
    if not isinstance(bank, list):
        bank = []

    today_str = date.today().isoformat()

    # ── 使用 ReviewScheduler 做分层 + 限量 ──
    try:
        from pmp_athena.review_scheduler import ReviewScheduler
    except ImportError:
        from review_scheduler import ReviewScheduler

    sched = ReviewScheduler()
    is_sprint = sched.should_activate_sprint()
    is_pre30 = sched.should_activate_pre30()
    plan = sched.build_daily_plan(is_pre_exam=is_sprint, is_pre30=is_pre30)
    progress = sched.format_progress_bar()

    lines = []
    lines.append(f"📅 今日复习清单（{today_str}）")
    lines.append("=" * 30)
    lines.append("")
    lines.append(progress)
    lines.append("")

    if is_pre30:
        lines.append(f"⚡ 30天冲刺模式 · T1+T2优先 · T3延期至考前7天")
        lines.append("")
    if is_sprint:
        lines.append(f"🔥 考前冲刺模式 · 今日配额 {plan['daily_quota']} 题")
        lines.append("")

    # ── 收集所有到期错题（原始逻辑）──
    due_ids: set[int] = set()
    today_errors = [e for e in errors if e.get("date") == today_str]
    for e in today_errors:
        due_ids.add(e["id"])

    for _key, card in review.items():
        if card.get("next_date", "9999") <= today_str:
            due_ids.add(card.get("error_id"))

    today_wrong_in_bank = [
        r for r in bank
        if r.get("date") == today_str and r.get("is_correct") is False
    ]
    for r in today_wrong_in_bank:
        eid = r.get("error_log_id")
        if eid is not None:
            due_ids.add(eid)

    if not due_ids:
        lines.append("✅ 今日暂无待复习错题，继续保持！")
        tiers = sched.classify_all()
        t3_count = len(tiers["T3"])
        if t3_count > 0:
            lines.append(f"📦 {t3_count} 道低频错题已归入考前冲刺包，考前 7 天自动推送。")
        return "\n".join(lines)

    # ── 分层过滤：T1（高频）不限量 + T2（近期）限量 + T3（低频）考前推送 ──
    tiers = sched.classify_all()
    t1_ids = {t.error_id for t in tiers["T1"]}
    t2_ids = {t.error_id for t in tiers["T2"]}
    t3_ids = {t.error_id for t in tiers["T3"]}
    t0_ids = {t.error_id for t in tiers["T0"]}  # 粗心 - 排除

    # 剔除粗心
    due_ids -= t0_ids

    # 非冲刺模式 + 非 pre30 模式：T3 不推送
    if not is_sprint and not is_pre30:
        due_ids -= t3_ids

    # T1 优先排前面 + T2 限量
    t1_due = sorted(due_ids & t1_ids)
    t2_due = sorted(due_ids & t2_ids)
    t3_due = sorted(due_ids & t3_ids)

    # 按优先级排序：T1 → T2 → T3
    ordered_ids = t1_due + t2_due + t3_due

    # 每日上限
    limit = sched.get_daily_limit() if (not is_sprint and not is_pre30) else plan["daily_quota"]
    ordered_ids = ordered_ids[:limit]

    # ── 按知识领域分组 ──
    area_groups: dict[str, list[dict]] = {}
    for eid in ordered_ids:
        error = next((e for e in errors if e.get("id") == eid), None)
        if error is None:
            continue
        area = error.get("knowledge_area", "未分类")
        area_groups.setdefault(area, []).append(error)

    lines.insert(3, f"📌 今日推送 {len(ordered_ids)}/{len(due_ids)} 题（上限 {limit} 题）")
    lines.insert(4, "")

    # ── 分层标记 ──
    tier_labels: dict[int, str] = {}
    for t in tiers["T1"]:
        tier_labels[t.error_id] = "🔴"
    for t in tiers["T2"]:
        tier_labels[t.error_id] = "🟡"
    for t in tiers["T3"]:
        tier_labels[t.error_id] = "🟢"

    for area in sorted(area_groups.keys(), key=lambda a: -len(area_groups[a])):
        items = area_groups[area]
        lines.append(f"\n### {area}（{len(items)} 题）")
        for e in items:
            q = e.get("question", "")[:60]
            tier_mark = tier_labels.get(e["id"], "")
            lines.append(f"- {tier_mark} #{e['id']} {q}...")
        lines.append("")

    # ── 非冲刺/非 pre30 模式：提示 T3 低频错题数量 ──
    if not is_sprint and not is_pre30 and t3_ids:
        t3_due_today = len(t3_ids & due_ids)
        if t3_due_today > 0:
            lines.append(f"📦 {t3_due_today} 道低频错题已推迟到考前冲刺包（考前 7 天推送）")

    lines.append("---")
    lines.append("以上为题号清单。交互出题时逐题展示，不泄露答案。")

    return "\n".join(lines)


def _collect_due_ids(
    errors: list,
    review: dict,
    bank: list,
    today_str: str,
) -> list[int]:
    """收集今日到期需复习的错题 ID（与 review_today 逻辑一致）"""
    due_ids: set[int] = set()

    for e in errors:
        if e.get("date") == today_str:
            due_ids.add(e["id"])

    for card in review.values():
        if card.get("next_date", "9999") <= today_str:
            due_ids.add(card.get("error_id"))

    for r in bank:
        if r.get("date") == today_str and r.get("is_correct") is False:
            eid = r.get("error_log_id")
            if eid is not None:
                due_ids.add(eid)

    return sorted(due_ids)


def _is_reviewed_today(card: dict | None, today_str: str) -> bool:
    """今日是否已复习过（history 中有今日 quality>0 记录）"""
    if not card:
        return False
    for h in card.get("history", []):
        if h.get("date") == today_str and h.get("quality", 0) > 0:
            return True
    return False


def _has_options(text: str) -> bool:
    return bool(_OPTION_RE.search(text or ""))


def _load_options_supplement() -> dict:
    if not OPTIONS_SUPPLEMENT.exists():
        return {}
    try:
        data = json.loads(OPTIONS_SUPPLEMENT.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _merge_options(question: str, error_id: int) -> str:
    """题干缺选项时，从 supplement 或分字段 options 补全"""
    if _has_options(question):
        return question.strip()

    supplement = _load_options_supplement()
    entry = supplement.get(str(error_id)) or supplement.get(error_id)
    if not entry:
        return question.strip()

    if isinstance(entry, str):
        opts = entry.strip()
    elif isinstance(entry, dict):
        opts = entry.get("options", "").strip()
        if not opts and all(k in entry for k in "ABCD"):
            opts = "\n".join(f"{k}. {entry[k]}" for k in "ABCD")
    else:
        return question.strip()

    if not opts:
        return question.strip()

    if _has_options(opts):
        # supplement 已是完整题干+选项
        if len(opts) > len(question):
            return opts
        return f"{question.strip()}\n{opts}"

    return f"{question.strip()}\n{opts}"


def _find_full_question(error_id: int, errors: list, bank: list) -> dict:
    """优先从题库/错题本取含选项的完整题干"""
    bank_entries = [r for r in bank if r.get("error_log_id") == error_id]
    error = next((e for e in errors if e.get("id") == error_id), None)
    candidates: list[dict] = list(bank_entries)
    if error:
        candidates.append(error)

    if not candidates:
        return {}

    with_opts = [r for r in candidates if _has_options(r.get("question", ""))]
    record = max(with_opts or candidates, key=lambda r: len(r.get("question", "")))

    merged = dict(record)
    merged["question"] = _merge_options(record.get("question", ""), error_id)
    return merged


def _format_review_question(error_id: int, record: dict) -> str:
    """格式化单道复习题（不含答案、解析、历史作答）"""
    area = record.get("knowledge_area", "综合")
    question = record.get("question", "").strip()
    lines = [f"📝 复习 #{error_id} [{area}]", question]
    if not _has_options(question):
        lines.append("")
        lines.append("⚠️ 本题选项缺失，无法作答")
        lines.append("  ① 回复「补录 #{}」手动补录选项".format(error_id))
        lines.append("  ② 回复「跳过」暂时跳过，排到队列末尾")
    return "\n".join(lines)


def _format_option_missing_knowledge(error_id: int, record: dict) -> str:
    """选项缺失时的「知识点回顾」模式降级输出。"""
    try:
        from pmp_athena.error_insights import build_summary, build_mnemonic
    except ImportError:
        from error_insights import build_summary, build_mnemonic
    area = record.get("knowledge_area", "综合")
    summary = build_summary(record)
    mnemonic = build_mnemonic(record)
    lines = [
        f"📖 本题选项缺失，转为知识点回顾",
        f"📌 核心考点：[{area}]",
        f"💡 正确思路：{summary}",
        f"🎯 口诀：{mnemonic}",
        "",
        "💬 回复「已掌握」继续下一题，回复「未掌握」标记明天再复习。",
    ]
    return "\n".join(lines)


def _enhance_high_frequency_question(error_id: int, record: dict) -> str:
    """高频错题增强格式：锚点 + 等级 + 根因诊断 + 演化洞察 + 口诀 + 变式预告"""
    try:
        from pmp_athena.error_insights import (
            count_mistakes, build_mnemonic, is_high_frequency_marked,
        )
    except ImportError:
        from error_insights import (
            count_mistakes, build_mnemonic, is_high_frequency_marked,
        )
    try:
        from pmp_athena.root_cause_engine import diagnose as rc_diagnose, format_root_cause_card
    except ImportError:
        from root_cause_engine import diagnose as rc_diagnose, format_root_cause_card
    try:
        from pmp_athena.semantic_anchors import format_anchor_with_cue
    except ImportError:
        from semantic_anchors import format_anchor_with_cue
    try:
        from pmp_athena.error_evolution import format_evolution_summary, format_evolution_report
    except ImportError:
        from error_evolution import format_evolution_summary, format_evolution_report

    mistake_info = count_mistakes(error_id)
    total_wrong = mistake_info["total"]

    # 上次错误记录
    bank = load_json(QUESTION_BANK)
    if not isinstance(bank, list):
        bank = []
    wrong_records = sorted(
        [r for r in bank if r.get("error_log_id") == error_id and r.get("is_correct") is False],
        key=lambda r: r.get("date", ""),
        reverse=True,
    )
    last_wrong = wrong_records[0] if wrong_records else record

    # 根因诊断
    root_cause = rc_diagnose(record, wrong_records)

    # 锚点话术（优先显示）
    try:
        anchor_text = format_anchor_with_cue(record, wrong_records)
    except Exception:
        anchor_text = ""

    # 口诀
    mnemonic = build_mnemonic(record)

    # 演化洞察（≥3 次时显示）
    evolution_text = ""
    if total_wrong >= 3:
        try:
            evolution_text = format_evolution_summary(error_id)
        except Exception:
            pass

    area = record.get("knowledge_area", "综合")
    question = record.get("question", "").strip()

    lines = []
    if anchor_text:
        lines.append(anchor_text)
        lines.append("")

    lines.extend([
        f"📌 错题等级：🔥 高频错题（已错 {total_wrong} 次）",
        f"📖 你的错误记录：上次错选 {last_wrong.get('my_answer', '?')}"
        f"（正确 {last_wrong.get('correct_answer', '?')}）",
    ])
    if root_cause:
        lines.append(f"⚠️ 根因诊断：{format_root_cause_card(root_cause)}")
    lines.append(f"🎯 破解口诀：{mnemonic}")
    if evolution_text:
        lines.append(f"🧬 {evolution_text}")
    lines.append("")
    lines.append(f"📝 复习 #{error_id} [{area}]")
    lines.append(question)
    if not _has_options(question):
        lines.append("")
        lines.append("⚠️ 本题选项缺失，无法作答")
        lines.append("  ① 回复「补录 #{}」手动补录选项".format(error_id))
        lines.append("  ② 回复「跳过」暂时跳过，排到队列末尾")
    else:
        lines.append("")
        if root_cause:
            rc_name = root_cause.get("name", "")
            lines.append(f"💡 根因变式（必做）：答对后将推送 ≥3 道「{rc_name}」类变式题，答对 ≥2/3 过关。")
        else:
            lines.append("💡 同类变式（必做）：本题为高频错题，答对后将推送 ≥3 道变式题巩固。")

    return "\n".join(lines)


def _enhance_stubborn_question(error_id: int, record: dict) -> str:
    """高频顽疾深度拆解格式：锚点 + 等级 + 每次错选记录 + 根因诊断 + 口诀 + 反向训练预告"""
    try:
        from pmp_athena.error_insights import count_mistakes, build_mnemonic
    except ImportError:
        from error_insights import count_mistakes, build_mnemonic
    try:
        from pmp_athena.root_cause_engine import diagnose as rc_diagnose, format_root_cause_card
    except ImportError:
        from root_cause_engine import diagnose as rc_diagnose, format_root_cause_card
    try:
        from pmp_athena.semantic_anchors import format_anchor_with_cue
    except ImportError:
        from semantic_anchors import format_anchor_with_cue

    mistake_info = count_mistakes(error_id)
    total_wrong = mistake_info["total"]

    # 全部错选记录（按日期正序，展示每次错选）
    bank = load_json(QUESTION_BANK)
    if not isinstance(bank, list):
        bank = []
    wrong_records = sorted(
        [r for r in bank if r.get("error_log_id") == error_id and r.get("is_correct") is False],
        key=lambda r: r.get("date", ""),
    )

    # 根因诊断
    root_cause = rc_diagnose(record, wrong_records)

    # 锚点话术（优先显示）
    try:
        anchor_text = format_anchor_with_cue(record, wrong_records)
    except Exception:
        anchor_text = ""

    # 口诀
    mnemonic = build_mnemonic(record)

    area = record.get("knowledge_area", "综合")
    question = record.get("question", "").strip()

    lines = []
    if anchor_text:
        lines.append(anchor_text)
        lines.append("")

    lines.append(f"📌 错题等级：🔥 高频顽疾（已错 {total_wrong} 次）")
    lines.append("📖 错误记录：")
    for i, wr in enumerate(wrong_records, 1):
        d = str(wr.get("date", ""))[:10]
        lines.append(
            f"  第{i}次 · {d}: 错选 {wr.get('my_answer', '?')}"
            f"（正确 {wr.get('correct_answer', '?')}）"
        )
    if root_cause:
        lines.append(f"⚠️ 根因诊断：{format_root_cause_card(root_cause)}")
    lines.append(f"🎯 破解口诀：{mnemonic}")
    lines.append("")
    lines.append(f"📝 复习 #{error_id} [{area}]")
    lines.append(question)
    if not _has_options(question):
        lines.append("")
        lines.append("⚠️ 本题选项缺失，无法作答")
        lines.append("  ① 回复「补录 #{}」手动补录选项".format(error_id))
        lines.append("  ② 回复「跳过」暂时跳过，排到队列末尾")
    else:
        lines.append("")
        lines.append("💡 反向训练（必做）：答对后推送同考点变式题，连续答对 2 道才移出高频列表。")

    return "\n".join(lines)


def review_next(*, include_header: bool = False) -> dict:
    """
    获取下一道待复习错题（微信硬路由用）。
    返回 dict: status, error_id, total_due, remaining, text
    """
    errors = load_json(ERROR_LOG)
    review = load_json(REVIEW_STATE)
    bank = load_json(QUESTION_BANK)

    if not isinstance(errors, list):
        errors = []
    if not isinstance(review, dict):
        review = {}
    if not isinstance(bank, list):
        bank = []

    today_str = date.today().isoformat()
    due_ids = _collect_due_ids(errors, review, bank, today_str)

    if not due_ids:
        return {
            "status": "empty",
            "error_id": None,
            "total_due": 0,
            "remaining": 0,
            "text": "✅ 今日暂无待复习错题，继续保持！",
        }

    pending = [
        eid for eid in due_ids
        if not _is_reviewed_today(review.get(str(eid)), today_str)
    ]

    if not pending:
        return {
            "status": "done",
            "error_id": None,
            "total_due": len(due_ids),
            "remaining": 0,
            "text": f"✅ 今日 {len(due_ids)} 道错题已全部复习完毕！",
        }

    error_id = pending[0]
    record = _find_full_question(error_id, errors, bank)
    if not record:
        return {
            "status": "error",
            "error_id": error_id,
            "total_due": len(due_ids),
            "remaining": len(pending),
            "text": f"⚠️ 错题 #{error_id} 未找到题目内容",
        }

    # 高频错题检测
    try:
        from pmp_athena.error_insights import (
            is_high_frequency, is_high_frequency_marked, mark_high_frequency,
            count_mistakes,
        )
    except ImportError:
        from error_insights import (
            is_high_frequency, is_high_frequency_marked, mark_high_frequency,
            count_mistakes,
        )
    is_hf = is_high_frequency_marked(error_id) or is_high_frequency(error_id, threshold=3)
    # 高频顽疾判定：累计错误 ≥4 次
    is_stubborn = count_mistakes(error_id)["total"] >= 4

    if is_stubborn:
        if not is_high_frequency_marked(error_id):
            mark_high_frequency(error_id)
        body = _enhance_stubborn_question(error_id, record)
    elif is_hf:
        if not is_high_frequency_marked(error_id):
            mark_high_frequency(error_id)
        body = _enhance_high_frequency_question(error_id, record)
    else:
        body = _format_review_question(error_id, record)

    # 进度行：已完成 / 总到期数
    done_count = len(due_ids) - len(pending)
    progress = f"[{done_count}/{len(due_ids)}]"

    # ── 每日上限检查 ──
    try:
        from pmp_athena.review_scheduler import ReviewScheduler
    except ImportError:
        from review_scheduler import ReviewScheduler
    sched = ReviewScheduler()
    limit = sched.get_daily_limit()
    is_sprint = sched.should_activate_sprint()
    is_pre30 = sched.should_activate_pre30()
    if is_sprint:
        plan = sched.build_daily_plan(is_pre_exam=True)
        limit = plan["daily_quota"]
    elif is_pre30:
        plan = sched.build_daily_plan(is_pre30=True)
        limit = plan["daily_quota"]
    completed_today = sched.get_today_completed_count()

    if completed_today >= limit and include_header:
        # 已达上限：显示完成卡片
        text = sched.format_daily_done_card()
        text += "\n\n" + sched.format_progress_bar()
        return {
            "status": "limit_reached",
            "error_id": None,
            "total_due": len(due_ids),
            "remaining": len(pending),
            "text": text,
        }

    if include_header:
        sprint_tag = "🔥 冲刺" if is_sprint else ("⚡ 30天" if is_pre30 else "")
        limit_hint = f"（今日上限 {limit} 题，已完成 {completed_today}/{limit}）{sprint_tag}"
        # 高频顽疾统计（累计错误 ≥4 次的到期错题）
        stubborn_count = sum(1 for eid in pending if count_mistakes(eid)["total"] >= 4)
        stubborn_line = f"\n🔥 高频顽疾：{stubborn_count} 道待攻克" if stubborn_count > 0 else ""
        text = (
            f"📚 今日待复习错题: {len(due_ids)} 道（还剩 {len(pending)} 道）{limit_hint}"
            f"{stubborn_line}\n\n"
            f"{body}"
        )
    else:
        text = f"{progress}\n{body}"

    return {
        "status": "question",
        "error_id": error_id,
        "total_due": len(due_ids),
        "remaining": len(pending),
        "text": text,
        "is_high_frequency": is_hf,
    }


def grade_review(error_id: int, user_answer: str) -> dict:
    """判卷并返回下一题（微信硬路由用）。

    支持高频错题变式触发、选项缺失知识回顾、跳过等子模式。
    """
    import sys
    from pathlib import Path
    _pkg = Path(__file__).resolve().parent
    if str(_pkg) not in sys.path:
        sys.path.insert(0, str(_pkg))
    from spaced_repetition import SpacedRepetition

    errors = load_json(ERROR_LOG)
    if not isinstance(errors, list):
        errors = []
    bank = load_json(QUESTION_BANK)
    if not isinstance(bank, list):
        bank = []

    error = next((e for e in errors if e.get("id") == error_id), None)
    if error is None:
        return {
            "status": "error",
            "correct": False,
            "error_id": error_id,
            "text": f"⚠️ 错题 #{error_id} 不存在",
        }

    user_ans = user_answer.strip().upper()
    correct_ans = str(error.get("correct_answer", "")).strip().upper()
    is_correct = user_ans == correct_ans

    # ── 根因变式 v2 指令路由（仅在根因诊断成功时触发）──
    user_ans_lower = user_answer.strip()
    if user_ans_lower in ("总结", "模拟") or user_ans_lower.startswith("陷阱=") or (
        user_ans_lower == "已掌握" and _has_root_cause(error)
    ):
        try:
            from pmp_athena.root_cause_variants import handle_variant_command
        except ImportError:
            from root_cause_variants import handle_variant_command

        # Resolve root cause name from the current error
        rc_name = ""
        try:
            from pmp_athena.root_cause_engine import diagnose
        except ImportError:
            from root_cause_engine import diagnose
        diag = diagnose(error)
        if diag:
            rc_name = diag.get("name", "")

        cmd_result = handle_variant_command(error_id, user_ans_lower, rc_name)
        return {
            "status": cmd_result["status"],
            "correct": cmd_result.get("correct", None),
            "error_id": error_id,
            "text": cmd_result["text"],
        }

    # ── 特殊模式：知识回顾（选项缺失时用户回复「已掌握」/「未掌握」）──
    if user_ans in ("已掌握", "未掌握"):
        sr = SpacedRepetition()
        quality = 5 if user_ans == "已掌握" else 1
        sr.grade(error_id, quality)
        lines = ["✅ 已记录！" if user_ans == "已掌握" else "📌 已标记，明天再复习。"]
        nxt = review_next(include_header=False)
        if nxt["status"] == "question":
            lines.append("")
            lines.append(nxt["text"])
        else:
            lines.append("")
            lines.append(nxt["text"])
        return {
            "status": "graded",
            "correct": user_ans == "已掌握",
            "error_id": error_id,
            "next_error_id": nxt.get("error_id"),
            "done": nxt["status"] in ("done", "empty"),
            "text": "\n".join(lines),
        }

    sr = SpacedRepetition()
    sr.grade(error_id, 5 if is_correct else 1)

    # ── 错题演化追踪（每次答错时记录）──
    if not is_correct:
        try:
            from pmp_athena.error_evolution import record_error as ev_record
        except ImportError:
            from error_evolution import record_error as ev_record
        ev_record(error_id, user_ans)

    lines: list[str] = []
    if is_correct:
        lines.append("✅ 正确！")
    else:
        try:
            from pmp_athena.error_insights import format_wrong_feedback
        except ImportError:
            from error_insights import format_wrong_feedback
        lines.append(format_wrong_feedback(error, user_answer=user_ans))

    # ── 高频错题变式触发 ──
    if is_correct:
        try:
            from pmp_athena.error_insights import (
                is_high_frequency_marked, unmark_high_frequency, count_mistakes,
            )
        except ImportError:
            from error_insights import (
                is_high_frequency_marked, unmark_high_frequency, count_mistakes,
            )
        if is_high_frequency_marked(error_id):
            # 高频顽疾判定：累计错误 ≥4 次
            is_stubborn = count_mistakes(error_id)["total"] >= 4
            state = sr._read_state()
            card = state.get(str(error_id), {})
            consec = card.get("consecutive_correct", 0)

            # 普通高频错题：连续正确 ≥2 → 直接 unmark，跳过变式
            # 高频顽疾：必须走变式，只有连续答对 2 道变式才移除
            if not is_stubborn and consec >= 2:
                unmark_high_frequency(error_id)
                sr.update_high_frequency_status(error_id, False)
                lines.append("🏆 连续 2 次正确，已取消高频错题标记！")
            else:
                # 触发变式子模式（升级版：防重复 + 降级总结 + 实战模拟）
                try:
                    from pmp_athena.root_cause_variants import review_variant_start_v2
                except ImportError:
                    from root_cause_variants import review_variant_start_v2
                variant_result = review_variant_start_v2(error_id)
                rc_name = variant_result.get("root_cause", "")
                if variant_result["status"] == "variant_question":
                    lines.append("")
                    lines.append(variant_result["text"])
                    return {
                        "status": "graded_variant_pending",
                        "correct": True,
                        "error_id": error_id,
                        "variant_ids": variant_result.get("variant_ids", []),
                        "variant_index": variant_result.get("variant_index", 0),
                        "variant_correct": variant_result.get("variant_correct", 0),
                        "variant_total": variant_result.get("variant_total", 0),
                        "variant_sub_mode": "question",
                        "text": "\n".join(lines),
                    }
                elif variant_result["status"] == "root_cause_summary":
                    lines.append("")
                    lines.append(variant_result["text"])
                    return {
                        "status": "graded_variant_pending",
                        "correct": True,
                        "error_id": error_id,
                        "variant_sub_mode": "summary",
                        "root_cause": rc_name,
                        "text": "\n".join(lines),
                    }
                elif variant_result["status"] == "insufficient":
                    lines.append("")
                    lines.append(variant_result["text"])
                    # 变式题不足：普通高频错题降级为连续正确 unmark；高频顽疾保留标记
                    if not is_stubborn and consec >= 1:
                        unmark_high_frequency(error_id)
                        sr.update_high_frequency_status(error_id, False)
                        lines.append("🏆 该领域变式题不足，已按连续正确判定，取消高频标记！")
                    elif is_stubborn:
                        lines.append("⚠️ 高频顽疾变式题不足，暂不移除标记，待题库补充变式题。")

    nxt = review_next(include_header=False)
    if nxt["status"] == "question":
        lines.append("")
        lines.append(nxt["text"])
    elif nxt["status"] in ("done", "empty"):
        lines.append("")
        lines.append(_build_done_summary(nxt))

    return {
        "status": "graded",
        "correct": is_correct,
        "error_id": error_id,
        "next_error_id": nxt.get("error_id"),
        "done": nxt["status"] in ("done", "empty"),
        "text": "\n".join(lines),
    }


# ── 辅助：今日复习完成汇总 ──────────────────────────────────


def _build_done_summary(nxt: dict) -> str:
    """生成复习完毕的统计行，含进度预估。"""
    review_state = load_json(REVIEW_STATE)
    nxt_text = nxt.get("text", "")
    if isinstance(review_state, dict):
        today_reviews = []
        for card in review_state.values():
            if isinstance(card, dict):
                for h in card.get("history", []):
                    if h.get("date") == date.today().isoformat() and h.get("quality", 0) > 0:
                        today_reviews.append(h["quality"])
        if today_reviews:
            correct = sum(1 for q in today_reviews if q >= 4)
            total = len(today_reviews)
            pct = correct / total * 100 if total > 0 else 0
            if "复习完毕" in nxt_text:
                nxt_text = nxt_text.replace("复习完毕", f"复习完毕！正确率 {pct:.0f}%（{correct}/{total}）")

    # ── 附加进度预估 ──
    try:
        from pmp_athena.review_scheduler import ReviewScheduler
    except ImportError:
        from review_scheduler import ReviewScheduler
    sched = ReviewScheduler()
    nxt_text += "\n\n" + sched.format_progress_bar()

    return nxt_text


# ── 高频错题变式巩固（根因驱动）─────────────────────────────────────


def _score_variant_by_root_cause(variant_question: str, root_cause_name: str) -> float:
    """按根因关键词匹配度给变式题打分。score=1.0 表示完全匹配根因。"""
    if not root_cause_name:
        return 0.0
    # 根因关键字提取（去除常见虚词）
    cause_keywords = set(re.findall(r"[一-鿿]{2,}", root_cause_name))
    q_words = set(re.findall(r"[一-鿿]{2,}", variant_question))
    if not cause_keywords:
        return 0.5
    overlap = len(cause_keywords & q_words)
    # 每命中 2 个关键词 +0.25，最多 1.0
    return min(1.0, 0.5 + overlap * 0.25)


def _review_variant_start(error_id: int) -> dict:
    """启动高频错题的根因驱动变式巩固。返回 ≥3 道变式题的第一道。

    升级逻辑：
    - 优先按根因类型（而非知识领域）筛题
    - 变式题至少 3 道，选项包含根因相关迷惑项
    - 答对 ≥2/3 为过关
    """
    errors = load_json(ERROR_LOG)
    if not isinstance(errors, list):
        errors = []
    error = next((e for e in errors if e.get("id") == error_id), None)
    if error is None:
        return {"status": "error", "text": f"⚠️ 错题 #{error_id} 不存在"}

    # 根因诊断
    root_cause_name = ""
    try:
        from pmp_athena.root_cause_engine import diagnose
    except ImportError:
        from root_cause_engine import diagnose
    diag = diagnose(error)
    if diag:
        root_cause_name = diag.get("name", "")

    area = error.get("knowledge_area", "")
    if not area and not root_cause_name:
        return {"status": "insufficient", "text": "⚠️ 该题无知识领域标记，无法生成变式题。"}

    try:
        from pmp_athena.question_bank import QuestionBank
    except ImportError:
        from question_bank import QuestionBank

    qb = QuestionBank()

    # 策略1：按知识领域取候选池（扩大到 15 道以便筛选）
    candidates = qb.list_by_area_excluding(area, error_id, limit=15) if area else []
    if not candidates:
        # 策略2：无领域标记 → 从全量取候选
        candidates = qb.list_recent_excluding(error_id, limit=15)

    # 按根因打分排序
    if root_cause_name and candidates:
        scored = [
            (c, _score_variant_by_root_cause(
                str(c.get("question", "")), root_cause_name,
            ))
            for c in candidates
        ]
        scored.sort(key=lambda x: -x[1])
        candidates = [c for c, _ in scored]

    # 取前 3 道（至少 2 道）
    variants = candidates[:3]
    if len(variants) < 2:
        return {
            "status": "insufficient",
            "text": (f"⚠️ 变式题池不足（仅{len(variants)}道），跳过变式环节。" +
                     (" 继续刷题积累更多题目后可启动。" if area else "")),
            "variant_count": len(variants),
        }

    variant_ids = [v.get("id") for v in variants]
    first = variants[0]
    q_text = first.get("question", "").strip()
    v_area = first.get("knowledge_area", area)

    # 标注变式来源
    source_note = ""
    if root_cause_name:
        source_note = f"（根因：「{root_cause_name}」）"

    lines = [
        f"💡 根因变式巩固（第 1/{len(variant_ids)} 题）{source_note}",
        f"[{v_area}] {q_text}",
        "",
        "请回复 A/B/C/D 作答。",
    ]

    return {
        "status": "variant_question",
        "error_id": error_id,
        "variant_ids": variant_ids,
        "variant_index": 0,
        "variant_total": len(variant_ids),
        "variant_correct": 0,
        "root_cause": root_cause_name,
        "text": "\n".join(lines),
    }


def review_variant_start(error_id: int) -> dict:
    """CLI 入口：与 _review_variant_start 相同。"""
    return _review_variant_start(error_id)


def grade_variant_answer(
    error_id: int,
    variant_index: int,
    user_answer: str,
    variant_ids: list[int],
    variant_correct: int,
) -> dict:
    """判卷一道变式题，返回下一道变式题或完成结果。"""
    import sys
    from pathlib import Path
    _pkg = Path(__file__).resolve().parent
    if str(_pkg) not in sys.path:
        sys.path.insert(0, str(_pkg))

    try:
        from pmp_athena.question_bank import QuestionBank
        from pmp_athena.spaced_repetition import SpacedRepetition
        from pmp_athena.error_insights import is_high_frequency_marked, unmark_high_frequency
    except ImportError:
        from question_bank import QuestionBank
        from spaced_repetition import SpacedRepetition
        from error_insights import is_high_frequency_marked, unmark_high_frequency

    qb = QuestionBank()
    sr = SpacedRepetition()

    if variant_index >= len(variant_ids):
        return {"status": "error", "text": "⚠️ 变式题序号超出范围"}

    current_variant_id = variant_ids[variant_index]
    variant_record = qb.get_by_id(current_variant_id)

    if not variant_record:
        return {"status": "error", "text": f"⚠️ 变式题 #{current_variant_id} 未找到"}

    correct_ans = str(variant_record.get("correct_answer", "")).strip().upper()
    my_ans = user_answer.strip().upper()
    is_correct = my_ans == correct_ans
    new_correct = variant_correct + (1 if is_correct else 0)

    if is_correct:
        feedback = "✅ 正确！"
    else:
        expl = str(variant_record.get("explanation", ""))[:200]
        feedback = (
            f"❌ 正确答案是 {correct_ans}（你选了 {my_ans}）\n"
            f"💡 {expl}"
        )

    next_index = variant_index + 1

    if next_index >= len(variant_ids):
        # 全部变式完成 → 判定
        passed = new_correct >= 2
        total = len(variant_ids)
        lines = [feedback]
        lines.append(f"\n📊 变式巩固完成：正确 {new_correct}/{total}")

        if passed:
            lines.append("✅ 变式通过！")
            # 检查是否可以 unmark
            state = sr._read_state()
            card = state.get(str(error_id), {})
            consec = card.get("consecutive_correct", 0)
            if consec >= 2 and is_high_frequency_marked(error_id):
                unmark_high_frequency(error_id)
                sr.update_high_frequency_status(error_id, False)
                lines.append("🏆 连续 2 次正确 + 变式通过，已取消高频错题标记！")
            else:
                lines.append(f"💡 再答对 {2 - consec} 次即可取消高频标记。")
        else:
            lines.append("⚠️ 变式未达标（需 ≥2/3 正确），保留高频标记，继续加油！")

        # 返回下一道复习题
        nxt = review_next(include_header=False)
        if nxt["status"] == "question":
            lines.append("")
            lines.append(nxt["text"])
        else:
            lines.append("")
            lines.append(_build_done_summary(nxt))

        return {
            "status": "variant_done",
            "correct": is_correct,
            "variant_correct": new_correct,
            "variant_total": total,
            "passed": passed,
            "next_error_id": nxt.get("error_id"),
            "done": nxt["status"] in ("done", "empty"),
            "text": "\n".join(lines),
        }

    # 还有下一道变式题
    next_variant = qb.get_by_id(variant_ids[next_index])
    if next_variant:
        area = next_variant.get("knowledge_area", "综合")
        q_text = next_variant.get("question", "").strip()
        lines = [feedback]
        lines.append(f"\n💡 根因变式巩固（第 {next_index + 1}/{len(variant_ids)} 题）")
        lines.append(f"[{area}] {q_text}")
        lines.append("\n请回复 A/B/C/D 作答。")
    else:
        lines = [feedback, "⚠️ 下一道变式题未找到"]

    return {
        "status": "variant_question",
        "correct": is_correct,
        "variant_ids": variant_ids,
        "variant_index": next_index,
        "variant_correct": new_correct,
        "variant_total": len(variant_ids),
        "text": "\n".join(lines),
    }


def review_skip_current(error_id: int) -> dict:
    """跳过当前题（排到明天），返回下一道复习题。

    连续跳过 3 次 → 自动降级为「知识点回顾」模式。
    """
    import sys
    from pathlib import Path
    _pkg = Path(__file__).resolve().parent
    if str(_pkg) not in sys.path:
        sys.path.insert(0, str(_pkg))
    from spaced_repetition import SpacedRepetition

    sr = SpacedRepetition()
    state = sr._read_state()
    key = str(error_id)

    # 跟踪跳过次数
    if key in state:
        state[key]["next_date"] = (date.today() + timedelta(days=1)).isoformat()
        state[key]["skip_count"] = state[key].get("skip_count", 0) + 1
        state[key]["consecutive_skips"] = state[key].get("consecutive_skips", 0) + 1
        total_skips = state[key]["skip_count"]
        sr._write_state(state)
    else:
        total_skips = 1

    # 连续跳过 3 次 → 降级为知识回顾
    is_knowledge_review = total_skips >= 3
    errors = load_json(ERROR_LOG)
    if not isinstance(errors, list):
        errors = []
    error = next((e for e in errors if e.get("id") == error_id), None)

    nxt = review_next(include_header=False)
    lines = [
        f"⏭️ 已跳过 #{error_id}，排到明天复习。",
    ]

    if is_knowledge_review and error:
        # 降级为知识回顾模式
        from pmp_athena.error_insights import build_summary, build_mnemonic
        area = error.get("knowledge_area", "综合")
        summary = build_summary(error)
        mnemonic = build_mnemonic(error)
        lines.append(f"\n⚠️ 已连续跳过 {total_skips} 次，降级为知识点回顾：")
        lines.append(f"📌 核心考点：[{area}]")
        lines.append(f"💡 正确思路：{summary}")
        lines.append(f"🎯 口诀：{mnemonic}")
        lines.append("\n💬 回复「已掌握」继续，回复「未掌握」标记明天再复习。")
    else:
        if nxt["status"] == "question":
            lines.append("")
            lines.append(nxt["text"])
        elif nxt["status"] in ("done", "empty"):
            lines.append("")
            lines.append(_build_done_summary(nxt))

    return {
        "status": "skipped",
        "error_id": error_id,
        "next_error_id": nxt.get("error_id"),
        "done": nxt["status"] in ("done", "empty") if not is_knowledge_review else False,
        "is_knowledge_review": is_knowledge_review,
        "text": "\n".join(lines),
    }


# ═══════════════════════════════════════════════════════════
# 3. 制定学习计划
# ═══════════════════════════════════════════════════════════

def generate_plan(custom_days: int = 0) -> str:
    """生成智能学习计划"""
    exam_date = get_exam_date()
    today = date.today()
    bank = load_json(QUESTION_BANK)
    review = load_json(REVIEW_STATE)

    if not isinstance(bank, list):
        bank = []
    if not isinstance(review, dict):
        review = {}

    lines = []
    lines.append("📋 PMP 智能学习计划")
    lines.append("=" * 30)

    # ── 倒计时 ──
    if exam_date:
        remaining = (exam_date - today).days
    else:
        remaining = 47  # 默认
        exam_date = today + timedelta(days=remaining)

    if custom_days > 0:
        plan_days = custom_days
    else:
        plan_days = min(remaining, 14)  # 默认规划两周

    phase = get_current_phase(today)
    milestone = get_phase_milestone(remaining)

    lines.append(f"\n📅 考试日期: {exam_date.isoformat()}")
    lines.append(f"⏳ 倒计时: **{remaining} 天**")
    lines.append(f"📍 当前阶段: {phase['icon']} {phase['name']} · 距下阶段还有 {phase['remaining_days']} 天")
    if milestone:
        lines.append(f"{milestone}")
    lines.append(f"📐 计划跨度: {plan_days} 天（{today.isoformat()} ~ {(today + timedelta(days=plan_days)).isoformat()}）")

    # ── 当前状态 ──
    total_q = len(bank)
    wrong_q = sum(1 for r in bank if r.get("is_correct") is False)
    correct_q = sum(1 for r in bank if r.get("is_correct") is True)
    accuracy = correct_q / (correct_q + wrong_q) if (correct_q + wrong_q) > 0 else 0

    overdue = sum(1 for v in review.values() if v.get("next_date", "9999") <= today.isoformat())
    total_review = len(review)

    lines.append(f"\n## 📊 当前状态\n")
    lines.append(f"| 指标 | 数据 |")
    lines.append(f"|------|------|")
    lines.append(f"| 总做题量 | {total_q} |")
    lines.append(f"| 当前正确率 | {accuracy:.0%} |")
    lines.append(f"| 错题本存量 | {wrong_q} |")
    lines.append(f"| SM-2 逾期复习 | {overdue} / {total_review} |")

    # ── 薄弱领域 ──
    area_stats: dict[str, dict] = {}
    for r in bank:
        area = r.get("knowledge_area", "未分类")
        if area not in area_stats:
            area_stats[area] = {"total": 0, "correct": 0, "wrong": 0}
        area_stats[area]["total"] += 1
        if r.get("is_correct") is True:
            area_stats[area]["correct"] += 1
        elif r.get("is_correct") is False:
            area_stats[area]["wrong"] += 1

    weak_list = []
    for area, s in area_stats.items():
        judged = s["correct"] + s["wrong"]
        if judged >= 2:
            rate = s["wrong"] / judged
            weak_list.append((area, rate))
    weak_list.sort(key=lambda x: x[1], reverse=True)

    if weak_list:
        lines.append(f"\n## 🎯 重点攻克领域\n")
        for area, rate in weak_list[:3]:
            lines.append(f"- **{area}**（错误率 {rate:.0%}）")

    # ── 每日任务 ──
    lines.append(f"\n## 📅 每日任务清单\n")
    lines.append("| 时段 | 任务 | 时长 |")
    lines.append("|------|------|------|")
    lines.append("| 🌅 早晨 | 温习昨日错题解析 | 15min |")
    lines.append("| ☀️ 上午 | 每日一练 10 题 + 精读解析 | 30min |")
    lines.append("| 🌤 下午 | 薄弱领域专项练习 10 题 | 25min |")
    lines.append("| 🌙 晚间 | SM-2 错题复习 + 评分 | 20min |")
    lines.append("| 📖 睡前 | 快速回顾今日 3 个关键概念 | 10min |")
    lines.append(f"\n**日均投入: 约 1.5 小时**")

    # ── 阶段规划 ──
    lines.append(f"\n## 🗺 阶段规划（{plan_days} 天）\n")

    phase1_days = max(1, plan_days // 3)
    phase2_days = max(1, plan_days // 3)
    phase3_days = plan_days - phase1_days - phase2_days

    lines.append(f"### 阶段一：补弱（前 {phase1_days} 天）")
    lines.append(f"- 集中攻克 TOP 3 薄弱领域")
    lines.append(f"- 每天保证 SM-2 错题复习清零")
    lines.append(f"- 目标：薄弱领域错误率降至 40% 以下")
    lines.append("")
    lines.append(f"### 阶段二：巩固（中间 {phase2_days} 天）")
    lines.append(f"- 真题模拟 + 错题归因")
    lines.append(f"- 敏捷场景专项突破")
    lines.append(f"- 目标：整体正确率稳定在 75%+")
    lines.append("")
    lines.append(f"### 阶段三：冲刺（最后 {phase3_days} 天）")
    lines.append(f"- 全真模拟考试节奏")
    lines.append(f"- 核心公式/概念最后过一遍")
    lines.append(f"- 目标：正确率 80%+，信心满满上考场")

    # ── 每日提醒 ──
    lines.append(f"\n## ⚠️ 每日坑位提醒\n")
    lines.append("1. 敏捷题：PM 是引导者，让团队自组织")
    lines.append("2. 资源题：先想'人'和'知识'，别绕到工具和钱")
    lines.append("3. 沟通题：先直接沟通，别绕弯查计划")
    lines.append("4. 干系人题：新干系人 → 先见面沟通，再更新登记册")
    lines.append("5. 题干问'首先'/'接下来' → 选最直接、最务实的选项")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="PMP 学习顾问")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("weakness", help="总结薄弱点")
    sub.add_parser("review-today", help="今日复习错题")

    p_next = sub.add_parser("review-next", help="获取下一道待复习错题（微信硬路由）")
    p_next.add_argument("--json", action="store_true", help="JSON 输出")
    p_next.add_argument("--header", action="store_true", help="附带今日待复习统计")

    p_grade = sub.add_parser("grade-review", help="复习错题判卷（微信硬路由）")
    p_grade.add_argument("error_id", type=int, help="错题 ID")
    p_grade.add_argument("answer", help="用户答案 A/B/C/D")
    p_grade.add_argument("--json", action="store_true", help="JSON 输出")

    p_plan = sub.add_parser("plan", help="制定学习计划")
    p_plan.add_argument("--days", "-d", type=int, default=0, help="计划跨度（天），默认14天")

    p_freq = sub.add_parser("frequent-errors", help="高频错题（总结+解答+口诀）")
    p_freq.add_argument("--top", type=int, default=5, help="显示 Top N")
    p_freq.add_argument("--json", action="store_true")

    p_vstart = sub.add_parser("variant-start", help="启动升级版根因变式巩固（v2）")
    p_vstart.add_argument("error_id", type=int, help="高频错题 ID")
    p_vstart.add_argument("--json", action="store_true")

    p_vgrade = sub.add_parser("variant-grade", help="变式题判卷")
    p_vgrade.add_argument("error_id", type=int, help="原高频错题 ID")
    p_vgrade.add_argument("variant_index", type=int, help="当前变式题序号（0 起）")
    p_vgrade.add_argument("answer", help="答案 A/B/C/D")
    p_vgrade.add_argument("variant_ids_json", help="变式题 ID 列表 JSON，如 [1,2,3]")
    p_vgrade.add_argument("variant_correct", type=int, help="当前已正确数")
    p_vgrade.add_argument("--json", action="store_true")

    p_skip = sub.add_parser("review-skip", help="跳过当前复习题（排到明天）")
    p_skip.add_argument("error_id", type=int, help="错题 ID")
    p_skip.add_argument("--json", action="store_true")

    p_sprint = sub.add_parser("sprint-plan", help="考前错题清零计划")
    p_sprint.add_argument("--json", action="store_true")

    p_layers = sub.add_parser("error-tiers", help="错题分层统计")
    p_layers.add_argument("--json", action="store_true")

    p_careless = sub.add_parser("mark-careless", help="标记为粗心错题（排除出队列）")
    p_careless.add_argument("error_id", type=int, help="错题 ID")

    args = parser.parse_args()

    if args.command == "sprint-plan":
        try:
            from pmp_athena.review_scheduler import ReviewScheduler
        except ImportError:
            from review_scheduler import ReviewScheduler
        sched = ReviewScheduler()
        if args.json:
            output = json.dumps(sched.build_sprint_plan(), ensure_ascii=False)
        else:
            output = sched.format_sprint_plan()
    elif args.command == "error-tiers":
        try:
            from pmp_athena.review_scheduler import ReviewScheduler
        except ImportError:
            from review_scheduler import ReviewScheduler
        sched = ReviewScheduler()
        tiers = sched.classify_all()
        if args.json:
            output = json.dumps({
                k: [{"error_id": t.error_id, "label": t.label, "mistakes": t.mistake_count}
                    for t in v]
                for k, v in tiers.items()
            }, ensure_ascii=False)
        else:
            lines = []
            for t, label in [("T1", "🔴 高频"), ("T2", "🟡 近期"), ("T3", "🟢 低频"), ("T0", "⚪ 粗心")]:
                items = tiers[t]
                lines.append(f"\n{label}（{len(items)} 题）")
                for it in items[:10]:
                    lines.append(f"  #{it.error_id} 错{it.mistake_count}次")
            output = "\n".join(lines)
    elif args.command == "mark-careless":
        try:
            from pmp_athena.review_scheduler import ReviewScheduler
        except ImportError:
            from review_scheduler import ReviewScheduler
        sched = ReviewScheduler()
        ok = sched.mark_as_careless(args.error_id)
        output = f"✅ 错题 #{args.error_id} 已标记为粗心，排除出复习队列" if ok else "❌ 失败"
    elif args.command == "weakness":
        output = analyze_weakness()
    elif args.command == "review-today":
        output = review_today()
    elif args.command == "review-next":
        result = review_next(include_header=args.header)
        if args.json:
            output = json.dumps(result, ensure_ascii=False)
        else:
            output = result["text"]
    elif args.command == "grade-review":
        result = grade_review(args.error_id, args.answer)
        if args.json:
            output = json.dumps(result, ensure_ascii=False)
        else:
            output = result["text"]
    elif args.command == "frequent-errors":
        try:
            from pmp_athena.error_insights import format_high_frequency_report
        except ImportError:
            from error_insights import format_high_frequency_report
        output = format_high_frequency_report(top_n=args.top)
        if args.json:
            output = json.dumps({"status": "ok", "text": output}, ensure_ascii=False)
    elif args.command == "plan":
        output = generate_plan(custom_days=args.days)
    elif args.command == "variant-start":
        try:
            from pmp_athena.root_cause_variants import review_variant_start_v2
        except ImportError:
            from root_cause_variants import review_variant_start_v2
        result = review_variant_start_v2(args.error_id)
        output = json.dumps(result, ensure_ascii=False) if args.json else result["text"]
    elif args.command == "variant-grade":
        variant_ids = json.loads(args.variant_ids_json)
        try:
            from pmp_athena.root_cause_variants import grade_variant_answer_v2
        except ImportError:
            from root_cause_variants import grade_variant_answer_v2
        rc = getattr(args, 'root_cause', '') if hasattr(args, 'root_cause') else ''
        result = grade_variant_answer_v2(
            args.error_id, args.variant_index, args.answer,
            variant_ids, args.variant_correct, root_cause_name=rc,
        )
        output = json.dumps(result, ensure_ascii=False) if args.json else result["text"]
    elif args.command == "review-skip":
        result = review_skip_current(args.error_id)
        output = json.dumps(result, ensure_ascii=False) if args.json else result["text"]
    else:
        output = analyze_weakness()

    # 显式用 UTF-8 编码输出，兼容 Windows GBK 控制台
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    try:
        print(output)
    except UnicodeEncodeError:
        # 回退：写入 bytes
        sys.stdout.buffer.write(output.encode("utf-8") + b"\n")


if __name__ == "__main__":
    main()
