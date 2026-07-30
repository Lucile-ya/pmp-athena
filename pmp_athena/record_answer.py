#!/usr/bin/env python3
"""
统一做题/错题入库 —— 每日一练、模考、微信判卷共用。

编码规则（与 PDF 题号无关）：
  - error_log.id        → 错题本 #N（复习错题、SM-2 用这个）
  - question_bank.id    → 做题记录 #M（统计、查题用这个）
  - question_bank.error_log_id → 错题时指向 error_log.id；做对时为 null
  - 同题干多次做错     → 共用同一个 error_log.id，question_bank 可有多条

用法:
    python pmp_athena/record_answer.py wrong \\
        --question "..." --my-answer B --correct-answer C \\
        --knowledge-area 采购管理 --explanation "..." \\
        --source daily_practice

    python pmp_athena/record_answer.py correct \\
        --question "..." --my-answer A --correct-answer A \\
        --knowledge-area 整合管理 --source mock_exam
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Literal

SourceType = Literal[
    "daily_practice",  # 每日一练 PDF 对账/互动
    "mock_exam",       # 模考 PDF / 随机模考
    "manual",          # 微信单题、手动录入
    "screenshot",      # 发图 OCR
    "review",          # 错题复习时又答错（仅记 bank，不新建 error_log）
]

VALID_SOURCES = {
    "daily_practice", "mock_exam", "manual", "screenshot", "review",
    "daily", "mock",  # 别名
}

SOURCE_ALIASES = {
    "daily": "daily_practice",
    "mock": "mock_exam",
}


def _import_loggers():
    try:
        from pmp_athena.error_logger import ErrorLogger
        from pmp_athena.question_bank import QuestionBank
    except ModuleNotFoundError:
        from error_logger import ErrorLogger
        from question_bank import QuestionBank
    return ErrorLogger(), QuestionBank()


def normalize_source(source: str) -> str:
    s = (source or "manual").strip().lower()
    s = SOURCE_ALIASES.get(s, s)
    if s not in VALID_SOURCES:
        return "manual"
    return s


def record_wrong_answer(
    question: str,
    my_answer: str,
    correct_answer: str,
    knowledge_area: str = "",
    explanation: str = "",
    *,
    source: str = "manual",
    parsed_by: str = "claude",
) -> dict:
    """
    错题三文件同步（error_log + error_review_state + question_bank）。

    Returns:
        {
          "error_log_id": int,
          "bank_id": int,
          "error_is_new": bool,
          "source": str,
        }
    """
    error_logger, question_bank = _import_loggers()
    src = normalize_source(source)

    existing = error_logger.find_by_question(question)
    error_is_new = existing is None

    if existing:
        error_record = existing
    else:
        error_record = error_logger.add(
            question=question,
            my_answer=my_answer,
            correct_answer=correct_answer,
            knowledge_area=knowledge_area,
            explanation=explanation,
            parsed_by=parsed_by,
        )

    bank_record = question_bank.add(
        question=question,
        my_answer=my_answer,
        correct_answer=correct_answer,
        is_correct=False,
        knowledge_area=knowledge_area,
        explanation=explanation,
        parsed_by=parsed_by,
        source=src,
        error_log_id=error_record["id"],
    )

    return {
        "error_log_id": error_record["id"],
        "bank_id": bank_record["id"],
        "error_is_new": error_is_new,
        "source": src,
    }


def record_correct_answer(
    question: str,
    my_answer: str,
    correct_answer: str,
    knowledge_area: str = "",
    explanation: str = "",
    *,
    source: str = "manual",
    parsed_by: str = "claude",
) -> dict:
    """做对：只写 question_bank，不进错题本。"""
    _, question_bank = _import_loggers()
    src = normalize_source(source)

    bank_record = question_bank.add(
        question=question,
        my_answer=my_answer,
        correct_answer=correct_answer,
        is_correct=True,
        knowledge_area=knowledge_area,
        explanation=explanation,
        parsed_by=parsed_by,
        source=src,
        error_log_id=None,
    )

    return {
        "bank_id": bank_record["id"],
        "source": src,
    }


def main():
    parser = argparse.ArgumentParser(description="统一做题/错题入库")
    sub = parser.add_subparsers(dest="command")

    def add_common(p):
        p.add_argument("--question", "-q", required=True)
        p.add_argument("--my-answer", "-m", required=True)
        p.add_argument("--correct-answer", "-c", required=True)
        p.add_argument("--knowledge-area", "-k", default="综合")
        p.add_argument("--explanation", "-e", default="")
        p.add_argument(
            "--source", "-s", default="manual",
            help="daily_practice | mock_exam | manual | screenshot",
        )
        p.add_argument("--parsed-by", default="claude")
        p.add_argument("--json", action="store_true", help="JSON 输出")

    p_wrong = sub.add_parser("wrong", help="错题入库（三文件同步）")
    add_common(p_wrong)

    p_ok = sub.add_parser("correct", help="正确题入库（仅 question_bank）")
    add_common(p_ok)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    if args.command == "wrong":
        result = record_wrong_answer(
            question=args.question,
            my_answer=args.my_answer,
            correct_answer=args.correct_answer,
            knowledge_area=args.knowledge_area,
            explanation=args.explanation,
            source=args.source,
            parsed_by=args.parsed_by,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            tag = "新建" if result["error_is_new"] else "已存在(去重)"
            print(
                f"✅ 错题 #{result['error_log_id']} [{args.knowledge_area}] ({tag}) "
                f"→ 题库 #{result['bank_id']} source={result['source']}"
            )
    else:
        result = record_correct_answer(
            question=args.question,
            my_answer=args.my_answer,
            correct_answer=args.correct_answer,
            knowledge_area=args.knowledge_area,
            explanation=args.explanation,
            source=args.source,
            parsed_by=args.parsed_by,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(
                f"✅ 题库 #{result['bank_id']} [{args.knowledge_area}] "
                f"source={result['source']}"
            )


if __name__ == "__main__":
    main()
