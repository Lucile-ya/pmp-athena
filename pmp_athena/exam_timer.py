#!/usr/bin/env python3
"""
考试倒计时 & 阶段管理

功能：
- 考试日期存储（JSON）
- 倒计时（天数、周数）
- 备考阶段自动分段（基础 / 强化 / 冲刺）
- 关键节点提醒（考前 30 / 14 / 7 天）
- 冲刺计划天数自动推荐

用法:
    python pmp_athena/exam_timer.py countdown        # 查看倒计时
    python pmp_athena/exam_timer.py set 2026-09-12   # 设置考试日期
    python pmp_athena/exam_timer.py stage             # 当前备考阶段
    python pmp_athena/exam_timer.py milestones        # 关键节点
    python pmp_athena/exam_timer.py recommend-sprint   # 推荐冲刺天数
"""

try:
    from pmp_athena.config import EXAM_CONFIG_PATH
except ModuleNotFoundError:
    from config import EXAM_CONFIG_PATH

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("exam_timer")

# ── 存储路径 ─────────────────────────────────────────────
STORE_PATH = EXAM_CONFIG_PATH

# ── 阶段划分规则 ─────────────────────────────────────────
# 距离考试 N 天以上 → 对应阶段
PHASE_RULES = [
    (60, "基础期",   "系统学习全部知识领域，构建知识框架"),
    (21, "强化期",   "重点攻克薄弱领域，大量刷题 + 错题整理"),
    (7,  "冲刺期",   "全真模考 + 高频错题复习 + 考前记忆"),
    (0,  "临考期",   "调整状态，回顾核心公式和易错点"),
]

# ── 里程碑提醒节点（考前 N 天）──────────────────────────
MILESTONE_DAYS = [90, 60, 30, 14, 7, 3, 1]

MILESTONE_MESSAGES = {
    90: "📅 距考试还有 3 个月——基础期应该过半了，检查进度！",
    60: "📅 距考试还有 2 个月——应该进入强化期了，开始大量刷题！",
    30: "🚨 距考试仅剩 30 天！进入冲刺阶段，每天至少 2 小时！",
    14: "⚠️ 距考试仅剩 2 周！全真模考 + 错题优先！",
    7:  "🔴 距考试仅剩 7 天！停止学新知识，专注错题和公式记忆！",
    3:  "🔥 距考试仅剩 3 天！调整作息，回顾核心概念和易错题！",
    1:  "⚡ 明天考试！今天只看错题本和公式卡片，早点休息！",
}


class ExamTimer:
    """考试倒计时管理器"""

    def __init__(self, store_path: Path | None = None):
        self.store_path = store_path or STORE_PATH
        self._ensure_file()

    def _ensure_file(self):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self.store_path.write_text(
                json.dumps({"exam_date": None, "created_at": datetime.now().isoformat()},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # ── 读写 ──────────────────────────────────────────────

    def _read(self) -> dict:
        try:
            return json.loads(self.store_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {"exam_date": None}

    def _write(self, data: dict):
        self.store_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── 考试日期 ──────────────────────────────────────────

    def set_date(self, date_str: str) -> date:
        """设置考试日期"""
        try:
            exam_date = date.fromisoformat(date_str)
        except (ValueError, TypeError):
            # 尝试常见格式
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y年%m月%d日"]:
                try:
                    exam_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"无法解析日期: {date_str}，请使用 YYYY-MM-DD 格式")

        today = date.today()
        if exam_date <= today:
            raise ValueError(f"考试日期必须在未来，今天已经是 {today} 了")

        data = self._read()
        data["exam_date"] = exam_date.isoformat()
        data["updated_at"] = datetime.now().isoformat()
        self._write(data)

        logger.info("Exam date set: %s", exam_date)
        return exam_date

    def get_date(self) -> date | None:
        """获取考试日期"""
        data = self._read()
        raw = data.get("exam_date")
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except (ValueError, TypeError):
            return None

    # ── 倒计时 ────────────────────────────────────────────

    def countdown(self) -> dict:
        """
        返回倒计时详情。

        Returns:
            {
                "exam_date": "2026-09-12",
                "days_remaining": int,
                "weeks_remaining": float,
                "phase": str,
                "phase_description": str,
                "milestone_hit": list[str],   # 命中的里程碑消息
                "today": "2026-07-15",
                "status": "active" | "past" | "not_set",
            }
        """
        exam_date = self.get_date()
        today = date.today()

        if exam_date is None:
            return {
                "exam_date": None,
                "days_remaining": None,
                "weeks_remaining": None,
                "phase": None,
                "phase_description": "请先设置考试日期：考试日期 2026-09-12",
                "milestone_hit": [],
                "today": today.isoformat(),
                "status": "not_set",
            }

        days = (exam_date - today).days

        if days < 0:
            return {
                "exam_date": exam_date.isoformat(),
                "days_remaining": abs(days),
                "weeks_remaining": 0,
                "phase": "已考完",
                "phase_description": f"考试已过去 {abs(days)} 天，祝好成绩！",
                "milestone_hit": [],
                "today": today.isoformat(),
                "status": "past",
            }

        # 阶段判断
        phase = PHASE_RULES[-1]
        for threshold, name, desc in PHASE_RULES:
            if days >= threshold:
                phase = (name, desc)
                break

        # 里程碑
        milestones = []
        for milestone_day in MILESTONE_DAYS:
            if days == milestone_day:
                milestones.append(MILESTONE_MESSAGES.get(milestone_day, ""))
            elif days <= milestone_day:
                # 找最近的下一个里程碑（今天之后）
                pass

        # 下一个里程碑（如果今天不命中）
        next_milestone = None
        if not any(days == m for m in MILESTONE_DAYS):
            for m in sorted(MILESTONE_DAYS):
                if days > m:
                    next_milestone = {
                        "day": m,
                        "in_days": days - m,
                        "message": MILESTONE_MESSAGES.get(m, ""),
                    }
                    break

        return {
            "exam_date": exam_date.isoformat(),
            "days_remaining": days,
            "weeks_remaining": round(days / 7, 1),
            "phase": phase[0],
            "phase_description": phase[1],
            "milestone_hit": milestones,
            "next_milestone": next_milestone,
            "today": today.isoformat(),
            "status": "active",
        }

    def get_phase(self) -> str | None:
        """返回当前备考阶段名称"""
        cd = self.countdown()
        return cd.get("phase")

    def get_milestones(self) -> list[dict]:
        """返回所有关键节点"""
        exam_date = self.get_date()
        if not exam_date:
            return []

        today = date.today()
        results = []
        for m in sorted(MILESTONE_DAYS, reverse=True):
            milestone_date = exam_date - timedelta(days=m)
            if milestone_date >= today:
                results.append({
                    "days_before": m,
                    "date": milestone_date.isoformat(),
                    "days_from_now": (milestone_date - today).days,
                    "message": MILESTONE_MESSAGES.get(m, ""),
                    "passed": False,
                })
            else:
                results.append({
                    "days_before": m,
                    "date": milestone_date.isoformat(),
                    "days_from_now": (today - milestone_date).days,
                    "message": MILESTONE_MESSAGES.get(m, ""),
                    "passed": True,
                })

        return results

    def recommend_sprint_days(self) -> int:
        """
        根据剩余天数推荐冲刺计划天数。

        - 剩余 >= 60 天 → 建议 14 天/轮，分多轮
        - 剩余 30-59 天 → 建议 10 天
        - 剩余 14-29 天 → 建议 7 天
        - 剩余 7-13 天 → 建议剩余天数
        - 剩余 < 7 天 → 建议剩余天数
        """
        cd = self.countdown()
        days = cd.get("days_remaining")
        if days is None:
            return 7
        if days >= 90:
            return 14
        elif days >= 60:
            return 14
        elif days >= 30:
            return 10
        elif days >= 14:
            return 7
        else:
            return max(1, days)

    def generate_phase_advice(self) -> str:
        """根据当前阶段生成备考建议"""
        cd = self.countdown()
        phase = cd.get("phase", "")
        days = cd.get("days_remaining", 0)

        advice = {
            "基础期": (
                "📚 基础期策略\n\n"
                f"- 每天学习 2-3 小时，系统覆盖 PMBOK 7 所有领域\n"
                f"- 每周完成 1 个知识领域的深度学习\n"
                f"- 建议每日刷题量：20-30 道\n"
                f"- 重点：理解概念 × 建立知识框架 × 做笔记\n"
                f"- 推荐冲刺天数：{self.recommend_sprint_days()} 天/轮"
            ),
            "强化期": (
                "💪 强化期策略\n\n"
                f"- 每天学习 2-3 小时，聚焦薄弱领域\n"
                f"- 大量刷题：每天 40-60 道\n"
                f"- 每道错题必须理解解析，记录到错题本\n"
                f"- 每周 2 次间隔复习错题\n"
                f"- 推荐冲刺天数：{self.recommend_sprint_days()} 天"
            ),
            "冲刺期": (
                "🚀 冲刺期策略\n\n"
                f"- 每天学习 3-4 小时\n"
                f"- 全真模考每周 2-3 次\n"
                f"- 错题复习优先于学新知识\n"
                f"- 每天回顾核心公式（EVM / CPM / 沟通渠道）\n"
                f"- 推荐冲刺天数：{self.recommend_sprint_days()} 天"
            ),
            "临考期": (
                "🔥 临考期策略\n\n"
                f"- 每天学习 1-2 小时，不要过度\n"
                f"- 只看错题本 + 核心公式卡片\n"
                f"- 调整作息，保证睡眠\n"
                f"- 准备考试用品（证件、计算器等）\n"
                f"- 不需要冲刺计划了，放松心态！"
            ),
        }

        return advice.get(phase, f"📅 距考试还有 {days} 天，加油！")

    def get_context_for_claude(self) -> str:
        """
        生成注入 Claude 系统提示词的倒计时上下文。
        每次对话开始时自动提醒 Claude 当前时间压力。
        """
        cd = self.countdown()

        if cd["status"] == "not_set":
            return ""
        if cd["status"] == "past":
            return ""

        lines = [
            f"\n[系统] 当前距 PMP 考试还有 **{cd['days_remaining']} 天** "
            f"（{cd['weeks_remaining']} 周）。",
            f"当前阶段：**{cd['phase']}** — {cd['phase_description']}",
        ]

        if cd.get("milestone_hit"):
            for m in cd["milestone_hit"]:
                lines.append(f"⚠️ 里程碑提醒：{m}")

        if cd.get("next_milestone"):
            nm = cd["next_milestone"]
            lines.append(
                f"下一个关键节点：**考前 {nm['day']} 天**"
                f"（{nm['in_days']} 天后）"
            )

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# Markdown 输出
# ═══════════════════════════════════════════════════════════

def format_countdown(cd: dict) -> str:
    """格式化倒计时 Markdown"""
    lines = []

    if cd["status"] == "not_set":
        lines.append("📅 尚未设置考试日期。")
        lines.append("")
        lines.append("在微信里发送 `考试日期 2026-09-12` 来设置。")
        return "\n".join(lines)

    if cd["status"] == "past":
        lines.append(f"🎉 考试已于 {cd['exam_date']} 结束！")
        lines.append(f"已过去 {cd['days_remaining']} 天。")
        return "\n".join(lines)

    lines.append("╔══════════════════════════════════════╗")
    lines.append("║   📅 PMP 考试倒计时                  ║")
    lines.append("╚══════════════════════════════════════╝")
    lines.append("")

    days = cd["days_remaining"]
    weeks = cd["weeks_remaining"]

    # 紧张度指示器
    if days > 60:
        emoji = "🟢"
    elif days > 30:
        emoji = "🟡"
    elif days > 14:
        emoji = "🟠"
    elif days > 7:
        emoji = "🔴"
    else:
        emoji = "🔥"

    lines.append(f"{emoji} 考试日期：**{cd['exam_date']}**")
    lines.append(f"📆 距今天：**{days} 天**（约 {weeks} 周）")

    # 进度条
    total_days = max(days + 90, 180)  # 估算总备考天数
    progress_pct = min(100, max(0, round((total_days - days) / total_days * 100)))
    bar_len = 20
    filled = int(bar_len * progress_pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    lines.append(f"📊 备考进度：[{bar}] {progress_pct}%")

    lines.append("")
    lines.append(f"## 📖 当前阶段：{cd['phase']}")
    lines.append(f"> {cd['phase_description']}")
    lines.append("")

    # 关键节点
    timer = ExamTimer()
    milestones = timer.get_milestones()
    upcoming = [m for m in milestones if not m["passed"]]
    passed = [m for m in milestones if m["passed"]]

    if upcoming:
        lines.append("### 📌 即将到来的关键节点\n")
        lines.append("| 节点 | 日期 | 距离 | 提醒 |")
        lines.append("|------|------|------|------|")
        for m in upcoming[:5]:
            msg = m["message"].split("—")[0] if "—" in m["message"] else m["message"][:30]
            lines.append(f"| 考前 {m['days_before']} 天 | {m['date']} | {m['days_from_now']} 天后 | {msg} |")

    if cd.get("milestone_hit"):
        lines.append("")
        lines.append("### ⚠️ 今天命中里程碑\n")
        for m in cd["milestone_hit"]:
            lines.append(f"> {m}")

    lines.append("")
    lines.append(timer.generate_phase_advice())

    return "\n".join(lines)


def format_stage(stage: str) -> str:
    """格式化当前阶段"""
    timer = ExamTimer()
    return timer.generate_phase_advice()


def format_milestones(milestones: list[dict]) -> str:
    """格式化关键节点列表"""
    if not milestones:
        return "📅 请先设置考试日期。"

    lines = ["## 📌 考试关键节点\n"]
    lines.append("| 节点 | 日期 | 状态 | 提醒 |")
    lines.append("|------|------|------|------|")
    for m in milestones:
        status = "✅ 已过" if m["passed"] else f"⏳ {m['days_from_now']}天后"
        msg_short = m["message"].split("！")[0] if "！" in m["message"] else m["message"][:30]
        lines.append(f"| 考前 {m['days_before']} 天 | {m['date']} | {status} | {msg_short} |")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="PMP 考试倒计时 & 阶段管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # countdown
    sub.add_parser("countdown", help="查看倒计时")

    # set
    p_set = sub.add_parser("set", help="设置考试日期")
    p_set.add_argument("date", type=str, help="考试日期 YYYY-MM-DD")

    # stage
    sub.add_parser("stage", help="当前备考阶段 + 策略建议")

    # milestones
    sub.add_parser("milestones", help="查看所有关键节点")

    # recommend-sprint
    sub.add_parser("recommend-sprint", help="推荐冲刺计划天数")

    # context — 输出给 Claude 的上下文片段
    sub.add_parser("context", help="输出 Claude 上下文片段（程序调用）")

    args = parser.parse_args()
    timer = ExamTimer()

    if args.command == "countdown":
        cd = timer.countdown()
        print(format_countdown(cd))

    elif args.command == "set":
        try:
            exam_date = timer.set_date(args.date)
            print(f"✅ 考试日期已设置为 {exam_date}")
            cd = timer.countdown()
            print(f"📆 距考试还有 {cd['days_remaining']} 天")
            print(f"📖 当前阶段：{cd['phase']} — {cd['phase_description']}")
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(1)

    elif args.command == "stage":
        phase = timer.get_phase()
        if phase:
            print(timer.generate_phase_advice())
        else:
            print("请先设置考试日期。")

    elif args.command == "milestones":
        milestones = timer.get_milestones()
        print(format_milestones(milestones))

    elif args.command == "recommend-sprint":
        days = timer.recommend_sprint_days()
        print(f"📋 推荐冲刺天数：{days} 天")
        cd = timer.countdown()
        print(f"   剩余 {cd['days_remaining']} 天，阶段：{cd['phase']}")

    elif args.command == "context":
        ctx = timer.get_context_for_claude()
        if ctx:
            print(ctx)

    else:
        # 默认显示倒计时
        cd = timer.countdown()
        print(format_countdown(cd))


if __name__ == "__main__":
    main()
