#!/usr/bin/env python3
"""
做题总览 — 纯 JSON 驱动，无外部依赖。
触发词: 做题数据 / 做题汇总 / 做题情况 / 做题总览 / 今日状态 / 今天进度
"""

import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import QUESTION_BANK_PATH, ERROR_LOG_PATH, REVIEW_STATE_PATH
except ModuleNotFoundError:
    from config import QUESTION_BANK_PATH, ERROR_LOG_PATH, REVIEW_STATE_PATH


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return [] if path.suffix == ".json" else {}


def generate_overview() -> str:
    bank = _load(QUESTION_BANK_PATH)
    if not isinstance(bank, list):
        bank = []
    errors = _load(ERROR_LOG_PATH)
    if not isinstance(errors, list):
        errors = []
    review = _load(REVIEW_STATE_PATH)
    if not isinstance(review, dict):
        review = {}

    today = date.today()
    today_str = today.isoformat()
    week_ago = (today - timedelta(days=7)).isoformat()

    total = len(bank)
    if total == 0:
        return "📊 暂无做题记录。发送「每日一练」开始刷题！"

    correct = sum(1 for r in bank if r.get("is_correct"))
    wrong = total - correct
    overall_pct = correct / max(1, total) * 100

    # Today
    today_records = [r for r in bank if (r.get("date") or "")[:10] == today_str]
    today_correct = sum(1 for r in today_records if r.get("is_correct"))
    today_total = len(today_records)

    # This week
    this_week = [r for r in bank if (r.get("date") or "") >= week_ago]
    w_correct = sum(1 for r in this_week if r.get("is_correct"))
    w_total = len(this_week)
    w_pct = w_correct / max(1, w_total) * 100

    # By knowledge area
    area_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in bank:
        area = r.get("knowledge_area", "未分类")
        if area == "综合":
            continue  # 合并到其他
        area_stats[area]["total"] += 1
        if r.get("is_correct"):
            area_stats[area]["correct"] += 1

    # Error counts per area
    area_errors: dict[str, int] = Counter()
    for e in errors:
        area = e.get("knowledge_area", "未分类")
        area_errors[area] += 1

    # Review progress
    total_review_cards = len(review)
    due_today = sum(1 for v in review.values() if v.get("next_date", "9999") <= today_str)
    mastered = sum(1 for v in review.values() if v.get("interval", 0) >= 21)

    # Target assessment
    target_70 = 0.70
    gap = target_70 - (overall_pct / 100)
    if gap <= 0:
        target_line = "🟢 已达 70% 目标"
    elif gap <= 0.05:
        target_line = f"🟡 距 70% 目标差 {int(gap * total):.0f} 题"
    elif gap <= 0.10:
        target_line = f"🟠 需提升 {int(gap * 100)} 个百分点"
    else:
        target_line = f"🔴 距目标较远（{overall_pct:.0f}% vs 70%）"

    # Most recent practice date
    dates = sorted({(r.get("date") or "")[:10] for r in bank if r.get("date")}, reverse=True)
    last_date = dates[0] if dates else "无"

    lines = [
        "📊 PMP 做题总览",
        "══════════════════",
        "",
        f"📅 最近刷题: {last_date}",
        f"📝 累计: {total} 题 | ✅ {correct} | ❌ {wrong} | 📈 {overall_pct:.0f}%",
        "",
        f"🕐 今日: {today_correct}/{today_total} 正确" if today_total > 0 else "🕐 今日: 尚未刷题",
        f"📆 近 7 天: {w_correct}/{w_total} 正确 ({w_pct:.0f}%)",
        f"🎯 目标: {target_line}",
    ]

    # Review
    if total_review_cards > 0:
        lines.extend([
            "",
            f"🔄 SM-2 错题复习: {total_review_cards} 排队 | 📅 {due_today} 今日到期 | 🏆 {mastered} 已掌握",
        ])

    # Area breakdown
    lines.extend(["", "📈 各领域正确率"])

    for area in sorted(area_stats, key=lambda a: -area_stats[a]["total"]):
        s = area_stats[area]
        rate = s["correct"] / max(1, s["total"]) * 100
        bar_width = 10
        filled = int(bar_width * rate / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        err_count = area_errors.get(area, 0)
        emoji = "🟢" if rate >= 70 else ("🟡" if rate >= 50 else "🔴")
        lines.append(
            f"  {emoji} {area:8s} {s['correct']:3d}/{s['total']:3d} ({rate:3.0f}%) [{bar}] 错{err_count}题"
        )

    # Weakest areas
    weakest = [(a, s["correct"] / max(1, s["total"]) * 100, s["total"])
               for a, s in area_stats.items()]
    weakest.sort(key=lambda x: x[1])
    top_weak = [w for w in weakest if w[1] < 60 and w[2] >= 3][:3]

    if top_weak:
        lines.extend([
            "",
            "🩺 需重点突破:",
        ])
        for area, rate, cnt in top_weak:
            lines.append(f"  · {area}: {rate:.0f}%（{cnt}题）")

    lines.extend([
        "",
        "💡 发送「复习错题」开始复习 | 「每日一练」刷题 | 「薄弱点」专项分析",
    ])

    return "\n".join(lines)


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    print(generate_overview())


if __name__ == "__main__":
    main()
