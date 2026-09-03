"""根因变式全局去重测试。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.root_cause_variants import (  # noqa: E402
    _normalize_question_stem,
    review_variant_start_v2,
)
from pmp_athena.question_bank import QuestionBank  # noqa: E402


def test_normalize_stem_ignores_ocr_spaces():
    qb = QuestionBank()
    q324 = qb.get_by_id(324)["question"]
    q535 = qb.get_by_id(535)["question"]
    assert _normalize_question_stem(q324) == _normalize_question_stem(q535)


def test_global_dedup_excludes_324_for_other_errors():
    """#35 已攻克 #324 后，#36 不应再推同一题。"""
    r = review_variant_start_v2(36)
    ids = r.get("variant_ids") or []
    assert 324 not in ids
    assert 535 not in ids


if __name__ == "__main__":
    test_normalize_stem_ignores_ocr_spaces()
    test_global_dedup_excludes_324_for_other_errors()
    print("ok")
