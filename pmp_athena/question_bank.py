#!/usr/bin/env python3
"""
题库管理器 —— 存储所有做过的题目（正确 + 错误）

供 Claude Code 在微信对话中处理截图时自动调用，
也支持 CLI 查询（今日总结、本周错题、统计等）。

用法:
    python pmp_athena/question_bank.py add --question "..." --my-answer "A" --correct-answer "A" --is-correct true --knowledge-area "风险管理" --explanation "..."
    python pmp_athena/question_bank.py list --recent 10
    python pmp_athena/question_bank.py today
    python pmp_athena/question_bank.py week-wrong
    python pmp_athena/question_bank.py stats
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("question_bank")

DEFAULT_BANK_PATH = Path("D:/pmp-athena/pmp_notes/question_bank.json")

# PMP 知识领域（与 error_logger 保持一致）
KNOWLEDGE_AREAS = [
    "整合管理", "范围管理", "进度管理", "成本管理", "质量管理",
    "资源管理", "沟通管理", "风险管理", "采购管理", "干系人管理",
    "敏捷/混合方法", "商业环境", "领导力/人员",
]


class QuestionBank:
    """题库管理器"""

    def __init__(self, bank_path: Path | None = None):
        self.bank_path = bank_path or DEFAULT_BANK_PATH
        self._ensure_file()

    def _ensure_file(self):
        if not self.bank_path.exists():
            self.bank_path.parent.mkdir(parents=True, exist_ok=True)
            self.bank_path.write_text("[]", encoding="utf-8")

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.bank_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _write(self, data: list[dict]):
        self.bank_path.parent.mkdir(parents=True, exist_ok=True)
        self.bank_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── CRUD ───────────────────────────────────────────────

    def add(
        self,
        question: str,
        my_answer: str,
        correct_answer: str,
        is_correct: bool | None = None,
        knowledge_area: str = "",
        explanation: str = "",
        parsed_by: str = "claude",
        source: str = "manual",
        error_log_id: int | None = None,
        confidence: float | None = None,
    ) -> dict:
        """
        追加一条题目记录。

        自动去重：如果相同题目（前80字符匹配）在24小时内已存在，
        则仅更新 times_seen 和 last_review_date，不创建新记录。
        """
        data = self._read()
        now = datetime.now()
        question_stub = question.strip()[:80]

        # 去重：24 小时内同题只增加 seen 计数
        for record in reversed(data):
            if record.get("question", "")[:80] == question_stub:
                try:
                    record_time = datetime.fromisoformat(record["timestamp"])
                    if (now - record_time).total_seconds() < 86400:
                        record["times_seen"] = record.get("times_seen", 1) + 1
                        record["last_review_date"] = now.strftime("%Y-%m-%d")
                        self._write(data)
                        logger.info(
                            "Updated existing record #%d (times_seen=%d)",
                            record["id"],
                            record["times_seen"],
                        )
                        return record
                except (ValueError, KeyError):
                    pass

        # 新记录
        next_id = max((r.get("id", 0) for r in data), default=0) + 1
        record = {
            "id": next_id,
            "date": now.strftime("%Y-%m-%d"),
            "timestamp": now.isoformat(),
            "is_correct": is_correct,
            "question": question.strip(),
            "my_answer": my_answer.strip().upper(),
            "correct_answer": correct_answer.strip().upper(),
            "knowledge_area": knowledge_area.strip(),
            "explanation": explanation.strip(),
            "parsed_by": parsed_by,
            "source": source,
            "times_seen": 1,
            "last_review_date": now.strftime("%Y-%m-%d"),
            "error_log_id": error_log_id,
            "confidence": confidence,
        }
        data.append(record)
        self._write(data)

        label = "correct" if is_correct else ("wrong" if is_correct is False else "uncertain")
        logger.info("Question bank #%d added [%s] (%s)", next_id, knowledge_area, label)
        return record

    def add_from_validation(
        self,
        validation_result: dict,
        parsed_by: str = "ocr_validator",
        error_log_id: int | None = None,
    ) -> dict | None:
        """
        从 AnswerValidator.validate() 的结果中添加记录。

        便捷方法：将 validation_result["extracted"] 映射到 add() 参数。
        如果 extracted 中没有足够的题目信息，返回 None。
        """
        ext = validation_result.get("extracted", {})
        if not ext or not ext.get("question"):
            return None

        return self.add(
            question=ext["question"],
            my_answer=ext.get("my_answer", ""),
            correct_answer=ext.get("correct_answer", ""),
            is_correct=validation_result.get("is_correct"),
            knowledge_area=ext.get("knowledge_area", "未分类"),
            explanation=ext.get("explanation", ""),
            parsed_by=parsed_by,
            source="screenshot",
            error_log_id=error_log_id,
            confidence=validation_result.get("confidence"),
        )

    def update(
        self,
        record_id: int,
        **kwargs,
    ) -> dict | None:
        """
        更新已有记录（用于纠正 OCR 误判或人工修正）。

        支持更新的字段：question, my_answer, correct_answer, is_correct,
        knowledge_area, explanation, confidence。

        Returns:
            更新后的记录，未找到返回 None。
        """
        data = self._read()
        for record in data:
            if record.get("id") == record_id:
                updatable = [
                    "question", "my_answer", "correct_answer", "is_correct",
                    "knowledge_area", "explanation", "confidence",
                ]
                for key in updatable:
                    if key in kwargs and kwargs[key] is not None:
                        record[key] = kwargs[key]
                # 修正来源标记
                record["parsed_by"] = record.get("parsed_by", "claude") + "+manual_fix"
                self._write(data)
                logger.info("Question bank #%d updated", record_id)
                return record

        logger.warning("Question bank #%d not found", record_id)
        return None

    def get_by_id(self, record_id: int) -> dict | None:
        """按 ID 获取单条记录"""
        for r in self._read():
            if r.get("id") == record_id:
                return r
        return None

    # ── 查询 ───────────────────────────────────────────────

    def list_all(self) -> list[dict]:
        return self._read()

    def list_recent(self, n: int = 5) -> list[dict]:
        data = self._read()
        return data[-n:][::-1]

    def list_by_date(self, date_str: str) -> list[dict]:
        return [r for r in self._read() if r.get("date") == date_str]

    def list_by_date_range(self, start: str, end: str) -> list[dict]:
        return [r for r in self._read() if start <= r.get("date", "") <= end]

    def list_wrong(self, date_str: str | None = None) -> list[dict]:
        data = self._read()
        if date_str:
            return [r for r in data if r.get("date") == date_str and r.get("is_correct") is False]
        return [r for r in data if r.get("is_correct") is False]

    def list_correct(self, date_str: str | None = None) -> list[dict]:
        data = self._read()
        if date_str:
            return [r for r in data if r.get("date") == date_str and r.get("is_correct") is True]
        return [r for r in data if r.get("is_correct") is True]

    def list_by_area(self, area: str) -> list[dict]:
        return [
            r for r in self._read()
            if area.lower() in r.get("knowledge_area", "").lower()
        ]

    # ── 统计 ───────────────────────────────────────────────

    def get_stats(self) -> dict:
        data = self._read()
        total = len(data)
        correct = sum(1 for r in data if r.get("is_correct") is True)
        wrong = sum(1 for r in data if r.get("is_correct") is False)
        unknown = total - correct - wrong
        accuracy = correct / (correct + wrong) if (correct + wrong) > 0 else 0.0

        # 按领域分布
        area_map: dict[str, dict] = {}
        for r in data:
            area = r.get("knowledge_area", "未分类")
            if area not in area_map:
                area_map[area] = {"total": 0, "correct": 0, "wrong": 0}
            area_map[area]["total"] += 1
            if r.get("is_correct") is True:
                area_map[area]["correct"] += 1
            elif r.get("is_correct") is False:
                area_map[area]["wrong"] += 1
        sorted_areas = sorted(area_map.items(), key=lambda x: x[1]["total"], reverse=True)

        # 今天 & 本周
        today_str = date.today().isoformat()
        today_records = self.list_by_date(today_str)
        today_total = len(today_records)
        today_correct = sum(1 for r in today_records if r.get("is_correct") is True)
        today_wrong = sum(1 for r in today_records if r.get("is_correct") is False)

        # 本周（周一 ~ 周日）
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        week_records = self.list_by_date_range(monday.isoformat(), sunday.isoformat())
        week_total = len(week_records)
        week_correct = sum(1 for r in week_records if r.get("is_correct") is True)
        week_wrong = sum(1 for r in week_records if r.get("is_correct") is False)

        # 常见错题模式
        patterns: dict[str, int] = {}
        for r in data:
            if r.get("is_correct") is False:
                pattern = f"{r.get('my_answer', '?')}→{r.get('correct_answer', '?')}"
                patterns[pattern] = patterns.get(pattern, 0) + 1
        sorted_patterns = sorted(patterns.items(), key=lambda x: x[1], reverse=True)

        return {
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "unknown": unknown,
            "accuracy": round(accuracy, 3),
            "by_area": dict(sorted_areas),
            "today": {"total": today_total, "correct": today_correct, "wrong": today_wrong},
            "this_week": {"total": week_total, "correct": week_correct, "wrong": week_wrong},
            "common_mistakes": dict(sorted_patterns[:5]),
            "recent_wrong": [
                self._summarize(r) for r in data if r.get("is_correct") is False
            ][-5:][::-1],
        }

    def get_today_summary(self) -> dict:
        """今日做题总结"""
        today_str = date.today().isoformat()
        records = self.list_by_date(today_str)
        total = len(records)
        correct = sum(1 for r in records if r.get("is_correct") is True)
        wrong = sum(1 for r in records if r.get("is_correct") is False)
        accuracy = correct / (correct + wrong) if (correct + wrong) > 0 else 0.0

        wrong_records = [r for r in records if r.get("is_correct") is False]

        return {
            "date": today_str,
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "accuracy": round(accuracy, 3),
            "wrong_list": [self._summarize(r) for r in wrong_records],
        }

    def get_week_wrong_summary(self) -> dict:
        """本周错题汇总"""
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)

        week_records = self.list_by_date_range(monday.isoformat(), sunday.isoformat())
        wrong_records = [r for r in week_records if r.get("is_correct") is False]

        area_map: dict[str, list] = {}
        for r in wrong_records:
            area = r.get("knowledge_area", "未分类")
            if area not in area_map:
                area_map[area] = []
            area_map[area].append(self._summarize(r))

        return {
            "start": monday.isoformat(),
            "end": sunday.isoformat(),
            "total": len(week_records),
            "wrong_total": len(wrong_records),
            "accuracy": round(
                (len(week_records) - len(wrong_records)) / len(week_records), 3
            ) if week_records else 0.0,
            "by_area": area_map,
        }

    def _summarize(self, record: dict) -> dict:
        return {
            "id": record["id"],
            "date": record.get("date", ""),
            "area": record.get("knowledge_area", ""),
            "q": record.get("question", "")[:60] + "...",
            "my_answer": record.get("my_answer", ""),
            "correct_answer": record.get("correct_answer", ""),
        }


# ═══════════════════════════════════════════════════════════
# 格式化输出（供 CLI 和 Claude 调用）
# ═══════════════════════════════════════════════════════════

def _format_stats(stats: dict) -> str:
    lines = [f"\n📊 题库统计（共 {stats['total']} 题）\n"]
    lines.append(
        f"✅ 正确: {stats['correct']} | ❌ 错误: {stats['wrong']} | "
        f"⚠️ 未判定: {stats['unknown']}"
    )
    lines.append(f"🎯 正确率: {stats['accuracy']:.1%}\n")

    # 今日 & 本周
    today = stats["today"]
    week = stats["this_week"]
    lines.append(f"📅 今日: {today['total']} 题（正确率 {today['correct']}/{today['total']}）")
    lines.append(f"📅 本周: {week['total']} 题（正确率 {week['correct']}/{week['total']}）\n")

    # 按领域
    if stats["by_area"]:
        lines.append("## 按知识领域分布\n")
        lines.append("| 领域 | 总题数 | 正确 | 错误 | 正确率 |")
        lines.append("|------|--------|------|------|--------|")
        for area, counts in stats["by_area"].items():
            total = counts["total"]
            correct = counts["correct"]
            wrong = counts["wrong"]
            rate = correct / (correct + wrong) if (correct + wrong) > 0 else 0
            lines.append(f"| {area} | {total} | {correct} | {wrong} | {rate:.0%} |")

    # 常错模式
    if stats["common_mistakes"]:
        lines.append("\n## 常错选项模式\n")
        for pattern, count in stats["common_mistakes"].items():
            lines.append(f"- {pattern}: {count} 次")

    return "\n".join(lines)


def _format_today(summary: dict) -> str:
    lines = [f"\n📅 今日做题总结（{summary['date']}）\n"]
    lines.append(f"  共 {summary['total']} 题")
    lines.append(f"  ✅ 正确: {summary['correct']}")
    lines.append(f"  ❌ 错误: {summary['wrong']}")
    if summary["total"] > 0:
        lines.append(f"  🎯 正确率: {summary['accuracy']:.1%}")

    if summary["wrong_list"]:
        lines.append("\n## 今日错题\n")
        for r in summary["wrong_list"]:
            lines.append(f"  #{r['id']} [{r['area']}] {r['q']}")
    elif summary["total"] > 0:
        lines.append("\n🏆 全对！继续保持！")

    return "\n".join(lines)


def _format_week_wrong(summary: dict) -> str:
    lines = [f"\n📅 本周错题汇总（{summary['start']} ~ {summary['end']}）\n"]
    lines.append(f"  共做题 {summary['total']} 题，错 {summary['wrong_total']} 题")
    lines.append(f"  🎯 正确率: {summary['accuracy']:.1%}")

    if summary["by_area"]:
        lines.append("\n## 按领域分组\n")
        for area, records in summary["by_area"].items():
            lines.append(f"### {area}（{len(records)} 题）")
            for r in records:
                my = r.get("my_answer", "?")
                correct = r.get("correct_answer", "?")
                lines.append(f"  #{r['id']} {my}→{correct} | {r['q']}")
            lines.append("")
    else:
        lines.append("\n🏆 本周没错题！")

    return "\n".join(lines)


def _format_list(records: list[dict]) -> str:
    if not records:
        return "📭 暂无记录"

    lines = []
    for r in records:
        is_correct = r.get("is_correct")
        icon = "✅" if is_correct is True else ("❌" if is_correct is False else "⚠️")
        lines.append(
            f"{icon} #{r['id']} [{r.get('date', '?')}] {r.get('knowledge_area', '')} | "
            f"{r.get('my_answer', '?')}→{r.get('correct_answer', '?')} | "
            f"{r.get('question', '')[:60]}..."
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="题库管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # add
    p_add = sub.add_parser("add", help="添加一道题目")
    p_add.add_argument("--question", "-q", required=True, help="题目文字")
    p_add.add_argument("--my-answer", "-m", required=True, help="我的答案")
    p_add.add_argument("--correct-answer", "-c", required=True, help="正确答案")
    p_add.add_argument("--is-correct", type=lambda s: s.lower() in ("true", "1", "yes"), default=None,
                       help="是否答对 (true/false)")
    p_add.add_argument("--knowledge-area", "-k", default="未分类", help="知识领域")
    p_add.add_argument("--explanation", "-e", default="", help="解析摘要")
    p_add.add_argument("--parsed-by", default="claude", help="解析者")
    p_add.add_argument("--source", default="manual", help="来源（screenshot/manual）")
    p_add.add_argument("--error-log-id", type=int, default=None, help="关联的错题记录 ID")
    p_add.add_argument("--confidence", type=float, default=None, help="判定置信度 (0.0~1.0)")

    # list
    p_list = sub.add_parser("list", help="列出题目")
    p_list.add_argument("--area", "-a", help="按领域筛选")
    p_list.add_argument("--recent", "-n", type=int, default=0, help="最近 N 条")
    p_list.add_argument("--wrong", action="store_true", help="只看错题")
    p_list.add_argument("--correct-only", action="store_true", help="只看对的题")
    p_list.add_argument("--today", action="store_true", help="只看今天的")
    p_list.add_argument("--week", action="store_true", help="只看本周的")

    # stats
    sub.add_parser("stats", help="题库统计")

    # today
    sub.add_parser("today", help="今日做题总结")

    # week-wrong
    sub.add_parser("week-wrong", help="本周错题汇总")

    # update
    p_update = sub.add_parser("update", help="纠正题目记录（手动修正 OCR 误判等）")
    p_update.add_argument("id", type=int, help="要纠正的题目 ID")
    p_update.add_argument("--question", "-q", default=None, help="修正题目文字")
    p_update.add_argument("--my-answer", "-m", default=None, help="修正我的答案")
    p_update.add_argument("--correct-answer", "-c", default=None, help="修正正确答案")
    p_update.add_argument("--is-correct", type=lambda s: s.lower() in ("true", "1", "yes"), default=None,
                          help="修正对错判定 (true/false)")
    p_update.add_argument("--knowledge-area", "-k", default=None, help="修正知识领域")
    p_update.add_argument("--explanation", "-e", default=None, help="修正解析")

    # show
    sub.add_parser("show", help="查看指定题目详情").add_argument("id", type=int, help="题目 ID")

    args = parser.parse_args()
    qb = QuestionBank()

    if args.command == "add":
        record = qb.add(
            question=args.question,
            my_answer=args.my_answer,
            correct_answer=args.correct_answer,
            is_correct=args.is_correct,
            knowledge_area=args.knowledge_area,
            explanation=args.explanation,
            parsed_by=args.parsed_by,
            source=args.source,
            error_log_id=args.error_log_id,
            confidence=args.confidence,
        )
        print(f"📋 已记录题库 #{record['id']} [{record.get('knowledge_area', '')}]")

    elif args.command == "list":
        if args.area:
            records = qb.list_by_area(args.area)
        elif args.today:
            records = qb.list_by_date(date.today().isoformat())
        elif args.week:
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            sunday = monday + timedelta(days=6)
            records = qb.list_by_date_range(monday.isoformat(), sunday.isoformat())
        elif args.wrong:
            records = qb.list_wrong()
        elif args.correct_only:
            records = qb.list_correct()
        elif args.recent:
            records = qb.list_recent(args.recent)
        else:
            records = qb.list_all()

        print(_format_list(records))

    elif args.command == "stats":
        stats = qb.get_stats()
        print(_format_stats(stats))

    elif args.command == "today":
        summary = qb.get_today_summary()
        print(_format_today(summary))

    elif args.command == "week-wrong":
        summary = qb.get_week_wrong_summary()
        print(_format_week_wrong(summary))

    elif args.command == "update":
        record = qb.update(
            args.id,
            question=args.question,
            my_answer=args.my_answer,
            correct_answer=args.correct_answer,
            is_correct=args.is_correct,
            knowledge_area=args.knowledge_area,
            explanation=args.explanation,
        )
        if record:
            print(f"✅ 已纠正 #{record['id']}")
            print(f"   题目: {record.get('question', '')[:60]}...")
            print(f"   答案: {record.get('my_answer', '')} → {record.get('correct_answer', '')}")
            print(f"   对错: {'✅ 正确' if record.get('is_correct') is True else ('❌ 错误' if record.get('is_correct') is False else '⚠️ 未判定')}")
            print(f"   领域: {record.get('knowledge_area', '')}")
        else:
            print(f"❌ 未找到 #{args.id}")

    elif args.command == "show":
        record = qb.get_by_id(args.id)
        if record:
            print(f"\n📋 题目 #{record['id']}")
            print(f"   日期: {record.get('date', '?')}")
            print(f"   题目: {record.get('question', '')}")
            print(f"   我的答案: {record.get('my_answer', '?')}")
            print(f"   正确答案: {record.get('correct_answer', '?')}")
            is_correct = record.get("is_correct")
            icon = "✅" if is_correct is True else ("❌" if is_correct is False else "⚠️")
            print(f"   判定: {icon}")
            print(f"   知识领域: {record.get('knowledge_area', '未分类')}")
            print(f"   解析: {record.get('explanation', '无')}")
            print(f"   来源: {record.get('source', '?')} ({record.get('parsed_by', '?')})")
            print(f"   见过: {record.get('times_seen', 1)} 次")
        else:
            print(f"❌ 未找到 #{args.id}")

    else:
        # 默认显示统计
        stats = qb.get_stats()
        print(_format_stats(stats))


if __name__ == "__main__":
    main()
