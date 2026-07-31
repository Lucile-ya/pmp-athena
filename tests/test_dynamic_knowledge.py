#!/usr/bin/env python3
"""三项知识检索优化单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.dynamic_knowledge import (  # noqa: E402
    handle_message,
    parse_user_message,
    retrieve_knowledge,
    search_entries,
)
from pmp_athena.knowledge_error_linkage import (  # noqa: E402
    find_errors_for_topic,
    format_error_hint,
)
from pmp_athena.knowledge_fuzzy_match import fuzzy_match_query  # noqa: E402
from pmp_athena.knowledge_index_builder import INDEX_PATH  # noqa: E402


def test_index_exists() -> None:
    assert INDEX_PATH.exists(), "请先运行 python build_knowledge_index.py"


def test_fuzzy_match_挣值() -> None:
    hits = search_entries("挣值", limit=3)
    assert hits, "挣值 应匹配到条目"
    names = " ".join(h["name"] for h in hits)
    assert "挣值" in names or "EVM" in names.upper() or "偏差" in names


def test_fuzzy_alias_evm() -> None:
    import json
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    entries = data.get("entries") or []
    fm = fuzzy_match_query("EVM", entries)
    assert fm.score >= 80, f"EVM 应高置信匹配，实际 {fm.score}"


def test_parse_triggers() -> None:
    assert parse_user_message("详细 挣值")["level"] == "L2"
    assert parse_user_message("套路 变更")["level"] == "L3"
    assert parse_user_message("挣值管理知识点") is not None
    assert parse_user_message("全文")["level"] == "L2"


def test_l1_format_and_error_hint() -> None:
    r = retrieve_knowledge("挣值", "L1")
    assert r["status"] == "ok"
    assert "📚" in r["text"]
    # 错题联动：有错题时应有提示（无错题时不强制）
    errors = find_errors_for_topic("挣值", {"name": "挣值", "domain": "成本管理"})
    if errors:
        assert "错题" in r["text"]


def test_error_detail_mode() -> None:
    retrieve_knowledge("成本管理", "L1")
    parsed = parse_user_message("错题")
    assert parsed is not None
    assert parsed.get("mode") == "error_detail"
    r = handle_message("错题")
    assert r["status"] == "ok"
    assert "错题" in r["text"] or "暂无" in r["text"]


def test_error_linkage_module() -> None:
    errors = find_errors_for_topic("干系人")
    assert isinstance(errors, list)
    hint = format_error_hint("干系人", errors)
    if errors:
        assert "⚠️" in hint


def main() -> int:
    if not INDEX_PATH.exists():
        print("⚠️ 跳过：索引不存在，先运行 build_knowledge_index.py")
        return 0
    failed = 0
    tests = [
        ("index_exists", test_index_exists),
        ("fuzzy_match_挣值", test_fuzzy_match_挣值),
        ("fuzzy_alias_evm", test_fuzzy_alias_evm),
        ("parse_triggers", test_parse_triggers),
        ("l1_format_error", test_l1_format_and_error_hint),
        ("error_detail_mode", test_error_detail_mode),
        ("error_linkage", test_error_linkage_module),
    ]
    for name, fn in tests:
        try:
            fn()
            print(f"✅ {name}")
        except AssertionError as e:
            print(f"❌ {name}: {e}")
            failed += 1
    return failed


if __name__ == "__main__":
    sys.exit(main())
