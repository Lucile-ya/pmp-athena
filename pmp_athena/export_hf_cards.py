#!/usr/bin/env python3
"""Export high-frequency error summary cards to Markdown."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

try:
    from pmp_athena.config import NOTES_DIR
except ModuleNotFoundError:
    from config import NOTES_DIR

try:
    from pmp_athena.error_insights import rank_high_frequency_errors
    from pmp_athena.knowledge_retriever import normalize_area
except ModuleNotFoundError:
    from error_insights import rank_high_frequency_errors
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
    """README 睡前清单：只列题号，不甩半截题干；练题走「复习错题」。"""
    del err_map, link_cards_file
    focus_s = " / ".join(_short_hf_area(a) for a in focus_areas) if focus_areas else "顽疾"
    lines = [
        "## 今日顽疾号（不要读长摘要卡）",
        "",
        f"> {today.month}月{today.day}日 · 当日域：**{focus_s}** · "
        f"共 {len(picked)} 号 · 发「复习错题」做完整题",
        "",
        "| # | 领域 | 错次 |",
        "|:-:|------|:----:|",
    ]
    for it in picked:
        lines.append(
            f"| #{it['error_id']} | {_short_hf_area(it.get('knowledge_area', ''))} "
            f"| **{it.get('mistake_count', '?')}** |"
        )
    if not picked:
        lines.append("| — | 暂无 | — |")
    lines += [
        "",
        "背口诀：[考前攻错决策卡](./00-考前攻错决策卡.md) · "
        "[三领域对比](./00-三领域对比速记卡.md) · `今日速记`",
    ]
    return "\n".join(lines)


def export_cards(
    *,
    top_n: int = 50,
    min_mistakes: int = 3,
    focus_areas: list[str] | None = None,
) -> Path:
    """写入降级占位页（不当教材）。完整题走「复习错题」/今日任务③。"""
    del focus_areas  # 保留签名兼容 sync 调用
    items = rank_high_frequency_errors(top_n=top_n, min_mistakes=min_mistakes)
    stubborn = [
        it for it in items if int(it.get("mistake_count") or 0) >= STUBBORN_MIN
    ]
    ids = " ".join(f"#{it['error_id']}" for it in stubborn[:20]) or "（暂无）"
    lines = [
        "# 高频错题索引（已降级 · 不当教材）",
        "",
        f"> {date.today()} · 错 ≥{min_mistakes} 次共 **{len(items)}** 道"
        f"（≥{STUBBORN_MIN} 次约 **{len(stubborn)}** 道）。",
        "> **不要通读本文件。** 半截题干/口诀错配收益低。",
        "> 要练：发「复习错题」；要背：发「今日速记」或打开 `01–09`。",
        "",
        "## 改看这些",
        "",
        "| 目的 | 去哪 |",
        "|------|------|",
        "| 搞懂跳步骤 | [00-考前攻错决策卡](./00-考前攻错决策卡.md) |",
        "| 30 秒分域 | [00-三领域对比速记卡](./00-三领域对比速记卡.md) |",
        "| 公式/储备/压缩 | [00-P0三领域完整知识点](./00-P0三领域完整知识点.md) |",
        "| 分领域口诀 | [README](./README.md) → `01–09` |",
        "",
        "## 机器仍在用什么",
        "",
        "- 微信「今日任务」③ / 「复习错题」按错次出**完整题**（不经过本 MD）。",
        "- 本文件只占位，避免旧链接 404；不再生成长摘要。",
        "",
        f"错 ≥{STUBBORN_MIN} 次优先过原题：{ids}",
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
