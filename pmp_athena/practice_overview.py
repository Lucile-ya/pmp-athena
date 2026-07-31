#!/usr/bin/env python3
"""
刷题总览 — 实时汇总日常刷题、模考、领域正确率与今日建议。

触发词：总览 / 刷题总览 / 我的进度 / 战况 / 现在什么水平

用法:
    python pmp_athena/practice_overview.py
    python pmp_athena/practice_overview.py message --text "总览" --json
"""

from __future__ import annotations

import argparse
import json
import sys
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import NOTES_DIR
    from pmp_athena.practice_summary import (
        EXAM_YEAR,
        PASS_CORRECT,
        TARGET_CORRECT,
        TARGET_TOTAL,
        _accuracy,
        _area_stats,
        _delta_label,
        _exam_rate,
        _load_exam_records,
    )
    from pmp_athena.question_bank import QuestionBank
except ModuleNotFoundError:
    from config import NOTES_DIR
    from practice_summary import (
        EXAM_YEAR,
        PASS_CORRECT,
        TARGET_CORRECT,
        TARGET_TOTAL,
        _accuracy,
        _area_stats,
        _delta_label,
        _exam_rate,
        _load_exam_records,
    )
    from question_bank import QuestionBank

ERROR_LOG_PATH = NOTES_DIR / "error_log.json"
EXAM_RECORDS_PATH = NOTES_DIR / "exam_records.json"
REVIEW_STATE_PATH = NOTES_DIR / "error_review_state.json"
CONFIG_PATH = NOTES_DIR / "config.json"
SPRINT_PLANS_PATH = NOTES_DIR / "sprint_plans.json"

EXAM_DATE = date(2026, 9, 12)
PREP_START = date(2026, 7, 1)  # 备考起始月
TARGET_RATE = 70.0
PASS_RATE = 59.0
MOCK_SOURCES = frozenset({"mock_exam", "mock", "模考"})

OVERVIEW_TRIGGERS_EXACT = frozenset({
    "总览",
    "刷题总览",
    "我的进度",
    "战况",
    "现在什么水平",
})


def _is_full_mock(exam: dict) -> bool:
    """完整模考 vs 章节练习。"""
    if exam.get("type") == "chapter_practice":
        return False
    if str(exam.get("exam_id", "")).startswith("章节练习"):
        return False
    total = int(exam.get("total_questions") or 0)
    return total >= 100


def _load_exams_split() -> tuple[list[dict], list[dict]]:
    """返回 (完整模考, 章节练习)。"""
    exams = _load_exam_records()
    full, chapter = [], []
    for e in exams:
        if _is_full_mock(e):
            full.append(e)
        elif e.get("type") == "chapter_practice" or str(e.get("exam_id", "")).startswith("章节练习"):
            chapter.append(e)
    full.sort(key=lambda x: str(x.get("exam_date", "")))
    return full, chapter


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _is_mock_source(source: str | None) -> bool:
    if not source:
        return False
    s = source.lower()
    return s in MOCK_SOURCES or "mock" in s or "模考" in source


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last = monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last:02d}"


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month <= 1 else (year, month - 1)


def _period_accuracy(bank: QuestionBank, start: str, end: str) -> tuple[int, int, float, int]:
    recs = [
        r for r in bank.list_by_date_range(start, end)
        if r.get("is_correct") is not None and not _is_mock_source(r.get("source"))
    ]
    total = len(recs)
    correct = sum(1 for r in recs if r.get("is_correct"))
    active = len({r.get("date") for r in recs if r.get("date")})
    return correct, total, _accuracy(correct, total), active


def _area_stats_with_errors(bank_records: list[dict], errors: list[dict]) -> dict[str, dict[str, int]]:
    """question_bank 正确率 + error_log 错题数联合。"""
    by_area = _area_stats(bank_records)
    error_counts: dict[str, int] = defaultdict(int)
    for e in errors:
        if isinstance(e, dict):
            error_counts[e.get("knowledge_area") or "综合"] += 1
    all_areas = set(by_area.keys()) | set(error_counts.keys())
    merged: dict[str, dict[str, int]] = {}
    for area in all_areas:
        s = by_area.get(area, {"total": 0, "correct": 0, "wrong": 0})
        merged[area] = {
            "total": s["total"],
            "correct": s["correct"],
            "wrong": s["wrong"],
            "errors": error_counts.get(area, 0),
        }
    return merged


def _due_error_count(today: date) -> int:
    state = _load_json(REVIEW_STATE_PATH, {})
    if not isinstance(state, dict):
        return 0
    today_s = today.isoformat()
    count = 0
    for entry in state.values():
        if not isinstance(entry, dict):
            continue
        nd = entry.get("next_date") or ""
        if nd and nd <= today_s:
            count += 1
    return count


def _daily_practice_done_today(today: date) -> bool:
    cfg = _load_json(CONFIG_PATH, {})
    if not isinstance(cfg, dict):
        return False
    completed = cfg.get("daily_completed") or []
    return today.isoformat() in completed


def _active_sprint_hint() -> str | None:
    plans = _load_json(SPRINT_PLANS_PATH, [])
    if not isinstance(plans, list):
        return None
    active = [p for p in plans if isinstance(p, dict) and p.get("status") == "active"]
    if not active:
        return None
    active.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    plan = active[0]
    days = plan.get("days", 0)
    done = sum(1 for d in plan.get("day_plans", []) if d.get("completed"))
    return f"冲刺计划 {done}/{days} 天"


def _progress_bar(pct: float, width: int = 20) -> str:
    """进度条：每 5% 一格（width=20 → 100%）。"""
    pct = max(0.0, min(100.0, pct))
    filled = min(width, round(pct / 5))
    return "█" * filled + "░" * (width - filled)


def _iter_months(start: date, end: date):
    """从 start 月到 end 月逐月 yield (year, month)。"""
    y, m = start.year, start.month
    ey, em = end.year, end.month
    while (y, m) <= (ey, em):
        yield y, m
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


def _iter_week_mondays(start: date, end: date):
    """从备考起始周到当前周，逐周 yield 周一日期。"""
    monday = start - timedelta(days=start.weekday())
    end_monday = end - timedelta(days=end.weekday())
    current = monday
    while current <= end_monday:
        yield current
        current += timedelta(days=7)


def _rate_delta(curr: float, prev: float | None) -> tuple[str, str]:
    """返回 (变化文案, 箭头)。"""
    if prev is None:
        return "（首段）", ""
    diff = round(curr - prev, 1)
    if abs(diff) < 0.5:
        return "→ 持平", "→"
    sign = f"+{diff}" if diff > 0 else str(diff)
    arrow = "↑" if diff > 0 else "↓"
    return f"{arrow} {sign}%", arrow


def _build_monthly_timeline(
    bank: QuestionBank,
    today: date,
) -> tuple[list[str], list[dict[str, Any]]]:
    """月度时间线：2026-07 起至当前月。"""
    lines = ["", "📅 月度时间线", "──────────────────────"]
    rows: list[dict[str, Any]] = []
    prev_acc: float | None = None

    for y, m in _iter_months(PREP_START, today):
        start, end = _month_bounds(y, m)
        if y == today.year and m == today.month:
            end = today.isoformat()
            in_progress = True
        else:
            in_progress = False

        correct, total, acc, active = _period_accuracy(bank, start, end)
        delta_text, _ = _rate_delta(acc if total else 0, prev_acc if prev_acc is not None and total else None)

        row = {
            "year": y,
            "month": m,
            "label": f"{m:02d}月",
            "total": total,
            "correct": correct,
            "accuracy": acc if total else None,
            "active_days": active,
            "in_progress": in_progress,
            "delta": round(acc - prev_acc, 1) if prev_acc is not None and total else None,
        }
        rows.append(row)

        if in_progress:
            if total:
                lines.append(
                    f"{m:02d}月 进行中 {total}题 {acc}% {_progress_bar(acc)} {delta_text}"
                )
            else:
                lines.append(f"{m:02d}月 进行中 · 暂无刷题")
        elif total:
            lines.append(
                f"{m:02d}月 {total}题 {acc}% {_progress_bar(acc)} {delta_text}"
            )
            prev_acc = acc
        else:
            lines.append(f"{m:02d}月 · 无刷题")

    return lines, rows


def _build_weekly_timeline(
    bank: QuestionBank,
    today: date,
) -> tuple[list[str], list[dict[str, Any]]]:
    """周度时间线：ISO 周，备考起始周至当前周。"""
    lines = ["", "📆 周度时间线", "──────────────────────"]
    rows: list[dict[str, Any]] = []
    prev_acc: float | None = None

    for monday in _iter_week_mondays(PREP_START, today):
        sunday = monday + timedelta(days=6)
        iso = monday.isocalendar()
        week_num = iso[1]
        week_end = sunday if sunday <= today else today
        current_monday = today - timedelta(days=today.weekday())
        in_progress = monday == current_monday

        start_s = monday.isoformat()
        end_s = week_end.isoformat()
        correct, total, acc, _ = _period_accuracy(bank, start_s, end_s)

        delta_text, arrow = _rate_delta(acc if total else 0, prev_acc if prev_acc is not None and total else None)
        range_label = f"{monday.month}/{monday.day}-{week_end.month}/{week_end.day}"

        row = {
            "iso_year": iso[0],
            "iso_week": week_num,
            "start": start_s,
            "end": end_s,
            "total": total,
            "correct": correct,
            "accuracy": acc if total else None,
            "in_progress": in_progress,
            "delta": round(acc - prev_acc, 1) if prev_acc is not None and total else None,
        }
        rows.append(row)

        if in_progress:
            if total:
                lines.append(f"W{week_num} {range_label} 进行中 {total}题 {acc}% {delta_text}")
            else:
                lines.append(f"W{week_num} {range_label} 进行中 · 暂无刷题")
        elif total:
            lines.append(f"W{week_num} {range_label} {total}题 {acc}% {delta_text}")
            prev_acc = acc
        else:
            lines.append(f"W{week_num} {range_label} · 无刷题")

    return lines, rows


def _build_mock_timeline(exams: list[dict]) -> tuple[list[str], list[dict[str, Any]]]:
    """模考时间线：全部完整模考，含 59% 通过线参考。"""
    lines = [
        "",
        f"🏁 模考时间线（通过线 {PASS_RATE:.0f}%）",
        "──────────────────────",
        f"  ┄┄ 59% 参考线 ┄┄",
    ]
    rows: list[dict[str, Any]] = []
    prev_rate: float | None = None

    for e in exams:
        rate = _exam_rate(e)
        d = str(e.get("exam_date", ""))[:10]
        name = (e.get("exam_id") or "模考")[:14]
        correct = int(e.get("correct_count") or 0)
        total = int(e.get("total_questions") or 0)
        pass_ok = rate >= PASS_RATE

        delta_val: float | None = None
        if prev_rate is not None and rate > 0:
            diff = round(rate - prev_rate, 1)
            delta_val = diff
            if abs(diff) < 0.5:
                change = "→ 持平"
            else:
                sign = f"+{diff}" if diff > 0 else str(diff)
                arrow = "↑" if diff > 0 else "↓"
                change = f"{arrow} {sign}%"
        elif prev_rate is None:
            change = "（首次）"
        else:
            change = ""

        status = "✅" if pass_ok else "❌"
        score_detail = f"{correct}/{total}" if total else ""

        if rate > 0 or correct > 0:
            lines.append(f"  {d[5:]} {name} {rate}% {status} {score_detail} {change}".rstrip())
            if rate > 0:
                prev_rate = rate
        else:
            lines.append(f"  {d[5:]} {name} · 无得分记录")

        rows.append({
            "exam_date": d,
            "exam_id": e.get("exam_id"),
            "rate": rate,
            "correct": correct,
            "total": total,
            "pass_ok": pass_ok,
            "delta": delta_val,
        })

    if not exams:
        lines.append("  暂无完整模考记录")

    return lines, rows


def _mock_trend(exams: list[dict]) -> str:
    """最近模考趋势箭头。"""
    recent = [_exam_rate(e) for e in exams[-3:] if _exam_rate(e) > 0]
    if len(recent) < 2:
        return "→ 数据不足"
    if recent[-1] > recent[-2] + 3:
        return "↑ 上升"
    if recent[-1] < recent[-2] - 3:
        return "↓ 下降"
    return "→ 持平"


def _today_suggestions(
    *,
    due_errors: int,
    weak_areas: list[str],
    combined_rate: float,
    mock_count: int,
    daily_done: bool,
    sprint_hint: str | None,
) -> list[str]:
    actions: list[str] = []
    if due_errors > 0:
        actions.append(f"复习错题 {due_errors} 道到期 → 发送「复习错题」")
    elif not daily_done:
        actions.append("完成今日每日一练 10 题 → 发送「每日一练」")
    elif weak_areas:
        actions.append(f"专项突破 {weak_areas[0]} 15 题 → 发送「{weak_areas[0]}知识点」")
    else:
        actions.append("保持每日一练 + 到期错题复习")

    if mock_count == 0:
        actions.append("尚未完整模考 → 发送「开始模考」摸底")
    elif combined_rate < TARGET_RATE:
        actions.append("发送「薄弱点」诊断 Top 3 弱项")
    elif sprint_hint:
        actions.append(f"{sprint_hint} → 发送「冲刺进度」")
    else:
        actions.append("发送「考前分析」制定冲刺方案")

    if len(actions) < 3:
        if combined_rate >= TARGET_RATE:
            actions.append("本周安排 1 次模考查漏补缺")
        else:
            actions.append("发送「复习计划」获取错题清单")

    return actions[:3]


def build_overview(*, ref_date: date | None = None) -> dict[str, Any]:
    """实时计算刷题总览（不缓存；时间线从 question_bank / exam_records 按日期读取）。"""
    today = ref_date or date.today()
    bank = QuestionBank()
    all_graded = [r for r in bank.list_all() if r.get("is_correct") is not None]

    daily_recs = [r for r in all_graded if not _is_mock_source(r.get("source"))]
    exams_full, chapter_exams = _load_exams_split()
    prep_exams = [
        e for e in exams_full
        if str(e.get("exam_date", "")).startswith(str(EXAM_YEAR))
        or int(str(e.get("exam_date", ""))[:4] or 0) >= EXAM_YEAR - 1
    ]

    chapter_q = sum(int(e.get("total_questions") or 0) for e in chapter_exams)
    chapter_c = sum(int(e.get("correct_count") or 0) for e in chapter_exams)

    daily_total = len(daily_recs) + chapter_q
    daily_correct = sum(1 for r in daily_recs if r.get("is_correct")) + chapter_c
    daily_wrong = daily_total - daily_correct
    daily_rate = _accuracy(daily_correct, daily_total)

    mock_sessions = len(prep_exams)
    mock_questions = sum(int(e.get("total_questions") or 0) for e in prep_exams)
    mock_correct = sum(int(e.get("correct_count") or 0) for e in prep_exams)

    combined_total = len(daily_recs) + chapter_q + mock_questions
    combined_correct = sum(1 for r in daily_recs if r.get("is_correct")) + chapter_c + mock_correct
    combined_rate = _accuracy(combined_correct, combined_total)

    # 180 题制差距（按综合正确率估算）
    projected_180 = round(combined_rate / 100 * TARGET_TOTAL) if combined_total else 0
    if prep_exams:
        last_mock = prep_exams[-1]
        lc = int(last_mock.get("correct_count") or 0)
        lt = int(last_mock.get("total_questions") or TARGET_TOTAL)
        if lc > 0 and lt >= 100:
            projected_180 = round(lc / lt * TARGET_TOTAL)

    gap_target = max(0, TARGET_CORRECT - projected_180)
    gap_pass = max(0, PASS_CORRECT - projected_180)
    pass_ok = projected_180 >= PASS_CORRECT
    target_ok = projected_180 >= TARGET_CORRECT

    # 活跃天数：日常刷题日期 ∪ 模考日期
    active_dates = {r.get("date") for r in daily_recs if r.get("date")}
    for e in prep_exams:
        d = str(e.get("exam_date", ""))[:10]
        if d:
            active_dates.add(d)
    active_days = len(active_dates)

    days_left = (EXAM_DATE - today).days

    # 本周 / 本月趋势
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    prev_monday = monday - timedelta(days=7)
    prev_sunday = monday - timedelta(days=1)

    w_c, w_t, w_acc, _ = _period_accuracy(bank, monday.isoformat(), sunday.isoformat())
    pw_c, pw_t, pw_acc, _ = _period_accuracy(
        bank, prev_monday.isoformat(), prev_sunday.isoformat()
    )

    cy, cm = today.year, today.month
    py, pm = _prev_month(cy, cm)
    m_start, m_end = _month_bounds(cy, cm)
    pm_start, pm_end = _month_bounds(py, pm)
    mc, mt, m_acc, _ = _period_accuracy(bank, m_start, m_end)
    pmc, pmt, pm_acc, _ = _period_accuracy(bank, pm_start, pm_end)

    errors = _load_json(ERROR_LOG_PATH, [])
    if not isinstance(errors, list):
        errors = []
    area_merged = _area_stats_with_errors(daily_recs, errors)
    area_rows = sorted(
        area_merged.items(),
        key=lambda x: (_accuracy(x[1]["correct"], x[1]["total"]) if x[1]["total"] else -1),
    )
    weak_areas = [
        a for a, s in area_rows
        if s["total"] >= 3 and _accuracy(s["correct"], s["total"]) < 60
    ]

    due_errors = _due_error_count(today)
    daily_done = _daily_practice_done_today(today)
    sprint_hint = _active_sprint_hint()
    suggestions = _today_suggestions(
        due_errors=due_errors,
        weak_areas=weak_areas,
        combined_rate=combined_rate,
        mock_count=mock_sessions,
        daily_done=daily_done,
        sprint_hint=sprint_hint,
    )

    # 完整时间线（实时从 JSON 计算，不写入缓存）
    monthly_lines, monthly_rows = _build_monthly_timeline(bank, today)
    weekly_lines, weekly_rows = _build_weekly_timeline(bank, today)
    mock_lines, mock_rows = _build_mock_timeline(prep_exams)

    # ── 格式化输出 ──
    lines: list[str] = [
        "📊 刷题总览",
        "══════════════════════",
        f"📅 {today.month}月{today.day}日 · 距考试 {days_left} 天",
        f"📆 累计活跃 {active_days} 天",
        "",
        "📝 刷题量",
        f"  日常 {daily_total}题 ✅{daily_correct} ❌{daily_wrong}",
        f"  模考 {mock_sessions}次 {mock_questions}题",
        f"  合计 {combined_total}题",
        "",
        "🎯 目标对比（180题）",
    ]

    target_tag = "✅" if target_ok else f"❌差{gap_target}题"
    pass_tag = "✅" if pass_ok else f"❌差{gap_pass}题"
    lines.extend([
        f"  训练70%：{TARGET_CORRECT}题 {target_tag}",
        f"  通过59%：{PASS_CORRECT}题 {pass_tag}",
        f"  综合正确率 {combined_rate}%",
        "",
        "📈 趋势",
    ])

    if w_t:
        if pw_t:
            arr, diff, em = _delta_label(w_acc, pw_acc)
            lines.append(f"  本周 {w_acc}% {arr} {diff}%（上周 {pw_acc}%） {em}".rstrip())
        else:
            lines.append(f"  本周 {w_acc}%（上周无刷题）")
    else:
        lines.append("  本周 暂无刷题")

    if mt:
        if pmt:
            arr, diff, em = _delta_label(m_acc, pm_acc)
            lines.append(f"  本月 {m_acc}% {arr} {diff}%（上月 {pm_acc}%） {em}".rstrip())
        else:
            lines.append(f"  本月 {m_acc}%（上月无刷题）")
    else:
        lines.append("  本月 暂无刷题")

    lines.extend(monthly_lines)
    lines.extend(weekly_lines)
    lines.extend(mock_lines)

    lines.extend(["", "📋 领域（低→高）"])
    shown_areas = [(a, s) for a, s in area_rows if s["total"] >= 2 or s["errors"] >= 2]
    if shown_areas:
        for area, s in shown_areas[:8]:
            acc = _accuracy(s["correct"], s["total"]) if s["total"] else 0.0
            tag = "🔴" if acc < 60 else ("🟡" if acc < 70 else "🟢")
            err_note = f" ·错{s['errors']}" if s["errors"] else ""
            detail = f"{s['correct']}/{s['total']}" if s["total"] else f"错{s['errors']}"
            lines.append(f"  {tag} {area} {acc}%（{detail}{err_note}）")
    else:
        lines.append("  暂无足够数据")

    lines.extend(["", "💡 今日建议"])
    for i, act in enumerate(suggestions, 1):
        lines.append(f"  {i}. {act}")

    if sprint_hint:
        lines.append(f"  📌 {sprint_hint}")

    lines.extend([
        "",
        "👉 补课 | 考前分析 | 开始模考",
    ])

    return {
        "status": "ok" if combined_total else "empty",
        "date": today.isoformat(),
        "days_left": days_left,
        "active_days": active_days,
        "daily_total": daily_total,
        "daily_correct": daily_correct,
        "daily_rate": daily_rate,
        "mock_sessions": mock_sessions,
        "mock_questions": mock_questions,
        "combined_total": combined_total,
        "combined_rate": combined_rate,
        "projected_180": projected_180,
        "gap_target": gap_target,
        "gap_pass": gap_pass,
        "week_accuracy": w_acc,
        "month_accuracy": m_acc,
        "weak_areas": weak_areas,
        "suggestions": suggestions,
        "timeline": {
            "monthly": monthly_rows,
            "weekly": weekly_rows,
            "mock_exams": mock_rows,
        },
        "text": "\n".join(lines),
    }


def parse_trigger(text: str) -> bool:
    """是否命中刷题总览触发词。"""
    t = text.strip().replace("\u200b", "")
    if not t:
        return False
    if t in OVERVIEW_TRIGGERS_EXACT:
        return True
    # 允许极短消息精确匹配
    for trigger in OVERVIEW_TRIGGERS_EXACT:
        if t == trigger:
            return True
    return False


def handle_message(text: str) -> dict[str, Any]:
    if not parse_trigger(text):
        return {"status": "skip"}
    return build_overview()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="刷题总览")
    sub = parser.add_subparsers(dest="command")

    p_show = sub.add_parser("show", help="输出总览")
    p_show.add_argument("--json", action="store_true")

    p_msg = sub.add_parser("message", help="解析微信消息")
    p_msg.add_argument("--text", "-t", required=True)
    p_msg.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.command == "message":
        result = handle_message(args.text)
        if result.get("status") == "skip":
            result = {"status": "skip", "text": ""}
    elif args.command == "show":
        result = build_overview()
    else:
        result = build_overview()

    if getattr(args, "json", False) or args.command == "message":
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result.get("text", ""))


if __name__ == "__main__":
    main()
