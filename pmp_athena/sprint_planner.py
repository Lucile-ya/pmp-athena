#!/usr/bin/env python3
"""
冲刺计划生成器

根据错题本和模考记录分析薄弱知识域，按错误率分配天数生成冲刺计划。
每天包含：知识域、推荐复习内容（向量检索）、建议做题数、建议时间。

用法:
    python pmp_athena/sprint_planner.py plan 7           # 生成 7 天冲刺计划
    python pmp_athena/sprint_planner.py today            # 今天的冲刺任务
    python pmp_athena/sprint_planner.py progress         # 冲刺进度
    python pmp_athena/sprint_planner.py done 1           # 标记第 1 天完成
    python pmp_athena/sprint_planner.py list             # 列出所有冲刺计划
"""

import argparse
import json
import logging
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sprint_planner")

# ── 路径 ──────────────────────────────────────────────────
ERROR_LOG = Path("D:/pmp-athena/pmp_notes/error_log.json")
EXAM_RECORDS = Path("D:/pmp-athena/pmp_notes/exam_records.json")
MOCK_RECORDS = Path("D:/pmp-athena/pmp_notes/mock_exam_records.json")
SPRINT_STORE = Path("D:/pmp-athena/pmp_notes/sprint_plans.json")

# ── 知识域映射 ──────────────────────────────────────────
DOMAIN_INFO = {
    "整合管理":        {"weight": 0.11, "search": "整合管理 项目章程 变更控制 知识管理"},
    "范围管理":        {"weight": 0.10, "search": "范围管理 WBS 需求收集 范围基准"},
    "进度管理":        {"weight": 0.11, "search": "进度管理 关键路径法 CPM 赶工 快速跟进"},
    "成本管理":        {"weight": 0.09, "search": "成本管理 挣值管理 EVM 成本估算 EAC"},
    "质量管理":        {"weight": 0.08, "search": "质量管理 因果图 控制图 帕累托图"},
    "资源管理":        {"weight": 0.08, "search": "资源管理 RACI 团队建设 冲突解决"},
    "沟通管理":        {"weight": 0.07, "search": "沟通管理 干系人沟通 信息分发"},
    "风险管理":        {"weight": 0.10, "search": "风险管理 风险应对 定性定量分析"},
    "采购管理":        {"weight": 0.04, "search": "采购管理 合同类型 FFP CPFF T&M"},
    "干系人管理":      {"weight": 0.08, "search": "干系人管理 参与矩阵 干系人分析"},
    "敏捷/混合方法":   {"weight": 0.06, "search": "敏捷 Scrum 看板 迭代 冲刺回顾"},
    "商业环境":        {"weight": 0.04, "search": "商业环境 商业论证 收益管理 合规"},
    "领导力/人员":     {"weight": 0.04, "search": "领导力 激励理论 Tuckman 情商"},
}


class SprintPlanner:
    """冲刺计划生成器"""

    def __init__(self):
        self.store_path = SPRINT_STORE
        self._ensure_files()

    def _ensure_files(self):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self.store_path.write_text("[]", encoding="utf-8")

    # ── 数据源 ────────────────────────────────────────────

    def _read_json(self, path: Path) -> list | dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return [] if path.suffix == ".json" else {}

    def _read_plans(self) -> list[dict]:
        return self._read_json(self.store_path)

    def _write_plans(self, plans: list[dict]):
        self.store_path.write_text(
            json.dumps(plans, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── 核心分析 ──────────────────────────────────────────

    def analyze_weakness(self) -> dict[str, dict]:
        """
        综合分析错题本 + 模考记录，返回各领域的薄弱指数。

        返回:
        {
            "风险管理": {"errors": 5, "weak_rate": 0.35, "total_questions": 50, "priority": 1},
            ...
        }
        """
        # 1. 错题统计
        error_log = self._read_json(ERROR_LOG)
        area_errors: dict[str, int] = {}
        for e in error_log:
            area = e.get("knowledge_area", "未分类")
            area_errors[area] = area_errors.get(area, 0) + 1

        # 2. 模考成绩（exam_records.json）
        exams = self._read_json(EXAM_RECORDS)
        if isinstance(exams, dict):
            exams = exams.get("exams", [])
        if isinstance(exams, list):
            # 取最近一次模考
            latest_scores: dict[str, float] = {}
            if exams:
                latest = sorted(
                    exams,
                    key=lambda x: x.get("exam_date", ""),
                    reverse=True,
                )[0]
                latest_scores = latest.get("scores", {})

            # 将 PMP 三大领域映射到具体知识领域
            people_score = latest_scores.get("people", 0.80)
            process_score = latest_scores.get("process", 0.75)
            be_score = latest_scores.get("business_environment", 0.80)

            # 领域 → 默认错误率（基于模考得分和错误分布）
            area_base_rate: dict[str, float] = {}
            for area, info in DOMAIN_INFO.items():
                if area in ("领导力/人员",):
                    area_base_rate[area] = 1 - people_score
                elif area == "商业环境":
                    area_base_rate[area] = 1 - be_score
                elif area == "敏捷/混合方法":
                    area_base_rate[area] = (1 - process_score) * 0.8
                else:
                    # 过程组的 8 个领域分摊 process 的失分
                    rate_adjust = 0.7 if info["weight"] >= 0.09 else 0.5
                    area_base_rate[area] = (1 - process_score) * rate_adjust
        else:
            area_base_rate = {a: 0.2 for a in DOMAIN_INFO}

        # 3. 合并：错题数 + 基础弱率 → 综合弱率
        total_errors = sum(area_errors.values()) or 1
        result: dict[str, dict] = {}

        for area, info in DOMAIN_INFO.items():
            err_count = area_errors.get(area, 0)
            err_rate = err_count / total_errors if total_errors else 0

            # 综合弱率 = 错题率 × 0.6 + 基础弱率 × 0.4
            base_rate = area_base_rate.get(area, 0.2)
            weak_rate = err_rate * 0.6 + base_rate * 0.4
            # 最小保证 0.02，最大 0.5
            weak_rate = max(0.02, min(0.5, weak_rate))

            # 估算该领域总题目数（基于权重 × 180）
            estimated_total = max(10, int(info["weight"] * 180))

            result[area] = {
                "errors": err_count,
                "weak_rate": round(weak_rate, 3),
                "estimated_total_questions": estimated_total,
                "weight": info["weight"],
                "search_query": info["search"],
            }

        return result

    # ── 生成计划 ──────────────────────────────────────────

    def generate(self, days: Optional[int] = None, start_date: Optional[str] = None) -> dict:
        """
        生成 N 天冲刺计划。

        Args:
            days: 冲刺天数
            start_date: 开始日期，默认明天

        Returns:
            完整的冲刺计划 dict
        """
        if start_date is None:
            start_date = (date.today() + timedelta(days=1)).isoformat()
        else:
            start_date = date.fromisoformat(start_date).isoformat()

        # 自动推荐天数（如果未指定）
        if days is None:
            try:
                from .exam_timer import ExamTimer
                days = ExamTimer().recommend_sprint_days()
            except Exception:
                days = 7

        # 分析弱点
        weaknesses = self.analyze_weakness()

        # 获取当前备考阶段，加到计划元数据
        try:
            from .exam_timer import ExamTimer
            timer = ExamTimer()
            cd = timer.countdown()
            phase = cd.get("phase", "")
            exam_date = cd.get("exam_date")
            days_remaining = cd.get("days_remaining")
        except Exception:
            phase = ""
            exam_date = None
            days_remaining = None

        # 按 weak_rate 降序排列领域
        ranked = sorted(weaknesses.items(), key=lambda x: x[1]["weak_rate"], reverse=True)

        # 按弱率分配天数
        total_weak = sum(v["weak_rate"] for _, v in ranked) or 1
        allocation: list[dict] = []

        # 给每个领域分配至少 0.5 天，剩余按比例
        raw_days = {area: max(0.5, (data["weak_rate"] / total_weak) * days)
                    for area, data in ranked}

        # 调整，确保总天数不超过 days
        total_allocated = sum(raw_days.values())
        scale = days / total_allocated if total_allocated > 0 else 1
        allocated_days = {a: max(1, round(d * scale)) for a, d in raw_days.items()}

        # 再次调整，截断到 days
        while sum(allocated_days.values()) > days:
            # 给分配最多的领域减一天
            max_area = max(allocated_days, key=allocated_days.get)
            if allocated_days[max_area] > 1:
                allocated_days[max_area] -= 1
            else:
                break

        # 生成每日计划
        plan_days: list[dict] = []
        day_num = 0
        baseline_date = date.fromisoformat(start_date)

        for area, data in ranked:
            area_days = allocated_days.get(area, 1)
            err_count = data["errors"]
            weak_rate = data["weak_rate"]
            weight = data["weight"]

            for d in range(area_days):
                day_num += 1
                if day_num > days:
                    break

                day_date = baseline_date + timedelta(days=day_num - 1)

                # 题目数：基于权重 × 180 × daily_focus
                daily_questions = max(10, int(weight * 180 * 0.4))

                # 时间：3-5 分钟/题 + 30 分钟复习笔记
                study_minutes = daily_questions * 4 + 30

                plan_days.append({
                    "day": day_num,
                    "date": day_date.isoformat(),
                    "knowledge_area": area,
                    "weak_rate": weak_rate,
                    "total_errors": err_count,
                    "domain_weight": weight,
                    "suggested_questions": daily_questions,
                    "suggested_time_minutes": study_minutes,
                    "search_query": data["search_query"],
                    "is_day_1_of_area": d == 0,
                    "completed": False,
                })

            if day_num >= days:
                break

        # 确保预留最后一天为综合复习
        if day_num < days and len(plan_days) > 0:
            # 最后一天：综合复习（薄弱领域中最弱的两三个）
            top_weak = [a for a, _ in ranked[:3]]
            review_day = {
                "day": days,
                "date": (baseline_date + timedelta(days=days - 1)).isoformat(),
                "knowledge_area": "综合复习",
                "weak_rate": 0,
                "total_errors": sum(v["errors"] for _, v in ranked),
                "domain_weight": 0,
                "suggested_questions": 60,
                "suggested_time_minutes": 120,
                "search_query": " ".join(
                    f"{a} {DOMAIN_INFO[a]['search']}" for a in top_weak
                ),
                "is_day_1_of_area": True,
                "completed": False,
            }
            # 移除中间多余的 day（如果有的话）
            plan_days = [d for d in plan_days if d["day"] != days]
            plan_days.append(review_day)
            plan_days.sort(key=lambda x: x["day"])

        # 存盘
        plan = {
            "id": datetime.now().strftime("sprint_%Y%m%d_%H%M%S"),
            "created_at": datetime.now().isoformat(),
            "days": days,
            "start_date": start_date,
            "end_date": (baseline_date + timedelta(days=days - 1)).isoformat(),
            "status": "active",          # active | completed | abandoned
            "exam_date": exam_date,
            "days_remaining": days_remaining,
            "phase": phase,
            "weakness_analysis": {
                a: {
                    "errors": d["errors"],
                    "weak_rate": d["weak_rate"],
                    "days_allocated": allocated_days.get(a, 1),
                }
                for a, d in ranked
            },
            "day_plans": plan_days,
        }

        plans = self._read_plans()
        plans.append(plan)
        self._write_plans(plans)

        logger.info(
            "Sprint plan %s created: %d days, start %s",
            plan["id"], days, start_date,
        )
        return plan

    # ── 当前冲刺 ──────────────────────────────────────────

    def get_active_plan(self) -> dict | None:
        """获取当前活跃的冲刺计划"""
        plans = self._read_plans()
        active = [p for p in plans if p.get("status") == "active"]
        active.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return active[0] if active else None

    def get_today_tasks(self) -> dict | None:
        """获取今天的冲刺任务"""
        plan = self.get_active_plan()
        if not plan:
            return None

        today_str = date.today().isoformat()
        for day in plan["day_plans"]:
            if day["date"] == today_str:
                return {
                    "plan_id": plan["id"],
                    "plan_days": plan["days"],
                    "plan_progress": f"{sum(1 for d in plan['day_plans'] if d['completed'])}/{plan['days']}",
                    "today": day,
                }

        # 今天的日期不在计划中——可能还没开始，或已结束
        start = plan["day_plans"][0]["date"]
        end = plan["day_plans"][-1]["date"]
        if today_str < start:
            return {"status": "not_started", "starts_on": start}
        return {"status": "ended", "ended_on": end}

    def mark_done(self, day_num: int) -> bool:
        """标记某天任务已完成"""
        plan = self.get_active_plan()
        if not plan:
            return False

        for day in plan["day_plans"]:
            if day["day"] == day_num:
                day["completed"] = True
                break
        else:
            return False

        # 检查是否全部完成
        if all(d["completed"] for d in plan["day_plans"]):
            plan["status"] = "completed"

        # 写回
        plans = self._read_plans()
        for i, p in enumerate(plans):
            if p["id"] == plan["id"]:
                plans[i] = plan
                break
        self._write_plans(plans)

        logger.info("Day %d marked done in plan %s", day_num, plan["id"])
        return True

    def get_progress(self) -> dict:
        """获取当前冲刺进度"""
        plan = self.get_active_plan()
        if not plan:
            return {"status": "no_active_plan"}

        total = len(plan["day_plans"])
        completed = sum(1 for d in plan["day_plans"] if d["completed"])
        today_tasks = self.get_today_tasks()

        return {
            "plan_id": plan["id"],
            "days": plan["days"],
            "start_date": plan["start_date"],
            "end_date": plan["end_date"],
            "completed": completed,
            "total": total,
            "progress_pct": round(completed / total * 100) if total else 0,
            "today": today_tasks,
            "day_plans": plan["day_plans"],
        }


# ═══════════════════════════════════════════════════════════
# Markdown 输出
# ═══════════════════════════════════════════════════════════

def format_plan_markdown(plan: dict) -> str:
    """将冲刺计划格式化为 Markdown"""
    lines = []

    # 头
    lines.append("╔══════════════════════════════════════╗")
    lines.append(f"║   📋 {plan['days']} 天 PMP 冲刺计划            ║")
    lines.append("╚══════════════════════════════════════╝")
    lines.append("")
    lines.append(f"📅 {plan['start_date']} ～ {plan['end_date']}")
    lines.append(f"🆔 {plan['id']}")
    lines.append("")

    # 薄弱分析
    lines.append("## 📊 薄弱领域分析\n")
    lines.append("| 知识领域 | 错题数 | 弱率 | 安排天数 |")
    lines.append("|----------|--------|------|----------|")
    w = plan.get("weakness_analysis", {})
    for area in sorted(w, key=lambda a: w[a].get("weak_rate", 0), reverse=True):
        d = w[area]
        bar = "█" * max(1, int(d["weak_rate"] * 40))
        lines.append(f"| {area} | {d['errors']} | {bar} {d['weak_rate']:.0%} | {d['days_allocated']} |")
    lines.append("")

    # 每日计划
    lines.append(f"## 🗓️ 每日规划\n")
    for day in plan["day_plans"]:
        day_num = day["day"]
        date_str = day["date"]
        area = day["knowledge_area"]
        questions = day["suggested_questions"]
        minutes = day["suggested_time_minutes"]
        completed = "✅" if day.get("completed") else "⬜"
        first_day = " 🆕 新领域" if day.get("is_day_1_of_area") else ""

        # 中文星期
        weekday = _get_weekday(date_str)

        lines.append(f"### {completed} 第 {day_num} 天 · {date_str} {weekday} · {area}{first_day}")
        lines.append("")
        lines.append(f"| 项目 | 内容 |")
        lines.append(f"|------|------|")
        lines.append(f"| 📖 知识域 | **{area}** |")
        lines.append(f"| ❓ 建议做题 | {questions} 道 |")
        lines.append(f"| ⏱️ 建议时间 | {minutes} 分钟 ({_format_duration(minutes)}) |")
        lines.append(f"| 🔍 检索 | `{day.get('search_query', '')}` |")
        lines.append("")

        # 复习指南
        lines.append("**📝 复习指南：**")
        lines.append(f"- 1. 先复习 {area} 相关讲义和笔记（搜索：`{day.get('search_query', '')}`）")
        lines.append(f"- 2. 完成 {questions} 道练习题")
        lines.append(f"- 3. 记录错题，在微信里说「选错了」")

        lines.append("")

    # 完成规则
    lines.append("## ⚡ 每日打卡\n")
    lines.append("完成后在微信里说 `打卡第N天`，我会自动标记完成。\n")
    lines.append("或使用命令：")
    lines.append("```bash")
    lines.append("python pmp_athena/sprint_planner.py done <天数>")
    lines.append("```")

    return "\n".join(lines)


def format_today_markdown(data: dict) -> str:
    """格式化今日任务"""
    if data.get("status") == "not_started":
        return f"📅 冲刺计划尚未开始，首日为 {data['starts_on']}"

    if data.get("status") == "ended":
        return f"📅 冲刺计划已于 {data['ended_on']} 结束。用 `冲刺计划 N天` 生成新的。"

    if data.get("status") == "no_active_plan":
        return "📭 没有活跃的冲刺计划。用 `冲刺计划 7天` 生成一个。"

    lines = []
    today = data.get("today") or {}
    if not today:
        return "📭 今天不在冲刺计划中，可以休息或自由复习。"

    completed = "✅" if today.get("completed") else "⬜"
    area = today["knowledge_area"]
    questions = today["suggested_questions"]
    minutes = today["suggested_time_minutes"]
    date_str = today["date"]
    weekday = _get_weekday(date_str)
    search = today.get("search_query", "")

    lines.append(f"## {completed} 今日冲刺 · {date_str} {weekday}")
    lines.append(f"📊 整体进度：{data.get('plan_progress', '?')} 天")
    lines.append("")
    lines.append(f"| 项目 | 内容 |")
    lines.append(f"|------|------|")
    lines.append(f"| 📖 知识域 | **{area}** |")
    lines.append(f"| ❓ 建议做题 | {questions} 道 |")
    lines.append(f"| ⏱️ 建议时间 | {minutes} 分钟 ({_format_duration(minutes)}) |")
    lines.append("")

    if search:
        lines.append(f"🔍 相关笔记搜索：`python -m pmp_athena.cli` 后输入 `{search}`")

    return "\n".join(lines)


def format_progress_markdown(progress: dict) -> str:
    """格式化冲刺进度"""
    if progress.get("status") == "no_active_plan":
        return "📭 没有活跃的冲刺计划。"

    lines = []
    lines.append("╔══════════════════════════════════════╗")
    lines.append("║   🏃 PMP 冲刺进度                    ║")
    lines.append("╚══════════════════════════════════════╝")
    lines.append("")
    lines.append(f"📅 {progress['start_date']} ～ {progress['end_date']}（共 {progress['days']} 天）")

    # 进度条
    pct = progress["progress_pct"]
    bar_len = 20
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    lines.append(f"📊 [{bar}] {pct}% （{progress['completed']}/{progress['total']}）")
    lines.append("")

    # 每日状态
    lines.append("| 天数 | 日期 | 领域 | 状态 |")
    lines.append("|------|------|------|------|")
    for day in progress["day_plans"]:
        status = "✅" if day.get("completed") else "⬜"
        lines.append(
            f"| {status} 第{day['day']}天 | {day['date']} "
            f"| {day['knowledge_area']} | 待完成 |" if not day.get("completed")
            else f"| {status} 第{day['day']}天 | {day['date']} "
            f"| {day['knowledge_area']} | 已完成 |"
        )

    lines.append("")
    today_info = progress.get("today")
    if today_info and today_info.get("today"):
        lines.append(f"🎯 今日任务：{today_info['today']['knowledge_area']}")

    return "\n".join(lines)


def _get_weekday(date_str: str) -> str:
    try:
        days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        dt = date.fromisoformat(date_str)
        return days[dt.weekday()]
    except Exception:
        return ""


def _format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}分钟"
    h = minutes // 60
    m = minutes % 60
    if m == 0:
        return f"{h}小时"
    return f"{h}小时{m}分钟"


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="PMP 冲刺计划生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # plan
    p_plan = sub.add_parser("plan", help="生成冲刺计划")
    p_plan.add_argument("days", nargs="?", type=int, default=7, help="天数（默认 7）")
    p_plan.add_argument("--start", type=str, help="开始日期 YYYY-MM-DD（默认明天）")

    # today
    sub.add_parser("today", help="今日冲刺任务")

    # progress
    sub.add_parser("progress", help="冲刺进度")

    # done
    p_done = sub.add_parser("done", help="标记某天完成")
    p_done.add_argument("day", type=int, help="第几天")

    # list
    sub.add_parser("list", help="列出所有冲刺计划")

    args = parser.parse_args()
    sp = SprintPlanner()

    if args.command == "plan":
        plan = sp.generate(days=args.days, start_date=args.start)
        print(format_plan_markdown(plan))

    elif args.command == "today":
        tasks = sp.get_today_tasks()
        print(format_today_markdown(tasks or {}))

    elif args.command == "progress":
        progress = sp.get_progress()
        print(format_progress_markdown(progress))

    elif args.command == "done":
        ok = sp.mark_done(args.day)
        if ok:
            print(f"✅ 第 {args.day} 天已标记完成！")
        else:
            print(f"❌ 标记失败，请检查天数是否正确。")

    elif args.command == "list":
        plans = sp._read_plans()
        if not plans:
            print("📭 暂无冲刺计划")
        else:
            print(f"📋 共 {len(plans)} 个冲刺计划\n")
            for p in sorted(plans, key=lambda x: x.get("created_at", ""), reverse=True):
                status_icon = {"active": "🟢", "completed": "✅", "abandoned": "⚫"}.get(
                    p.get("status", ""), "⬜"
                )
                completed = sum(1 for d in p["day_plans"] if d.get("completed"))
                total = len(p["day_plans"])
                print(
                    f"{status_icon} {p['id']}  "
                    f"{p['days']}天  "
                    f"{p.get('start_date', '?')}～{p.get('end_date', '?')}  "
                    f"进度 {completed}/{total}  "
                    f"{p.get('status', '')}"
                )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
