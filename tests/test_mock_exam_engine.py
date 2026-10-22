#!/usr/bin/env python3
"""模考引擎：每批 10 题 + 计时。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pmp_athena.mock_exam_engine import MockExamEngine  # noqa: E402


def _fake_questions(n: int) -> list[dict]:
    return [
        {
            "question": f"题干{i + 1}，项目经理应该做什么？",
            "options": ["A. a", "B. b", "C. c", "D. d"],
            "correct_answer": "A",
            "explanation": "解析不应出现在出题里",
            "_area": "综合",
            "_is_multi": False,
        }
        for i in range(n)
    ]


def _engine(tmp_path: Path, n: int = 20) -> MockExamEngine:
    path = tmp_path / "mock_exam_engine.json"
    eng = MockExamEngine(state_path=path)
    now = eng._now_ts()
    eng._write(
        {
            "paper": "测试卷",
            "paper_key": "random",
            "status": "active",
            "total": n,
            "current_index": 0,
            "questions": _fake_questions(n),
            "answers": {},
            "start_ts": now,
            "paused_accumulated": 0,
            "last_resume_ts": now,
            "batch_base_elapsed": 0,
            "batch_times": [],
        }
    )
    return eng


def test_fmt_batch_has_ten_questions_no_answers(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    state = eng._read()
    assert state is not None
    r = eng._fmt_batch(state, 0)
    text = r.get("text", "")
    assert "第 1/2 批" in text
    assert "Q1" in text and "Q10" in text
    assert "Q11" not in text
    assert "正确答案" not in text
    assert "解析不应出现在出题里" not in text


def test_batch_waits_for_ten(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    too_few = eng.answer("A")
    assert too_few.get("status") == "error"
    assert "期望 10 个答案" in (too_few.get("text") or too_few.get("error") or "")

    first = eng.answer("A" * 10)
    assert first.get("status") == "question", first
    text = first.get("text", "")
    assert "第 1 批结果" in text
    assert "本批用时" in text
    assert "Q11" in text
    assert "解析不应出现在出题里" not in text.split("📦")[-1]


def test_show_current_is_batch(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    r = eng.show_current()
    assert "第 1/2 批" in (r.get("text", "") + r.get("next", {}).get("text", ""))


def main() -> int:
    import tempfile

    failed = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for fn in (
            test_fmt_batch_has_ten_questions_no_answers,
            test_batch_waits_for_ten,
            test_show_current_is_batch,
        ):
            try:
                fn(tmp)
                print(f"✅ {fn.__name__}")
            except AssertionError as e:
                failed += 1
                print(f"❌ {fn.__name__}: {e}")
            except Exception as e:
                failed += 1
                print(f"❌ {fn.__name__}: {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
