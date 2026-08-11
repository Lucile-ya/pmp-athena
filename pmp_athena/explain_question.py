#!/usr/bin/env python3
"""
题目解释引擎 — 对用户询问「为啥选X不选Y」返回针对性解析。

用法:
    python pmp_athena/explain_question.py explain --question "..." --options "..." --target "X" --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 判题框架（精简版）──────────────────────────────────────

TRAP_PATTERNS: dict[str, str] = {
    "T01": "过早行动 — 未分析/未记录就执行",
    "T02": "过早升级 — 第一步找发起人/高管，应先协作沟通",
    "T03": "绕过流程 — 跳过 CCB/CR/Backlog 直接改",
    "T04": "First 选 Best — 问 First 给了终局方案",
    "T05": "绝对化 — always/never/all/must 极端措辞",
    "T06": "角色越权 — SM 定优先级/PM 改章程/替团队决定",
    "T07": "Risk/Issue 混淆 — 已发生写 Risk Register",
    "T08": "过度反应 — 小题大做/全员加班",
    "T09": "反应不足 — 忽视/不记录",
    "T10": "敏捷文档过度 — 敏捷选冗长文档/邮件",
    "T11": "预测型文档不足 — 口头变更无书面 CR",
    "T12": "镀金/范围蔓延 — 主动加功能/接受未批范围",
}

KNOWLEDGE_TIPS: dict[str, str] = {
    "变更": "变更流程：记录 CR → 评估影响 → CCB 审批 → 实施。CCB 批准前不执行。",
    "风险": "风险应对：规避 > 转移 > 减轻 > 接受 > 上报。新风险先登记册，已发生先 Issue Log。",
    "冲突": "冲突解决优先级：合作/解决问题 > 妥协 > 缓和 > 强迫 > 回避。",
    "干系": "新干系人：先会面/沟通了解需求，再更新登记册。先人后工具。",
    "敏捷": "敏捷三角色：PO 定优先级，SM 清障碍，团队自组织。变更走 Backlog 而非 CCB。",
    "质量": "管理质量=QA 过程审计，控制质量=QC 测量结果。根因分析用鱼骨图。",
    "进度": "关键路径上活动延迟 → 总工期延迟。压缩：赶工(加资源) / 快速跟进(并行)。",
    "成本": "CV=EV-AC, SV=EV-PV, CPI=EV/AC, SPI=EV/PV。CPI<1 成本超支。",
}


def explain_question(text: str) -> dict:
    """
    接收题目文本 + 用户选项目标，返回针对性解析。
    输入文本格式示例: "题干... A... B... C... D... 为啥选C不选B"
    """
    result = {"status": "ok", "explanation": "", "target_option": "", "related_traps": []}

    # 提取用户关心的选项
    target_m = re.search(r"(?:为啥|为什么|解释|选\s*)([A-D])(?:\s*不选\s*([A-D]))?", text)
    if target_m:
        result["target_option"] = target_m.group(1)
        rejected = target_m.group(2)

    # 尝试匹配知识领域给提示
    matched_tips = []
    for kw, tip in KNOWLEDGE_TIPS.items():
        if kw in text:
            matched_tips.append(tip)

    # 尝试匹配陷阱
    traps_found = []
    if re.search(r"(?:上报|发起人|sponsor|高层|管理层)", text, re.I):
        traps_found.append("T02")
    if re.search(r"(?:立即|马上|直接|立刻|without|immediately)", text, re.I):
        traps_found.append("T01")
    if re.search(r"(?:CCB|变更|口头|绕过|bypass)", text, re.I):
        traps_found.append("T03")
    if re.search(r"(?:注册|register|已发生|发生.*风险)", text, re.I):
        traps_found.append("T07")
    if re.search(r"(?:SM|PO|产品负责人|Scrum.*Master|定优先级)", text, re.I):
        traps_found.append("T06")

    result["related_traps"] = traps_found

    # 构建解释
    parts = []
    if result["target_option"]:
        letter = result["target_option"]
        # 找对应选项文字
        opt_m = re.search(rf"{letter}[.、．：:]\s*(.+?)(?=\s*[A-D][.、．：:]|\n|$)", text)
        opt_text = opt_m.group(1).strip()[:80] if opt_m else f"选项 {letter}"
        parts.append(f"📝 关于选 {letter}（{opt_text}…）")

    if traps_found:
        parts.append("")
        parts.append("⚠️ 本题可能的陷阱：")
        for tid in traps_found:
            parts.append(f"  • {tid}: {TRAP_PATTERNS.get(tid, tid)}")

    if matched_tips:
        parts.append("")
        parts.append("💡 相关知识要点：")
        for tip in matched_tips[:2]:
            parts.append(f"  • {tip}")

    if not parts:
        parts.append("📝 这道题的关键在于识别题干中的问题类型和项目阶段，")
        parts.append("按照 PMP 推理框架（先分析→先协作→先流程→先根因）逐层判断。")
        parts.append("发送「薄弱点」可查看你在这个领域的整体表现。")

    result["explanation"] = "\n".join(parts)
    return result


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="题目解释引擎")
    parser.add_argument("command", choices=["explain"], default="explain", nargs="?")
    parser.add_argument("--text", "-t", required=True, help="包含题目和用户问题的完整文本")
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    result = explain_question(args.text)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
