#!/usr/bin/env python3
"""今日任务摘要卡：具体口诀，禁止万能句。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.error_insights import (  # noqa: E402
    build_mnemonic,
    format_quest_summary_card,
)


class QuestCardTests(unittest.TestCase):
    def test_org_structure_not_business_case_mnemonic(self) -> None:
        err = {
            "id": 23,
            "knowledge_area": "商业环境",
            "question": "公司的组织结构授予项目经理的职权比职能经理高。这是什么组织结构？",
            "explanation": "PM职权>职能经理→强矩阵",
            "my_answer": "C",
            "correct_answer": "A",
        }
        tip = build_mnemonic(err)
        self.assertIn("强矩阵", tip)
        self.assertNotIn("商业论证", tip)

    def test_po_external_not_ccb(self) -> None:
        err = {
            "id": 27,
            "knowledge_area": "敏捷/混合方法",
            "question": "敏捷项目需适应法规变更、技术创新、市场竞争等持续变更。如何管理？",
            "explanation": "PO职责=监测外部环境变化调整backlog",
            "my_answer": "A",
            "correct_answer": "B",
        }
        tip = build_mnemonic(err)
        self.assertIn("PO", tip)
        self.assertNotIn("CCB", tip)

    def test_card_has_stem_and_trap(self) -> None:
        err = {
            "id": 4,
            "knowledge_area": "敏捷/混合方法",
            "question": "敏捷团队发布第二版后用户体验错误很多。项目经理应该做什么？ A.x B.激励 C.y D.回顾",
            "explanation": "质量问题 → 回顾会议是首选。激励计划是外部驱动，治标不治本。",
            "my_answer": "B",
            "correct_answer": "D",
        }
        text = format_quest_summary_card(err, mistake_count=8)
        self.assertIn("题眼：", text)
        self.assertIn("背：", text)
        self.assertIn("别踩：", text)
        self.assertIn("你曾 B → 应 D", text)
        self.assertNotIn("记牢正确选项", text)


if __name__ == "__main__":
    unittest.main()
