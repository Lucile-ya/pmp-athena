#!/usr/bin/env python3
"""App 刷题：自动解析 + 跟答入库辅助。"""

from __future__ import annotations

import re
from typing import Any


def auto_explanation(stem: str, options: dict[str, str], correct: str) -> str:
    """根据题干关键词生成简短解析（硬路由，不依赖 LLM）。"""
    text = f"{stem} {' '.join(options.values())}"
    ca = correct.upper()
    opt = options.get(ca, "")

    if "跨职能" in stem and "需求" in stem:
        return (
            "定义跨职能需求需要不同职能/部门一起对齐，"
            "引导式研讨会(引导/Facilitated Workshops)由引导师主持联合定义需求；"
            "名义小组侧重头脑风暴后排序，不是跨职能定义的首选。"
        )
    if "项目章程" in stem and ("客户" in text or "团队" in text):
        return (
            "项目章程在需求组织与执行组织之间建立伙伴关系；"
            "客户代表需求方，项目团队代表执行方，B 选项符合。"
        )
    if "根本原因" in stem or "根因" in stem:
        return "问题已发生，项目经理应先与团队找根本原因，再决定后续行动。"
    if "WBS" in text.upper() or "工作分解" in stem:
        return "WBS 将可交付成果逐层分解为工作包，是范围基准核心组件。"
    if "变更" in stem and ("CCB" in text.upper() or "变更控制" in text):
        return "变更应先评估影响，再提交 CCB 审批，批准后实施。"

    if opt:
        return f"正确选项 {ca}（{opt}）最符合题干考点，结合关键词排除干扰项。"
    return f"正确选项 {ca} 最符合题干描述的 PMP 考点。"


def memory_tip(stem: str, correct: str) -> str:
    if "跨职能" in stem and "需求" in stem:
        return "跨职能对齐需求 → 引导式研讨会（人要坐在一起谈）"
    if "项目章程" in stem:
        return "章程连需求方与执行方：客户↔项目团队"
    return f"抓住题干关键词，优先选 {correct.upper()}。"


def format_explain_reply(
    *,
    correct: str,
    explanation: str,
    stem: str = "",
    my_answer: str = "",
    error_log_id: int | None = None,
    updated: bool = False,
) -> str:
    lines: list[str] = [f"答案：{correct.upper()}"]
    if my_answer and my_answer.upper() != correct.upper():
        lines[0] = f"❌ 你的 {my_answer.upper()} → ✅ 正确 {correct.upper()}"
    lines.append(f"解析：{explanation[:200]}")
    if stem:
        lines.append(f"记忆口诀：{memory_tip(stem, correct)}")
    if error_log_id:
        tag = "已更新" if updated else "已入库"
        lines.append(f"💾 错题 #{error_log_id} {tag}")
    return "\n".join(lines)


def parse_explain_request(text: str) -> bool:
    t = text.strip()
    return bool(
        re.match(
            r"^(?:给我|帮我)?(?:解析|解释|讲解)(?:一下|下|这题|这道题)?[。.!！?？]*$",
            t,
            re.I,
        )
    )
