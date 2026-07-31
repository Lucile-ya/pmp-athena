#!/usr/bin/env python3
"""
考前深度分析 — 战况评估、高风险清单、冲刺计划、根因防错卡。

触发词：考前分析 / 根因分析 / 最后X天怎么安排

用法:
    python pmp_athena/pre_exam_analysis.py analyze
    python pmp_athena/pre_exam_analysis.py message --text "考前分析"
    python pmp_athena/pre_exam_analysis.py root-cause
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import NOTES_DIR, PROJECT_ROOT
    from pmp_athena.prep_analytics import find_knowledge_resources
    from pmp_athena.practice_summary import _accuracy, _area_stats, _bar, _load_exam_records
    from pmp_athena.question_bank import QuestionBank
except ModuleNotFoundError:
    from config import NOTES_DIR, PROJECT_ROOT
    from prep_analytics import find_knowledge_resources
    from practice_summary import _accuracy, _area_stats, _bar, _load_exam_records
    from question_bank import QuestionBank

ERROR_LOG_PATH = NOTES_DIR / "error_log.json"
REVIEW_STATE_PATH = NOTES_DIR / "error_review_state.json"
CONFIG_PATH = NOTES_DIR / "config.json"

EXAM_DATE = date(2026, 9, 12)
PASS_RATE = 59.0
TARGET_RATE = 70.0
MOCK_EVAL_RATE = 65.0

ALL_AREAS = [
    "整合管理", "范围管理", "进度管理", "成本管理", "质量管理",
    "资源管理", "沟通管理", "风险管理", "采购管理", "干系人管理",
    "敏捷/混合方法", "商业环境", "领导力/人员",
]

# 领域 → 1 条改进建议
AREA_FIX_TIPS: dict[str, str] = {
    "整合管理": "变更流程：先评估影响再交CCB，未批不动",
    "范围管理": "WBS 分解可交付成果，拒绝范围蔓延",
    "进度管理": "关键路径活动延迟=项目延迟，先判关键路径",
    "成本管理": "挣值题先写公式：CV/SV/CPI/SPI",
    "质量管理": "QA管过程审计，QC查可交付物结果",
    "资源管理": "冲突首选合作/解决问题，RACI 分清责",
    "沟通管理": "交互式>推式>拉式，新信息先确认",
    "风险管理": "威胁/机会策略不同，应急储备vs管理储备",
    "采购管理": "FFP卖方担风险，成本补偿买方担风险",
    "干系人管理": "新干系人出现→先沟通再更新登记册",
    "敏捷/混合方法": "PO定优先级，回顾会查根因，SM清障碍",
    "商业环境": "商业论证+合规，效益导向做决策",
    "领导力/人员": "仆人式领导，情商激励优于命令控制",
    "敏捷": "质量问题→回顾会，团队自组织解决",
    "综合": "读清题干问「接下来第一步做什么」",
    "未分类": "回到 PMBOK 过程组定位考点",
}

# 根因类型：(名称, 匹配关键词, 防错策略, 考试当天提醒)
ROOT_CAUSE_TYPES: list[tuple[str, tuple[str, ...], str, str]] = [
    (
        "权力型",
        ("干系人", "相关方", "权力", "利益", "不满", "新加入", "新识别", "发起人", "客户"),
        "出现「人」的变量→先沟通/会面，再动工具或文档",
        "📌 见人先开口，登记册排第二",
    ),
    (
        "流程型",
        ("变更", "CCB", "审批", "基准", "章程", "流程", "下一步", "首先应该"),
        "问「接下来做什么」→先评估/分析，再执行/更新",
        "📌 未批不变更，先评估后执行",
    ),
    (
        "防御型",
        ("风险", "储备", "应急", "威胁", "问题", "缺陷", "根本原因", "鱼骨"),
        "区分风险(未发生)vs问题(已发生)，工具对号入座",
        "📌 风险登记册管未来，问题日志管已发生",
    ),
    (
        "敏捷混淆型",
        ("敏捷", "Scrum", "迭代", "燃尽", "回顾", "冲刺", "产品负责人", "自组织"),
        "敏捷题先想文化/透明/回顾，别盲选加流程或换工具",
        "📌 敏捷先查文化，回顾会治质量",
    ),
    (
        "采购混淆型",
        ("采购", "合同", "FFP", "工料", "成本补偿", "投标人", "卖方", "买方"),
        "合同题先判风险在谁：FFP→卖方，成本补偿→买方",
        "📌 合同先看型，风险跟谁走",
    ),
]


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default if default is not None else []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default if default is not None else []


def _days_left(today: date | None = None) -> int:
    return max(0, (EXAM_DATE - (today or date.today())).days)


def _exam_rate(e: dict) -> float:
    rate = float(e.get("correct_rate") or 0)
    if rate <= 1:
        rate *= 100
    if rate <= 1 and e.get("correct_count") and e.get("total_questions"):
        rate = _accuracy(e["correct_count"], e["total_questions"])
    return round(rate, 1)


def _mock_exams() -> list[dict]:
    """完整模考（≥100题，且有有效得分）。"""
    out = []
    for e in _load_exam_records():
        if e.get("total_questions", 0) < 100:
            continue
        if e.get("type") == "chapter_practice":
            continue
        rate = _exam_rate(e)
        if e.get("correct_count", 0) > 0 or rate > 0:
            out.append(e)
    return out


def _mock_avg_rate() -> float | None:
    exams = _mock_exams()
    if not exams:
        return None
    return round(sum(_exam_rate(e) for e in exams) / len(exams), 1)


def _risk_tag(acc: float, error_count: int) -> str:
    if acc < 30 or error_count >= 10:
        return "🔴 最高"
    if acc < 40 or error_count >= 6:
        return "🟠 高"
    return "🟡 中"


def _short_tip(text: str, max_len: int = 10) -> str:
    """核心建议压缩到 max_len 字以内。"""
    t = re.sub(r"[，。；、：]", "", text.strip())
    if len(t) <= max_len:
        return t
    # 优先截到标点或短语
    for cut in (8, 9, 10):
        if len(t) >= cut:
            return t[:cut]
    return t[:max_len]


def _analyze_root_causes(errors: list[dict]) -> list[dict[str, Any]]:
    """识别思维漏洞类型及频次。"""
    type_counts: Counter[str] = Counter()
    type_examples: dict[str, list[str]] = defaultdict(list)

    for err in errors:
        blob = f"{err.get('question', '')} {err.get('explanation', '')}"
        matched_type = None
        for name, keywords, strategy, tip in ROOT_CAUSE_TYPES:
            if any(kw in blob for kw in keywords):
                matched_type = name
                type_counts[name] += 1
                if len(type_examples[name]) < 2:
                    preview = re.sub(r"\s+", " ", err.get("question", ""))[:40]
                    type_examples[name].append(preview)
                break

    results = []
    for name, keywords, strategy, tip in ROOT_CAUSE_TYPES:
        cnt = type_counts.get(name, 0)
        if cnt == 0:
            continue
        results.append({
            "type": name,
            "count": cnt,
            "strategy": strategy,
            "exam_tip": tip,
            "examples": type_examples.get(name, []),
        })
    results.sort(key=lambda x: -x["count"])
    return results


def _high_risk_areas(
    by_area: dict[str, dict[str, int]],
    error_counts: dict[str, int],
) -> list[dict[str, Any]]:
    risks = []
    for area, stats in by_area.items():
        total = stats["total"]
        if total < 3:
            continue
        acc = _accuracy(stats["correct"], total)
        if acc >= 50:
            continue
        err_n = error_counts.get(area, 0)
        risks.append({
            "area": area,
            "accuracy": acc,
            "total": total,
            "errors": err_n,
            "tag": _risk_tag(acc, err_n),
            "tip": AREA_FIX_TIPS.get(area, AREA_FIX_TIPS["综合"]),
        })
    risks.sort(key=lambda x: (x["accuracy"], -x["errors"]))
    return risks


def _core_suggestions(
    mock_avg: float | None,
    pass_ok: bool,
    risks: list[dict],
    days: int,
) -> list[str]:
    tips: list[str] = []
    if mock_avg is not None and mock_avg < PASS_RATE:
        tips.append("先稳59%过线")
    elif mock_avg is not None and mock_avg < TARGET_RATE:
        tips.append("模考冲刺70%")
    if risks:
        tips.append(f"攻{risks[0]['area'][:4]}")
    if days <= 14:
        tips.append("错题每日清")
    elif days <= 30:
        tips.append("每周完整模考")
    else:
        tips.append("每日一练10题")

    if not tips:
        tips = ["保持刷题节奏", "复习到期错题", "做完整模考"]
    # 补齐 3 条
    fallbacks = ["复习到期错题", "专项攻薄弱项", "完整模考一次"]
    for fb in fallbacks:
        if len(tips) >= 3:
            break
        if fb not in tips:
            tips.append(fb)
    return [_short_tip(t, 10) for t in tips[:3]]


def _daily_sprint_plan(
    risks: list[dict],
    days: int,
    *,
    plan_days: int | None = None,
) -> list[dict[str, Any]]:
    """逐日冲刺计划。"""
    n = plan_days or min(days, 7)
    if n <= 0:
        n = 1
    today = date.today()
    plan: list[dict[str, Any]] = []

    # 任务池：薄弱领域 + 通用
    weak_names = [r["area"] for r in risks[:5]]
    if not weak_names:
        weak_names = ["整合管理", "风险管理"]

    for i in range(n):
        d = today + timedelta(days=i)
        tasks: list[str] = []
        if i == 0:
            due = _due_error_count()
            if due:
                tasks.append(f"复习到期错题 {due} 道")
            tasks.append("完成今日每日一练 10 题")
        area = weak_names[i % len(weak_names)]
        q = 20 if i < 3 else 15
        tasks.append(f"刷 {area} 专项 {q} 题")
        if i % 2 == 1 and area:
            tasks.append(f"重刷 {area} 错题 5 道")
        if i == n - 1 and days <= 14:
            tasks.append("完整模考 180 题（或随机模考）")
        elif i == 3:
            res = find_knowledge_resources(area, limit=1)
            if res:
                tasks.append(f"速查：{res[0][:20]}")

        plan.append({"day": i + 1, "date": d.isoformat(), "tasks": tasks[:3]})

    return plan


def _due_error_count() -> int:
    review = _load_json(REVIEW_STATE_PATH, {})
    today = date.today().isoformat()
    if not isinstance(review, dict):
        return 0
    return sum(
        1 for v in review.values()
        if isinstance(v, dict) and str(v.get("next_date", "")) <= today
    )


def _today_must_do(risks: list[dict], root_causes: list[dict]) -> list[str]:
    """今天必须完成的 3 件事（具体可执行）。"""
    actions: list[str] = []

    due = _due_error_count()
    if due:
        actions.append(f"复习到期错题 {due} 道（发送「复习错题」）")

    if risks:
        area = risks[0]["area"]
        err_n = min(risks[0]["errors"], 10) or 5
        actions.append(f"刷 30 道{area}专项题")
        actions.append(f"重刷 {err_n} 道{area}错题")
        res = find_knowledge_resources(area, limit=1)
        guide = "敏捷实践指南" if "敏捷" in area else res[0][:15] if res else f"{area}知识点"
        actions.append(f"看{guide}速查一遍")
    else:
        actions.append("完成今日每日一练 10 题")
        actions.append("发送「随机每日一练」加练一套")
        actions.append("回顾挣值/变更/风险核心公式")

    if root_causes and len(actions) < 3:
        rc = root_causes[0]
        actions.append(f"牢记防错卡：{rc['exam_tip'].replace('📌 ', '')}")

    # 去重并取 3 条
    seen: set[str] = set()
    out: list[str] = []
    for a in actions:
        if a not in seen:
            seen.add(a)
            out.append(a)
        if len(out) >= 3:
            break
    while len(out) < 3:
        out.append("睡前发送「睡前复习」巩固")
        break
    return out[:3]


def pre_exam_analysis(
    *,
    focus: str = "full",
    plan_days: int | None = None,
) -> dict[str, Any]:
    """
    考前深度分析主入口。

    focus: full | root_cause
    plan_days: 「最后X天」指定天数
    """
    today = date.today()
    days = _days_left(today)

    bank = QuestionBank()
    graded = [r for r in bank.list_all() if r.get("is_correct") is not None]
    by_area = _area_stats(graded)

    errors = _load_json(ERROR_LOG_PATH, [])
    if not isinstance(errors, list):
        errors = []
    error_counts: dict[str, int] = defaultdict(int)
    for e in errors:
        error_counts[e.get("knowledge_area") or "综合"] += 1

    mock_avg = _mock_avg_rate()
    mock_exams = _mock_exams()
    pass_ok = mock_avg is not None and mock_avg >= PASS_RATE
    target_ok = mock_avg is not None and mock_avg >= TARGET_RATE

    risks = _high_risk_areas(by_area, dict(error_counts))
    root_causes = _analyze_root_causes(errors)
    suggestions = _core_suggestions(mock_avg, pass_ok, risks, days)
    daily_plan = _daily_sprint_plan(risks, days, plan_days=plan_days)
    today_actions = _today_must_do(risks, root_causes)

    # ── 组装输出 ──
    lines: list[str] = [
        "══════════════════════════════",
        "🎯 考前深度分析",
        "══════════════════════════════",
        "",
        f"📅 距考试 {days} 天（{EXAM_DATE}）",
    ]

    # 功能1：一句话结论
    if mock_avg is not None:
        status = "✅ 已过线" if pass_ok else "⚠️ 未过线"
        target_tag = " 🎉" if target_ok else ""
        lines.append(
            f"📊 模考均分 {mock_avg}%（{len(mock_exams)} 次）{status}{target_tag}"
        )
        lines.append(
            f"💬 结论：{'已达59%通过线' if pass_ok else '距59%过线还差' + str(max(0, round(PASS_RATE - mock_avg, 1))) + '%'}"
            f"，{'冲刺70%目标' if not target_ok else '保持手感'}"
        )
    else:
        total = len(graded)
        acc = _accuracy(sum(1 for r in graded if r.get("is_correct")), total) if total else 0
        lines.append(f"📊 暂无完整模考，日常正确率 {acc}%（{total} 题）")
        lines.append("💬 结论：建议尽快做完整模考摸底")

    sug_str = " · ".join(f"{i+1}.{s}" for i, s in enumerate(suggestions))
    lines.extend(["", f"🎯 核心建议：{sug_str}"])

    # 功能4 根因（focus 模式提前）
    if focus == "root_cause" and root_causes:
        lines.extend(["", "🧠 防错策略卡", "──────────────────────"])
        for rc in root_causes[:4]:
            lines.append(f"· {rc['type']}（{rc['count']}题）")
            lines.append(f"  策略：{rc['strategy']}")
            lines.append(f"  {rc['exam_tip']}")

    # 功能2：高风险清单
    if risks:
        lines.extend(["", "🚨 高风险领域", "──────────────────────"])
        for r in risks[:6]:
            lines.append(
                f"{r['tag']} [{r['area']}] {r['accuracy']}% "
                f"（{r['total']}题/{r['errors']}错）"
            )
            lines.append(f"  💡 {r['tip']}")
    else:
        lines.extend(["", "✅ 暂无正确率<50%的高风险领域"])

    # 功能3：逐日冲刺
    show_days = plan_days or min(days, 7)
    lines.extend(["", f"📆 逐日冲刺（{show_days} 天）", "──────────────────────"])
    for dp in daily_plan[:show_days]:
        wd = ["一", "二", "三", "四", "五", "六", "日"][date.fromisoformat(dp["date"]).weekday()]
        lines.append(f"Day{dp['day']} {dp['date'][5:]} 周{wd}")
        for t in dp["tasks"]:
            lines.append(f"  · {t}")

    # 功能4：根因（full 模式）
    if focus != "root_cause" and root_causes:
        lines.extend(["", "🧠 防错策略卡", "──────────────────────"])
        for rc in root_causes[:3]:
            lines.append(f"· {rc['type']} ×{rc['count']}")
            lines.append(f"  {rc['exam_tip']}")

    # 功能5：今日必做
    lines.extend(["", "✅ 今天必须完成", "──────────────────────"])
    for i, act in enumerate(today_actions, 1):
        lines.append(f"{i}. {act}")

    return {
        "status": "ok",
        "days_left": days,
        "mock_avg": mock_avg,
        "pass_ok": pass_ok,
        "target_ok": target_ok,
        "high_risks": risks,
        "root_causes": root_causes,
        "suggestions": suggestions,
        "daily_plan": daily_plan,
        "today_actions": today_actions,
        "text": "\n".join(lines),
    }


def parse_trigger(text: str) -> dict[str, Any] | None:
    t = text.strip().replace("\u200b", "")
    if not t:
        return None

    triggers = ("考前分析", "根因分析")
    if any(k in t for k in triggers):
        focus = "root_cause" if "根因" in t else "full"
        return {"focus": focus}

    m = re.search(r"最后\s*(\d+)\s*天", t)
    if m and re.search(r"安排|计划|怎么", t):
        return {"focus": "full", "plan_days": int(m.group(1))}

    return None


def handle_message(text: str) -> dict[str, Any]:
    parsed = parse_trigger(text)
    if not parsed:
        return {"status": "skip"}
    return pre_exam_analysis(
        focus=parsed.get("focus", "full"),
        plan_days=parsed.get("plan_days"),
    )


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="考前深度分析")
    sub = parser.add_subparsers(dest="command")

    p_an = sub.add_parser("analyze", help="完整分析报告")
    p_an.add_argument("--days", type=int, default=None, help="冲刺计划天数")
    p_an.add_argument("--json", action="store_true")

    sub.add_parser("root-cause", help="侧重根因防错卡")

    p_msg = sub.add_parser("message", help="解析微信消息")
    p_msg.add_argument("--text", "-t", required=True)
    p_msg.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.command == "analyze":
        result = pre_exam_analysis(plan_days=args.days)
    elif args.command == "root-cause":
        result = pre_exam_analysis(focus="root_cause")
    elif args.command == "message":
        result = handle_message(args.text)
        if result.get("status") == "skip":
            result = {"status": "skip", "text": ""}
    else:
        result = pre_exam_analysis()

    if getattr(args, "json", False) or args.command == "message":
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result.get("text", ""))


if __name__ == "__main__":
    main()
