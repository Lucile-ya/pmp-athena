"""study_advisor._merge_options 单元测试"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.study_advisor import (  # noqa: E402
    _find_full_question,
    _is_options_only_block,
    _merge_options,
    load_json,
    ERROR_LOG_PATH,
    QUESTION_BANK_PATH,
)


def test_is_options_only_block():
    assert _is_options_only_block("A. foo\nB. bar")
    assert not _is_options_only_block("题干内容\nA. foo")


def test_merge_options_only_supplement_keeps_stem():
    stem = "某团队已推进项目数月，但完工时间仍不明确。"
    opts = "A. WBS\nB. backlog\nC. 每日站会\nD. 启动会"
    result = _merge_options(stem, 999)
    # 无 supplement 时原样返回
    assert result == stem

    # 模拟 supplement 注入：用真实 #35 数据
    errors = load_json(ERROR_LOG_PATH)
    bank = load_json(QUESTION_BANK_PATH)
    rec = _find_full_question(35, errors, bank)
    assert "某团队" in rec["question"]
    assert "A." in rec["question"]
    assert rec["question"].index("某团队") < rec["question"].index("A.")
