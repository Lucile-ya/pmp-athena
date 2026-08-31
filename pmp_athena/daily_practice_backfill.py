#!/usr/bin/env python3
"""
每日一练历史补录 — 从 PDF + 答案串批量写入 question_bank / error_log。

用法:
  python pmp_athena/daily_practice_backfill.py scan --from 2026-07-16 --to 2026-07-20
  python pmp_athena/daily_practice_backfill.py template --from 2026-07-16 --to 2026-07-20
  python pmp_athena/daily_practice_backfill.py run --answers-file pmp_notes/daily_backfill_answers.json
  python pmp_athena/daily_practice_backfill.py run --date 2026-07-16 --answers BCBABACBCA
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import NOTES_DIR
    from pmp_athena.daily_practice import (
        DAILY_DIR,
        _format_options,
        _normalize_answer_text,
        load_questions_for_date,
    )
    from pmp_athena.question_bank import QuestionBank
    from pmp_athena.record_answer import record_correct_answer, record_wrong_answer
    from pmp_athena.utils.question_text import normalize_question_text, question_dedup_key
except ModuleNotFoundError:
    from config import NOTES_DIR
    from daily_practice import (
        DAILY_DIR,
        _format_options,
        _normalize_answer_text,
        load_questions_for_date,
    )
    from question_bank import QuestionBank
    from record_answer import record_correct_answer, record_wrong_answer
    from utils.question_text import normalize_question_text, question_dedup_key

DEFAULT_ANSWERS_PATH = NOTES_DIR / "daily_backfill_answers.json"
YEAR = 2026


def _parse_iso(s: str) -> date:
    return date.fromisoformat(s)


def _iter_dates(start: date, end: date) -> list[date]:
    out: list[date] = []
    d = start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def _question_key(q: dict[str, Any]) -> str:
    return question_dedup_key(normalize_question_text(q.get("stem", "")))


def _find_pdf_files(d: date) -> list[Path]:
    label = f"{d.month}月{d.day}日"
    files: list[Path] = []
    if not DAILY_DIR.exists():
        return files
    for f in DAILY_DIR.glob("*.pdf"):
        if label in f.name:
            files.append(f)
    return sorted(files)


def _bank_stats(bank: QuestionBank) -> dict[str, Any]:
    records = bank.list_all()
    graded = [r for r in records if r.get("is_correct") is not None]
    correct = sum(1 for r in graded if r.get("is_correct"))
    total = len(graded)
    acc = round(correct / total * 100, 1) if total else 0.0
    by_area: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in graded:
        a = r.get("knowledge_area") or "综合"
        by_area[a]["total"] += 1
        if r.get("is_correct"):
            by_area[a]["correct"] += 1
    return {"total": total, "correct": correct, "accuracy": acc, "by_area": dict(by_area)}


def _area_accuracy(area_stats: dict[str, dict[str, int]], area: str) -> float | None:
    s = area_stats.get(area)
    if not s or not s["total"]:
        return None
    return round(s["correct"] / s["total"] * 100, 1)


def _patch_bank_date(bank: QuestionBank, bank_id: int, record_date: str) -> None:
    data = bank._read()
    for r in data:
        if r.get("id") == bank_id:
            r["date"] = record_date
            r["last_review_date"] = record_date
            ts = r.get("timestamp", "")
            if ts and "T" in ts:
                r["timestamp"] = f"{record_date}T{ts.split('T', 1)[1]}"
            else:
                r["timestamp"] = f"{record_date}T12:00:00"
            bank._write(data)
            return


def _split_user_answers(raw: str, questions: list[dict[str, Any]]) -> list[str]:
    """按题序拆分用户答案；多选题占一个槽位。"""
    raw = raw.strip().upper().replace(",", "").replace(" ", "")
    if not raw:
        return []
    # 若长度与题数一致且全为单选字母
    if len(raw) == len(questions) and all(
        q.get("question_type", "single") == "single" for q in questions
    ):
        return list(raw)
    # 含多选：按题逐个匹配 A-E 串
    answers: list[str] = []
    i = 0
    for q in questions:
        if q.get("question_type") == "multi":
            # 贪心：从长到短尝试匹配正确答案长度或 2-5 字母
            matched = ""
            for length in range(min(5, len(raw) - i), 1, -1):
                chunk = raw[i : i + length]
                if re.fullmatch(r"[A-E]+", chunk):
                    matched = chunk
                    break
            if not matched and i < len(raw):
                matched = raw[i]
            answers.append(matched)
            i += len(matched)
        else:
            if i >= len(raw):
                answers.append("")
            else:
                answers.append(raw[i])
                i += 1
    return answers


def _compare_answer(user: str, correct: str, *, multi: bool) -> bool:
    u = _normalize_answer_text(user, multi=multi)
    c = _normalize_answer_text(correct, multi=multi)
    return bool(u) and u == c


def scan_range(*, start: date, end: date) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    bank = QuestionBank()
    existing_keys = {question_dedup_key(r.get("question", "")) for r in bank.list_all()}

    for d in _iter_dates(start, end):
        pdfs = _find_pdf_files(d)
        row: dict[str, Any] = {
            "date": d.isoformat(),
            "pdf_files": [p.name for p in pdfs],
            "question_count": 0,
            "already_in_bank": 0,
            "missing_pdf": not any("答案" not in p.name for p in pdfs),
        }
        try:
            qs = load_questions_for_date(d)
            row["question_count"] = len(qs)
            row["already_in_bank"] = sum(1 for q in qs if _question_key(q) in existing_keys)
            row["parse_ok"] = True
        except (FileNotFoundError, ValueError) as e:
            row["parse_ok"] = False
            row["error"] = str(e)
        rows.append(row)

    return {"start": start.isoformat(), "end": end.isoformat(), "rows": rows}


def build_template(*, start: date, end: date) -> dict[str, Any]:
    payload: dict[str, str] = {}
    meta: dict[str, Any] = {}
    for d in _iter_dates(start, end):
        iso = d.isoformat()
        try:
            qs = load_questions_for_date(d)
            meta[iso] = {
                "count": len(qs),
                "correct_key": "".join(q.get("correct_answer", "") for q in qs),
            }
            payload[iso] = ""
        except (FileNotFoundError, ValueError):
            payload[iso] = ""
            meta[iso] = {"count": 0, "error": "no_pdf"}
    return {
        "description": "填写每日一练答案串，如 2026-07-16: BCBABACBCA；留空则跳过该日",
        "answers": payload,
        "_meta_correct_keys_for_reference": meta,
    }


def run_backfill(
    *,
    start: date,
    end: date,
    answers_map: dict[str, str],
    redate_existing: bool = True,
    dry_run: bool = False,
    insert_only: bool = True,
) -> dict[str, Any]:
    bank = QuestionBank()
    before = _bank_stats(bank)

    scanned_files: set[str] = set()
    extracted = 0
    skipped_dup = 0
    inserted = 0
    wrong_count = 0
    redate_count = 0
    area_added: dict[str, int] = defaultdict(int)
    unparsed: list[str] = []
    missing_answers: list[str] = []

    for d in _iter_dates(start, end):
        iso = d.isoformat()
        pdfs = _find_pdf_files(d)
        for p in pdfs:
            scanned_files.add(p.name)

        user_key = (answers_map.get(iso) or "").strip()
        try:
            questions = load_questions_for_date(d)
        except FileNotFoundError:
            if pdfs:
                unparsed.append(f"{iso}: 缺少题目 PDF")
            continue
        except ValueError as e:
            unparsed.append(f"{iso}: {e}")
            continue

        extracted += len(questions)
        user_answers = _split_user_answers(user_key, questions) if user_key else []

        for idx, q in enumerate(questions):
            qkey = _question_key(q)
            existing = bank.find_by_question(q.get("stem", ""))
            multi = q.get("question_type") == "multi"
            correct = str(q.get("correct_answer", "")).upper()

            if existing:
                if redate_existing and existing.get("date") != iso:
                    if not dry_run:
                        _patch_bank_date(bank, existing["id"], iso)
                    redate_count += 1
                else:
                    skipped_dup += 1
                continue

            if not insert_only:
                continue

            if not user_answers or idx >= len(user_answers) or not user_answers[idx]:
                missing_answers.append(f"{iso} Q{q.get('index', idx+1)}")
                continue

            my_answer = user_answers[idx]
            is_correct = _compare_answer(my_answer, correct, multi=multi)
            area = q.get("knowledge_area", "综合")

            if dry_run:
                inserted += 1
                if not is_correct:
                    wrong_count += 1
                area_added[area] += 1
                continue

            kwargs = dict(
                question=q["stem"],
                my_answer=my_answer,
                correct_answer=correct,
                knowledge_area=area,
                explanation=q.get("explanation", ""),
                source="daily_practice",
                parsed_by="daily_practice_backfill.py",
            )
            if is_correct:
                result = record_correct_answer(**kwargs)
            else:
                result = record_wrong_answer(**kwargs, defer_cheatsheet_sync=True)
                wrong_count += 1

            _patch_bank_date(bank, result["bank_id"], iso)
            inserted += 1
            area_added[area] += 1

    if not dry_run and wrong_count > 0:
        try:
            from pmp_athena.cheatsheet_sync import flush_cheatsheet_sync
        except ModuleNotFoundError:
            from cheatsheet_sync import flush_cheatsheet_sync
        try:
            flush_cheatsheet_sync(silent=True)
        except Exception:
            pass

    after = _bank_stats(bank if not dry_run else QuestionBank())

    # 领域变化（示例领域）
    area_changes: list[str] = []
    for area in sorted(set(before["by_area"]) | set(after["by_area"]) | set(area_added)):
        ba = _area_accuracy(before["by_area"], area)
        aa = _area_accuracy(after["by_area"], area)
        added = area_added.get(area, 0)
        if added or (ba is not None and aa is not None and ba != aa):
            if ba is None:
                area_changes.append(f"  - {area}：新增 {added} 题")
            else:
                area_changes.append(
                    f"  - {area}：{ba}% → {aa}%（补充 {added} 题）"
                )

    lines = [
        "📊 补录完成报告",
        f"✅ 扫描文件：{len(scanned_files)} 个",
        f"✅ 提取题目：{extracted} 题",
        f"✅ 去重跳过：{skipped_dup} 题",
        f"✅ 修正日期：{redate_count} 题",
        f"✅ 新增录入：{inserted} 题",
        f"✅ 其中错题：{wrong_count} 题",
        "",
        "📈 更新后的总览：",
        f"- 总刷题量：{before['total']} → {after['total']} 题",
        f"- 总正确率：{before['accuracy']}% → {after['accuracy']}%",
    ]
    if area_changes:
        lines.append("- 领域正确率变化：")
        lines.extend(area_changes[:8])

    if missing_answers:
        lines.append("")
        lines.append(f"⚠️ 缺少用户答案（{len(missing_answers)} 题），未录入：")
        for item in missing_answers[:10]:
            lines.append(f"  · {item}")
        if len(missing_answers) > 10:
            lines.append(f"  · ...还有 {len(missing_answers) - 10} 题")

    if unparsed:
        lines.append("")
        lines.append("⚠️ 无法解析的文件/日期：")
        for u in unparsed:
            lines.append(f"  · {u}")

    return {
        "before": before,
        "after": after,
        "inserted": inserted,
        "skipped_dup": skipped_dup,
        "redate_count": redate_count,
        "wrong_count": wrong_count,
        "missing_answers": missing_answers,
        "unparsed": unparsed,
        "text": "\n".join(lines),
    }


def _load_answers_file(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "answers" in data:
        return {str(k): str(v or "") for k, v in data["answers"].items()}
    if isinstance(data, dict):
        return {str(k): str(v or "") for k, v in data.items()}
    raise ValueError("answers 文件格式应为 {\"answers\": {\"2026-07-16\": \"ABC...\"}}")


def _parse_natural_answers(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(
        r"(\d{1,2})月(\d{1,2})日(?:每日一练)?答案[：:]\s*([A-Ea-e,\s]+)",
        text,
    ):
        mo, day = int(m.group(1)), int(m.group(2))
        iso = date(YEAR, mo, day).isoformat()
        ans = re.sub(r"[^A-Ea-e]", "", m.group(3)).upper()
        out[iso] = ans
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="每日一练历史补录")
    sub = parser.add_subparsers(dest="command")

    def add_range(p):
        p.add_argument("--from", dest="date_from", default="2026-07-16")
        p.add_argument("--to", dest="date_to", default="2026-07-20")

    p_scan = sub.add_parser("scan", help="扫描日期范围内 PDF")
    add_range(p_scan)
    p_scan.add_argument("--json", action="store_true")

    p_tpl = sub.add_parser("template", help="生成答案模板 JSON")
    add_range(p_tpl)
    p_tpl.add_argument("--output", "-o", default=str(DEFAULT_ANSWERS_PATH))

    p_run = sub.add_parser("run", help="执行补录")
    add_range(p_run)
    p_run.add_argument("--answers-file", "-f", help="答案 JSON 文件")
    p_run.add_argument("--date", help="单日 YYYY-MM-DD")
    p_run.add_argument("--answers", help="该日答案串")
    p_run.add_argument("--no-redate", action="store_true", help="不修正已存在记录的日期")
    p_run.add_argument("--redate-only", action="store_true", help="仅修正已入库题目的日期，不新增")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--json", action="store_true")

    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    if args.command == "scan":
        result = scan_range(
            start=_parse_iso(args.date_from),
            end=_parse_iso(args.date_to),
        )
    elif args.command == "template":
        tpl = build_template(
            start=_parse_iso(args.date_from),
            end=_parse_iso(args.date_to),
        )
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        public = {
            "description": tpl["description"],
            "answers": tpl["answers"],
        }
        out.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
        result = {
            "status": "ok",
            "path": str(out),
            "meta": tpl.get("_meta_correct_keys_for_reference"),
            "text": f"✅ 已生成模板：{out}\n💡 填好 answers 后运行 run --answers-file",
        }
    elif args.command == "run":
        answers_map: dict[str, str] = {}
        if args.answers_file:
            answers_map.update(_load_answers_file(Path(args.answers_file)))
        if args.date and args.answers:
            answers_map[args.date] = args.answers
        if not answers_map and not getattr(args, "redate_only", False):
            result = {
                "status": "error",
                "text": "⚠️ 请提供 --answers-file 或 --date + --answers（或 --redate-only）",
            }
        else:
            result = run_backfill(
                start=_parse_iso(args.date_from),
                end=_parse_iso(args.date_to),
                answers_map=answers_map,
                redate_existing=not args.no_redate,
                dry_run=args.dry_run,
                insert_only=not getattr(args, "redate_only", False),
            )
    else:
        parser.print_help()
        return

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result.get("text", json.dumps(result, ensure_ascii=False, indent=2)))


if __name__ == "__main__":
    main()
