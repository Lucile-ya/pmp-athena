#!/usr/bin/env python3
"""
学习顾问 —— 薄弱点分析、今日错题复习、智能学习计划

用法:
    python pmp_athena/study_advisor.py weakness       # 总结薄弱点
    python pmp_athena/study_advisor.py review-today    # 今日复习错题
    python pmp_athena/study_advisor.py plan            # 制定学习计划
    python pmp_athena/study_advisor.py plan --days 7   # 未来N天计划
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# ── 路径 ──────────────────────────────────────────────────
QUESTION_BANK = Path("D:/pmp-athena/pmp_notes/question_bank.json")
ERROR_LOG = Path("D:/pmp-athena/pmp_notes/error_log.json")
REVIEW_STATE = Path("D:/pmp-athena/pmp_notes/error_review_state.json")
EXAM_CONFIG = Path("D:/pmp-athena/pmp_notes/exam_config.json")

# ── 知识领域 ──────────────────────────────────────────────
ALL_AREAS = [
    "整合管理", "范围管理", "进度管理", "成本管理", "质量管理",
    "资源管理", "沟通管理", "风险管理", "采购管理", "干系人管理",
    "敏捷/混合方法", "商业环境", "领导力/人员",
]


# ═══════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════

def load_json(path: Path) -> list | dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [] if path.suffix == ".json" and path.name != "exam_config.json" else {}


def get_exam_date() -> date | None:
    cfg = load_json(EXAM_CONFIG)
    if isinstance(cfg, dict):
        raw = cfg.get("exam_date", "")
        try:
            return datetime.strptime(str(raw), "%Y-%m-%d").date()
        except Exception:
            pass
    return None


# ═══════════════════════════════════════════════════════════
# 1. 总结薄弱点
# ═══════════════════════════════════════════════════════════

def analyze_weakness() -> str:
    """分析薄弱领域，输出诊断报告"""
    bank = load_json(QUESTION_BANK)
    errors = load_json(ERROR_LOG)
    review = load_json(REVIEW_STATE)

    if not isinstance(bank, list):
        bank = []
    if not isinstance(errors, list):
        errors = []
    if not isinstance(review, dict):
        review = {}

    lines = []
    lines.append("📊 薄弱点诊断报告")
    lines.append("=" * 30)

    # ── 按领域统计正确率 ──
    area_stats: dict[str, dict] = {}
    for r in bank:
        area = r.get("knowledge_area", "未分类")
        if area not in area_stats:
            area_stats[area] = {"total": 0, "correct": 0, "wrong": 0}
        area_stats[area]["total"] += 1
        if r.get("is_correct") is True:
            area_stats[area]["correct"] += 1
        elif r.get("is_correct") is False:
            area_stats[area]["wrong"] += 1

    # 找薄弱领域（按错误率降序，至少做过2题）
    weak_list = []
    for area, s in area_stats.items():
        judged = s["correct"] + s["wrong"]
        if judged >= 2:
            rate = s["wrong"] / judged
            weak_list.append((area, rate, s["total"], s["wrong"], s["correct"]))
    weak_list.sort(key=lambda x: x[1], reverse=True)

    if weak_list:
        lines.append("\n## 🎯 薄弱领域 TOP 3\n")
        lines.append("| 领域 | 错误率 | 错/总 | 风险 |")
        lines.append("|------|--------|-------|------|")
        for area, rate, total, wrong, correct in weak_list[:5]:
            risk = "🔴 高危" if rate >= 0.7 else ("🟡 注意" if rate >= 0.4 else "🟢 可接受")
            lines.append(f"| {area} | {rate:.0%} | {wrong}/{total} | {risk} |")

    # ── 错题本专项统计 ──
    if errors:
        err_area: dict[str, int] = {}
        for e in errors:
            a = e.get("knowledge_area", "未分类")
            err_area[a] = err_area.get(a, 0) + 1
        sorted_err = sorted(err_area.items(), key=lambda x: x[1], reverse=True)

        lines.append("\n## 📋 错题本分布\n")
        for area, count in sorted_err:
            bar = "█" * count
            lines.append(f"- {area}: {count} 题 {bar}")

    # ── 常见错误模式 ──
    patterns: dict[str, int] = {}
    for r in bank:
        if r.get("is_correct") is False:
            p = f"{r.get('my_answer', '?')}→{r.get('correct_answer', '?')}"
            patterns[p] = patterns.get(p, 0) + 1
    sorted_pt = sorted(patterns.items(), key=lambda x: x[1], reverse=True)

    if sorted_pt:
        lines.append("\n## 🔁 高频错误选项模式\n")
        for p, cnt in sorted_pt[:5]:
            lines.append(f"- {p}: {cnt} 次")

    # ── 敏捷专项诊断 ──
    agile_wrong = sum(
        1 for r in bank
        if r.get("is_correct") is False and "敏捷" in r.get("knowledge_area", "")
    )
    agile_total = sum(
        1 for r in bank
        if "敏捷" in r.get("knowledge_area", "")
    )
    if agile_total > 0:
        lines.append(f"\n## ⚡ 敏捷专项\n")
        lines.append(f"- 敏捷题总数: {agile_total}")
        lines.append(f"- 敏捷错题: {agile_wrong}")
        lines.append(f"- 敏捷错误率: {agile_wrong / agile_total:.0%}" if agile_total else "")
        if agile_wrong >= 3:
            lines.append("- ⚠️ 敏捷场景是你的**持续弱点**，建议专题突破")

    # ── 复习待办 ──
    today_str = date.today().isoformat()
    overdue = sum(1 for v in review.values() if v.get("next_date", "9999") <= today_str)
    total_review = len(review)
    mastered = sum(1 for v in review.values() if v.get("interval", 0) >= 30)

    lines.append(f"\n## 🧠 间隔复习状态\n")
    lines.append(f"- 队列总数: {total_review}")
    lines.append(f"- 今日逾期未复习: **{overdue}** 题")
    lines.append(f"- 已掌握 (间隔≥30天): {mastered} 题")

    # ── 一句话建议 ──
    lines.append("\n## 💡 针对性建议\n")
    if weak_list:
        top_weak = weak_list[0][0]
        lines.append(f"1. 优先攻克 **{top_weak}**：每天专项练习 10 题")
    if agile_wrong >= 3:
        lines.append("2. 重点补强 **敏捷/混合方法**：回顾 Scrum 指南、敏捷 manifesto 四价值十二原则")
    if overdue > 0:
        lines.append(f"3. ⚠️ 有 {overdue} 道错题复习已逾期，今天优先处理！")
    lines.append("4. 练习时注意：选'看起来标准化的流程动作'前，先想'直接、务实、人本'的替代方案")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 2. 今日复习错题
# ═══════════════════════════════════════════════════════════

def review_today() -> str:
    """汇总今日需要复习的错题"""
    errors = load_json(ERROR_LOG)
    review = load_json(REVIEW_STATE)
    bank = load_json(QUESTION_BANK)

    if not isinstance(errors, list):
        errors = []
    if not isinstance(review, dict):
        review = {}
    if not isinstance(bank, list):
        bank = []

    today_str = date.today().isoformat()
    lines = []
    lines.append(f"📅 今日复习清单（{today_str}）")
    lines.append("=" * 30)

    # ── 今天新增的错题 ──
    today_errors = [e for e in errors if e.get("date") == today_str]
    if today_errors:
        lines.append(f"\n## 🆕 今日新增错题（{len(today_errors)} 题）\n")
        for e in today_errors:
            lines.append(
                f"❌ #{e['id']} [{e.get('knowledge_area', '')}] "
                f"{e.get('my_answer', '?')}→{e.get('correct_answer', '?')}"
            )
            q = e.get("question", "")[:80]
            lines.append(f"   {q}")
            expl = e.get("explanation", "")
            if expl:
                lines.append(f"   💡 {expl[:100]}")
            lines.append("")

    # ── SM-2 今日到期 ──
    due_cards = []
    for key, card in review.items():
        if card.get("next_date", "9999") <= today_str:
            error = next((e for e in errors if e.get("id") == card.get("error_id")), None)
            due_cards.append({**card, "error": error})

    if due_cards:
        lines.append(f"\n## 🔄 SM-2 到期复习（{len(due_cards)} 题）\n")
        for i, card in enumerate(due_cards, 1):
            e = card.get("error") or {}
            lines.append(
                f"### {i}. #{card.get('error_id', '?')} "
                f"[{card.get('knowledge_area', e.get('knowledge_area', ''))}] "
                f"EF={card.get('ef', 0):.1f} 间隔{card.get('interval', 0)}天"
            )
            q = e.get("question", card.get("question_preview", ""))[:100]
            lines.append(f"> {q}")
            lines.append(
                f"❌ {e.get('my_answer', '?')} → ✅ {e.get('correct_answer', '?')}"
            )
            expl = e.get("explanation", "")
            if expl:
                lines.append(f"💡 {expl[:120]}")
            lines.append("")

    # ── 题库中今日做错的（已在question_bank但可能未入error_log）──
    today_wrong_in_bank = [
        r for r in bank
        if r.get("date") == today_str and r.get("is_correct") is False
    ]
    already_covered = {e.get("id") for e in today_errors}
    extra_wrong = [r for r in today_wrong_in_bank if r.get("error_log_id") not in already_covered]

    if extra_wrong:
        lines.append(f"\n## 📋 题库中的今日错题（{len(extra_wrong)} 题）\n")
        for r in extra_wrong:
            lines.append(
                f"❌ #{r['id']} [{r.get('knowledge_area', '')}] "
                f"{r.get('my_answer', '?')}→{r.get('correct_answer', '?')}"
            )
            lines.append(f"   {r.get('question', '')[:80]}")
            lines.append("")

    if not today_errors and not due_cards and not extra_wrong:
        lines.append("\n✅ 今日暂无待复习错题，继续保持！")
        lines.append("\n💡 建议：回顾之前的高频薄弱领域，保持手感。")
    else:
        total = len(today_errors) + len(due_cards) + len(extra_wrong)
        lines.insert(2, f"📌 共 {total} 题需要复习\n")
        lines.append("---")
        lines.append("复习完成后用 `/review` 评分，格式：`评分#N M`（M 为 0-5）")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 3. 制定学习计划
# ═══════════════════════════════════════════════════════════

def generate_plan(custom_days: int = 0) -> str:
    """生成智能学习计划"""
    exam_date = get_exam_date()
    today = date.today()
    bank = load_json(QUESTION_BANK)
    review = load_json(REVIEW_STATE)

    if not isinstance(bank, list):
        bank = []
    if not isinstance(review, dict):
        review = {}

    lines = []
    lines.append("📋 PMP 智能学习计划")
    lines.append("=" * 30)

    # ── 倒计时 ──
    if exam_date:
        remaining = (exam_date - today).days
    else:
        remaining = 47  # 默认
        exam_date = today + timedelta(days=remaining)

    if custom_days > 0:
        plan_days = custom_days
    else:
        plan_days = min(remaining, 14)  # 默认规划两周

    lines.append(f"\n📅 考试日期: {exam_date.isoformat()}")
    lines.append(f"⏳ 倒计时: **{remaining} 天**")
    lines.append(f"📐 计划跨度: {plan_days} 天（{today.isoformat()} ~ {(today + timedelta(days=plan_days)).isoformat()}）")

    # ── 当前状态 ──
    total_q = len(bank)
    wrong_q = sum(1 for r in bank if r.get("is_correct") is False)
    correct_q = sum(1 for r in bank if r.get("is_correct") is True)
    accuracy = correct_q / (correct_q + wrong_q) if (correct_q + wrong_q) > 0 else 0

    overdue = sum(1 for v in review.values() if v.get("next_date", "9999") <= today.isoformat())
    total_review = len(review)

    lines.append(f"\n## 📊 当前状态\n")
    lines.append(f"| 指标 | 数据 |")
    lines.append(f"|------|------|")
    lines.append(f"| 总做题量 | {total_q} |")
    lines.append(f"| 当前正确率 | {accuracy:.0%} |")
    lines.append(f"| 错题本存量 | {wrong_q} |")
    lines.append(f"| SM-2 逾期复习 | {overdue} / {total_review} |")

    # ── 薄弱领域 ──
    area_stats: dict[str, dict] = {}
    for r in bank:
        area = r.get("knowledge_area", "未分类")
        if area not in area_stats:
            area_stats[area] = {"total": 0, "correct": 0, "wrong": 0}
        area_stats[area]["total"] += 1
        if r.get("is_correct") is True:
            area_stats[area]["correct"] += 1
        elif r.get("is_correct") is False:
            area_stats[area]["wrong"] += 1

    weak_list = []
    for area, s in area_stats.items():
        judged = s["correct"] + s["wrong"]
        if judged >= 2:
            rate = s["wrong"] / judged
            weak_list.append((area, rate))
    weak_list.sort(key=lambda x: x[1], reverse=True)

    if weak_list:
        lines.append(f"\n## 🎯 重点攻克领域\n")
        for area, rate in weak_list[:3]:
            lines.append(f"- **{area}**（错误率 {rate:.0%}）")

    # ── 每日任务 ──
    lines.append(f"\n## 📅 每日任务清单\n")
    lines.append("| 时段 | 任务 | 时长 |")
    lines.append("|------|------|------|")
    lines.append("| 🌅 早晨 | 温习昨日错题解析 | 15min |")
    lines.append("| ☀️ 上午 | 每日一练 10 题 + 精读解析 | 30min |")
    lines.append("| 🌤 下午 | 薄弱领域专项练习 10 题 | 25min |")
    lines.append("| 🌙 晚间 | SM-2 错题复习 + 评分 | 20min |")
    lines.append("| 📖 睡前 | 快速回顾今日 3 个关键概念 | 10min |")
    lines.append(f"\n**日均投入: 约 1.5 小时**")

    # ── 阶段规划 ──
    lines.append(f"\n## 🗺 阶段规划（{plan_days} 天）\n")

    phase1_days = max(1, plan_days // 3)
    phase2_days = max(1, plan_days // 3)
    phase3_days = plan_days - phase1_days - phase2_days

    lines.append(f"### 阶段一：补弱（前 {phase1_days} 天）")
    lines.append(f"- 集中攻克 TOP 3 薄弱领域")
    lines.append(f"- 每天保证 SM-2 错题复习清零")
    lines.append(f"- 目标：薄弱领域错误率降至 40% 以下")
    lines.append("")
    lines.append(f"### 阶段二：巩固（中间 {phase2_days} 天）")
    lines.append(f"- 真题模拟 + 错题归因")
    lines.append(f"- 敏捷场景专项突破")
    lines.append(f"- 目标：整体正确率稳定在 75%+")
    lines.append("")
    lines.append(f"### 阶段三：冲刺（最后 {phase3_days} 天）")
    lines.append(f"- 全真模拟考试节奏")
    lines.append(f"- 核心公式/概念最后过一遍")
    lines.append(f"- 目标：正确率 80%+，信心满满上考场")

    # ── 每日提醒 ──
    lines.append(f"\n## ⚠️ 每日坑位提醒\n")
    lines.append("1. 敏捷题：PM 是引导者，让团队自组织")
    lines.append("2. 资源题：先想'人'和'知识'，别绕到工具和钱")
    lines.append("3. 沟通题：先直接沟通，别绕弯查计划")
    lines.append("4. 干系人题：新干系人 → 先见面沟通，再更新登记册")
    lines.append("5. 题干问'首先'/'接下来' → 选最直接、最务实的选项")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="PMP 学习顾问")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("weakness", help="总结薄弱点")
    sub.add_parser("review-today", help="今日复习错题")

    p_plan = sub.add_parser("plan", help="制定学习计划")
    p_plan.add_argument("--days", "-d", type=int, default=0, help="计划跨度（天），默认14天")

    args = parser.parse_args()

    if args.command == "weakness":
        output = analyze_weakness()
    elif args.command == "review-today":
        output = review_today()
    elif args.command == "plan":
        output = generate_plan(custom_days=args.days)
    else:
        output = analyze_weakness()

    # 显式用 UTF-8 编码输出，兼容 Windows GBK 控制台
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    try:
        print(output)
    except UnicodeEncodeError:
        # 回退：写入 bytes
        sys.stdout.buffer.write(output.encode("utf-8") + b"\n")


if __name__ == "__main__":
    main()
