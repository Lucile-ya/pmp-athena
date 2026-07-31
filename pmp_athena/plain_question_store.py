#!/usr/bin/env python3
"""
纯题干截图待答状态 —— 用户随后告知「我选 X」且答错时自动入库。

pending 文件: pmp_notes/pending_plain_question.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PENDING_PATH = Path(__file__).resolve().parent.parent / "pmp_notes" / "pending_plain_question.json"


def _load() -> dict | None:
    if not PENDING_PATH.exists():
        return None
    try:
        data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("question") else None
    except (json.JSONDecodeError, OSError):
        return None


def _save(data: dict) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_pending() -> None:
    if PENDING_PATH.exists():
        PENDING_PATH.unlink()


def has_pending() -> bool:
    return _load() is not None


def get_pending() -> dict | None:
    return _load()


def _question_for_bank(pending: dict) -> str:
    fq = (pending.get("formatted_question") or "").strip()
    if fq:
        return fq.replace("📝 ", "", 1) if fq.startswith("📝 ") else fq
    q = pending.get("question") or ""
    options = pending.get("options") or {}
    lines = [q] if q else []
    for letter in ("A", "B", "C", "D", "E"):
        if letter in options:
            lines.append(f"{letter}. {options[letter]}")
    return "\n".join(lines)


def parse_my_answer(text: str) -> str | None:
    """从用户文字提取「我的答案」字母。"""
    t = (text or "").strip().replace("\u200b", "").replace("\ufeff", "")
    if not t:
        return None

    patterns = [
        r"我[的]?选(?:了|错)?[是为：:\s]*([A-Ea-e])",
        r"选了([A-Ea-e])",
        r"我的答案[是为：:\s]*([A-Ea-e])",
        r"我答([A-Ea-e])",
        r"([A-Ea-e])错了",
        r"选错([A-Ea-e])",
        r"^([A-Ea-e])$",
    ]
    for pat in patterns:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            return m.group(1).upper()

    return None


def parse_both_answers(text: str) -> tuple[str | None, str | None]:
    """解析「我的答案 X，正确答案 Y」类同时给出两个答案的文本。"""
    t = (text or "").strip()
    my: str | None = None
    correct: str | None = None

    combo_patterns = [
        r"我的答案[是为：:\s]*([A-Ea-e]).{0,20}?正确(?:答案)?[是为：:\s]*([A-Ea-e])",
        r"我选([A-Ea-e]).{0,20}?正确(?:答案)?[是为：:\s]*([A-Ea-e])",
        r"答案[是为：:\s]*([A-Ea-e]).{0,20}?正确(?:答案)?[是为：:\s]*([A-Ea-e])",
    ]
    for pat in combo_patterns:
        m = re.search(pat, t, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).upper(), m.group(2).upper()

    my = parse_my_answer(t)
    m2 = re.search(r"正确(?:答案)?[是为：:\s]*([A-Ea-e])", t, re.IGNORECASE)
    if m2:
        correct = m2.group(1).upper()
    return my, correct


def parse_claude_answer(text: str) -> tuple[str | None, str]:
    """从 Claude 解析块提取标准答案与解析。"""
    if not text:
        return None, ""

    correct: str | None = None
    for pat in (
        r"答案[：:]\s*([A-Ea-e])",
        r"^答案\s*([A-Ea-e])\s*$",
    ):
        m = re.search(pat, text, re.MULTILINE | re.IGNORECASE)
        if m:
            correct = m.group(1).upper()
            break

    explanation = ""
    m_exp = re.search(r"解析[：:]\s*(.+?)(?:\n记忆口诀|\n$)", text, re.DOTALL)
    if m_exp:
        explanation = m_exp.group(1).strip()
        explanation = re.sub(r"\s+", " ", explanation)[:200]

    return correct, explanation


def save_from_image(image_path: str, my_answer_hint: str | None = None) -> dict[str, Any]:
    try:
        from pmp_athena.image_processor import process_and_validate
    except ModuleNotFoundError:
        from image_processor import process_and_validate

    result = process_and_validate(
        image_path,
        run_ocr=True,
        validate_answer=True,
        auto_log_errors=False,
    )
    if not result.get("success"):
        return {"status": "error", "error": result.get("error", "处理失败")}

    validation = result.get("answer_validation") or {}
    if validation.get("screenshot_type") != "plain_question":
        return {
            "status": "not_plain_question",
            "screenshot_type": validation.get("screenshot_type", "unknown"),
        }

    extracted = validation.get("extracted") or {}
    pending = {
        "question": extracted.get("question"),
        "options": extracted.get("options") or {},
        "formatted_question": validation.get("formatted_question"),
        "knowledge_area": extracted.get("knowledge_area") or "综合",
        "my_answer": (my_answer_hint or "").upper() or None,
        "correct_answer": None,
        "explanation": None,
        "image_path": image_path,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save(pending)
    return {"status": "saved", "pending": pending}


def update_pending(**fields: Any) -> dict | None:
    pending = _load()
    if not pending:
        return None
    for k, v in fields.items():
        if v is not None:
            pending[k] = v
    _save(pending)
    return pending


def try_record(
    my_answer: str | None = None,
    correct_answer: str | None = None,
    explanation: str | None = None,
) -> dict[str, Any]:
    pending = _load()
    if not pending:
        return {"status": "no_pending"}

    my = (my_answer or pending.get("my_answer") or "").upper() or None
    correct = (correct_answer or pending.get("correct_answer") or "").upper() or None
    expl = explanation if explanation is not None else (pending.get("explanation") or "")

    if my:
        pending["my_answer"] = my
    if correct:
        pending["correct_answer"] = correct
    if explanation is not None:
        pending["explanation"] = expl
    _save(pending)

    if not my:
        return {
            "status": "waiting",
            "need": "my_answer",
            "question_preview": (pending.get("question") or "")[:50],
        }
    if not correct:
        return {
            "status": "waiting",
            "need": "correct_answer",
            "my_answer": my,
            "question_preview": (pending.get("question") or "")[:50],
        }

    if my == correct:
        clear_pending()
        return {
            "status": "correct",
            "my_answer": my,
            "correct_answer": correct,
        }

    try:
        from pmp_athena.record_answer import record_wrong_answer
    except ModuleNotFoundError:
        from record_answer import record_wrong_answer

    bank_q = _question_for_bank(pending)
    result = record_wrong_answer(
        question=bank_q,
        my_answer=my,
        correct_answer=correct,
        knowledge_area=pending.get("knowledge_area") or "综合",
        explanation=expl,
        source="screenshot",
        parsed_by="plain_followup",
    )
    clear_pending()
    return {
        "status": "logged",
        "my_answer": my,
        "correct_answer": correct,
        "knowledge_area": pending.get("knowledge_area") or "综合",
        "question_preview": (pending.get("question") or "")[:60],
        **result,
    }


def followup_user_text(text: str) -> dict[str, Any]:
    my, correct = parse_both_answers(text)
    if not my:
        my = parse_my_answer(text)
    return try_record(my_answer=my, correct_answer=correct)


def apply_claude_parse(text: str) -> dict[str, Any]:
    correct, explanation = parse_claude_answer(text)
    if not correct:
        return {"status": "no_answer_in_text"}
    update_pending(correct_answer=correct, explanation=explanation or None)
    return try_record(correct_answer=correct, explanation=explanation or None)


def format_log_reply(data: dict[str, Any]) -> str:
    if data.get("status") == "logged":
        q = data.get("question_preview") or "（题干）"
        return "\n".join([
            f"✅ 已录入错题 #{data['error_log_id']} [{data.get('knowledge_area', '综合')}]",
            f"📝 题干: {q}{'…' if len(q) >= 60 else ''}",
            f"❌ 你的答案: {data['my_answer']} → ✅ 正确答案: {data['correct_answer']}",
            "💾 已同步 question_bank.json + error_review_state.json",
        ])
    if data.get("status") == "correct":
        return f"✅ 你选的 {data['my_answer']} 正确，无需录入错题。"
    if data.get("status") == "waiting":
        if data.get("need") == "my_answer":
            return "📌 已识别纯题干。请告诉我你选了哪个选项（如：我选 A）。"
        return f"📌 已记录你的答案 {data.get('my_answer')}，等我给出解析后会自动入库（若答错）。"
    return ""


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="纯题干截图待答状态")
    sub = parser.add_subparsers(dest="command")

    p_save = sub.add_parser("save-from-image", help="从截图 OCR 并保存 pending")
    p_save.add_argument("image_path")
    p_save.add_argument("--my-answer", default=None)

    p_fu = sub.add_parser("followup", help="用户补充我的答案")
    p_fu.add_argument("--text", "-t", required=True)

    p_parse = sub.add_parser("apply-parse", help="从 Claude 解析结果提取标准答案")
    p_parse.add_argument("--text", "-t", required=True)

    sub.add_parser("status", help="是否有 pending")
    sub.add_parser("clear", help="清除 pending")

    p_try = sub.add_parser("try-record", help="尝试入库")
    p_try.add_argument("--my-answer", default=None)
    p_try.add_argument("--correct-answer", default=None)

    parser.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    out: dict[str, Any]
    if args.command == "save-from-image":
        out = save_from_image(args.image_path, args.my_answer)
    elif args.command == "followup":
        out = followup_user_text(args.text)
    elif args.command == "apply-parse":
        out = apply_claude_parse(args.text)
    elif args.command == "status":
        p = _load()
        out = {"status": "pending" if p else "empty", "pending": p}
    elif args.command == "clear":
        clear_pending()
        out = {"status": "cleared"}
    elif args.command == "try-record":
        out = try_record(my_answer=args.my_answer, correct_answer=args.correct_answer)
    else:
        parser.print_help()
        sys.exit(1)

    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        reply = format_log_reply(out)
        if reply:
            print(reply)
        else:
            print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
