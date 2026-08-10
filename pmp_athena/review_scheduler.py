#!/usr/bin/env python3
"""
智能复习排期引擎 — 错题分层 + 每日限量 + 进度预估 + 考前清零。

分层规则:
  Tier 1 (高频错题): 错 >=3 次 → 每天推送，不限量
  Tier 2 (近期错题): 7 天内录入 → 每天 5-10 道
  Tier 3 (低频错题): 错 1-2 次且 >30 天 → 归入考前冲刺包
  Tier 0 (粗心错题): 标记为粗心 → 不计入队列，仅记录

每日上限: 默认 25 道 / 天
考前清零: 考前 7 天每天推送剩余 20%, 最低 10 最高 40
"""

from __future__ import annotations
try:
    from pmp_athena.config import ERROR_LOG_PATH, QUESTION_BANK_PATH, REVIEW_CONFIG_PATH, REVIEW_STATE_PATH
except ModuleNotFoundError:
    from config import ERROR_LOG_PATH, QUESTION_BANK_PATH, REVIEW_CONFIG_PATH, REVIEW_STATE_PATH


import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any


CONFIG_PATH = REVIEW_CONFIG_PATH

EXAM_DATE = date(2026, 9, 12)
DEFAULT_DAILY_LIMIT = 25
TIER2_DAILY_LIMIT = 10
PRE_EXAM_DAYS = 7
PRE_EXAM_30_DAYS = 30
PRE_EXAM_MIN = 10
PRE_EXAM_MAX = 40
PRE_EXAM_RATIO = 0.20


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {} if path.name.startswith("error_review") or path.name.startswith("review_config") else []


def _save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class ErrorTier:
    """错题分层信息"""
    error_id: int
    tier: int           # 0=粗心 1=高频 2=近期 3=低频
    label: str          # 展示标签
    mistake_count: int
    days_since_last: int
    is_careless: bool = False
    priority_score: float = 0.0  # 排队优先级（越大越靠前）


class ReviewScheduler:
    """智能复习排期器"""

    def __init__(self) -> None:
        self.review_state = _load(REVIEW_STATE_PATH)
        if not isinstance(self.review_state, dict):
            self.review_state = {}
        self.errors = _load(ERROR_LOG_PATH)
        if not isinstance(self.errors, list):
            self.errors = []
        self.bank = _load(QUESTION_BANK_PATH)
        if not isinstance(self.bank, list):
            self.bank = []
        self.config = _load(CONFIG_PATH)
        if not isinstance(self.config, dict):
            self.config = {}
        self.today = date.today()
        self.today_str = self.today.isoformat()

    # ── 错题分层 ──────────────────────────────────────────────

    def _count_mistakes(self, error_id: int) -> int:
        """统计某道错题在题库中的错误次数。"""
        return sum(
            1 for r in self.bank
            if r.get("error_log_id") == error_id and r.get("is_correct") is False
        )

    def _days_since_last_error(self, error_id: int) -> int:
        """距最后一次错误的间隔天数。"""
        records = [
            r for r in self.bank
            if r.get("error_log_id") == error_id and r.get("is_correct") is False
        ]
        if not records:
            return 999
        last_date = max(r.get("date", "2000-01-01") for r in records)
        try:
            return (self.today - date.fromisoformat(last_date)).days
        except (ValueError, TypeError):
            return 999

    def _is_careless(self, error_id: int) -> bool:
        """判断是否为粗心错题（review state 中有标记）。"""
        card = self.review_state.get(str(error_id), {})
        return card.get("careless", False)

    def _mark_careless(self, error_id: int) -> None:
        card = self.review_state.setdefault(str(error_id), {})
        card["careless"] = True
        _save(REVIEW_STATE_PATH, self.review_state)

    def classify(self, error_id: int) -> ErrorTier:
        """对单道错题分层。"""
        mistake_count = self._count_mistakes(error_id)
        days_since = self._days_since_last_error(error_id)
        is_careless = self._is_careless(error_id)

        if is_careless:
            return ErrorTier(error_id, 0, "粗心", mistake_count, days_since, True, 0.0)

        if mistake_count >= 3:
            priority = 100.0 + mistake_count
            return ErrorTier(error_id, 1, "高频错题", mistake_count, days_since, False, priority)

        if days_since <= 7:
            priority = 50.0 + mistake_count - days_since * 0.5
            return ErrorTier(error_id, 2, "近期错题", mistake_count, days_since, False, priority)

        priority = 10.0 - days_since * 0.01
        return ErrorTier(error_id, 3, "低频错题", mistake_count, days_since, False, max(priority, 0))

    def classify_all(self) -> dict[str, list[ErrorTier]]:
        """对所有在库错题分层。"""
        tiers: dict[str, list[ErrorTier]] = {"T1": [], "T2": [], "T3": [], "T0": []}
        seen: set[int] = set()
        for r in self.bank:
            eid = r.get("error_log_id")
            if eid is None or eid in seen:
                continue
            seen.add(eid)
            tier = self.classify(eid)
            tiers[f"T{tier.tier}"].append(tier)

        # 各层按优先级排序
        for t in ("T1", "T2", "T3"):
            tiers[t].sort(key=lambda x: -x.priority_score)
        return tiers

    # ── 每日复习计划 ──────────────────────────────────────────

    def get_daily_limit(self) -> int:
        return self.config.get("daily_limit", DEFAULT_DAILY_LIMIT)

    def set_daily_limit(self, n: int) -> None:
        self.config["daily_limit"] = n
        _save(CONFIG_PATH, self.config)

    def get_today_completed_count(self) -> int:
        """今日已完成复习的错题数（有 quality>0 记录）。"""
        return sum(
            1 for _key, card in self.review_state.items()
            if any(
                h.get("date") == self.today_str and h.get("quality", 0) > 0
                for h in card.get("history", [])
            )
        )

    def get_total_errors(self) -> int:
        """错题总数（Tier 1+2+3，不含粗心）。"""
        tiers = self.classify_all()
        return len(tiers["T1"]) + len(tiers["T2"]) + len(tiers["T3"])

    def get_completed_total(self) -> int:
        """已完成总数（interval >= 21 或最近 quality >= 4）。"""
        count = 0
        today = self.today_str
        for key, card in self.review_state.items():
            if int(key) in [t.error_id for t in self.classify_all()["T0"]]:
                continue
            interval = card.get("interval", 0)
            last_q = card.get("last_quality")
            has_recent_quality = any(
                h.get("date") == today and h.get("quality", 5) >= 4
                for h in card.get("history", [])
            )
            if interval >= 21 or has_recent_quality:
                count += 1
        return count

    def build_daily_plan(self, is_pre_exam: bool = False, is_pre30: bool = False) -> dict:
        """
        构建每日错题推送计划。

        Returns:
            {
                "questions": [error_id, ...],  # 今日应推送的错题 ID 列表
                "tiers": { "T1": N, "T2": N, "T3": N },
                "total": int,
                "limit": int,
                "remaining": int,          # 尚未清理的错题总数
                "completed_today": int,     # 今日已完成
                "completion_pct": float,    # 整体完成百分比
                "expected_days": int,       # 预计全部清完所需天数
                "estimated_done_date": str, # 预计完成日期
                "is_pre_exam": bool,
                "is_pre30": bool,
                "daily_quota": int,         # 考前清零模式每天配额
            }
        """
        tiers = self.classify_all()
        limit = self.get_daily_limit()
        daily_quota = limit

        # 考前清零模式
        if is_pre_exam:
            remaining = self.get_total_errors() - self.get_completed_total()
            daily_quota = max(PRE_EXAM_MIN, min(PRE_EXAM_MAX, int(remaining * PRE_EXAM_RATIO)))

        completed_today = self.get_today_completed_count()
        question_ids: list[int] = []

        if is_pre_exam:
            # 考前模式：全部排队，按优先级
            all_candidates = tiers["T1"] + tiers["T2"] + tiers["T3"]
            all_candidates.sort(key=lambda x: -x.priority_score)
        elif is_pre30:
            # 30天模式：T1 + T2，完全排除 T3
            t1_ids = [t.error_id for t in tiers["T1"]]
            t2_ids = [t.error_id for t in tiers["T2"][:TIER2_DAILY_LIMIT]]

            t1_filtered = [eid for eid in t1_ids
                           if not self._already_reviewed_today(int(eid))]
            t2_filtered = [eid for eid in t2_ids
                           if not self._already_reviewed_today(int(eid))
                           and eid not in t1_filtered]

            question_ids = t1_filtered + t2_filtered
            question_ids = question_ids[:limit]
            # T3 延期至考前7天，不计入今日推送
            tiers["T3"] = []  # 标记 T3 为 0（延期）
        else:
            # 正常模式：T1 不限量 + T2 限量 + T3 跳过
            t1_ids = [t.error_id for t in tiers["T1"]]
            t2_ids = [t.error_id for t in tiers["T2"][:TIER2_DAILY_LIMIT]]

            # 去重 + 过滤今日已复习
            t1_filtered = [eid for eid in t1_ids
                           if not self._already_reviewed_today(int(eid))]
            t2_filtered = [eid for eid in t2_ids
                           if not self._already_reviewed_today(int(eid))
                           and eid not in t1_filtered]

            question_ids = t1_filtered + t2_filtered
            question_ids = question_ids[:limit]

        remaining = self.get_total_errors() - completed_today
        if remaining < 0:
            remaining = 0

        # 计算预计完成天数
        speed = max(1, completed_today)  # 今天的完成速度
        expected_days = max(1, int(remaining / speed)) if speed > 0 else remaining

        return {
            "questions": question_ids,
            "tiers": {
                "T1": len([t for t in tiers["T1"] if not self._already_reviewed_today(t.error_id)]),
                "T2": len([t for t in tiers["T2"] if not self._already_reviewed_today(t.error_id)]),
                "T3": len(tiers["T3"]),
            },
            "total": len(question_ids),
            "limit": limit,
            "remaining": remaining,
            "completed_today": completed_today,
            "completion_pct": round(
                self.get_completed_total() / max(1, self.get_total_errors()) * 100, 1
            ),
            "expected_days": expected_days,
            "estimated_done_date": (self.today + timedelta(days=expected_days)).isoformat(),
            "is_pre_exam": is_pre_exam,
            "is_pre30": is_pre30,
            "daily_quota": daily_quota,
        }

    def _already_reviewed_today(self, error_id: int) -> bool:
        card = self.review_state.get(str(error_id), {})
        return any(
            h.get("date") == self.today_str and h.get("quality", 0) > 0
            for h in card.get("history", [])
        )

    # ── 进度摘要 ──────────────────────────────────────────────

    def get_progress_summary(self) -> dict:
        total = self.get_total_errors()
        completed = self.get_completed_total()
        pct = round(completed / max(1, total) * 100, 1)
        completed_today = self.get_today_completed_count()
        limit = self.get_daily_limit()

        return {
            "total": total,
            "completed": completed,
            "completion_pct": pct,
            "completed_today": completed_today,
            "daily_limit": limit,
        }

    def format_progress_bar(self) -> str:
        """进度条 + 预估完成日期。"""
        p = self.get_progress_summary()
        is_pre_exam = self.should_activate_sprint()
        is_pre30 = self.should_activate_pre30()
        plan = self.build_daily_plan(is_pre_exam=is_pre_exam, is_pre30=is_pre30)
        bar_width = 20
        filled = int(bar_width * p["completion_pct"] / 100)
        bar = "█" * filled + "░" * (bar_width - filled)

        days_left = self.days_to_exam()
        is_pre_exam = days_left <= PRE_EXAM_DAYS
        is_pre30 = PRE_EXAM_DAYS < days_left <= PRE_EXAM_30_DAYS

        lines = [
            f"📊 错题清理进度：{p['completed']}/{p['total']}（{p['completion_pct']}%）",
            f"   [{bar}]",
        ]
        if is_pre30:
            lines.append(f"⚡ 30天冲刺模式 · T1+T2优先 · T3延期至考前7天")
        if is_pre_exam:
            lines.append(f"🔥 考前冲刺模式 · 日均配额 {plan['daily_quota']} 题")
        if plan["remaining"] > 0:
            lines.append(f"📅 预计全部清完：{plan['estimated_done_date']}（{plan['expected_days']} 天）")
            if plan["expected_days"] > 3:
                lines.append(f"💡 每天再刷 {plan['limit']} 题，{plan['expected_days']} 天即可清零")
        else:
            lines.append("🏆 错题已清零！")
        return "\n".join(lines)

    def format_daily_done_card(self) -> str:
        """每日复习完成卡片。"""
        p = self.get_progress_summary()
        is_pre_exam = self.should_activate_sprint()
        is_pre30 = self.should_activate_pre30()
        plan = self.build_daily_plan(is_pre_exam=is_pre_exam, is_pre30=is_pre30)
        lines = []
        if plan["total"] > 0 and plan["remaining"] > 0:
            lines.append(
                f"✅ 今日错题复习完成！已刷 {p['completed_today']}/{p['total'] + p['completed_today']} 道"
            )
            if plan["expected_days"] > 0:
                lines.append(f"📊 预计剩余错题将在 {plan['expected_days']} 天内全部清完")
        else:
            lines.append("✅ 今日错题复习完成！")
        lines.append(f"💬 回复「继续加练」可突破每日上限")
        return "\n".join(lines)

    # ── 考前清零计划 ──────────────────────────────────────────

    def days_to_exam(self) -> int:
        """距考试的天数。"""
        return (EXAM_DATE - self.today).days

    def should_activate_sprint(self) -> bool:
        return self.days_to_exam() <= PRE_EXAM_DAYS

    def should_activate_pre30(self) -> bool:
        """D ≤ 30 但 > 7：进入30天冲刺模式。"""
        d = self.days_to_exam()
        return PRE_EXAM_DAYS < d <= PRE_EXAM_30_DAYS

    def build_sprint_plan(self) -> dict:
        """
        考前 7 天清零计划：每天推送剩余 20%（最低 10，最高 40）。
        确保考前 3 天所有错题至少过一遍。
        """
        days_left = max(1, (EXAM_DATE - self.today).days)
        remaining = max(0, self.get_total_errors() - self.get_completed_total())
        daily_quota = max(PRE_EXAM_MIN, min(PRE_EXAM_MAX, int(remaining * PRE_EXAM_RATIO)))

        # 按日期分配
        schedule: list[dict] = []
        remaining_after = remaining
        for d in range(days_left):
            day_date = self.today + timedelta(days=d)
            target = min(daily_quota, remaining_after)
            schedule.append({
                "date": day_date.isoformat(),
                "target": target,
                "remaining_before": remaining_after,
            })
            remaining_after = max(0, remaining_after - target)

        will_clear = remaining_after <= 0 and remaining > 0

        return {
            "days_left": days_left,
            "total_remaining": remaining,
            "daily_quota": daily_quota,
            "will_clear_before_exam": will_clear,
            "clear_before_days": (EXAM_DATE - self.today).days - (
                remaining // daily_quota if daily_quota > 0 else 0
            ) if daily_quota > 0 else 0,
            "schedule": schedule,
        }

    def format_sprint_plan(self) -> str:
        """考前清零计划格式化。"""
        sp = self.build_sprint_plan()
        lines = [
            "🔥 考前错题清零计划",
            "══════════════════════════",
            "",
            f"📅 距考试 {sp['days_left']} 天",
            f"📊 待清零错题：{sp['total_remaining']} 道",
            f"📋 每日配额：{sp['daily_quota']} 题（最低 {PRE_EXAM_MIN}，最高 {PRE_EXAM_MAX}）",
            "",
        ]
        if sp["will_clear_before_exam"]:
            lines.append(f"✅ 按此节奏可在考前 3 天内全部清完")
        elif sp["total_remaining"] == 0:
            lines.append("🏆 错题已清零！保持手感即可。")
        else:
            lines.append(f"⚠️ 按当前速度考前可能清不完，建议提升每日刷题量")
        lines.append("")
        lines.append(f"💡 回复「复习错题」开始今日清零 | 「继续加练」突破上限")
        return "\n".join(lines)

    # ── 粗心标记 ──────────────────────────────────────────────

    def mark_as_careless(self, error_id: int) -> bool:
        """标记为粗心错题 → 移出复习队列。"""
        self._mark_careless(error_id)
        return True

    def is_careless(self, error_id: int) -> bool:
        return self._is_careless(error_id)


# ── 快捷函数 ──────────────────────────────────────────────────────────

_scheduler: ReviewScheduler | None = None


def _get_scheduler() -> ReviewScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = ReviewScheduler()
    return _scheduler


def get_daily_plan(is_pre_exam: bool | None = None) -> dict:
    """获取今日推送计划。自动判断考前模式。"""
    s = _get_scheduler()
    if is_pre_exam is None:
        is_pre_exam = s.should_activate_sprint()
    return s.build_daily_plan(is_pre_exam=is_pre_exam)


def get_progress() -> dict:
    return _get_scheduler().get_progress_summary()


def format_progress() -> str:
    return _get_scheduler().format_progress_bar()


def format_sprint_plan() -> str:
    return _get_scheduler().format_sprint_plan()


def format_daily_done() -> str:
    return _get_scheduler().format_daily_done_card()


def mark_careless(error_id: int) -> bool:
    return _get_scheduler().mark_as_careless(error_id)


def classify_all() -> dict:
    return _get_scheduler().classify_all()


# ── CLI ───────────────────────────────────────────────────────────────


def main():
    import argparse
    s = ReviewScheduler()
    parser = argparse.ArgumentParser(description="智能复习排期引擎")
    sub = parser.add_subparsers(dest="cmd")

    p_plan = sub.add_parser("plan", help="查看今日推送计划")
    p_plan.add_argument("--json", action="store_true")
    p_plan.add_argument("--sprint", action="store_true", help="强制考前模式")

    p_prog = sub.add_parser("progress", help="查看清理进度")
    p_prog.add_argument("--json", action="store_true")

    p_sprint = sub.add_parser("sprint", help="生成考前清零计划")
    p_sprint.add_argument("--json", action="store_true")

    p_careless = sub.add_parser("careless", help="标记为粗心错题")
    p_careless.add_argument("error_id", type=int)

    p_tiers = sub.add_parser("tiers", help="查看分层统计")
    p_tiers.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    if args.cmd == "plan":
        plan = s.build_daily_plan(is_pre_exam=args.sprint)
        if args.json:
            print(json.dumps(plan, ensure_ascii=False))
        else:
            print(f"今日计划: {plan['total']} 题 (T1={plan['tiers']['T1']} T2={plan['tiers']['T2']} T3={plan['tiers']['T3']})")
            print(f"今日已完成: {plan['completed_today']}")
            print(f"整体进度: {plan['completion_pct']}%")
            print(f"预计完成: {plan['estimated_done_date']}")

    elif args.cmd == "progress":
        print(s.format_progress_bar())

    elif args.cmd == "sprint":
        if args.json:
            print(json.dumps(s.build_sprint_plan(), ensure_ascii=False))
        else:
            print(s.format_sprint_plan())

    elif args.cmd == "careless":
        ok = s.mark_as_careless(args.error_id)
        print(f"✅ 错题 #{args.error_id} 已标记为粗心，排除出复习队列" if ok else "❌ 失败")

    elif args.cmd == "tiers":
        tiers = s.classify_all()
        if args.json:
            print(json.dumps({
                k: [{"error_id": t.error_id, "label": t.label, "mistakes": t.mistake_count}
                    for t in v]
                for k, v in tiers.items()
            }, ensure_ascii=False))
        else:
            for t in ("T1", "T2", "T3", "T0"):
                items = tiers[t]
                label = {"T1": "🔴 高频", "T2": "🟡 近期", "T3": "🟢 低频", "T0": "⚪ 粗心"}[t]
                print(f"\n{label}（{len(items)} 题）")
                for item in items[:10]:
                    print(f"  #{item.error_id} 错{item.mistake_count}次 最后{item.days_since_last}天前 P={item.priority_score:.0f}")


if __name__ == "__main__":
    main()
