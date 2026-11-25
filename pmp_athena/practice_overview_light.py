#!/usr/bin/env python3
"""
做题汇总 — 纯 JSON 驱动。

默认（微信）：一屏总览 + 模考分数列表，不堆章节/每日一练明细。
详细：--detail

触发词: 做题汇总 / 做题数据 / 整体情况 / 汇总 / 刷题总结 /
        所有做题记录 / 近两个月 / 做题总览 / 今日状态 / 今天进度
"""

import json
from collections import defaultdict
from datetime import date
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


def _format_score(correct: int, total: int, *, with_flag: bool = False) -> str:
    if total <= 0:
        return "无数据"
    rate = correct / total * 100
    text = f"{correct}/{total} ({rate:.1f}%)"
    if with_flag:
        text += f" {_rate_flag(rate)}"
    return text


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


def _mock_line(e: dict) -> str:
    name = _exam_display_name(e.get("exam_id", "模考"))
    ed = e.get("exam_date", "")[5:10].replace("-", "/")
    cc = e.get("correct_count")
    tq = e.get("total_questions")
    rate = _exam_correct_rate_pct(e)
    score = f"（{cc}/{tq}）" if cc is not None and tq else ""
    head = f"  · {ed} {name}" if ed else f"  · {name}"
    return f"{head} {rate}{score}"


def _target_line(latest_mock: dict | None, overall_pct: float, total: int) -> str:
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
            return f"🟢 最近模考已达 70% 训练目标 · {mock_bit}"
        if mock_pct >= MOCK_LINE:
            miss = (126 - int(cc)) if cc is not None else None
            extra = f"，距 70% 差 {miss} 题" if miss is not None and miss > 0 else ""
            return f"🟡 已过模考线 65% · {mock_bit}{extra}"
        if mock_pct >= PASS_LINE:
            return f"🟠 已过通过线 59%，未到模考线 65% · {mock_bit}"
        return f"🔴 最近模考未过 59% 通过线 · {mock_bit}"
    if gap <= 0:
        return "🟢 题库已达 70% 目标"
    if gap <= 5:
        return f"🟡 距 70% 目标差 {int(gap * total / 100)} 题"
    if gap <= 15:
        return f"🟠 需提升 {gap:.0f} 个百分点"
    return f"🔴 差距较大（{overall_pct:.0f}% vs 70%）"


def _collect(from_date: str | None) -> dict[str, Any] | str:
    """加载并汇总数据；无记录时返回提示字符串。"""
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

    if from_date is None:
        cfg_from = config.get("overview_from_date")
        if isinstance(cfg_from, str) and cfg_from.strip():
            from_date = cfg_from.strip()[:10]

    today = date.today()
    if not bank and not from_date:
        return "📊 暂无做题记录。发送「每日一练」开始刷题！"

    if from_date:
        bank = [r for r in bank if (r.get("date") or "")[:10] >= from_date]
        exams = [e for e in exams if (e.get("exam_date") or "")[:10] >= from_date]
        if not bank and not exams:
            return (
                f"📊 暂无 {from_date} 起的做题记录。\n"
                "发送截图入库 /「每日一练」开始本轮刷题！"
            )

    bank_for_rate = [r for r in bank if not _is_mock_bank_dup(r)]
    dup_mock_n = len(bank) - len(bank_for_rate)

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

    sorted_months = sorted(
        set(monthly.keys())
        | set(monthly_dups.keys())
        | set(month_chapters.keys())
        | set(month_exams.keys())
    )

    chapter_total_all = 0
    chapter_correct_all = 0
    mock_total_all = 0
    mock_correct_all = 0
    month_details: list[dict] = []
    formal_all: list[dict] = []

    for m in sorted_months:
        records = monthly.get(m, [])
        judged = [r for r in records if r.get("is_correct") is not None]
        bank_c = sum(1 for r in judged if r.get("is_correct"))
        bank_t = len(records)

        chapters = month_chapters.get(m, [])
        chap_t = sum(int(e.get("total_questions") or 0) for e in chapters)
        chap_c = sum(int(e.get("correct_count") or 0) for e in chapters)
        chapter_total_all += chap_t
        chapter_correct_all += chap_c

        mocks = month_exams.get(m, [])
        formal_all.extend(mocks)
        mock_t = sum(int(e.get("total_questions") or 0) for e in mocks)
        mock_c = sum(int(e.get("correct_count") or 0) for e in mocks)
        mock_total_all += mock_t
        mock_correct_all += mock_c

        t = bank_t + chap_t + mock_t
        c = bank_c + chap_c + mock_c
        judged_n = len(judged) + chap_t + mock_t
        rate = c / max(1, judged_n) * 100
        month_details.append({
            "month": m,
            "total": t,
            "correct": c,
            "rate": rate,
            "exams": len(mocks),
            "records": records,
            "judged": judged,
            "bank_c": bank_c,
            "chapters": chapters,
            "chap_t": chap_t,
            "chap_c": chap_c,
            "mocks": mocks,
            "mock_t": mock_t,
            "mock_c": mock_c,
            "dup_n": monthly_dups.get(m, 0),
        })

    formal_all.sort(key=lambda e: e.get("exam_date", ""))
    judged_all = [r for r in bank_for_rate if r.get("is_correct") is not None]
    bank_correct = sum(1 for r in judged_all if r.get("is_correct"))
    bank_total = len(bank_for_rate)
    correct = bank_correct + chapter_correct_all + mock_correct_all
    total = bank_total + chapter_total_all + mock_total_all
    overall_pct = (
        correct
        / max(1, (len(judged_all) + chapter_total_all + mock_total_all))
        * 100
    )

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

    weakest = [
        (a, s["correct"] / max(1, s["total"]) * 100, s["total"])
        for a, s in area_stats.items()
    ]
    weakest.sort(key=lambda x: x[1])
    top_weak = [w for w in weakest if w[1] < 60 and w[2] >= 3][:3]

    today_str = today.isoformat()
    total_review = len(review)
    due_today = sum(
        1 for v in review.values() if v.get("next_date", "9999") <= today_str
    )
    mastered = sum(1 for v in review.values() if v.get("interval", 0) >= 21)
    latest_mock = formal_all[-1] if formal_all else None

    # 每日一练汇总（精简：只算总数，不逐日）
    daily_records = [
        r for r in bank_for_rate
        if r.get("source") == DAILY_PRACTICE_SOURCE and r.get("is_correct") is not None
    ]
    daily_c = sum(1 for r in daily_records if r.get("is_correct"))
    daily_t = len(daily_records)

    return {
        "from_date": from_date,
        "today": today,
        "bank": bank,
        "bank_for_rate": bank_for_rate,
        "dup_mock_n": dup_mock_n,
        "sorted_months": sorted_months,
        "month_details": month_details,
        "formal_all": formal_all,
        "latest_mock": latest_mock,
        "judged_all": judged_all,
        "bank_correct": bank_correct,
        "bank_total": bank_total,
        "chapter_correct_all": chapter_correct_all,
        "chapter_total_all": chapter_total_all,
        "mock_correct_all": mock_correct_all,
        "mock_total_all": mock_total_all,
        "correct": correct,
        "total": total,
        "overall_pct": overall_pct,
        "top_weak": top_weak,
        "total_review": total_review,
        "due_today": due_today,
        "mastered": mastered,
        "daily_c": daily_c,
        "daily_t": daily_t,
        "config": config,
        "errors": errors,
    }


def _build_compact(data: dict[str, Any]) -> str:
    """微信一屏：量/趋势置顶 → 分类 → 模考分 → 目标。"""
    from_date = data["from_date"]
    title = "📊 做题汇总"
    if from_date:
        title = f"📊 做题汇总（{from_date}起）"

    lines = [title]

    # 0) 累计题量 + 总正确率（微信精简版也要有，不能只拆分月/分类）
    if data["total"] > 0:
        judged_n = (
            len(data["judged_all"])
            + data["chapter_total_all"]
            + data["mock_total_all"]
        )
        rate_n = judged_n if judged_n > 0 else data["total"]
        lines.append(
            f"📌 总刷题量 {data['total']} 题 · 总正确率 "
            f"{_format_score(data['correct'], rate_n, with_flag=True)}"
        )

    # 1) 刷题量 + 月度对比（置顶）
    details = data["month_details"]
    if details:
        vol_bits = []
        for md in details:
            m = int(md["month"][5:])
            vol_bits.append(f"{_MONTH_CN[m]} {md['total']}题")
        lines.append(f"📦 刷题量：{' · '.join(vol_bits)}")

    if len(details) >= 2:
        prev, curr = details[-2], details[-1]
        dr = curr["rate"] - prev["rate"]
        dt = curr["total"] - prev["total"]
        r_arrow = "↑" if dr > 0 else ("↓" if dr < 0 else "→")
        t_arrow = f"+{dt}" if dt >= 0 else str(dt)
        pm = int(prev["month"][5:])
        cm = int(curr["month"][5:])
        lines.append(
            f"📈 {_MONTH_CN[pm]}→{_MONTH_CN[cm]}："
            f"{prev['total']}→{curr['total']}题（{t_arrow}）"
            f" · {prev['rate']:.0f}% → {curr['rate']:.0f}%（{r_arrow}{abs(dr):.0f}%）"
            f" · 模考 {prev['exams']}→{curr['exams']}"
        )

    # 2) 分类正确率
    lines.append(
        f"📝 日常 {_format_score(data['bank_correct'], len(data['judged_all']) or data['bank_total'], with_flag=True)}"
    )
    if data["daily_t"] > 0:
        lines.append(
            f"   └ 每日一练 {_format_score(data['daily_c'], data['daily_t'], with_flag=True)}"
        )
    lines.append(
        f"📚 章节/App {_format_score(data['chapter_correct_all'], data['chapter_total_all'], with_flag=True)}"
    )
    n_mocks = len(data["formal_all"])
    mock_score = _format_score(
        data["mock_correct_all"], data["mock_total_all"], with_flag=True
    )
    lines.append(f"📋 模考整卷 {mock_score} · {n_mocks} 次")
    lines.append("")

    # 3) 模考成绩列表
    if data["formal_all"]:
        lines.append("📋 模考成绩")
        for e in data["formal_all"]:
            lines.append(_mock_line(e))
        lines.append("")
    else:
        lines.append("📋 模考成绩：暂无整卷记录")
        lines.append("")

    # 4) 目标 / 错题 / 薄弱
    lines.append(
        f"🎯 {_target_line(data['latest_mock'], data['overall_pct'], data['total'])}"
    )

    if data["total_review"] > 0:
        lines.append(
            f"❌ 错题 {data['total_review']} 排队 | "
            f"{data['due_today']} 今日到期 | {data['mastered']} 已掌握"
        )

    if data["top_weak"]:
        weak = " · ".join(f"{a}（{r:.0f}%）" for a, r, _ in data["top_weak"])
        lines.append(f"薄弱：{weak}")

    lines.extend([
        "",
        "💡 「复习错题」|「今日任务」|「分析趋势」",
    ])
    return "\n".join(lines)


def _build_daily_practice_section(
    bank: list[dict],
    config: dict,
    from_date: str | None = None,
) -> list[str]:
    """每日一练按日正确率明细（仅 --detail）。"""
    daily_records = [
        r for r in bank
        if r.get("source") == DAILY_PRACTICE_SOURCE and r.get("is_correct") is not None
    ]
    completed_days: list[str] = config.get("daily_completed", [])
    if not isinstance(completed_days, list):
        completed_days = []
    if from_date:
        daily_records = [r for r in daily_records if (r.get("date") or "")[:10] >= from_date]
        completed_days = [d for d in completed_days if str(d)[:10] >= from_date]

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

        no_record_days = [
            d for d in by_month[month_key] if d in completed_days and d not in by_date
        ]

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
        lines.append("")

    return lines


def _build_detail(data: dict[str, Any]) -> str:
    """完整月度明细（终端 / --detail）。"""
    from_date = data["from_date"]
    sorted_months = data["sorted_months"]
    start_month = sorted_months[0] if sorted_months else data["today"].strftime("%Y-%m")
    end_month = sorted_months[-1] if sorted_months else start_month
    y1, m1 = int(start_month[:4]), int(start_month[5:])
    y2, m2 = int(end_month[:4]), int(end_month[5:])
    title = f"📊 {y1}年{m1}-{m2}月 做题汇总"
    if from_date:
        title = f"📊 {from_date} 起做题汇总（至考前）"

    lines = [title, "══════════════════════════════", ""]
    if from_date:
        lines.append(f"口径：仅统计 {from_date} 及之后（7–9 月旧数据不计入本轮）。")
        lines.append("")
    if data["dup_mock_n"] > 0:
        lines.append(
            f"口径：总刷题 = 日常逐题 + 章节/App + 模考整卷；"
            f"题库里 {data['dup_mock_n']} 条模考错题重复记账已剔除，不与整卷叠算。"
        )
        lines.append("")
    else:
        lines.append("口径：总刷题 = 日常逐题 + 章节/App + 模考整卷。")
        lines.append("")

    # 首次/二次（detail 用）
    first_seen: set[str] = set()
    month_first_correct: dict[str, int] = defaultdict(int)
    month_first_total: dict[str, int] = defaultdict(int)
    month_second_correct: dict[str, int] = defaultdict(int)
    month_second_total: dict[str, int] = defaultdict(int)
    for md in data["month_details"]:
        m = md["month"]
        for r in md["records"]:
            if r.get("is_correct") is None:
                continue
            q_sig = r.get("question", "")[:50]
            if q_sig not in first_seen:
                first_seen.add(q_sig)
                month_first_total[m] += 1
                if r.get("is_correct"):
                    month_first_correct[m] += 1
            else:
                month_second_total[m] += 1
                if r.get("is_correct"):
                    month_second_correct[m] += 1

    for md in data["month_details"]:
        m = md["month"]
        ym = int(m[:4]), int(m[5:])
        records = md["records"]
        date_range = _format_date_range(m, records)
        if (not records) and (md["chapters"] or md["mocks"]):
            extra_days = sorted(
                {
                    (e.get("exam_date") or "")[:10]
                    for e in (md["chapters"] + md["mocks"])
                    if e.get("exam_date")
                }
            )
            if extra_days:
                date_range = _format_date_range(m, [{"date": d} for d in extra_days])

        judged = md["judged"]
        judged_n = len(judged) + md["chap_t"] + md["mock_t"]
        pending = len(records) - len(judged)
        pending_note = f"（待判卷 {pending} 题）" if pending > 0 else ""
        dup_note = (
            f"（已剔除 {md['dup_n']} 条模考重复记账）" if md["dup_n"] else ""
        )

        lines.append(f"📅 {_MONTH_CN[ym[1]]}（{date_range}）")
        lines.append(
            f"刷题：{_format_score(md['correct'], judged_n, with_flag=True)}"
            f"{pending_note}{dup_note}"
        )
        parts = []
        if records:
            parts.append(
                f"日常 {_format_score(md['bank_c'], len(judged) if judged else len(records))}"
            )
        if md["chap_t"] > 0:
            parts.append(f"章节/App {_format_score(md['chap_c'], md['chap_t'])}")
        if md["mock_t"] > 0:
            parts.append(f"模考 {_format_score(md['mock_c'], md['mock_t'])}")
        if parts:
            lines.append(f"  其中：{' · '.join(parts)}")
        lines.append(
            f"  首次正确率 {_format_score(month_first_correct[m], month_first_total[m])}"
            f"  |  二次正确率 {_format_score(month_second_correct[m], month_second_total[m])}"
        )

        if md["mocks"]:
            rates = " / ".join(_exam_correct_rate_pct(e) for e in md["mocks"])
            lines.append(f"模考：{len(md['mocks'])} 次（{rates}）")
            for e in md["mocks"]:
                lines.append(_mock_line(e))
        else:
            lines.append("模考：0 次")

        for e in md["chapters"]:
            lines.append(_mock_line(e))
        lines.append("")

    if len(data["month_details"]) >= 2:
        lines.append("📈 月度对比")
        lines.append("─" * 30)
        for i in range(1, len(data["month_details"])):
            prev = data["month_details"][i - 1]
            curr = data["month_details"][i]
            dt = curr["total"] - prev["total"]
            dr = curr["rate"] - prev["rate"]
            de = curr["exams"] - prev["exams"]
            t_arrow = f"+{dt}" if dt >= 0 else str(dt)
            r_arrow = "↑" if dr > 0 else ("↓" if dr < 0 else "→")
            lines.append(f"刷题量：{prev['total']} → {curr['total']}（{t_arrow} 题）")
            lines.append(
                f"正确率：{prev['rate']:.1f}% → {curr['rate']:.1f}%（{r_arrow}{abs(dr):.1f}%）"
            )
            if de != 0:
                lines.append(
                    f"模考：{prev['exams']} → {curr['exams']}（{'+' if de > 0 else ''}{de} 次）"
                )
            lines.append("")

    daily_lines = _build_daily_practice_section(
        data["bank"], data["config"], from_date=from_date
    )
    if daily_lines:
        lines.extend(daily_lines)

    lines.extend([
        "📌 当前总览",
        "─" * 30,
        f"累计：{_format_score(data['correct'], data['total'], with_flag=True)}",
        f"  · 日常逐题：{_format_score(data['bank_correct'], len(data['judged_all']) or data['bank_total'])}",
        f"  · 章节/App：{_format_score(data['chapter_correct_all'], data['chapter_total_all'])}",
        f"  · 模考整卷：{_format_score(data['mock_correct_all'], data['mock_total_all'])}",
        (
            f"题量构成：日常 {data['bank_total']} + 章节/App {data['chapter_total_all']}"
            f" + 模考 {data['mock_total_all']} = {data['total']}"
        ),
    ])
    if data["dup_mock_n"] > 0:
        lines.append(
            f"（原始题库 {len(data['bank'])} 条含模考错题重复记账，已剔除 {data['dup_mock_n']} 条，"
            f"模考按整卷 {data['mock_total_all']} 计入）"
        )
    if data["total_review"] > 0:
        lines.append(
            f"错题复习：{data['total_review']} 排队 | "
            f"{data['due_today']} 今日到期 | {data['mastered']} 已掌握"
        )
    lines.append(
        f"🎯 目标：{_target_line(data['latest_mock'], data['overall_pct'], data['total'])}"
    )

    if data["top_weak"]:
        lines.append("")
        lines.append("薄弱领域：")
        for area, rate, cnt in data["top_weak"]:
            lines.append(f"  · {area}（{rate:.0f}%）")

    lines.extend([
        "",
        "💡 发送「复习错题」开始复习 | 「每日一练」刷题 | 「分析趋势」趋势分析",
    ])
    return "\n".join(lines)


def generate_summary(from_date: str | None = None, *, detail: bool = False) -> str:
    collected = _collect(from_date)
    if isinstance(collected, str):
        return collected
    if detail:
        return _build_detail(collected)
    return _build_compact(collected)


def main():
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="做题汇总 / 刷题总览")
    parser.add_argument(
        "--from",
        dest="from_date",
        default=None,
        help="起始日期 YYYY-MM-DD（覆盖 config.overview_from_date）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="忽略 overview_from_date，统计全部历史",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="输出完整月度/每日一练明细（默认微信精简版）",
    )
    args = parser.parse_args()
    if args.all:
        print(generate_summary(from_date="", detail=args.detail))
    else:
        print(generate_summary(from_date=args.from_date, detail=args.detail))


if __name__ == "__main__":
    main()
