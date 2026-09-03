#!/usr/bin/env python3
"""daily_quest 单元测试（stdlib，不依赖 pytest）。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.daily_quest import (  # noqa: E402
    handle_message,
    next_step,
    parse_quest_request,
    _sprint_area,
)
import pmp_athena.daily_quest as dq  # noqa: E402


def _base_status(**overrides):
    data = {
        "area": "成本管理",
        "rev_done": 0,
        "rev_total": 13,
        "step1_done": False,
        "area_n": 0,
        "step2_target": 15,
        "step2_done": False,
        "step3_done": False,
        "all_done": False,
        "focus": ["成本管理", "进度管理"],
        "kind": "area",
        "skip_area": False,
        "why": "成本管理 错误率 67%，P0 红线，今天必须压下去",
        "tomorrow": "明天：专项 进度管理",
        "clear_mode": False,
    }
    data.update(overrides)
    return data


class DailyQuestTests(unittest.TestCase):
    def test_parse_quest_request(self) -> None:
        self.assertEqual(parse_quest_request("今日任务"), "start")
        self.assertEqual(parse_quest_request("今天任务"), "start")
        self.assertEqual(parse_quest_request("开始任务"), "next")
        self.assertEqual(parse_quest_request("下一步"), "next")
        self.assertEqual(parse_quest_request("继续任务"), "next")
        self.assertIsNone(parse_quest_request("开始模考"))
        self.assertIsNone(parse_quest_request("继续"))
        self.assertIsNone(parse_quest_request("今日练习"))

    def test_sprint_area(self) -> None:
        self.assertEqual(_sprint_area("敏捷/混合方法"), "敏捷")
        self.assertEqual(_sprint_area("成本管理"), "成本管理")

    def test_handle_message_skip(self) -> None:
        self.assertEqual(handle_message("复习错题")["status"], "skip")

    def test_overview_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            quest_path = Path(td) / "today_quest.json"
            with patch.object(dq, "TODAY_QUEST_PATH", quest_path), patch.object(
                dq, "_status", lambda: _base_status()
            ):
                result = handle_message("今日任务")
        self.assertEqual(result["action"], "overview")
        self.assertIn("今日任务", result["text"])
        self.assertIn("开始任务", result["text"])
        self.assertIn("清错题", result["text"])
        self.assertIn("成本管理", result["text"])
        self.assertIn("进度管理", result["text"])
        self.assertIn("明天", result["text"])

    def test_next_step_review_then_area_then_cards(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            quest_path = Path(td) / "today_quest.json"
            status = _base_status()
            with patch.object(dq, "TODAY_QUEST_PATH", quest_path), patch.object(
                dq, "_cards_text", lambda: "③ 摘要卡假数据"
            ), patch.object(dq, "_status", lambda: status):
                r1 = next_step()
                self.assertEqual(r1["action"], "review")
                self.assertIn("清错题", r1["text"])

                status["step1_done"] = True
                status["rev_done"] = 13
                r2 = next_step()
                self.assertEqual(r2["action"], "area")
                self.assertEqual(r2["area"], "成本管理")

                status["step2_done"] = True
                status["area_n"] = 15
                r3 = next_step()
                self.assertEqual(r3["action"], "cards")
                data = json.loads(quest_path.read_text(encoding="utf-8"))
                self.assertTrue(data["cards_shown"])

                status["step3_done"] = True
                status["all_done"] = True
                r4 = next_step()
                self.assertEqual(r4["action"], "done")


if __name__ == "__main__":
    unittest.main()
