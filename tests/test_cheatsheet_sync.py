#!/usr/bin/env python3
"""cheatsheet_sync 单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.cheatsheet_sync import (  # noqa: E402
    build_trap_row,
    _existing_trap_keys,
    _insert_auto_trap_rows,
    _row_key,
)


def test_build_trap_row() -> None:
    err = {
        "question": "1. CPI 小于 1 表示什么？",
        "my_answer": "A",
        "correct_answer": "C",
        "explanation": "CPI=EV/AC，小于1表示成本超支",
    }
    w, r = build_trap_row(err)
    assert "选A" in w
    assert "超支" in r or "C" in r


def test_insert_auto_trap_rows() -> None:
    content = """## 七、易错陷阱

| ❌ 错 | ✅ 对 |
|------|------|
| 旧陷阱 | 旧纠正 |

---

## 八、做题决策链
"""
    w, r = "新陷阱（选B）", "应选 D — 先沟通"
    out = _insert_auto_trap_rows(content, [(w, r)], "2026-08-27")
    assert "来自错题本（自动" in out
    assert "新陷阱" in out
    assert _row_key(w, r) in _existing_trap_keys(out)


def test_row_key_dedup() -> None:
    assert _row_key("A", "B") == _row_key("A", "B")
