#!/usr/bin/env python3
"""
根因变式升级引擎 — 防重复 + 智能降级 + 实战模拟。

升级逻辑:
  1. 检测重复 — 已做对过的变式题不再推送，标记「已攻克」
  2. 题库不足 → 降级为「根因专项总结」
  3. 总结后可触发「根因实战模拟」— 干扰项识别挑战
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import REVIEW_STATE_PATH, ERROR_LOG_PATH
except ModuleNotFoundError:
    from config import REVIEW_STATE_PATH, ERROR_LOG_PATH

VARIANT_STATE_PATH = REVIEW_STATE_PATH  # 复用 review state 存 variant 状态


def _load_review_state() -> dict:
    try:
        return json.loads(REVIEW_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_review_state(data: dict) -> None:
    REVIEW_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_error_log() -> list:
    try:
        data = json.loads(ERROR_LOG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ── 根因专项总结池 ──────────────────────────────────────────────────

ROOT_CAUSE_SUMMARIES: dict[str, dict] = {
    "混淆风险与问题": {
        "title": "混淆风险与问题",
        "core_distinction": "已发生 → 问题日志；未发生 → 风险登记册",
        "judgment_flow": "问自己「这件事发生了吗？」→ 是 → 问题；否 → 风险",
        "common_traps": [
            "看到「可能」「预计」「如果」→ 选风险",
            "看到「已」「确定」「当前」「现在」→ 选问题",
            "「风险已发生」= 问题！记 Issue Log，不是 Risk Register",
        ],
        "exam_trigger_words": {
            "风险": ["可能", "预计", "如果", "潜在", "不确定"],
            "问题": ["已发生", "当前", "现在", "已经", "确定"],
        },
    },
    "已发生当成未发生": {
        "title": "已发生当成未发生",
        "core_distinction": "题干写「当前/已经/现在」= 问题；题干写「未来/可能/预计」= 风险",
        "judgment_flow": "看出题时态 → 现在时 → 问题日志 → 纠正措施；将来时 → 风险登记册 → 应对规划",
        "common_traps": [
            "题干出现「风险」二字但描述已发生 → 仍是问题",
            "不要因为选项有「风险登记册」就选，先判题干时态",
        ],
        "exam_trigger_words": {
            "风险语境": ["风险", "威胁", "机会"],
            "问题语境": ["已发生", "延误", "缺陷", "错误", "投诉"],
        },
    },
    "新干系人先沟通再工具": {
        "title": "新干系人先沟通再工具",
        "core_distinction": "PMI 铁律：先人后工具。先会面沟通了解需求 → 再更新登记册/PMIS",
        "judgment_flow": "出现新干系人 → 1. 约见面/沟通 → 2. 了解期望和影响 → 3. 更新登记册 → 4. 调整参与策略",
        "common_traps": [
            "「更新干系人登记册」看起来专业，但不是第一步",
            "「发邮件通知」「上传 PMIS」是工具选项，不是首选",
            "新干系人 ≠ 自动触发变更请求",
        ],
        "exam_trigger_words": {
            "首选": ["会面", "沟通", "了解", "讨论", "会议"],
            "陷阱": ["更新登记册", "PMIS", "邮件", "通知", "文档"],
        },
    },
    "变更未评估就执行": {
        "title": "变更未评估就执行",
        "core_distinction": "变更流程：评估影响 → 提交 CCB → 批准后才实施。跳步骤 = 必错",
        "judgment_flow": "变更请求出现 → 1. 先评估对范围/进度/成本/质量的影响 → 2. 提交 CCB → 3. 批准 → 4. 更新计划 → 5. 实施",
        "common_traps": [
            "「先做再补审批」是实战常态但 PMP 不允许",
            "CCB 审批前不能开始实施，连准备都不行",
            "项目经理可以审批不涉及基准的变更，但不能批涉及基准的",
        ],
        "exam_trigger_words": {
            "正确路径": ["评估影响", "提交变更", "CCB", "批准后"],
            "陷阱": ["立即实施", "直接修改", "口头确认", "先改再说"],
        },
    },
    "敏捷进度失真的根因是文化": {
        "title": "敏捷进度失真 — 根因是文化",
        "core_distinction": "燃尽图好看但实际延期 → 不是工具问题，是心理安全感/透明文化缺失",
        "judgment_flow": "进度失真 → 先问「团队敢说真话吗」→ 否 → 建设透明文化/Coaching → 是 → 再看工具/流程",
        "common_traps": [
            "「升级报告工具」「改燃尽图配置」是标准干扰项",
            "正确答案往往是『培训+持续辅导(Coaching)』",
            "不要选「做一次培训」，要选「持续」的",
        ],
        "exam_trigger_words": {
            "根因": ["心理安全", "透明", "信任", "文化"],
            "陷阱": ["升级工具", "报告系统", "燃尽图配置"],
        },
    },
    "合同类型选择错误": {
        "title": "合同类型选择错误",
        "core_distinction": "FFP = 卖方扛风险（买方最安全）；成本补偿 = 买方扛风险；工料 = 双方共担",
        "judgment_flow": "题干条件判断 → 范围明确 → FFP；范围不确定 → 成本补偿或工料；需灵活 → 工料",
        "common_traps": [
            "FFP 对买方最安全，但不是所有场景都适用（需要范围明确）",
            "成本补偿只保护卖方，买方承担所有超支",
            "工料合同是「范围不明确」时的选择，不是「双方都满意」",
        ],
        "exam_trigger_words": {
            "FFP": ["范围明确", "买方风险低", "固定价格"],
            "成本补偿": ["范围不确定", "卖方成本", "实报实销"],
            "工料": ["灵活", "按工时", "双方共担"],
        },
    },
    "冲突解决策略选错": {
        "title": "冲突解决策略选错",
        "core_distinction": "合作/解决问题（双赢）第一优先，强迫（Win-Lose）是最后手段",
        "judgment_flow": "团队冲突 → 先判断有没有「紧急/安全」前提 → 有 → 可强迫；没有 → 合作/妥协优先",
        "common_traps": [
            "「回避」看似不惹事，但在 PMP 里是最低优先级",
            "「妥协」看起来公平，但不如「合作」彻底解决问题",
            "题干问「最佳」= 合作；问「最快」= 可考虑强迫",
        ],
        "exam_trigger_words": {
            "首选": ["合作", "解决问题", "双赢", "面对"],
            "末选": ["强迫", "命令", "强制"],
            "中间": ["妥协", "缓和", "回避"],
        },
    },
    "应急储备与管理储备混淆": {
        "title": "应急储备 vs 管理储备",
        "core_distinction": "应急储备 = 已知风险，PM 可用，在基准内；管理储备 = 未知风险，需管理层批准，不在基准内",
        "judgment_flow": "风险是否已识别 → 是 → 应急储备（PM 自行）→ 否 → 管理储备（需变更基准）",
        "common_traps": [
            "「储备分析」是监控过程组的工具，不是规划时才用",
            "管理储备使用后，成本基准要更新",
        ],
        "exam_trigger_words": {
            "应急": ["已知", "已识别", "PM", "基准内"],
            "管理": ["未知", "未识别", "管理层", "变更基准"],
        },
    },
    "估算方法选择不当": {
        "title": "估算方法选择不当",
        "core_distinction": "没数据 → 自下而上（最稳）；有历史 → 类比（最快）；有公式 → 参数（最准）",
        "judgment_flow": "先判断有没有历史数据 → 没有 → 自下而上；有 → 再看有没有公式/参数 → 有 → 参数；没有 → 类比",
        "common_traps": [
            "「没有任何数据」不能选类比或参数",
            "三点估算是 PERT 公式，不是独立的估算方法",
        ],
        "exam_trigger_words": {
            "自下而上": ["没有数据", "新项目", "无历史"],
            "类比": ["类似项目", "历史", "快速"],
            "参数": ["公式", "模型", "统计"],
        },
    },
    "干系人管理策略选错": {
        "title": "干系人管理策略 — 权力利益方格",
        "core_distinction": "高权高利 → 密切管理；高权低利 → 令其满意；低权高利 → 随时告知；低权低利 → 监督",
        "judgment_flow": "先判定干系人的权力级别和利益级别 → 放到 2×2 方格 → 选对应策略",
        "common_traps": [
            "不要把「高利益低权力」的干系人忽略掉",
            "「令其满意」只关注高权力低利益，不是高利益",
        ],
        "exam_trigger_words": {
            "密切管理": ["高权力", "高利益", "关键", "核心"],
            "令其满意": ["高权力", "低利益", "审批"],
            "随时告知": ["低权力", "高利益", "受影响"],
            "监督": ["低权力", "低利益", "外围"],
        },
    },
    "质量审计 vs 控制质量": {
        "title": "质量审计 vs 控制质量",
        "core_distinction": "QA/管理质量 → 关注过程是否合规（审计）；QC/控制质量 → 关注可交付物是否达标（测量）",
        "judgment_flow": "问「过程对不对」→ QA/审计；问「结果好不好」→ QC/测量",
        "common_traps": [
            "「审计」≠ 财务审计，是查过程/流程是否合规",
            "确认范围（Validate Scope）≠ 控制质量（QC），前者是和客户一起验收",
        ],
        "exam_trigger_words": {
            "QA": ["过程", "审计", "合规", "流程", "改进"],
            "QC": ["可交付成果", "检查", "测量", "测试", "缺陷"],
        },
    },
    "敏捷中替团队做决定": {
        "title": "敏捷中替团队做决定",
        "core_distinction": "PO 定优先级，SM 清障碍，团队自组织做决策。PM 不替团队分任务。",
        "judgment_flow": "敏捷题 → 看「谁该做这个决定」→ PO 管 Backlog 顺序，SM 管流程障碍，团队自定怎么做",
        "common_traps": [
            "「项目经理分配任务」在敏捷场景永远是错的",
            "SM 不是团队的老板，是教练/服务者",
        ],
        "exam_trigger_words": {
            "PO": ["优先级", "Backlog", "价值排序", "需求"],
            "SM": ["障碍", "流程", "教练", "站会"],
            "团队": ["自组织", "估算", "怎么做", "技术方案"],
        },
    },
}


# ── 变式打分（本地副本，避免循环导入）──────────────────────────────

def _score_variant_by_rc(variant_question: str, root_cause_name: str) -> float:
    """按根因关键词匹配度给变式题打分。"""
    if not root_cause_name:
        return 0.0
    import re as _re
    cause_keywords = set(_re.findall(r"[一-鿿]{2,}", root_cause_name))
    q_words = set(_re.findall(r"[一-鿿]{2,}", variant_question))
    if not cause_keywords:
        return 0.5
    overlap = len(cause_keywords & q_words)
    return min(1.0, 0.5 + overlap * 0.25)


# ── 已攻克检测 ──────────────────────────────────────────────────

def _get_mastered_variants(error_id: int) -> list[int]:
    """获取某错题的已攻克变式题 ID 列表。"""
    state = _load_review_state()
    card = state.get(str(error_id), {})
    return card.get("mastered_variant_ids", [])


def _get_conquered_root_causes(error_id: int) -> list[str]:
    """获取某错题的已攻克根因列表。"""
    state = _load_review_state()
    card = state.get(str(error_id), {})
    return card.get("conquered_root_causes", [])


def mark_variant_mastered(error_id: int, variant_id: int) -> bool:
    """标记某道变式题为已攻克。"""
    state = _load_review_state()
    key = str(error_id)
    card = state.setdefault(key, {})
    mastered = card.setdefault("mastered_variant_ids", [])
    if variant_id not in mastered:
        mastered.append(variant_id)
    card["mastered_variant_ids"] = mastered
    _save_review_state(state)
    return True


def mark_root_cause_conquered(error_id: int, root_cause_name: str) -> bool:
    """标记某根因为已攻克。"""
    state = _load_review_state()
    key = str(error_id)
    card = state.setdefault(key, {})
    conquered = card.setdefault("conquered_root_causes", [])
    if root_cause_name not in conquered:
        conquered.append(root_cause_name)
    card["conquered_root_causes"] = conquered
    _save_review_state(state)
    return True


# ── 根因专项总结 ──────────────────────────────────────────────────

def get_root_cause_summary(root_cause_name: str) -> dict | None:
    """获取根因专项总结内容。"""
    for key, summary in ROOT_CAUSE_SUMMARIES.items():
        if key in root_cause_name or root_cause_name in key:
            return summary
    return None


def format_root_cause_summary(root_cause_name: str) -> str:
    """格式化根因专项总结（微信推送用）。"""
    s = get_root_cause_summary(root_cause_name)
    if not s:
        return ""

    lines = [
        f"📖 根因专项总结：[{s['title']}]",
        "",
        f"📌 核心区别：{s['core_distinction']}",
        f"📌 判断流程：{s['judgment_flow']}",
        "",
        "📌 高频陷阱：",
    ]
    for t in s["common_traps"]:
        lines.append(f"  · {t}")

    if "exam_trigger_words" in s:
        lines.append("")
        for category, words in s["exam_trigger_words"].items():
            lines.append(f"  🔑 {category}：{' / '.join(words)}")

    lines.extend([
        "",
        "💬 回复「已掌握」标记该根因已攻克",
        "💬 回复「模拟」进入根因实战模拟",
    ])
    return "\n".join(lines)


# ── 根因实战模拟 ──────────────────────────────────────────────────

COMBAT_SIMULATIONS: dict[str, dict] = {
    "混淆风险与问题": {
        "scenario": "项目正在进行中，项目经理发现某关键供应商的交付有延迟迹象。供应商表示「如果原材料价格继续上涨，交货期可能延长2周」。",
        "options": [
            "A. 更新风险登记册，评估影响并规划应对",
            "B. 记录问题日志，通知相关方并制定纠正措施",
            "C. 立即更换供应商以避免延迟",
            "D. 上报发起人请求额外预算",
        ],
        "correct": "A",
        "risk_trap": "B",
        "issue_trap": "——",
        "explanation": "「如果……可能」说明风险尚未发生 → 应记入风险登记册(A)。干扰项 B 是「已发生问题」的处理方式 — 这是考试中最常见的陷阱：把可能发生的当成了已发生的。",
    },
    "已发生当成未发生": {
        "scenario": "项目启动后发现，开发团队的一名关键成员已经连续两周无法完成分配的任务，导致 Sprint 目标无法达成。",
        "options": [
            "A. 更新风险登记册，分析该成员能力不足的风险概率",
            "B. 记录问题日志，与成员面谈了解原因并制定支持计划",
            "C. 调整 Product Backlog，降低本 Sprint 的交付目标",
            "D. 提交变更请求，申请延长项目工期",
        ],
        "correct": "B",
        "risk_trap": "A",
        "issue_trap": "——",
        "explanation": "「已经连续两周无法完成」= 已发生 → 这是问题，不是风险。应记录问题日志并采取纠正(B)。A 将已发生的问题当成风险来管，是考试高频陷阱。",
    },
    "新干系人先沟通再工具": {
        "scenario": "项目执行到一半，一位从未参与过的部门总监突然提出：「我对项目的技术方案有担忧，你们为什么没找我确认？」",
        "options": [
            "A. 更新干系人登记册，将这位总监加入并评估其权力/利益级别",
            "B. 安排与总监的会面，了解其具体的担忧和期望",
            "C. 在 PMIS 上创建项目门户页面，让总监可以自行查看项目进展",
            "D. 提交变更请求，因为需要调整干系人参与计划",
        ],
        "correct": "B",
        "risk_trap": "A",
        "issue_trap": "——",
        "explanation": "新干系人出现 → PMI 第一反应永远是见面/沟通(B)。A「更新登记册」是正确的后续步骤但不是第一步。C 是工具思维。这是「先人后工具」的经典场景。",
    },
    "变更未评估就执行": {
        "scenario": "客户在 Sprint Review 中提出：「这个功能必须加上才符合我的业务流程。」产品负责人认为这确实有价值。项目经理应该首先做什么？",
        "options": [
            "A. 同意加入下个 Sprint，因为客户需求和 PO 判断一致",
            "B. 拒绝变更，因为 Sprint 已在进行中不可打断",
            "C. 评估变更对范围、进度和成本的影响",
            "D. 提交变更请求到 CCB 审批",
        ],
        "correct": "C",
        "risk_trap": "D",
        "issue_trap": "——",
        "explanation": "变更请求出现 → 第一步永远是评估影响(C)，不是直接提交 CCB(D)。PO 同意不代表可以跳过评估。A 是敏捷中常见陷阱（未经评估直接接受）。",
    },
}


def get_combat_simulation(root_cause_name: str | None) -> dict | None:
    """获取根因实战模拟题。"""
    if not root_cause_name:
        return None
    for key, sim in COMBAT_SIMULATIONS.items():
        if key in root_cause_name or root_cause_name in key:
            return sim
    return None


def format_combat_simulation(root_cause_name: str | None) -> str | None:
    """格式化根因实战模拟题。"""
    sim = get_combat_simulation(root_cause_name)
    if not sim:
        return None

    lines = [
        "⚔️ 根因实战模拟",
        "══════════════════",
        "",
        f"📝 {sim['scenario']}",
        "",
    ]
    for opt in sim["options"]:
        lines.append(f"  {opt}")

    lines.extend([
        "",
        "请回复格式：",
        "  陷阱=<选项字母>",
        "  区分=<你的判断依据>",
        "",
        "💡 例如：「陷阱=B 区分=题干写的是可能发生不是已发生」",
    ])
    return "\n".join(lines)


def grade_combat_simulation(
    root_cause_name: str | None,
    trap_answer: str,
    distinction_text: str,
) -> dict:
    """判卷根因实战模拟。"""
    sim = get_combat_simulation(root_cause_name)
    if not sim:
        return {"status": "error", "text": "⚠️ 未找到匹配的实战模拟题"}

    correct_trap = sim.get("risk_trap", sim.get("correct", ""))
    trap_correct = trap_answer.strip().upper() == correct_trap.strip().upper()

    lines = []
    if trap_correct:
        lines.append("✅ 陷阱识别正确！")
    else:
        lines.append(f"❌ 正确陷阱是 {correct_trap}（你指了 {trap_answer.upper()}）")
        lines.append(f"💡 {sim['explanation']}")

    # 对区分描述做宽松判断（含关键词即可）
    keywords = re.findall(r"[一-鿿]{2,}", sim.get("explanation", ""))
    hit_count = sum(1 for kw in keywords if kw in distinction_text)
    if hit_count >= 2 or len(distinction_text) >= 10:
        lines.append("✅ 区分思路合理！")
    else:
        lines.append("💡 建议更详细描述判断依据，巩固记忆。")

    lines.extend([
        "",
        f"📖 解析：{sim['explanation']}",
    ])

    if trap_correct:
        lines.append("🏆 该根因已攻克！")
        lines.append("💬 回复「继续」进入下一题")

    return {
        "status": "combat_graded",
        "correct": trap_correct,
        "conquered": trap_correct,
        "trap_answer": trap_answer.upper(),
        "explanation": sim["explanation"],
        "text": "\n".join(lines),
    }


# ── 升级版变式启动 ──────────────────────────────────────────────────

def review_variant_start_v2(error_id: int) -> dict:
    """
    升级版变式启动：
    1. 去重已攻克的变式题
    2. 剩余不足 2 道 → 降级为根因专项总结
    3. 否则推送全新变式
    """
    errors = _load_error_log()
    error = next((e for e in errors if e.get("id") == error_id), None)
    if error is None:
        return {"status": "error", "text": f"⚠️ 错题 #{error_id} 不存在"}

    # 根因诊断
    root_cause_name = ""
    try:
        from pmp_athena.root_cause_engine import diagnose
    except ImportError:
        from root_cause_engine import diagnose
    diag = diagnose(error)
    if diag:
        root_cause_name = diag.get("name", "")

    area = error.get("knowledge_area", "")
    if not area and not root_cause_name:
        return {"status": "insufficient", "text": "⚠️ 该题无知识领域标记。"}

    # 已攻克检测
    mastered_ids = _get_mastered_variants(error_id)

    try:
        from pmp_athena.question_bank import QuestionBank
    except ImportError:
        from question_bank import QuestionBank

    qb = QuestionBank()
    candidates = qb.list_by_area_excluding(area, error_id, limit=30) if area else []
    if not candidates:
        candidates = qb.list_recent_excluding(error_id, limit=30)

    # 按根因排序 + 去重已攻克
    if root_cause_name and candidates:
        scored = [
            (c, _score_variant_by_rc(
                str(c.get("question", "")), root_cause_name,
            ))
            for c in candidates
        ]
        scored.sort(key=lambda x: -x[1])
        candidates = [c for c, _ in scored]

    # 过滤已攻克的
    fresh = [c for c in candidates if c.get("id") not in mastered_ids]

    if len(fresh) < 2:
        # ── 降级：根因专项总结 ──
        summary_text = format_root_cause_summary(root_cause_name)
        if summary_text:
            return {
                "status": "root_cause_summary",
                "error_id": error_id,
                "root_cause": root_cause_name,
                "text": summary_text,
            }

        return {
            "status": "insufficient",
            "text": f"⚠️ 该领域({area or root_cause_name})变式题不足，且无匹配总结模板。",
            "variant_count": len(fresh),
        }

    variants = fresh[:3]
    var_ids = [v.get("id") for v in variants]
    first = variants[0]

    source_note = f"（根因：「{root_cause_name}」）" if root_cause_name else ""

    lines = [
        f"💡 根因变式巩固（第 1/{len(var_ids)} 题）{source_note}",
        f"[{first.get('knowledge_area', area)}] {first.get('question', '').strip()}",
        "",
        "请回复 A/B/C/D 作答。",
    ]

    return {
        "status": "variant_question",
        "error_id": error_id,
        "variant_ids": var_ids,
        "variant_index": 0,
        "variant_total": len(var_ids),
        "variant_correct": 0,
        "root_cause": root_cause_name,
        "text": "\n".join(lines),
    }


def grade_variant_answer_v2(
    error_id: int,
    variant_index: int,
    user_answer: str,
    variant_ids: list[int],
    variant_correct: int,
    root_cause_name: str = "",
) -> dict:
    """
    升级版判卷：
    - 答对 → 标记该题已攻克
    - 全部完成 → 通关判定 + 未通关时可选根因总结
    """
    import sys
    from pathlib import Path
    _pkg = Path(__file__).resolve().parent
    if str(_pkg) not in sys.path:
        sys.path.insert(0, str(_pkg))

    try:
        from pmp_athena.question_bank import QuestionBank
        from pmp_athena.spaced_repetition import SpacedRepetition
        from pmp_athena.error_insights import is_high_frequency_marked, unmark_high_frequency
    except ImportError:
        from question_bank import QuestionBank
        from spaced_repetition import SpacedRepetition
        from error_insights import is_high_frequency_marked, unmark_high_frequency

    qb = QuestionBank()
    sr = SpacedRepetition()

    if variant_index >= len(variant_ids):
        return {"status": "error", "text": "⚠️ 变式题序号超出范围"}

    current_variant_id = variant_ids[variant_index]
    variant_record = qb.get_by_id(current_variant_id)

    if not variant_record:
        return {"status": "error", "text": f"⚠️ 变式题 #{current_variant_id} 未找到"}

    correct_ans = str(variant_record.get("correct_answer", "")).strip().upper()
    my_ans = user_answer.strip().upper()
    is_correct = my_ans == correct_ans
    new_correct = variant_correct + (1 if is_correct else 0)

    if is_correct:
        mark_variant_mastered(error_id, current_variant_id)
        feedback = "✅ 正确！已标记为已攻克。"
    else:
        expl = str(variant_record.get("explanation", ""))[:200]
        feedback = (
            f"❌ 正确答案是 {correct_ans}（你选了 {my_ans}）\n"
            f"💡 {expl}"
        )

    next_index = variant_index + 1

    if next_index >= len(variant_ids):
        passed = new_correct >= 2
        total = len(variant_ids)
        lines = [feedback]
        lines.append(f"\n📊 变式巩固完成：正确 {new_correct}/{total}")

        if passed:
            lines.append("✅ 变式通过！")
            state = sr._read_state()
            card = state.get(str(error_id), {})
            consec = card.get("consecutive_correct", 0)
            if consec >= 2 and is_high_frequency_marked(error_id):
                unmark_high_frequency(error_id)
                sr.update_high_frequency_status(error_id, False)
                lines.append("🏆 连续 2 次正确 + 变式通过，已取消高频错题标记！")
        else:
            lines.append("⚠️ 变式未达标（需 ≥2/3 正确），保留高频标记。")
            # 降级提示
            if root_cause_name and get_root_cause_summary(root_cause_name):
                lines.append(f"💡 回复「总结」获取「{root_cause_name}」专项总结")
                lines.append(f"💡 回复「模拟」进入根因实战模拟")

        nxt = _study_advisor_review_next()
        if nxt["status"] == "question":
            lines.append("")
            lines.append(nxt["text"])
        else:
            lines.append("")
            lines.append(nxt["text"])

        return {
            "status": "variant_done",
            "correct": is_correct,
            "variant_correct": new_correct,
            "variant_total": total,
            "passed": passed,
            "next_error_id": nxt.get("error_id"),
            "done": nxt["status"] in ("done", "empty"),
            "text": "\n".join(lines),
        }

    # 下一道变式
    next_variant = qb.get_by_id(variant_ids[next_index])
    if next_variant:
        lines = [feedback]
        lines.append(f"\n💡 根因变式巩固（第 {next_index + 1}/{len(variant_ids)} 题）")
        lines.append(f"[{next_variant.get('knowledge_area', '综合')}] {next_variant.get('question', '').strip()}")
        lines.append("\n请回复 A/B/C/D 作答。")
    else:
        lines = [feedback, "⚠️ 下一道变式题未找到"]

    return {
        "status": "variant_question",
        "correct": is_correct,
        "variant_ids": variant_ids,
        "variant_index": next_index,
        "variant_correct": new_correct,
        "variant_total": len(variant_ids),
        "text": "\n".join(lines),
    }


def _study_advisor_review_next():
    """桥接 study_advisor.review_next，通过函数引用避免循环导入。"""
    from pmp_athena.study_advisor import review_next as rn
    return rn(include_header=False)


def handle_variant_command(error_id: int, command: str, root_cause_name: str = "") -> dict:
    """统一处理变式相关指令：「总结」「模拟」「已掌握」等。"""
    cmd = command.strip()

    if cmd == "总结":
        text = format_root_cause_summary(root_cause_name)
        if text:
            mark_root_cause_conquered(error_id, root_cause_name)
            text += f"\n\n✅ 已标记根因「{root_cause_name}」为已掌握。"
            return {"status": "summary_shown", "text": text}
        return {"status": "error", "text": "⚠️ 未找到匹配的根因总结。"}

    if cmd == "模拟":
        text = format_combat_simulation(root_cause_name)
        if text:
            return {"status": "combat_question", "root_cause": root_cause_name, "text": text}
        return {"status": "error", "text": "⚠️ 未找到该根因的实战模拟题。"}

    if cmd == "已掌握":
        mark_root_cause_conquered(error_id, root_cause_name)
        nxt = _study_advisor_review_next()
        text = f"✅ 已标记根因「{root_cause_name or '当前'}」为已掌握。\n\n{nxt['text']}"
        return {"status": "graded", "text": text}

    # 可能是模拟题的判卷回复（陷阱=<字母> 区分=<文字>）
    trap_match = re.match(r"陷阱\s*=\s*([A-Da-d])\s+区分\s*=\s*(.+)", cmd, re.DOTALL)
    if trap_match:
        trap_letter = trap_match.group(1)
        distinction = trap_match.group(2).strip()
        return grade_combat_simulation(root_cause_name, trap_letter, distinction)

    return {"status": "unrecognized", "text": "⚠️ 请回复「总结」「模拟」「已掌握」或陷阱识别答案。"}


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="根因变式升级引擎")
    sub = parser.add_subparsers(dest="cmd")

    p_start = sub.add_parser("variant-start", help="启动升级版变式")
    p_start.add_argument("error_id", type=int)
    p_start.add_argument("--json", action="store_true")

    p_grade = sub.add_parser("variant-grade", help="升级版判卷")
    p_grade.add_argument("error_id", type=int)
    p_grade.add_argument("variant_index", type=int)
    p_grade.add_argument("answer")
    p_grade.add_argument("variant_ids_json")
    p_grade.add_argument("variant_correct", type=int)
    p_grade.add_argument("--root-cause", default="")
    p_grade.add_argument("--json", action="store_true")

    p_cmd = sub.add_parser("command", help="变式指令处理")
    p_cmd.add_argument("error_id", type=int)
    p_cmd.add_argument("command_text")
    p_cmd.add_argument("--root-cause", default="")
    p_cmd.add_argument("--json", action="store_true")

    p_mastered = sub.add_parser("mark-mastered", help="标记变式题已攻克")
    p_mastered.add_argument("error_id", type=int)
    p_mastered.add_argument("variant_id", type=int)

    p_conquer = sub.add_parser("conquer-root-cause", help="标记根因已攻克")
    p_conquer.add_argument("error_id", type=int)
    p_conquer.add_argument("root_cause")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    if args.cmd == "variant-start":
        result = review_variant_start_v2(args.error_id)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(result["text"])

    elif args.cmd == "variant-grade":
        variant_ids = json.loads(args.variant_ids_json)
        result = grade_variant_answer_v2(
            args.error_id, args.variant_index, args.answer,
            variant_ids, args.variant_correct, args.root_cause,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(result["text"])

    elif args.cmd == "command":
        result = handle_variant_command(args.error_id, args.command_text, args.root_cause)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(result["text"])

    elif args.cmd == "mark-mastered":
        ok = mark_variant_mastered(args.error_id, args.variant_id)
        print(f"✅ 变式题 #{args.variant_id} 已标记为已攻克" if ok else "❌ 失败")

    elif args.cmd == "conquer-root-cause":
        ok = mark_root_cause_conquered(args.error_id, args.root_cause)
        print(f"✅ 根因「{args.root_cause}」已标记为已攻克" if ok else "❌ 失败")


if __name__ == "__main__":
    main()
