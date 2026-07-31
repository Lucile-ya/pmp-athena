#!/usr/bin/env python3
"""构建 PMP 知识点索引 — 部署入口。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pmp_athena.knowledge_index_builder import main

if __name__ == "__main__":
    main()
