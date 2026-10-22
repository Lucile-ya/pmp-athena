#!/usr/bin/env python3
"""复习错题展示：去污染题干、判卷短反馈、出题不剧透。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.error_insights import format_wrong_feedback  # noqa: E402
from pmp_athena.study_advisor import (  # noqa: E402
    _clean_review_question,
    _find_full_question,
    _format_review_question,
    _is_polluted_question,
)


POLLUTED = (
    "项目已满足商定的产品要求，即将结束。项目经理应该做什么？"
    " 选项A：直接实施变更，做法不妥。 选项B：额外质量检查，因此不选。"
    " 选项C：提交给拥有变更审批权的干系人审批。\n"
    "A. 用剩余资源加范围\n"
    "B. 做额外质量检查\n"
    "C. 确认关闭标准并释放资源\n"
    "D. 获发起人批准后加功能"
)


class ReviewDisplayTests(unittest.TestCase):
    def test_strip_inline_option_analysis(self) -> None:
        cleaned = _clean_review_question(POLLUTED)
        self.assertNotIn("选项A", cleaned)
        self.assertNotIn("因此不选", cleaned)
        self.assertIn("项目经理应该做什么？", cleaned)
        self.assertIn("A. 用剩余资源加范围", cleaned)
        self.assertLess(cleaned.index("做什么"), cleaned.index("A."))

    def test_prefer_clean_bank_record(self) -> None:
        errors = [{"id": 84, "question": POLLUTED, "knowledge_area": "成本管理"}]
        bank = [
            {
                "error_log_id": 84,
                "question": POLLUTED,
                "is_correct": False,
            },
            {
                "error_log_id": 84,
                "question": (
                    "项目已满足商定的产品要求，即将结束。项目经理应该做什么？\n"
                    "A. 用剩余资源加范围\nB. 做额外质量检查\n"
                    "C. 确认关闭标准并释放资源\nD. 获发起人批准后加功能"
                ),
                "is_correct": False,
            },
        ]
        rec = _find_full_question(84, errors, bank)
        self.assertFalse(_is_polluted_question(rec["question"]))
        self.assertNotIn("选项A", rec["question"])

    def test_review_card_is_silent(self) -> None:
        rec = {
            "knowledge_area": "成本管理",
            "question": POLLUTED,
        }
        text = _format_review_question(84, rec, times_wrong=3)
        self.assertIn("📝 复习 #84 [成本管理]  🔥3次", text)
        self.assertNotIn("🔑", text)
        self.assertNotIn("👁️", text)
        self.assertNotIn("答对后可能", text)
        self.assertNotIn("选项A", text)

    def test_wrong_feedback_is_two_lines(self) -> None:
        err = {
            "id": 1,
            "correct_answer": "A",
            "my_answer": "C",
            "mnemonic": "已发生先找根因，教训会放到收尾。",
            "question": "数据丢失后项目经理首先做什么？",
            "explanation": "先与团队讨论根本原因",
            "knowledge_area": "质量管理",
        }
        text = format_wrong_feedback(err, user_answer="C")
        self.assertEqual(text.splitlines()[0], "❌ 你的 C → 正确 A")
        self.assertIn("🎯 已发生先找根因", text)
        self.assertNotIn("🔑", text)
        self.assertNotIn("📌 总结", text)
        self.assertLessEqual(len(text.splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
