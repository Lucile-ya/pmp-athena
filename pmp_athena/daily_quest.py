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
        TARGET_EXAM_DATE,
        TODAY_QUEST_PATH,
    )
    from pmp_athena.cheatsheet_sync import (
        _d_day,
        _ranked_area_triples,
        sprint_slot,
        today_focus_areas,
    )
    from pmp_athena.error_insights import build_mnemonic, rank_high_frequency_errors
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
        TARGET_EXAM_DATE,
        TODAY_QUEST_PATH,
    )
    from cheatsheet_sync import (  # type: ignore
        _d_day,
        _ranked_area_triples,
        sprint_slot,
        today_focus_areas,
    )
    from error_insights import build_mnemonic, rank_high_frequency_errors  # type: ignore
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
        return date.fromisoformat(str(TARGET_EXAM_DATE)[:10])
    except Exception:
        return date(2026, 9, 12)


def _phase_line(today: date, days: int) -> str:
    if today >= date(2026, 9, 2):
        return f"🔥 冲刺模考期 · 距考试 {max(days, 0)} 天"
    if today >= date(2026, 8, 16):
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
    return sprint_slot(_ranked_area_triples(), _d_day())


def _area_why(area: str | None) -> str:
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


def _tomorrow_line(kind: str, area: str | None) -> str:
    if kind == "exam":
        return "明天：考试日，只过口诀"
    if kind == "finale" or not area:
        return "明天：摘要卡 + 错题清零 / 随机模考"
    return f"明天：专项 {_sprint_area(area)}"


def _focus_areas(locked: dict | None = None) -> list[str]:
    if locked and locked.get("focus"):
        return list(locked["focus"])
    return today_focus_areas(_ranked_area_triples(), _d_day())


def _primary_area(locked: dict | None = None) -> str | None:
    if locked and locked.get("kind") == "finale":
        return None
    if locked and locked.get("area"):
        return locked["area"]
    slot = _live_slot()
    return slot.get("area")


def _fresh_plan(history: list) -> dict:
    slot = _live_slot()
    d = _d_day()
    tomorrow = sprint_slot(_ranked_area_triples(), d - 1) if d > 1 else {
        "kind": "exam",
        "area": None,
    }
    return {
        "date": date.today().isoformat(),
        "kind": slot.get("kind") or "area",
        "area": slot.get("area"),
        "focus": slot.get("focus") or [],
        "tomorrow_area": tomorrow.get("area"),
        "tomorrow_kind": tomorrow.get("kind"),
        "cards_shown": False,
        "done": False,
        "history": history[-10:],
    }


def _state() -> dict:
    today = date.today().isoformat()
    data = _load_json(TODAY_QUEST_PATH, {})
    if isinstance(data, dict) and data.get("date") == today:
        if "kind" not in data:
            slot = _live_slot()
            d = _d_day()
            tomorrow = sprint_slot(_ranked_area_triples(), d - 1) if d > 1 else {
                "kind": "exam",
                "area": None,
            }
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
    """(已完成, 今日应推总数含已完成)."""
    sch = ReviewScheduler()
    days = (_exam_date() - date.today()).days
    plan = sch.build_daily_plan(
        is_pre_exam=days <= PRE_EXAM_DAYS,
        is_pre30=days <= PRE_EXAM_30_DAYS,
    )
    done = int(plan.get("completed_today") or 0)
    remaining = len(plan.get("questions") or [])
    return done, done + remaining


def _area_done_count(area: str) -> int:
    bank = _load_json(QUESTION_BANK_PATH, [])
    if not isinstance(bank, list):
        return 0
    today = date.today().isoformat()
    want = normalize_area(area) or area
    n = 0
    for r in bank:
        if not isinstance(r, dict):
            continue
        if r.get("date") != today:
            continue
        if r.get("source") != "area_practice":
            continue
        got = normalize_area(r.get("knowledge_area") or "") or r.get("knowledge_area")
        if got == want:
            n += 1
    return n


def _box(done: bool) -> str:
    return "✅" if done else "□"


def _status() -> dict[str, Any]:
    st = _state()
    area = _primary_area(st)
    skip_area = st.get("kind") == "finale" or not area
    rev_done, rev_total = _review_progress()
    step1_done = rev_total == 0 or rev_done >= rev_total
    area_n = 0 if skip_area else _area_done_count(area or "")
    step2_target = AREA_PRACTICE_LIMIT
    step2_done = True if skip_area else area_n >= step2_target
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
        "kind": st.get("kind") or "area",
        "skip_area": skip_area,
        "why": _area_why(area),
        "tomorrow": _tomorrow_line(tomorrow_kind, tomorrow_area),
        "clear_mode": d <= 7,
        "rev_done": rev_done,
        "rev_total": rev_total,
        "step1_done": step1_done,
        "area_n": area_n,
        "step2_target": step2_target,
        "step2_done": step2_done,
        "step3_done": step3_done,
        "all_done": all_done,
        "focus": _focus_areas(st),
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
    lines = [
        f"③ 摘要卡（{STEP3_MINUTES}分钟 · {len(picked)} 张）",
        "口诀出声念，不必重做选项",
        "",
    ]
    for it in picked:
        eid = it["error_id"]
        err = err_map.get(eid, {})
        mnemonic = build_mnemonic(err) if err else ""
        gist = re.sub(r"\s+", " ", it.get("question_preview") or "")[:28]
        area = _sprint_area(it.get("knowledge_area") or "")
        lines.append(f"#{eid} [{area}] 错{it.get('mistake_count')}次")
        if mnemonic:
            lines.append(f"  🎯 {mnemonic}")
        if gist:
            lines.append(f"  {gist}…")
        lines.append("")
    if not picked:
        lines.append("暂无高频卡，先完成①清错题。")
        lines.append("")
    lines.append("念完回复「下一步」收工")
    return "\n".join(lines).rstrip()


def format_overview() -> str:
    s = _status()
    today = date.today()
    days = (_exam_date() - today).days
    area = _sprint_area(s["area"] or "")
    rev_shown = s["rev_total"] if s["rev_total"] else s["rev_done"]
    lines = [
        f"📋 今日任务 · {today.month}月{today.day}日 · 约80分钟",
        _phase_line(today, days),
        f"🎯 {s.get('why') or '按考前日历推进'}",
        f"📆 {s.get('tomorrow') or '明天任务会自动更新'}",
        "",
        f"{_box(s['step1_done'])} ① 清错题  {s['rev_done']}/{rev_shown}  · {STEP1_MINUTES}分钟",
    ]
    if s.get("skip_area"):
        lines.append(f"{_box(True)} ② 不新开专项（考前复盘日）")
    else:
        lines.append(
            f"{_box(s['step2_done'])} ② 专项 {area}  {s['area_n']}/{s['step2_target']}题 · {STEP2_MINUTES}分钟"
        )
    lines.extend([
        f"{_box(s['step3_done'])} ③ 摘要卡  {DAILY_HF_LIMIT}张 · {STEP3_MINUTES}分钟",
        "□ 睡前 今天新错的 3 条口诀",
        "",
    ])
    if s.get("clear_mode"):
        lines.append("⚠️ 考前清零已开，错题量会加大，优先清完①")
        lines.append("")
    if s["all_done"]:
        lines.append("🎉 三步已完成。睡前回想今天新错的 3 条口诀。")
        lines.append("💬 或发「睡前复习」")
    elif not s["step1_done"]:
        lines.append("回复「开始任务」进入①清错题（逐题作答）")
        lines.append("做题中途直接答 A/B/C/D，做完再发「下一步」")
    elif not s["step2_done"]:
        lines.append(f"①已清完。回复「开始任务」进入②专项 {area}")
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
                f"① 清错题开始（剩 {left} 道 · 约{STEP1_MINUTES}分钟）\n"
                "逐题回复 A/B/C/D。全部清完后发「下一步」。"
            ),
        }

    if not s["step2_done"]:
        cmd_area = _sprint_area(area or "")
        return {
            "status": "ok",
            "action": "area",
            "area": area,
            "text": (
                f"② 专项 {cmd_area} 开始（目标 {s['step2_target']} 题 · 约{STEP2_MINUTES}分钟）\n"
                f"已做 {s['area_n']} 题。先自己选，再看解析。做完发「下一步」。"
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
