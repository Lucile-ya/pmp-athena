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
    from pmp_athena.knowledge_retriever import normalize_area
except ModuleNotFoundError:
    from error_insights import (
        _load_json,
        build_answer_text,
        build_mnemonic,
        build_summary,
        rank_high_frequency_errors,
    )
    from semantic_anchors import format_anchor_with_cue
    from knowledge_retriever import normalize_area

STUBBORN_MIN = 4
DAILY_HF_LIMIT = 10


def _norm_hf_area(raw: str) -> str:
    return normalize_area(raw) or (raw or "未分类")


def _short_hf_area(raw: str) -> str:
    area = _norm_hf_area(raw)
    return "敏捷" if area.startswith("敏捷") else area


def pick_daily_hf_cards(
    items: list[dict],
    focus_areas: list[str] | None,
    *,
    stubborn_min: int = STUBBORN_MIN,
    limit: int = DAILY_HF_LIMIT,
) -> list[dict]:
    """当日领域全部 + 错≥4 次顽疾补足，上限 limit。"""
    focus = {_norm_hf_area(a) for a in (focus_areas or []) if a}
    picked: list[dict] = []
    seen: set[int] = set()

    def _add(it: dict) -> None:
        eid = it.get("error_id")
        if not isinstance(eid, int) or eid in seen:
            return
        seen.add(eid)
        picked.append(it)

    for it in items:
        if _norm_hf_area(it.get("knowledge_area", "")) in focus:
            _add(it)
    for it in items:
        if len(picked) >= limit:
            break
        if int(it.get("mistake_count") or 0) >= stubborn_min:
            _add(it)
    return picked[:limit]


def format_daily_hf_table(
    picked: list[dict],
    err_map: dict,
    *,
    focus_areas: list[str],
    today: date,
    link_cards_file: bool = False,
) -> str:
    focus_s = " / ".join(_short_hf_area(a) for a in focus_areas) if focus_areas else "顽疾"
    href = "./00-高频错题摘要卡.md" if link_cards_file else ""
    lines = [
        "## 今日推荐摘要卡（10分钟）",
        "",
        f"> {today.month}月{today.day}日 · 当日领域：**{focus_s}** · 含错 ≥{STUBBORN_MIN} 次顽疾 · 共 {len(picked)} 道  ",
        "> 口诀出声念一遍即可，不必重做选项",
        "",
        "| # | 领域 | 错次 | 口诀 | 题干 |",
        "|:-:|------|:----:|------|------|",
    ]
    for it in picked:
        eid = it["error_id"]
        err = err_map.get(eid, {})
        mnemonic = build_mnemonic(err) if err else "—"
        mnemonic = re.sub(r"\s+", " ", mnemonic).strip()
        if len(mnemonic) > 24:
            mnemonic = mnemonic[:23] + "…"
        gist = re.sub(r"\s+", " ", it.get("question_preview") or "").strip()
        if len(gist) > 30:
            gist = gist[:29] + "…"
        area = _short_hf_area(it.get("knowledge_area", ""))
        num = f"[#{eid}]({href})" if href else f"#{eid}"
        lines.append(
            f"| {num} | {area} | **{it.get('mistake_count', '?')}** | {mnemonic} | {gist} |"
        )
    if not picked:
        lines.append("| — | — | — | 暂无高频卡 | 先发「复习错题」积累 |")
    return "\n".join(lines)


def export_cards(
    *,
    top_n: int = 50,
    min_mistakes: int = 3,
    focus_areas: list[str] | None = None,
) -> Path:
    items = rank_high_frequency_errors(top_n=top_n, min_mistakes=min_mistakes)
    errors = _load_json(ERROR_LOG_PATH)
    if not isinstance(errors, list):
        errors = []
    err_map = {e["id"]: e for e in errors if e.get("id")}

    picked = pick_daily_hf_cards(items, focus_areas)
    daily_table = format_daily_hf_table(
        picked,
        err_map,
        focus_areas=focus_areas or [],
        today=date.today(),
        link_cards_file=False,
    )

    index_rows = [
        "## 全部索引",
        "",
        "| 序 | # | 领域 | 错次 | 题干 |",
        "|:--:|:-:|------|:----:|------|",
    ]
    for i, item in enumerate(items, 1):
        gist = re.sub(r"\s+", " ", item.get("question_preview") or "").strip()
        if len(gist) > 32:
            gist = gist[:31] + "…"
        index_rows.append(
            f"| {i} | #{item['error_id']} | {_short_hf_area(item.get('knowledge_area', ''))} "
            f"| **{item['mistake_count']}** | {gist} |"
        )

    lines = [
        "# 🔥 高频错题摘要卡",
        "",
        f"> 生成日期：{date.today()} · 阈值：同一题错 ≥{min_mistakes} 次 · 共 {len(items)} 道",
        "> 用法：先过「今日推荐」10 分钟 → 考前再刷全部索引",
        "",
        daily_table,
        "",
        "---",
        "",
        *index_rows,
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
