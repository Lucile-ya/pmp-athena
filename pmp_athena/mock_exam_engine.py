#!/usr/bin/env python3
"""
模考引擎 — 状态机驱动的逐题模考，供微信桥接 hard-route 调用。

用法:
    python pmp_athena/mock_exam_engine.py start --paper one --json
    python pmp_athena/mock_exam_engine.py next --json
    python pmp_athena/mock_exam_engine.py answer A --json
    python pmp_athena/mock_exam_engine.py pause --json
    python pmp_athena/mock_exam_engine.py resume --json
    python pmp_athena/mock_exam_engine.py grade --json
    python pmp_athena/mock_exam_engine.py status --json
    python pmp_athena/mock_exam_engine.py abandon --json
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from pmp_athena.config import NOTES_DIR
    from pmp_athena.db.vector_store import get_vector_store
    from pmp_athena.error_logger import ErrorLogger
    from pmp_athena.question_bank import QuestionBank
    from pmp_athena.mock_exam_state import MockExamState
    from pmp_athena.exam_recorder import ExamRecorder
except (ImportError, ModuleNotFoundError):
    from config import NOTES_DIR
    from db.vector_store import get_vector_store
    from error_logger import ErrorLogger
    from question_bank import QuestionBank
    from mock_exam_state import MockExamState
    from exam_recorder import ExamRecorder

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("mock_exam_engine")

TZ_CST = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent.parent
ENGINE_STATE_PATH = ROOT / "pmp_notes" / "mock_exam_engine.json"

PAPER_MAP = {
    "one":   "考前冲刺卷1",
    "two":   "考前冲刺卷2",
    "three": "考前冲刺卷3",
    "random": "随机模考",
}

KNOWLEDGE_AREAS = [
    "整合管理", "范围管理", "进度管理", "成本管理", "质量管理",
    "资源管理", "沟通管理", "风险管理", "采购管理", "干系人管理",
    "敏捷/混合方法", "商业环境", "领导力/人员", "综合",
]

AREA_KEYWORDS: dict[str, str] = {
    "整合": "整合管理", "变更": "整合管理", "章程": "整合管理", "CCB": "整合管理",
    "范围": "范围管理", "WBS": "范围管理", "可交付": "范围管理",
    "进度": "进度管理", "关键路径": "进度管理", "CPM": "进度管理", "里程碑": "进度管理",
    "成本": "成本管理", "EV": "成本管理", "挣值": "成本管理", "EVM": "成本管理", "预算": "成本管理",
    "质量": "质量管理", "QA": "质量管理", "QC": "质量管理",
    "资源": "资源管理", "团队": "资源管理", "RACI": "资源管理", "冲突": "资源管理",
    "沟通": "沟通管理",
    "风险": "风险管理",
    "采购": "采购管理", "合同": "采购管理",
    "干系": "干系人管理", "相关方": "干系人管理",
    "敏捷": "敏捷/混合方法", "Scrum": "敏捷/混合方法", "Sprint": "敏捷/混合方法",
    "商业": "商业环境",
}


def guess_knowledge_area(text: str) -> str:
    t = text or ""
    scores: dict[str, int] = {}
    for kw, area in AREA_KEYWORDS.items():
        if kw.lower() in t.lower():
            scores[area] = scores.get(area, 0) + 1
    if scores:
        return max(scores, key=lambda k: scores[k])
    return "综合"


def load_questions_from_chroma(count: int = 180) -> list[dict]:
    """从 ChromaDB 随机抽取题目。"""
    store = get_vector_store()
    total = store.get_notes_count()
    if total == 0:
        raise RuntimeError("向量库为空。请先运行 python -m pmp_athena.cli ingest")

    sample_size = min(total, max(count * 3, 500))
    results = store._notes.get(
        limit=sample_size,
        include=["documents", "metadatas"],
    )

    docs = results.get("documents", [])
    metas = results.get("metadatas", [])
    ids = results.get("ids", [])

    # 筛出含"答案:"或"A."的题目型 chunk
    candidates = []
    for i, doc in enumerate(docs):
        if not doc or not isinstance(doc, str):
            continue
        has_answer = "答案:" in doc or "答案：" in doc
        has_option = "A." in doc or "A、" in doc or "A．" in doc
        if has_option:
            candidates.append({
                "doc_id": ids[i] if i < len(ids) else "",
                "text": doc,
                "meta": metas[i] if i < len(metas) else {},
            })

    if len(candidates) < count:
        count = len(candidates)

    selected = random.sample(candidates, min(count, len(candidates)))

    # 简化为题干+选项
    questions = []
    for c in selected:
        q = parse_question_chunk(c["text"])
        q["doc_id"] = c["doc_id"]
        q["_area"] = guess_knowledge_area(c["text"])
        questions.append(q)

    return questions


def parse_question_chunk(text: str) -> dict:
    """从 ChromaDB chunk 提取题干 + 选项 + 正确答案。"""
    lines = text.strip().split("\n")
    question_lines: list[str] = []
    options: list[str] = []
    correct_answer = ""
    explanation = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("答案:") or stripped.startswith("答案："):
            correct_answer = stripped.replace("答案:", "").replace("答案：", "").strip()
            continue
        if stripped.startswith("解析:") or stripped.startswith("解析："):
            explanation = stripped.replace("解析:", "").replace("解析：", "").strip()
            continue
        if stripped[0] in "ABCD" and len(stripped) > 1 and stripped[1] in ".．、":
            options.append(stripped)
            continue
        question_lines.append(stripped)

    question = " ".join(question_lines)
    my_answer = extract_embedded_answer(text)

    return {
        "question": question[:300],
        "options": options[:4],
        "correct_answer": correct_answer[:5],
        "explanation": explanation[:200],
        "my_answer": my_answer,
    }


def extract_embedded_answer(text: str) -> str:
    """从文本提取「我的答案: A」。"""
    import re
    m = re.search(r"(?:我的答案|我选)[是为：:\s]*([A-Ea-e])", text)
    if m:
        return m.group(1).upper()
    return ""


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

    def _now(self) -> str:
        return datetime.now(TZ_CST).isoformat()

    def _now_ts(self) -> float:
        return datetime.now(TZ_CST).timestamp()

    def start(self, paper: str) -> dict:
        """加载题目，写入状态文件，返回第一题。"""
        existing = self._read()
        if existing and existing.get("status") in ("active", "paused"):
            return {"status": "error", "error": f"已有活跃模考「{existing.get('paper')}」，请先完成或放弃。"}

        ptype = PAPER_MAP.get(paper, "随机模考")

        questions = load_questions_from_chroma(180)

        if len(questions) < 10:
            return {"status": "error", "error": f"向量库题目不足（仅 {len(questions)} 道），无法组卷。"}

        state = {
            "paper": ptype,
            "paper_key": paper,
            "status": "active",
            "total": len(questions),
            "current_index": 0,
            "questions": questions,
            "answers": {},
            "start_ts": self._now_ts(),
            "paused_accumulated": 0,
            "last_resume_ts": self._now_ts(),
        }
        self._write(state)

        # Also init MockExamState for the legacy tracker
        try:
            ms = MockExamState()
            ms.start(exam_id=ptype, total_questions=len(questions))
        except Exception:
            pass

        return self._format_question(state, 0)

    def next_question(self) -> dict:
        """返回当前题目。"""
        state = self._read()
        if not state:
            return {"status": "error", "error": "没有活跃的模考。"}
        idx = state["current_index"]
        return self._format_question(state, idx)

    def answer(self, letter: str) -> dict:
        """记录答案并前进到下一题。"""
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
            # 全部答完 → 自动判卷
            self._write(state)
            return self.grade()

        self._write(state)
        new_idx = state["current_index"]
        return self._format_question(state, new_idx)

    def pause(self) -> dict:
        """暂停模考。"""
        state = self._read()
        if not state:
            return {"status": "error", "error": "没有活跃的模考。"}

        if state["status"] != "active":
            return {"status": "error", "error": f"模考状态为 {state['status']}，无法暂停。"}

        now = self._now_ts()
        this_leg = now - state.get("last_resume_ts", now)
        state["paused_accumulated"] = state.get("paused_accumulated", 0) + this_leg
        state["status"] = "paused"
        self._write(state)

        answered = len(state.get("answers", {}))
        elapsed = int(state["paused_accumulated"] / 60)

        return {
            "status": "paused",
            "answered": answered,
            "total": state["total"],
            "text": f"⏸️  模考已暂停（已做答 {elapsed} 分）\n   进度: {answered}/{state['total']} 题\n   回复「继续」恢复，回复「放弃模考」退出。",
        }

    def resume(self) -> dict:
        """继续模考。"""
        state = self._read()
        if not state:
            return {"status": "error", "error": "没有模考可以继续。"}

        if state["status"] != "paused":
            return {"status": "error", "error": f"模考状态为 {state['status']}，无法继续。"}

        state["status"] = "active"
        state["last_resume_ts"] = self._now_ts()
        self._write(state)

        idx = state["current_index"]
        answered = len(state.get("answers", {}))
        return {
            "status": "active",
            "text": f"▶️  模考已继续\n   进度: {answered}/{state['total']} 题",
            "next": self._format_question(state, idx),
        }

    def grade(self) -> dict:
        """判卷 + 入库 + 清空状态，返回完整报告。"""
        state = self._read()
        if not state:
            return {"status": "error", "error": "没有模考数据可判卷。"}

        questions = state.get("questions", [])
        answers = state.get("answers", {})
        total = len(questions)

        correct_count = 0
        wrong_details: list[dict] = []
        area_stats: dict[str, dict[str, int]] = {}

        for i, q in enumerate(questions):
            idx_str = str(i)
            user_ans = answers.get(idx_str, "?")
            correct_ans = q.get("correct_answer", "").strip()

            area = q.get("_area", "综合")
            if area not in area_stats:
                area_stats[area] = {"correct": 0, "total": 0}
            area_stats[area]["total"] += 1

            is_correct = user_ans == correct_ans
            if is_correct:
                correct_count += 1
                area_stats[area]["correct"] += 1
            else:
                wrong_details.append({
                    "index": i + 1,
                    "question": q.get("question", "")[:120],
                    "user_answer": user_ans,
                    "correct_answer": correct_ans,
                    "explanation": q.get("explanation", ""),
                    "area": area,
                })

        correct_rate = correct_count / total if total > 0 else 0

        # 计算用时
        total_seconds = int(state.get("paused_accumulated", 0))
        if state.get("status") == "active":
            now = self._now_ts()
            total_seconds += int(now - state.get("last_resume_ts", now))
        total_minutes = total_seconds // 60

        # ── 写入错题到 error_log + question_bank ──
        error_logger = ErrorLogger()
        question_bank = QuestionBank()

        new_error_ids: list[int] = []
        for wd in wrong_details:
            err = error_logger.add(
                question=wd["question"],
                my_answer=wd["user_answer"],
                correct_answer=wd["correct_answer"],
                knowledge_area=wd["area"],
                explanation=wd["explanation"],
            )
            err_id = err["id"]
            new_error_ids.append(err_id)

            question_bank.add(
                question=wd["question"],
                my_answer=wd["user_answer"],
                correct_answer=wd["correct_answer"],
                is_correct=False,
                knowledge_area=wd["area"],
                explanation=wd["explanation"],
                error_log_id=err_id,
            )

        # 写入正确题到 question_bank
        for i, q in enumerate(questions):
            idx_str = str(i)
            user_ans = answers.get(idx_str, "?")
            correct_ans = q.get("correct_answer", "").strip()
            if user_ans == correct_ans:
                question_bank.add(
                    question=q.get("question", ""),
                    my_answer=user_ans,
                    correct_answer=correct_ans,
                    is_correct=True,
                    knowledge_area=q.get("_area", "综合"),
                    explanation="",
                )

        # ── 写入 exam_records.json ──
        recorder = ExamRecorder()
        recorder.add(
            exam_id=state.get("paper", "模考"),
            total_questions=total,
            correct_count=correct_count,
            wrong_count=total - correct_count,
            correct_rate=correct_rate,
            time_used_minutes=total_minutes,
            total_time_seconds=total_seconds,
            scores={},
            weak_areas=[],
            knowledge_areas=area_stats,
            status="completed",
        )

        # ── 清空状态 ──
        self._clear()

        # ── 生成报告 ──
        report = self._build_report(
            state.get("paper", "模考"), total, correct_count,
            correct_rate, total_minutes, area_stats, wrong_details,
        )

        return {
            "status": "done",
            "total": total,
            "correct": correct_count,
            "wrong": total - correct_count,
            "correct_rate": round(correct_rate * 100, 1),
            "time_minutes": total_minutes,
            "error_ids": new_error_ids,
            "text": report,
        }

    def _build_report(
        self, paper: str, total: int, correct: int, rate: float,
        minutes: int, area_stats: dict, wrong_details: list[dict],
    ) -> str:
        """生成微信适配报告。"""
        lines = [
            "══════════════════════════",
            f"📋 PMP 模考报告: {paper}",
            "══════════════════════════",
            "",
            f"⏱️  做答用时: {minutes} 分钟",
            f"✏️  预估涂卡: {total * 8 // 60} 分钟（{total} 题 × 8 秒）",
            "",
            f"📊 总正确率: {correct}/{total}（{round(rate * 100, 1)}%）",
            "",
        ]

        level = "🟢 已达目标 ✅" if rate >= 0.70 else (
            "🟡 接近目标" if rate >= 0.65 else (
                "🟠 需加强" if rate >= 0.59 else "🔴 需重点关注"
            )
        )
        lines.append(f"🎯 目标判定: {level}")
        lines.append(f"   模考评估线 65%: {round(total * 0.65)} 题 | 训练目标 70%: {round(total * 0.70)} 题")
        lines.append("")

        # 各领域正确率
        if area_stats:
            lines.append("📈 各领域正确率:")
            sorted_areas = sorted(
                area_stats.items(),
                key=lambda x: x[1]["correct"] / max(1, x[1]["total"]),
            )
            for area, s in sorted_areas:
                ar = s["correct"] / max(1, s["total"]) * 100
                bar_len = max(1, int(ar / 5))
                bar = "█" * bar_len + "░" * (10 - bar_len)
                emoji = "🟢" if ar >= 70 else ("🟡" if ar >= 55 else "🔴")
                lines.append(f"  {emoji} {area}: {bar} {s['correct']}/{s['total']} ({round(ar)}%)")

        lines.append("")

        # 错题列表
        if wrong_details:
            lines.append(f"🔴 错题列表（{len(wrong_details)} 道）:")
            for wd in wrong_details[:10]:
                q_preview = wd["question"][:60]
                lines.append(f"  Q{wd['index']} [{wd['area']}]: {wd['user_answer']} → {wd['correct_answer']}")
                lines.append(f"     {q_preview}…")
            if len(wrong_details) > 10:
                lines.append(f"  …还有 {len(wrong_details) - 10} 道错题")
            lines.append("")

        lines.append(f"💡 建议: 发送「薄弱点」查看完整诊断，或「复习错题」开始复习。")

        return "\n".join(lines)

    def get_status(self) -> dict:
        """当前状态。"""
        state = self._read()
        if not state:
            return {"status": "no_exam", "text": "📭 当前没有活跃的模考。"}

        idx = state.get("current_index", 0)
        total = state.get("total", 0)
        answered = len(state.get("answers", {}))
        elapsed = int(state.get("paused_accumulated", 0))
        if state.get("status") == "active":
            now = self._now_ts()
            elapsed += int(now - state.get("last_resume_ts", now))

        return {
            "status": state.get("status"),
            "paper": state.get("paper"),
            "current_index": idx,
            "total": total,
            "answered": answered,
            "elapsed_minutes": elapsed // 60,
            "text": f"📊 模考: {state.get('paper')}\n   进度: {answered}/{total} 题\n   状态: {state.get('status')}\n   用时: {elapsed // 60} 分",
        }

    def abandon(self) -> dict:
        self._clear()
        return {"status": "abandoned", "text": "🗑️  模考已放弃，状态已清空。"}

    def _format_question(self, state: dict, idx: int) -> dict:
        """格式化一道题目。"""
        questions = state.get("questions", [])
        if idx >= len(questions):
            return {"status": "error", "error": f"题目索引越界: {idx}"}

        q = questions[idx]
        area = q.get("_area", "综合")
        question_text = q.get("question", "")
        options = q.get("options", [])

        lines = [f"📝 Q{idx + 1} [{area}]: {question_text}"]
        for opt in options:
            lines.append(opt)

        return {
            "status": "question",
            "index": idx + 1,
            "total": state["total"],
            "text": "\n".join(lines),
        }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="模考引擎")
    parser.add_argument("command", choices=[
        "start", "next", "answer", "pause", "resume",
        "grade", "status", "abandon",
    ])
    parser.add_argument("arg", nargs="?", default="", help="答案字母 或 试卷名")
    parser.add_argument("--paper", default="random", choices=["one", "two", "three", "random"])
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args()

    engine = MockExamEngine()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    result: dict = {}

    if args.command == "start":
        result = engine.start(args.paper)
    elif args.command == "next":
        result = engine.next_question()
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
        # Merge the resume message + question
        if result.get("text"):
            result["text"] += "\n\n" + nxt.get("text", "")
        result["index"] = nxt.get("index")
        result["total"] = nxt.get("total")
        result["status"] = "question"

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
