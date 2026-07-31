#!/usr/bin/env python3
"""每日一练 PDF 解析回归（题头 [单选] / 水印行）。"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pmp_athena.daily_practice import (  # noqa: E402
    _parse_questions,
    _strip_question_header,
    load_questions_for_date,
)

SAMPLE_BLOCK = """
2．【问答题】 [单选] 项目经理面临的一个关键挑战是各个团队成员缺乏纪律，他们无法集中精
力来实现项目目标。项目经部理应该做些什么来克服这一挑战？A key challenge
A：单独会见每个团队成员 Meet separately
B：联系项目发起人 Approach sponsor
C：向团队解释 Explain
D：给不同的团队分配多个经理 Delegate
"""

SAMPLE_Q3 = """
3．【问答题】 [单选] A公司委派内部员工任项目经理并购B公司，但是这位项目经理之前在B
内部资料
公司工作过。项目经理接下来如何开展工作？Company A assigns
A：收集数据 Collect
B：开展非正式沟通 Informal
C：进行定量分析 Quantitative
D：通过蒙特卡洛分析 Monte Carlo
"""


def test_strip_header_preserves_stem() -> None:
    line = "2．【问答题】 [单选] 项目经理面临的一个关键挑战"
    got = _strip_question_header(line)
    assert got.startswith("项目经理面临"), got


def test_parse_block_not_truncated() -> None:
    qs = _parse_questions(SAMPLE_BLOCK)
    assert len(qs) == 1
    stem = qs[0]["stem"]
    assert "项目经理面临的一个关键挑战" in stem
    assert "克服这一挑战" in stem


def test_watermark_line_skipped() -> None:
    qs = _parse_questions(SAMPLE_Q3)
    assert len(qs) == 1
    stem = qs[0]["stem"]
    assert "A公司" in stem and "B公司" in stem
    assert "内部资料" not in stem


def test_july16_pdf_if_present() -> None:
    pdf = _ROOT / "pmp_notes" / "每日一练" / "2609每日一练7月16日.pdf"
    if not pdf.exists():
        print("⏭️  SKIP july16 pdf: 文件不存在")
        return
    qs = load_questions_for_date(date(2026, 7, 16))
    assert len(qs) == 10
    q1 = qs[0]["stem"]
    assert q1.startswith("项目经理正在管理一个新的开发计划")
    q3 = qs[2]["stem"]
    assert "A公司" in q3 and "B公司" in q3


def test_option_not_watermark_tail() -> None:
    from pmp_athena.daily_practice import _clean_option

    raw = (
        "确保该干系人从团队成员那里收到所有必要的信息 "
        "Ensure that the stakeholder receives all requiredinformation fromteammembers "
        "部 内 育 教 迹"
    )
    got = _clean_option(raw)
    assert got.startswith("确保该干系人"), got
    assert "部 内" not in got


def test_july17_pdf_if_present() -> None:
    pdf = _ROOT / "pmp_notes" / "每日一练" / "2609每日一练7月17日.pdf"
    if not pdf.exists():
        print("⏭️  SKIP july17 pdf: 文件不存在")
        return
    qs = load_questions_for_date(date(2026, 7, 17))
    assert len(qs) == 10
    q1 = qs[0]
    assert "一个新的干系人" in q1["stem"]
    assert q1["options"]["D"].startswith("确保该干系人")
    q4 = qs[3]
    assert "经验教训登记册" in q4["options"]["A"]


def test_july20_pdf_if_present() -> None:
    pdf = _ROOT / "pmp_notes" / "每日一练" / "2609每日一练7月20日.pdf"
    if not pdf.exists():
        print("⏭️  SKIP july20 pdf: 文件不存在")
        return
    qs = load_questions_for_date(date(2026, 7, 20))
    assert len(qs) == 10
    assert "（RACI）" in qs[9]["options"]["A"]
    assert "（DoD）" in qs[3]["options"]["C"]
    assert not qs[6]["options"]["A"].endswith("育")


def test_grade_batch() -> None:
    from pmp_athena.daily_practice import _clear_state, _save_state, grade_answers

    _clear_state()
    _save_state(
        {
            "mode": "fixed",
            "date": "2026-07-31",
            "label": "7月31日",
            "questions": [
                {
                    "index": i + 1,
                    "num": i + 1,
                    "stem": f"Q{i+1}",
                    "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                    "correct_answer": c,
                    "explanation": "",
                    "knowledge_area": "综合",
                    "question_type": "single",
                }
                for i, c in enumerate(["C", "A"])
            ],
            "current_index": 0,
            "correct_count": 0,
            "wrong_count": 0,
            "wrong_items": [],
        }
    )
    r = grade_answers("AC")
    assert r.get("done"), r
    assert "批量判卷" in r.get("text", "")
    _clear_state()


def main() -> int:
    tests = [
        test_strip_header_preserves_stem,
        test_parse_block_not_truncated,
        test_watermark_line_skipped,
        test_option_not_watermark_tail,
        test_grade_batch,
        test_july16_pdf_if_present,
        test_july17_pdf_if_present,
        test_july20_pdf_if_present,
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
