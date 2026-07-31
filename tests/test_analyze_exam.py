"""模考截图 OCR 解析单元测试（纯文本，无需图片）。"""

import unittest

from pmp_athena.analyze_exam import (
    analyze_exam_text,
    detect_exam_screenshot,
    parse_exam_text,
    _compare_history,
    _load_error_log_areas,
)


SAMPLE_2606 = """
2606PMP模考一
交卷时间：2026-07-28 14:32:15
得分 100分
共180题 总计180分
答对 100 题
答错 75 题
未答 5 题
排名 12
班级平均分 85.6
用时 196分钟
"""

SAMPLE_MINIMAL = """
PMP模拟考试
答对 90 题
共 180 题
"""

SAMPLE_SCORE_ONLY = """
模考卷二
100/180
正确率 55.6%
"""


class TestDetectExamScreenshot(unittest.TestCase):
    def test_positive(self):
        self.assertTrue(detect_exam_screenshot(SAMPLE_2606))
        self.assertTrue(detect_exam_screenshot(SAMPLE_MINIMAL))

    def test_negative_plain_question(self):
        text = "1. 项目经理收到变更请求\nA. 拒绝\nB. 评估\nC. 实施\nD. 上报"
        self.assertFalse(detect_exam_screenshot(text))


class TestParseExamText(unittest.TestCase):
    def test_full_fields(self):
        p = parse_exam_text(SAMPLE_2606)
        self.assertEqual(p["exam_name"], "2606PMP模考一")
        self.assertEqual(p["exam_date"], "2026-07-28")
        self.assertEqual(p["score"], 100)
        self.assertEqual(p["total_questions"], 180)
        self.assertEqual(p["total_score"], 180)
        self.assertEqual(p["correct_count"], 100)
        self.assertEqual(p["wrong_count"], 75)
        self.assertEqual(p["unanswered_count"], 5)
        self.assertEqual(p["ranking"], "12")
        self.assertAlmostEqual(p["average_score"], 85.6)
        self.assertEqual(p["time_used_minutes"], 196)

    def test_minimal(self):
        p = parse_exam_text(SAMPLE_MINIMAL)
        self.assertEqual(p["correct_count"], 90)
        self.assertEqual(p["total_questions"], 180)

    def test_score_fraction(self):
        p = parse_exam_text(SAMPLE_SCORE_ONLY)
        self.assertEqual(p["correct_count"], 100)
        self.assertEqual(p["total_questions"], 180)
        self.assertTrue(p["exam_name"])


class TestAnalyzeExamText(unittest.TestCase):
    def test_no_save(self):
        r = analyze_exam_text(SAMPLE_2606, save=False)
        self.assertTrue(r["success"])
        self.assertIn("模考", r["report"])
        self.assertEqual(r["record"], {})

    def test_report_sections(self):
        r = analyze_exam_text(SAMPLE_2606, save=False)
        report = r["report"]
        self.assertIn("模考分析", report)
        self.assertIn("建议", report)


class TestHelpers(unittest.TestCase):
    def test_compare_history_empty(self):
        from pmp_athena.exam_recorder import ExamRecorder

        h = _compare_history(ExamRecorder(), 55.0)
        self.assertIn("trend", h)

    def test_error_log_areas(self):
        areas = _load_error_log_areas()
        self.assertIsInstance(areas, list)


if __name__ == "__main__":
    unittest.main()
