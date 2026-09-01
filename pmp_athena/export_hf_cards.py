#!/usr/bin/env python3
"""Export high-frequency error summary cards to Markdown."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

try:
    from pmp_athena.config import ERROR_LOG_PATH, NOTES_DIR
except ModuleNotFoundError:
    from config import ERROR_LOG_PATH, NOTES_DIR

try:
    from pmp_athena.error_insights import (
        _load_json,
        build_answer_text,
        build_mnemonic,
        build_summary,
        rank_high_frequency_errors,
    )
    from pmp_athena.semantic_anchors import format_anchor_with_cue
except ModuleNotFoundError:
    from error_insights import (
        _load_json,
        build_answer_text,
        build_mnemonic,
        build_summary,
        rank_high_frequency_errors,
    )
    from semantic_anchors import format_anchor_with_cue


def export_cards(*, top_n: int = 50, min_mistakes: int = 3) -> Path:
    items = rank_high_frequency_errors(top_n=top_n, min_mistakes=min_mistakes)
    errors = _load_json(ERROR_LOG_PATH)
    if not isinstance(errors, list):
        errors = []
    err_map = {e["id"]: e for e in errors if e.get("id")}

    lines = [
        "# 🔥 高频错题摘要卡",
        "",
        f"> 生成日期：{date.today()} · 阈值：同一题错 ≥{min_mistakes} 次 · 共 {len(items)} 道",
        "> 用法：考前快速过一遍锚点+口诀，发送「复习错题」逐题巩固",
        "",
        "---",
        "",
    ]

    for i, item in enumerate(items, 1):
        eid = item["error_id"]
        err = err_map.get(eid, {})
        q = re.sub(r"\s+", " ", err.get("question", item["question_preview"])).strip()
        if len(q) > 120:
            q = q[:120] + "…"
        my_a = err.get("my_answer", "?")
        correct = err.get("correct_answer", "?")
        area = item["knowledge_area"]
        cnt = item["mistake_count"]
        try:
            anchor_line = format_anchor_with_cue(err).replace("\n", " / ")
        except Exception:
            anchor_line = ""
        summary = build_summary(err)
        mnemonic = build_mnemonic(err)
        answer = build_answer_text(err)
        if len(answer) > 150:
            answer = answer[:150] + "…"

        lines += [
            f"## {i}. 错题 #{eid} · {area} · 错 {cnt} 次",
            "",
            f"**题干**：{q}",
            "",
            "| 你的错选 | 正确答案 |",
            "|:--------:|:--------:|",
            f"| **{my_a}** | **{correct}** |",
            "",
        ]
        if anchor_line:
            lines += [f"**🔑 锚点**：{anchor_line}", ""]
        lines += [
            f"**📌 总结**：{summary}",
            "",
            f"**🎯 口诀**：{mnemonic}",
            "",
            f"**💡 要点**：{answer}",
            "",
            "---",
            "",
        ]

    out = Path(NOTES_DIR) / "薄弱点速记" / "00-高频错题摘要卡.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="导出高频错题摘要卡")
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--min", type=int, default=3, dest="min_mistakes")
    args = parser.parse_args()
    path = export_cards(top_n=args.top, min_mistakes=args.min_mistakes)
    print(f"✅ 已生成 {path}")


if __name__ == "__main__":
    main()
