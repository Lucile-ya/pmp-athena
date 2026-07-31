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


def _prev_month_year(year: int, month: int) -> tuple[int, int]:
    if month <= 1:
        return year - 1, 12
    return year, month - 1


def _month_prefix(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def _exams_in_month(exams: list[dict], year: int, month: int) -> list[dict]:
    prefix = _month_prefix(year, month)
    return [e for e in exams if str(e.get("exam_date", "")).startswith(prefix)]


def _exam_rate(e: dict) -> float:
    rate = float(e.get("correct_rate") or 0)
    if rate <= 1:
        rate *= 100
    if rate <= 1 and e.get("correct_count") and e.get("total_questions"):
        rate = _accuracy(e["correct_count"], e["total_questions"])
    return round(rate, 1)


def _exam_avg_rate(exams: list[dict]) -> float | None:
    if not exams:
        return None
    return round(sum(_exam_rate(e) for e in exams) / len(exams), 1)


def _delta_label(
    curr: float,
    prev: float,
    *,
    higher_is_better: bool = True,
    unit: str = "",
) -> tuple[str, str, str]:
    """
    返回 (箭头, 差值文案, 状态 emoji)。
    例: ("↑", "+5.2%", "🎉")
    """
    diff = round(curr - prev, 1)
    if abs(diff) < 0.5:
        return "→", "持平", ""
    improved = diff > 0 if higher_is_better else diff < 0
    arrow = "↑" if diff > 0 else "↓"
    sign = f"+{diff}" if diff > 0 else str(diff)
    if improved:
        emoji = "🎉" if abs(diff) >= 10 else "✅"
    else:
        emoji = "⚠️" if abs(diff) >= 10 else ""
    return arrow, f"{sign}{unit}", emoji


def _collect_month_stats(
    bank: QuestionBank,
    year: int,
    month: int,
) -> dict[str, Any]:
    start, end = _month_bounds(year, month)
    records = bank.list_by_date_range(start, end)
    graded = [r for r in records if r.get("is_correct") is not None]
    total = len(graded)
    correct = sum(1 for r in graded if r.get("is_correct"))
    return {
        "year": year,
        "month": month,
        "total": total,
        "correct": correct,
        "accuracy": _accuracy(correct, total),
        "active_days": len({r.get("date") for r in graded if r.get("date")}),
        "by_area": _area_stats(graded),
        "exams": _exams_in_month(_load_exam_records(), year, month),
    }


def _format_month_compare(
    curr: dict[str, Any],
    prev: dict[str, Any],
    *,
    has_prev_practice: bool,
    has_prev_exams: bool,
) -> tuple[list[str], dict[str, Any]]:
    """生成「月度对比」区块。"""
    cy, cm = curr["year"], curr["month"]
    py, pm = prev["year"], prev["month"]

    lines = [
        "",
        "══════════════════════",
        f"📊 月度对比（vs {pm}月）",
        "══════════════════════",
        "",
    ]

    compare_meta: dict[str, Any] = {
        "prev_month": pm,
        "prev_year": py,
        "has_prev_data": has_prev_practice or has_prev_exams,
    }

    if not has_prev_practice and not has_prev_exams:
        lines.append("📌 首月记录，暂无对比")
        return lines, compare_meta

    # ── 刷题量 / 正确率 / 活跃天数 ──
    if has_prev_practice:
        if curr["total"] or prev["total"]:
            arr, diff, em = _delta_label(curr["total"], prev["total"])
            lines.append(
                f"📝 刷题量：{curr['total']} 题  {arr} {diff}（上月 {prev['total']} 题） {em}".rstrip()
            )
            compare_meta["volume_delta"] = curr["total"] - prev["total"]

        if curr["total"] and prev["total"]:
            arr, diff, em = _delta_label(curr["accuracy"], prev["accuracy"])
            lines.append(
                f"📈 正确率：{curr['accuracy']}%  {arr} {diff}%（上月 {prev['accuracy']}%） {em}".rstrip()
            )
            compare_meta["accuracy_delta"] = round(curr["accuracy"] - prev["accuracy"], 1)
        elif curr["total"] and not prev["total"]:
            tag = "✅" if curr["accuracy"] >= 70 else ("⚠️" if curr["accuracy"] < 50 else "")
            lines.append(f"📈 正确率：{curr['accuracy']}%（上月无刷题） {tag}".rstrip())

        if curr["active_days"] or prev["active_days"]:
            arr, diff, _ = _delta_label(float(curr["active_days"]), float(prev["active_days"]))
            lines.append(
                f"📅 活跃天数：{curr['active_days']} 天  {arr} {diff}（上月 {prev['active_days']} 天）"
            )
    elif has_prev_exams:
        lines.append("📝 刷题量：本月暂无（上月亦无）")

    # ── 各领域正确率对比 ──
    curr_areas = curr.get("by_area") or {}
    prev_areas = prev.get("by_area") or {}
    all_areas = sorted(set(curr_areas) | set(prev_areas))

    area_changes: list[tuple[str, float, float, float]] = []
    for area in all_areas:
        cs = curr_areas.get(area, {"total": 0, "correct": 0})
        ps = prev_areas.get(area, {"total": 0, "correct": 0})
        if cs["total"] < 2 and ps["total"] < 2:
            continue
        ca = _accuracy(cs["correct"], cs["total"]) if cs["total"] else 0.0
        pa = _accuracy(ps["correct"], ps["total"]) if ps["total"] else 0.0
        area_changes.append((area, ca, pa, round(ca - pa, 1)))

    if area_changes:
        lines.append("")
        lines.append("📋 领域正确率变化：")
        area_changes.sort(key=lambda x: -abs(x[3]))
        for area, ca, pa, delta in area_changes[:8]:
            cs = curr_areas.get(area, {"total": 0})
            ps = prev_areas.get(area, {"total": 0})
            if cs["total"] >= 2 and ps["total"] >= 2:
                arr, _, em = _delta_label(ca, pa)
                delta_str = "持平" if abs(delta) < 0.5 else f"{delta:+.1f}%"
                lines.append(
                    f"  {em or '·'} [{area}] {pa}% → {ca}%  {arr} {delta_str}"
                )
            elif cs["total"] >= 2:
                tag = "🎉" if ca >= 70 else ("⚠️" if ca < 50 else "✅")
                lines.append(f"  {tag} [{area}] 新增 {ca}%（{cs['correct']}/{cs['total']}）")
            elif ps["total"] >= 2:
                lines.append(f"  · [{area}] 上月 {pa}% → 本月未练习")

    # ── 模考成绩对比 ──
    curr_exams = curr.get("exams") or []
    prev_exams = prev.get("exams") or []
    curr_exam_avg = _exam_avg_rate(curr_exams)
    prev_exam_avg = _exam_avg_rate(prev_exams)

    lines.append("")
    lines.append("🏁 模考成绩：")
    if curr_exams:
        for e in curr_exams:
            rate = _exam_rate(e)
            name = e.get("exam_id", "模考")
            cc = e.get("correct_count", "?")
            tq = e.get("total_questions", "?")
            lines.append(f"  本月 · {name}: {rate}%（{cc}/{tq}）")
    else:
        lines.append("  本月 · 无模考记录")

    if prev_exams:
        for e in prev_exams:
            rate = _exam_rate(e)
            name = e.get("exam_id", "模考")
            cc = e.get("correct_count", "?")
            tq = e.get("total_questions", "?")
            lines.append(f"  上月 · {name}: {rate}%（{cc}/{tq}）")
    else:
        lines.append("  上月 · 无模考记录")

    if curr_exam_avg is not None and prev_exam_avg is not None:
        arr, diff, em = _delta_label(curr_exam_avg, prev_exam_avg)
        lines.append(
            f"  对比 · 平均 {curr_exam_avg}%  {arr} {diff}%（上月 {prev_exam_avg}%） {em}".rstrip()
        )
        compare_meta["exam_avg_delta"] = round(curr_exam_avg - prev_exam_avg, 1)
    elif curr_exam_avg is not None and prev_exam_avg is None:
        tag = "🎉" if curr_exam_avg >= 65 else "⚠️"
        lines.append(f"  对比 · 本月首次模考 {curr_exam_avg}% {tag}")
    elif curr_exam_avg is None and prev_exam_avg is not None:
        lines.append(f"  对比 · 上月 {prev_exam_avg}%，本月未模考 ⚠️")

    return lines, compare_meta


def month_summary(*, year: int | None = None, month: int) -> dict[str, Any]:
    y = year or EXAM_YEAR
    bank = QuestionBank()

    curr_stats = _collect_month_stats(bank, y, month)
    total = curr_stats["total"]
    correct = curr_stats["correct"]
    wrong = total - correct
    acc = curr_stats["accuracy"]
    by_area = curr_stats["by_area"]
    graded = bank.list_by_date_range(*_month_bounds(y, month))
    graded = [r for r in graded if r.get("is_correct") is not None]

    # 上月数据
    prev_y, prev_m = _prev_month_year(y, month)
    prev_stats = _collect_month_stats(bank, prev_y, prev_m)
    has_prev_practice = prev_stats["total"] > 0
    has_prev_exams = len(prev_stats["exams"]) > 0

    vs_prev = (
        round(acc - prev_stats["accuracy"], 1)
        if has_prev_practice and total
        else None
    )

    area_rows = sorted(
        by_area.items(),
        key=lambda x: _accuracy(x[1]["correct"], x[1]["total"]),
    )

    weak = [a for a, s in area_rows if s["total"] >= 3 and _accuracy(s["correct"], s["total"]) < 70]
    strong = [a for a, s in area_rows if s["total"] >= 3 and _accuracy(s["correct"], s["total"]) >= 70]

    gap_questions = max(0, round(TARGET_ACCURACY * total) - correct) if total else 0
    active_days = curr_stats["active_days"]

    lines = [
        f"📊 {y}年{month}月刷题总结（{total} 题）",
        "",
        f"📈 总正确率：{acc}%（{correct}/{total}）",
    ]
    if vs_prev is not None:
        arrow = "↑" if vs_prev > 0 else ("↓" if vs_prev < 0 else "→")
        emoji = "🎉" if vs_prev >= 10 else ("✅" if vs_prev > 0 else ("⚠️" if vs_prev <= -10 else ""))
        lines.append(
            f"📉 vs 上月：{arrow} {abs(vs_prev)}%（上月 {prev_stats['accuracy']}%） {emoji}".rstrip()
        )
    elif not has_prev_practice and not has_prev_exams:
        lines.append("📉 vs 上月：首月记录，暂无对比")
    elif not total and has_prev_practice:
        lines.append(
            f"📉 vs 上月：本月暂无刷题（上月 {prev_stats['accuracy']}% / {prev_stats['total']} 题） ⚠️"
        )
    elif total and not has_prev_practice:
        tag = "✅" if acc >= 70 else ""
        lines.append(f"📉 vs 上月：上月无刷题，本月 {acc}% {tag}".rstrip())
    else:
        lines.append("📉 vs 上月：数据不足，详见下方月度对比")

    lines.append(f"📅 活跃刷题：{active_days} 天")

    if by_area:
        lines.append("")
        lines.append("📋 按知识领域：")
        for area, s in sorted(by_area.items(), key=lambda x: -x[1]["total"]):
            a = _accuracy(s["correct"], s["total"])
            tag = "🔴" if a < 50 else ("🟡" if a < 70 else "🟢")
            lines.append(f"  {tag} [{area}]: {s['correct']}/{s['total']}（{a}%） {_bar(a)}")

    # 本月模考摘要
    curr_exams = curr_stats["exams"]
    if curr_exams:
        lines.append("")
        lines.append(f"🏁 本月模考：{len(curr_exams)} 次")
        for e in curr_exams:
            rate = _exam_rate(e)
            lines.append(
                f"  · {e.get('exam_date', '?')[:10]} {e.get('exam_id', '模考')}: "
                f"{rate}%（{e.get('correct_count', '?')}/{e.get('total_questions', '?')}）"
            )

    lines.extend([
        "",
        f"🎯 当前目标 70%（{TARGET_CORRECT}/{TARGET_TOTAL}）",
    ])
    if total:
        if acc >= 70:
            lines.append("✅ 本月已达训练目标，继续保持！")
        else:
            lines.append(f"⚠️ 差距：差约 {gap_questions} 题（按本月题量折算）")

    # 月度对比详细区块
    compare_lines, compare_meta = _format_month_compare(
        curr_stats,
        prev_stats,
        has_prev_practice=has_prev_practice,
        has_prev_exams=has_prev_exams,
    )
    lines.extend(compare_lines)

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
        "status": "ok" if graded or curr_exams else "empty",
        "year": y,
        "month": month,
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "accuracy": acc,
        "vs_prev": vs_prev,
        "by_area": by_area,
        "month_compare": compare_meta,
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
        "这几个月", "全程总结",
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
