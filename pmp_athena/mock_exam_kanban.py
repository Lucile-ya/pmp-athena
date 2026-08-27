#!/usr/bin/env python3
"""
模考任务看板 — 可视化管理全部模考的完成/待完成/重刷建议。

读取 mock_exam_config.json + exam_records.json，自动联动更新状态。
触发词: 模考清单 / 模考看板 / 还有哪几套模考 / 模考进度
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("D:/pmp-athena/pmp_notes/mock_exam_config.json")
RECORDS_PATH = Path("D:/pmp-athena/pmp_notes/exam_records.json")
PDF_DIR = Path("D:/pmp-athena/pmp_notes/模考")


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"mock_exams": [], "target_weekly_exams": 2}


def _save_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_records() -> list[dict]:
    try:
        d = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))
        return d.get("exams", []) if isinstance(d, dict) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _match_exam_to_record(config_exam: dict, records: list[dict]) -> dict | None:
    """尝试将配置中的模考匹配到 exam_records 中的某条记录。"""
    name = config_exam.get("name", "")
    pdf_name = config_exam.get("pdf_name", "")

    for r in records:
        rid = r.get("exam_id", "")
        # 匹配：配置名包含在记录名中，或 PDF 名包含在记录名中
        if name in rid or (pdf_name and pdf_name in rid):
            # 排除章节练习
            if "章节" in rid or "练习" in rid:
                continue
            return r
    return None


def _detect_available_pdfs() -> set[str]:
    """扫描模考 PDF 目录，返回可用试卷名集合。"""
    available = set()
    for p in PDF_DIR.glob("*.pdf"):
        stem = p.stem
        if "答案" in stem or "解析" in stem or "参考" in stem:
            continue
        available.add(stem)
    return available


def _pdf_available(pdf_name: str, available_pdfs: set[str]) -> bool:
    if not pdf_name:
        return False
    return any(pdf_name in stem for stem in available_pdfs)


def build_kanban() -> dict:
    """构建模考看板数据。"""
    config = _load_config()
    records = _load_records()
    available_pdfs = _detect_available_pdfs()

    exams = config.get("mock_exams", [])
    completed: list[dict] = []
    pending: list[dict] = []
    retake: list[dict] = []
    pass_line = 106  # 59% of 180

    for exam in exams:
        eid = exam.get("id", "")
        name = exam.get("name", "未知")
        pdf_name = exam.get("pdf_name", "")

        # Auto-detect: match against exam_records.json
        matched = _match_exam_to_record(exam, records)

        if matched:
            score = matched.get("correct_count", 0)
            total = matched.get("total_questions", 180)
            rate = matched.get("correct_rate", 0)
            if isinstance(rate, float) and rate <= 1:
                rate_pct = rate * 100
            else:
                rate_pct = rate * 100 if rate <= 1 else rate
            edate = matched.get("exam_date", "")

            status = "completed"
            exam["status"] = status
            exam["score"] = score
            exam["correct_rate"] = round(rate_pct, 1)
            exam["date"] = edate
            exam["total_questions"] = total

            entry = {
                "id": eid, "name": name, "score": score,
                "total": total, "rate": rate_pct, "date": edate,
            }
            completed.append(entry)

            # Retake suggestion: < 59%
            if rate_pct < 59:
                retake.append(entry)
        else:
            has_pdf = _pdf_available(pdf_name, available_pdfs)
            exam["has_pdf"] = has_pdf
            pending.append({
                "id": eid,
                "name": name,
                "has_pdf": has_pdf,
                "start_cmd": exam.get("start_cmd", ""),
            })

    # Sort completed by date
    completed.sort(key=lambda x: x.get("date", ""))
    retake.sort(key=lambda x: x.get("rate", 0))

    total = len(completed) + len(pending)
    target_weekly = config.get("target_weekly_exams", 2)

    # Estimate completion
    weekly_pace = max(0.5, min(target_weekly, 3))
    weeks_to_complete = max(1, int(len(pending) / weekly_pace) + (1 if len(pending) % weekly_pace > 0 else 0))
    done_date = (date.today() + timedelta(weeks=weeks_to_complete)).isoformat()

    _save_config(config)

    return {
        "completed": completed,
        "pending": pending,
        "retake": retake,
        "total": total,
        "completed_count": len(completed),
        "pending_count": len(pending),
        "target_weekly": target_weekly,
        "weeks_to_complete": weeks_to_complete,
        "estimated_done_date": done_date,
    }


def format_kanban() -> str:
    """格式化为微信推送文本。"""
    kb = build_kanban()

    lines = [
        "📊 模考任务看板",
        "══════════════════════════════",
        "",
    ]

    comp = kb["completed"]
    pend = kb["pending"]
    retake = kb["retake"]

    # Completed
    lines.append(f"✅ 已完成（{len(comp)}/{kb['total']}）：")
    if comp:
        for c in comp:
            d = c.get("date", "")[-5:] or "???"
            lines.append(f"  · {c['name']}（{d}：{c['score']}/{c['total']}，{c['rate']:.0f}%）")
    else:
        lines.append("  · 暂无")
    lines.append("")

    # Pending
    lines.append(f"⏳ 待完成（{len(pend)}/{kb['total']}）：")
    if pend:
        for i, p in enumerate(pend):
            pdf_mark = " 📄" if p.get("has_pdf") else ""
            cmd = p.get("start_cmd") or ""
            cmd_hint = f" → 「{cmd}」" if cmd and cmd != "录入成绩" else ""
            hint = ""
            if i == 0:
                hint = " ← 建议本周完成"
            lines.append(f"  · {p['name']}{pdf_mark}{cmd_hint}{hint}")
    else:
        lines.append("  · 暂无")
    lines.append("")

    # Retake suggestions
    if retake:
        lines.append(f"🔁 建议重刷（正确率 < 59%）：")
        for r in retake:
            lines.append(f"  · {r['name']}（{r['rate']:.0f}% < 59%）")
        lines.append("")

    # Schedule estimate
    lines.append(f"📅 按当前节奏（{kb['target_weekly']} 次/周），预计 {kb['weeks_to_complete']} 周内完成全部模考")

    lines.extend([
        "",
        "💬 做题：发「开始模考七」或卷名「2609期模考一」（见各行 → 提示）",
        "💬 录入：「录入成绩 <模考名> <分数>」如「录入成绩 2606PMP模考二 125」",
        "💬 发「模考」查看完整试卷菜单（模考一~八）",
    ])
    return "\n".join(lines)


def record_score(exam_name: str, score: int) -> dict:
    """手动录入模考成绩。写入 exam_records.json 并更新看板配置。"""
    config = _load_config()
    exams = config.get("mock_exams", [])
    found = None
    for e in exams:
        if exam_name in e.get("name", ""):
            found = e
            break

    if not found:
        return {"status": "error", "text": f"⚠️ 未找到模考「{exam_name}」。可用：{[e['name'] for e in exams]}"}

    total = found.get("total_questions", 180)
    rate = score / total
    found["status"] = "completed"
    found["score"] = score
    found["correct_rate"] = round(rate * 100, 1)
    found["date"] = date.today().isoformat()
    _save_config(config)

    # Also write to exam_records.json
    records_data = json.loads(RECORDS_PATH.read_text(encoding="utf-8")) if RECORDS_PATH.exists() else {"exams": []}
    if not isinstance(records_data, dict):
        records_data = {"exams": []}
    records_data.setdefault("exams", []).append({
        "exam_id": f"人工录入_{exam_name}",
        "exam_date": date.today().isoformat(),
        "status": "completed",
        "total_questions": total,
        "correct_count": score,
        "wrong_count": total - score,
        "correct_rate": round(rate, 4),
        "time_used_minutes": 0,
        "total_time_seconds": 0,
        "paused_duration": 0,
        "scores": {"people": 0, "process": 0, "business_environment": 0},
        "weak_areas": [],
    })
    RECORDS_PATH.write_text(json.dumps(records_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "ok",
        "text": f"✅ 已录入：{exam_name} {score}/{total}（{rate*100:.0f}%）\n\n{format_kanban()}",
        "exam_name": exam_name, "score": score, "total": total, "rate": round(rate * 100, 1),
    }


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    import argparse
    parser = argparse.ArgumentParser(description="模考任务看板")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("kanban", help="显示模考看板")
    sub.add_parser("kanban-json", help="JSON 格式看板")
    p_rec = sub.add_parser("record", help="录入成绩")
    p_rec.add_argument("exam_name")
    p_rec.add_argument("score", type=int)
    args = parser.parse_args()

    if args.cmd == "kanban-json":
        print(json.dumps(build_kanban(), ensure_ascii=False))
    elif args.cmd == "record":
        print(json.dumps(record_score(args.exam_name, args.score), ensure_ascii=False))
    else:
        print(format_kanban())


if __name__ == "__main__":
    main()
