#!/usr/bin/env python3
"""weak_area_cheatsheet 单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.weak_area_cheatsheet import (  # noqa: E402
    DOMAIN_FILES,
    format_wechat_push,
    is_cheatsheet_request,
    parse_cheatsheet_request,
)


def test_parse_triggers() -> None:
    assert parse_cheatsheet_request("薄弱点速记") == ("menu", None)
    assert parse_cheatsheet_request("今日速记") == ("today", None)
    assert parse_cheatsheet_request("速记 商业环境") == ("push", "商业环境")
    assert parse_cheatsheet_request("成本速记") == ("push", "成本管理")
    assert parse_cheatsheet_request("敏捷速记") == ("push", "敏捷/混合方法")
    assert parse_cheatsheet_request("薄弱点") == ("none", None)
    assert parse_cheatsheet_request("成本管理速查") == ("none", None)


def test_is_request() -> None:
    assert is_cheatsheet_request("今日速记")
    assert is_cheatsheet_request("速记 整合管理")
    assert not is_cheatsheet_request("成本管理知识点")


def test_format_push_has_mnemonic() -> None:
    out = format_wechat_push("商业环境")
    assert "商业环境" in out
    assert "总口诀" in out or "论证" in out
    assert "闪卡" in out or "商业论证四要素" in out
    assert len(out) <= 4000


def test_all_domain_files_exist() -> None:
    base = ROOT / "pmp_notes" / "薄弱点速记"
    for area, fname in DOMAIN_FILES.items():
        assert (base / fname).is_file(), f"missing {fname} for {area}"
