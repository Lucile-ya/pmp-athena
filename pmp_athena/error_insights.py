#!/usr/bin/env python3
"""
错题深度解读 —— 总结 / 解答 / 口诀

供复习判卷、高频错题清单等场景使用。
"""

from __future__ import annotations
try:
    from pmp_athena.config import ERROR_LOG_PATH, QUESTION_BANK_PATH, REVIEW_STATE_PATH
except ModuleNotFoundError:
    from config import ERROR_LOG_PATH, QUESTION_BANK_PATH, REVIEW_STATE_PATH


import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

ERROR_LOG = ERROR_LOG_PATH
REVIEW_STATE = REVIEW_STATE_PATH
QUESTION_BANK = QUESTION_BANK_PATH

try:
    from pmp_athena.image_processor import clean_explanation_text
except ModuleNotFoundError:
    from image_processor import clean_explanation_text

# (题干/解析关键词, 总结, 口诀)
# 更具体的规则必须排在前面：否则「转移/采购/变更」会误配镀金、合同审查题。
SCENARIO_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (
        ("虚拟团队", "文化不同", "地理分散", "文化数据", "职业道德"),
        "虚拟团队文化差异：主动收集文化信息并让成员参与讨论，别只登记风险或解散虚队。",
        "虚队文化先摸底讨论，别只登风险或解散。",
    ),
    (
        ("who would be responsible", "交付责任并不明确", "责任归属", "重叠的领域", "资源管理计划"),
        "责任归属不清查资源管理计划（管 who）；WBS 只管 what。",
        "责任不清查资源计划，WBS管事不管人。",
    ),
    (
        ("关闭标准", "即将结束", "添加功能", "镀金", "产品拥护者", "释放剩余"),
        "已满足关闭标准时释放资源，剩余时间/预算不加功能。",
        "满足关闭就收摊，剩余预算不镀金。",
    ),
    (
        ("采购协议", "供应商将无法", "无法在约定的日期", "延迟交货"),
        "供应商无法按期交货，先审查采购协议按合同处理。",
        "供应商延期先审合同，别先换商改待办。",
    ),
    (
        ("回顾会议", "retrospective", "用户体验的错误", "影响用户体验"),
        "敏捷质量问题先开回顾，让团队自组织找根因，别靠外部激励。",
        "质量问题开回顾，自组织找根因。",
    ),
    (
        ("战略一致性", "目标效益", "测量指标", "选择项目", "选择标准"),
        "选项目看战略一致+效益+可测指标，别靠 CEO 拍板。",
        "选项目看战略效益指标，CEO拍板不算数。",
    ),
    (
        ("多个不同层面", "不同技术知识", "组织类型最有效", "共享专业"),
        "多项目多技术用强矩阵共享专业人才，别上纯项目型独占资源。",
        "多项目多技术用强矩阵，别独占资源。",
    ),
    (
        ("职权比职能经理", "授予项目经理的职权", "职权比职能"),
        "PM 权>职能经理=强矩阵；职能<弱<平衡<强<项目型。",
        "PM权大于职能是强矩阵。",
    ),
    (
        ("自管预算", "信息辐射源", "费用报告", "冲刺评审评估费用"),
        "预算透明：站会费用报告+信息辐射源；冲刺评审看增量不是审预算。",
        "预算透明靠站会和信息辐射，评审不审账。",
    ),
    (
        ("监督外部环境", "监测外部环境", "法规变更、技术创新", "持续变更"),
        "敏捷持续变更靠 PO 监测外部环境并调 backlog，不是停变更。",
        "持续变更找PO盯环境，别叫停范围。",
    ),
    (
        ("backlog优先级", "通知PO", "全员远程", "重新排优先级"),
        "Backlog 优先级是 PO 的事，PM 尽快通知 PO，自己不越权重排。",
        "优先级变动先告PO，PM自己重排越权。",
    ),
    (
        ("预期完工", "速率", "故事点", "周期时间", "不会在项目前期"),
        "敏捷用稳定速率/周期时间预测完工，不设传统基准。",
        "敏捷靠速率预测工期，不设传统基准。",
    ),
    (
        ("用户操作指南", "合同规定", "用户手册", "详尽的文档"),
        "合同要求的文档必须交付，敏捷也不豁免合同。",
        "合同要文档就得交，敏捷不豁免合同。",
    ),
    (
        ("丢失了", "根本原因", "经验教训会议", "遗漏的过程"),
        "问题已发生先找根因，经验教训放后面。",
        "已发生先找根因，教训会放到收尾。",
    ),
    (
        ("问题日志", "转入问题日志", "发生了就是问题"),
        "已发生记问题日志，未发生才进风险登记册。",
        "发生了就是问题，没发生就是风险。",
    ),
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
        ("风险应对", "风险登记册", "规避", "减轻威胁"),
        "风险应对：规避 > 转移 > 减轻 > 接受 > 上报（超权限）。",
        "风险应对有顺序，规避转移减轻接受。",
    ),
    (
        ("冲突", "团队冲突", "分歧"),
        "冲突解决首选合作/解决问题，强迫是最后手段。",
        "冲突先合作，强迫是下策。",
    ),
    (
        ("FFP", "固定总价", "工料合同", "成本补偿合同"),
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


@lru_cache(maxsize=512)
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


def is_high_frequency(error_id: int, *, threshold: int = 3) -> bool:
    return count_mistakes(error_id)["total"] >= threshold


# ── 高频错题标记管理（持久化到 error_review_state.json）──────────


def mark_high_frequency(error_id: int) -> bool:
    """标记为高频错题。返回 True 表示新标记，False 表示已存在。"""
    review = _load_json(REVIEW_STATE)
    if not isinstance(review, dict):
        review = {}
    key = str(error_id)
    if key not in review:
        review[key] = {"error_id": error_id, "high_frequency": True}
    elif review[key].get("high_frequency"):
        return False
    else:
        review[key]["high_frequency"] = True
    REVIEW_STATE.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_STATE.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def unmark_high_frequency(error_id: int) -> bool:
    """取消高频标记。返回 True 表示之前有标记，False 表示本就没有。"""
    review = _load_json(REVIEW_STATE)
    if not isinstance(review, dict):
        review = {}
    key = str(error_id)
    if key in review and review[key].get("high_frequency"):
        review[key]["high_frequency"] = False
        REVIEW_STATE.parent.mkdir(parents=True, exist_ok=True)
        REVIEW_STATE.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    return False


def is_high_frequency_marked(error_id: int) -> bool:
    """检查 error_review_state.json 中是否已有高频标记。"""
    review = _load_json(REVIEW_STATE)
    if not isinstance(review, dict):
        return False
    return bool(review.get(str(error_id), {}).get("high_frequency"))


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
    return f"[{area}] 易混淆干扰项，先锁场景/工具/流程再选动作。"


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

    # 禁止甩领域万能句：从解析压一句可背的
    tip = _mnemonic_from_explanation(expl)
    if tip:
        return tip

    area = error.get("knowledge_area", "")
    if area in AREA_MNEMONICS:
        return AREA_MNEMONICS[area]

    return "先锁场景再选动作，别靠语感蒙。"


def _mnemonic_from_explanation(expl: str) -> str:
    text = clean_explanation_text(str(expl or "")).strip()
    if not text:
        return ""
    # 优先中文句；丢掉纯英文/选项字母残留
    for part in re.split(r"[。！？\n|;；|]", text):
        first = part.strip()
        first = re.sub(r"[A-Za-z]{10,}", "", first)  # 去掉 whowouldberesponsible 一类，保留 Kick-off/CEO
        first = _strip_option_letters(re.sub(r"\s+", "", first))
        first = re.sub(r"^题干问的是['\"‘’].*?[—\-]+", "", first)  # 去掉「题干问的是'…'——」壳
        if len(first) < 8:
            continue
        if len(first) > 28:
            first = first[:27] + "…"
        return first
    return ""


def _strip_option_letters(text: str) -> str:
    """摘要卡去掉选项字母（A/B/C/D），只留可背语义。"""
    t = text or ""
    t = re.sub(r"别再选\s*[A-Ea-e]\s*，?\s*锁\s*[A-Ea-e]\s*[：:.]?\s*", "", t)
    t = re.sub(r"(?:别再选|应选|锁|选了?)\s*[A-Ea-e]\b[：:.]?\s*", "", t)
    t = re.sub(r"易混淆选项\s*[A-Ea-e]\s*与\s*[A-Ea-e]", "易混淆干扰项", t)
    t = re.sub(r"选项\s*[A-Ea-e]\b", "干扰项", t)
    t = re.sub(r"(?<![A-Za-z])[A-Ea-e]\s*[\(（]", "(", t)  # C(集成计划) → (集成计划)
    t = re.sub(r"[A-Ea-e]\s*[→\-–—]+\s*[A-Ea-e]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.strip(" ：:，,")


def build_trap_line(error: dict) -> str:
    """别踩：一句话点出干扰项（不写选项字母）。"""
    expl = clean_explanation_text(str(error.get("explanation") or ""))
    summary = build_summary(error)
    q = str(error.get("question") or "")
    # 规则命中时直接用总结，避免从半截解析抠出「明书)」一类残句
    if _match_scenario(f"{q} {expl}"):
        tip = _strip_option_letters(summary)
        if len(tip) > 32:
            tip = tip[:31] + "…"
        return tip
    # 从解析里抓「别/不要/而非/不是」类
    m = re.search(r"[^。]{0,20}(?:不要|别|而非|不是|勿)[^。]{2,30}", expl)
    if m:
        tip = _strip_option_letters(re.sub(r"\s+", "", m.group(0)))
        # 残句/选项碎片不要
        if tip and re.search(r"[\u4e00-\u9fff]{4,}", tip) and not re.match(
            r"^[\)\]\}，,、.．]", tip
        ):
            if len(tip) > 28:
                tip = tip[:27] + "…"
            return tip
    tip = _strip_option_letters(summary[:32] if summary else "")
    return tip


def format_quest_summary_card(error: dict, *, mistake_count: int = 0) -> str:
    """今日任务③摘要卡：能背，不甩选项字母。"""
    eid = error.get("id", "?")
    area = error.get("knowledge_area") or "综合"
    if str(area).startswith("敏捷"):
        area = "敏捷"
    q = re.sub(r"\s+", " ", str(error.get("question") or ""))
    # 去掉选项，只留题眼
    stem = re.split(r"\s*[A-E][\.、．\)]\s*", q)[0].strip()
    if len(stem) > 42:
        stem = stem[:41] + "…"
    mnemonic = _strip_option_letters(build_mnemonic(error))
    trap = build_trap_line(error)
    fire = f"🔥{mistake_count}次" if mistake_count >= 3 else f"错{mistake_count}次"
    lines = [
        f"#{eid} [{area}] {fire}",
        f"题眼：{stem}",
        f"背：{mnemonic}",
    ]
    if trap:
        lines.append(f"别踩：{trap}")
    return "\n".join(lines)


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
    """复习错题反馈：一行对错 + 一口诀，避免微信刷屏。"""
    correct = str(error.get("correct_answer", "?")).upper()
    my = (user_answer or error.get("my_answer", "?")).upper()
    mnemonic = build_mnemonic(error)
    summary = build_summary(error)
    tip = mnemonic if mnemonic and not mnemonic.startswith("记牢正确选项") else summary
    lines = [f"❌ 你的 {my} → 正确 {correct}"]
    if tip:
        lines.append(f"🎯 {tip}")
    return "\n".join(lines)


def rank_high_frequency_errors(
    *,
    top_n: int = 5,
    min_mistakes: int = 3,
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
            "📋 暂无高频错题（同一题错 ≥3 次才会上榜）。\n"
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
