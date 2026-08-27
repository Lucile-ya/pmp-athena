#!/usr/bin/env python3
"""希赛 PMP® 英文模考 PDF 解析（题目 + 参考答案网格）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_MULTI_KW = (
    "choose two",
    "choose three",
    "choose four",
    "choose 2",
    "choose 3",
    "choose 4",
    "选两项",
    "选三项",
    "选四项",
    "哪两个",
    "哪三个",
    "哪四项",
)

_OPTION_LINE = re.compile(r"^([A-F])[-\.、:：]\s*(.+)$", re.I)
_QUESTION_MARKER = re.compile(r"(?:^|\n)(\d{1,3})\s*、\s*")


def normalize_hisai_question_text(text: str) -> str:
    """归一化题号顿号周围的空格（如 `31 、 A`）。"""
    text = re.sub(r"(\d{1,3})\s+、\s*", r"\n\1、", text)
    return text


def parse_hisai_answer_key(text: str) -> dict[int, dict[str, str]]:
    """从参考答案 PDF 提取 {题号: {answer, question_type}}。"""
    answers: dict[int, dict[str, str]] = {}
    for line in text.splitlines():
        tokens = line.split()
        i = 0
        while i < len(tokens):
            if re.fullmatch(r"\d{1,3}", tokens[i]):
                qnum = int(tokens[i])
                if 1 <= qnum <= 180 and i + 1 < len(tokens) and re.fullmatch(r"[A-F]+", tokens[i + 1]):
                    raw = tokens[i + 1].upper()
                    letters = "".join(sorted(c for c in raw if c in "ABCDEF"))
                    answers[qnum] = {
                        "answer": letters,
                        "question_type": "multi" if len(letters) > 1 else "single",
                    }
                    i += 2
                    continue
            i += 1
    return answers


def _is_multichoice(stem: str, opt_count: int, answer_len: int) -> bool:
    low = stem.lower()
    if any(k in low for k in _MULTI_KW):
        return True
    if answer_len > 1:
        return True
    if opt_count > 4:
        return True
    return False


def parse_hisai_questions(text: str) -> list[dict[str, Any]]:
    """从题目 PDF 提取题目列表。"""
    text = normalize_hisai_question_text(text)
    # 去掉卷头说明
    text = re.sub(
        r"^PMP.*?说明：.*?(?=(?:^|\n)\d{1,3}\s*、)",
        "",
        text,
        count=1,
        flags=re.S,
    )

    markers = list(_QUESTION_MARKER.finditer(text))
    if not markers:
        return []

    questions: list[dict[str, Any]] = []
    seen_nums: set[int] = set()

    for i, m in enumerate(markers):
        num = int(m.group(1))
        if num in seen_nums or num < 1 or num > 180:
            continue
        start = m.start()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        block = text[start:end].strip()
        block = re.sub(r"^\d{1,3}\s*、\s*", "", block, count=1)

        stem_en: list[str] = []
        stem_cn: list[str] = []
        opts: dict[str, str] = {}
        phase = "en"

        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            om = _OPTION_LINE.match(line)
            if om:
                letter = om.group(1).upper()
                if letter not in opts:
                    opts[letter] = om.group(2).strip()
                if re.search(r"[\u4e00-\u9fff]", om.group(2)):
                    phase = "cn"
                continue
            if re.search(r"[\u4e00-\u9fff]{4,}", line):
                phase = "cn"
                stem_cn.append(line)
            elif phase == "en":
                stem_en.append(line)

        stem = re.sub(r"\s+", " ", " ".join(stem_en + stem_cn)).strip()
        if not stem or len(opts) < 4:
            continue

        seen_nums.add(num)
        questions.append(
            {
                "num": num,
                "stem": stem[:800],
                "options": opts,
                "question_type": "single",
            }
        )

    questions.sort(key=lambda q: q["num"])
    return questions


def load_hisai_mock_from_pdfs(question_pdf: Path, answer_pdf: Path | None) -> list[dict[str, Any]]:
    """加载并合并希赛英文模考题目 + 答案。"""
    import pdfplumber

    with pdfplumber.open(str(question_pdf)) as pdf:
        q_text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    questions = parse_hisai_questions(q_text)
    if not questions:
        raise ValueError(f"无法解析题目 PDF: {question_pdf.name}")

    answers: dict[int, dict[str, str]] = {}
    if answer_pdf and answer_pdf.exists():
        with pdfplumber.open(str(answer_pdf)) as pdf:
            a_text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        answers = parse_hisai_answer_key(a_text)

    merged: list[dict[str, Any]] = []
    for q in questions:
        num = q["num"]
        ans = answers.get(num, {})
        correct = ans.get("answer", "")
        qtype = ans.get("question_type") or q.get("question_type", "single")
        if _is_multichoice(q["stem"], len(q["options"]), len(correct)):
            qtype = "multi"
        merged.append(
            {
                "num": num,
                "stem": q["stem"],
                "options": q["options"],
                "correct_answer": correct,
                "explanation": "",
                "question_type": qtype,
                "knowledge_area": "综合",
            }
        )
    return merged
