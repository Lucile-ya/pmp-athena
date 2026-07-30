"""题干规范化 —— 入库时去掉 PDF/每日一练来源题号，去重用统一摘要。"""

from __future__ import annotations

import re

# 31. / 31、 / Q31. / 第31题：
_LEADING_NUMBER = re.compile(
    r"^(?:"
    r"(?:Q|q)?\d+[\.、．:：]\s*"
    r"|第\d+题[：:\.]?\s*"
    r"|Question\s*\d+[\.、．:：]?\s*"
    r")",
    re.IGNORECASE,
)


def normalize_question_text(text: str) -> str:
    """入库前规范化题干：去首尾空白、去掉来源题号（保留 A/B/C/D 选项）。"""
    if not text:
        return ""

    q = text.strip()

    # 只剥离开头题号，选项里的 "A." 不动
    while True:
        new_q = _LEADING_NUMBER.sub("", q, count=1).lstrip()
        if new_q == q:
            break
        q = new_q

    return q


def question_dedup_key(text: str, length: int = 50) -> str:
    """去重键：规范化后取前 N 字（与 CLAUDE.md 50 字规则一致）。"""
    return normalize_question_text(text)[:length]
