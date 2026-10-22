#!/usr/bin/env python3
"""bedtime_review 单元测试。"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.bedtime_review import (  # noqa: E402
    _tier,
    build_bedtime_review,
    is_bedtime_request,
)


def test_triggers() -> None:
    assert is_bedtime_request("睡前复习")
    assert is_bedtime_request("睡前回顾")
    assert is_bedtime_request("睡前复习。")
    assert not is_bedtime_request("复习错题")
    assert not is_bedtime_request("今日任务")


def test_tier() -> None:
    assert _tier(44) == "green"
    assert _tier(20) == "yellow"
    assert _tier(10) == "orange"
    assert _tier(5) == "red"


def test_build_outputs_header() -> None:
    # 用固定日期避免依赖当天错题状态断言过死
    out = build_bedtime_review(today=date(2026, 10, 22))
    assert "🌙" in out
    assert ("睡前" in out) or ("错题" in out) or ("必考点" in out)
