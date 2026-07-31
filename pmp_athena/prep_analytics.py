#!/usr/bin/env python3
"""
备考分析 — 月度/周度总结、错题专项计划、复习清单。

数据源: exam_records.json, error_log.json, question_bank.json,
        sprint_plans.json, pmp_knowledge_index.json

用法:
    python pmp_athena/prep_analytics.py week
    python pmp_athena/prep_analytics.py month --month 7
    python pmp_athena/prep_analytics.py plan          # 错题专项计划
    python pmp_athena/prep_analytics.py today           # 今日复习清单
    python pmp_athena/prep_analytics.py message --text "7月做题总结"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import NOTES_DIR, PROJECT_ROOT
    from pmp_athena.practice_summary import (
        EXAM_YEAR,
        TARGET_ACCURACY,
        TARGET_CORRECT,
        TARGET_TOTAL,
        _accuracy,
        _area_stats,
        _bar,
        month_summary,
        parse_month_query,
        prep_summary,
    )
    from pmp_athena.question_bank import QuestionBank, DEFAULT_BANK_PATH
except ModuleNotFoundError:
    from config import NOTES_DIR, PROJECT_ROOT
    from practice_summary import (
        EXAM_YEAR,
        TARGET_ACCURACY,
        TARGET_CORRECT,
        TARGET_TOTAL,
        _accuracy,
        _area_stats,
        _bar,
        month_summary,
        parse_month_query,
        prep_summary,
    )
    from question_bank import QuestionBank, DEFAULT_BANK_PATH

ERROR_LOG_PATH = NOTES_DIR / "error_log.json"
EXAM_RECORDS_PATH = NOTES_DIR / "exam_records.json"
REVIEW_STATE_PATH = NOTES_DIR / "error_review_state.json"
SPRINT_PLANS_PATH = NOTES_DIR / "sprint_plans.json"
CONFIG_PATH = NOTES_DIR / "config.json"
INDEX_PATH = PROJECT_ROOT / "pmp_knowledge_index.json"
EXAM_DATE = date(2026, 9, 12)

ALL_AREAS = [
    "整合管理", "范围管理", "进度管理", "成本管理", "质量管理",
    "资源管理", "沟通管理", "风险管理", "采购管理", "干系人管理",
    "敏捷/混合方法", "商业环境", "领导力/人员",
]


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default if default is not None else []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default if default is not None else []


def _week_bounds(ref: date | None = None) -> tuple[str, str, int]:
    """本周一至周日（ISO week）。"""
    today = ref or date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat(), monday.isocalendar()[1]


def _load_exams() -> list[dict]:
    data = _load_json(EXAM_RECORDS_PATH, {"exams": []})
    exams = data.get("exams", []) if isinstance(data, dict) else data
    return [e for e in exams if isinstance(e, dict) and e.get("status") == "completed"]


def _daily_accuracy(bank: QuestionBank, day: str) -> tuple[int, int, float]:
    recs = [r for r in bank.list_by_date(day) if r.get("is_correct") is not None]
    total = len(recs)
    correct = sum(1 for r in recs if r.get("is_correct"))
    return correct, total, _accuracy(correct, total)


def _exam_rate(e: dict) -> float:
    rate = float(e.get("correct_rate") or 0)
    if rate <= 1:
        rate *= 100
    if rate <= 1 and e.get("correct_count") and e.get("total_questions"):
        rate = _accuracy(e["correct_count"], e["total_questions"])
    return round(rate, 1)


def find_knowledge_resources(area: str, limit: int = 2) -> list[str]:
    """从 pmp_knowledge_index.json 找推荐学习资源。"""
    data = _load_json(INDEX_PATH, {"entries": []})
    entries = data.get("entries") or []
    scored: list[tuple[int, str]] = []
    for e in entries:
        if "_error" in e:
            continue
        name = e.get("name") or ""
        domain = e.get("domain") or ""
        kws = e.get("keywords") or []
        score = 0
        if area in domain or domain in area:
            score += 3
        if area in name:
            score += 2
        if any(area in kw or kw in area for kw in kws):
            score += 1
        if score > 0:
            scored.append((score, name[:40]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    seen: set[str] = set()
    out: list[str] = []
    for _, name in scored:
        if name not in seen:
            seen.add(name)
            out.append(name)
        if len(out) >= limit:
            break
    if not out:
        out.append(f"发送「{area}知识点」速查")
    return out


def week_summary(*, ref: date | None = None) -> dict[str, Any]:
    """周度总结（格式对齐月度总结）。"""
    today = ref or date.today()
    start, end, week_num = _week_bounds(today)
    bank = QuestionBank()
    records = bank.list_by_date_range(start, end)
    graded = [r for r in records if r.get("is_correct") is not None]

    total = len(graded)
    correct = sum(1 for r in graded if r.get("is_correct"))
    acc = _accuracy(correct, total)

    # vs 上周
    monday = date.fromisoformat(start)
    prev_start = (monday - timedelta(days=7)).isoformat()
    prev_end = (monday - timedelta(days=1)).isoformat()
    prev_graded = [
        r for r in bank.list_by_date_range(prev_start, prev_end)
        if r.get("is_correct") is not None
    ]
    prev_total = len(prev_graded)
    prev_correct = sum(1 for r in prev_graded if r.get("is_correct"))
    prev_acc = _accuracy(prev_correct, prev_total)
    vs_prev = round(acc - prev_acc, 1) if prev_total else None

    by_area = _area_stats(graded)
    weak = [
        a for a, s in by_area.items()
        if s["total"] >= 2 and _accuracy(s["correct"], s["total"]) < 50
    ]

    # 本周模考
    week_exams = [
        e for e in _load_exams()
        if start <= str(e.get("exam_date", ""))[:10] <= end
    ]

    # 本周新增错题
    errors = _load_json(ERROR_LOG_PATH, [])
    week_errors = [
        e for e in errors
        if isinstance(e, dict) and start <= str(e.get("date", "")) <= end
    ]
    error_by_area: dict[str, int] = defaultdict(int)
    for e in week_errors:
        error_by_area[e.get("knowledge_area") or "综合"] += 1
    top_error_areas = sorted(error_by_area.items(), key=lambda x: -x[1])[:3]

    active_days = len({r.get("date") for r in graded if r.get("date")})
    days_left = (EXAM_DATE - today).days

    lines = [
        "══════════════════════════════",
        f"📊 第 {week_num} 周备考周报（{start[5:]} ~ {end[5:]}）",
        "══════════════════════════════",
        "",
        f"📅 考试倒计时：{days_left} 天",
        f"📝 本周刷题：{total} 题（✅ {correct} / ❌ {total - correct}）",
        f"📈 总正确率：{acc}% {_bar(acc)}",
    ]
    if vs_prev is not None:
        arrow = "↑" if vs_prev > 0 else ("↓" if vs_prev < 0 else "→")
        lines.append(f"📉 vs 上周：{arrow} {abs(vs_prev)}%（上周 {prev_acc}%）")
    lines.append(f"📅 活跃刷题：{active_days} 天")

    if by_area:
        lines.extend(["", "📋 知识领域正确率："])
        rows = sorted(by_area.items(), key=lambda x: _accuracy(x[1]["correct"], x[1]["total"]))
        for area, s in rows:
            a = _accuracy(s["correct"], s["total"])
            tag = "🔴" if a < 50 else ("🟡" if a < 70 else "🟢")
            lines.append(f"  {tag} [{area}]: {s['correct']}/{s['total']}（{a}%） {_bar(a)}")

    if week_exams:
        lines.extend(["", f"🏁 本周模考：{len(week_exams)} 次"])
        for e in week_exams:
            lines.append(
                f"  · {e.get('exam_date', '?')[:10]} {e.get('exam_id', '模考')}: "
                f"{_exam_rate(e)}%"
            )

    if week_errors:
        lines.extend(["", f"❌ 本周新增错题：{len(week_errors)} 道"])
        if top_error_areas:
            parts = [f"{a} {n}题" for a, n in top_error_areas]
            lines.append(f"  高频领域：{' / '.join(parts)}")

    if weak:
        lines.extend(["", f"⚠️ 薄弱领域（<50%）：{'、'.join(weak[:3])}"])

    lines.extend([
        "",
        f"🎯 训练目标：70%（{TARGET_CORRECT}/{TARGET_TOTAL}）",
        "💡 下周建议：",
    ])
    if weak:
        lines.append(f"  1. 专项突破：{'、'.join(weak[:2])}")
    lines.append("  2. 发送「复习计划」获取错题专项清单")
    lines.append("  3. 保持每日一练 + 到期错题复习")

    return {
        "status": "ok" if graded or week_exams else "empty",
        "week": week_num,
        "start": start,
        "end": end,
        "total": total,
        "accuracy": acc,
        "vs_prev": vs_prev,
        "weak_areas": weak,
        "text": "\n".join(lines),
    }


def error_study_plan(*, horizon: str = "week") -> dict[str, Any]:
    """
    错题专项计划 — 三档优先级 + 推荐资源。
    horizon: 'today' | 'week'
    """
    bank = QuestionBank()
    all_recs = [r for r in bank.list_all() if r.get("is_correct") is not None]
    by_area = _area_stats(all_recs)

    # 补充 error_log 错题数
    errors = _load_json(ERROR_LOG_PATH, [])
    error_counts: dict[str, int] = defaultdict(int)
    for e in errors:
        if isinstance(e, dict):
            error_counts[e.get("knowledge_area") or "综合"] += 1

    tiers: dict[str, list[dict]] = {"urgent": [], "focus": [], "maintain": []}

    for area in ALL_AREAS:
        s = by_area.get(area, {"total": 0, "correct": 0, "wrong": 0})
        total = s["total"]
        acc = _accuracy(s["correct"], total) if total else None
        err_n = error_counts.get(area, 0)

        if total == 0 and err_n == 0:
            continue

        if acc is None and err_n > 0:
            acc = 0.0

        entry = {
            "area": area,
            "total": total,
            "correct": s["correct"],
            "accuracy": acc if acc is not None else 0.0,
            "errors": err_n,
            "resources": find_knowledge_resources(area),
        }

        eff_acc = acc if acc is not None else 0.0
        if eff_acc < 30 or (total < 5 and err_n >= 3):
            tiers["urgent"].append(entry)
        elif eff_acc < 60:
            tiers["focus"].append(entry)
        else:
            tiers["maintain"].append(entry)

    for key in tiers:
        tiers[key].sort(key=lambda x: (x["accuracy"], -x["errors"]))

    today = date.today()
    days_left = (EXAM_DATE - today).days

    lines = [
        "══════════════════════════════",
        f"📋 错题专项复习计划（{'今日' if horizon == 'today' else '本周'}）",
        "══════════════════════════════",
        "",
        f"📅 距考试 {days_left} 天 · 基于 {len(all_recs)} 题 + {len(errors)} 道错题",
        "",
    ]

    def _tier_block(title: str, emoji: str, items: list[dict], q_per_day: int) -> None:
        if not items:
            return
        lines.append(f"{emoji} {title}（{len(items)} 个领域）")
        lines.append("─" * 28)
        for i, it in enumerate(items[:5], 1):
            acc_str = f"{it['accuracy']:.0f}%" if it["total"] else "无做题"
            res = it["resources"][0] if it["resources"] else ""
            lines.append(
                f"{i}. [{it['area']}] 正确率 {acc_str} · 错题 {it['errors']} 道"
            )
            lines.append(f"   📚 资源：{res}")
            lines.append(f"   📝 建议：刷 {q_per_day} 题 + 复习错题")
        lines.append("")

    _tier_block("紧急突破（正确率 < 30%）", "🔴", tiers["urgent"], 20)
    _tier_block("重点巩固（30% ~ 60%）", "🟡", tiers["focus"], 15)
    _tier_block("保持手感（> 60%）", "🟢", tiers["maintain"], 5)

    # 今日/本周清单
    review_state = _load_json(REVIEW_STATE_PATH, {})
    due_today = [
        v for k, v in review_state.items()
        if isinstance(v, dict) and str(v.get("next_date", "")) <= today.isoformat()
    ]

    lines.append("📝 到期错题复习：" + (f"{len(due_today)} 道待复习" if due_today else "暂无"))
    cfg = _load_json(CONFIG_PATH, {})
    daily_done = today.isoformat() in (cfg.get("daily_completed") or [])

    lines.extend([
        "",
        "✅ 今日任务清单：" if horizon == "today" else "✅ 本周任务清单：",
        f"  {'✅' if daily_done else '⬜'} 每日一练 10 题",
        f"  {'✅' if not due_today else '⬜'} 错题复习 {len(due_today)} 道",
    ])
    if tiers["urgent"]:
        lines.append(f"  ⬜ 紧急领域：{tiers['urgent'][0]['area']} 专项 20 题")
    elif tiers["focus"]:
        lines.append(f"  ⬜ 重点领域：{tiers['focus'][0]['area']} 专项 15 题")

    # 冲刺计划联动
    plans = _load_json(SPRINT_PLANS_PATH, [])
    active = [p for p in plans if isinstance(p, dict) and p.get("status") == "active"]
    if active:
        plan = active[-1]
        day_plans = plan.get("day_plans") or []
        today_plan = next(
            (d for d in day_plans if d.get("date") == today.isoformat()),
            None,
        )
        if today_plan:
            lines.append(
                f"  ⬜ 冲刺 Day{today_plan.get('day')}: "
                f"{today_plan.get('knowledge_area')} {today_plan.get('suggested_questions', 10)} 题"
            )

    lines.extend(["", "💡 发送「复习错题」开始 SM-2 复习"])

    return {
        "status": "ok",
        "tiers": tiers,
        "due_errors": len(due_today),
        "text": "\n".join(lines),
    }


def today_review_checklist() -> dict[str, Any]:
    """今日复习清单（轻量版，供推送用）。"""
    return error_study_plan(horizon="today")


def mock_exam_analysis(exam_record: dict | None = None) -> dict[str, Any]:
    """模考完成后分析报告。"""
    if exam_record is None:
        exams = _load_exams()
        exam_record = exams[-1] if exams else None
    if not exam_record:
        return {"status": "empty", "text": "⚠️ 暂无模考记录。"}

    rate = _exam_rate(exam_record)
    correct = exam_record.get("correct_count", 0)
    total = exam_record.get("total_questions", 180)
    exam_id = exam_record.get("exam_id", "模考")
    exam_date = str(exam_record.get("exam_date", ""))[:10]
    time_used = exam_record.get("time_used_minutes", 0)
    weak = exam_record.get("weak_areas") or []

    # vs 上次
    exams = _load_exams()
    prev = exams[-2] if len(exams) >= 2 else None
    prev_rate = _exam_rate(prev) if prev else None
    vs_prev = round(rate - prev_rate, 1) if prev_rate is not None else None

    target_65 = rate >= 65
    target_70 = rate >= 70

    lines = [
        "══════════════════════════════",
        f"📊 模考分析：{exam_id}",
        "══════════════════════════════",
        "",
        f"📅 日期：{exam_date}",
        f"📝 得分：{correct}/{total}（{rate}%）",
    ]
    if time_used:
        lines.append(f"⏱️ 用时：{time_used} 分钟")
    if vs_prev is not None:
        arrow = "↑" if vs_prev > 0 else ("↓" if vs_prev < 0 else "→")
        lines.append(f"📈 vs 上次：{arrow} {abs(vs_prev)}%")

    lines.extend([
        "",
        f"🎯 模考评估线 65%：{'✅ 达标' if target_65 else f'⚠️ 差 {max(0, round(0.65 * total) - correct)} 题'}",
        f"🎯 训练目标 70%：{'✅ 达标' if target_70 else f'⚠️ 差 {max(0, round(0.70 * total) - correct)} 题'}",
    ])

    ka = exam_record.get("knowledge_areas") or {}
    if ka:
        lines.extend(["", "📋 领域正确率："])
        rows = []
        for area, val in ka.items():
            if isinstance(val, dict):
                r = val.get("rate", 0)
                if r <= 1:
                    r *= 100
                c, t = val.get("correct", 0), val.get("total", 0)
            else:
                r = float(val) * 100 if float(val) <= 1 else float(val)
                c, t = 0, 0
            rows.append((area, r, c, t))
        rows.sort(key=lambda x: x[1])
        for area, r, c, t in rows[:8]:
            tag = "🔴" if r < 50 else ("🟡" if r < 70 else "🟢")
            detail = f"{c}/{t}" if t else ""
            lines.append(f"  {tag} [{area}]: {r:.0f}% {detail} {_bar(r)}")

    if weak:
        lines.extend(["", f"⚠️ 薄弱领域：{'、'.join(weak[:3])}"])

    lines.extend([
        "",
        "💡 建议：",
        f"  1. 发送「{'、'.join(weak[:2]) if weak else '薄弱点'}」专项复习" if weak else "  1. 发送「薄弱点」查看诊断",
        "  2. 发送「复习计划」制定专项突破",
        "  3. 发送「分析趋势」查看整体走势",
    ])

    return {"status": "ok", "exam": exam_record, "text": "\n".join(lines)}


def check_accuracy_alert() -> dict[str, Any] | None:
    """连续 2 天正确率下降 > 10% → 预警。"""
    bank = QuestionBank()
    today = date.today()
    days: list[tuple[str, float, int]] = []
    for i in range(5, 0, -1):
        d = (today - timedelta(days=i)).isoformat()
        c, t, acc = _daily_accuracy(bank, d)
        if t >= 5:
            days.append((d, acc, t))

    if len(days) < 2:
        return None

    d1, acc1, t1 = days[-2]
    d2, acc2, t2 = days[-1]
    drop = round(acc1 - acc2, 1)
    if drop > 10:
        lines = [
            "🚨 正确率预警",
            "",
            f"📉 {d1[5:]}: {acc1}%（{t1} 题）",
            f"📉 {d2[5:]}: {acc2}%（{t2} 题）",
            f"⚠️ 连续下降 {drop}%，超过 10% 阈值",
            "",
            "💡 建议：",
            "  1. 暂停新题，先复习到期错题",
            "  2. 发送「薄弱点」诊断薄弱领域",
            "  3. 发送「复习计划」调整节奏",
        ]
        return {"status": "alert", "drop": drop, "text": "\n".join(lines)}
    return None


def parse_user_query(text: str) -> tuple[str, dict[str, Any]]:
    """
    解析用户消息 → (command, kwargs)。
    command: overview | week | month | plan | today | prep | mock | ''
    """
    t = text.strip()

    try:
        from pmp_athena.practice_overview import parse_trigger as overview_trigger
    except ImportError:
        from practice_overview import parse_trigger as overview_trigger

    if overview_trigger(t):
        return "overview", {}

    week_triggers = ("周报", "本周汇总", "本周总结", "周度总结", "上周总结", "本周报告")
    if any(k in t for k in week_triggers):
        return "week", {}

    plan_triggers = ("复习计划", "专项计划", "错题计划", "今日复习计划", "本周复习计划")
    if any(k in t for k in plan_triggers):
        horizon = "today" if "今日" in t else "week"
        return "plan", {"horizon": horizon}

    today_triggers = ("今日复习清单", "今天复习什么", "今日任务", "今日清单")
    if any(k in t for k in today_triggers):
        return "today", {}

    mock_triggers = ("模考分析", "分析模考", "上次模考")
    if any(k in t for k in mock_triggers):
        return "mock", {}

    month = parse_month_query(t)
    if month and re.search(r"(做题|刷题).{0,4}(情况|统计|汇总|总结)|总结", t):
        return "month", {"month": month}

    prep_triggers = ("备考总结", "备考刷题")
    if any(k in t for k in prep_triggers):
        return "prep", {}

    return "", {}


def handle_message(text: str) -> dict[str, Any]:
    """微信硬路由入口。"""
    cmd, kwargs = parse_user_query(text)
    if not cmd:
        return {"status": "skip"}

    if cmd == "overview":
        try:
            from pmp_athena.practice_overview import build_overview
        except ImportError:
            from practice_overview import build_overview
        return build_overview()

    if cmd == "week":
        return week_summary()
    if cmd == "month":
        return month_summary(month=kwargs["month"])
    if cmd == "prep":
        return prep_summary()
    if cmd == "plan":
        return error_study_plan(horizon=kwargs.get("horizon", "week"))
    if cmd == "today":
        return today_review_checklist()
    if cmd == "mock":
        return mock_exam_analysis()

    return {"status": "error", "text": "⚠️ 无法识别分析指令"}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="备考分析")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("week", help="周度总结")
    p_month = sub.add_parser("month", help="月度总结")
    p_month.add_argument("--month", "-m", type=int, default=date.today().month)
    p_month.add_argument("--year", "-y", type=int, default=EXAM_YEAR)

    p_plan = sub.add_parser("plan", help="错题专项计划")
    p_plan.add_argument("--horizon", choices=["today", "week"], default="week")

    sub.add_parser("today", help="今日复习清单")
    sub.add_parser("mock", help="最近一次模考分析")
    sub.add_parser("alert", help="检查正确率预警")
    sub.add_parser("prep", help="备考全程汇总")

    p_msg = sub.add_parser("message", help="解析微信消息")
    p_msg.add_argument("--text", "-t", required=True)

    for p in [sub.choices[c] for c in sub.choices if hasattr(sub.choices[c], "add_argument")]:
        if p != p_msg:
            p.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.command == "week":
        result = week_summary()
    elif args.command == "month":
        result = month_summary(year=args.year, month=args.month)
    elif args.command == "plan":
        result = error_study_plan(horizon=args.horizon)
    elif args.command == "today":
        result = today_review_checklist()
    elif args.command == "mock":
        result = mock_exam_analysis()
    elif args.command == "alert":
        result = check_accuracy_alert() or {"status": "ok", "text": "✅ 暂无正确率预警"}
    elif args.command == "prep":
        result = prep_summary()
    elif args.command == "message":
        result = handle_message(args.text)
        if result.get("status") == "skip":
            result = {"status": "skip", "text": ""}
    else:
        result = today_review_checklist()

    if getattr(args, "json", False) or args.command == "message":
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result.get("text", ""))


if __name__ == "__main__":
    main()
