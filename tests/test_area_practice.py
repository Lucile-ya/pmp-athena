#!/usr/bin/env python3
"""专项练习：周历混域抽题。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.daily_practice import (  # noqa: E402
    _split_areas,
    load_mixed_area_questions,
)


def _q(stem: str, area: str) -> dict:
    return {
        "stem": stem,
        "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "correct": "A",
        "knowledge_area": area,
    }


class AreaPracticeTests(unittest.TestCase):
    def test_split_calendar_mix(self) -> None:
        self.assertEqual(
            _split_areas("商业环境+敏捷"),
            ["商业环境", "敏捷/混合方法"],
        )
        self.assertEqual(
            _split_areas("商业环境+敏捷/混合方法"),
            ["商业环境", "敏捷/混合方法"],
        )

    def test_mixed_even_split_and_fill(self) -> None:
        pools = {
            "商业环境": [_q(f"商业环境题{i}？", "商业环境") for i in range(12)],
            "敏捷/混合方法": [_q(f"敏捷题{i}？", "敏捷/混合方法") for i in range(12)],
        }

        def fake_collect(area: str):
            return list(pools[area])

        with patch("pmp_athena.daily_practice._collect_area_questions", side_effect=fake_collect):
            got = load_mixed_area_questions(["商业环境", "敏捷/混合方法"], 20)
        self.assertEqual(len(got), 20)
        areas = [q["knowledge_area"] for q in got]
        self.assertEqual(areas.count("商业环境"), 10)
        self.assertEqual(areas.count("敏捷/混合方法"), 10)

    def test_mixed_fills_when_one_pool_short(self) -> None:
        pools = {
            "商业环境": [_q(f"商业环境题{i}？", "商业环境") for i in range(3)],
            "敏捷/混合方法": [_q(f"敏捷题{i}？", "敏捷/混合方法") for i in range(20)],
        }

        def fake_collect(area: str):
            return list(pools[area])

        with patch("pmp_athena.daily_practice._collect_area_questions", side_effect=fake_collect):
            got = load_mixed_area_questions(["商业环境", "敏捷"], 20)
        self.assertEqual(len(got), 20)
        areas = [q["knowledge_area"] for q in got]
        self.assertEqual(areas.count("商业环境"), 3)
        self.assertEqual(areas.count("敏捷/混合方法"), 17)


if __name__ == "__main__":
    unittest.main()
