#!/usr/bin/env python3
"""模考 PDF 完整性审计 — 题量 / 选项 / 答案 / 解析。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.mock_exam_engine import (  # noqa: E402
    MOCK_DIR,
    PAPER_FILES,
    PAPER_MAP,
    PAPER_QIJI,
    PAPER_TEXT,
    _parse_text_pdf,
    load_qiji_mock_exam,
    load_scanned_mock_exam,
    load_text_mock_exam,
)


def _audit_questions(questions: list[dict], *, expect: int = 180) -> dict:
    total = len(questions)
    no_answer = [i + 1 for i, q in enumerate(questions) if not str(q.get("correct_answer", "")).strip()]
    no_expl = [i + 1 for i, q in enumerate(questions) if not str(q.get("explanation", "")).strip()]
    bad_opts: list[tuple[int, int]] = []
    short_stem: list[int] = []
    for i, q in enumerate(questions):
        opts = q.get("options") or []
        n_opts = len(opts) if isinstance(opts, list) else 0
        if n_opts < 4:
            bad_opts.append((i + 1, n_opts))
        stem = str(q.get("question") or "")
        if len(stem) < 15:
            short_stem.append(i + 1)
    return {
        "total": total,
        "expect": expect,
        "count_ok": total >= expect,
        "with_answer": total - len(no_answer),
        "with_explanation": total - len(no_expl),
        "missing_answer": no_answer[:20],
        "missing_explanation": no_expl[:20],
        "bad_options": bad_opts[:20],
        "short_stem": short_stem[:10],
    }


def audit_wired_papers() -> list[dict]:
    rows: list[dict] = []
    for key, label in PAPER_MAP.items():
        if key == "random":
            continue
        row: dict = {"key": key, "label": label, "wired": True}
        if key in PAPER_TEXT:
            pdf = PAPER_TEXT[key]
            row["type"] = "文字版"
            row["pdf"] = pdf
            row["pdf_exists"] = (MOCK_DIR / pdf).exists()
            qs = load_text_mock_exam(key) if row["pdf_exists"] else []
        elif key in PAPER_QIJI:
            q_pdf, a_pdf = PAPER_QIJI[key]
            row["type"] = "骐迹双PDF"
            row["pdf"] = q_pdf
            row["answer_pdf"] = a_pdf
            row["pdf_exists"] = (MOCK_DIR / q_pdf).exists()
            row["answer_exists"] = (MOCK_DIR / a_pdf).exists()
            qs = load_qiji_mock_exam(key) if row["pdf_exists"] else []
        elif key in PAPER_FILES:
            q_pdf, a_pdf = PAPER_FILES[key]
            row["type"] = "扫描版"
            row["pdf"] = q_pdf
            row["answer_pdf"] = a_pdf
            row["pdf_exists"] = (MOCK_DIR / q_pdf).exists()
            row["answer_exists"] = (MOCK_DIR / a_pdf).exists()
            qs = load_scanned_mock_exam(key) if row["pdf_exists"] else []
        else:
            row["type"] = "未配置"
            row["wired"] = False
            qs = []
        if qs:
            row.update(_audit_questions(qs))
        else:
            row["total"] = 0
            row["count_ok"] = False
        rows.append(row)
    return rows


def audit_unwired_pdfs() -> list[dict]:
    wired_names = set(PAPER_TEXT.values())
    wired_names |= {q for q, _ in PAPER_FILES.values()}
    wired_names |= {a for _, a in PAPER_FILES.values()}

    rows: list[dict] = []
    for pdf in sorted(MOCK_DIR.glob("*.pdf")):
        name = pdf.name
        if name in wired_names:
            continue
        if "答案" in name or "解析" in name or "参考" in name:
            continue
        row: dict = {"pdf": name, "wired": False, "pdf_exists": True}
        # 尝试文字版解析
        qs = _parse_text_pdf(pdf)
        if len(qs) >= 50:
            row["type"] = "文字版(未接入)"
            row.update(_audit_questions(qs))
        else:
            row["type"] = "未接入/需OCR"
            row["total"] = len(qs)
            row["count_ok"] = False
            row["note"] = f"文字解析仅 {len(qs)} 题，尚未接入模考引擎"
        rows.append(row)
    return rows


def format_report(wired: list[dict], unwired: list[dict]) -> str:
    lines = ["📋 模考 PDF 完整性审计", "═" * 30, ""]

    ok = 0
    for r in wired:
        icon = "✅" if r.get("count_ok") and r.get("with_answer", 0) >= 180 else "❌"
        if icon == "✅":
            ok += 1
        lines.append(f"{icon} 【{r['label']}】({r.get('type', '?')})")
        if not r.get("pdf_exists", True):
            lines.append(f"   ⚠️ 缺少 PDF: {r.get('pdf')}")
            if r.get("answer_pdf"):
                lines.append(f"   ⚠️ 答案 PDF: {'有' if r.get('answer_exists') else '缺'}")
            lines.append("")
            continue
        total = r.get("total", 0)
        ans = r.get("with_answer", 0)
        expl = r.get("with_explanation", 0)
        lines.append(f"   题量: {total}/180 | 有答案: {ans} | 有解析: {expl}")
        if r.get("missing_answer"):
            lines.append(f"   ⚠️ 缺答案题号: {r['missing_answer'][:10]}{'…' if len(r['missing_answer']) > 10 else ''}")
        if r.get("missing_explanation"):
            n = len(r.get("missing_explanation", []))
            lines.append(f"   ⚠️ 缺解析: {n} 题（前10: {r['missing_explanation'][:10]}）")
        if r.get("bad_options"):
            lines.append(f"   ⚠️ 选项不足4个: {r['bad_options'][:5]}")
        if total < 180:
            lines.append(f"   ⚠️ 题量不足，模考时会从每日一练补足至 180")
        lines.append("")

    lines.append(f"已接入试卷: {ok}/{len([x for x in wired if x.get('wired')])} 完整")
    lines.append("")

    if unwired:
        lines.append("📌 目录中未接入的 PDF:")
        for r in unwired:
            lines.append(f"  · {r['pdf']} — {r.get('type')} ({r.get('total', 0)} 题)")
            if r.get("note"):
                lines.append(f"    {r['note']}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    wired = audit_wired_papers()
    unwired = audit_unwired_pdfs()
    if "--json" in sys.argv:
        print(json.dumps({"wired": wired, "unwired": unwired}, ensure_ascii=False, indent=2))
    else:
        print(format_report(wired, unwired))


if __name__ == "__main__":
    main()
