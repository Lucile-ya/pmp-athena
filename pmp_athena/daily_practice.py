#!/usr/bin/env python3
"""
每日一练 — 微信硬路由 + CLI。

流程:
  menu     → 列出未完成日期（全部完成则提示随机）
  start    → 加载 PDF，开始出题
  grade    → 判卷并推进下一题
  resolve  → 解析用户输入的日期
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import NOTES_DIR
    from pmp_athena.utils.question_text import normalize_question_text
except ModuleNotFoundError:
    from config import NOTES_DIR
    from utils.question_text import normalize_question_text

DAILY_DIR = NOTES_DIR / "每日一练"
CONFIG_PATH = NOTES_DIR / "config.json"
STATE_PATH = NOTES_DIR / "daily_practice_state.json"

_YEAR = 2026

_AREA_KEYWORDS: list[tuple[str, list[str]]] = [
    ("干系人管理", ["干系人", "相关方", "stakeholder"]),
    ("敏捷", ["敏捷", "Scrum", "迭代", "产品负责人", "燃尽"]),
    ("整合管理", ["章程", "变更", "CCB", "整合"]),
    ("范围管理", ["范围", "WBS", "需求"]),
    ("进度管理", ["进度", "关键路径", "工期"]),
    ("成本管理", ["成本", "预算", "挣值", "CPI", "SPI"]),
    ("质量管理", ["质量", "审计", "控制质量"]),
    ("资源管理", ["资源", "团队", "RACI"]),
    ("沟通管理", ["沟通", "报告"]),
    ("风险管理", ["风险", "应急"]),
    ("采购管理", ["采购", "合同", "投标人"]),
    ("领导力", ["冲突", "激励", "教练"]),
]


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_pdf_text(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as e:
        raise RuntimeError("需要安装 pdfplumber") from e

    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n".join(parts)


def _strip_watermark(text: str) -> str:
    return re.sub(r"[料资部内育教迹骐练一日每]", "", text)


def _clean_stem(stem: str) -> str:
    """优先保留中文题干，去掉 PDF 噪声。"""
    stem = _strip_watermark(re.sub(r"\s+", " ", stem).strip())
    candidates = re.findall(
        r"[\u4e00-\u9fff][\u4e00-\u9fff\d，。、；;（）()\"'\s]*[？?]",
        stem,
    )
    if candidates:
        return max(candidates, key=len).strip()[:500]
    cn_segments = re.findall(
        r"[\u4e00-\u9fff][\u4e00-\u9fff\d，。、？?：:；;（）()\"''\sA-Za-z-]*[\u4e00-\u9fff？?。]",
        stem,
    )
    if cn_segments:
        return max(cn_segments, key=len).strip()[:500]
    return stem[:500]


def _clean_option(text: str) -> str:
    text = _strip_watermark(re.sub(r"\s+", " ", text).strip())
    parts = re.split(r"(?<=[a-zA-Z\.])\s+(?=[\u4e00-\u9fff])", text)
    for part in reversed(parts):
        if re.search(r"[\u4e00-\u9fff]", part):
            cleaned = part.strip()
            if len(cleaned) >= 4:
                return cleaned[:120]
    cn = re.findall(r"[\u4e00-\u9fff][\u4e00-\u9fff，。、？?：:；;（）()\s]*", text)
    if cn:
        return max(cn, key=len).strip()[:120]
    return text[:120]


def _guess_knowledge_area(stem: str, explanation: str = "") -> str:
    text = f"{stem} {explanation}".lower()
    for area, keys in _AREA_KEYWORDS:
        for k in keys:
            if k.lower() in text:
                return area
    return "综合"


def _parse_questions(text: str) -> list[dict[str, Any]]:
    text = text.replace("．", ".")
    blocks = re.split(r"(?=\n\s*\d+\.\s*【)", text)
    questions: list[dict[str, Any]] = []

    for block in blocks:
        m = re.match(r"\s*(\d+)\.", block)
        if not m:
            continue
        num = int(m.group(1))
        opts: dict[str, str] = {}
        lines = block.split("\n")
        stem_lines: list[str] = []
        current: str | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue
            om = re.match(r"^([A-D])[、\.]\s*(.*)$", line)
            if om:
                current = om.group(1)
                opts[current] = om.group(2)
            elif current and current in opts and not re.match(r"^\d+\.", line):
                opts[current] += " " + line
            elif not opts:
                if re.match(r"^\d+\.", line):
                    line = re.sub(r"^\d+\.\s*【[^】]*】[^】]*】?\s*", "", line)
                    line = re.sub(r"^\d+\.\s*", "", line)
                stem_lines.append(line)

        if len(opts) >= 4:
            stem = _clean_stem(" ".join(stem_lines))
            clean_opts = {k: _clean_option(v) for k, v in opts.items()}
            questions.append({"num": num, "stem": stem, "options": clean_opts})

    return questions


def _parse_answers(text: str) -> dict[int, dict[str, str]]:
    text = text.replace("．", ".")
    blocks = re.split(r"(?=\n\s*\d+\.\s*【)", text)
    answers: dict[int, dict[str, str]] = {}

    for block in blocks:
        m = re.match(r"\s*(\d+)\.", block)
        if not m:
            continue
        num = int(m.group(1))
        am = re.search(r"答案\s*[:：]\s*([A-D])", block, re.I)
        em = re.search(r"解析\s*[:：]\s*(.+)", block, re.S)
        if am:
            answers[num] = {
                "answer": am.group(1).upper(),
                "explanation": (em.group(1).strip()[:200] if em else ""),
            }
    return answers


def _date_from_filename(name: str) -> date | None:
    m = re.search(r"(\d{1,2})月(\d{1,2})日", name)
    if not m:
        return None
    return date(_YEAR, int(m.group(1)), int(m.group(2)))


def _format_label(d: date) -> str:
    return f"{d.month}月{d.day}日"


def _find_pdfs_for_date(d: date) -> tuple[Path | None, Path | None]:
    label = _format_label(d)
    q_pdf = a_pdf = None
    for f in DAILY_DIR.glob("*.pdf"):
        if "答案" in f.name:
            continue
        fd = _date_from_filename(f.name)
        if fd == d:
            q_pdf = f
            break
    if q_pdf:
        for f in DAILY_DIR.glob(f"*{label}*答案*.pdf"):
            a_pdf = f
            break
    return q_pdf, a_pdf


def _load_completed() -> set[str]:
    cfg = _load_json(CONFIG_PATH, {})
    items = cfg.get("daily_completed", [])
    return set(items) if isinstance(items, list) else set()


def _mark_completed(d: date) -> None:
    cfg = _load_json(CONFIG_PATH, {"daily_completed": []})
    if not isinstance(cfg.get("daily_completed"), list):
        cfg["daily_completed"] = []
    iso = d.isoformat()
    if iso not in cfg["daily_completed"]:
        cfg["daily_completed"].append(iso)
        cfg["daily_completed"].sort()
    _save_json(CONFIG_PATH, cfg)


def list_available_dates() -> list[date]:
    dates: list[date] = []
    for f in DAILY_DIR.glob("*.pdf"):
        if "答案" in f.name:
            continue
        d = _date_from_filename(f.name)
        if d:
            dates.append(d)
    return sorted(set(dates))


def list_incomplete_dates() -> list[date]:
    completed = _load_completed()
    return [d for d in list_available_dates() if d.isoformat() not in completed]


def load_questions_for_date(d: date) -> list[dict[str, Any]]:
    q_pdf, a_pdf = _find_pdfs_for_date(d)
    if not q_pdf:
        raise FileNotFoundError(f"未找到 {_format_label(d)} 的题目 PDF")

    q_text = _extract_pdf_text(q_pdf)
    questions = _parse_questions(q_text)
    if not questions:
        raise ValueError(f"无法解析 {_format_label(d)} 的题目")

    answers: dict[int, dict[str, str]] = {}
    if a_pdf and a_pdf.exists():
        answers = _parse_answers(_extract_pdf_text(a_pdf))

    merged: list[dict[str, Any]] = []
    for i, q in enumerate(questions, start=1):
        ans = answers.get(q["num"], {})
        stem = normalize_question_text(q["stem"])
        expl = ans.get("explanation", "")
        merged.append(
            {
                "index": i,
                "num": q["num"],
                "stem": stem,
                "options": q["options"],
                "correct_answer": ans.get("answer", ""),
                "explanation": expl,
                "knowledge_area": _guess_knowledge_area(stem, expl),
            }
        )
    return merged


def load_random_questions(count: int = 10) -> tuple[list[dict[str, Any]], str]:
    pool: list[dict[str, Any]] = []
    for d in list_available_dates():
        try:
            qs = load_questions_for_date(d)
            for q in qs:
                q = dict(q)
                q["source_date"] = d.isoformat()
                q["source_label"] = _format_label(d)
                pool.append(q)
        except (FileNotFoundError, ValueError):
            continue

    if not pool:
        raise FileNotFoundError("题库为空，请确认 pmp_notes/每日一练/ 下有 PDF")

    random.shuffle(pool)
    picked = pool[: min(count, len(pool))]
    for i, q in enumerate(picked, start=1):
        q["index"] = i
    label = f"随机（{len(picked)} 题）"
    return picked, label


def _format_options(options: dict[str, str]) -> str:
    parts = []
    for letter in "ABCD":
        if letter in options:
            text = options[letter].strip()
            if len(text) > 80:
                text = text[:80] + "…"
            parts.append(f"{letter}. {text}")
    return " ".join(parts)


def _format_question(q: dict[str, Any], *, header: str = "") -> str:
    area = q.get("knowledge_area", "综合")
    body = (
        f"📝 Q{q['index']} [{area}]: {q['stem']}\n"
        f"{_format_options(q['options'])}"
    )
    return f"{header}\n\n{body}" if header else body


def _load_state() -> dict[str, Any] | None:
    data = _load_json(STATE_PATH, None)
    return data if isinstance(data, dict) else None


def _save_state(state: dict[str, Any]) -> None:
    _save_json(STATE_PATH, state)


def _clear_state() -> None:
    if STATE_PATH.exists():
        STATE_PATH.unlink()


def menu(*, include_completed: bool = False) -> dict[str, Any]:
    incomplete = list_incomplete_dates()
    completed = _load_completed()
    all_dates = list_available_dates()

    if incomplete:
        labels = "、".join(_format_label(d) for d in incomplete)
        text = (
            "📋 每日一练\n\n"
            f"❌ 未完成（{len(incomplete)} 天）:\n"
            f" {labels}\n\n"
            "💡 回复日期开始，例如：`7月30日`"
        )
        return {
            "status": "select",
            "incomplete": [d.isoformat() for d in incomplete],
            "completed_count": len(completed),
            "total_count": len(all_dates),
            "text": text,
        }

    text = (
        "🎉 所有每日一练已全部完成！\n\n"
        f"✅ 已完成 {len(completed)}/{len(all_dates)} 天\n\n"
        "🎲 正在为你随机抽取 10 题…"
    )
    return {
        "status": "all_done",
        "incomplete": [],
        "completed_count": len(completed),
        "total_count": len(all_dates),
        "text": text,
    }


def resolve_date(text: str) -> date | None:
    """解析用户输入的日期。"""
    text = text.strip()
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if m:
        return date(_YEAR, int(m.group(1)), int(m.group(2)))

    m = re.search(r"(\d{1,2})[/.](\d{1,2})", text)
    if m:
        return date(_YEAR, int(m.group(1)), int(m.group(2)))

    return None


def start_session(*, target_date: date | None = None, random_mode: bool = False) -> dict[str, Any]:
    _clear_state()

    session_date: date | None = target_date
    label = ""

    if random_mode:
        questions, label = load_random_questions(10)
        session_date = None
    elif target_date:
        questions = load_questions_for_date(target_date)
        label = _format_label(target_date)
    else:
        incomplete = list_incomplete_dates()
        if incomplete:
            return {
                "status": "select",
                "text": menu()["text"],
            }
        questions, label = load_random_questions(10)
        random_mode = True

    if not questions:
        return {"status": "error", "text": "⚠️ 未能加载题目，请检查 PDF 文件。"}

    missing_ans = [q for q in questions if not q.get("correct_answer")]
    if missing_ans:
        if len(missing_ans) == len(questions):
            label = _format_label(session_date) if session_date else "该套"
            return {
                "status": "error",
                "text": f"⚠️ {label} 每日一练缺少答案解析 PDF，暂无法自动判卷。",
            }
        questions = [q for q in questions if q.get("correct_answer")]

    state = {
        "mode": "random" if random_mode else "fixed",
        "date": session_date.isoformat() if session_date else None,
        "label": label,
        "questions": questions,
        "current_index": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "wrong_items": [],
    }
    _save_state(state)

    header = f"📝 {_format_label(session_date) if session_date else label}每日一练（共 {len(questions)} 题）"
    q0 = questions[0]
    return {
        "status": "question",
        "question_index": 1,
        "total": len(questions),
        "mode": state["mode"],
        "date": state["date"],
        "text": _format_question(q0, header=header),
    }


def grade_current(user_answer: str) -> dict[str, Any]:
    state = _load_state()
    if not state or not state.get("questions"):
        return {"status": "error", "text": "⚠️ 当前没有进行中的每日一练，请发送「每日一练」开始。"}

    ans = user_answer.strip().upper()
    if ans not in "ABCD":
        return {"status": "error", "text": "⚠️ 请回复 A/B/C/D"}

    idx = state["current_index"]
    questions: list[dict] = state["questions"]
    if idx >= len(questions):
        return {"status": "error", "text": "⚠️ 练习已结束，请发送「每日一练」重新开始。"}

    q = questions[idx]
    correct = str(q.get("correct_answer", "")).upper()
    is_correct = ans == correct

    if is_correct:
        state["correct_count"] += 1
    else:
        state["wrong_count"] += 1
        state.setdefault("wrong_items", []).append(
            {
                "index": q["index"],
                "my_answer": ans,
                "correct_answer": correct,
                "stem": q["stem"],
                "knowledge_area": q.get("knowledge_area", "综合"),
                "explanation": q.get("explanation", ""),
            }
        )

    _record_answer(q, ans, is_correct=is_correct)

    state["current_index"] = idx + 1
    _save_state(state)

    lines: list[str] = []
    if is_correct:
        lines.append("✅ 正确！")
    else:
        expl = q.get("explanation", "")[:100]
        lines.append(f"❌ 正确答案是 {correct}" + (f" — {expl}" if expl else ""))

    if state["current_index"] >= len(questions):
        return _finish_session(state, lines)

    next_q = questions[state["current_index"]]
    lines.append("")
    lines.append(_format_question(next_q))
    return {
        "status": "question",
        "correct": is_correct,
        "question_index": state["current_index"] + 1,
        "total": len(questions),
        "done": False,
        "text": "\n".join(lines),
    }


def _record_answer(q: dict[str, Any], my_answer: str, *, is_correct: bool) -> None:
    try:
        from pmp_athena.record_answer import record_correct_answer, record_wrong_answer
    except ModuleNotFoundError:
        from record_answer import record_correct_answer, record_wrong_answer

    kwargs = dict(
        question=q["stem"],
        my_answer=my_answer,
        correct_answer=q.get("correct_answer", ""),
        knowledge_area=q.get("knowledge_area", "综合"),
        explanation=q.get("explanation", ""),
        source="daily_practice",
        parsed_by="daily_practice.py",
    )
    if is_correct:
        record_correct_answer(**kwargs)
    else:
        record_wrong_answer(**kwargs)


def _finish_session(state: dict[str, Any], prefix_lines: list[str]) -> dict[str, Any]:
    total = len(state["questions"])
    correct = state["correct_count"]
    wrong = state["wrong_count"]
    rate = round(correct / total * 100) if total else 0

    if state.get("mode") == "fixed" and state.get("date"):
        _mark_completed(date.fromisoformat(state["date"]))

    lines = list(prefix_lines)
    lines.append("")
    lines.append(f"📋 每日一练完成：正确 {correct}/{total}（{rate}%）")

    wrong_items = state.get("wrong_items", [])
    if wrong_items:
        lines.append("")
        lines.append("❌ 错题回顾：")
        for w in wrong_items:
            lines.append(
                f"Q{w['index']} [{w['knowledge_area']}]: "
                f"你的 {w['my_answer']} → 正确 {w['correct_answer']}"
            )
    else:
        lines.append("")
        lines.append("🎉 全部正确！")

    session_date = state.get("date")
    if session_date and state.get("mode") == "fixed":
        lines.append("")
        lines.append(f"💾 已记录完成：{_format_label(date.fromisoformat(session_date))}")

    _clear_state()

    return {
        "status": "done",
        "correct": correct,
        "total": total,
        "rate": rate,
        "done": True,
        "text": "\n".join(lines),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="每日一练")
    sub = parser.add_subparsers(dest="command")

    p_menu = sub.add_parser("menu", help="列出未完成日期")
    p_menu.add_argument("--json", action="store_true")

    p_resolve = sub.add_parser("resolve-date", help="解析用户日期")
    p_resolve.add_argument("text")
    p_resolve.add_argument("--json", action="store_true")

    p_start = sub.add_parser("start", help="开始每日一练")
    p_start.add_argument("--date", help="YYYY-MM-DD")
    p_start.add_argument("--random", action="store_true")
    p_start.add_argument("--json", action="store_true")

    p_grade = sub.add_parser("grade", help="判卷")
    p_grade.add_argument("answer")
    p_grade.add_argument("--json", action="store_true")

    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    result: dict[str, Any]

    if args.command == "menu":
        result = menu()
    elif args.command == "resolve-date":
        d = resolve_date(args.text)
        incomplete = {x.isoformat() for x in list_incomplete_dates()}
        all_dates = {x.isoformat() for x in list_available_dates()}
        if d is None:
            result = {"status": "error", "date": None, "text": "⚠️ 无法识别日期，请发如 `7月30日`"}
        elif d.isoformat() not in all_dates:
            result = {"status": "error", "date": d.isoformat(), "text": f"⚠️ 题库中没有 {_format_label(d)} 的每日一练"}
        elif d.isoformat() in incomplete or not incomplete:
            result = {"status": "ok", "date": d.isoformat(), "label": _format_label(d), "text": ""}
        else:
            result = {
                "status": "already_done",
                "date": d.isoformat(),
                "text": f"📌 {_format_label(d)} 每日一练已完成。请选择未完成日期，或发送「随机每日一练」。",
            }
    elif args.command == "start":
        td = date.fromisoformat(args.date) if args.date else None
        result = start_session(target_date=td, random_mode=args.random)
    elif args.command == "grade":
        result = grade_current(args.answer)
    else:
        result = menu()

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result.get("text", ""))


if __name__ == "__main__":
    main()
