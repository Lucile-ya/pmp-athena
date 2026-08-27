#!/usr/bin/env python3
"""希赛英文模考 PDF 解析回归。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pmp_athena.hisai_mock_parser import (  # noqa: E402
    load_hisai_mock_from_pdfs,
    parse_hisai_answer_key,
    parse_hisai_questions,
)

SAMPLE_Q = """
1、A project team is faced with deciding on the next steps.
A-Democratic
B-Autocratic
C-Free rein
D-Smoothing
一个项目团队正面临决定下一步行动。
A. 民主型
B. 专制型
C. 放任型
D. 缓冲型
2、Which of the following is true?
A-One
B-Two
C-Three
D-Four
"""

SAMPLE_A = """
1 C 2 B 11 ACEF 88 AE
"""


def test_parse_questions_basic() -> None:
    qs = parse_hisai_questions(SAMPLE_Q)
    assert len(qs) == 2
    assert qs[0]["num"] == 1
    assert set(qs[0]["options"].keys()) == {"A", "B", "C", "D"}
    assert "Democratic" in qs[0]["options"]["A"]


def test_parse_spaced_marker() -> None:
    text = SAMPLE_Q.replace("1、", "1 、 ", 1)
    qs = parse_hisai_questions(text)
    assert any(q["num"] == 1 for q in qs)


def test_parse_answer_key_grid() -> None:
    ans = parse_hisai_answer_key(SAMPLE_A)
    assert ans[1]["answer"] == "C"
    assert ans[11]["answer"] == "ACEF"
    assert ans[88]["answer"] == "AE"


def test_hisai_2609_pdf_if_present() -> None:
    q_pdf = _ROOT / "pmp_notes" / "模考" / "PMP®模考题-2609.pdf"
    a_pdf = _ROOT / "pmp_notes" / "模考" / "PMP®模考题（参考答案）-2609.pdf"
    if not q_pdf.exists() or not a_pdf.exists():
        print("⏭️  SKIP hisai2609 mock: PDF 不存在")
        return
    qs = load_hisai_mock_from_pdfs(q_pdf, a_pdf)
    assert len(qs) == 180
    assert all(q.get("correct_answer") for q in qs)
    assert all(len(q.get("options") or {}) >= 4 for q in qs)
    multi = [q for q in qs if q.get("question_type") == "multi"]
    assert len(multi) >= 10


def main() -> int:
    tests = [
        test_parse_questions_basic,
        test_parse_spaced_marker,
        test_parse_answer_key_grid,
        test_hisai_2609_pdf_if_present,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"✅ {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"❌ {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"❌ {fn.__name__}: {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
