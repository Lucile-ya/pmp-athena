#!/usr/bin/env python3
"""
题库质量审计 & 清洗 — 扫描 question_bank.json，标记/过滤低质量题目。

质量维度:
  Q1: 选项完整度 — 至少 3 个 A/B/C/D 标记
  Q2: 内容长度 — 题干 ≥ 30 字
  Q3: 语言一致性 — 中文占比 ≥ 30%（过滤 OCR 英文乱码）
  Q4: 正确答案 — 必须有 correct_answer
  Q5: 选项混乱度 — 不是同一选项重复出现

输出:
  - 每个题目附加 quality_score (0-100) 和 quality_flags
  - 生成清洗报告
  - 可选: 自动标记不合格题为 excluded
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import QUESTION_BANK_PATH
except ModuleNotFoundError:
    from config import QUESTION_BANK_PATH


def _load_bank() -> list[dict]:
    try:
        data = json.loads(QUESTION_BANK_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_bank(bank: list[dict]) -> None:
    QUESTION_BANK_PATH.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")


def _option_markers(text: str) -> list[str]:
    """提取所有选项标记文本（A. xxx / B、xxx 等）。"""
    return re.findall(r'(?:^|\n|\s)([A-D][\.、．\)])\s*(\S[^\n]{0,200})', text)


def _count_options(text: str) -> int:
    """数出 A/B/C/D 选项标记的种类数。"""
    found = set()
    for m in re.finditer(r'(?:^|\n|\s)([A-D])[\.、．\)]\s*\S', text):
        found.add(m.group(1))
    return len(found)


def quality_check(record: dict) -> dict:
    """对单条题库记录做质量打分。返回 {score, flags, details, stage}。

    分级逻辑:
      - 有完整选项 + 正确答案 → A 级（可用作变式题/独立出题）
      - 有正确答案 + 解析 + 合理题干 → B 级（可用于复习/错题分析）
      - 仅有题干无答案无解析 → C 级（仅记录）
      - OCR 残次 / 乱码 → D 级（应排除）
    """
    q = record.get("question", "")
    correct = record.get("correct_answer", "")
    expl = record.get("explanation", "")
    flags = []
    score = 60  # 基础分：能用于复习

    # Q1: 选项完整度
    opt_count = _count_options(q)
    has_inline_options = opt_count >= 3
    if has_inline_options:
        score += 30  # 可用于变式/独立出题
        stage = "full_question"
    else:
        # 无选项但可用于复习（有答案+解析）
        stage = "review_only"

    # Q2: 内容长度（题干太短=残次）
    if len(q) < 20:
        score -= 35
        flags.append(f"Q2:too_short({len(q)}chars)")
        stage = "garbled"
    elif len(q) < 30:
        score -= 10

    # Q3: 中文占比（过滤 OCR 英文乱码）
    cjk_chars = len(re.findall(r'[一-鿿　-〿＀-￯]', q))
    alpha_chars = len(re.findall(r'[a-zA-Z]', q))
    total_chars = max(1, len(q))
    cjk_ratio = cjk_chars / total_chars
    alpha_ratio = alpha_chars / total_chars

    # 真正的 OCR 垃圾：全英文碎片、无中文
    if cjk_chars < 8 and alpha_ratio > 0.5:
        score -= 50
        flags.append(f"Q3:garbled_ocr(cjk={cjk_chars},alpha_ratio={alpha_ratio:.0%})")
        stage = "garbled"

    # Q4: 无正确答案（无法判卷）
    if not correct or correct.strip() == "":
        score -= 25
        flags.append("Q4:no_correct_answer")
        # 连答案都没 → 降级
        if stage == "review_only":
            score -= 10

    # Q5: 选项重复检测
    if has_inline_options:
        seen_letters = set()
        for letter, text in _option_markers(q):
            if letter[0] in seen_letters:
                score -= 10
                flags.append(f"Q5:duplicate_option({letter[0]})")
            seen_letters.add(letter[0])

    return {
        "quality_score": max(0, min(100, score)),
        "stage": stage,
        "quality_flags": flags,
        "details": {
            "option_count": opt_count,
            "text_length": len(q),
            "cjk_chars": cjk_chars,
            "alpha_ratio": round(alpha_ratio, 2),
            "has_correct_answer": bool(correct and correct.strip()),
        },
    }


def quality_grade(score: int) -> str:
    if score >= 80: return "A"
    if score >= 60: return "B"
    if score >= 40: return "C"
    return "D"


def audit_full(bank: list[dict] | None = None) -> dict:
    """全量审计，返回统计报告。"""
    if bank is None:
        bank = _load_bank()

    total = len(bank)
    grades = {"A": 0, "B": 0, "C": 0, "D": 0}
    flagged: dict[str, list[int]] = {}

    for r in bank:
        qc = quality_check(r)
        qid = r.get("id", "?")
        grade = quality_grade(qc["quality_score"])
        grades[grade] += 1
        for flag in qc["quality_flags"]:
            flagged.setdefault(flag, []).append(qid)

    return {
        "total": total,
        "grades": grades,
        "a_pct": grades["A"] / max(1, total) * 100,
        "b_pct": grades["B"] / max(1, total) * 100,
        "c_pct": grades["C"] / max(1, total) * 100,
        "d_pct": grades["D"] / max(1, total) * 100,
        "flagged": {k: v for k, v in sorted(flagged.items(), key=lambda x: -len(x[1]))},
    }


def mark_excluded(bank: list[dict]) -> int:
    """仅标记 stage='garbled'（真正 OCR 残次）的题为 excluded。返回标记数。"""
    count = 0
    for r in bank:
        qc = quality_check(r)
        r["quality_score"] = qc["quality_score"]
        r["quality_stage"] = qc["stage"]
        r["quality_grade"] = quality_grade(qc["quality_score"])
        if qc["stage"] == "garbled":
            r["excluded"] = True
            count += 1
        elif "excluded" in r:
            # Remove previous exclusion if quality improved
            del r["excluded"]
    return count


def clean_and_save() -> dict:
    """全量审计 + 标记残次题 + 持久化。返回报告。"""
    bank = _load_bank()
    marked = mark_excluded(bank)
    _save_bank(bank)
    return {
        "total": len(bank),
        "marked_excluded": marked,
        "clean": len(bank) - marked,
    }


def format_report() -> str:
    """格式化质量审计报告。"""
    bank = _load_bank()
    audit = audit_full(bank)

    # Stage breakdown
    stages = {"full_question": 0, "review_only": 0, "garbled": 0}
    for r in bank:
        qc = quality_check(r)
        s = qc.get("stage", "review_only")
        stages[s] = stages.get(s, 0) + 1

    lines = [
        "📋 题库质量审计报告",
        "══════════════════",
        "",
        f"📊 总计: {audit['total']} 题",
        "",
        "### 用途分级",
        f"  🟢 完整题（可出题+变式）: {stages.get('full_question', 0)} 题",
        f"  🟡 复习题（可复习无选项）: {stages.get('review_only', 0)} 题",
        f"  🔴 残次题（应排除）: {stages.get('garbled', 0)} 题",
        "",
        "### 质量等级",
        f"  A (≥80): {audit['grades']['A']} | B (60-79): {audit['grades']['B']} | C (40-59): {audit['grades']['C']} | D (<40): {audit['grades']['D']}",
        "",
        "### 主要问题",
    ]

    for flag, ids in audit["flagged"].items():
        lines.append(f"  · {flag}: {len(ids)} 题")

    # Show garbled samples
    garbled_items = []
    for r in bank:
        qc = quality_check(r)
        if qc.get("stage") == "garbled":
            garbled_items.append((qc["quality_score"], r.get("id"), r.get("question", "")[:80]))

    if garbled_items:
        garbled_items.sort(key=lambda x: x[0])
        lines.append("")
        lines.append("### 🔴 OCR 残次题样本")
        for score, qid, preview in garbled_items[:5]:
            lines.append(f"  #{qid} (score={score}): {preview}...")
    else:
        lines.append("")
        lines.append("✅ 无 OCR 残次题！")

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────


def main():
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="题库质量审计 & 清洗")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("audit", help="生成质量审计报告（只读）")
    sub.add_parser("audit-json", help="JSON 格式审计报告")

    p_clean = sub.add_parser("clean", help="标记 OCR 残次题 + 持久化质量字段")
    p_clean.add_argument("--dry-run", action="store_true", help="预览不写入")

    p_bad = sub.add_parser("list-bad", help="列出所有低质量题 ID")
    p_bad.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    if args.cmd == "audit":
        print(format_report())

    elif args.cmd == "audit-json":
        audit = audit_full()
        print(json.dumps(audit, ensure_ascii=False))

    elif args.cmd == "clean":
        bank = _load_bank()
        marked = mark_excluded(bank)
        report = {"total": len(bank), "marked_excluded": marked}
        if not args.dry_run:
            _save_bank(bank)
            print(json.dumps(report, ensure_ascii=False))
        else:
            print(f"[DRY RUN] Would mark {marked}/{len(bank)} as excluded (threshold={args.threshold})")
            # Show what would be excluded
            for r in bank:
                if r.get("excluded"):
                    q = r.get("question", "")[:80]
                    print(f"  #{r.get('id')}: {q}...")

    elif args.cmd == "list-bad":
        bank = _load_bank()
        bad = []
        for r in bank:
            qc = quality_check(r)
            if quality_grade(qc["quality_score"]) in ("C", "D"):
                bad.append((qc["quality_score"], r))
        bad.sort(key=lambda x: x[0])
        for score, r in bad[:args.limit]:
            q = r.get("question", "")[:100]
            flags = ", ".join(r.get("quality_flags", [qc["quality_flags"][:2]]))
            print(f"  #{r.get('id')} score={score}: {q}...")
            print(f"        flags: {flags}")


if __name__ == "__main__":
    main()
