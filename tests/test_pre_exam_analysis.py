#!/usr/bin/env python3
"""pre_exam_analysis 单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.pre_exam_analysis import (  # noqa: E402
    handle_message,
    parse_trigger,
    pre_exam_analysis,
    _short_tip,
)


def test_parse_triggers() -> None:
    assert parse_trigger("战况") is None
    assert parse_trigger("考前分析") is not None
    assert parse_trigger("我现在的水平") is None
    assert parse_trigger("根因分析")["focus"] == "root_cause"
    assert parse_trigger("最后14天怎么安排")["plan_days"] == 14
    assert parse_trigger("每日一练") is None


def test_full_analysis() -> None:
    r = pre_exam_analysis()
    assert r["status"] == "ok"
    text = r["text"]
    assert "考前深度分析" in text
    assert "核心建议" in text
    assert "今天必须完成" in text
    assert len(r["today_actions"]) == 3


def test_suggestions_length() -> None:
    tips = [_short_tip("补敏捷专项强化", 10), _short_tip("模考冲刺70%目标", 10)]
    for t in tips:
        assert len(t) <= 10


def test_handle_message() -> None:
    r = handle_message("考前分析")
    assert r["status"] == "ok"
    assert "考前深度分析" in r["text"]


def test_root_cause_focus() -> None:
    r = pre_exam_analysis(focus="root_cause")
    assert "防错策略卡" in r["text"]


def main() -> int:
    failed = 0
    for name, fn in [
        ("parse_triggers", test_parse_triggers),
        ("full_analysis", test_full_analysis),
        ("suggestions_length", test_suggestions_length),
        ("handle_message", test_handle_message),
        ("root_cause_focus", test_root_cause_focus),
    ]:
        try:
            fn()
            print(f"OK {name}")
        except AssertionError as e:
            print(f"FAIL {name}: {e}")
            failed += 1
    return failed


if __name__ == "__main__":
    sys.exit(main())
