#!/usr/bin/env python3
"""
做题汇总 — 纯 JSON 驱动，月度分组 + 趋势分析。

触发词: 做题汇总 / 做题数据 / 整体情况 / 汇总 / 刷题总结 /
        所有做题记录 / 近两个月 / 做题总览 / 今日状态 / 今天进度
"""

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import (
        QUESTION_BANK_PATH,
        ERROR_LOG_PATH,
        REVIEW_STATE_PATH,
        EXAM_RECORDS_PATH,
        CONFIG_JSON_PATH,
    )
except ModuleNotFoundError:
    from config import (
        QUESTION_BANK_PATH,
        ERROR_LOG_PATH,
        REVIEW_STATE_PATH,
        EXAM_RECORDS_PATH,
        CONFIG_JSON_PATH,
    )

DAILY_PRACTICE_SOURCE = "daily_practice"
MOCK_EXAM_SOURCE = "mock_exam"
TARGET_RATE = 70.0
PASS_RATE = 59.0
MOCK_LINE = 65.0  # 117/180
PASS_LINE = 59.0  # 106/180


def _is_mock_bank_dup(record: dict) -> bool:
    """题库里 source=mock_exam 的记录是模考错题重复记账，成绩已在 exam_records。"""
    return (record.get("source") or "") == MOCK_EXAM_SOURCE


def _is_chapter_practice(exam: dict) -> bool:
    eid = str(exam.get("exam_id", ""))
    return "章节" in eid or "练习" in eid


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return [] if path.suffix == ".json" else {}


# ── 中文月份 ──────────────────────────────────────────────────────

_MONTH_CN = {
    1: "1月", 2: "2月", 3: "3月", 4: "4月", 5: "5月", 6: "6月",
    7: "7月", 8: "8月", 9: "9月", 10: "10月", 11: "11月", 12: "12月",
}

def _format_date_range(month_key: str, records: list[dict]) -> str:
    """格式化为 '7/16-7/31'。"""
    days = sorted({r.get("date", "")[:10] for r in records if r.get("date")})
    if not days:
        return month_key
    start = days[0][5:].replace("-", "/")
    end = days[-1][5:].replace("-", "/")
    m = str(int(month_key[-2:]))
    return f"{m}/{start}-{m}/{end}"


def _format_monthly_rate(correct: int, total: int) -> str:
    if total == 0:
        return "无数据"
    return f"{correct / max(1, total) * 100:.1f}%"


def _exam_correct_rate_pct(e: dict) -> str:
    cr = e.get("correct_rate", 0)
    if isinstance(cr, float):
        return f"{cr * 100:.0f}%"
    return f"{cr}%"


def _exam_display_name(exam_id: str) -> str:
    return exam_id.removeprefix("人工录入_")


def _rate_flag(rate: float) -> str:
    if rate >= TARGET_RATE:
        return "✅"
    if rate >= PASS_RATE:
        return "🟡"
    return "🔴"


def _format_day_cn(iso_date: str) -> str:
    """YYYY-MM-DD → 8月31日"""
    try:
        y, m, d = iso_date[:10].split("-")
        return f"{int(m)}月{int(d)}日"
    except ValueError:
        return iso_date


def _build_daily_practice_section(bank: list[dict], config: dict) -> list[str]:
    """每日一练按日正确率明细。"""
    daily_records = [
        r for r in bank
        if r.get("source") == DAILY_PRACTICE_SOURCE and r.get("is_correct") is not None
    ]
    completed_days: list[str] = config.get("daily_completed", [])
    if not isinstance(completed_days, list):
        completed_days = []

    if not daily_records and not completed_days:
        return []

    by_date: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in daily_records:
        d = r.get("date", "")[:10]
        if not d:
            continue
        by_date[d]["total"] += 1
        if r.get("is_correct"):
            by_date[d]["correct"] += 1

    all_dates = sorted(set(by_date.keys()) | set(completed_days))
    if not all_dates:
        return []

    lines = [
        "📝 每日一练明细",
        "─" * 30,
    ]

    # 按月分组输出
    by_month: dict[str, list[str]] = defaultdict(list)
    for d in all_dates:
        by_month[d[:7]].append(d)

    month_subtotals: list[tuple[str, int, int]] = []

    for month_key in sorted(by_month.keys()):
        ym = int(month_key[5:])
        month_correct = 0
        month_total = 0
        day_lines: list[str] = []

        for d in by_month[month_key]:
            label = _format_day_cn(d)
            if d in by_date:
                t = by_date[d]["total"]
                c = by_date[d]["correct"]
                rate = c / max(1, t) * 100
                month_correct += c
                month_total += t
                extra = ""
                if t > 10:
                    extra = " ·重刷"
                elif d in completed_days and t < 10:
                    extra = " ·未做完"
                day_lines.append(
                    f"  {label}: {c}/{t} ({rate:.0f}%) {_rate_flag(rate)}{extra}"
                )

        no_record_days = [d for d in by_month[month_key] if d in completed_days and d not in by_date]

        if day_lines or no_record_days:
            lines.append(f"📅 {_MONTH_CN[ym]}")
            lines.extend(day_lines)
            if no_record_days:
                labels = "、".join(_format_day_cn(d) for d in no_record_days)
                if len(no_record_days) > 5:
                    labels = "、".join(_format_day_cn(d) for d in no_record_days[:5])
                    labels += f" 等{len(no_record_days)}天"
                lines.append(f"  📌 已标记完成（无逐题记录）: {labels}")
            if month_total > 0:
                m_rate = month_correct / month_total * 100
                lines.append(
                    f"  小计: {month_correct}/{month_total} ({m_rate:.1f}%) {_rate_flag(m_rate)}"
                )
                month_subtotals.append((month_key, month_correct, month_total))
            lines.append("")

    # 汇总行
    total_c = sum(c for _, c, _t in month_subtotals)
    total_t = sum(_t for _, _, _t in month_subtotals)
    if total_t > 0:
        overall = total_c / total_t * 100
        hit_target = sum(
            1 for d in by_date
            if by_date[d]["total"] > 0
            and by_date[d]["correct"] / by_date[d]["total"] * 100 >= TARGET_RATE
        )
        days_with_data = len(by_date)

        # 近 7 个有做题记录的日期
        recent_dates = sorted(by_date.keys())[-7:]
        if recent_dates:
            rc = sum(by_date[d]["correct"] for d in recent_dates)
            rt = sum(by_date[d]["total"] for d in recent_dates)
            recent_avg = rc / max(1, rt) * 100
        else:
            recent_avg = 0.0

        no_record = sum(1 for d in completed_days if d not in by_date)
        lines.append("📊 每日一练汇总")
        lines.append(f"  累计: {total_c}/{total_t} ({overall:.1f}%) {_rate_flag(overall)}")
        lines.append(
            f"  完成标记: {len(completed_days)} 天 | "
            f"有记录 {days_with_data} 天 | 达标(≥70%) {hit_target} 天"
        )
        if no_record > 0:
            lines.append(f"  ⚠️ {no_record} 天已标记完成但无逐题记录")
        if recent_dates:
            lines.append(f"  近{len(recent_dates)}次: {recent_avg:.1f}% {_rate_flag(recent_avg)}")
        gap = int(total_t * TARGET_RATE / 100) - total_c
        if gap > 0:
            lines.append(f"  距 70% 目标: 还差 {gap} 题")
        lines.append("")

    return lines


def generate_summary() -> str:
    bank = _load(QUESTION_BANK_PATH)
    if not isinstance(bank, list):
        bank = []
    errors = _load(ERROR_LOG_PATH)
    if not isinstance(errors, list):
        errors = []
    exams_data = _load(EXAM_RECORDS_PATH)
    exams = exams_data.get("exams", []) if isinstance(exams_data, dict) else []
    review = _load(REVIEW_STATE_PATH)
    if not isinstance(review, dict):
        review = {}
    config = _load(CONFIG_JSON_PATH)
    if not isinstance(config, dict):
        config = {}

    today = date.today()
    if not bank:
        return "📊 暂无做题记录。发送「每日一练」开始刷题！"

    # 题库正确率不含 mock_exam：那些是模考错题重复记账，正式成绩看 exam_records
    bank_for_rate = [r for r in bank if not _is_mock_bank_dup(r)]
    dup_mock_n = len(bank) - len(bank_for_rate)

    # ── 月度分组 ──
    monthly: dict[str, list[dict]] = defaultdict(list)
    monthly_dups: dict[str, int] = defaultdict(int)
    for r in bank:
        d = r.get("date", "")
        if not d:
            continue
        key = d[:7]
        if _is_mock_bank_dup(r):
            monthly_dups[key] += 1
        else:
            monthly[key].append(r)

    sorted_months = sorted(set(monthly.keys()) | set(monthly_dups.keys()))

    # ── 首次/二次正确率（不含模考重复记账）──
    first_seen_questions: set[str] = set()
    month_first_correct: dict[str, int] = defaultdict(int)
    month_first_total: dict[str, int] = defaultdict(int)
    month_second_correct: dict[str, int] = defaultdict(int)
    month_second_total: dict[str, int] = defaultdict(int)

    for m in sorted_months:
        for r in monthly.get(m, []):
            if r.get("is_correct") is None:
                continue
            q_sig = r.get("question", "")[:50]
            if q_sig not in first_seen_questions:
                first_seen_questions.add(q_sig)
                month_first_total[m] += 1
                if r.get("is_correct"):
                    month_first_correct[m] += 1
            else:
                month_second_total[m] += 1
                if r.get("is_correct"):
                    month_second_correct[m] += 1

    # ── 模考分组（排除章节练习等非标准模考）──
    month_exams: dict[str, list[dict]] = defaultdict(list)
    month_chapters: dict[str, list[dict]] = defaultdict(list)
    for e in exams:
        ed = e.get("exam_date", "")[:7]
        if not ed:
            continue
        if _is_chapter_practice(e):
            month_chapters[ed].append(e)
        else:
            month_exams[ed].append(e)

    # ── 格式输出 ──
    start_month = sorted_months[0] if sorted_months else today.strftime("%Y-%m")
    end_month = sorted_months[-1] if sorted_months else start_month
    y1, m1 = int(start_month[:4]), int(start_month[5:])
    y2, m2 = int(end_month[:4]), int(end_month[5:])
    lines = [
        f"📊 {y1}年{m1}-{m2}月 做题汇总",
        "══════════════════════════════",
        "",
    ]
    if dup_mock_n > 0:
        lines.append(f"口径：题库正确率已剔除 {dup_mock_n} 条模考错题重复记账，模考看下方正式卷。")
        lines.append("")

    # ── 逐月详情 ──
    month_details: list[dict] = []

    for m in sorted_months:
        records = monthly.get(m, [])
        dup_n = monthly_dups.get(m, 0)
        t = len(records)
        judged = [r for r in records if r.get("is_correct") is not None]
        c = sum(1 for r in judged if r.get("is_correct"))
        rate = c / max(1, len(judged)) * 100
        pending = t - len(judged)

        f_t = month_first_total.get(m, 0)
        f_c = month_first_correct.get(m, 0)
        s_t = month_second_total.get(m, 0)
        s_c = month_second_correct.get(m, 0)

        ym = int(m[:4]), int(m[5:])
        date_range = _format_date_range(m, records)
        n_exams = len(month_exams.get(m, []))

        lines.append(f"📅 {_MONTH_CN[ym[1]]}（{date_range}）")
        pending_note = f"（待判卷 {pending} 题）" if pending > 0 else ""
        dup_note = f"（已剔除 {dup_n} 条模考重复记账）" if dup_n else ""
        lines.append(
            f"刷题：{t} 题 | 正确率 {_format_monthly_rate(c, len(judged))}"
            f"{pending_note}{dup_note}"
        )
        lines.append(
            f"  首次正确率 {_format_monthly_rate(f_c, f_t)}"
            f"  |  二次正确率 {_format_monthly_rate(s_c, s_t)}"
        )

        if n_exams > 0:
            month_list = month_exams.get(m, [])
            rates = " / ".join(_exam_correct_rate_pct(e) for e in month_list)
            lines.append(f"模考：{n_exams} 次（{rates}）")
            for e in month_list:
                name = _exam_display_name(e.get("exam_id", "模考"))
                ed = e.get("exam_date", "")[5:10].replace("-", "/")
                cc = e.get("correct_count")
                tq = e.get("total_questions")
                score = f"{cc}/{tq}" if cc is not None and tq else ""
                detail = f"  · {name}"
                if ed:
                    detail += f" {ed}"
                detail += f" {_exam_correct_rate_pct(e)}"
                if score:
                    detail += f"（{score}）"
                lines.append(detail)
        else:
            lines.append("模考：0 次")

        for e in month_chapters.get(m, []):
            name = _exam_display_name(e.get("exam_id", "章节练习"))
            ed = e.get("exam_date", "")[5:10].replace("-", "/")
            cc = e.get("correct_count")
            tq = e.get("total_questions")
            score = f"{cc}/{tq}" if cc is not None and tq else ""
            detail = f"  · {name}"
            if ed:
                detail += f" {ed}"
            detail += f" {_exam_correct_rate_pct(e)}"
            if score:
                detail += f"（{score}）"
            lines.append(detail)
        lines.append("")

        month_details.append({
            "month": m, "total": t, "correct": c, "rate": rate,
            "exams": n_exams,
        })

    # ── 月度对比 ──
    if len(month_details) >= 2:
        lines.append("📈 月度对比")
        lines.append("─" * 30)

        for i in range(1, len(month_details)):
            prev = month_details[i - 1]
            curr = month_details[i]
            dt = curr["total"] - prev["total"]
            dr = curr["rate"] - prev["rate"]
            de = curr["exams"] - prev["exams"]

            t_arrow = f"+{dt}" if dt >= 0 else str(dt)
            r_arrow = "↑" if dr > 0 else ("↓" if dr < 0 else "→")
            lines.append(f"刷题量：{prev['total']} → {curr['total']}（{t_arrow} 题）")
            lines.append(f"正确率：{prev['rate']:.1f}% → {curr['rate']:.1f}%（{r_arrow}{abs(dr):.1f}%）")

            if de != 0:
                lines.append(f"模考：{prev['exams']} → {curr['exams']}（{'+' if de > 0 else ''}{de} 次）")
            lines.append("")

    # ── 每日一练明细 ──
    daily_lines = _build_daily_practice_section(bank, config)
    if daily_lines:
        lines.extend(daily_lines)

    # ── 总览 ──
    judged_all = [r for r in bank_for_rate if r.get("is_correct") is not None]
    correct = sum(1 for r in judged_all if r.get("is_correct"))
    overall_pct = correct / max(1, len(judged_all)) * 100
    total = len(bank_for_rate)

    # 薄弱领域
    area_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in bank_for_rate:
        if r.get("is_correct") is None:
            continue
        area = r.get("knowledge_area", "未分类")
        if area == "综合":
            continue
        area_stats[area]["total"] += 1
        if r.get("is_correct"):
            area_stats[area]["correct"] += 1

    weakest = [(a, s["correct"] / max(1, s["total"]) * 100, s["total"])
               for a, s in area_stats.items()]
    weakest.sort(key=lambda x: x[1])
    top_weak = [w for w in weakest if w[1] < 60 and w[2] >= 3][:3]

    # SM-2 review
    today_str = today.isoformat()
    total_review = len(review)
    due_today = sum(1 for v in review.values() if v.get("next_date", "9999") <= today_str)
    mastered = sum(1 for v in review.values() if v.get("interval", 0) >= 21)

    # 最近一次正式模考
    formal_all = [e for m in sorted_months for e in month_exams.get(m, [])]
    formal_all.sort(key=lambda e: e.get("exam_date", ""))
    latest_mock = formal_all[-1] if formal_all else None

    # 目标评估：题库累计仍对照 70%；过线看最近模考
    gap = 70 - overall_pct
    if latest_mock:
        mock_pct = float(latest_mock.get("correct_rate") or 0)
        mock_pct = mock_pct * 100 if mock_pct <= 1 else mock_pct
        cc = latest_mock.get("correct_count")
        tq = latest_mock.get("total_questions")
        mock_bit = f"最近模考 {mock_pct:.0f}%"
        if cc is not None and tq:
            mock_bit += f"（{cc}/{tq}）"
        if mock_pct >= TARGET_RATE:
            target_line = f"🟢 最近模考已达 70% 训练目标 · {mock_bit}"
        elif mock_pct >= MOCK_LINE:
            miss = (126 - int(cc)) if cc is not None else None
            extra = f"，距 70% 差 {miss} 题" if miss is not None and miss > 0 else ""
            target_line = f"🟡 已过模考线 65% · {mock_bit}{extra}"
        elif mock_pct >= PASS_LINE:
            target_line = f"🟠 已过通过线 59%，未到模考线 65% · {mock_bit}"
        else:
            target_line = f"🔴 最近模考未过 59% 通过线 · {mock_bit}"
    elif gap <= 0:
        target_line = "🟢 题库已达 70% 目标"
    elif gap <= 5:
        target_line = f"🟡 距 70% 目标差 {int(gap * total / 100)} 题"
    elif gap <= 15:
        target_line = f"🟠 需提升 {gap:.0f} 个百分点"
    else:
        target_line = f"🔴 差距较大（{overall_pct:.0f}% vs 70%）"

    lines.extend([
        "📌 当前总览",
        "─" * 30,
        f"总刷题：{total} 题 | 总正确率：{overall_pct:.1f}%",
    ])
    if dup_mock_n > 0:
        lines.append(f"（原始题库 {len(bank)} 条含模考重复记账，已剔除 {dup_mock_n} 条）")
    if total_review > 0:
        lines.append(f"错题复习：{total_review} 排队 | {due_today} 今日到期 | {mastered} 已掌握")
    lines.append(f"🎯 目标：{target_line}")

    if top_weak:
        lines.append("")
        lines.append("薄弱领域：")
        for area, rate, cnt in top_weak:
            lines.append(f"  · {area}（{rate:.0f}%）")

    lines.extend([
        "",
        "💡 发送「复习错题」开始复习 | 「每日一练」刷题 | 「分析趋势」趋势分析",
    ])

    return "\n".join(lines)


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    print(generate_summary())


if __name__ == "__main__":
    main()
