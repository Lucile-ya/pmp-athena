#!/usr/bin/env python3
"""开放模考卷进入专项池。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.mock_exam_engine import (  # noqa: E402
    MOCK_DIR,
    PRACTICE_OPEN_PAPERS,
    mock_to_area_question,
)


class MockPracticePoolTests(unittest.TestCase):
    def test_mock_dir_points_at_pdfs(self) -> None:
        self.assertTrue(MOCK_DIR.is_dir())
        self.assertGreaterEqual(len(list(MOCK_DIR.glob("*.pdf"))), 5)

    def test_practice_open_covers_wired_papers(self) -> None:
        self.assertIn("five", PRACTICE_OPEN_PAPERS)
        self.assertIn("seven", PRACTICE_OPEN_PAPERS)
        self.assertIn("four", PRACTICE_OPEN_PAPERS)
        self.assertNotIn("random", PRACTICE_OPEN_PAPERS)

    def test_mock_to_area_question(self) -> None:
        q = {
            "question": "项目已满足关闭标准，项目经理下一步应该做什么？",
            "options": [
                "A. 继续加功能",
                "B. 释放资源",
                "C. 额外质量检查",
                "D. 口头接受变更",
            ],
            "correct_answer": "B",
            "explanation": "满足关闭就收摊",
            "_area": "整合管理",
            "_is_multi": False,
        }
        out = mock_to_area_question(q, paper="模拟一")
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["correct_answer"], "B")
        self.assertEqual(out["source"], "mock_exam")
        self.assertEqual(out["options"]["B"], "释放资源")
        self.assertEqual(out["paper"], "模拟一")

    def test_collect_area_includes_mock(self) -> None:
        from pmp_athena import daily_practice as dp

        fake_mock = [
            {
                "stem": "开放模考池测试题：商业论证用于什么？" + ("x" * 20),
                "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                "correct_answer": "A",
                "explanation": "",
                "knowledge_area": "商业环境",
                "question_type": "single",
                "source": "mock_exam",
                "paper": "模拟一",
            }
        ]

        class _QB:
            def list_by_area(self, _area: str):
                return []

        with patch.object(dp, "_load_area_seed_questions", return_value=[]), patch(
            "pmp_athena.mock_exam_engine.load_all_open_mock_questions",
            return_value=fake_mock,
        ), patch("pmp_athena.question_bank.QuestionBank", _QB):
            qs = dp._collect_area_questions("商业环境")
        stems = [q.get("stem", "") for q in qs]
        self.assertTrue(any("开放模考池测试题" in s for s in stems))


if __name__ == "__main__":
    unittest.main()
