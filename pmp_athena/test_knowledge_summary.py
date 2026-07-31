#!/usr/bin/env python3
"""knowledge_retriever 单元测试（不依赖向量库加载）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.knowledge_retriever import (  # noqa: E402
    is_knowledge_retrieval_request,
    normalize_area,
    parse_knowledge_request,
)


def test_parse_triggers() -> None:
    assert parse_knowledge_request("项目成本管理知识点") == "成本管理"
    assert parse_knowledge_request("知识点 范围管理") == "范围管理"
    assert parse_knowledge_request("总结范围管理") == "范围管理"
    assert parse_knowledge_request("质量管理总结") == "质量管理"
    assert parse_knowledge_request("敏捷有哪些考点") == "敏捷/混合方法"
    assert parse_knowledge_request("考点 风险管理") == "风险管理"
    assert parse_knowledge_request("成本管理速查") == "成本管理"
    assert parse_knowledge_request("每日一练") is None
    assert parse_knowledge_request("薄弱点") is None


def test_normalize_area() -> None:
    assert normalize_area("项目成本管理") == "成本管理"
    assert normalize_area("挣值") == "成本管理"
    assert normalize_area("相关方") == "干系人管理"


def test_is_request() -> None:
    assert is_knowledge_retrieval_request("知识点 沟通管理")
    assert is_knowledge_retrieval_request("进度管理速查")
    assert not is_knowledge_retrieval_request("复习错题")


def main() -> int:
    failed = 0
    for name, fn in [
        ("parse_triggers", test_parse_triggers),
        ("normalize_area", test_normalize_area),
        ("is_request", test_is_request),
    ]:
        try:
            fn()
            print(f"✅ {name}")
        except AssertionError as e:
            print(f"❌ {name}: {e}")
            failed += 1
    return failed


if __name__ == "__main__":
    sys.exit(main())
