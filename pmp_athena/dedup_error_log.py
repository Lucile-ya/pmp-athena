#!/usr/bin/env python3
"""
合并 error_log 中题干重复的错题，保留一条 canonical id，更新关联引用。

规则：
  - 按规范化题干前 50 字分组
  - 保留组内 id 最小且题干更完整（更长）的一条；同长度保留较小 id
  - question_bank.error_log_id 重指向
  - error_review_state 合并后删除重复 key
  - 删除 error_log 重复条目
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ERROR_LOG = Path("D:/pmp-athena/pmp_notes/error_log.json")
QUESTION_BANK = Path("D:/pmp-athena/pmp_notes/question_bank.json")
REVIEW_STATE = Path("D:/pmp-athena/pmp_notes/error_review_state.json")

try:
    from pmp_athena.utils.question_text import normalize_question_text, question_dedup_key
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from utils.question_text import normalize_question_text, question_dedup_key


def _pick_canonical(records: list[dict]) -> dict:
    """同组内选保留条目：题干更长者优先，否则 id 更小者优先。"""
    return max(records, key=lambda r: (len(r.get("question", "")), -r["id"]))


def _merge_review(canonical_id: int, remove_id: int, state: dict) -> None:
    ck, rk = str(canonical_id), str(remove_id)
    if rk not in state:
        return
    if ck not in state:
        state[ck] = state[rk]
        state[ck]["error_id"] = canonical_id
    else:
        # 保留复习进度更 advanced 的（repetitions 更高或 history 更长）
        c, r = state[ck], state[rk]
        if len(r.get("history", [])) > len(c.get("history", [])):
            state[ck] = r
            state[ck]["error_id"] = canonical_id
        state[ck]["error_id"] = canonical_id
    del state[rk]


def dedup_error_log(*, dry_run: bool = False) -> list[tuple[int, int]]:
    errors: list[dict] = json.loads(ERROR_LOG.read_text(encoding="utf-8"))
    bank: list[dict] = json.loads(QUESTION_BANK.read_text(encoding="utf-8"))
    review: dict = json.loads(REVIEW_STATE.read_text(encoding="utf-8"))

    groups: dict[str, list[dict]] = {}
    for e in errors:
        key = question_dedup_key(e.get("question", ""))
        groups.setdefault(key, []).append(e)

    merges: list[tuple[int, int]] = []  # (keep_id, remove_id)
    remove_ids: set[int] = set()

    for key, items in groups.items():
        if len(items) < 2:
            continue
        keep = _pick_canonical(items)
        for item in items:
            if item["id"] == keep["id"]:
                continue
            merges.append((keep["id"], item["id"]))
            remove_ids.add(item["id"])
            # 合并字段：canonical 用更完整题干
            if len(item.get("question", "")) > len(keep.get("question", "")):
                keep["question"] = normalize_question_text(item["question"])

    if not merges:
        print("✅ 无重复错题")
        return []

    print(f"发现 {len(merges)} 组重复，将合并：")
    for keep_id, rem_id in merges:
        print(f"  保留 #{keep_id}，删除 #{rem_id}")

    if dry_run:
        return merges

    # 应用 question_bank 重指向
    bank_updates = 0
    for rec in bank:
        eid = rec.get("error_log_id")
        if eid in remove_ids:
            # 找到该 remove_id 对应的 keep_id
            keep_id = next(k for k, r in merges if r == eid)
            rec["error_log_id"] = keep_id
            bank_updates += 1

    # 应用 review_state
    for keep_id, rem_id in merges:
        _merge_review(keep_id, rem_id, review)

    # 重建 error_log
    id_map = {rem: keep for keep, rem in merges}
    new_errors = []
    for e in errors:
        if e["id"] in remove_ids:
            continue
        new_errors.append(e)

    ERROR_LOG.write_text(
        json.dumps(new_errors, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    QUESTION_BANK.write_text(
        json.dumps(bank, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    REVIEW_STATE.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"💾 已删除 error_log {len(remove_ids)} 条，更新 question_bank {bank_updates} 条")
    return merges


def main():
    dry = "--dry-run" in sys.argv
    dedup_error_log(dry_run=dry)


if __name__ == "__main__":
    main()
