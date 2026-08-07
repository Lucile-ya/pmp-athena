#!/usr/bin/env python3
"""批量补全错题/题库中缺失的 A-D 选项，并同步三处数据。"""

import json
import re
from pathlib import Path

ERROR_LOG = ERROR_LOG_PATH
QUESTION_BANK = QUESTION_BANK_PATH
OPTIONS_SUPPLEMENT = OPTIONS_SUPPLEMENT_PATH

OPTION_RE = re.compile(r"(?:^|\s)[A-D][\.、．\)]")

# 选项来源：解析/标准 PMP 题库/ExamTopics & examsvce 交叉验证
SUPPLEMENT: dict[int, dict[str, str]] = {
    1: {
        "A": "与干系人会面，了解其不满的原因和关切",
        "B": "更新项目进度计划以反映最新状态",
        "C": "将问题上报给项目发起人处理",
        "D": "更新干系人登记册",
    },
    2: {
        "A": "控制图",
        "B": "因果图（鱼骨图）",
        "C": "散点图",
        "D": "帕累托图",
    },
    3: {
        "A": "快速跟进",
        "B": "资源平衡",
        "C": "赶工",
        "D": "关键链",
    },
    8: {
        "A": "实施控制质量",
        "B": "更新问题日志",
        "C": "实施质量审计",
        "D": "核实变更请求",
    },
    9: {
        "A": "制定敏捷风险宣言以指导团队",
        "B": "任命产品负责人兼任风险经理",
        "C": "聘请专职风险经理负责风险管理",
        "D": "在每个迭代中持续识别、分析和管理风险",
    },
    10: {
        "A": "审查项目范围以使项目团队保持一致",
        "B": "审查资源管理计划以使项目团队保持一致",
        "C": "审查项目整合计划以使项目团队保持一致",
        "D": "审查工作分解结构(WBS)以使项目团队保持一致",
    },
    11: {
        "A": "立即让SME加入项目，稍后再讨论影响",
        "B": "让现有团队成员与SME协作完成相关工作",
        "C": "让SME独立完成所有必要变更以节省时间",
        "D": "指示团队成员忽略SME的变更建议",
    },
    33: {
        "A": "查阅投标的选定供应商名单并评估可能的供应商变更",
        "B": "修订采购控制流程以避免可能影响进度的意外变更",
        "C": "将情况评估为改进的机会并进行风险分析",
        "D": "对采购流程进行审计并将审计意见告知供应商",
    },
}


def has_options(text: str) -> bool:
    return bool(OPTION_RE.search(text or ""))


def strip_options(text: str) -> str:
    """去掉已有选项，保留纯题干"""
try:
    from pmp_athena.config import ERROR_LOG_PATH, OPTIONS_SUPPLEMENT_PATH, QUESTION_BANK_PATH
except ModuleNotFoundError:
    from config import ERROR_LOG_PATH, OPTIONS_SUPPLEMENT_PATH, QUESTION_BANK_PATH

    m = re.search(r"\s+[A-D][\.、．\)]", text or "")
    if m:
        return text[: m.start()].strip()
    return (text or "").strip()


def build_full_question(stem: str, opts: dict[str, str]) -> str:
    stem = strip_options(stem)
    lines = [stem] + [f"{k}. {opts[k]}" for k in "ABCD" if k in opts]
    return "\n".join(lines)


def pick_best_stem(error: dict, bank_entries: list[dict]) -> str:
    candidates = [error.get("question", "")]
    candidates.extend(b.get("question", "") for b in bank_entries)
    # 优先最长且无选项污染的题干
    stems = [strip_options(c) for c in candidates if c]
    return max(stems, key=len) if stems else ""


def main() -> None:
    errors = json.loads(ERROR_LOG.read_text(encoding="utf-8"))
    bank = json.loads(QUESTION_BANK.read_text(encoding="utf-8"))

    # 合并已有 supplement 文件
    existing = {}
    if OPTIONS_SUPPLEMENT.exists():
        existing = json.loads(OPTIONS_SUPPLEMENT.read_text(encoding="utf-8"))

    merged_supplement = {**existing, **{str(k): v for k, v in SUPPLEMENT.items()}}
    OPTIONS_SUPPLEMENT.write_text(
        json.dumps(merged_supplement, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    updated_errors = 0
    updated_bank = 0

    for eid, opts in SUPPLEMENT.items():
        error = next((e for e in errors if e.get("id") == eid), None)
        if not error:
            print(f"⚠️ error_log 无 #{eid}，跳过")
            continue

        bank_entries = [b for b in bank if b.get("error_log_id") == eid]
        stem = pick_best_stem(error, bank_entries)
        full = build_full_question(stem, opts)

        if error.get("question") != full:
            error["question"] = full
            updated_errors += 1

        for b in bank_entries:
            if b.get("question") != full:
                b["question"] = full
                updated_bank += 1

        status = "补全" if not has_options(error.get("question", "")) else "同步"
        print(f"✅ #{eid} {status}（{len(opts)} 选项）")

    ERROR_LOG.write_text(json.dumps(errors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    QUESTION_BANK.write_text(json.dumps(bank, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 复查
    still_missing = []
    for e in errors:
        bank_q = [b for b in bank if b.get("error_log_id") == e["id"]]
        texts = [e.get("question", "")] + [b.get("question", "") for b in bank_q]
        if not any(has_options(t) for t in texts):
            still_missing.append(e["id"])

    print(f"\n📊 更新 error_log {updated_errors} 条，question_bank {updated_bank} 条")
    if still_missing:
        print(f"⚠️ 仍缺选项: {still_missing}")
    else:
        print("🎉 全部错题均已含选项")


if __name__ == "__main__":
    main()
