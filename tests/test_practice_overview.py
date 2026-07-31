"""practice_overview 单元测试。"""

import unittest
from datetime import date

from pmp_athena.practice_overview import (
    PREP_START,
    build_overview,
    handle_message,
    parse_trigger,
    _area_stats_with_errors,
    _build_monthly_timeline,
    _build_weekly_timeline,
    _mock_trend,
    _progress_bar,
    _rate_delta,
    _today_suggestions,
)
from pmp_athena.question_bank import QuestionBank


class TestParseTrigger(unittest.TestCase):
    def test_exact_triggers(self):
        for t in ("总览", "刷题总览", "我的进度", "战况", "现在什么水平"):
            self.assertTrue(parse_trigger(t), t)

    def test_skip(self):
        self.assertFalse(parse_trigger("考前分析"))
        self.assertFalse(parse_trigger("每日一练"))


class TestHandleMessage(unittest.TestCase):
    def test_overview(self):
        r = handle_message("总览")
        self.assertNotEqual(r.get("status"), "skip")
        self.assertIn("刷题总览", r.get("text", ""))

    def test_skip(self):
        self.assertEqual(handle_message("hello").get("status"), "skip")


class TestBuildOverview(unittest.TestCase):
    def test_structure(self):
        r = build_overview()
        text = r.get("text", "")
        self.assertIn("刷题量", text)
        self.assertIn("目标对比", text)
        self.assertIn("趋势", text)
        self.assertIn("月度时间线", text)
        self.assertIn("周度时间线", text)
        self.assertIn("模考时间线", text)
        self.assertIn("领域", text)
        self.assertIn("今日建议", text)
        self.assertIn("补课", text)

    def test_timeline_json(self):
        r = build_overview()
        tl = r.get("timeline", {})
        self.assertIn("monthly", tl)
        self.assertIn("weekly", tl)
        self.assertIn("mock_exams", tl)
        self.assertGreaterEqual(len(tl["monthly"]), 1)

    def test_fields(self):
        r = build_overview()
        self.assertIn("combined_total", r)
        self.assertIn("days_left", r)
        self.assertIn("active_days", r)


class TestHelpers(unittest.TestCase):
    def test_progress_bar(self):
        self.assertEqual(len(_progress_bar(50)), 20)
        self.assertIn("█", _progress_bar(75))
        self.assertIn("░", _progress_bar(75))

    def test_rate_delta(self):
        text, arrow = _rate_delta(70, 60)
        self.assertIn("+10", text)
        self.assertEqual(arrow, "↑")
        text2, _ = _rate_delta(70, None)
        self.assertIn("首段", text2)

    def test_monthly_timeline(self):
        bank = QuestionBank()
        lines, rows = _build_monthly_timeline(bank, date(2026, 7, 31))
        self.assertTrue(any("07月" in ln for ln in lines))
        self.assertGreaterEqual(len(rows), 1)
        july = rows[0]
        self.assertEqual(july["month"], 7)

    def test_weekly_timeline(self):
        bank = QuestionBank()
        lines, rows = _build_weekly_timeline(bank, date(2026, 7, 31))
        self.assertTrue(any("W" in ln for ln in lines))
        self.assertGreaterEqual(len(rows), 1)

    def test_mock_trend(self):
        exams = [
            {"correct_rate": 0.65, "correct_count": 117, "total_questions": 180},
            {"correct_rate": 0.70, "correct_count": 126, "total_questions": 180},
        ]
        self.assertIn("上升", _mock_trend(exams))

    def test_area_merge(self):
        merged = _area_stats_with_errors(
            [{"knowledge_area": "成本管理", "is_correct": False}],
            [{"knowledge_area": "成本管理"}],
        )
        self.assertIn("成本管理", merged)
        self.assertEqual(merged["成本管理"]["errors"], 1)

    def test_suggestions(self):
        acts = _today_suggestions(
            due_errors=5,
            weak_areas=["成本管理"],
            combined_rate=55.0,
            mock_count=0,
            daily_done=False,
            sprint_hint=None,
        )
        self.assertGreaterEqual(len(acts), 1)
        self.assertLessEqual(len(acts), 3)


if __name__ == "__main__":
    unittest.main()
