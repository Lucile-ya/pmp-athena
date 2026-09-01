#!/usr/bin/env python3
"""cheatsheet_sync 单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.cheatsheet_sync import (  # noqa: E402
    auto_sync_on_new_error,
    build_trap_row,
    flush_cheatsheet_sync,
    schedule_cheatsheet_sync,
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


def test_sync_hf_cards_in_sync_all(tmp_path, monkeypatch) -> None:
    import pmp_athena.cheatsheet_sync as cs

    cheatsheet_dir = tmp_path / "薄弱点速记"
    cheatsheet_dir.mkdir(parents=True)
    readme = cheatsheet_dir / "README.md"
    readme.write_text("## 推荐 7 天背诵计划\n", encoding="utf-8")

    monkeypatch.setattr(cs, "CHEATSHEET_DIR", cheatsheet_dir)
    monkeypatch.setattr(cs, "README_PATH", readme)
    monkeypatch.setattr(cs, "sync_traps_from_errors", lambda **_: cs.SyncResult())
    monkeypatch.setattr(cs, "refresh_domain_headers", lambda **_: 0)
    monkeypatch.setattr(cs, "refresh_readme", lambda **_: True)

    def fake_export(**kwargs):
        return 2, True

    monkeypatch.setattr(cs, "sync_hf_cards", fake_export)

    result = cs.sync_all()
    assert result.hf_cards_count == 2
    assert result.hf_cards_updated is True


def test_auto_sync_defer_and_flush(monkeypatch) -> None:
    import pmp_athena.cheatsheet_sync as cs

    cs._deferred_cheatsheet_sync = False
    calls: list[str] = []

    def fake_sync_all() -> cs.SyncResult:
        calls.append("sync")
        return cs.SyncResult(hf_cards_count=3, hf_cards_updated=True)

    monkeypatch.setattr(cs, "sync_all", fake_sync_all)

    assert auto_sync_on_new_error(error_is_new=False) is None
    assert calls == []

    assert auto_sync_on_new_error(error_is_new=True, defer=False) is not None
    assert calls == ["sync"]

    calls.clear()
    assert auto_sync_on_new_error(error_is_new=True, defer=True) is None
    assert calls == []
    assert flush_cheatsheet_sync() is not None
    assert calls == ["sync"]

    assert flush_cheatsheet_sync() is None
    cs._deferred_cheatsheet_sync = False
