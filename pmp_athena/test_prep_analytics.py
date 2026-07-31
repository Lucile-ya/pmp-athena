#!/usr/bin/env python3
"""prep_analytics / prep_push 单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.prep_analytics import (  # noqa: E402
    error_study_plan,
    find_knowledge_resources,
    handle_message,
    mock_exam_analysis,
    parse_user_query,
    week_summary,
)
from pmp_athena.prep_push import enqueue, list_pending, tick  # noqa: E402


def test_week_summary() -> None:
    r = week_summary()
    assert "text" in r
    assert "📊" in r["text"]


def test_error_study_plan() -> None:
    r = error_study_plan()
    assert "tiers" in r
    assert "紧急" in r["text"] or "重点" in r["text"] or "保持" in r["text"]


def test_knowledge_resources() -> None:
    res = find_knowledge_resources("成本管理")
    assert isinstance(res, list)
    assert len(res) >= 1


def test_parse_triggers() -> None:
    assert parse_user_query("总览")[0] == "overview"
    assert parse_user_query("战况")[0] == "overview"
    assert parse_user_query("周报")[0] == "week"
    assert parse_user_query("复习计划")[0] == "plan"
    assert parse_user_query("7月做题总结")[0] == "month"


def test_handle_message() -> None:
    r = handle_message("本周汇总")
    assert r.get("status") in ("ok", "empty")
    assert "text" in r


def test_mock_analysis() -> None:
    r = mock_exam_analysis()
    assert "text" in r


def test_month_compare_july() -> None:
    from pmp_athena.practice_summary import month_summary

    r = month_summary(year=2026, month=7)
    assert "月度对比" in r["text"]
    assert "month_compare" in r
    # 7月有数据，6月可能无 → 或 vs 6月
    assert "📊" in r["text"]


def test_month_compare_first_month() -> None:
    from pmp_athena.practice_summary import month_summary

    r = month_summary(year=2025, month=1)
    text = r["text"]
    assert "首月记录" in text or "暂无对比" in text or "月度对比" in text


def test_push_enqueue() -> None:
    item = enqueue("test", "测试推送", delay_minutes=0)
    assert item.get("id")
    pending = list_pending()
    assert any(p["id"] == item["id"] for p in pending)


def main() -> int:
    failed = 0
    for name, fn in [
        ("week_summary", test_week_summary),
        ("error_study_plan", test_error_study_plan),
        ("knowledge_resources", test_knowledge_resources),
        ("parse_triggers", test_parse_triggers),
        ("handle_message", test_handle_message),
        ("mock_analysis", test_mock_analysis),
        ("month_compare_july", test_month_compare_july),
        ("month_compare_first", test_month_compare_first_month),
        ("push_enqueue", test_push_enqueue),
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
