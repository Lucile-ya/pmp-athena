#!/usr/bin/env python3
"""
模考记录写入工具 —— CLI + API

每次模考完成后，将完整考试数据写入 exam_records.json。

用法:
    python pmp_athena/exam_recorder.py add \
        --exam-id "模考卷二" \
        --total-questions 180 \
        --correct-count 142 \
        --wrong-count 38 \
        --time-used 196 \
        --scores '{"people":0.72,"process":0.78,"business_environment":0.85}' \
        --weak-areas '["质量管理","干系人管理"]' \
        --knowledge-areas '{"整合管理":0.8,"范围管理":0.75,"进度管理":0.9,...}'

    python pmp_athena/exam_recorder.py list       # 列出所有模考
    python pmp_athena/exam_recorder.py stats      # 模考统计
    python pmp_athena/exam_recorder.py latest     # 最近一次模考
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("exam_recorder")

DEFAULT_RECORDS_PATH = Path("D:/pmp-athena/pmp_notes/exam_records.json")

# ── PMP 知识领域列表 ──────────────────────────────────────────
KNOWLEDGE_AREAS = [
    "整合管理", "范围管理", "进度管理", "成本管理", "质量管理",
    "资源管理", "沟通管理", "风险管理", "采购管理", "干系人管理",
    "敏捷/混合方法", "商业环境", "领导力/人员",
]


class ExamRecorder:
    """模考记录管理器"""

    def __init__(self, records_path: Path | None = None):
        self.records_path = records_path or DEFAULT_RECORDS_PATH
        self._ensure_file()

    def _ensure_file(self):
        """确保记录文件存在并格式正确，自动迁移旧格式"""
        if not self.records_path.exists():
            self.records_path.parent.mkdir(parents=True, exist_ok=True)
            self.records_path.write_text(
                json.dumps({"exams": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return

        data = self._read_raw()
        exams = data.get("exams", []) if isinstance(data, dict) else []

        # 检测是否需要迁移：旧格式条目缺少 exam_id 字段
        needs_migrate = any(
            isinstance(e, dict) and "exam_id" not in e
            for e in exams
        )

        if needs_migrate:
            new_exams = []
            for e in exams:
                if not isinstance(e, dict):
                    continue
                # 如果已经是新格式，直接保留
                if "exam_id" in e and "correct_count" in e:
                    new_exams.append(e)
                    continue
                # 旧格式 → 新格式
                new_exams.append({
                    "exam_id": e.get("source", e.get("_comment", "未知模考")),
                    "exam_date": e.get("exam_date", ""),
                    "status": "completed",
                    "total_questions": e.get("total_questions", 180),
                    "correct_count": e.get("correct_count", 0),
                    "wrong_count": e.get("wrong_count", 0),
                    "correct_rate": e.get("correct_rate", 0.0),
                    "time_used_minutes": e.get("time_used_minutes", 0),
                    "scores": {
                        "people": e.get("scores", {}).get("people", 0),
                        "process": e.get("scores", {}).get("process", 0),
                        "business_environment": e.get("scores", {}).get("business_environment", 0),
                    },
                    "weak_areas": e.get("weak_areas", []),
                })
            self._write({"exams": new_exams})
            logger.info("Migrated exam_records.json to new format (%d records)", len(new_exams))

    def _read_raw(self) -> dict | list:
        try:
            return json.loads(self.records_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {"exams": []}

    def _read(self) -> dict:
        data = self._read_raw()
        if isinstance(data, list) or "exams" not in data:
            return {"exams": []}
        return data

    def _write(self, data: dict):
        self.records_path.parent.mkdir(parents=True, exist_ok=True)
        self.records_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── CRUD ───────────────────────────────────────────────────

    def add(
        self,
        exam_id: str,
        total_questions: int = 180,
        correct_count: int = 0,
        wrong_count: int = 0,
        correct_rate: float = 0.0,
        time_used_minutes: int = 0,
        scores: dict[str, float] | None = None,
        weak_areas: list[str] | None = None,
        knowledge_areas: dict | None = None,
        status: str = "completed",
        exam_type: str | None = None,
        source: str | None = None,
    ) -> dict:
        """
        添加一条完整的模考/练习记录。

        Args:
            exam_id: 模考标识（如"模考卷二"、"章节练习_范围管理"）
            total_questions: 总题数
            correct_count: 正确题数
            wrong_count: 错误题数
            correct_rate: 正确率（0-1）
            time_used_minutes: 用时（分钟）
            scores: {"people": 0.72, "process": 0.78, "business_environment": 0.85}
            weak_areas: 薄弱知识领域列表
            knowledge_areas: 各知识领域正确率或明细
                {"整合管理": 0.8} 或 {"范围管理": {"correct": 6, "total": 30, "rate": 0.2}}
            status: 状态
            exam_type: 记录类型（如 chapter_practice）
            source: 来源（如 截图录入）
        Returns:
            写入的完整记录
        """
        data = self._read()

        # 自动计算
        if correct_rate == 0.0 and total_questions > 0:
            correct_rate = correct_count / total_questions

        if wrong_count == 0 and total_questions > 0 and correct_count > 0:
            wrong_count = total_questions - correct_count

        record = {
            "exam_id": exam_id,
            "exam_date": date.today().isoformat(),
            "status": status,
            "total_questions": total_questions,
            "correct_count": correct_count,
            "wrong_count": wrong_count,
            "correct_rate": round(correct_rate, 4),
            "time_used_minutes": time_used_minutes,
            "scores": {
                "people": (scores or {}).get("people", 0),
                "process": (scores or {}).get("process", 0),
                "business_environment": (scores or {}).get("business_environment", 0),
            },
            "weak_areas": weak_areas or [],
        }

        # 可选：详细知识领域正确率
        if knowledge_areas:
            record["knowledge_areas"] = knowledge_areas

        if exam_type:
            record["type"] = exam_type
        if source:
            record["source"] = source

        data["exams"].append(record)
        self._write(data)

        logger.info(
            "Exam recorded: %s | %d/%d (%.1f%%) | %d min | weak: %s",
            exam_id, correct_count, total_questions,
            correct_rate * 100, time_used_minutes,
            ", ".join(weak_areas or []) or "none",
        )

        return record

    def list_all(self) -> list[dict]:
        """列出所有模考"""
        return self._read()["exams"]

    def latest(self) -> dict | None:
        """获取最近一次模考"""
        exams = self.list_all()
        return exams[-1] if exams else None

    def stats(self) -> dict:
        """模考统计"""
        exams = self.list_all()
        if not exams:
            return {"total": 0, "exams": []}

        completed = [e for e in exams if e.get("status") == "completed"]

        rates = [e["correct_rate"] for e in completed]

        return {
            "total_exams": len(exams),
            "completed": len(completed),
            "average_rate": round(sum(rates) / len(rates), 4) if rates else 0,
            "best_rate": round(max(rates), 4) if rates else 0,
            "worst_rate": round(min(rates), 4) if rates else 0,
            "latest_rate": round(completed[-1]["correct_rate"], 4) if completed else 0,
            "trend": "up" if len(rates) >= 2 and rates[-1] > rates[-2] else ("down" if len(rates) >= 2 and rates[-1] < rates[-2] else "flat"),
        }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="模考记录写入工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s add --exam-id "模考卷二" \\
      --total-questions 180 --correct-count 142 --wrong-count 38 \\
      --time-used 196 \\
      --scores '{"people":0.72,"process":0.78,"business_environment":0.85}' \\
      --weak-areas '["质量管理","干系人管理"]' \\
      --knowledge-areas '{"整合管理":0.8,"质量管理":0.6}'
  %(prog)s list
  %(prog)s stats
  %(prog)s latest
        """,
    )

    sub = parser.add_subparsers(dest="command", help="子命令")

    # add
    p_add = sub.add_parser("add", help="添加模考记录")
    p_add.add_argument("--exam-id", required=True, help="模考标识（如 模考卷二）")
    p_add.add_argument("--total-questions", type=int, default=180)
    p_add.add_argument("--correct-count", type=int, default=0)
    p_add.add_argument("--wrong-count", type=int, default=0)
    p_add.add_argument("--correct-rate", type=float, default=0.0)
    p_add.add_argument("--time-used", type=int, default=0, help="用时（分钟）")
    p_add.add_argument("--scores", type=str, default="{}", help='JSON: {"people":0.72,...}')
    p_add.add_argument("--weak-areas", type=str, default="[]", help='JSON: ["质量管理","干系人管理"]')
    p_add.add_argument("--knowledge-areas", type=str, default=None, help='JSON: {"整合管理":0.8,...}')
    p_add.add_argument("--status", default="completed")
    p_add.add_argument("--type", dest="exam_type", default=None, help="记录类型，如 chapter_practice")
    p_add.add_argument("--source", default=None, help="来源，如 截图录入")

    # list
    sub.add_parser("list", help="列出所有模考")

    # stats
    sub.add_parser("stats", help="模考统计")

    # latest
    sub.add_parser("latest", help="最近一次模考")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    recorder = ExamRecorder()

    if args.command == "add":
        try:
            scores = json.loads(args.scores)
        except json.JSONDecodeError:
            print(f"❌ --scores JSON 格式错误: {args.scores}")
            sys.exit(1)

        try:
            weak_areas = json.loads(args.weak_areas)
        except json.JSONDecodeError:
            print(f"❌ --weak-areas JSON 格式错误: {args.weak_areas}")
            sys.exit(1)

        knowledge_areas = None
        if args.knowledge_areas:
            try:
                knowledge_areas = json.loads(args.knowledge_areas)
            except json.JSONDecodeError:
                print(f"❌ --knowledge-areas JSON 格式错误: {args.knowledge_areas}")
                sys.exit(1)

        record = recorder.add(
            exam_id=args.exam_id,
            total_questions=args.total_questions,
            correct_count=args.correct_count,
            wrong_count=args.wrong_count,
            correct_rate=args.correct_rate,
            time_used_minutes=args.time_used,
            scores=scores,
            weak_areas=weak_areas,
            knowledge_areas=knowledge_areas,
            status=args.status,
            exam_type=args.exam_type,
            source=args.source,
        )

        print(f"✅ 模考记录已写入 exam_records.json (#{len(recorder.list_all())})")
        print(f"   {record['exam_id']} | {record['exam_date']}")
        print(f"   {record['correct_count']}/{record['total_questions']} ({record['correct_rate']*100:.1f}%)")
        print(f"   用时 {record['time_used_minutes']} 分钟")
        if record["weak_areas"]:
            print(f"   薄弱领域: {', '.join(record['weak_areas'])}")

    elif args.command == "list":
        exams = recorder.list_all()
        if not exams:
            print("📭 暂无模考记录")
            return

        print(f"📋 模考记录（共 {len(exams)} 次）\n")
        for i, e in enumerate(exams, 1):
            rate = e.get("correct_rate", 0) * 100
            print(
                f"  {i}. {e['exam_id']} | {e['exam_date']} | "
                f"{e.get('correct_count', '?')}/{e['total_questions']} ({rate:.1f}%) | "
                f"{e.get('time_used_minutes', '?')}min"
            )

    elif args.command == "stats":
        s = recorder.stats()
        print("📊 模考统计\n")
        print(f"  总次数: {s['total_exams']} / 已完成: {s['completed']}")
        print(f"  平均正确率: {s['average_rate']*100:.1f}%")
        print(f"  最高正确率: {s['best_rate']*100:.1f}%")
        print(f"  最低正确率: {s['worst_rate']*100:.1f}%")
        print(f"  最近正确率: {s['latest_rate']*100:.1f}%")
        print(f"  趋势: {'📈 上升' if s['trend'] == 'up' else ('📉 下降' if s['trend'] == 'down' else '➡️ 持平')}")

    elif args.command == "latest":
        latest = recorder.latest()
        if not latest:
            print("📭 暂无模考记录")
            return
        print(json.dumps(latest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
