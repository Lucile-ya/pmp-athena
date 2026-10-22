#!/usr/bin/env python3
"""
今日任务 — 微信分步闯关（清错题 → 专项 → 摘要卡）。

CLI:
  python pmp_athena/daily_quest.py message --text "今日任务"
  python pmp_athena/daily_quest.py next
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from pmp_athena.config import (
        AREA_PRACTICE_LIMIT,
        ERROR_LOG_PATH,
        QUESTION_BANK_PATH,
        RETAKE_REVIEW_QUOTA,
        TARGET_EXAM_DATE,
        TODAY_QUEST_PATH,
    )
    from pmp_athena.cheatsheet_sync import (
        _d_day,
        _ranked_area_triples,
        sprint_slot,
        today_focus_areas,
    )
    from pmp_athena.error_insights import (
        format_quest_summary_card,
        rank_high_frequency_errors,
    )
    from pmp_athena.export_hf_cards import DAILY_HF_LIMIT, pick_daily_hf_cards
    from pmp_athena.knowledge_retriever import normalize_area
    from pmp_athena.review_scheduler import (
        PRE_EXAM_30_DAYS,
        PRE_EXAM_DAYS,
        ReviewScheduler,
    )
except ModuleNotFoundError:
    from config import (  # type: ignore
        AREA_PRACTICE_LIMIT,
        ERROR_LOG_PATH,
        QUESTION_BANK_PATH,
        RETAKE_REVIEW_QUOTA,
        TARGET_EXAM_DATE,
        TODAY_QUEST_PATH,
    )
    from cheatsheet_sync import (  # type: ignore
        _d_day,
        _ranked_area_triples,
        sprint_slot,
        today_focus_areas,
    )
    from error_insights import (  # type: ignore
        format_quest_summary_card,
        rank_high_frequency_errors,
    )
    from export_hf_cards import DAILY_HF_LIMIT, pick_daily_hf_cards  # type: ignore
    from knowledge_retriever import normalize_area  # type: ignore
    from review_scheduler import PRE_EXAM_30_DAYS, PRE_EXAM_DAYS, ReviewScheduler  # type: ignore

START_TRIGGERS = frozenset({"今日任务", "今天任务", "今日闯关"})
NEXT_TRIGGERS = frozenset({"开始任务", "下一步", "继续任务", "下一步任务"})

STEP1_MINUTES = 30
STEP2_MINUTES = 40
STEP3_MINUTES = 10


def _exam_date() -> date:
    try:
        from pmp_athena.config import get_target_exam_date
        return get_target_exam_date()
    except Exception:
        try:
            return date.fromisoformat(str(TARGET_EXAM_DATE)[:10])
        except Exception:
            return date(2026, 12, 5)


def _phase_line(today: date, days: int) -> str:
    _ = today
    if days <= 11:
        return f"🔥 冲刺模考期 · 距考试 {max(days, 0)} 天"
    if days <= 30:
        return f"⚡ 强化刷题期 · 距考试 {max(days, 0)} 天"
    return f"📖 基础巩固期 · 距考试 {max(days, 0)} 天"


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _save_state(state: dict) -> None:
    TODAY_QUEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    TODAY_QUEST_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sprint_area(area: str) -> str:
    return "敏捷" if (area or "").startswith("敏捷") else area


def _live_slot() -> dict:
    try:
        from pmp_athena.retake_calendar import day_plan
    except ModuleNotFoundError:
        from retake_calendar import day_plan  # type: ignore
    p = day_plan(date.today())
    if p:
        slot = p.as_slot()
        if slot.get("kind") == "area" and not slot.get("area"):
            fb = sprint_slot(_ranked_area_triples(), _d_day())
            if fb.get("area"):
                slot["area"] = fb.get("area")
                slot["focus"] = slot.get("focus") or fb.get("focus") or [fb["area"]]
        return slot
    return sprint_slot(_ranked_area_triples(), _d_day())


def _tomorrow_slot() -> dict:
    try:
        from pmp_athena.retake_calendar import next_plan
    except ModuleNotFoundError:
        from retake_calendar import next_plan  # type: ignore
    nxt = next_plan(date.today())
    if nxt:
        return nxt.as_slot()
    d = _d_day()
    if d > 1:
        return sprint_slot(_ranked_area_triples(), d - 1)
    return {"kind": "exam", "area": None}


def _area_why(area: str | None, locked: dict | None = None) -> str:
    if locked and locked.get("why"):
        return str(locked["why"])
    if not area:
        return "考前一天：清错题 + 摘要卡，不再新开专项"
    try:
        from pmp_athena.weak_area_cheatsheet import get_weak_areas
    except ModuleNotFoundError:
        from weak_area_cheatsheet import get_weak_areas  # type: ignore
    want = normalize_area(area) or area
    short = _sprint_area(area)
    for name, rate, _wrong, _total in get_weak_areas():
        got = normalize_area(name) or name
        if got != want:
            continue
        pct = int(round(rate * 100))
        if rate >= 0.60:
            return f"{short} 错误率 {pct}%，P0 红线，今天必须压下去"
        if rate >= 0.50:
            return f"{short} 错误率 {pct}%，先拉到 50% 以下"
        return f"{short} 错误率 {pct}%，巩固不丢分"
    return f"按考前日历攻坚 {short}"


def _tomorrow_line(kind: str, area: str | None, focus: list | None = None) -> str:
    if kind == "exam":
        return "明天：考试日，只过口诀"
    if kind == "mock":
        return "明天：全真模考，当正式考试"
    if kind == "finale" or not area:
        return "明天：摘要卡 + 错题清零 / 随机模考"
    if focus and len(focus) >= 2:
        return "明天：专项 " + "+".join(_sprint_area(a) for a in focus[:2])
    return f"明天：专项 {_sprint_area(area)}"


def _focus_areas(locked: dict | None = None) -> list[str]:
    if locked and locked.get("focus"):
        return list(locked["focus"])
    return today_focus_areas(_ranked_area_triples(), _d_day())


def _primary_area(locked: dict | None = None) -> str | None:
    if locked and locked.get("kind") in ("finale", "exam", "mock"):
        return None
    if locked and locked.get("area"):
        return locked["area"]
    slot = _live_slot()
    return slot.get("area")


def _fresh_plan(history: list) -> dict:
    slot = _live_slot()
    tomorrow = _tomorrow_slot()
    focus = list(slot.get("focus") or [])
    if not focus and slot.get("area"):
        focus = [slot["area"]]
    return {
        "date": date.today().isoformat(),
        "exam_date": _exam_date().isoformat(),
        "kind": slot.get("kind") or "area",
        "area": slot.get("area"),
        "focus": focus,
        "question_n": int(slot.get("question_n") or AREA_PRACTICE_LIMIT),
        "review_n": int(
            slot["review_n"]
            if slot.get("review_n") is not None
            else RETAKE_REVIEW_QUOTA
        ),
        "why": slot.get("why") or "",
        "plan_key": slot.get("plan_key") or "",
        "skip_live": bool(slot.get("skip_live")),
        "live": slot.get("live") or "",
        "athena": slot.get("athena") or "",
        "tomorrow_area": tomorrow.get("area"),
        "tomorrow_kind": tomorrow.get("kind"),
        "tomorrow_focus": tomorrow.get("focus") or [],
        "cards_shown": False,
        "done": False,
        "history": history[-10:],
    }


def _state() -> dict:
    today = date.today().isoformat()
    exam_s = _exam_date().isoformat()
    data = _load_json(TODAY_QUEST_PATH, {})
    if (
        isinstance(data, dict)
        and data.get("date") == today
        and data.get("exam_date") == exam_s
    ):
        slot = _live_slot()
        pk = slot.get("plan_key") or ""
        if pk and data.get("plan_key") == pk:
            tm = _tomorrow_slot()
            data["why"] = slot.get("why") or data.get("why")
            data["skip_live"] = bool(slot.get("skip_live"))
            data["live"] = slot.get("live") or data.get("live")
            data["athena"] = slot.get("athena") or data.get("athena")
            data["tomorrow_area"] = tm.get("area")
            data["tomorrow_kind"] = tm.get("kind")
            data["tomorrow_focus"] = tm.get("focus") or []
            if slot.get("focus"):
                data["focus"] = list(slot["focus"])
            if slot.get("area"):
                data["area"] = slot.get("area")
            if slot.get("question_n") is not None:
                data["question_n"] = int(slot["question_n"])
            if slot.get("review_n") is not None:
                data["review_n"] = int(slot["review_n"])
            _save_state(data)
        if pk and data.get("plan_key") != pk:
            history = list(data.get("history") or [])
            if data.get("date"):
                history.append({
                    "date": data.get("date"),
                    "area": data.get("area"),
                    "done": bool(data.get("done")),
                })
            fresh = _fresh_plan(history)
            _save_state(fresh)
            return fresh
        if "kind" not in data:
            tomorrow = _tomorrow_slot()
            data["kind"] = slot.get("kind") or "area"
            data.setdefault("area", slot.get("area"))
            data.setdefault("focus", slot.get("focus") or [])
            data.setdefault("tomorrow_area", tomorrow.get("area"))
            data.setdefault("tomorrow_kind", tomorrow.get("kind"))
            _save_state(data)
        return data
    history: list = []
    if isinstance(data, dict):
        history = list(data.get("history") or [])
        if data.get("date"):
            history.append({
                "date": data.get("date"),
                "area": data.get("area"),
                "done": bool(data.get("done")),
            })
    fresh = _fresh_plan(history)
    _save_state(fresh)
    return fresh


def _review_progress() -> tuple[int, int]:
    """(已完成, 今日应推总数含已完成). 补考周历日按定额封顶。"""
    sch = ReviewScheduler()
    days = (_exam_date() - date.today()).days
    plan = sch.build_daily_plan(
        is_pre_exam=days <= PRE_EXAM_DAYS,
        is_pre30=days <= PRE_EXAM_30_DAYS,
    )
    done = int(plan.get("completed_today") or 0)
    remaining = len(plan.get("questions") or [])
    raw_total = done + remaining
    st = _load_json(TODAY_QUEST_PATH, {})
    kind = st.get("kind") if isinstance(st, dict) else "area"
    quota = RETAKE_REVIEW_QUOTA
    if isinstance(st, dict) and st.get("review_n") is not None:
        quota = int(st["review_n"])
    if kind in ("finale", "mock") or quota >= 25:
        return done, max(raw_total, quota)
    if quota <= 0:
        return done, raw_total
    return min(done, quota), quota


def _area_done_count(areas: str | list[str]) -> int:
    bank = _load_json(QUESTION_BANK_PATH, [])
    if not isinstance(bank, list):
        return 0
    names = areas if isinstance(areas, list) else [areas]
    wants = {(normalize_area(a) or a) for a in names if a}
    if not wants:
        return 0
    today = date.today().isoformat()
    n = 0
    for r in bank:
        if not isinstance(r, dict):
            continue
        if r.get("date") != today:
            continue
        src = str(r.get("source") or "")
        # area_seed 会归一成 area_practice；旧数据可能仍是 area_seed / 误记成 manual
        if src in ("area_practice", "area_seed"):
            pass
        elif (
            src == "manual"
            and str(r.get("parsed_by") or "") == "daily_practice.py"
        ):
            # 今日任务专项里种子题曾被记成 manual，仍计入进度
            pass
        else:
            continue
        got = normalize_area(r.get("knowledge_area") or "") or r.get("knowledge_area")
        if got in wants:
            n += 1
    return n


def _daily_practice_count() -> int:
    bank = _load_json(QUESTION_BANK_PATH, [])
    if not isinstance(bank, list):
        return 0
    today = date.today().isoformat()
    n = 0
    for r in bank:
        if not isinstance(r, dict):
            continue
        if r.get("date") != today:
            continue
        if r.get("source") == "daily_practice":
            n += 1
    return n


def _box(done: bool) -> str:
    return "✅" if done else "□"


def _status() -> dict[str, Any]:
    st = _state()
    area = _primary_area(st)
    kind = st.get("kind") or "area"
    skip_area = kind in ("finale", "exam", "mock") or not area
    rev_done, rev_total = _review_progress()
    step1_done = rev_total == 0 or rev_done >= rev_total
    focus = _focus_areas(st)
    area_n = 0 if skip_area else _area_done_count(focus if focus else (area or ""))
    step2_target = int(st.get("question_n") or AREA_PRACTICE_LIMIT)
    session_done = bool(st.get("area_session_done")) and bool(st.get("area_session_passed"))
    session_total = int(st.get("area_session_total") or 0)
    if session_done and session_total > area_n:
        area_n = session_total
    step2_done = True if skip_area else (area_n >= step2_target or session_done)
    step3_done = bool(st.get("cards_shown"))
    all_done = step1_done and step2_done and step3_done
    if all_done and not st.get("done"):
        st["done"] = True
        _save_state(st)
    d = _d_day()
    tomorrow_area = st.get("tomorrow_area")
    tomorrow_kind = st.get("tomorrow_kind") or ("exam" if d <= 1 else "area")
    return {
        "area": area,
        "kind": kind,
        "skip_area": skip_area,
        "why": _area_why(area, st),
        "tomorrow": _tomorrow_line(tomorrow_kind, tomorrow_area, st.get("tomorrow_focus")),
        "clear_mode": d <= 7,
        "rev_done": rev_done,
        "rev_total": rev_total,
        "step1_done": step1_done,
        "area_n": area_n,
        "step2_target": step2_target,
        "step2_done": step2_done,
        "step3_done": step3_done,
        "all_done": all_done,
        "focus": focus,
        "skip_live": bool(st.get("skip_live")),
        "daily_n": _daily_practice_count(),
        "plan_key": st.get("plan_key") or "",
    }


def _cards_text() -> str:
    st = _state()
    focus = _focus_areas(st)
    items = rank_high_frequency_errors(top_n=50, min_mistakes=3)
    errors = _load_json(ERROR_LOG_PATH, [])
    err_map = {
        e["id"]: e
        for e in errors
        if isinstance(e, dict) and e.get("id")
    } if isinstance(errors, list) else {}
    picked = pick_daily_hf_cards(items, focus)
    focus_s = "+".join(_sprint_area(a) for a in focus[:2]) if focus else "顽疾"
    lines = [
        f"③ 摘要卡（{STEP3_MINUTES}分钟 · {len(picked)} 张 · 今日域 {focus_s}）",
        "出声念「背」，扫一眼「别踩」。不必重做选项。",
        "",
    ]
    for i, it in enumerate(picked, 1):
        eid = it["error_id"]
        err = err_map.get(eid)
        if not err:
            lines.append(f"{i}. #{eid} 题库缺失，跳过")
            lines.append("")
            continue
        card = format_quest_summary_card(
            err, mistake_count=int(it.get("mistake_count") or 0)
        )
        # 编号前缀，微信更好扫
        first, *rest = card.splitlines()
        lines.append(f"{i}. {first}")
        lines.extend(rest)
        lines.append("")
    if not picked:
        lines.append("暂无高频卡，先完成①清错题。")
        lines.append("")
    lines.append("念完回复「下一步」收工")
    return "\n".join(lines).rstrip()


def _area_label(s: dict[str, Any]) -> str:
    focus = s.get("focus") or []
    if len(focus) >= 2:
        return "+".join(_sprint_area(a) for a in focus[:2])
    return _sprint_area(s.get("area") or "")


def format_overview() -> str:
    s = _status()
    today = date.today()
    days = (_exam_date() - today).days
    area = _area_label(s)
    rev_shown = s["rev_total"] if s["rev_total"] else s["rev_done"]
    budget = 70 if s.get("plan_key") else 80
    review_min = 15 if (s.get("rev_total") or 0) <= 5 else STEP1_MINUTES
    area_min = 45 if (s.get("step2_target") or 0) >= 20 else STEP2_MINUTES
    daily_n = int(s.get("daily_n") or 0)
    pass_line = max(1, round(int(s.get("step2_target") or 20) * 0.7))
    lines = [
        f"📋 今日任务 · {today.month}月{today.day}日 · 约{budget}分钟",
        _phase_line(today, days),
        f"🎯 {s.get('why') or '按补考周历推进'}",
        f"📆 {s.get('tomorrow') or '明天任务会自动更新'}",
        "",
        f"{_box(s['step1_done'])} ① 清错题  {s['rev_done']}/{rev_shown}  · {review_min}分钟（定额，刷量不算加分）",
    ]
    if s.get("skip_area"):
        kind = s.get("kind")
        if kind == "mock":
            lines.append(f"{_box(True)} ② 今日专项停：全真模考，当正式考试")
        elif kind == "exam":
            lines.append(f"{_box(True)} ② 今日专项停：考试日只过口诀")
        else:
            lines.append(f"{_box(True)} ② 不新开专项（复盘日）")
    else:
        lines.append(
            f"{_box(s['step2_done'])} ② 专项 {area}  {s['area_n']}/{s['step2_target']}题 · {area_min}分钟"
        )
    lines.extend([
        f"{_box(s['step3_done'])} ③ 摘要卡  {DAILY_HF_LIMIT}张 · {STEP3_MINUTES}分钟",
        f"{_box(daily_n >= 10)} 每日一练  {daily_n}/10 · 13分钟（必须掐表）",
        "□ 睡前 今天新错的 3 条口诀",
        "",
    ])
    if s.get("skip_live"):
        lines.append("🟡 今晚机构课可跳过/倍速，70 分钟必须给专项，不准拿课当借口")
        lines.append("")
    if s.get("clear_mode"):
        lines.append("⚠️ 考前清零已开，错题量会加大，优先清完①")
        lines.append("")
    if not s.get("skip_area") and not s["step2_done"]:
        gap = int(s["step2_target"]) - int(s["area_n"])
        lines.append(
            f"⚠️ 专项还差 {gap} 题。过关线 {s['step2_target']} 题、正确率 ≥70%（至少对 {pass_line} 题），少一题都不算完"
        )
        lines.append("")
    if daily_n < 10:
        lines.append(f"⚠️ 每日一练 {daily_n}/10，未掐完 13 分钟套卷不算今天过关")
        lines.append("")
    if s["all_done"] and daily_n >= 10:
        lines.append("🎉 周历任务已完成。睡前回想今天新错的 3 条口诀。")
        lines.append("💬 或发「睡前复习」")
    elif s["all_done"]:
        lines.append("三步骨架已走完，但每日一练没掐完，今天还不能收工。")
        lines.append("💬 发「每日一练」补上")
    elif not s["step1_done"]:
        lines.append("回复「开始任务」进入①清错题（逐题作答，定额做透）")
        lines.append("做题中途直接答 A/B/C/D，做完再发「下一步」")
    elif not s["step2_done"]:
        lines.append(f"①定额已满。回复「开始任务」进入②专项 {area}")
    else:
        lines.append("②已完成。回复「开始任务」过③摘要卡")
    return "\n".join(lines)


def next_step() -> dict[str, Any]:
    """推进到当前未完成的一步。action: overview|review|area|cards|done"""
    s = _status()
    area = s["area"]

    if s["all_done"]:
        return {
            "status": "ok",
            "action": "done",
            "text": "🎉 今日三步已完成。\n睡前回想今天新错的 3 条口诀。\n💬 发「睡前复习」或收工。",
        }

    if not s["step1_done"]:
        left = max(0, s["rev_total"] - s["rev_done"])
        return {
            "status": "ok",
            "action": "review",
            "text": (
                f"① 清错题开始（定额剩 {left} 道，多刷错不算加分）\n"
                "逐题回复 A/B/C/D。做透这几道再发「下一步」。"
            ),
        }

    if not s["step2_done"]:
        cmd_area = _area_label(s)
        pass_line = max(1, round(int(s["step2_target"]) * 0.7))
        remain = max(1, int(s["step2_target"]) - int(s["area_n"]))
        focus = list(s.get("focus") or [])
        if not focus and area:
            focus = [area]
        return {
            "status": "ok",
            "action": "area",
            "area": area,
            "focus": focus,
            "limit": remain,
            "text": (
                f"② 专项 {cmd_area} 开始（目标 {s['step2_target']} 题）\n"
                f"已做 {s['area_n']} 题。过关：做满且至少对 {pass_line} 题（70%）。\n"
                "先自己选，再看解析。做完发「下一步」。"
            ),
        }

    st = _state()
    st["cards_shown"] = True
    _save_state(st)
    return {
        "status": "ok",
        "action": "cards",
        "text": _cards_text(),
    }


def parse_quest_request(text: str) -> str | None:
    t = (text or "").strip().replace("\u200b", "").replace("\ufeff", "")
    t = re.sub(r"[。！!？?\s]+$", "", t)
    if t in START_TRIGGERS:
        return "start"
    if t in NEXT_TRIGGERS:
        return "next"
    return None


def handle_message(text: str) -> dict[str, Any]:
    action = parse_quest_request(text)
    if action == "start":
        return {"status": "ok", "action": "overview", "text": format_overview()}
    if action == "next":
        return next_step()
    return {"status": "skip"}


def main() -> None:
    parser = argparse.ArgumentParser(description="今日任务分步闯关")
    sub = parser.add_subparsers(dest="command")
    p_msg = sub.add_parser("message")
    p_msg.add_argument("--text", required=True)
    sub.add_parser("start")
    sub.add_parser("next")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    cmd = args.command or "start"
    if cmd == "message":
        result = handle_message(args.text)
    elif cmd == "next":
        result = next_step()
    else:
        result = {"status": "ok", "action": "overview", "text": format_overview()}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
