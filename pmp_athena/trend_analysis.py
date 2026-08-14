#!/usr/bin/env python3
"""
PMP 趋势分析与通过率预测 — 微信硬路由入口。

触发词: 分析趋势 / 通过率预测 / 预测通过率 / 趋势分析 / 我的趋势 / 成绩趋势

数据来源: exam_records.json（模考）+ question_bank.json（每日一练）。
与 practice_overview_light.py 同源，供 athena-router.ts 硬路由调用。
"""

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import QUESTION_BANK_PATH, EXAM_RECORDS_PATH
except ModuleNotFoundError:
    from config import QUESTION_BANK_PATH, EXAM_RECORDS_PATH


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _pct(rate: float) -> float:
    """正确率归一化为百分数（0.5556 -> 55.56）。"""
    if rate is None:
        return 0.0
    if rate <= 1.0:
        return rate * 100
    return rate


def _trend_arrow(seq: list[float]) -> str:
    """最近 3 次正确率的趋势方向。"""
    if len(seq) < 2:
        return "→"
    if seq[-1] > seq[-2] + 0.5:
        return "↑"
    if seq[-1] < seq[-2] - 0.5:
        return "↓"
    return "→"


def _bar(rate: float, width: int = 10) -> str:
    filled = round(rate / 100 * width)
    return "█" * filled + "░" * (width - filled)


def generate_report() -> str:
    exams_data = _load(EXAM_RECORDS_PATH)
    exams = exams_data.get("exams", []) if isinstance(exams_data, dict) else []
    # 只统计正式模考，排除章节练习
    mocks = [
        e for e in exams
        if e.get("status") == "completed"
        and "章节" not in str(e.get("exam_id", ""))
        and "练习" not in str(e.get("exam_id", ""))
    ]
    mocks.sort(key=lambda e: e.get("exam_date", ""))

    bank = _load(QUESTION_BANK_PATH)
    bank = bank if isinstance(bank, list) else []

    lines = [
        "══════════════════════════════",
        "📈 PMP 趋势分析报告",
        "══════════════════════════════",
        "",
    ]

    # ── 模考趋势 ──
    if len(mocks) < 2:
        lines.append(f"📊 模考成绩趋势: ⚠️ 模考数据不足（需要至少 2 次模考，当前 {len(mocks)} 次）")
        lines.append("")
    else:
        rates = [_pct(e.get("correct_rate", 0)) for e in mocks]
        recent3 = rates[-3:]
        all_avg = sum(rates) / len(rates)
        arrow = _trend_arrow(recent3)

        seq_str = " → ".join(
            f"{e.get('exam_date', '?')} {_pct(e.get('correct_rate', 0)):.0f}%"
            for e in mocks[-3:]
        )
        lines.append("📊 模考成绩趋势:")
        lines.append(f"  最近 {len(recent3)} 次: {seq_str}（趋势: {arrow}）")
        lines.append(f"  全部均值: {all_avg:.0f}%（共 {len(mocks)} 次模考）")
        lines.append("")

    # ── 每日一练趋势（最近 7 天）──
    daily: dict[str, dict] = defaultdict(lambda: {"c": 0, "t": 0})
    for r in bank:
        d = str(r.get("date", ""))[:10]
        if not d or r.get("is_correct") is None:
            continue
        daily[d]["t"] += 1
        if r.get("is_correct"):
            daily[d]["c"] += 1

    if daily:
        today = date.today()
        last7 = [
            (today - timedelta(days=i)).isoformat()
            for i in range(6, -1, -1)
        ]
        active = [(d, daily[d]) for d in last7 if d in daily and daily[d]["t"] > 0]
        if active:
            lines.append("📝 每日一练趋势（最近 7 天）:")
            for d, st in active:
                rate = st["c"] / st["t"] * 100
                lines.append(f"  {d[5:].replace('-', '/')} {_bar(rate)} {rate:.0f}%（{st['c']}/{st['t']}）")
            lines.append("")
        else:
            lines.append("📝 每日一练趋势: 近 7 天无记录")
            lines.append("")
    else:
        lines.append("📝 每日一练趋势: 无记录")
        lines.append("")

    # ── 知识领域变化 ──
    area_records = [e for e in mocks if e.get("knowledge_areas")]
    if area_records:
        # 有领域细分数据时，与全部均值对比（简化为最近 3 次 vs 全部）
        all_area: dict[str, list] = defaultdict(list)
        for e in mocks:
            for a, v in (e.get("knowledge_areas") or {}).items():
                if isinstance(v, dict):
                    rate = v.get("rate", v.get("correct_rate", 0))
                else:
                    rate = v
                all_area[a].append(_pct(float(rate)))
        lines.append("🔍 知识领域变化:")
        for a, vals in all_area.items():
            recent = vals[-3:] if vals else []
            avg_all = sum(vals) / len(vals)
            avg_recent = sum(recent) / len(recent) if recent else avg_all
            diff = avg_recent - avg_all
            tag = "↑ 改善" if diff > 5 else ("↓ 恶化" if diff < -5 else "→ 持平")
            lines.append(f"  {tag}: {a} 全部 {avg_all:.0f}% → 最近 {avg_recent:.0f}%")
        lines.append("")
    else:
        lines.append("🔍 知识领域变化: 无领域细分数据")
        lines.append("")

    # ── 通过概率 ──
    if mocks:
        rates = [_pct(e.get("correct_rate", 0)) for e in mocks]
        recent3_avg = sum(rates[-3:]) / len(rates[-3:])
        all_avg = sum(rates) / len(rates)
        prob = recent3_avg * 0.7 + all_avg * 0.3

        if prob >= 80:
            verdict = "🟢 高概率稳妥通过（远超 70% 目标）"
        elif prob >= 70:
            verdict = "🟢 稳妥通过（已达 70% 目标）"
        elif prob >= 65:
            verdict = "🟡 临界区间（接近 70% 目标）"
        elif prob >= 59:
            verdict = "🟠 刚过线但偏低"
        else:
            verdict = "🔴 需要大幅提升"

        lines.append(f"🎯 通过概率: {prob:.0f}%（{verdict}）")
    else:
        lines.append("🎯 通过概率: 暂无模考数据")

    lines.append("")

    # ── 建议 ──
    suggestions: list[str] = []
    if mocks:
        rates = [_pct(e.get("correct_rate", 0)) for e in mocks]
        recent3_avg = sum(rates[-3:]) / len(rates[-3:])
        if recent3_avg >= 70:
            suggestions.append("保持当前节奏，巩固优势领域，冲刺高分段")
        elif recent3_avg >= 59:
            suggestions.append("集中突破 2-3 个薄弱领域，模考正确率向 70% 靠拢")
        else:
            suggestions.append("回归教材核心章节 + 加大每日一练量，先补基础")
        if _trend_arrow(rates[-3:]) == "↓" and len(rates) >= 2:
            suggestions.append("正确率连续下降，建议复盘近期错题共性原因")
        suggestions.append("薄弱领域可通过「薄弱点」专项练习 + 「复习错题」巩固")
    else:
        suggestions.append("先完成 1-2 次完整模考，再来看趋势")

    lines.append("💡 建议:")
    for i, s in enumerate(suggestions, 1):
        lines.append(f"  {i}. {s}")

    return "\n".join(lines)


def main() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    print(generate_report())


if __name__ == "__main__":
    main()
