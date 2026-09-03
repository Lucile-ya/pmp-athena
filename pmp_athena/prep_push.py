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
    python pmp_athena/prep_push.py deliver       # 发送队列中的待推消息到微信
    python pmp_athena/prep_push.py schedule-mock # 模考完成后调用
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
import urllib.error
import urllib.request
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


def _load_wechat_account() -> dict | None:
    """读取最新绑定的微信账号（~/.wechat-claude-code/accounts）。"""
    accounts_dir = Path.home() / ".wechat-claude-code" / "accounts"
    if not accounts_dir.is_dir():
        return None
    files = sorted(accounts_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _split_wechat_text(text: str, max_len: int = 1800) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_len:
        cut = remaining.rfind("\n", 0, max_len)
        if cut < max_len // 2:
            cut = max_len
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _send_wechat_text(account: dict, text: str) -> None:
    base = str(account.get("baseUrl") or "https://ilinkai.weixin.qq.com").rstrip("/")
    token = account.get("botToken") or account.get("bot_token")
    user = account.get("userId") or account.get("user_id")
    if not token or not user:
        raise RuntimeError("微信账号缺少 botToken / userId")

    url = f"{base}/ilink/bot/sendmessage?token={token}"
    payload = json.dumps(
        {"touser": user, "msgtype": "text", "text": {"content": text}},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"微信 HTTP {exc.code}: {detail[:200]}") from exc

    if body.get("ret") != 0:
        raise RuntimeError(f"微信发送失败 ret={body.get('ret')} {body.get('errmsg')}")


def deliver_pending(*, dry_run: bool = False) -> list[str]:
    """将 pending 队列消息发送到微信并 ack。"""
    pending = list_pending()
    if not pending:
        return []

    account = _load_wechat_account()
    if account is None and not dry_run:
        raise RuntimeError(
            "未找到微信账号。请先运行 wechat-claude-code 扫码绑定（~/.wechat-claude-code/accounts/）"
        )

    sent_ids: list[str] = []
    for item in pending:
        msg_id = str(item.get("id") or "")
        text = str(item.get("text") or "").strip()
        if not msg_id:
            continue
        if not text:
            if not dry_run:
                ack_message(msg_id)
            sent_ids.append(msg_id)
            continue
        if dry_run:
            sent_ids.append(msg_id)
            continue
        parts = _split_wechat_text(text)
        for idx, part in enumerate(parts):
            _send_wechat_text(account, part)
            if idx + 1 < len(parts):
                import time
                time.sleep(1.5)
        ack_message(msg_id)
        sent_ids.append(msg_id)
    return sent_ids


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


def _append_daily_cheatsheet(parts: list[str]) -> None:
    """晨间推送附加：速记同步摘要 + 今日速记背诵。"""
    try:
        from pmp_athena.cheatsheet_sync import ensure_daily_sync, format_wechat_sync_report
        from pmp_athena.weak_area_cheatsheet import push_today
    except ModuleNotFoundError:
        from cheatsheet_sync import ensure_daily_sync, format_wechat_sync_report
        from weak_area_cheatsheet import push_today

    sync_result = ensure_daily_sync(silent=True)
    parts.append("\n" + "─" * 20 + "\n")
    if sync_result:
        parts.append(format_wechat_sync_report(sync_result))
        parts.append("")
    parts.append(push_today())


def push_daily_plan() -> dict | None:
    """生成今日复习计划推送（含速记同步 + 今日速记）。"""
    try:
        from pmp_athena.prep_analytics import today_review_checklist
    except ModuleNotFoundError:
        from prep_analytics import today_review_checklist

    result = today_review_checklist()
    text = result.get("text", "")
    if not text:
        return None

    header = f"🌅 今日复习计划 · {date.today().isoformat()}\n\n"
    parts = [header]
    try:
        from pmp_athena.daily_quest import format_overview
        parts.append(format_overview())
        parts.append("")
        parts.append("─" * 20)
        parts.append("")
    except Exception:
        pass
    parts.append(text)
    try:
        _append_daily_cheatsheet(parts)
    except Exception:
        pass
    return enqueue("daily_plan", "\n".join(parts))


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

    p_deliver = sub.add_parser("deliver", help="发送待推消息到微信")
    p_deliver.add_argument("--dry-run", action="store_true")
    p_deliver.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.command == "tick":
        created = tick()
        print(json.dumps({"created": len(created), "items": created}, ensure_ascii=False))
    elif args.command == "force-tick":
        created = tick(force=True)
        print(json.dumps({"created": len(created), "items": created}, ensure_ascii=False))
    elif args.command == "deliver":
        try:
            sent = deliver_pending(dry_run=getattr(args, "dry_run", False))
            out = {"status": "ok", "sent": sent, "count": len(sent)}
            print(json.dumps(out, ensure_ascii=False) if args.json else f"✅ 已发送 {len(sent)} 条")
        except RuntimeError as exc:
            out = {"status": "error", "error": str(exc)}
            print(json.dumps(out, ensure_ascii=False) if args.json else f"❌ {exc}")
            sys.exit(1)
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
