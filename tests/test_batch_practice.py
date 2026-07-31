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


def main() -> int:
    tests = [
        test_parse_five_questions,
        test_extract_answer,
        test_is_batch_input,
        test_parse_update_command,
        test_cn_enum_question_format,
        test_breakfast_solution_format,
        test_my_answer_only_phrase,
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
