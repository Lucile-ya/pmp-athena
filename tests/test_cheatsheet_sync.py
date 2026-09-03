#!/usr/bin/env python3
"""cheatsheet_sync 单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import date

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


def test_extract_mnemonic_bold_label() -> None:
    from pmp_athena.cheatsheet_sync import extract_mnemonic

    md = "> **你的数据**：错误率 **67%**\n> **总口诀**：**挣值先算 EV，储备分应急和管理**\n"
    assert extract_mnemonic(md) == "挣值先算 EV，储备分应急和管理"


def test_build_recitation_plan_sprint() -> None:
    from datetime import date

    from pmp_athena.cheatsheet_sync import build_recitation_plan

    ranked = [
        ("🔴 P0", "02", "成本管理"),
        ("🔴 P0", "05", "进度管理"),
        ("🟡 P1", "09", "范围管理"),
        ("🟢 P2", "01", "商业环境"),
    ]
    plan = build_recitation_plan(ranked, d_day=9, today=date(2026, 9, 3))
    assert plan.startswith("## 考前 9 天背诵计划")
    assert "02 成本管理" in plan
    assert "商业环境" not in plan.split("**考前加练**")[0]
    assert "`专项 成本管理`" in plan

    sep4 = build_recitation_plan(ranked, d_day=8, today=date(2026, 9, 4))
    first_row = [ln for ln in sep4.splitlines() if ln.startswith("| D1 |")][0]
    assert "进度管理" in first_row
    assert "成本管理" not in first_row


def test_sprint_slot_rotates_by_dday() -> None:
    from pmp_athena.cheatsheet_sync import sprint_slot, today_focus_areas

    ranked = [
        ("🔴 P0", "02", "成本管理"),
        ("🔴 P0", "05", "进度管理"),
        ("🟡 P1", "09", "范围管理"),
        ("🟢 P2", "01", "商业环境"),
    ]
    assert today_focus_areas(ranked, 9)[0] == "成本管理"
    assert today_focus_areas(ranked, 8)[0] == "进度管理"
    assert today_focus_areas(ranked, 7)[0] == "范围管理"
    assert sprint_slot(ranked, 1)["kind"] == "finale"
    assert sprint_slot(ranked, 1)["area"] is None


def test_pick_daily_hf_cards_focus_then_stubborn() -> None:
    from pmp_athena.export_hf_cards import pick_daily_hf_cards

    items = [
        {"error_id": 1, "mistake_count": 3, "knowledge_area": "成本管理", "question_preview": "成本A"},
        {"error_id": 2, "mistake_count": 8, "knowledge_area": "风险管理", "question_preview": "风险B"},
        {"error_id": 3, "mistake_count": 3, "knowledge_area": "干系人管理", "question_preview": "干系人C"},
        {"error_id": 4, "mistake_count": 4, "knowledge_area": "敏捷", "question_preview": "敏捷D"},
    ]
    picked = pick_daily_hf_cards(items, ["成本管理", "进度管理"], limit=3)
    ids = [x["error_id"] for x in picked]
    assert ids[0] == 1
    assert 2 in ids and 4 in ids
    assert 3 not in ids


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


def test_ensure_daily_sync_once_per_day(tmp_path, monkeypatch) -> None:
    import pmp_athena.cheatsheet_sync as cs

    sync_state = tmp_path / ".sync_state.json"
    sync_state.write_text('{"last_daily_refresh": "2099-01-01"}', encoding="utf-8")
    monkeypatch.setattr(cs, "SYNC_STATE_PATH", sync_state)

    calls: list[str] = []

    def fake_sync_all(**kwargs) -> cs.SyncResult:
        calls.append("sync")
        return cs.SyncResult(readme_updated=True)

    monkeypatch.setattr(cs, "sync_all", fake_sync_all)

    assert cs.ensure_daily_sync() is not None
    assert calls == ["sync"]

    sync_state.write_text(
        f'{{"last_daily_refresh": "{date.today().isoformat()}"}}',
        encoding="utf-8",
    )
    assert cs.ensure_daily_sync() is None
    assert calls == ["sync"]


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
