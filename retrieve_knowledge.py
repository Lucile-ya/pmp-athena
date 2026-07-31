#!/usr/bin/env python3
"""动态知识查询 — 部署入口。

示例:
  python retrieve_knowledge.py 挣值
  python retrieve_knowledge.py 挣值 --level L2
  python retrieve_knowledge.py --message "详细 挣值"
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pmp_athena.dynamic_knowledge import main

if __name__ == "__main__":
    main()
