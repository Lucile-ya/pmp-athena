#!/usr/bin/env python3
"""
备考建议生成器 — 基于全量做题数据自动生成个性化备考建议。

用法:
    python pmp_athena/study_advice.py advice --json
    python pmp_athena/study_advice.py advice --target 1500 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TZ_CST = timezone(timedelta(hours=8))

try:
    from pmp_athena.config import ERROR_LOG_PATH, EXAM_RECORDS_PATH, QUESTION_BANK_PATH, REVIEW_STATE_PATH
except (ImportError, ModuleNotFoundError):
    from config import ERROR_LOG_PATH, EXAM_RECORDS_PATH, QUESTION_BANK_PATH, REVIEW_STATE_PATH

EXAM_DATE = date(2026, 9, 12)
PASS_LINE = 0.59          # PMP 通过线
TARGET_LINE = 0.70         # 训练目标
MIN_TOTAL_QUESTIONS = 1000  # 建议最低刷题量
RECOMMENDED_QUESTIONS = 1500


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return [] if path.name.endswith("bank.json") or path.name.endswith("log.json") else {}


def generate_advice(target_questions: int = RECOMMENDED_QUESTIONS) -> dict:
    """生成备考建议。"""
    today = date.today()
    days_left = (EXAM_DATE - today).days

    # ── 1. 做题数据 ──
    bank = _load(QUESTION_BANK_PATH) if isinstance(_load(QUESTION_BANK_PATH), list) else []
    total_done = len(bank)
    correct = sum(1 for r in bank if r.get("is_correct") is True)
    wrong = sum(1 for r in bank if r.get("is_correct") is False)
    accuracy = correct / max(1, correct + wrong)
    gap = target_questions - total_done

    # ── 2. 错题分布 ──
    errors = _load(ERROR_LOG_PATH) if isinstance(_load(ERROR_LOG_PATH), list) else []
    area_wrong: dict[str, int] = {}
    for e in errors:
        area = e.get("knowledge_area", "综合")
        area_wrong[area] = area_wrong.get(area, 0) + 1

    # 今日到期错题
    review_state = _load(REVIEW_STATE_PATH) if isinstance(_load(REVIEW_STATE_PATH), dict) else {}
    today_str = today.isoformat()
    overdue = sum(
        1 for v in review_state.values()
        if isinstance(v, dict) and v.get("next_date", "9999") <= today_str
    )

    # ── 3. 模考记录 ──
    exams = _load(EXAM_RECORDS_PATH)
    exam_list = exams.get("exams", []) if isinstance(exams, dict) else []
    completed = [e for e in exam_list if e.get("status") == "completed"]
    mock_count = len(completed)
    recent_3 = sorted(completed, key=lambda e: e.get("exam_date", ""), reverse=True)[:3]
    recent_rates = [e.get("correct_rate", 0) for e in recent_3]

    # ── 4. 薄弱领域 ──
    area_acc: dict[str, dict] = {}
    for r in bank:
        a = r.get("knowledge_area", "综合")
        if a not in area_acc:
            area_acc[a] = {"correct": 0, "total": 0}
        area_acc[a]["total"] += 1
        if r.get("is_correct"):
            area_acc[a]["correct"] += 1

    weak_areas = []
    for area, stats in area_acc.items():
        if stats["total"] >= 3:
            ar = stats["correct"] / stats["total"]
            if ar < 0.50:
                weak_areas.append((area, ar, stats["correct"], stats["total"]))

    weak_areas.sort(key=lambda x: x[1])

    # ── 5. 本周刷题趋势 ──
    week_ago = today - timedelta(days=7)
    week_records = [r for r in bank if r.get("date", "") >= week_ago.isoformat()]
    week_total = len(week_records)
    week_correct = sum(1 for r in week_records if r.get("is_correct"))
    week_rate = week_correct / max(1, week_total)

    # ── 构建建议文本 ──
    lines = [
        "📋 备考建议",
        "──────────────────────────────",
        "",
        "📊 当前状态：",
    ]

    # 刷题量
    if total_done < MIN_TOTAL_QUESTIONS:
        lines.append(f"- 刷题量：{total_done}/{target_questions}（需再刷 {gap} 题）⚠️ 偏少")
    else:
        progress_pct = total_done / target_questions * 100
        lines.append(f"- 刷题量：{total_done}/{target_questions}（{progress_pct:.0f}%）✅")

    # 正确率
    acc_label = (
        "🟢 达标" if accuracy >= TARGET_LINE else
        "🟡 可通过" if accuracy >= PASS_LINE else
        "🔴 未通过"
    )
    pass_gap = round((PASS_LINE - accuracy) * 100, 1) if accuracy < PASS_LINE else 0
    if pass_gap > 0:
        lines.append(f"- 正确率：{accuracy:.1%}（距通过线差 {pass_gap}%）{acc_label}")
    else:
        lines.append(f"- 正确率：{accuracy:.1%} {acc_label}")

    # 错题堆积
    if overdue > 0:
        lines.append(f"- 错题堆积：{overdue} 道今日到期 🔴")
    else:
        lines.append(f"- 错题复习：今日无逾期 ✅")

    # 模考
    if mock_count == 0:
        lines.append(f"- 模考次数：0 ⚠️ 建议本周完成 1 次")
    elif mock_count < 3:
        lines.append(f"- 模考次数：{mock_count} 次（建议考前至少 3 次）")
    else:
        trend = "↑" if len(recent_rates) >= 2 and recent_rates[0] > recent_rates[1] else "→"
        lines.append(f"- 模考次数：{mock_count} 次（最近 {recent_rates[0]*100:.0f}% {trend}）")

    # ── 每日配额（目标追踪要用）──
    daily_new = max(10, min(50, gap // max(1, days_left)))
    daily_review = max(5, min(20, overdue // 7)) if overdue > 0 else 10

    # ── 6. 最近 7 天趋势 ──
    recent_7_days: list[float] = []
    for d_offset in range(6, -1, -1):
        day = (today - timedelta(days=d_offset)).isoformat()
        day_records = [r for r in bank if r.get("date") == day]
        day_total = len(day_records)
        if day_total > 0:
            day_correct = sum(1 for r in day_records if r.get("is_correct"))
            recent_7_days.append(day_correct / day_total)
        else:
            recent_7_days.append(0)

    # 趋势斜率（最近7天每日正确率的线性趋势）
    valid_days = [(i, r) for i, r in enumerate(recent_7_days) if r > 0]
    trend_slope = 0
    if len(valid_days) >= 3:
        n = len(valid_days)
        sum_x = sum(i for i, _ in valid_days)
        sum_y = sum(r for _, r in valid_days)
        sum_xy = sum(i * r for i, r in valid_days)
        sum_x2 = sum(i * i for i, _ in valid_days)
        denom = n * sum_x2 - sum_x * sum_x
        if denom != 0:
            trend_slope = (n * sum_xy - sum_x * sum_y) / denom  # 每天变化率

    # ── 目标追踪 ──
    gap_to_target = max(0, TARGET_LINE - accuracy)
    gap_pct = round(gap_to_target * 100, 1)

    # 按当前速度预计达标时间
    if trend_slope > 0.001:
        # 每天进步 trend_slope%，达到 70% 需要多少天
        weeks_to_target = max(1, round(gap_to_target / trend_slope / 7))
    elif trend_slope < -0.001:
        weeks_to_target = 99  # 倒退中
    else:
        weeks_to_target = max(1, round(gap_to_target / 0.005 / 7)) if gap_to_target > 0 else 0  # 保守估算 0.5%/天

    # 提速方案
    speedup_new = max(5, daily_new + 10)  # 每天多刷 10 题
    speedup_review = max(3, daily_review + 5)  # 每天多复习 5 道
    speedup_weeks = max(1, round(weeks_to_target * 0.6)) if weeks_to_target < 99 else "—"

    lines.append("")
    lines.append(f"🎯 70% 目标追踪")
    if accuracy < TARGET_LINE:
        lines.append(f"- 总正确率：{accuracy:.1%}（距目标差 {gap_pct}%）")
        if weeks_to_target < 99:
            lines.append(f"- 按当前速度：预计 {weeks_to_target} 周后达标（日均变化 {trend_slope*100:+.1f}%）")
        else:
            lines.append(f"- 按当前速度：趋势下降中 ⚠️ 需调整策略")
        lines.append(f"- 提速方案：每天多刷 {speedup_new - daily_new} 题 + 重刷 {speedup_review - daily_review} 道错题 → 可缩短至 {speedup_weeks} 周")
    else:
        lines.append(f"- 总正确率：{accuracy:.1%} ✅ 已达目标")
        lines.append(f"- 趋势：{'↑ 上升中' if trend_slope > 0.001 else '→ 持平' if trend_slope > -0.001 else '↓ 注意'}")

    # 各领域距目标差距
    area_gaps = []
    for area, stats in area_acc.items():
        if stats["total"] >= 3:
            ar = stats["correct"] / stats["total"]
            g = TARGET_LINE - ar
            if g > 0:
                area_gaps.append((area, ar, g, stats["correct"], stats["total"]))
    area_gaps.sort(key=lambda x: -x[2])  # 差距最大的排前面
    if area_gaps:
        lines.append(f"- 各领域距目标差距（Top {min(5, len(area_gaps))}）：")
        for area, ar, g, corr, tot in area_gaps[:5]:
            lines.append(f"  • {area}：{ar:.0%}（差 {g:.0%}）— {corr}/{tot}")

    lines.append("")

    # ── 本周目标 ──
    lines.append("🎯 本周目标：")
    lines.append(f"1. 刷题：每天至少 {daily_new} 题（7 天 {daily_new * 7} 题）")
    if overdue > 0:
        lines.append(f"2. 复习：每天清 {daily_review} 道错题（7 天清完 {min(overdue, daily_review * 7)} 道）")
    if mock_count < 3:
        lines.append(f"3. 模考：本周完成 1 次模考")

    lines.append("")

    # ── 每日建议 ──
    lines.append("📅 每日建议：")
    weak_str = "、".join([a for a, _, _, _ in weak_areas[:3]]) if weak_areas else "通用"

    morning = f"- 上午：复习 {daily_review} 道错题"
    if weak_areas:
        morning += f"（优先 {weak_str}）"
    lines.append(morning)
    lines.append(f"- 下午：刷 {daily_new} 道新题（优先薄弱领域）")
    lines.append(f"- 晚上：总结今日错题，录入系统")

    lines.append("")

    # ── 薄弱领域提醒 ──
    if weak_areas:
        lines.append("⚠️ 薄弱领域（正确率 < 50%）：")
        for area, ar, corr, tot in weak_areas[:5]:
            lines.append(f"  • {area}：{corr}/{tot}（{ar:.0%}）")
        lines.append("")

    # ── 考前倒计时 ──
    lines.append(f"📅 距考试：{days_left} 天")
    if days_left <= 7:
        lines.append("🔥 考前冲刺！保持手感，每天至少 30 题")
    elif days_left <= 30:
        lines.append("⚡ 强化刷题期，专注薄弱领域 + 高频错题")
    else:
        lines.append("📖 基础巩固期，覆盖全领域 + 建立错题库")

    lines.append("")
    lines.append("💬 回复「今日计划」生成今日详细计划")
    lines.append("💬 回复「复习错题」开始今日复习")

    return {
        "status": "ok",
        "total_done": total_done,
        "accuracy": round(accuracy * 100, 1),
        "overdue": overdue,
        "mock_count": mock_count,
        "weak_areas": [(a, round(ar * 100, 1)) for a, ar, _, _ in weak_areas[:5]],
        "days_left": days_left,
        "text": "\n".join(lines),
    }


def generate_daily_plan() -> dict:
    """生成今日详细计划。"""
    result = generate_advice()
    today = date.today()

    bank = _load(QUESTION_BANK_PATH) if isinstance(_load(QUESTION_BANK_PATH), list) else []
    today_records = [r for r in bank if r.get("date") == today.isoformat()]
    today_done = len(today_records)
    today_correct = sum(1 for r in today_records if r.get("is_correct"))

    lines = [
        f"📋 今日计划（{today.isoformat()}）",
        "──────────────────────────────",
        "",
        f"📊 今日进度：已刷 {today_done} 题",
    ]
    if today_done > 0:
        lines.append(f"   今日正确率：{today_correct}/{today_done}（{today_correct/today_done*100:.0f}%）")

    # 重新取每日建议
    days_left = result["days_left"]
    daily_new = max(10, min(50, (RECOMMENDED_QUESTIONS - result["total_done"]) // max(1, days_left)))
    daily_review = max(5, min(20, result["overdue"] // 7)) if result["overdue"] > 0 else 10

    weak_areas_names = [a for a, _ in result["weak_areas"][:3]]

    lines.append("")
    lines.append("⏰ 上午任务：")
    lines.append(f"  1. 复习错题 {daily_review} 道（发送「复习错题」开始）")
    if weak_areas_names:
        lines.append(f"  2. 重点领域：{' / '.join(weak_areas_names)}")

    lines.append("")
    lines.append("⏰ 下午任务：")
    lines.append(f"  1. 刷新题 {daily_new} 道（发送「随机每日一练」开始）")
    lines.append(f"  2. 完成后发送答案串判卷")

    lines.append("")
    lines.append("⏰ 晚间任务：")
    lines.append(f"  1. 录入今日错题到系统")
    if result["mock_count"] < 3:
        lines.append(f"  2. 考虑做一次模考（发送「开始模考」）")

    lines.append("")
    lines.append(f"💬 回复「睡前复习」晚间知识点回顾")

    return {
        "status": "ok",
        "today_done": today_done,
        "text": "\n".join(lines),
    }


def generate_three_step_plan() -> dict:
    """生成今日三步练习计划：① 清账（复习错题）→ ② 定点爆破（薄弱专项）→ ③ 高频错题收尾。"""
    today = date.today()
    today_str = today.isoformat()

    bank = _load(QUESTION_BANK_PATH)
    bank = bank if isinstance(bank, list) else []
    errors = _load(ERROR_LOG_PATH)
    errors = errors if isinstance(errors, list) else []
    review = _load(REVIEW_STATE_PATH)
    review = review if isinstance(review, dict) else {}

    # ── 第一步：清账 ──
    overdue = sum(
        1 for v in review.values()
        if isinstance(v, dict) and v.get("next_date", "9999") <= today_str
    )
    today_new_wrong = sum(
        1 for r in bank
        if r.get("date") == today_str and r.get("is_correct") is False
    )

    # ── 第二步：定点爆破（正确率最低的 2 个领域）──
    area_stats: dict[str, dict] = {}
    for r in bank:
        a = r.get("knowledge_area", "综合")
        s = area_stats.setdefault(a, {"correct": 0, "wrong": 0})
        if r.get("is_correct") is True:
            s["correct"] += 1
        elif r.get("is_correct") is False:
            s["wrong"] += 1

    area_rates: list[tuple[str, float, int, int]] = []
    for a, s in area_stats.items():
        judged = s["correct"] + s["wrong"]
        if judged >= 3:
            rate = s["correct"] / judged
            area_rates.append((a, rate, s["correct"], judged))
    area_rates.sort(key=lambda x: x[1])  # 正确率升序，最低在前
    weak_two = area_rates[:2]

    # ── 第三步：高频错题收尾（错 ≥3 次）──
    bank_wrong_by_err: dict[int, int] = {}
    for r in bank:
        if r.get("is_correct") is False and r.get("error_log_id"):
            eid = r["error_log_id"]
            bank_wrong_by_err[eid] = bank_wrong_by_err.get(eid, 0) + 1

    high_freq = 0
    for e in errors:
        eid = e.get("id")
        card = review.get(str(eid), {})
        review_wrong = sum(
            1 for h in card.get("history", [])
            if isinstance(h, dict) and int(h.get("quality", 5)) < 3
        )
        total = max(bank_wrong_by_err.get(eid, 0), 1) + review_wrong
        if total >= 3:
            high_freq += 1

    # ── 组装文本 ──
    lines = [
        "📋 今日练习 · 三步走",
        "══════════════════════",
        "",
    ]

    # 第一步
    lines.append("① 清账（复习错题）")
    lines.append(f"   今日错题到期 {overdue} 道，建议优先复习")
    if today_new_wrong > 0:
        lines.append(f"   （今日已新增 {today_new_wrong} 道，目标：清理 ≥ 新增）")
    lines.append("   → 发送「复习错题」开始")
    lines.append("")

    # 第二步
    lines.append("② 定点爆破（薄弱领域专项）")
    if weak_two:
        weak_names = "、".join(a for a, _, _, _ in weak_two)
        lines.append(f"   今日薄弱专项：{weak_names}")
        lines.append("   建议各刷 15-20 题")
        lines.append(f"   → 发送「专项 {weak_two[0][0]}」开始")
    else:
        lines.append("   当前领域数据不足，建议「随机每日一练」拓宽覆盖面")
    lines.append("")

    # 第三步
    lines.append("③ 高频错题收尾")
    lines.append(f"   今日高频错题处理 {high_freq} 道")
    lines.append("   （完成前两步后，发送「复习错题」收尾高频错题）")

    return {
        "status": "ok",
        "overdue": overdue,
        "today_new_wrong": today_new_wrong,
        "weak_areas": [(a, round(rate * 100, 1)) for a, rate, _, _ in weak_two],
        "high_freq": high_freq,
        "text": "\n".join(lines),
    }


def main():
    parser = argparse.ArgumentParser(description="备考建议生成器")
    parser.add_argument("command", choices=["advice", "daily-plan", "three-step", "today-practice"])
    parser.add_argument("--target", type=int, default=RECOMMENDED_QUESTIONS, help="目标刷题量")
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if args.command == "advice":
        result = generate_advice(args.target)
    elif args.command in ("three-step", "today-practice"):
        result = generate_three_step_plan()
    else:
        result = generate_daily_plan()

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
