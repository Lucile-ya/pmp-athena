#!/usr/bin/env python3
"""
App / 培训机构批量题：一次发多题 + 答案串 → 收录 → 补录标准答案后判卷入库。

用法:
  python pmp_athena/daily_practice.py batch --stdin
  python pmp_athena/daily_practice.py batch-update 41 --correct-answer C --explanation "..."
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import NOTES_DIR
    from pmp_athena.daily_practice import _guess_knowledge_area
    from pmp_athena.record_answer import record_correct_answer, record_wrong_answer
    from pmp_athena.utils.question_text import normalize_question_text, question_dedup_key
except ModuleNotFoundError:
    from config import NOTES_DIR
    from daily_practice import _guess_knowledge_area
    from record_answer import record_correct_answer, record_wrong_answer
    from utils.question_text import normalize_question_text, question_dedup_key

BATCH_STATE_PATH = NOTES_DIR / "batch_practice_state.json"
_BANK_PATH = NOTES_DIR / "question_bank.json"

_OPTION_LINE = re.compile(r"^([A-D])[\.．、:：]\s*(.*)$", re.I)
_ANSWER_TAIL = re.compile(
    r"(?:我的答案(?:是)?|我选(?:了)?)[：:\s]*([A-E]+)\s*$",
    re.I | re.M,
)
_BATCH_UPDATE = re.compile(
    r"更新\s*#?(\d+)\s*题",
    re.I,
)
_BATCH_UPDATE_ANS = re.compile(
    r"正确答案[是为：:\s]*([A-E])",
    re.I,
)
_BATCH_UPDATE_EXPL = re.compile(
    r"解析[：:\s]*(.+)$",
    re.I | re.S,
)
_PER_Q_ANS = re.compile(r"^答案[：:\s]*([A-E])\s*$", re.I | re.M)
_PER_Q_EXPL = re.compile(r"^解析[：:\s]*(.*)", re.I | re.M)
_PREFIX_STRIP = re.compile(r"^(?:早餐题|早题)[：:\s]*", re.I)
_Q_BLOCK_SPLIT = re.compile(r"(?=(?:^|\n)\d+[\.．]\s*)")


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


def _load_batch_state() -> dict[str, Any]:
    return _load_json(BATCH_STATE_PATH, {"by_num": {}, "sessions": []})


def _save_batch_state(state: dict[str, Any]) -> None:
    _save_json(BATCH_STATE_PATH, state)


def _read_bank() -> list[dict]:
    return _load_json(_BANK_PATH, [])


def _write_bank(data: list[dict]) -> None:
    _save_json(_BANK_PATH, data)


def _format_question_text(stem: str, options: dict[str, str]) -> str:
    lines = [normalize_question_text(stem)]
    for key in sorted(options):
        lines.append(f"{key}. {options[key]}")
    return "\n".join(lines)


def extract_answer_string(text: str) -> str | None:
    m = _ANSWER_TAIL.search(text.strip())
    return m.group(1).upper() if m else None


def _normalize_input(text: str) -> str:
    return _PREFIX_STRIP.sub("", text.strip())


def _parse_question_block(block: str) -> dict[str, Any] | None:
    block = block.strip()
    if not block:
        return None
    m = re.match(r"^(\d+)[\.．]\s*", block)
    if not m:
        return None
    num = int(m.group(1))
    rest = block[m.end() :].strip()

    stem_parts: list[str] = []
    options: dict[str, str] = {}
    current: str | None = None
    correct_answer = ""
    explanation = ""

    for line in rest.split("\n"):
        line = line.strip()
        if not line:
            continue
        am = _PER_Q_ANS.match(line)
        if am:
            current = None
            correct_answer = am.group(1).upper()
            continue
        em = _PER_Q_EXPL.match(line)
        if em:
            current = None
            explanation = em.group(1).strip()
            continue
        om = _OPTION_LINE.match(line)
        if om:
            current = om.group(1).upper()
            options[current] = om.group(2).strip()
        elif current:
            options[current] += " " + line
        else:
            stem_parts.append(line)

    if len(options) < 2:
        return None
    stem = " ".join(stem_parts).strip()
    return {
        "num": num,
        "stem": stem,
        "options": options,
        "question": _format_question_text(stem, options),
        "correct_answer": correct_answer,
        "explanation": explanation,
    }


def parse_breakfast_questions(text: str) -> list[dict[str, Any]]:
    """解析「早餐题」格式：每题块内含 答案：X 与 解析：…"""
    raw = _normalize_input(text)
    ans_m = _ANSWER_TAIL.search(raw)
    body = raw[: ans_m.start()].strip() if ans_m else raw

    items: list[dict[str, Any]] = []
    for block in _Q_BLOCK_SPLIT.split(body):
        q = _parse_question_block(block)
        if q and q.get("correct_answer"):
            items.append(q)
    return items


def parse_batch_questions(text: str) -> list[dict[str, Any]]:
    """解析 41.题干 A.xx B.xx ... 格式。"""
    raw = _normalize_input(text)
    ans_m = _ANSWER_TAIL.search(raw)
    body = raw[: ans_m.start()].strip() if ans_m else raw

    items: list[dict[str, Any]] = []
    for block in _Q_BLOCK_SPLIT.split(body):
        q = _parse_question_block(block)
        if q:
            items.append(q)
    return items


def _resolve_my_answers(
    text: str,
    questions: list[dict[str, Any]],
    state: dict[str, Any],
) -> str | None:
    """从文末答案串或 batch_state 还原我的作答。"""
    tail = extract_answer_string(text)
    if tail and len(tail) == len(questions):
        return tail
    by_num = state.get("by_num", {})
    if len(questions) >= 2 and all(str(q["num"]) in by_num for q in questions):
        return "".join(by_num[str(q["num"])].get("my_answer", "") for q in questions)
    return None


def _find_bank_by_dedup(stem: str) -> dict | None:
    key = question_dedup_key(stem, 30)
    for rec in reversed(_read_bank()):
        if question_dedup_key(rec.get("question", ""), 30) == key:
            return rec
    return None


def _add_bank_pending(
    q: dict[str, Any],
    my_answer: str,
    *,
    correct_answer: str = "",
    is_correct: bool | None = None,
) -> dict:
    data = _read_bank()
    next_id = max((r.get("id", 0) for r in data), default=0) + 1
    area = _guess_knowledge_area(q["stem"])
    record = {
        "id": next_id,
        "date": date.today().isoformat(),
        "timestamp": date.today().isoformat(),
        "is_correct": is_correct,
        "question": q["question"],
        "my_answer": my_answer.upper(),
        "correct_answer": correct_answer.upper() if correct_answer else "",
        "knowledge_area": area,
        "explanation": "",
        "parsed_by": "batch_practice.py",
        "source": "batch_practice",
        "times_seen": 1,
        "last_review_date": date.today().isoformat(),
        "error_log_id": None,
        "batch_num": q["num"],
    }
    data.append(record)
    _write_bank(data)
    return record


def _sync_wrong_to_error_log(record: dict, explanation: str = "") -> int | None:
    rec = record_wrong_answer(
        question=record["question"],
        my_answer=record["my_answer"],
        correct_answer=record["correct_answer"],
        knowledge_area=record.get("knowledge_area", "综合"),
        explanation=explanation,
        source="batch_practice",
        parsed_by="batch_practice.py",
    )
    bank_id = record["id"]
    error_id = rec.get("error_log_id") or rec.get("error_id")
    data = _read_bank()
    for r in data:
        if r.get("id") == bank_id:
            r["error_log_id"] = error_id
            r["is_correct"] = False
            if explanation:
                r["explanation"] = explanation
            break
    _write_bank(data)
    return error_id


def batch_ingest(text: str, *, answer_key: str | None = None) -> dict[str, Any]:
    """
    批量收录/判卷。
    - 无标准答案：收录待补录
    - 有标准答案（--key 或早餐题逐题答案）：立即判卷
    """
    breakfast = parse_breakfast_questions(text)
    if len(breakfast) >= 2:
        return _batch_ingest_with_solutions(text, breakfast, answer_key=answer_key)

    questions = parse_batch_questions(text)
    if not questions:
        return {"status": "error", "text": "⚠️ 未能解析题目，请确认格式：41.题干\\nA.xx\\n...\\n我的答案是：CCCAB"}

    answers = extract_answer_string(text)
    if not answers:
        return {"status": "error", "text": "⚠️ 未找到答案串，请在末尾加：我的答案是：CCCAB"}

    if len(answers) != len(questions):
        return {
            "status": "error",
            "text": f"⚠️ 题目 {len(questions)} 道，答案 {len(answers)} 个，数量不一致。",
        }

    key = answer_key.upper().replace(" ", "") if answer_key else None
    return _batch_grade_questions(text, questions, answers, answer_key=key)


def _batch_ingest_with_solutions(
    text: str,
    questions: list[dict[str, Any]],
    *,
    answer_key: str | None = None,
) -> dict[str, Any]:
    state = _load_batch_state()
    my_answers = answer_key.upper().replace(" ", "") if answer_key else _resolve_my_answers(text, questions, state)

    if not my_answers:
        by_num: dict[str, Any] = state.setdefault("by_num", {})
        for q in questions:
            by_num[str(q["num"])] = {
                "num": q["num"],
                "bank_id": None,
                "my_answer": "",
                "correct_answer": q.get("correct_answer", ""),
                "explanation": q.get("explanation", ""),
                "pending": True,
                "question": q["question"],
            }
        state["by_num"] = by_num
        _save_batch_state(state)
        nums = "、".join(str(q["num"]) for q in questions)
        return {
            "status": "ok",
            "total": len(questions),
            "text": (
                f"📋 已解析早餐题 {len(questions)} 道（#{nums}）标准答案+解析\n"
                "⏳ 请补发你的作答，末尾加：我的答案是：XXX"
            ),
        }

    if len(my_answers) != len(questions):
        return {
            "status": "error",
            "text": f"⚠️ 题目 {len(questions)} 道，你的答案 {len(my_answers)} 个，数量不一致。",
        }

    return _batch_grade_questions(
        text,
        questions,
        my_answers,
        answer_key="".join(q.get("correct_answer", "") for q in questions),
        explanations=[q.get("explanation", "") for q in questions],
    )


def _batch_grade_questions(
    text: str,
    questions: list[dict[str, Any]],
    my_answer_str: str,
    *,
    answer_key: str | None = None,
    explanations: list[str] | None = None,
) -> dict[str, Any]:
    """统一判卷入库。"""
    key = answer_key.upper().replace(" ", "") if answer_key else None
    if not key:
        key = None
    elif len(key) != len(questions):
        return {
            "status": "error",
            "text": f"⚠️ 标准答案 {len(key)} 个，与题目数 {len(questions)} 不一致。",
        }

    state = _load_batch_state()
    by_num: dict[str, Any] = state.setdefault("by_num", {})
    correct_nums: list[int] = []
    wrong_nums: list[int] = []
    pending_nums: list[int] = []
    skipped: list[int] = []

    for idx, (q, my_ans) in enumerate(zip(questions, my_answer_str)):
        num = q["num"]
        std_ans = key[idx] if key else ""
        expl = (explanations[idx] if explanations and idx < len(explanations) else "") or q.get("explanation", "")

        existing = _find_bank_by_dedup(q["stem"])
        if existing and existing.get("my_answer") == my_ans.upper() and existing.get("correct_answer") == std_ans:
            by_num[str(num)] = {
                "bank_id": existing["id"],
                "my_answer": my_ans.upper(),
                "correct_answer": std_ans,
                "pending": False,
            }
            skipped.append(num)
            continue

        if key:
            is_ok = my_ans.upper() == std_ans
            if is_ok:
                rec = record_correct_answer(
                    question=q["question"],
                    my_answer=my_ans,
                    correct_answer=std_ans,
                    knowledge_area=_guess_knowledge_area(q["stem"]),
                    explanation=expl,
                    source="batch_practice",
                    parsed_by="batch_practice.py",
                )
                correct_nums.append(num)
            else:
                rec = record_wrong_answer(
                    question=q["question"],
                    my_answer=my_ans,
                    correct_answer=std_ans,
                    knowledge_area=_guess_knowledge_area(q["stem"]),
                    explanation=expl[:200] if expl else "",
                    source="batch_practice",
                    parsed_by="batch_practice.py",
                )
                wrong_nums.append(num)
            bank_id = rec.get("bank_id") or rec.get("id")
            by_num[str(num)] = {
                "bank_id": bank_id,
                "my_answer": my_ans.upper(),
                "correct_answer": std_ans,
                "pending": False,
            }
        else:
            rec = _add_bank_pending(q, my_ans, is_correct=None)
            pending_nums.append(num)
            by_num[str(num)] = {
                "bank_id": rec["id"],
                "my_answer": my_ans.upper(),
                "correct_answer": "",
                "pending": True,
            }

    state.setdefault("sessions", []).append(
        {
            "date": date.today().isoformat(),
            "count": len(questions),
            "answers": my_answer_str,
            "has_key": bool(key),
        }
    )
    state["by_num"] = by_num
    _save_batch_state(state)

    lines = [f"📋 批量{'判卷' if key else '收录'}完成（{len(questions)} 题）"]
    lines.append(f"你的答案：{my_answer_str}")
    if key:
        if wrong_nums:
            lines.append(f"❌ 错题：{'、'.join(str(n) for n in wrong_nums)}（{len(wrong_nums)} 题）")
        if correct_nums:
            lines.append(f"✅ 正确：{'、'.join(str(n) for n in correct_nums)}（{len(correct_nums)} 题）")
        lines.append("💾 错题已同步 question_bank + error_log + error_review_state")
    else:
        lines.append("⏳ 标准答案待补录（发：更新41题，正确答案是 C，解析：xxx）")
        lines.append("💾 做题记录已写入 question_bank（待判卷）")
    if skipped:
        lines.append(f"📌 已存在同题同答，跳过：{'、'.join(str(n) for n in skipped)}")

    return {
        "status": "ok",
        "total": len(questions),
        "correct": correct_nums,
        "wrong": wrong_nums,
        "pending": pending_nums,
        "text": "\n".join(lines),
    }


def batch_complete_pending(text: str) -> dict[str, Any] | None:
    """仅发「我的答案是：XXX」且 state 中已有待判早餐题时，补全判卷。"""
    my_answers = extract_answer_string(text)
    if not my_answers or re.search(r"(?:^|\n)\d+[\.．]", text.strip()):
        return None

    state = _load_batch_state()
    by_num = state.get("by_num", {})
    pending_items = [
        (int(k), v)
        for k, v in by_num.items()
        if v.get("correct_answer") and v.get("pending") and not v.get("bank_id")
    ]
    pending_items.sort(key=lambda x: x[0])
    if len(pending_items) < 2:
        return None

    questions: list[dict[str, Any]] = []
    explanations: list[str] = []
    for num_int, entry in pending_items:
        qtext = entry.get("question") or ""
        if not qtext:
            return None
        lines = qtext.split("\n")
        stem = lines[0]
        options: dict[str, str] = {}
        for line in lines[1:]:
            om = _OPTION_LINE.match(line.strip())
            if om:
                options[om.group(1).upper()] = om.group(2).strip()
        questions.append(
            {
                "num": entry.get("num") or num_int,
                "stem": stem,
                "options": options,
                "question": qtext,
                "correct_answer": entry["correct_answer"],
                "explanation": entry.get("explanation", ""),
            }
        )
        explanations.append(entry.get("explanation", ""))

    if len(my_answers) != len(questions):
        return {
            "status": "error",
            "text": f"⚠️ 待判 {len(questions)} 题，答案串 {len(my_answers)} 个，数量不一致。",
        }

    return _batch_grade_questions(
        text,
        questions,
        my_answers,
        answer_key="".join(q["correct_answer"] for q in questions),
        explanations=explanations,
    )


def batch_update(
    num: int,
    *,
    correct_answer: str,
    explanation: str = "",
) -> dict[str, Any]:
    """补录标准答案 + 解析，重新判卷并同步错题本。"""
    try:
        from pmp_athena.question_bank import QuestionBank
    except ModuleNotFoundError:
        from question_bank import QuestionBank

    state = _load_batch_state()
    entry = state.get("by_num", {}).get(str(num))
    if not entry:
        return {
            "status": "error",
            "text": f"⚠️ 未找到 #{num} 的批量做题记录。请先发送题目+答案串。",
        }

    bank_id = entry.get("bank_id")
    qb = QuestionBank()
    record = qb.get_by_id(bank_id)
    if not record:
        return {"status": "error", "text": f"⚠️ 题库 #{bank_id} 不存在。"}

    ca = correct_answer.strip().upper()
    my = entry.get("my_answer") or record.get("my_answer", "")
    is_ok = my.upper() == ca

    qb.update(
        bank_id,
        correct_answer=ca,
        explanation=explanation.strip(),
        is_correct=is_ok,
    )
    record = qb.get_by_id(bank_id) or record

    if is_ok:
        msg = f"✅ #{num} 标准答案 {ca}，判卷：正确"
    else:
        if not record.get("error_log_id"):
            eid = _sync_wrong_to_error_log(record, explanation)
            msg = f"❌ #{num} 你的 {my} → 正确 {ca}，已入库错题 #{eid}"
        else:
            msg = f"❌ #{num} 你的 {my} → 正确 {ca}（错题 #{record['error_log_id']} 已存在）"
        if explanation:
            msg += f"\n解析: {explanation[:120]}"

    entry["correct_answer"] = ca
    entry["pending"] = False
    state["by_num"][str(num)] = entry
    _save_batch_state(state)

    return {"status": "ok", "num": num, "is_correct": is_ok, "text": msg}


def parse_batch_update_command(text: str) -> dict[str, Any] | None:
    """从自然语言解析：更新41题，正确答案是 B，解析：xxx"""
    t = text.strip()
    m = _BATCH_UPDATE.search(t)
    if not m:
        return None
    num = int(m.group(1))
    am = _BATCH_UPDATE_ANS.search(t)
    if not am:
        return None
    em = _BATCH_UPDATE_EXPL.search(t)
    expl = em.group(1).strip() if em else ""
    return {
        "num": num,
        "correct_answer": am.group(1).upper(),
        "explanation": expl,
    }


def is_breakfast_question_input(text: str) -> bool:
    return len(parse_breakfast_questions(text)) >= 2


def is_batch_question_input(text: str) -> bool:
    t = _normalize_input(text)
    if is_breakfast_question_input(t):
        return True
    if not extract_answer_string(t):
        return False
    qs = parse_batch_questions(t)
    return len(qs) >= 2


def is_batch_update_input(text: str) -> bool:
    return parse_batch_update_command(text) is not None
