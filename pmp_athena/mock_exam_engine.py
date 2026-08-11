#!/usr/bin/env python3
"""
模考引擎 — 状态机驱动的逐题模考（直接解析每日一练PDF组卷）。

用法:
    python pmp_athena/mock_exam_engine.py start --paper one
    python pmp_athena/mock_exam_engine.py answer A
    python pmp_athena/mock_exam_engine.py pause
    python pmp_athena/mock_exam_engine.py resume
    python pmp_athena/mock_exam_engine.py status
    python pmp_athena/mock_exam_engine.py abandon
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pmp_athena.error_logger import ErrorLogger
from pmp_athena.question_bank import QuestionBank
from pmp_athena.mock_exam_state import MockExamState
from pmp_athena.exam_recorder import ExamRecorder

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("mock_exam_engine")

TZ_CST = timezone(timedelta(hours=8))
ENGINE_STATE_PATH = ROOT / "pmp_notes" / "mock_exam_engine.json"
DAILY_DIR = ROOT / "pmp_notes" / "每日一练"

PAPER_MAP = {
    "one": "考前冲刺卷1", "two": "考前冲刺卷2",
    "three": "考前冲刺卷3", "random": "随机模考",
}

KNOWLEDGE_AREAS = [
    "整合管理", "范围管理", "进度管理", "成本管理", "质量管理",
    "资源管理", "沟通管理", "风险管理", "采购管理", "干系人管理",
    "敏捷/混合方法", "商业环境", "领导力/人员", "综合",
]

AREA_KW: dict[str, str] = {
    "整体": "整合管理", "整合": "整合管理", "变更": "整合管理", "章程": "整合管理",
    "CCB": "整合管理", "启动": "整合管理",
    "范围": "范围管理", "WBS": "范围管理", "可交付": "范围管理", "验收": "范围管理",
    "进度": "进度管理", "关键路径": "进度管理", "CPM": "进度管理", "里程碑": "进度管理",
    "最短": "进度管理", "历时": "进度管理", "浮动": "进度管理", "滞后": "进度管理",
    "超前": "进度管理", "日历": "进度管理",
    "成本": "成本管理", "EV": "成本管理", "挣值": "成本管理", "EVM": "成本管理",
    "预算": "成本管理", "CPI": "成本管理", "SPI": "成本管理",
    "质量": "质量管理", "QA": "质量管理", "QC": "质量管理", "缺陷": "质量管理",
    "资源": "资源管理", "团队": "资源管理", "RACI": "资源管理", "冲突": "资源管理",
    "沟通": "沟通管理", "干系": "干系人管理", "相关方": "干系人管理",
    "风险": "风险管理", "采购": "采购管理", "合同": "采购管理",
    "敏捷": "敏捷/混合方法", "Scrum": "敏捷/混合方法", "Sprint": "敏捷/混合方法",
    "商业": "商业环境", "领导": "领导力/人员",
}


def guess_area(text: str) -> str:
    scores: dict[str, int] = {}
    for kw, area in AREA_KW.items():
        if kw in (text or ""):
            scores[area] = scores.get(area, 0) + 1
    return max(scores, key=lambda k: scores[k]) if scores else "综合"


# ═══════════════════════════════════════════════════════════════
# PDF 题库解析（每日一练 PDF → 题目列表）
# ═══════════════════════════════════════════════════════════════

def _parse_daily_pdf(pdf_path: Path) -> list[dict]:
    """从一份每日一练习题 PDF 提取题目列表。"""
    try:
        import pdfplumber
    except ImportError:
        return []

    questions: list[dict] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            all_lines: list[str] = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    all_lines.extend(text.split("\n"))

        # 去水印碎片
        full = "\n".join(all_lines)
        full = re.sub(r"(?:^|\n)\s*[内育教迹骐料资部]{1,3}\s*(?:\n|$)", "\n", full)
        full = re.sub(r"\n{2,}", "\n", full)

        # 找到所有题号位置：\n + 数字 + ．/./
        q_starts = list(re.finditer(r"\n(\d{1,2})[．.、]\s*", "\n" + full))

        for k, m in enumerate(q_starts):
            qnum = int(m.group(1))
            start = m.start()
            # 下一题的起始位置
            if k + 1 < len(q_starts):
                end = q_starts[k + 1].start()
            else:
                end = len(full)
            block = full[start:end].strip()

            if len(block) < 30:
                continue
            if "答案" in block[:50] or "解析" in block[:50]:
                continue

            # 提取选项 A：/A./A．/A、格式
            opt_re = re.compile(r"([A-D])[：:\.．、\)]\s*")
            opt_parts = list(opt_re.finditer(block))

            if len(opt_parts) < 2:
                continue

            opts: list[str] = []
            for j, om in enumerate(opt_parts):
                s = om.start()
                e = opt_parts[j + 1].start() if j + 1 < len(opt_parts) else len(block)
                opts.append(block[s:e].strip()[:200])

            stem = block[: opt_parts[0].start()].strip()
            stem = re.sub(r"^\d{1,2}[．.、]\s*", "", stem)
            stem = re.sub(r"【[^】]+】\s*", "", stem)
            stem = re.sub(r"\[[^\]]+\]\s*", "", stem)
            stem = re.sub(r"\s+", " ", stem).strip()

            if len(stem) < 10:
                continue

            questions.append({
                "question": stem[:300],
                "options": opts[:4],
                "correct_answer": "",
                "explanation": "",
            })
    except Exception:
        pass

    return questions


def _parse_answer_pdf(pdf_path: Path) -> dict[int, dict]:
    """从答案解析 PDF 提取 {题号: {correct_answer, explanation}}。"""
    try:
        import pdfplumber
    except ImportError:
        return {}

    answers: dict[int, dict] = {}
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            all_lines: list[str] = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    all_lines.extend(text.split("\n"))
        full = "\n".join(all_lines)

        # 方法1：匹配 "答案:X" 模式，按出现顺序分配给题号
        ans_matches = list(re.finditer(r"答案\s*[:：]\s*([A-Ea-e])", full))
        for seq, m in enumerate(ans_matches):
            qnum = seq + 1  # 按顺序编号
            letter = m.group(1).upper()

            # 提取紧跟的解析（到下一题的答案之前或300字）
            expl_end = ans_matches[seq + 1].start() if seq + 1 < len(ans_matches) else len(full)
            expl_chunk = full[m.end():expl_end]
            expl_m = re.search(r"解析\s*[:：]\s*(.*?)(?=\n\d{1,2}[．.]|\n答案|\Z)", expl_chunk, re.DOTALL)
            expl = expl_m.group(1).strip()[:200] if expl_m else ""

            answers[qnum] = {"correct_answer": letter, "explanation": expl}
    except Exception:
        pass

    return answers


def load_questions_from_pdfs(target_count: int = 180) -> list[dict]:
    """从全部每日一练 PDF 解析题目，随机抽取 target_count 道。"""
    if not DAILY_DIR.exists():
        raise RuntimeError(f"每日一练目录不存在: {DAILY_DIR}")

    pdf_files = sorted(DAILY_DIR.glob("*.pdf"))
    question_pdfs = [f for f in pdf_files if "答案" not in f.name and "解析" not in f.name]
    answer_pdfs = [f for f in pdf_files if "答案" in f.name or "解析" in f.name]

    # 建立题目→答案的对应关系
    ans_map: dict[str, Path] = {}
    for ap in answer_pdfs:
        key = ap.name.replace("答案解析", "").replace("答案", "").replace(".pdf", "")
        ans_map[key] = ap

    all_questions: list[dict] = []

    for qp in question_pdfs:
        qs = _parse_daily_pdf(qp)
        if not qs:
            continue

        # 找到对应的答案 PDF
        key = qp.name.replace(".pdf", "")
        ans_path = ans_map.get(key)
        if ans_path:
            ans_data = _parse_answer_pdf(ans_path)
            for i, q in enumerate(qs):
                qnum = i + 1
                if qnum in ans_data:
                    q["correct_answer"] = ans_data[qnum].get("correct_answer", "")
                    q["explanation"] = ans_data[qnum].get("explanation", "")

        # 标记知识领域
        for q in qs:
            q["_area"] = guess_area(q.get("question", ""))
            q["source_pdf"] = qp.name

        # 只保留有标准答案的
        valid = [q for q in qs if q.get("correct_answer")]
        all_questions.extend(valid)

    if not all_questions:
        raise RuntimeError(
            "未能从每日一练 PDF 中提取到任何题目。\n"
            f"目录: {DAILY_DIR}\nPDF 数量: 题目 {len(question_pdfs)} / 答案 {len(answer_pdfs)}"
        )

    # 取 target_count 道（或全部）
    if len(all_questions) > target_count:
        selected = random.sample(all_questions, target_count)
    else:
        selected = all_questions
    random.shuffle(selected)
    return selected


# ═══════════════════════════════════════════════════════════════
# Engine
# ═══════════════════════════════════════════════════════════════


class MockExamEngine:
    """逐题模考引擎 — 状态文件驱动。"""

    def __init__(self, state_path: Path | None = None):
        self.path = state_path or ENGINE_STATE_PATH

    def _read(self) -> dict | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _write(self, data: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _clear(self):
        try:
            self.path.unlink(missing_ok=True)
        except (FileNotFoundError, OSError):
            pass

    def _now_ts(self) -> float:
        return datetime.now(TZ_CST).timestamp()

    # ── 公共 API ─────────────────────────────────────────────

    def start(self, paper: str) -> dict:
        """加载题目，写入状态，返回第一题。"""
        existing = self._read()
        if existing and existing.get("status") in ("active", "paused"):
            return {
                "status": "error",
                "error": f"已有活跃模考「{existing.get('paper')}」，请先完成或放弃。",
            }

        ptype = PAPER_MAP.get(paper, "随机模考")

        questions = load_questions_from_pdfs(180)
        total = len(questions)

        if total < 10:
            return {
                "status": "error",
                "error": f"题库不足（仅 {total} 道），无法组卷。请先做更多每日一练。",
            }

        state = {
            "paper": ptype,
            "paper_key": paper,
            "status": "active",
            "total": total,
            "current_index": 0,
            "questions": questions,
            "answers": {},
            "start_ts": self._now_ts(),
            "paused_accumulated": 0,
            "last_resume_ts": self._now_ts(),
        }
        self._write(state)

        # 兼容旧 MockExamState
        try:
            import logging as _l
            _l.getLogger("mock_exam_state").setLevel(_l.ERROR)
            MockExamState().start(exam_id=ptype, total_questions=total)
        except Exception:
            pass

        return self._fmt_q(state, 0)

    def answer(self, letter: str) -> dict:
        """记录答案、前进。全部答完自动判卷。"""
        state = self._read()
        if not state:
            return {"status": "error", "error": "没有活跃的模考。"}
        if state["status"] != "active":
            return {"status": "error", "error": f"模考状态为 {state['status']}。"}

        letter = letter.strip().upper()
        if letter not in "ABCDE":
            return {"status": "error", "error": f"无效答案: {letter}"}

        idx = state["current_index"]
        state["answers"][str(idx)] = letter
        state["current_index"] = idx + 1

        if state["current_index"] >= state["total"]:
            self._write(state)
            return self.grade()

        self._write(state)
        return self._fmt_q(state, state["current_index"])

    def pause(self) -> dict:
        state = self._read()
        if not state:
            return {"status": "error", "error": "没有活跃的模考。"}
        if state["status"] != "active":
            return {"status": "error", "error": "无法暂停。"}

        now = self._now_ts()
        state["paused_accumulated"] = (
            state.get("paused_accumulated", 0)
            + now - state.get("last_resume_ts", now)
        )
        state["status"] = "paused"
        self._write(state)
        answered = len(state.get("answers", {}))
        elapsed = int(state["paused_accumulated"] / 60)
        return {
            "status": "paused",
            "text": (
                f"⏸️  模考已暂停（已做答 {elapsed} 分）\n"
                f"   进度: {answered}/{state['total']} 题\n"
                f"   回复「继续」恢复，回复「放弃模考」退出。"
            ),
        }

    def resume(self) -> dict:
        state = self._read()
        if not state:
            return {"status": "error", "error": "没有模考可继续。"}
        if state["status"] != "paused":
            return {"status": "error", "error": "无法继续。"}

        state["status"] = "active"
        state["last_resume_ts"] = self._now_ts()
        self._write(state)
        idx = state["current_index"]
        answered = len(state.get("answers", {}))
        q = self._fmt_q(state, idx)
        return {
            "status": "active",
            "text": f"▶️  模考已继续（进度 {answered}/{state['total']}）",
            "next": q,
        }

    def grade(self) -> dict:
        """判卷 + 入库 + 清空，返回报告。"""
        state = self._read()
        if not state:
            return {"status": "error", "error": "没有模考数据。"}

        questions = state.get("questions", [])
        answers = state.get("answers", {})
        total = len(questions)
        correct = 0
        wrongs: list[dict] = []
        area_s: dict[str, dict[str, int]] = {}

        for i, q in enumerate(questions):
            ua = answers.get(str(i), "?")
            ca = q.get("correct_answer", "").strip()
            area = q.get("_area", "综合")
            area_s.setdefault(area, {"correct": 0, "total": 0})["total"] += 1
            if ua == ca:
                correct += 1
                area_s[area]["correct"] += 1
            else:
                wrongs.append({
                    "index": i + 1,
                    "question": q.get("question", "")[:120],
                    "user_answer": ua,
                    "correct_answer": ca,
                    "explanation": q.get("explanation", ""),
                    "area": area,
                })

        rate = correct / total if total else 0
        total_sec = int(state.get("paused_accumulated", 0))
        if state.get("status") == "active":
            total_sec += int(self._now_ts() - state.get("last_resume_ts", self._now_ts()))
        total_min = total_sec // 60

        # ── 入库 ──
        el = ErrorLogger()
        qb = QuestionBank()
        for w in wrongs:
            err = el.add(
                question=w["question"], my_answer=w["user_answer"],
                correct_answer=w["correct_answer"], knowledge_area=w["area"],
                explanation=w["explanation"],
            )
            qb.add(
                question=w["question"], my_answer=w["user_answer"],
                correct_answer=w["correct_answer"], is_correct=False,
                knowledge_area=w["area"], explanation=w["explanation"],
                error_log_id=err["id"],
            )
        for i, q in enumerate(questions):
            ua = answers.get(str(i), "?")
            if ua == q.get("correct_answer", "").strip():
                qb.add(
                    question=q.get("question", ""), my_answer=ua,
                    correct_answer=q.get("correct_answer", ""),
                    is_correct=True, knowledge_area=q.get("_area", "综合"),
                    explanation="",
                )

        ExamRecorder().add(
            exam_id=state.get("paper", "模考"), total_questions=total,
            correct_count=correct, wrong_count=total - correct,
            correct_rate=rate, time_used_minutes=total_min,
            total_time_seconds=total_sec, scores={}, weak_areas=[],
            knowledge_areas=area_s, status="completed",
        )

        self._clear()

        return {
            "status": "done", "total": total, "correct": correct,
            "wrong": total - correct, "correct_rate": round(rate * 100, 1),
            "time_minutes": total_min,
            "text": self._report(state["paper"], total, correct, rate, total_min, area_s, wrongs),
        }

    def get_status(self) -> dict:
        s = self._read()
        if not s:
            return {"status": "no_exam", "text": "📭 当前没有活跃的模考。"}
        idx = s.get("current_index", 0)
        answered = len(s.get("answers", {}))
        elapsed = int(s.get("paused_accumulated", 0))
        if s.get("status") == "active":
            elapsed += int(self._now_ts() - s.get("last_resume_ts", self._now_ts()))
        return {
            "status": s.get("status"), "paper": s.get("paper"),
            "current_index": idx, "total": s["total"], "answered": answered,
            "elapsed_minutes": elapsed // 60,
            "text": (
                f"📊 模考: {s.get('paper')}\n"
                f"   进度: {answered}/{s['total']} 题\n"
                f"   状态: {s.get('status')}\n"
                f"   用时: {elapsed // 60} 分"
            ),
        }

    def abandon(self) -> dict:
        self._clear()
        return {"status": "abandoned", "text": "🗑️  模考已放弃，状态已清空。"}

    def _fmt_q(self, state, idx) -> dict:
        qs = state.get("questions", [])
        if idx >= len(qs):
            return {"status": "error", "error": f"索引越界: {idx}"}
        q = qs[idx]
        area = q.get("_area", "综合")
        lines = [f"📝 Q{idx + 1} [{area}]: {q.get('question', '')}"]
        for o in q.get("options", []):
            lines.append(o)
        return {"status": "question", "index": idx + 1, "total": state["total"], "text": "\n".join(lines)}

    def _report(self, paper, total, correct, rate, minutes, area_s, wrongs):
        lines = [
            "══════════════════════════",
            f"📋 PMP 模考报告: {paper}",
            "══════════════════════════",
            "",
            f"⏱️  做答用时: {minutes} 分钟",
            f"✏️  涂卡估算: {total * 8 // 60} 分钟（{total}题×8秒）",
            "",
            f"📊 总正确率: {correct}/{total}（{round(rate * 100, 1)}%）",
            "",
        ]
        lvl = (
            "🟢 已达目标 ✅" if rate >= 0.70 else
            "🟡 接近目标" if rate >= 0.65 else
            "🟠 需加强" if rate >= 0.59 else "🔴 需重点关注"
        )
        lines.append(f"🎯 目标判定: {lvl}")
        lines.append(f"   评估线65%: {round(total * 0.65)}题 | 目标70%: {round(total * 0.70)}题")
        lines.append("")

        if area_s:
            lines.append("📈 各领域正确率:")
            for area, s in sorted(area_s.items(), key=lambda x: x[1]["correct"] / max(1, x[1]["total"])):
                ar = s["correct"] / max(1, s["total"]) * 100
                bar = "█" * max(1, int(ar / 5)) + "░" * max(0, 10 - int(ar / 5))
                e = "🟢" if ar >= 70 else ("🟡" if ar >= 55 else "🔴")
                lines.append(f"  {e} {area}: {bar} {s['correct']}/{s['total']} ({round(ar)}%)")
            lines.append("")

        if wrongs:
            lines.append(f"🔴 错题（{len(wrongs)} 道）:")
            for w in wrongs[:10]:
                qp = w["question"][:50]
                lines.append(f"  Q{w['index']} [{w['area']}]: {w['user_answer']} → {w['correct_answer']}  {qp}…")
            if len(wrongs) > 10:
                lines.append(f"  …还有 {len(wrongs) - 10} 道")
            lines.append("")

        lines.append("💡 发送「薄弱点」查看完整诊断，或「复习错题」开始复习。")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="模考引擎")
    parser.add_argument("command", choices=[
        "start", "answer", "pause", "resume", "grade", "status", "abandon",
    ])
    parser.add_argument("arg", nargs="?", default="", help="答案字母或试卷名")
    parser.add_argument("--paper", default="random", choices=["one", "two", "three", "random"])
    args = parser.parse_args()

    engine = MockExamEngine()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    result: dict = {}

    if args.command == "start":
        result = engine.start(args.paper)
    elif args.command == "answer":
        result = engine.answer(args.arg)
    elif args.command == "pause":
        result = engine.pause()
    elif args.command == "resume":
        result = engine.resume()
    elif args.command == "grade":
        result = engine.grade()
    elif args.command == "status":
        result = engine.get_status()
    elif args.command == "abandon":
        result = engine.abandon()

    if result.get("next"):
        nxt = result.pop("next")
        if result.get("text"):
            result["text"] += "\n\n" + nxt.get("text", "")
        result["index"] = nxt.get("index")
        result["total"] = nxt.get("total")
        result["status"] = "question"

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
