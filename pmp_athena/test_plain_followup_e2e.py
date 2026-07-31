#!/usr/bin/env python3
"""截图 pending → 我的答案是X+正确答案是Y → 给我解析一下 — 端到端自测。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _setup_temp_store(tmp: Path) -> None:
    import pmp_athena.error_logger as el
    import pmp_athena.plain_question_store as pqs
    import pmp_athena.question_bank as qb

    el.DEFAULT_LOG_PATH = tmp / "error_log.json"
    qb.DEFAULT_BANK_PATH = tmp / "question_bank.json"
    pqs.PENDING_PATH = tmp / "pending_plain_question.json"
    el.DEFAULT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    el.DEFAULT_LOG_PATH.write_text("[]", encoding="utf-8")
    qb.DEFAULT_BANK_PATH.write_text("[]", encoding="utf-8")
    pqs.clear_pending()


Q10 = {
    "question": "【E2E】下列哪个工具适用于定义跨职能的需求？",
    "options": {
        "A": "焦点小组",
        "B": "引导",
        "C": "名义小组",
        "D": "问卷调查",
    },
    "formatted_question": (
        "【E2E】下列哪个工具适用于定义跨职能的需求？\n"
        "A. 焦点小组\nB. 引导\nC. 名义小组\nD. 问卷调查"
    ),
    "knowledge_area": "范围管理",
}


def test_inline_grade_and_explain(tmp: Path) -> None:
    import pmp_athena.batch_explain as be
    import pmp_athena.batch_practice as bp
    import pmp_athena.plain_question_store as pqs

    _setup_temp_store(tmp)
    pqs._save({**Q10, "my_answer": None, "correct_answer": None, "explanation": None})

    assert pqs.has_pending(), "pending 应已写入"

    r1 = pqs.followup_user_text("我的答案是C,正确答案是B")
    assert r1.get("status") == "logged", r1
    assert r1.get("error_log_id") == 1
    assert r1.get("error_is_new") is True
    assert "跨职能" in (r1.get("explain_text") or "")
    assert "引导" in (r1.get("explain_text") or "")
    assert pqs.get_pending() is None, "入库后 pending 应清除"

    # 重复录入：应更新而非新建
    pqs._save({**Q10, "my_answer": None, "correct_answer": None, "explanation": None})
    r2 = pqs.followup_user_text("我的答案是C,正确答案是B")
    assert r2.get("status") == "logged", r2
    assert r2.get("error_log_id") == 1, "同题干应复用 error_log #1"
    assert r2.get("error_is_new") is False
    assert "已更新" in (r2.get("explain_text") or "")

    bank = json.loads((tmp / "question_bank.json").read_text(encoding="utf-8"))
    wrong_rows = [b for b in bank if b.get("is_correct") is False]
    assert len(wrong_rows) == 1, f"题库错题应只有 1 条，实际 {len(wrong_rows)}"

    # last_activity + batch_explain_last
    bp._save_batch_state({
        "last_activity": {
            "stem": Q10["question"],
            "options": Q10["options"],
            "correct_answer": "B",
            "my_answer": "C",
            "explanation": be.auto_explanation(Q10["question"], Q10["options"], "B"),
        }
    })
    assert be.parse_explain_request("给我解析一下")
    r3 = bp.batch_explain_last()
    assert r3.get("status") == "ok"
    assert "解析" in r3.get("text", "")


def test_batch_inline_grade_no_pending(tmp: Path) -> None:
    import pmp_athena.batch_practice as bp
    import pmp_athena.plain_question_store as pqs

    _setup_temp_store(tmp)
    pqs.clear_pending()

    r = bp.batch_inline_grade("我的答案是C,正确答案是B")
    assert r and r.get("status") == "error"
    assert "请先发送题干" in r.get("text", "")


def main() -> int:
    tmp = ROOT / "pmp_notes" / "_test_plain_e2e"
    tmp.mkdir(parents=True, exist_ok=True)
    failed = 0
    tests = [
        ("inline_grade_and_explain", test_inline_grade_and_explain),
        ("batch_inline_no_pending", test_batch_inline_grade_no_pending),
    ]
    for name, fn in tests:
        try:
            fn(tmp)
            print(f"✅ {name}")
        except AssertionError as e:
            print(f"❌ {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {name}: {type(e).__name__}: {e}")
            failed += 1
    return failed


if __name__ == "__main__":
    sys.exit(main())
