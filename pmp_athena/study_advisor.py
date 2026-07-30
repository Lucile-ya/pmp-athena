#!/usr/bin/env python3
"""
学习顾问 —— 薄弱点分析、今日错题复习、智能学习计划

用法:
    python pmp_athena/study_advisor.py weakness       # 总结薄弱点
    python pmp_athena/study_advisor.py review-today    # 今日复习错题
    python pmp_athena/study_advisor.py plan            # 制定学习计划
    python pmp_athena/study_advisor.py plan --days 7   # 未来N天计划
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# ── 路径 ──────────────────────────────────────────────────
QUESTION_BANK = Path("D:/pmp-athena/pmp_notes/question_bank.json")
ERROR_LOG = Path("D:/pmp-athena/pmp_notes/error_log.json")
REVIEW_STATE = Path("D:/pmp-athena/pmp_notes/error_review_state.json")
EXAM_CONFIG = Path("D:/pmp-athena/pmp_notes/exam_config.json")
OPTIONS_SUPPLEMENT = Path("D:/pmp-athena/pmp_notes/question_options_supplement.json")

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

def review_today() -> str:
    """汇总今日需要复习的错题（不含答案，供交互出题使用）"""
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
    lines = []
    lines.append(f"📅 今日复习清单（{today_str}）")
    lines.append("=" * 30)

    # ── 收集所有到期错题 ──
    due_ids: set[int] = set()

    # 今天新增的错题
    today_errors = [e for e in errors if e.get("date") == today_str]
    for e in today_errors:
        due_ids.add(e["id"])

    # SM-2 今日到期
    due_cards = []
    for key, card in review.items():
        if card.get("next_date", "9999") <= today_str:
            eid = card.get("error_id")
            due_ids.add(eid)
            error = next((e for e in errors if e.get("id") == eid), None)
            due_cards.append({**card, "error": error})

    # 题库中今日做错的
    today_wrong_in_bank = [
        r for r in bank
        if r.get("date") == today_str and r.get("is_correct") is False
    ]
    for r in today_wrong_in_bank:
        eid = r.get("error_log_id")
        if eid is not None:
            due_ids.add(eid)

    if not due_ids:
        lines.append("\n✅ 今日暂无待复习错题，继续保持！")
        return "\n".join(lines)

    # ── 按知识领域分组 ──
    area_groups: dict[str, list[dict]] = {}
    for eid in due_ids:
        error = next((e for e in errors if e.get("id") == eid), None)
        if error is None:
            continue
        area = error.get("knowledge_area", "未分类")
        if area not in area_groups:
            area_groups[area] = []
        area_groups[area].append(error)

    lines.insert(2, f"📌 共 {len(due_ids)} 题需要复习，按领域分布：\n")

    # 输出按领域分组（只显示 ID + 题干摘要，不泄露答案和解析）
    for area in sorted(area_groups.keys(), key=lambda a: -len(area_groups[a])):
        items = area_groups[area]
        lines.append(f"\n### {area}（{len(items)} 题）")
        for e in items:
            q = e.get("question", "")[:60]
            lines.append(f"- #{e['id']} {q}...")
        lines.append("")

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
        lines.append("⚠️ 本题录入时未保存选项。请凭记忆作答，或发「查看题目#N」补录。")
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

    body = _format_review_question(error_id, record)
    if include_header:
        text = (
            f"📚 今日待复习错题: {len(due_ids)} 道（还剩 {len(pending)} 道）\n\n"
            f"{body}"
        )
    else:
        text = body

    return {
        "status": "question",
        "error_id": error_id,
        "total_due": len(due_ids),
        "remaining": len(pending),
        "text": text,
    }


def grade_review(error_id: int, user_answer: str) -> dict:
    """判卷并返回下一题（微信硬路由用）"""
    import sys
    from pathlib import Path
    _pkg = Path(__file__).resolve().parent
    if str(_pkg) not in sys.path:
        sys.path.insert(0, str(_pkg))
    from spaced_repetition import SpacedRepetition

    errors = load_json(ERROR_LOG)
    if not isinstance(errors, list):
        errors = []

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

    sr = SpacedRepetition()
    sr.grade(error_id, 5 if is_correct else 1)

    lines: list[str] = []
    if is_correct:
        lines.append("✅ 正确！")
    else:
        try:
            from pmp_athena.error_insights import format_wrong_feedback
        except ImportError:
            from error_insights import format_wrong_feedback
        lines.append(format_wrong_feedback(error, user_answer=user_ans))

    nxt = review_next(include_header=False)
    if nxt["status"] == "question":
        lines.append("")
        lines.append(nxt["text"])
    elif nxt["status"] == "done":
        lines.append("")
        lines.append(nxt["text"])

    return {
        "status": "graded",
        "correct": is_correct,
        "error_id": error_id,
        "next_error_id": nxt.get("error_id"),
        "done": nxt["status"] in ("done", "empty"),
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

    args = parser.parse_args()

    if args.command == "weakness":
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
