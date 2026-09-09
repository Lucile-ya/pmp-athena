#!/usr/bin/env python3
"""学习计划止于考试前一天（stdlib，不依赖 pytest）。"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.study_advisor import clamp_plan_span, last_study_date  # noqa: E402


class TestStudyPlanHorizon(unittest.TestCase):
    def test_last_study_is_day_before_exam(self) -> None:
        self.assertEqual(last_study_date(date(2026, 9, 12)), date(2026, 9, 11))

    def test_plan_from_sep9_ends_sep11(self) -> None:
        days, start, end = clamp_plan_span(date(2026, 9, 9), date(2026, 9, 12))
        self.assertEqual(days, 3)
        self.assertEqual(start, date(2026, 9, 9))
        self.assertEqual(end, date(2026, 9, 11))

    def test_custom_days_cannot_pass_exam(self) -> None:
        days, _start, end = clamp_plan_span(
            date(2026, 9, 9), date(2026, 9, 12), custom_days=14
        )
        self.assertEqual(days, 3)
        self.assertEqual(end, date(2026, 9, 11))

    def test_exam_day_has_no_study_plan(self) -> None:
        days, _start, end = clamp_plan_span(date(2026, 9, 12), date(2026, 9, 12))
        self.assertEqual(days, 0)
        self.assertEqual(end, date(2026, 9, 11))


if __name__ == "__main__":
    unittest.main()
