#!/usr/bin/env python3
"""
刷题汇总 — 月度 / 备考全程统计。

用法:
    python pmp_athena/practice_summary.py month --month 7
    python pmp_athena/practice_summary.py month --month 7 --year 2026 --json
    python pmp_athena/practice_summary.py prep --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from calendar import monthrange
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

try:
    from pmp_athena.question_bank import QuestionBank, DEFAULT_BANK_PATH
except ModuleNotFoundError:
    from question_bank import QuestionBank, DEFAULT_BANK_PATH

EXAM_YEAR = 2026
TARGET_ACCURACY = 0.70
TARGET_CORRECT = 126
TARGET_TOTAL = 180
PASS_CORRECT = 106


def _bar(pct: float, width: int = 8) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _area_stats(records: list[dict]) -> dict[str, dict[str, int]]:
    area: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0, "wrong": 0})
    for r in records:
        if r.get("is_correct") is None:
            continue
        a = r.get("knowledge_area") or "综合"
        area[a]["total"] += 1
        if r.get("is_correct"):
            area[a]["correct"] += 1
        else:
            area[a]["wrong"] += 1
    return dict(area)


def _accuracy(correct: int, total: int) -> float:
    return round(correct / total * 100, 1) if total else 0.0


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last = monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last:02d}"


def _load_exam_records() -> list[dict]:
    path = DEFAULT_BANK_PATH.parent / "exam_records.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        exams = data.get("exams", data if isinstance(data, list) else [])
        return [e for e in exams if e.get("status") == "completed"]
    except (json.JSONDecodeError, OSError):
        return []


def month_summary(*, year: int | None = None, month: int) -> dict[str, Any]:
    y = year or EXAM_YEAR
    bank = QuestionBank()
    start, end = _month_bounds(y, month)
    records = bank.list_by_date_range(start, end)
    graded = [r for r in records if r.get("is_correct") is not None]

    total = len(graded)
    correct = sum(1 for r in graded if r.get("is_correct"))
    wrong = total - correct
    acc = _accuracy(correct, total)

    # vs 上月
    prev_month = month - 1
    prev_year = y
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1
    p_start, p_end = _month_bounds(prev_year, prev_month)
    prev_graded = [
        r for r in bank.list_by_date_range(p_start, p_end)
        if r.get("is_correct") is not None
    ]
    prev_total = len(prev_graded)
    prev_correct = sum(1 for r in prev_graded if r.get("is_correct"))
    prev_acc = _accuracy(prev_correct, prev_total)
    vs_prev = round(acc - prev_acc, 1) if prev_total else None

    by_area = _area_stats(graded)
    area_rows = sorted(
        by_area.items(),
        key=lambda x: _accuracy(x[1]["correct"], x[1]["total"]),
    )

    weak = [a for a, s in area_rows if s["total"] >= 3 and _accuracy(s["correct"], s["total"]) < 70]
    strong = [a for a, s in area_rows if s["total"] >= 3 and _accuracy(s["correct"], s["total"]) >= 70]

    gap_questions = max(0, round(TARGET_ACCURACY * total) - correct) if total else 0

    lines = [
        f"📊 {y}年{month}月刷题总结（{total} 题）",
        "",
        f"📈 总正确率：{acc}%（{correct}/{total}）",
    ]
    if vs_prev is not None:
        arrow = "↑" if vs_prev > 0 else ("↓" if vs_prev < 0 else "→")
        lines.append(f"📉 vs 上月：{arrow} {abs(vs_prev)}%（上月 {prev_acc}%）")
    elif prev_total == 0:
        lines.append("📉 vs 上月：暂无上月数据")

    active_days = len({r.get("date") for r in graded if r.get("date")})
    lines.append(f"📅 活跃刷题：{active_days} 天")

    if by_area:
        lines.append("")
        lines.append("📋 按知识领域：")
        for area, s in sorted(by_area.items(), key=lambda x: -x[1]["total"]):
            a = _accuracy(s["correct"], s["total"])
            lines.append(f"  [{area}]: {s['correct']}/{s['total']}（{a}%） {_bar(a)}")

    lines.extend([
        "",
        f"🎯 当前目标 70%（{TARGET_CORRECT}/{TARGET_TOTAL}）",
    ])
    if total:
        if acc >= 70:
            lines.append("✅ 本月已达训练目标，继续保持！")
        else:
            lines.append(f"差距：差约 {gap_questions} 题（按本月题量折算）")

    lines.append("")
    lines.append("💡 建议：")
    if weak:
        lines.append(f"  · 薄弱领域：{'、'.join(weak[:3])} 需重点加强")
    if strong:
        lines.append(f"  · 继续保持：{'、'.join(strong[:3])} 已达标")
    if not graded:
        lines.append("  · 本月暂无刷题记录，建议每天完成一套每日一练")
    elif not weak and acc >= 70:
        lines.append("  · 各域表现均衡，可加大模考频率")

    return {
        "status": "ok" if graded else "empty",
        "year": y,
        "month": month,
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "accuracy": acc,
        "vs_prev": vs_prev,
        "by_area": by_area,
        "text": "\n".join(lines),
    }


def prep_summary(*, year: int | None = None) -> dict[str, Any]:
    """备考全程刷题 + 模考汇总。"""
    y = year or EXAM_YEAR
    bank = QuestionBank()
    all_records = bank.list_all()
    graded = [
        r for r in all_records
        if r.get("is_correct") is not None and str(r.get("date", "")).startswith(str(y))
    ]

    total = len(graded)
    correct = sum(1 for r in graded if r.get("is_correct"))
    wrong = total - correct
    acc = _accuracy(correct, total)

    # 按月 breakdown
    by_month: dict[int, list[dict]] = defaultdict(list)
    for r in graded:
        d = r.get("date", "")
        if len(d) >= 7:
            try:
                m = int(d[5:7])
                by_month[m].append(r)
            except ValueError:
                pass

    exams = _load_exam_records()
    year_exams = [e for e in exams if str(e.get("exam_date", "")).startswith(str(y))]

    first_date = min((r.get("date") for r in graded if r.get("date")), default=None)
    active_days = len({r.get("date") for r in graded if r.get("date")})

    by_area = _area_stats(graded)
    area_rows = sorted(
        by_area.items(),
        key=lambda x: _accuracy(x[1]["correct"], x[1]["total"]),
    )
    weak = [a for a, s in area_rows if s["total"] >= 5 and _accuracy(s["correct"], s["total"]) < 60]
    mid = [a for a, s in area_rows if s["total"] >= 5 and 60 <= _accuracy(s["correct"], s["total"]) < 70]
    strong = [a for a, s in area_rows if s["total"] >= 5 and _accuracy(s["correct"], s["total"]) >= 70]

    today = date.today()
    days_left = (date(EXAM_YEAR, 9, 12) - today).days

    lines = [
        "══════════════════════════════",
        f"📊 PMP 备考刷题总览（{y}）",
        "══════════════════════════════",
        "",
        f"📅 考试倒计时：{days_left} 天（2026-09-12）",
    ]
    if first_date:
        lines.append(f"📆 备考起始：{first_date} · 累计活跃 {active_days} 天")

    lines.extend([
        "",
        f"📝 累计刷题：{total} 题（✅ {correct} / ❌ {wrong}）",
        f"📈 总正确率：{acc}%",
        f"🎯 训练目标：70%（{TARGET_CORRECT}/{TARGET_TOTAL}）"
        + (" ✅ 已达标" if acc >= 70 else f" · 差约 {max(0, round(TARGET_ACCURACY * total) - correct)} 题"),
        f"📌 通过线参考：59%（{PASS_CORRECT}/{TARGET_TOTAL}）"
        + (" ✅" if acc >= 59 else ""),
    ])

    if by_month:
        lines.append("")
        lines.append("📆 月度趋势：")
        for m in sorted(by_month.keys()):
            recs = by_month[m]
            c = sum(1 for r in recs if r.get("is_correct"))
            t = len(recs)
            lines.append(f"  {m}月：{t} 题，正确率 {_accuracy(c, t)}%")

    if year_exams:
        lines.append("")
        lines.append(f"🏁 模考记录：{len(year_exams)} 次")
        for e in year_exams[-5:]:
            rate = round(float(e.get("correct_rate", 0)) * 100, 1)
            if rate <= 1 and e.get("correct_count") and e.get("total_questions"):
                rate = _accuracy(e["correct_count"], e["total_questions"])
            lines.append(
                f"  · {e.get('exam_date', '?')} {e.get('exam_id', '模考')}: "
                f"{e.get('correct_count', '?')}/{e.get('total_questions', '?')}（{rate}%）"
            )

    if by_area:
        lines.append("")
        lines.append("📋 知识领域（累计）：")
        for area, s in sorted(by_area.items(), key=lambda x: -x[1]["total"])[:12]:
            a = _accuracy(s["correct"], s["total"])
            tag = "🔴" if a < 60 else ("🟡" if a < 70 else "🟢")
            lines.append(f"  {tag} [{area}]: {s['correct']}/{s['total']}（{a}%）")

    lines.append("")
    lines.append("💡 备考建议：")
    if weak:
        lines.append(f"  1. 优先突破：{'、'.join(weak[:3])}")
    if mid:
        lines.append(f"  2. 巩固提升：{'、'.join(mid[:3])}")
    if acc < 70:
        lines.append("  3. 保持每日一练 + 错题复习，稳住 70% 训练线")
    elif not year_exams:
        lines.append("  3. 正确率已达标，建议开始完整模考检验")
    else:
        lines.append("  3. 保持节奏，每周 1-2 次模考查漏补缺")

    return {
        "status": "ok" if graded else "empty",
        "year": y,
        "total": total,
        "correct": correct,
        "accuracy": acc,
        "active_days": active_days,
        "exam_count": len(year_exams),
        "by_month": {m: len(v) for m, v in by_month.items()},
        "text": "\n".join(lines),
    }


def parse_month_query(text: str) -> int | None:
    """从「7月做题情况」等文本解析月份。"""
    text = text.strip().replace("份", "")
    m = re.search(r"(\d{1,2})\s*月", text)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return month
    return None


def parse_user_query(text: str) -> tuple[str, int | None]:
    """
    返回 (command, month)。
    command: 'month' | 'prep' | ''
    """
    t = text.strip()
    prep_triggers = (
        "备考总结", "备考刷题", "刷题总结", "做题总结", "做题情况总结",
        "总结一下做题", "总结做题", "备考情况", "备考刷题情况",
        "这几个月", "全程总结", "刷题总览",
    )
    if any(k in t for k in prep_triggers):
        return "prep", None
    if re.search(r"\d{1,2}\s*月", t) and re.search(
        r"(做题|刷题).{0,4}(情况|统计|汇总|总结)|"
        r"(情况|统计|汇总|总结).{0,4}(做题|刷题)",
        t,
    ):
        month = parse_month_query(t)
        if month:
            return "month", month
    # 仅「7月刷题」「7月做题」
    m = re.fullmatch(r"(\d{1,2})月(?:刷题|做题)", t.replace("份", ""))
    if m:
        return "month", int(m.group(1))
    return "", None


def main() -> None:
    parser = argparse.ArgumentParser(description="刷题汇总")
    sub = parser.add_subparsers(dest="command")

    p_month = sub.add_parser("month", help="月度刷题汇总")
    p_month.add_argument("--month", "-m", type=int, required=True)
    p_month.add_argument("--year", "-y", type=int, default=EXAM_YEAR)
    p_month.add_argument("--json", action="store_true")

    p_prep = sub.add_parser("prep", help="备考全程汇总")
    p_prep.add_argument("--year", "-y", type=int, default=EXAM_YEAR)
    p_prep.add_argument("--json", action="store_true")

    p_parse = sub.add_parser("parse", help="解析用户自然语言")
    p_parse.add_argument("text")
    p_parse.add_argument("--json", action="store_true")

    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    if args.command == "month":
        result = month_summary(year=args.year, month=args.month)
    elif args.command == "prep":
        result = prep_summary(year=args.year)
    elif args.command == "parse":
        cmd, month = parse_user_query(args.text)
        if cmd == "month" and month:
            result = month_summary(month=month)
        elif cmd == "prep":
            result = prep_summary()
        else:
            result = {"status": "error", "text": "⚠️ 无法识别汇总指令"}
    else:
        result = prep_summary()

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result.get("text", ""))


if __name__ == "__main__":
    main()
