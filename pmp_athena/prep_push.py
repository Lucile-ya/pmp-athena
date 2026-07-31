#!/usr/bin/env python3
"""
备考自动推送调度器。

推送队列写入 pmp_notes/prep_push_queue.json，由微信桥接或 Task Scheduler 轮询发送。

触发规则:
  - 每天 08:00 → 今日复习计划
  - 每周一 08:00 → 上周总结 + 本周目标
  - 模考完成 10 分钟后 → 模考分析
  - 连续 2 天正确率下降 >10% → 预警提醒

用法:
    python pmp_athena/prep_push.py tick          # 检查并生成到期推送（每分钟跑）
    python pmp_athena/prep_push.py pending       # 列出待发送消息
    python pmp_athena/prep_push.py ack --id N    # 标记已发送
    python pmp_athena/prep_push.py schedule-mock # 模考完成后调用
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import NOTES_DIR
except ModuleNotFoundError:
    from config import NOTES_DIR

QUEUE_PATH = NOTES_DIR / "prep_push_queue.json"
STATE_PATH = NOTES_DIR / "prep_push_state.json"

PUSH_HOUR = 8
MOCK_DELAY_MINUTES = 10


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def enqueue(
    push_type: str,
    text: str,
    *,
    delay_minutes: int = 0,
    meta: dict | None = None,
) -> dict:
    """加入推送队列。"""
    queue = _load_json(QUEUE_PATH, [])
    scheduled = datetime.now() + timedelta(minutes=delay_minutes)
    item = {
        "id": str(uuid.uuid4())[:8],
        "type": push_type,
        "text": text,
        "scheduled_at": scheduled.isoformat(timespec="seconds"),
        "created_at": _now_iso(),
        "sent_at": None,
        "status": "pending",
        "meta": meta or {},
    }
    queue.append(item)
    _save_json(QUEUE_PATH, queue)
    return item


def list_pending() -> list[dict]:
    """返回已到期的待发送消息。"""
    queue = _load_json(QUEUE_PATH, [])
    now = datetime.now()
    pending = []
    for item in queue:
        if item.get("status") != "pending":
            continue
        try:
            sched = datetime.fromisoformat(item.get("scheduled_at", ""))
        except ValueError:
            sched = now
        if sched <= now:
            pending.append(item)
    return pending


def ack_message(msg_id: str) -> bool:
    queue = _load_json(QUEUE_PATH, [])
    found = False
    for item in queue:
        if item.get("id") == msg_id:
            item["status"] = "sent"
            item["sent_at"] = _now_iso()
            found = True
            break
    if found:
        _save_json(QUEUE_PATH, queue)
    return found


def _state() -> dict:
    return _load_json(STATE_PATH, {
        "last_daily": None,
        "last_weekly": None,
        "last_alert": None,
        "mock_pending": [],
    })


def _save_state(state: dict) -> None:
    _save_json(STATE_PATH, state)


def _already_pushed_today(state: dict, key: str) -> bool:
    last = state.get(key)
    return last == date.today().isoformat()


def push_daily_plan() -> dict | None:
    """生成今日复习计划推送。"""
    try:
        from pmp_athena.prep_analytics import today_review_checklist
    except ModuleNotFoundError:
        from prep_analytics import today_review_checklist

    result = today_review_checklist()
    text = result.get("text", "")
    if not text:
        return None

    header = f"🌅 今日复习计划 · {date.today().isoformat()}\n\n"
    return enqueue("daily_plan", header + text)


def push_weekly_summary() -> dict | None:
    """生成上周总结 + 本周目标。"""
    try:
        from pmp_athena.prep_analytics import week_summary, error_study_plan
    except ModuleNotFoundError:
        from prep_analytics import week_summary, error_study_plan

    week = week_summary()
    plan = error_study_plan(horizon="week")
    text = week.get("text", "") + "\n\n" + "─" * 20 + "\n\n" + plan.get("text", "")
    header = f"📅 新的一周 · {date.today().isoformat()}\n\n"
    return enqueue("weekly_summary", header + text)


def schedule_mock_analysis(exam_record: dict | None = None) -> dict:
    """模考完成后调度 10 分钟后的分析推送。"""
    state = _state()
    state.setdefault("mock_pending", []).append({
        "scheduled_at": (datetime.now() + timedelta(minutes=MOCK_DELAY_MINUTES)).isoformat(timespec="seconds"),
        "exam_id": (exam_record or {}).get("exam_id", "模考"),
        "exam_date": (exam_record or {}).get("exam_date", date.today().isoformat()),
    })
    _save_state(state)

    try:
        from pmp_athena.prep_analytics import mock_exam_analysis
    except ModuleNotFoundError:
        from prep_analytics import mock_exam_analysis

    result = mock_exam_analysis(exam_record)
    text = result.get("text", "")
    header = "📊 模考分析报告\n\n"
    return enqueue("mock_analysis", header + text, delay_minutes=MOCK_DELAY_MINUTES, meta={
        "exam_id": (exam_record or {}).get("exam_id"),
    })


def push_accuracy_alert() -> dict | None:
    """正确率预警推送。"""
    try:
        from pmp_athena.prep_analytics import check_accuracy_alert
    except ModuleNotFoundError:
        from prep_analytics import check_accuracy_alert

    alert = check_accuracy_alert()
    if not alert:
        return None
    return enqueue("accuracy_alert", alert.get("text", ""))


def tick(*, force: bool = False) -> list[dict]:
    """
    调度心跳：检查时间点并生成推送。
    建议 Task Scheduler 每分钟或每天 8:00 调用。
    """
    state = _state()
    created: list[dict] = []
    now = datetime.now()
    today_str = date.today().isoformat()

    # 08:00 每日推送
    if force or (now.hour == PUSH_HOUR and now.minute < 5):
        if not _already_pushed_today(state, "last_daily"):
            item = push_daily_plan()
            if item:
                created.append(item)
                state["last_daily"] = today_str

        # 周一额外推送周报
        if date.today().weekday() == 0 and not _already_pushed_today(state, "last_weekly"):
            item = push_weekly_summary()
            if item:
                created.append(item)
                state["last_weekly"] = today_str

    # 正确率预警（每天检查一次）
    if not _already_pushed_today(state, "last_alert"):
        alert = push_accuracy_alert()
        if alert:
            created.append(alert)
            state["last_alert"] = today_str

    # 处理到期的模考分析（兜底）
    mock_pending = state.get("mock_pending") or []
    remaining = []
    for mp in mock_pending:
        try:
            sched = datetime.fromisoformat(mp.get("scheduled_at", ""))
        except ValueError:
            continue
        if sched <= now:
            # 已在 schedule_mock_analysis 入队，此处仅清理
            pass
        else:
            remaining.append(mp)
    state["mock_pending"] = remaining

    _save_state(state)
    return created


def cleanup_old(days: int = 30) -> int:
    """清理已发送超过 N 天的队列项。"""
    queue = _load_json(QUEUE_PATH, [])
    cutoff = datetime.now() - timedelta(days=days)
    kept = []
    removed = 0
    for item in queue:
        if item.get("status") == "sent":
            try:
                sent = datetime.fromisoformat(item.get("sent_at") or item.get("created_at", ""))
                if sent < cutoff:
                    removed += 1
                    continue
            except ValueError:
                pass
        kept.append(item)
    _save_json(QUEUE_PATH, kept)
    return removed


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="备考自动推送")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("tick", help="检查并生成到期推送")
    p_pending = sub.add_parser("pending", help="列出待发送消息")
    p_pending.add_argument("--json", action="store_true")

    p_ack = sub.add_parser("ack", help="标记消息已发送")
    p_ack.add_argument("--id", required=True)

    p_mock = sub.add_parser("schedule-mock", help="模考完成后调度分析推送")
    p_mock.add_argument("--json", action="store_true")

    p_daily = sub.add_parser("daily", help="立即推送今日计划")
    p_weekly = sub.add_parser("weekly", help="立即推送周报")
    p_alert = sub.add_parser("alert", help="立即检查预警")

    p_force = sub.add_parser("force-tick", help="强制运行 tick（忽略时间窗口）")

    args = parser.parse_args()

    if args.command == "tick":
        created = tick()
        print(json.dumps({"created": len(created), "items": created}, ensure_ascii=False))
    elif args.command == "force-tick":
        created = tick(force=True)
        print(json.dumps({"created": len(created), "items": created}, ensure_ascii=False))
    elif args.command == "pending":
        pending = list_pending()
        if args.json:
            print(json.dumps(pending, ensure_ascii=False))
        else:
            for p in pending:
                print(f"[{p['id']}] {p['type']} — {p['text'][:60]}…")
    elif args.command == "ack":
        ok = ack_message(args.id)
        print("✅ 已标记" if ok else "❌ 未找到")
    elif args.command == "schedule-mock":
        item = schedule_mock_analysis()
        out = {"status": "ok", "item": item}
        print(json.dumps(out, ensure_ascii=False) if args.json else f"✅ 已调度模考分析（10分钟后） id={item['id']}")
    elif args.command == "daily":
        item = push_daily_plan()
        print(item["text"] if item else "无内容")
    elif args.command == "weekly":
        item = push_weekly_summary()
        print(item["text"] if item else "无内容")
    elif args.command == "alert":
        item = push_accuracy_alert()
        print(item["text"] if item else "✅ 暂无预警")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
