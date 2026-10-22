#!/usr/bin/env python3
"""补考周历解析测试。"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.retake_calendar import day_plan  # noqa: E402


class RetakeCalendarTests(unittest.TestCase):
    def test_oct22_business_agile_20(self) -> None:
        p = day_plan(date(2026, 10, 22))
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.kind, "area")
        self.assertIn("商业环境", p.areas)
        self.assertIn("敏捷/混合方法", p.areas)
        self.assertEqual(p.question_n, 20)
        self.assertEqual(p.review_n, 5)
        self.assertTrue(p.skip_live)
        self.assertEqual(p.primary, "商业环境")

    def test_oct23_split_20(self) -> None:
        p = day_plan(date(2026, 10, 23))
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.kind, "area")
        self.assertEqual(p.question_n, 20)
        self.assertIn("商业环境", p.areas)
        self.assertIn("敏捷/混合方法", p.areas)
        self.assertFalse(p.skip_live)

    def test_nov14_mock(self) -> None:
        p = day_plan(date(2026, 11, 14))
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.kind, "mock")
        self.assertEqual(p.question_n, 0)
        self.assertEqual(p.areas, [])
        self.assertIsNone(p.primary)

    def test_dec3_finale(self) -> None:
        p = day_plan(date(2026, 12, 3))
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.kind, "finale")
        self.assertEqual(p.question_n, 0)

    def test_oct30_quality_20(self) -> None:
        p = day_plan(date(2026, 10, 30))
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.kind, "area")
        self.assertEqual(p.areas, ["质量管理"])
        self.assertEqual(p.question_n, 20)

    def test_nov19_people_plus_business(self) -> None:
        p = day_plan(date(2026, 11, 19))
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.kind, "area")
        self.assertIn("干系人管理", p.areas)
        self.assertIn("商业环境", p.areas)
        self.assertEqual(p.question_n, 25)

    def test_dec5_exam(self) -> None:
        p = day_plan(date(2026, 12, 5))
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.kind, "exam")
        self.assertIsNone(p.primary)


if __name__ == "__main__":
    unittest.main()
