#!/usr/bin/env python3
"""
根因诊断引擎 —— 高频错题错误模式识别

根据错选答案 + 题干关键词，自动生成：
- ⚠️ 根因诊断：用户为什么错
- 🎯 破解口诀：一句话记住正确思路

纯规则引擎，不依赖 LLM。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

QUESTION_BANK = Path("D:/pmp-athena/pmp_notes/question_bank.json")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ── 根因诊断规则库 ──────────────────────────────────────────────────
# 每条规则: (name, condition_fn, diagnosis, mnemonic)
# condition_fn(error_dict, wrong_records) → bool
#
# 匹配策略：按顺序逐条检测，命中第一条即返回。
# 规则越具体越靠前。

DIAGNOSIS_RULES: list[dict] = []


def _register(keywords: list[str], wrong_answer_hints: list[str],
              diagnosis: str, mnemonic: str, name: str = "") -> dict:
    """注册诊断规则。"""
    rule = {
        "name": name,
        "keywords": keywords,
        "wrong_answer_hints": wrong_answer_hints,
        "diagnosis": diagnosis.strip(),
        "mnemonic": mnemonic.strip(),
    }
    DIAGNOSIS_RULES.append(rule)
    return rule


# ── 规则 1: 风险/问题混淆 ──
_register(
    name="混淆风险与问题",
    keywords=["风险", "威胁", "问题", "上报", "修订", "报告"],
    wrong_answer_hints=["上报", "修订", "报告", "提交变更"],
    diagnosis=(
        "你把『问题』（已发生的事实）当成了『风险』（未发生的可能性），"
        "或试图越级上报/修订报告而非按流程处理。\n"
        "记住：已发生的是问题 → 问题日志；未发生的是风险 → 风险登记册。"
    ),
    mnemonic="风险登记册管未来，问题日志管已发生。先记录再应对，别越级乱投医。",
)

# ── 规则 2: 质量审计 vs 控制质量 ──
_register(
    name="混淆质量审计与控制质量",
    keywords=["质量审计", "控制质量", "管理质量", "QA", "QC", "审计", "缺陷", "可交付成果"],
    wrong_answer_hints=["控制质量", "QC"],
    diagnosis=(
        "混淆了『执行』和『监控』：质量审计（管理质量/QA）管过程是否合规，"
        "控制质量（QC）查可交付物结果是否达标。\n"
        "审计 = 独立审查过程，控制质量 = 测量具体结果。"
    ),
    mnemonic="QA 管过程审计，QC 查交付物结果。审计看对不对，控制看好不好。",
)

# ── 规则 3: 新干系人处理 ──
_register(
    name="新干系人先沟通再工具",
    keywords=["新干系人", "新识别", "新加入", "相关方出现", "干系人变化", "新相关方"],
    wrong_answer_hints=["更新登记册", "PMIS", "门户", "邮件", "文档库"],
    diagnosis=(
        "新干系人出现时，你选了工具/文档类方案。但 PMP 的核心原则是『先人后工具』："
        "先当面沟通、了解需求、建立信任，再更新登记册或使用工具。"
    ),
    mnemonic="新方进场先开口，会面沟通第一手。登记册更新排在后面，千万别抢跑。",
)

# ── 规则 4: 变更流程 ──
_register(
    name="变更未评估就执行",
    keywords=["变更", "CCB", "变更请求", "变更控制", "基准", "SOW"],
    wrong_answer_hints=["修订流程", "更换供应商", "直接实施", "通知"],
    diagnosis=(
        "面对变更请求时，你跳过了关键步骤：变更流程的核心顺序是"
        "评估影响 → 提交 CCB 审批 → 批准后才实施。"
        "不能先改再评估，也不能跳过 CCB 直接动手。"
    ),
    mnemonic="变更先评估，CCB 批了再动刀。未批不变更，变更必留痕。",
)

# ── 规则 5: 敏捷进度失真 ──
_register(
    name="敏捷进度失真的根因是文化",
    keywords=["燃尽图", "进度报告", "报喜不报忧", "站会", "透明", "心理安全",
              "进度失真", "报告失真"],
    wrong_answer_hints=["报告工具", "燃尽图配置", "升级工具", "做报告培训"],
    diagnosis=(
        "进度报告失真不是工具的问题，是信任和透明文化的缺失。"
        "敏捷中团队成员缺乏心理安全感时，会报喜不报忧。"
        "正确答案通常是『早期培训 + 持续辅导（Coaching）』，而非升级工具。"
    ),
    mnemonic="进度失真查文化，透明信任是根因。先育人再改工具，Coaching 治本不治标。",
)

# ── 规则 6: 合同类型混淆 ──
_register(
    name="合同类型选择错误",
    keywords=["FFP", "固定总价", "工料合同", "成本补偿", "采购", "合同", "卖方", "买方"],
    wrong_answer_hints=["固定总价", "FFP", "成本补偿", "工料"],
    diagnosis=(
        "合同类型决定了风险在谁身上：FFP 固定总价 = 卖方承担成本超支风险（买方最安全），"
        "成本补偿 = 买方承担风险（卖方实报实销），工料合同 = 双方共担。"
        "选合同前先判断：谁该承担主要风险？"
    ),
    mnemonic="FFP 卖方扛风险，成本补偿买方买单，工料双方一起担。先看风险再选合同。",
)

# ── 规则 7: 冲突解决优先级 ──
_register(
    name="冲突解决策略选错",
    keywords=["冲突", "分歧", "争吵", "矛盾", "团队冲突"],
    wrong_answer_hints=["强迫", "回避", "妥协"],
    diagnosis=(
        "PMP 冲突解决的优先级是：合作/解决问题（双赢）> 妥协 > 缓和 > 强迫 > 回避。"
        "你选的可能是低优先级的策略。首选永远是『合作/解决问题』，强迫是最后手段。"
    ),
    mnemonic="冲突先合作双赢，强迫回避是下策。坐下来谈比绕开走强。",
)

# ── 规则 8: 储备分析混淆 ──
_register(
    name="应急储备与管理储备混淆",
    keywords=["储备", "应急储备", "管理储备", "已知", "未知", "成本不确定"],
    wrong_answer_hints=["管理储备", "应急储备"],
    diagnosis=(
        "应急储备是『已知的未知』（已识别的风险），PM 可以自行使用，费用在成本基准内。"
        "管理储备是『未知的未知』（未识别的风险），使用时需要变更基准，需管理层批准。"
    ),
    mnemonic="应急储备已知风险 PM 可用，管理储备未知风险需变更基准。",
)

# ── 规则 9: 估算方法混淆 ──
_register(
    name="估算方法选择不当",
    keywords=["没有任何数据", "无历史", "新项目", "估算", "自下而上", "三点", "类比"],
    wrong_answer_hints=["三点估算", "类比估算", "参数估算"],
    diagnosis=(
        "没有历史数据时，类比估算无法用（需要类似项目），参数估算也无法用（需要数据公式）。"
        "自下而上估算虽然最费时，但『没有数据』时是最可靠的选择。"
    ),
    mnemonic="没数据别三点，自下而上最稳当。有历史用类比，有公式用参数。",
)

# ── 规则 10: 干系人权力利益方格 ──
_register(
    name="干系人管理策略选错",
    keywords=["权力", "利益", "干系人", "相关方", "管理策略"],
    wrong_answer_hints=["令其满意", "监督", "告知"],
    diagnosis=(
        "干系人管理策略取决于权力-利益方格：高权力高利益 = 密切管理，"
        "高权力低利益 = 令其满意，低权力高利益 = 随时告知，低权力低利益 = 监督。"
        "判断错了象限就选错了策略。"
    ),
    mnemonic="高权高利密切管，高权低利令其满。低权高利随时告，低权低利监督就行。",
)

# ── 规则 11: 问题 vs 风险（通用版）──
_register(
    name="已发生当成未发生",
    keywords=["已发生", "已经", "目前", "现在", "当前"],
    wrong_answer_hints=["风险登记册", "风险应对", "应急计划"],
    diagnosis=(
        "题干描述的是『已经发生的事情』（问题），你选了风险相关的选项。"
        "已发生 → 问题日志 + 解决问题；未发生 → 风险登记册 + 预防。"
    ),
    mnemonic="问题已发生记日志，风险未发生入登记册。已发生先解决，未发生先预防。",
)

# ── 规则 12: 敏捷团队决策 ──
_register(
    name="敏捷中替团队做决定",
    keywords=["敏捷", "Scrum", "自组织", "迭代", "PO", "SM"],
    wrong_answer_hints=["项目经理决定", "PM 决策", "管理者"],
    diagnosis=(
        "敏捷团队是自组织的，PO 排优先级、SM 清障碍，但决策权在开发团队。"
        "你选了管理层/PM 替团队做决定，这违背了敏捷自组织原则。"
    ),
    mnemonic="PO 定优先级，SM 清障碍，团队自组织做决策。敏捷不越权。",
)


# ── 公共 API ──────────────────────────────────────────────────────


def get_wrong_history(error_id: int) -> list[dict]:
    """获取某道错题在 question_bank 中的全部错误记录（按日期降序）。"""
    bank = _load_json(QUESTION_BANK)
    if not isinstance(bank, list):
        return []
    records = [
        r for r in bank
        if r.get("error_log_id") == error_id and r.get("is_correct") is False
    ]
    records.sort(key=lambda r: r.get("date", ""), reverse=True)
    return records


def diagnose(error: dict, wrong_records: list[dict] | None = None) -> dict | None:
    """
    对一道错题进行根因诊断。

    参数:
        error: error_log.json 中的错题记录
        wrong_records: question_bank 中该题的全部错误记录（可选，不传则自动查）

    返回:
        {"name": str, "diagnosis": str, "mnemonic": str} 或 None
    """
    if wrong_records is None:
        wrong_records = get_wrong_history(error.get("id", 0))

    # Build the full text corpus for keyword matching
    q = error.get("question", "")
    expl = error.get("explanation", "")
    my_ans = str(error.get("my_answer", "")).upper()
    combined = f"{q} {expl}"

    # Collect all previous wrong answers for pattern matching
    all_wrong_answers = {my_ans}
    for wr in wrong_records:
        wa = str(wr.get("my_answer", "")).upper()
        if wa:
            all_wrong_answers.add(wa)

    for rule in DIAGNOSIS_RULES:
        # Check keyword match
        kw_match = any(kw in combined for kw in rule.get("keywords", []))

        # Check wrong answer pattern match
        wa_match = any(
            hint in ans or ans in hint
            for hint in rule.get("wrong_answer_hints", [])
            for ans in all_wrong_answers
        )

        # Need at least keyword match AND wrong-answer match, or strong keyword
        # match with 3+ keywords hitting
        kw_hits = sum(1 for kw in rule.get("keywords", []) if kw in combined)

        if wa_match and kw_match:
            return {
                "name": rule["name"],
                "diagnosis": rule["diagnosis"],
                "mnemonic": rule["mnemonic"],
            }

        if kw_hits >= 3:
            return {
                "name": rule["name"],
                "diagnosis": rule["diagnosis"],
                "mnemonic": rule["mnemonic"],
            }

    return None


def format_root_cause_card(diag: dict) -> str:
    """将诊断结果格式化为微信推送文本。"""
    name = diag.get("name", "")
    diagnosis = diag.get("diagnosis", "")
    return f"[{name}]\n{diagnosis}"


def format_mnemonic_line(diag: dict) -> str:
    """只提取口诀行。"""
    return diag.get("mnemonic", "")


# ── CLI ───────────────────────────────────────────────────────────


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="根因诊断引擎")
    sub = parser.add_subparsers(dest="command")

    p_diag = sub.add_parser("diagnose", help="对错题进行根因诊断")
    p_diag.add_argument("error_id", type=int, help="错题 ID")
    p_diag.add_argument("--json", action="store_true")

    p_card = sub.add_parser("card", help="格式化诊断卡片")
    p_card.add_argument("error_id", type=int, help="错题 ID")
    p_card.add_argument("--json", action="store_true")

    args = parser.parse_args()

    # 显式用 UTF-8 编码输出
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    if not args.command:
        parser.print_help()
        sys.exit(1)

    EL_PATH = Path("D:/pmp-athena/pmp_notes/error_log.json")

    errors = _load_json(EL_PATH)
    if not isinstance(errors, list):
        errors = []
    error = next((e for e in errors if e.get("id") == args.error_id), None)

    if not error:
        result = {"status": "error", "text": f"错题 #{args.error_id} 不存在"}
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(result["text"])
        return

    wrong_records = get_wrong_history(args.error_id)
    diag = diagnose(error, wrong_records)

    if not diag:
        result = {"status": "empty", "text": "未匹配到诊断规则"}
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(result["text"])
        return

    if args.command == "card":
        text = f"⚠️ 根因诊断：{format_root_cause_card(diag)}\n🎯 破解口诀：{format_mnemonic_line(diag)}"
    else:
        text = format_root_cause_card(diag)

    if args.json:
        print(json.dumps({"status": "ok", "diag": diag, "text": text}, ensure_ascii=False))
    else:
        print(text)


if __name__ == "__main__":
    main()
