#!/usr/bin/env python3
"""
模考状态持久化模块 — 支持开始/暂停/继续/完成/放弃模考，自动计时。

状态文件: pmp_notes/mock_exam_state.json

用法:
    python -m pmp_athena.mock_exam_state start --exam-id "模考二" --total-questions 180
    python -m pmp_athena.mock_exam_state pause
    python -m pmp_athena.mock_exam_state resume
    python -m pmp_athena.mock_exam_state complete --correct-count 142
    python -m pmp_athena.mock_exam_state abandon
    python -m pmp_athena.mock_exam_state status
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("mock_exam_state")

# ── 中国时区（UTC+8）──────────────────────────────────────────
TZ_CST = timezone(timedelta(hours=8))

DEFAULT_STATE_PATH = Path("D:/pmp-athena/pmp_notes/mock_exam_state.json")


class MockExamState:
    """模考状态管理器"""

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or DEFAULT_STATE_PATH

    # ── 底层读写 ─────────────────────────────────────────────

    def _read(self) -> dict | None:
        """读取状态文件，不存在或损坏返回 None"""
        if not self.state_path.exists():
            return None
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return None

    def _write(self, data: dict):
        """写入状态文件"""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _clear(self):
        """删除状态文件"""
        try:
            self.state_path.unlink(missing_ok=True)
        except (FileNotFoundError, OSError):
            pass

    def _now_iso(self) -> str:
        """当前时间 ISO 格式（中国时区）"""
        return datetime.now(TZ_CST).isoformat()

    def _parse_time(self, ts: str) -> datetime:
        """解析 ISO 时间戳"""
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_CST)
        return dt

    def _elapsed_since(self, started_at_iso: str) -> int:
        """计算从 started_at 到现在的秒数"""
        if not started_at_iso:
            return 0
        start = self._parse_time(started_at_iso)
        now = datetime.now(TZ_CST)
        delta = now - start
        return max(0, int(delta.total_seconds()))

    # ── 公共 API ─────────────────────────────────────────────

    def get_status(self) -> dict:
        """获取当前模考状态"""
        data = self._read()
        if data is None:
            return {"has_active_exam": False}
        return {"has_active_exam": True, **data}

    def start(self, exam_id: str, total_questions: int = 180) -> dict:
        """
        开始一次新模考。
        如果已有活跃模考，先提示是否覆盖。
        """
        existing = self._read()
        if existing and existing.get("status") in ("active", "paused"):
            raise RuntimeError(
                f"已有活跃模考「{existing.get('exam_id')}」（状态: {existing.get('status')}）。\n"
                f"请先完成或放弃后再开始新模考。"
            )

        state = {
            "exam_id": exam_id,
            "status": "active",
            "started_at": self._now_iso(),
            "paused_at": None,
            "elapsed_seconds": 0,
            "total_questions": total_questions,
            "current_batch": 1,
            "current_question": 1,
            "answers": {},
            "batches_completed": [],
            "correct_so_far": 0,
            "wrong_so_far": 0,
        }
        self._write(state)
        logger.info("模考「%s」已开始（%d 题）", exam_id, total_questions)
        return state

    def pause(self) -> dict:
        """
        暂停模考：计算本轮用时，累加到 elapsed_seconds。
        """
        state = self._read()
        if state is None:
            raise RuntimeError("没有活跃的模考可以暂停。")

        if state["status"] != "active":
            raise RuntimeError(f"模考状态为「{state['status']}」，无法暂停。")

        # 本轮用时 = 当前时间 - started_at
        this_leg = self._elapsed_since(state.get("started_at", ""))
        accumulated = state.get("elapsed_seconds", 0) + this_leg

        state["status"] = "paused"
        state["paused_at"] = self._now_iso()
        state["elapsed_seconds"] = accumulated
        # 不清空 started_at，保留用于日志
        self._write(state)

        mins = accumulated // 60
        secs = accumulated % 60
        logger.info("模考已暂停。累计用时: %d分%d秒", mins, secs)
        return state

    def resume(self) -> dict:
        """
        继续模考：重置 started_at 为当前时间，状态恢复为 active。
        """
        state = self._read()
        if state is None:
            raise RuntimeError("没有模考记录可以继续。")

        if state["status"] != "paused":
            raise RuntimeError(f"模考状态为「{state['status']}」，无法继续。")

        state["status"] = "active"
        state["started_at"] = self._now_iso()
        state["paused_at"] = None
        self._write(state)

        logger.info("模考「%s」已继续，累计用时 %d 秒",
                      state.get("exam_id"), state.get("elapsed_seconds", 0))
        return state

    def complete(
        self,
        correct_count: int = 0,
        wrong_count: int | None = None,
        scores: dict | None = None,
        weak_areas: list | None = None,
        knowledge_areas: dict | None = None,
    ) -> dict:
        """
        完成模考：计算总用时，写入 exam_records.json，清空状态文件。

        Returns:
            写入 exam_records.json 的记录
        """
        state = self._read()
        if state is None:
            raise RuntimeError("没有活跃的模考可以完成。")

        if state["status"] not in ("active", "paused"):
            raise RuntimeError(f"模考状态为「{state['status']}」，无法完成。")

        # 计算总用时
        total_seconds = state.get("elapsed_seconds", 0)
        if state["status"] == "active":
            # 如果当前是 active，加上本轮还没算的
            this_leg = self._elapsed_since(state.get("started_at", ""))
            total_seconds += this_leg

        total_minutes = total_seconds / 60

        # 用 batch 内累积的正确/错误数，或传参覆盖
        final_correct = correct_count or state.get("correct_so_far", 0)
        total_q = state.get("total_questions", 180)
        if wrong_count is None:
            final_wrong = total_q - final_correct
        else:
            final_wrong = wrong_count

        correct_rate = final_correct / total_q if total_q > 0 else 0

        # 写入 exam_records.json
        from .exam_recorder import ExamRecorder
        recorder = ExamRecorder()
        record = recorder.add(
            exam_id=state.get("exam_id", "未知模考"),
            total_questions=total_q,
            correct_count=final_correct,
            wrong_count=final_wrong,
            correct_rate=correct_rate,
            time_used_minutes=int(total_minutes),
            scores=scores or {},
            weak_areas=weak_areas or [],
            knowledge_areas=knowledge_areas,
            status="completed",
        )

        # 清空状态文件
        self._clear()

        logger.info(
            "模考完成。%s | %d/%d (%.1f%%) | 总用时 %d分",
            state.get("exam_id"), final_correct, total_q,
            correct_rate * 100, int(total_minutes),
        )
        return record

    def abandon(self) -> dict | None:
        """
        放弃模考：不写入记录，直接清空状态文件。
        """
        state = self._read()
        if state is None:
            raise RuntimeError("没有活跃的模考可以放弃。")

        exam_id = state.get("exam_id", "未知")
        status = state.get("status", "?")
        self._clear()
        logger.info("模考「%s」已放弃（状态: %s）", exam_id, status)
        return None

    def update_answers(
        self,
        batch: int | None = None,
        question: int | None = None,
        answers: dict | None = None,
        correct_so_far: int | None = None,
        wrong_so_far: int | None = None,
        batches_completed: list | None = None,
    ):
        """
        更新模考进度（每批判卷后调用）。
        不会改变计时。
        """
        state = self._read()
        if state is None:
            raise RuntimeError("没有活跃的模考，无法更新。")

        if batch is not None:
            state["current_batch"] = batch
        if question is not None:
            state["current_question"] = question
        if answers is not None:
            existing = state.get("answers", {})
            existing.update({str(k): v for k, v in answers.items()})
            state["answers"] = existing
        if correct_so_far is not None:
            state["correct_so_far"] = correct_so_far
        if wrong_so_far is not None:
            state["wrong_so_far"] = wrong_so_far
        if batches_completed is not None:
            state["batches_completed"] = batches_completed

        self._write(state)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════


def cmd_exam_state(args):
    """CLI entry: exam-state 子命令"""
    mgr = MockExamState()

    try:
        if args.sub == "start":
            state = mgr.start(
                exam_id=args.exam_id,
                total_questions=args.total_questions,
            )
            print(f"✅ 模考已开始: {state['exam_id']}（{state['total_questions']} 题）")
            print(f"   started_at: {state['started_at']}")

        elif args.sub == "pause":
            state = mgr.pause()
            mins = state["elapsed_seconds"] // 60
            secs = state["elapsed_seconds"] % 60
            print(f"⏸️  模考已暂停。累计用时: {mins}分{secs}秒")

        elif args.sub == "resume":
            state = mgr.resume()
            print(f"▶️  模考已继续: {state['exam_id']}")
            print(f"   started_at: {state['started_at']}（累计 {state['elapsed_seconds']} 秒）")

        elif args.sub == "complete":
            record = mgr.complete(
                correct_count=args.correct_count,
                wrong_count=args.wrong_count,
            )
            print(f"✅ 模考完成，已写入 exam_records.json")
            print(f"   {record['exam_id']} | {record['correct_count']}/{record['total_questions']} ({record['correct_rate']*100:.1f}%)")

        elif args.sub == "abandon":
            mgr.abandon()
            print("🗑️  模考已放弃，状态已清空。")

        elif args.sub == "status":
            info = mgr.get_status()
            if not info["has_active_exam"]:
                print("📭 当前没有活跃的模考。")
            else:
                status_emoji = {"active": "▶️", "paused": "⏸️", "completed": "✅"}
                emoji = status_emoji.get(info.get("status", ""), "❓")
                mins = info.get("elapsed_seconds", 0) // 60
                secs = info.get("elapsed_seconds", 0) % 60
                print(f"{emoji} 模考状态: {info.get('exam_id')} ({info.get('status')})")
                print(f"   进度: 第 {info.get('current_batch')} 批 / 第 {info.get('current_question')} 题")
                print(f"   已用时: {mins}分{secs}秒")
                print(f"   已完成批次: {info.get('batches_completed')}")
                if info.get("answers"):
                    print(f"   已答题数: {len(info.get('answers', {}))}")

        else:
            print(f"❓ 未知子命令: {args.sub}")

    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)


def add_subparser(subparsers):
    """注册 exam-state 到父 argparse"""
    p = subparsers.add_parser("exam-state", help="管理模考状态（开始/暂停/继续/完成/放弃/查看）")
    sub = p.add_subparsers(dest="sub", help="子命令")

    # exam-state start
    p_start = sub.add_parser("start", help="开始新模考")
    p_start.add_argument("--exam-id", required=True, help="模考名称")
    p_start.add_argument("--total-questions", type=int, default=180, help="总题数")
    p_start.set_defaults(func=cmd_exam_state)

    # exam-state pause
    p_pause = sub.add_parser("pause", help="暂停模考")
    p_pause.set_defaults(func=cmd_exam_state)

    # exam-state resume
    p_resume = sub.add_parser("resume", help="继续模考")
    p_resume.set_defaults(func=cmd_exam_state)

    # exam-state complete
    p_done = sub.add_parser("complete", help="完成模考并写入记录")
    p_done.add_argument("--correct-count", type=int, default=0, help="正确题数")
    p_done.add_argument("--wrong-count", type=int, default=None, help="错误题数（可选，默认 total-correct）")
    p_done.set_defaults(func=cmd_exam_state)

    # exam-state abandon
    p_abandon = sub.add_parser("abandon", help="放弃模考，不写记录")
    p_abandon.set_defaults(func=cmd_exam_state)

    # exam-state status
    p_status = sub.add_parser("status", help="查看当前模考状态")
    p_status.set_defaults(func=cmd_exam_state)


# ═══════════════════════════════════════════════════════════════
# 独立运行
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="模考状态持久化工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s start --exam-id "模考三" --total-questions 180
  %(prog)s pause
  %(prog)s resume
  %(prog)s complete --correct-count 142
  %(prog)s abandon
  %(prog)s status
        """,
    )
    sub = parser.add_subparsers(dest="sub", help="子命令")

    # start
    p_start = sub.add_parser("start", help="开始新模考")
    p_start.add_argument("--exam-id", required=True, help="模考名称")
    p_start.add_argument("--total-questions", type=int, default=180, help="总题数")

    sub.add_parser("pause", help="暂停模考")
    sub.add_parser("resume", help="继续模考")

    p_done = sub.add_parser("complete", help="完成模考并写入记录")
    p_done.add_argument("--correct-count", type=int, default=0, help="正确题数")
    p_done.add_argument("--wrong-count", type=int, default=None, help="错误题数")

    sub.add_parser("abandon", help="放弃模考，不写记录")
    sub.add_parser("status", help="查看当前模考状态")

    args = parser.parse_args()

    if not args.sub:
        parser.print_help()
        sys.exit(1)

    cmd_exam_state(args)


if __name__ == "__main__":
    main()
