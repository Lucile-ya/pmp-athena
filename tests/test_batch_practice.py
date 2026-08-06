#!/usr/bin/env python3
"""App 批量题解析回归。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pmp_athena.batch_practice import (  # noqa: E402
    extract_answer_string,
    extract_my_answer_only,
    is_batch_question_input,
    is_batch_update_input,
    parse_batch_questions,
    parse_batch_update_command,
    parse_solution_only,
    _is_multichoice_question,
    _get_answer_count,
    _normalize_answer_string,
    _get_per_question_answer_counts,
    _split_answers_for_questions,
    _format_answer_mapping,
)

SAMPLE = """
41.项目经理应如何确保项目满足关闭标准？
A. 继续监控项目
B. 提交变更请求
C. 获得客户验收并释放资源
D. 更新风险登记册

42.团队冲突最佳首选策略是什么？
A. 回避
B. 强迫
C. 合作/解决问题
D. 缓和

43.WBS 的核心作用是什么？
A. 估算成本
B. 分解可交付成果
C. 制定进度基准
D. 识别风险

44.变更请求的正确流程是？
A. 直接实施
B. 先评估影响再提交 CCB
C. 口头批准即可
D. 仅更新日志

45.项目收尾时首要工作是什么？
A. 庆祝
B. 释放资源并归档
C. 开始新项目
D. 更新章程

我的答案是：CCCAB
"""


def test_parse_five_questions() -> None:
    qs = parse_batch_questions(SAMPLE)
    assert len(qs) == 5
    assert qs[0]["num"] == 41
    assert "关闭标准" in qs[0]["stem"]
    assert set(qs[0]["options"]) == {"A", "B", "C", "D"}


def test_extract_answer() -> None:
    assert extract_answer_string(SAMPLE) == "CCCAB"


def test_is_batch_input() -> None:
    assert is_batch_question_input(SAMPLE)
    assert not is_batch_question_input("41.只有一题 A.a B.b 我的答案是：C")


def test_parse_update_command() -> None:
    cmd = parse_batch_update_command("更新41题，正确答案是 C，解析：先验收再收尾")
    assert cmd is not None
    assert cmd["num"] == 41
    assert cmd["correct_answer"] == "C"
    assert "验收" in cmd["explanation"]
    assert is_batch_update_input("更新 45 题 正确答案是 B 解析 xxx")


def test_cn_enum_question_format() -> None:
    text = """
1、项目发起人启动了一个新项目，该项目涉及他们的客户。
A、项目发起人和赞助公司
B、客户和项目团队
C、分包商和项目团队
D、项目经理和赞助公司
我的答案是A
"""
    qs = parse_batch_questions(text)
    assert len(qs) == 1
    assert qs[0]["num"] == 1
    assert "项目发起人" in qs[0]["stem"]
    assert extract_answer_string(text) == "A"
    assert is_batch_question_input(text)


def test_breakfast_solution_format() -> None:
    text = """
1、答案： B
【解析】项目章程在需求组织与执行组织之间建立伙伴关系。
"""
    sol = parse_solution_only(text)
    assert len(sol) == 1
    assert sol[0]["correct_answer"] == "B"
    assert "项目章程" in sol[0]["explanation"]


def test_my_answer_only_phrase() -> None:
    assert extract_my_answer_only("我的答案是A") == "A"
    assert extract_my_answer_only("我选B") == "B"


# ── 多选题解析测试 ──

def test_multichoice_detection() -> None:
    """检测「选择两项」「选择三项」"""
    assert _is_multichoice_question("54.业务转型...选择两项") is True
    assert _is_multichoice_question("请选择三项正确的选项") is True
    assert _is_multichoice_question("51.正常的单选题") is False
    assert _is_multichoice_question("54.choose two options") is True
    assert _is_multichoice_question("choose 3 answers") is True


def test_answer_count_per_question() -> None:
    assert _get_answer_count("选择两项的题目") == 2
    assert _get_answer_count("选三项") == 3
    assert _get_answer_count("普通题") == 1


def test_normalize_answer_with_delimiters() -> None:
    """分隔符去除：A,E → AE, A、E → AE, A和E → AE"""
    assert _normalize_answer_string("A,E") == "AE"
    assert _normalize_answer_string("A、E") == "AE"
    assert _normalize_answer_string("A 和 E") == "AE"
    assert _normalize_answer_string("A, E") == "AE"
    assert _normalize_answer_string("C, E") == "CE"


def test_extract_answer_with_delimiters() -> None:
    """我的答案是 支持多选分隔符"""
    assert extract_answer_string("我的答案是：A,E") == "AE"
    assert extract_answer_string("我的答案是A、E") == "AE"
    # 普通连续字母不变
    assert extract_answer_string("我的答案是：AAAAED") == "AAAAED"


def test_split_answers_for_questions() -> None:
    """按每题期望答案数拆分"""
    questions = [
        {"num": 51, "question": "单选题 A. B. C. D.", "stem": "单选题"},
        {"num": 52, "question": "单选题2 A. B. C. D.", "stem": "单选题2"},
        {"num": 53, "question": "单选题3 A. B. C. D.", "stem": "单选题3"},
        {"num": 54, "question": "选择两项的题 A. B. C. D. E.", "stem": "多选题"},
        {"num": 55, "question": "单选题4 A. B. C. D.", "stem": "单选题4"},
    ]
    result = _split_answers_for_questions("AAAAED", questions)
    assert result is not None
    assert result == ["A", "A", "A", "AE", "D"]


def test_split_answers_length_mismatch() -> None:
    """长度不匹配返回 None"""
    questions = [
        {"num": 51, "question": "单选题", "stem": "单选题"},
        {"num": 52, "question": "单选题2", "stem": "单选题2"},
    ]
    assert _split_answers_for_questions("ABC", questions) is None  # 3 chars for 2 single questions
    assert _split_answers_for_questions("A", questions) is None     # 1 char for 2 single questions


def test_per_question_answer_counts() -> None:
    """计算每题期望答案数"""
    questions = [
        {"num": 51, "question": "普通题", "stem": "普通"},
        {"num": 52, "question": "选择两项的题", "stem": "多选"},
        {"num": 53, "question": "选三项的题", "stem": "多选3"},
    ]
    assert _get_per_question_answer_counts(questions) == [1, 2, 3]


def test_format_answer_mapping() -> None:
    """答案映射格式化输出"""
    questions = [
        {"num": 51, "question": "单选", "stem": "单选"},
        {"num": 54, "question": "选择两项", "stem": "多选"},
    ]
    mapping = _format_answer_mapping(questions, "ABC")
    assert "题目 2 道" in mapping
    assert "期望 3 个" in mapping
    assert "Q54" in mapping
    assert "选择二项" in mapping


def test_extract_my_answer_only_multichoice() -> None:
    """extract_my_answer_only 支持多选格式"""
    assert extract_my_answer_only("A,E") == "AE"
    assert extract_my_answer_only("A、E") == "AE"
    assert extract_my_answer_only("AE") == "AE"


def main() -> int:
    tests = [
        test_parse_five_questions,
        test_extract_answer,
        test_is_batch_input,
        test_parse_update_command,
        test_cn_enum_question_format,
        test_breakfast_solution_format,
        test_my_answer_only_phrase,
        # 多选题测试
        test_multichoice_detection,
        test_answer_count_per_question,
        test_normalize_answer_with_delimiters,
        test_extract_answer_with_delimiters,
        test_split_answers_for_questions,
        test_split_answers_length_mismatch,
        test_per_question_answer_counts,
        test_format_answer_mapping,
        test_extract_my_answer_only_multichoice,
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
