#!/usr/bin/env python3
"""
错题深度解读 —— 总结 / 解答 / 口诀

供复习判卷、高频错题清单等场景使用。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ERROR_LOG = Path("D:/pmp-athena/pmp_notes/error_log.json")
REVIEW_STATE = Path("D:/pmp-athena/pmp_notes/error_review_state.json")
QUESTION_BANK = Path("D:/pmp-athena/pmp_notes/question_bank.json")

try:
    from pmp_athena.image_processor import clean_explanation_text
except ModuleNotFoundError:
    from image_processor import clean_explanation_text

# (题干/解析关键词, 总结, 口诀)
SCENARIO_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (
        ("新干系人", "新识别", "新加入", "相关方出现", "干系人变化"),
        "出现新干系人时，先沟通了解需求，再更新工具/登记册。",
        "新方进场先开口，先人后工具不用愁。",
    ),
    (
        ("燃尽图", "进度报告", "报喜不报忧", "站会", "透明", "心理安全"),
        "进度失真往往是信任/透明文化问题，先育人再改工具。",
        "进度失真查文化，透明信任是根因。",
    ),
    (
        ("储备分析", "应急储备", "管理储备", "成本不确定", "价格波动"),
        "成本估算中的不确定性用储备分析（应急+管理储备）应对。",
        "成本有波动找储备，汇总三点都不靠。",
    ),
    (
        ("没有任何数据", "无历史", "新项目", "自下而上"),
        "无历史数据时优先自下而上估算，类比/三点需经验或类似项目。",
        "没数据别三点，自下而上最稳当。",
    ),
    (
        ("变更", "CCB", "变更请求", "变更控制"),
        "变更流程：评估影响 → 提交 CCB → 批准后实施。",
        "变更先评估，CCB 批了再动刀。",
    ),
    (
        ("风险", "威胁", "应对策略", "规避", "转移"),
        "风险应对：规避 > 转移 > 减轻 > 接受 > 上报（超权限）。",
        "风险应对有顺序，规避转移减轻接受。",
    ),
    (
        ("冲突", "团队冲突", "分歧"),
        "冲突解决首选合作/解决问题，强迫是最后手段。",
        "冲突先合作，强迫是下策。",
    ),
    (
        ("FFP", "固定总价", "工料合同", "成本补偿", "采购"),
        "合同类型决定风险分担：FFP 卖方担风险，成本补偿买方担风险。",
        "FFP 卖方扛，成本补偿买方扛。",
    ),
]

AREA_MNEMONICS: dict[str, str] = {
    "整合管理": "章程授权定方向，变更CCB要把关。",
    "范围管理": "范围基准三件套，WBS 分解不能少。",
    "进度管理": "关键路径定工期，赶工快速要分清。",
    "成本管理": "挣值看偏差，储备防不确定。",
    "质量管理": "QA 管过程，QC 查结果。",
    "资源管理": "RACI 分责任，团队发展五阶段。",
    "沟通管理": "交互式最好，推式拉式次之。",
    "风险管理": "先识别再分析，应对策略记心间。",
    "采购管理": "合同类型定风险，投标人会议要一致。",
    "干系人管理": "权力利益分方格，新方先沟通。",
    "敏捷/混合方法": "PO 定优先级，SM 清障碍，团队自组织。",
    "商业环境": "商业论证做依据，合规收益两手抓。",
    "领导力/人员": "激励情商与冲突，仆人式领导是核心。",
}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return [] if path.name != "error_review_state.json" else {}


def count_mistakes(error_id: int) -> dict[str, int]:
    """统计某道错题的错误次数（题库 + 复习历史）。"""
    bank = _load_json(QUESTION_BANK)
    review = _load_json(REVIEW_STATE)
    if not isinstance(bank, list):
        bank = []
    if not isinstance(review, dict):
        review = {}

    bank_wrong = sum(
        1 for r in bank
        if r.get("error_log_id") == error_id and r.get("is_correct") is False
    )
    card = review.get(str(error_id), {})
    review_wrong = sum(
        1 for h in card.get("history", [])
        if int(h.get("quality", 5)) < 3
    )
    total = max(bank_wrong, 1) + review_wrong
    return {
        "bank_wrong": bank_wrong,
        "review_wrong": review_wrong,
        "total": total,
    }


def is_high_frequency(error_id: int, *, threshold: int = 2) -> bool:
    return count_mistakes(error_id)["total"] >= threshold


def _match_scenario(text: str) -> tuple[str, str] | None:
    for keywords, summary, mnemonic in SCENARIO_RULES:
        if any(kw in text for kw in keywords):
            return summary, mnemonic
    return None


def build_summary(error: dict) -> str:
    """一句话总结错因/考点。"""
    q = error.get("question", "")
    expl = error.get("explanation", "")
    blob = f"{q} {expl}"
    matched = _match_scenario(blob)
    if matched:
        return matched[0]

    area = error.get("knowledge_area", "综合")
    my_a = error.get("my_answer", "?")
    correct = error.get("correct_answer", "?")
    return (
        f"[{area}] 易混淆选项 {my_a} 与 {correct}，"
        f"核心考点是选 {correct} 对应的场景/工具/流程。"
    )


def build_mnemonic(error: dict) -> str:
    """记忆口诀（规则优先，领域兜底）。"""
    q = error.get("question", "")
    expl = error.get("explanation", "")
    stored = (error.get("mnemonic") or "").strip()
    if stored:
        return stored

    matched = _match_scenario(f"{q} {expl}")
    if matched:
        return matched[1]

    area = error.get("knowledge_area", "")
    if area in AREA_MNEMONICS:
        return AREA_MNEMONICS[area]

    correct = error.get("correct_answer", "")
    return f"记牢正确选项 {correct} 对应的 PMBOK 场景，同类题先想 '{area}' 核心原则。"


def build_answer_text(error: dict) -> str:
    """完整解答（清洗 OCR 噪音）。"""
    expl = clean_explanation_text(str(error.get("explanation", "")))
    if expl:
        return expl

    area = error.get("knowledge_area", "综合")
    correct = error.get("correct_answer", "?")
    summary = build_summary(error)
    return f"正确答案是 {correct}。{summary} 建议回顾 [{area}] 教材对应章节。"


def format_wrong_feedback(error: dict, *, user_answer: str | None = None) -> str:
    """复习/复盘用的三段式反馈：总结 + 解答 + 口诀。"""
    eid = error.get("id")
    correct = str(error.get("correct_answer", "?")).upper()
    my = (user_answer or error.get("my_answer", "?")).upper()
    counts = count_mistakes(int(eid)) if eid else {"total": 1}

    lines = [f"❌ 正确答案是 {correct}（你选了 {my}）"]
    if counts["total"] >= 2:
        lines.append(f"🔥 高频错题 · 累计错 {counts['total']} 次")

    lines.append(f"📌 总结: {build_summary(error)}")
    lines.append(f"💡 解答: {build_answer_text(error)}")
    lines.append(f"🎯 口诀: {build_mnemonic(error)}")
    return "\n".join(lines)


def rank_high_frequency_errors(
    *,
    top_n: int = 5,
    min_mistakes: int = 2,
) -> list[dict]:
    """按错误频次排序，返回 enriched 列表。"""
    errors = _load_json(ERROR_LOG)
    if not isinstance(errors, list):
        return []

    ranked: list[tuple[int, dict]] = []
    for err in errors:
        eid = err.get("id")
        if not eid:
            continue
        c = count_mistakes(int(eid))
        if c["total"] >= min_mistakes:
            ranked.append((c["total"], err))

    ranked.sort(key=lambda x: (-x[0], -x[1].get("id", 0)))
    out = []
    for cnt, err in ranked[:top_n]:
        out.append({
            "error_id": err["id"],
            "mistake_count": cnt,
            "knowledge_area": err.get("knowledge_area", "未分类"),
            "question_preview": re.sub(r"\s+", " ", err.get("question", ""))[:60],
            "feedback": format_wrong_feedback(err),
        })
    return out


def format_high_frequency_report(*, top_n: int = 5) -> str:
    """微信推送：高频错题清单（每题含总结+解答+口诀）。"""
    items = rank_high_frequency_errors(top_n=top_n)
    if not items:
        return (
            "📋 暂无高频错题（同一题错 ≥2 次才会上榜）。\n"
            "继续刷题积累，或发送「复习错题」开始复习。"
        )

    lines = [
        "🔥 高频错题 TOP",
        "══════════════════════",
        f"共 {len(items)} 道（按累计错误次数排序）",
        "",
    ]
    for i, item in enumerate(items, 1):
        lines.append(f"── #{item['error_id']} [{item['knowledge_area']}] 错 {item['mistake_count']} 次 ──")
        lines.append(f"📝 {item['question_preview']}…")
        lines.append(item["feedback"])
        lines.append("")

    lines.append("💡 发送「复习错题」可逐题巩固以上题目。")
    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="错题深度解读")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=5)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="高频错题清单")
    p_fb = sub.add_parser("feedback", help="单题三段式反馈")
    p_fb.add_argument("error_id", type=int)

    args = parser.parse_args()
    if args.command == "feedback":
        errors = _load_json(ERROR_LOG)
        err = next((e for e in errors if e.get("id") == args.error_id), None)
        if not err:
            print(json.dumps({"status": "error", "text": "未找到"}, ensure_ascii=False))
            return
        text = format_wrong_feedback(err)
        if args.json:
            print(json.dumps({"status": "ok", "text": text}, ensure_ascii=False))
        else:
            print(text)
        return

    text = format_high_frequency_report(top_n=args.top)
    if args.json:
        print(json.dumps({"status": "ok", "text": text}, ensure_ascii=False))
    else:
        print(text)


if __name__ == "__main__":
    main()
