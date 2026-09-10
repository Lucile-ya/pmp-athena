"""practice_overview_light / trend_analysis：模考重复记账不再拉低月度正确率。"""

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from pmp_athena import practice_overview_light as pol
from pmp_athena import trend_analysis as ta


def _bank_row(date, correct, source="manual", q="题", area="整合管理"):
    return {
        "date": date,
        "is_correct": correct,
        "source": source,
        "question": q,
        "knowledge_area": area,
    }


class TestOverviewExcludesMockDumps(unittest.TestCase):
    def test_september_rate_not_dragged_by_mock_exam_source(self):
        bank = [
            _bank_row("2026-08-03", True, q="aug1"),
            _bank_row("2026-08-04", False, q="aug2"),
            _bank_row("2026-09-01", True, q="sep1"),
            _bank_row("2026-09-01", True, q="sep2"),
            *[
                _bank_row("2026-09-03", False, source="mock_exam", q=f"dump{i}", area="资源管理")
                for i in range(10)
            ],
        ]
        exams = {
            "exams": [
                {
                    "exam_id": "模拟二",
                    "exam_date": "2026-09-03",
                    "status": "completed",
                    "correct_rate": 0.6278,
                    "correct_count": 113,
                    "total_questions": 180,
                }
            ]
        }

        def fake_load(path):
            name = Path(path).name
            if name == "question_bank.json":
                return bank
            if name == "exam_records.json":
                return exams
            if name == "error_review_state.json":
                return {}
            if name == "config.json":
                return {"daily_completed": []}
            if name == "error_log.json":
                return []
            return []

        with patch.object(pol, "_load", side_effect=fake_load):
            text = pol.generate_summary()

        self.assertIn("已剔除 10 条模考重复记账", text)
        self.assertIn("正确率 100.0%", text)  # 9月 2/2
        self.assertNotRegex(text.split("📅 9月")[-1].split("📈")[0], r"正确率 16\.")
        self.assertIn("最近模考 63%", text)
        self.assertIn("模拟二", text)


class TestTrendAreaRate(unittest.TestCase):
    def test_rate_from_correct_total_when_rate_missing(self):
        self.assertAlmostEqual(ta._area_rate({"correct": 21, "total": 32}), 65.625)

    def test_counts_win_over_missing_or_zero_rate_field(self):
        self.assertAlmostEqual(
            ta._area_rate({"rate": 0, "correct": 54, "total": 83}),
            54 / 83 * 100,
        )

    def test_generate_report_shows_latest_score_and_area_delta(self):
        exams = {
            "exams": [
                {
                    "exam_id": "模拟一",
                    "exam_date": "2026-08-25",
                    "status": "completed",
                    "correct_rate": 0.5722,
                    "correct_count": 103,
                    "total_questions": 180,
                    "knowledge_areas": {
                        "整合管理": {"correct": 21, "total": 38},
                        "风险管理": {"correct": 1, "total": 3},
                    },
                },
                {
                    "exam_id": "模拟二",
                    "exam_date": "2026-09-03",
                    "status": "completed",
                    "correct_rate": 0.6278,
                    "correct_count": 113,
                    "total_questions": 180,
                    "knowledge_areas": {
                        "整合管理": {"correct": 21, "total": 32},
                        "风险管理": {"correct": 0, "total": 1},
                    },
                },
            ]
        }

        def fake_load(path):
            name = Path(path).name
            if name == "exam_records.json":
                return exams
            if name == "question_bank.json":
                return [
                    {
                        "date": date.today().isoformat(),
                        "is_correct": True,
                        "source": "daily_practice",
                    }
                ]
            return []

        with patch.object(ta, "_load", side_effect=fake_load):
            text = ta.generate_report()

        self.assertIn("整合管理 55% → 66%", text)
        self.assertNotIn("风险管理", text)  # 样本不足
        self.assertIn("当前卷面: 最近一次 63%", text)
        today_md = date.today().isoformat()[5:].replace("-", "/")
        self.assertIn(today_md, text)


if __name__ == "__main__":
    unittest.main()
