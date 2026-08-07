#!/usr/bin/env python3
"""
语义记忆锚点 — 按根因类型生成专属锚点话术。

激活原理：
  - 每道高频错题的「根因」→ 一句话锚点话术
  - 每次复习推送：先显示锚点 → 再出题 → 判卷后回顾锚点
  - 格式：🔑 "发生了吗？发生了就是问题，没发生就是风险。"

锚点话术池：覆盖 root_cause_engine.py 定义的 12 种根因类型。
"""

from __future__ import annotations

import re
from typing import Any

try:
    from pmp_athena.root_cause_engine import diagnose, get_wrong_history
except ModuleNotFoundError:
    from root_cause_engine import diagnose, get_wrong_history


# ── 锚点话术池（按根因类型索引）─────────────────────────────────────

ANCHOR_POOL: dict[str, dict[str, str]] = {
    "混淆风险与问题": {
        "anchor": "发生了就是问题，没发生就是风险。问题记日志，风险入登记册。",
        "cue": "题干描述是「已经发生的」还是「可能发生的」？",
    },
    "已发生当成未发生": {
        "anchor": "已发生 = 问题日志 + 解决，未发生 = 风险登记册 + 预防。",
        "cue": "题目写的是「当前」「已经」「现在」还是「未来」「可能」「如果」？",
    },
    "混淆质量审计与控制质量": {
        "anchor": "QA 管过程合不合规，QC 查交付物达不达标。审计看过程，控制看结果。",
        "cue": "这道题在问「过程对不对」还是「结果好不好」？",
    },
    "新干系人先沟通再工具": {
        "anchor": "新方进场先开口，会面沟通第一手。登记册更新排在后面，工具是手段不是第一步。",
        "cue": "出现新干系人 → PMP 第一反应永远是和 Ta 见面/沟通。",
    },
    "变更未评估就执行": {
        "anchor": "变更先评估，CCB 批了再动刀。未批不变更，变更必留痕。",
        "cue": "出现变更请求 → 先评估影响，不要先执行！",
    },
    "敏捷进度失真的根因是文化": {
        "anchor": "进度失真不是工具的问题，是信任和透明文化的缺失。先育人再改工具。",
        "cue": "燃尽图/站会失真 → 根因是「缺乏心理安全感/透明文化」。",
    },
    "合同类型选择错误": {
        "anchor": "FFP 卖方扛风险（买方最安全），成本补偿买方买单，工料双方一起担。",
        "cue": "题目场景：范围明确 → FFP；范围不确定 → 成本补偿/工料。",
    },
    "冲突解决策略选错": {
        "anchor": "合作/解决问题（双赢）第一，强迫（Win-Lose）是最后手段。",
        "cue": "遇到团队冲突 → PMP 第一反应：面对面合作解决，不是上报或回避。",
    },
    "应急储备与管理储备混淆": {
        "anchor": "应急储备（已知风险，PM 可用，在基准内）≠ 管理储备（未知风险，需变更基准）。",
        "cue": "储备题 → 先判断题干风险是「已知」还是「未知」。",
    },
    "估算方法选择不当": {
        "anchor": "没数据用自下而上（最稳），有历史用类比（最快），有公式用参数（最准）。",
        "cue": "估算题 → 先看条件：有没有历史数据？有没有公式？",
    },
    "干系人管理策略选错": {
        "anchor": "高权高利密切管，高权低利令其满。低权高利随时告，低权低利监督就行。",
        "cue": "干系人管理 → 在权力-利益方格上定好象限再选策略。",
    },
    "敏捷中替团队做决定": {
        "anchor": "PO 定优先级，SM 清障碍，团队自组织做决策。敏捷不越权。",
        "cue": "敏捷题 → 谁做决定？一定是团队（自组织原则），不是 PM。",
    },
}

# 降级锚点：根因未匹配时的通用兜底
_FALLBACK_ANCHOR = {
    "anchor": "先分析再行动，先协作再升级，先走流程再变更。",
    "cue": "不确定时回头对照 P1-P6 优先级原则。",
}


def get_anchor_for_root_cause(root_cause_name: str) -> dict[str, str]:
    """根据根因名称获取锚点话术。"""
    for key, anchor_data in ANCHOR_POOL.items():
        if key in root_cause_name or root_cause_name in key:
            return anchor_data
    return _FALLBACK_ANCHOR


def get_anchor_for_error(error: dict, wrong_records: list[dict] | None = None) -> dict[str, str]:
    """为一道错题生成锚点话术（自动诊断根因）。"""
    diag = diagnose(error, wrong_records)
    if diag:
        return get_anchor_for_root_cause(diag.get("name", ""))
    return _FALLBACK_ANCHOR


def format_anchor_card(error: dict, wrong_records: list[dict] | None = None) -> str:
    """格式化锚点卡片 — 复习时优先显示。"""
    anchor = get_anchor_for_error(error, wrong_records)
    return f"🔑 {anchor['anchor']}"


def format_cue_line(error: dict, wrong_records: list[dict] | None = None) -> str:
    """格式化视觉线索行 — 帮助用户快速识别题型模式。"""
    anchor = get_anchor_for_error(error, wrong_records)
    return f"👁️ {anchor['cue']}"


def format_anchor_with_cue(error: dict, wrong_records: list[dict] | None = None) -> str:
    """锚点 + 线索 组合输出。"""
    anchor = get_anchor_for_error(error, wrong_records)
    return f"🔑 {anchor['anchor']}\n👁️ {anchor['cue']}"


def list_all_root_causes() -> list[str]:
    """列出所有已注册根因类型。"""
    return list(ANCHOR_POOL.keys())


# ── CLI ───────────────────────────────────────────────────────────────


def main():
    import argparse
    import json
    import sys
    from pathlib import Path

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="语义记忆锚点")
    sub = parser.add_subparsers(dest="command")

    p_anchor = sub.add_parser("anchor", help="获取错题的锚点话术")
    p_anchor.add_argument("error_id", type=int)
    p_anchor.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="列出所有根因类型")
    p_list.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "list":
        causes = list_all_root_causes()
        if args.json:
            print(json.dumps(causes, ensure_ascii=False))
        else:
            for c in causes:
                a = ANCHOR_POOL.get(c, {})
                print(f"  {c}: 🔑 {a.get('anchor', 'N/A')}")
        return

    if args.command == "anchor":
        EL_PATH = Path("D:/pmp-athena/pmp_notes/error_log.json")
        errors = json.loads(EL_PATH.read_text(encoding="utf-8")) if EL_PATH.exists() else []
        if not isinstance(errors, list):
            errors = []
        err = next((e for e in errors if e.get("id") == args.error_id), None)
        if not err:
            print(json.dumps({"error": f"错题 #{args.error_id} 不存在"}, ensure_ascii=False))
            return

        text = format_anchor_with_cue(err)
        if args.json:
            print(json.dumps({"text": text}, ensure_ascii=False))
        else:
            print(text)


if __name__ == "__main__":
    main()
