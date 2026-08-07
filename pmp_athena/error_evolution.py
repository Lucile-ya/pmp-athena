#!/usr/bin/env python3
"""
错题演化追踪 — 为每道高频错题记录「错误演化史」。

每次错误记录：错选答案 + 时间 + 根因标签
当错误次数 ≥ 3 次时，自动生成「洞察报告」：
  - 是否在两个错误答案之间反复摇摆？
  - 是否总被同一个干扰项吸引？
  - 是否知道答案但不信任自己的判断？
"""

from __future__ import annotations


try:
    from pmp_athena.config import BATCH_PRACTICE_STATE_PATH, CHROMA_PERSIST_DIR, CONFIG_JSON_PATH, DAILY_PRACTICE_DIR, DATA_DIR, ERROR_EVOLUTION_PATH, ERROR_LOG_PATH, EXAM_CONFIG_PATH, EXAM_RECORDS_PATH, KNOWLEDGE_INDEX_PATH, KNOWLEDGE_MASTERY_PATH, MOCK_EXAM_DIR, MOCK_EXAM_STATE_PATH, NOTES_DIR, OPTIONS_SUPPLEMENT_PATH, PENDING_PLAIN_QUESTION_PATH, PREP_PUSH_STATE_PATH, PROJECT_ROOT, QUESTION_BANK_PATH, REVIEW_CONFIG_PATH, REVIEW_STATE_PATH
except ModuleNotFoundError:
    from config import BATCH_PRACTICE_STATE_PATH, CHROMA_PERSIST_DIR, CONFIG_JSON_PATH, DAILY_PRACTICE_DIR, DATA_DIR, ERROR_EVOLUTION_PATH, ERROR_LOG_PATH, EXAM_CONFIG_PATH, EXAM_RECORDS_PATH, KNOWLEDGE_INDEX_PATH, KNOWLEDGE_MASTERY_PATH, MOCK_EXAM_DIR, MOCK_EXAM_STATE_PATH, NOTES_DIR, OPTIONS_SUPPLEMENT_PATH, PENDING_PLAIN_QUESTION_PATH, PREP_PUSH_STATE_PATH, PROJECT_ROOT, QUESTION_BANK_PATH, REVIEW_CONFIG_PATH, REVIEW_STATE_PATH

import json
from collections import Counter
from datetime import datetime, date
from pathlib import Path
from typing import Any

EVOLUTION_PATH = ERROR_EVOLUTION_PATH
ERROR_LOG_PATH = ERROR_LOG_PATH


def _ev_load() -> dict:
    try:
        return json.loads(EVOLUTION_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _ev_save(data: dict) -> None:
    EVOLUTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVOLUTION_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_error_log() -> list:
    try:
        data = json.loads(ERROR_LOG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ── 公共 API ──────────────────────────────────────────────────────────


def record_error(error_id: int, my_answer: str, root_cause: str | None = None) -> dict:
    """记录一次错误演化事件。每次答错调用一次。"""
    store = _ev_load()
    key = str(error_id)

    # 自动诊断根因（如未传入）
    if not root_cause:
        errors = _read_error_log()
        err = next((e for e in errors if e.get("id") == error_id), None)
        if err:
            try:
                from pmp_athena.root_cause_engine import diagnose as rc_diagnose
            except ModuleNotFoundError:
                from root_cause_engine import diagnose as rc_diagnose
            diag = rc_diagnose(err)
            root_cause = diag.get("name", "") if diag else None

    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": date.today().isoformat(),
        "my_answer": my_answer.upper().strip(),
        "root_cause": root_cause or "未分类",
    }
    store.setdefault(key, []).append(entry)
    _ev_save(store)
    return entry


def get_evolution(error_id: int) -> list[dict]:
    """获取某道错题的完整演化史（按时间升序）。"""
    store = _ev_load()
    return store.get(str(error_id), [])


def get_error_count(error_id: int) -> int:
    """演化史中的错误次数。"""
    return len(get_evolution(error_id))


def analyze_error_pattern(error_id: int) -> dict:
    """分析错误模式，≥2 次时生成洞察报告，≥3 次输出完整洞察。"""
    history = get_evolution(error_id)
    total = len(history)
    if total < 2:
        return {"status": "insufficient", "total": total}

    answer_counts = Counter(h.get("my_answer", "") for h in history)
    cause_counts = Counter(h.get("root_cause", "未分类") for h in history)
    top_answers = answer_counts.most_common(3)

    oscillating = (
        len(top_answers) >= 2
        and top_answers[0][1] >= 2
        and top_answers[1][1] >= 1
        and total >= 3
    )
    single_trap = (
        len(top_answers) == 1
        or (len(top_answers) >= 2 and top_answers[0][1] >= total - 1)
    )
    trust_issue = (
        len(top_answers) >= 2 and top_answers[0][1] >= 2 and top_answers[1][1] >= 2
    )

    insights: list[str] = []
    if oscillating:
        a1, a2 = top_answers[0][0], top_answers[1][0]
        insights.append(
            f"🔄 摇摆模式：您在 {a1} 和 {a2} 之间反复切换，"
            f"说明对这两个选项的区别不够清晰。"
        )
    if single_trap:
        trap_ans = top_answers[0][0]
        insights.append(
            f"🎯 固定陷阱：您多次被选项 {trap_ans} 吸引（{top_answers[0][1]}/{total} 次）。"
        )
    if trust_issue and not single_trap:
        insights.append(
            "🤔 信任摇摆：您在正确和错误之间反复，说明知识掌握不牢固。"
        )
    if total >= 3 and not insights:
        if len(cause_counts) >= 3:
            insights.append(
                "🌊 碎片化错误：错误原因分散，建议回归 PMBOK 框架梳理。"
            )
        else:
            insights.append(
                "📊 模式不明显：建议严格按六步推理链做题。"
            )
    return {
        "status": "ok", "error_id": error_id, "total_errors": total,
        "answer_distribution": dict(answer_counts.most_common()),
        "top_root_cause": cause_counts.most_common(1)[0] if cause_counts else ("未分类", 0),
        "oscillating": oscillating, "single_trap": single_trap,
        "trust_issue": trust_issue, "insights": insights,
    }


def format_evolution_report(error_id: int) -> str:
    """格式化演化洞察报告。"""
    report = analyze_error_pattern(error_id)
    if report["status"] == "insufficient":
        return ""
    lines = ["🧬 错题演化洞察", "═" * 20, ""]
    lines.append(f"#️⃣ 错题 #{error_id}")
    lines.append(f"📊 累计错误：{report['total_errors']} 次")
    dist = report.get("answer_distribution", {})
    if dist:
        lines.append(f"📋 错选分布：{' | '.join(f'{a}:{c}次' for a,c in dist.items())}")
    rc = report.get("top_root_cause", ("", 0))
    if rc[1] > 0:
        lines.append(f"🔍 主要根因：{rc[0]}（{rc[1]}次）")
    for i in report.get("insights", []):
        lines.append(f"\n{i}")
    return "\n".join(lines)


def format_evolution_summary(error_id: int) -> str:
    """一句话演化摘要。"""
    report = analyze_error_pattern(error_id)
    if report["status"] == "insufficient":
        return ""
    if report["oscillating"]:
        return "🔄 摇摆模式 — 注意区分易混选项"
    if report["single_trap"]:
        return "🎯 固定陷阱 — 警惕干扰项伪装"
    if report["trust_issue"]:
        return "🤔 信任摇摆 — 相信第一直觉"
    return "📊 碎片化 — 按推理链做题"


# ── CLI ───────────────────────────────────────────────────────────────


def main():
    import argparse, sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError: pass
    p = argparse.ArgumentParser(description="错题演化追踪")
    s = p.add_subparsers(dest="cmd")
    r = s.add_parser("record", help="记录一次错误")
    r.add_argument("error_id", type=int)
    r.add_argument("--answer", "-a", required=True)
    r.add_argument("--root-cause", "-r")
    rep = s.add_parser("report", help="演化洞察报告")
    rep.add_argument("error_id", type=int)
    rep.add_argument("--json", action="store_true")
    sm = s.add_parser("summary", help="一句话摘要")
    sm.add_argument("error_id", type=int)
    args = p.parse_args()
    if not args.cmd: p.print_help(); return
    if args.cmd == "record":
        print(json.dumps(record_error(args.error_id, args.answer, args.root_cause), ensure_ascii=False))
    elif args.cmd == "report":
        if args.json: print(json.dumps(analyze_error_pattern(args.error_id), ensure_ascii=False))
        else: print(format_evolution_report(args.error_id))
    elif args.cmd == "summary":
        print(format_evolution_summary(args.error_id))


if __name__ == "__main__":
    main()
