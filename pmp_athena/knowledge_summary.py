#!/usr/bin/env python3
"""兼容入口 — 逻辑已迁移至 knowledge_retriever.py。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pmp_athena.knowledge_retriever import (  # noqa: F401
    is_knowledge_retrieval_request,
    is_knowledge_summary_request,
    parse_knowledge_request,
    retrieve_area,
    retrieve_from_text,
    summarize_area,
    summarize_from_text,
)

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "summarize":
        sys.argv[1] = "retrieve"
    from pmp_athena.knowledge_retriever import main

    main()
