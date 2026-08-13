#!/usr/bin/env python3
"""
错题记录工具 —— CLI + API

供 Claude Code 在微信对话中检测到"选错了"/"记录错题"时调用，
自动追加错题到 error_log.json。

用法（Claude 调用）:
    python pmp_athena/error_logger.py add \
        --question "以下哪项是风险应对策略？" \
        --my-answer "C" \
        --correct-answer "A" \
        --knowledge-area "风险管理" \
        --explanation "规避(Escalate)不是应对策略，正确应为上报"

    python pmp_athena/error_logger.py list          # 列出所有错题
    python pmp_athena/error_logger.py stats         # 错题统计
    python pmp_athena/error_logger.py recent 5      # 最近 N 条
"""

try:
    from pmp_athena.config import ERROR_LOG_PATH
except ModuleNotFoundError:
    from config import ERROR_LOG_PATH

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from pmp_athena.utils.question_text import normalize_question_text
except ModuleNotFoundError:
    from utils.question_text import normalize_question_text

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("error_logger")

# ── 配置 ──────────────────────────────────────────────────
DEFAULT_LOG_PATH = ERROR_LOG_PATH

# PMP 知识领域列表（供 Claude 参考分类）
KNOWLEDGE_AREAS = [
    "整合管理", "范围管理", "进度管理", "成本管理", "质量管理",
    "资源管理", "沟通管理", "风险管理", "采购管理", "干系人管理",
    "敏捷/混合方法", "商业环境", "领导力/人员",
]

# ── 错误类型分类 ──────────────────────────────────────────
ERROR_TYPES = {
    "概念混淆": "两个概念记反了（如 Risk vs Issue）",
    "流程顺序错": "知道该干啥但顺序不对（First 选了 Best）",
    "角色越权": "PO/SM/PM 职责搞混",
    "陷阱误导": "被干扰项骗了（T01-T12）",
    "粗心": "看漏/看错/手滑",
    "知识盲区": "完全没见过这个概念",
}


class ErrorLogger:
    """错题记录管理器"""

    def __init__(self, log_path: Path | None = None):
        self.log_path = log_path or DEFAULT_LOG_PATH
        self._ensure_file()

    def _ensure_file(self):
        """确保日志文件存在"""
        if not self.log_path.exists():
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_path.write_text("[]", encoding="utf-8")

    def _read(self) -> list[dict]:
        """读取全部错题"""
        try:
            data = json.loads(self.log_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _write(self, data: list[dict]):
        """写入全部错题"""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── CRUD ───────────────────────────────────────────────

    def find_by_question(self, question: str) -> dict | None:
        """按规范化题干查找已有错题（去重用）"""
        try:
            from pmp_athena.utils.question_text import question_dedup_key, normalize_question_text
        except ModuleNotFoundError:
            from utils.question_text import question_dedup_key, normalize_question_text

        key = question_dedup_key(question)
        for record in reversed(self._read()):
            if question_dedup_key(record.get("question", "")) == key:
                return record
        return None

    def update(self, record_id: int, **kwargs) -> dict | None:
        """更新已有错题（同题干重复录入时刷新答案/解析）。"""
        data = self._read()
        for record in data:
            if record.get("id") != record_id:
                continue
            updatable = [
                "question", "my_answer", "correct_answer",
                "knowledge_area", "explanation", "error_type",
            ]
            for key in updatable:
                if key in kwargs and kwargs[key] is not None:
                    val = kwargs[key]
                    if key == "question":
                        val = normalize_question_text(val)
                    elif key in ("my_answer", "correct_answer"):
                        val = val.strip().upper()
                    else:
                        val = str(val).strip()
                    record[key] = val
            record["timestamp"] = datetime.now().isoformat()
            self._write(data)
            logger.info("Error record #%d updated", record_id)
            return record
        logger.warning("Error record #%d not found", record_id)
        return None

    def add(
        self,
        question: str,
        my_answer: str,
        correct_answer: str,
        knowledge_area: str = "",
        explanation: str = "",
        parsed_by: str = "claude",
        *,
        allow_duplicate: bool = False,
        error_type: str = "",
    ) -> dict:
        """追加一条错题；默认同题去重，返回已有记录。"""
        question = normalize_question_text(question)

        if not allow_duplicate:
            existing = self.find_by_question(question)
            if existing:
                logger.info(
                    "Error #%d already exists (dedup), skip new entry",
                    existing["id"],
                )
                return existing

        data = self._read()
        next_id = max((r.get("id", 0) for r in data), default=0) + 1

        record = {
            "id": next_id,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "my_answer": my_answer.strip().upper(),
            "correct_answer": correct_answer.strip().upper(),
            "knowledge_area": knowledge_area.strip(),
            "parsed_by": parsed_by,
            "explanation": explanation.strip(),
            "error_type": error_type.strip() if error_type else "",
        }

        data.append(record)
        self._write(data)

        logger.info("Error record #%d added [%s]", next_id, knowledge_area)

        # 自动加入间隔复习队列
        try:
            from .spaced_repetition import SpacedRepetition
            sr = SpacedRepetition()
            sr.add(next_id)
        except Exception as e:
            logger.debug("Failed to add #%d to review queue: %s", next_id, e)

        return record

    def list_all(self) -> list[dict]:
        return self._read()

    def delete(self, record_id: int) -> dict | None:
        """删除一条错题记录，返回被删除的记录；未找到返回 None。"""
        data = self._read()
        for i, record in enumerate(data):
            if record.get("id") == record_id:
                removed = data.pop(i)
                self._write(data)
                logger.info("Error record #%d deleted", record_id)
                return removed
        logger.warning("Error record #%d not found", record_id)
        return None

    def list_recent(self, n: int = 5) -> list[dict]:
        data = self._read()
        return data[-n:][::-1]  # 最新的在前

    def list_by_area(self, area: str) -> list[dict]:
        return [
            r for r in self._read()
            if area.lower() in r.get("knowledge_area", "").lower()
        ]

    def get_stats(self) -> dict:
        """按知识领域统计错题分布"""
        data = self._read()
        area_counts: dict[str, int] = {}
        for r in data:
            area = r.get("knowledge_area", "未分类")
            area_counts[area] = area_counts.get(area, 0) + 1

        # 按数量降序
        sorted_areas = sorted(area_counts.items(), key=lambda x: x[1], reverse=True)

        # 计算最常见的错误选项模式
        patterns: dict[str, int] = {}
        for r in data:
            pattern = f"{r.get('my_answer', '?')}→{r.get('correct_answer', '?')}"
            patterns[pattern] = patterns.get(pattern, 0) + 1
        sorted_patterns = sorted(patterns.items(), key=lambda x: x[1], reverse=True)

        return {
            "total": len(data),
            "by_area": dict(sorted_areas),
            "common_mistakes": dict(sorted_patterns[:5]),
            "recent_5": [self._summarize(r) for r in data[-5:][::-1]],
        }

    def _summarize(self, record: dict) -> dict:
        return {
            "id": record["id"],
            "date": record["date"],
            "area": record.get("knowledge_area", ""),
            "q": record.get("question", "")[:50] + "...",
        }


# ═══════════════════════════════════════════════════════════
# 给 Claude 用的系统提示词片段
# ═══════════════════════════════════════════════════════════

AUTO_LOG_SYSTEM_PROMPT = """
## 错题自动记录规则

当用户的微信消息包含"选错了"、"记录错题"、"错题"、"做错了"、"记一下"等关键词，
且用户提供了题目信息时，你必须在完成题目解析后，调用以下命令记录错题：

```bash
python pmp_athena/error_logger.py add \\
    --question "<题目文字>" \\
    --my-answer "<用户选的错误选项>" \\
    --correct-answer "<正确答案>" \\
    --knowledge-area "<知识领域>" \\
    --explanation "<解析摘要（50字以内）>"
```

知识领域请从以下列表中选择最匹配的一个：
整合管理、范围管理、进度管理、成本管理、质量管理、
资源管理、沟通管理、风险管理、采购管理、干系人管理、
敏捷/混合方法、商业环境、领导力/人员

记录完成后，告诉用户"已记录到错题本 #N"。
"""


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def _format_stats(stats: dict) -> str:
    lines = []
    lines.append(f"\n📊 错题统计（共 {stats['total']} 条）\n")
    lines.append("## 按知识领域分布\n")
    lines.append("| 领域 | 错题数 | 占比 |")
    lines.append("|------|--------|------|")
    for area, count in stats["by_area"].items():
        pct = count / stats["total"] * 100 if stats["total"] else 0
        bar = "█" * max(1, int(pct / 5))
        lines.append(f"| {area} | {count} | {bar} {pct:.0f}% |")

    if stats["common_mistakes"]:
        lines.append("\n## 常错选项模式\n")
        for pattern, count in stats["common_mistakes"].items():
            lines.append(f"- {pattern}: {count} 次")

    lines.append("\n## 最近错题\n")
    for r in stats["recent_5"]:
        lines.append(f"  #{r['id']} [{r['area']}] {r['q']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="错题记录工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # add
    p_add = sub.add_parser("add", help="添加一条错题")
    p_add.add_argument("--question", "-q", required=True, help="题目文字")
    p_add.add_argument("--my-answer", "-m", required=True, help="我选的错误选项")
    p_add.add_argument("--correct-answer", "-c", required=True, help="正确答案")
    p_add.add_argument("--knowledge-area", "-k", default="未分类", help="知识领域")
    p_add.add_argument("--explanation", "-e", default="", help="解析摘要")
    p_add.add_argument("--parsed-by", default="claude", help="解析者")
    p_add.add_argument("--error-type", default="", help="错误类型：概念混淆/流程顺序错/角色越权/陷阱误导/粗心/知识盲区")

    # list
    p_list = sub.add_parser("list", help="列出错题")
    p_list.add_argument("--area", "-a", help="按领域筛选")
    p_list.add_argument("--recent", "-n", type=int, default=0, help="最近 N 条")

    # stats
    sub.add_parser("stats", help="错题统计")

    # 直接传 JSON（方便 Claude 调用）
    p_json = sub.add_parser("add-json", help="通过 JSON 添加错题（方便程序调用）")
    p_json.add_argument("json_str", help='JSON 字符串，如 \'{"question":"...","my_answer":"B",...}\'')

    args = parser.parse_args()
    logger_inst = ErrorLogger()

    if args.command == "add":
        record = logger_inst.add(
            question=args.question,
            my_answer=args.my_answer,
            correct_answer=args.correct_answer,
            knowledge_area=args.knowledge_area,
            explanation=args.explanation,
            parsed_by=getattr(args, "parsed_by", "claude"),
            error_type=getattr(args, "error_type", ""),
        )
        print(f"✅ 已记录错题 #{record['id']} [{record['knowledge_area']}]")

    elif args.command == "add-json":
        try:
            data = json.loads(args.json_str)
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败: {e}")
            sys.exit(1)
        record = logger_inst.add(
            question=data.get("question", ""),
            my_answer=data.get("my_answer", ""),
            correct_answer=data.get("correct_answer", ""),
            knowledge_area=data.get("knowledge_area", "未分类"),
            explanation=data.get("explanation", ""),
            parsed_by=data.get("parsed_by", "claude"),
            error_type=data.get("error_type", ""),
        )
        print(f"✅ 已记录错题 #{record['id']} [{record['knowledge_area']}]")

    elif args.command == "list":
        if args.area:
            records = logger_inst.list_by_area(args.area)
        elif args.recent:
            records = logger_inst.list_recent(args.recent)
        else:
            records = logger_inst.list_all()

        if not records:
            print("📭 暂无错题记录")
        else:
            for r in records:
                print(
                    f"#{r['id']} [{r['date']}] {r['knowledge_area']} | "
                    f"{r['my_answer']}→{r['correct_answer']} | "
                    f"{r['question'][:60]}..."
                )

    elif args.command == "stats":
        stats = logger_inst.get_stats()
        print(_format_stats(stats))

    else:
        # 默认显示统计
        stats = logger_inst.get_stats()
        print(_format_stats(stats))


if __name__ == "__main__":
    main()
