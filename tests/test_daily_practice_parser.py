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
    _parse_answers,
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


SAMPLE_Q5_ORPHAN_C = """
5.【单选题】What should the project manager do first?项目经理应该先做什么?
A. Start developing a business case.开始制定一个商业论证。
B. Start a strengths, weaknesses, opportunities and threats (SWOT).开始进行 SWOT 分析。
Engage stakeholders and allocate resources.让干系人参与进来并分配资源
D. Gather requirements from stakeholders.从干系人那里收集需求
"""


def test_recover_orphan_option_c() -> None:
    qs = _parse_questions(SAMPLE_Q5_ORPHAN_C)
    assert len(qs) == 1
    opts = qs[0]["options"]
    assert set(opts.keys()) >= {"A", "B", "C", "D"}
    assert "干系人" in opts["C"]


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


SAMPLE_DUNHAO = """
1、【单选题】在部署一个企业资源管理系统期间，财务总监辞职。项目经理应该做什么？
A、发布更新干系人登记册的变更请求
B、将项目文档发送给该财务总监
C、请新财务总监更新项目成本管理计划
D、与新的财务总监开会了解参与情况
答案：A
解析：新干系人先更新登记册。
2、【单选题】项目经理应该做什么？
A、执行根本原因分析
B、执行干系人分析
C、执行假设条件和制约因素分析
D、执行数据分析
答案：C
解析：先审查制约因素。
"""


def test_parse_chinese_dunhao_question_numbers() -> None:
    qs = _parse_questions(SAMPLE_DUNHAO)
    assert len(qs) == 2, [q["num"] for q in qs]
    assert qs[0]["stem"].startswith("在部署一个企业资源管理系统期间")
    assert qs[0]["options"]["D"].startswith("与新的财务总监开会")
    ans = _parse_answers(SAMPLE_DUNHAO)
    assert ans[1]["answer"] == "A"
    assert ans[2]["answer"] == "C"


def test_oct22_pdf_if_present() -> None:
    folder = _ROOT / "pmp_notes" / "每日一练"
    if not any("10月22日" in f.name and "答案" not in f.name for f in folder.glob("*.pdf")):
        print("⏭️  SKIP oct22 pdf: 文件不存在")
        return
    qs = load_questions_for_date(date(2026, 10, 22))
    assert len(qs) == 10, len(qs)
    assert all(len(q.get("options") or {}) >= 4 for q in qs)
    assert all(q.get("correct_answer") for q in qs)
    assert "财务总监" in qs[0]["stem"]


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


def test_qiji_2609_mock_if_present() -> None:
    q_pdf = _ROOT / "pmp_notes" / "模考" / "2609期PMP模考一（8月22日）-骐迹教育.pdf"
    a_pdf = _ROOT / "pmp_notes" / "模考" / "2609期PMP模考一（8月22日）答案和解析-骐迹教育.pdf"
    if not q_pdf.exists() or not a_pdf.exists():
        print("⏭️  SKIP qiji2609 mock: PDF 不存在")
        return
    from pmp_athena.daily_practice import load_questions_from_pdf

    qs = load_questions_from_pdf(q_pdf, a_pdf)
    assert len(qs) == 180, len(qs)
    assert all(q.get("correct_answer") for q in qs)
    assert all(len(q.get("options") or {}) >= 4 for q in qs)


def test_qiji_2609_mock2_if_present() -> None:
    q_pdf = _ROOT / "pmp_notes" / "模考" / "2609期PMP模考二（8月30日）骐迹教育.pdf"
    a_pdf = _ROOT / "pmp_notes" / "模考" / "2609期PMP模考二（8月30日）答案和解析-骐迹教育.pdf"
    if not q_pdf.exists() or not a_pdf.exists():
        print("⏭️  SKIP qiji2609 mock2: PDF 不存在")
        return
    from pmp_athena.daily_practice import load_questions_from_pdf

    qs = load_questions_from_pdf(q_pdf, a_pdf)
    assert len(qs) == 180, len(qs)
    assert all(q.get("correct_answer") for q in qs)
    assert all(len(q.get("options") or {}) >= 4 for q in qs)


def _silence_recording(monkey_mod):
    original = monkey_mod._record_answer
    monkey_mod._record_answer = lambda *a, **k: None
    return original


def test_grade_batch() -> None:
    from pmp_athena import daily_practice as dp
    from pmp_athena.daily_practice import _clear_state, _save_state, grade_answers

    original = _silence_recording(dp)
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
    try:
        r = grade_answers("AC")
        assert r.get("done"), r
        assert "本批判卷" in r.get("text", "")
    finally:
        dp._record_answer = original
        _clear_state()


def test_daily_batch_waits_for_five() -> None:
    from pmp_athena import daily_practice as dp
    from pmp_athena.daily_practice import _clear_state, _save_state, grade_answers

    original = _silence_recording(dp)
    _clear_state()
    _save_state(
        {
            "mode": "fixed",
            "date": "2026-10-22",
            "label": "10月22日",
            "questions": [
                {
                    "index": i + 1,
                    "num": i + 1,
                    "stem": f"题干{i+1}",
                    "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                    "correct_answer": "A",
                    "explanation": "解析不应出现在出题里",
                    "knowledge_area": "综合",
                    "question_type": "single",
                }
                for i in range(10)
            ],
            "current_index": 0,
            "correct_count": 0,
            "wrong_count": 0,
            "wrong_items": [],
        }
    )
    try:
        too_few = grade_answers("A")
        assert too_few.get("status") == "error", too_few
        assert "期望 5 个答案" in too_few.get("text", "")
        first = grade_answers("ABCDA")
        assert first.get("status") == "question", first
        assert "本批判卷" in first.get("text", "")
        assert "Q6" in first.get("text", "")
        assert "解析不应出现在出题里" not in first.get("text", "").split("📦")[-1]
    finally:
        dp._record_answer = original
        _clear_state()


def test_start_oct22_first_batch_if_present() -> None:
    folder = _ROOT / "pmp_notes" / "每日一练"
    if not any("10月22日" in f.name and "答案" not in f.name for f in folder.glob("*.pdf")):
        print("⏭️  SKIP oct22 start: 文件不存在")
        return
    from pmp_athena.daily_practice import _clear_state, start_session

    _clear_state()
    r = start_session(target_date=date(2026, 10, 22))
    text = r.get("text", "")
    assert r.get("status") == "question", r
    assert "第 1/2 批" in text
    assert "Q1" in text and "Q5" in text
    assert "Q6" not in text
    assert "答案：" not in text and "正确答案" not in text
    _clear_state()


def test_parse_multichoice_answer_chinese_comma() -> None:
    block = """
10.【多选题】新成员不愿参与讨论，团队应采取哪两个行动？
答案:C，E
解析：选项C和E正确。
"""
    ans = _parse_answers(block)
    assert 10 in ans
    assert ans[10]["answer"] == "CE"
    assert ans[10]["question_type"] == "multi"


def test_aug24_q10_if_present() -> None:
    pdf = _ROOT / "pmp_notes" / "每日一练" / "2609每日一练8月24日.pdf"
    if not pdf.exists():
        print("⏭️  SKIP aug24 pdf: 文件不存在")
        return
    qs = load_questions_for_date(date(2026, 8, 24))
    assert len(qs) == 10
    q10 = qs[9]
    assert q10["correct_answer"] == "CE", q10.get("correct_answer")
    assert q10.get("question_type") == "multi"


def test_grade_multichoice() -> None:
    from pmp_athena import daily_practice as dp
    from pmp_athena.daily_practice import _clear_state, _save_state, grade_answers

    original = _silence_recording(dp)
    _clear_state()
    _save_state(
        {
            "mode": "fixed",
            "date": "2026-07-24",
            "label": "7月24日",
            "questions": [
                {
                    "index": 1,
                    "num": 1,
                    "stem": "多选干系人",
                    "options": {"A": "a", "B": "b", "C": "c", "D": "d", "E": "e"},
                    "correct_answer": "ACD",
                    "explanation": "测试",
                    "knowledge_area": "干系人管理",
                    "question_type": "multi",
                },
                {
                    "index": 2,
                    "num": 2,
                    "stem": "单选",
                    "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                    "correct_answer": "B",
                    "explanation": "",
                    "knowledge_area": "综合",
                    "question_type": "single",
                },
            ],
            "current_index": 0,
            "correct_count": 0,
            "wrong_count": 0,
            "wrong_items": [],
        }
    )
    try:
        r = grade_answers("ACDB")
        assert r.get("done"), r
        assert "本批判卷" in r.get("text", "")
    finally:
        dp._record_answer = original
        _clear_state()


def test_parse_inline_bank_options() -> None:
    from pmp_athena.daily_practice import _parse_bank_question

    record = {
        "id": 54,
        "question": "启动阶段新法规可能使采购计划变更。发起人要PM提供说服高管继续项目的信息。在哪找？A.商业论证 B.章程 C.项目批准要求 D.组织过程资产",
        "correct_answer": "A",
        "knowledge_area": "商业环境",
    }
    q = _parse_bank_question(record)
    assert q is not None
    assert q["stem"].endswith("？")
    assert sorted(q["options"]) == ["A", "B", "C", "D"]


def test_load_area_questions_business_environment() -> None:
    from pmp_athena.daily_practice import load_area_questions

    qs = load_area_questions("商业环境")
    assert len(qs) >= 15
    assert all(q["knowledge_area"] == "商业环境" for q in qs)


def main() -> int:
    tests = [
        test_strip_header_preserves_stem,
        test_parse_block_not_truncated,
        test_watermark_line_skipped,
        test_recover_orphan_option_c,
        test_parse_chinese_dunhao_question_numbers,
        test_oct22_pdf_if_present,
        test_option_not_watermark_tail,
        test_grade_batch,
        test_daily_batch_waits_for_five,
        test_start_oct22_first_batch_if_present,
        test_parse_multichoice_answer_chinese_comma,
        test_grade_multichoice,
        test_july16_pdf_if_present,
        test_aug24_q10_if_present,
        test_july17_pdf_if_present,
        test_july20_pdf_if_present,
        test_qiji_2609_mock_if_present,
        test_qiji_2609_mock2_if_present,
        test_parse_inline_bank_options,
        test_load_area_questions_business_environment,
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
