#!/usr/bin/env python3
"""
间隔复习模块 —— 基于 SM-2 算法（Anki）

对错题本中的题目按艾宾浩斯遗忘曲线安排复习节奏。
每道错题首次加入时排到明天；复习后根据自评质量（0-5）自动计算下次间隔。

用法:
    python pmp_athena/spaced_repetition.py review          # 今日待复习
    python pmp_athena/spaced_repetition.py next            # 预览明天的题
    python pmp_athena/spaced_repetition.py grade 1 4       # 给错题 #1 打分 4/5
    python pmp_athena/spaced_repetition.py add 1           # 将错题 #1 加入复习队列
    python pmp_athena/spaced_repetition.py stats           # 复习统计
    python pmp_athena/spaced_repetition.py queue           # 查看所有排队中的题目

SM-2 算法参考:
    https://www.supermemo.com/en/archives1990-2015/english/ol/sm2
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
logger = logging.getLogger("spaced_repetition")

# ── 常量 ──────────────────────────────────────────────────
DEFAULT_STATE_PATH = Path("D:/pmp-athena/pmp_notes/error_review_state.json")
DEFAULT_ERROR_LOG = Path("D:/pmp-athena/pmp_notes/error_log.json")

SM2_INITIAL_EF = 2.5       # 初始难度系数
SM2_MIN_EF = 1.3           # 难度系数下限
SM2_INTERVALS = [1, 6]     # 前两次复习间隔（天）


# ═══════════════════════════════════════════════════════════
# SM-2 算法核心
# ═══════════════════════════════════════════════════════════

def sm2_next(
    quality: int,
    repetitions: int,
    ef: float,
    interval: int,
    today: Optional[date] = None,
) -> dict:
    """
    根据 SM-2 算法计算下一次复习的参数。

    Args:
        quality: 自评质量 0-5
           0 = 完全忘记
           1 = 有些印象但仍错误
           2 = 部分回忆但有很大困难
           3 = 能回忆但有明显困难
           4 = 能回忆略有犹豫
           5 = 完美回忆
        repetitions: 当前连续正确次数
        ef: 当前难度系数 (easiness factor)
        interval: 当前间隔（天）
        today: 基准日期（默认今天）

    Returns:
        {
            "repetitions": int,
            "ef": float,
            "interval": int,
            "next_date": str,
            "action": "again" | "hard" | "good" | "easy",
        }
    """
    today = today or date.today()

    if quality < 3:
        # 不合格：重置，明天再复习
        return {
            "repetitions": 0,
            "ef": max(SM2_MIN_EF, ef - 0.2),
            "interval": 1,
            "next_date": (today + timedelta(days=1)).isoformat(),
            "action": "again",
        }

    # 更新 EF
    new_ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ef = max(SM2_MIN_EF, round(new_ef, 2))

    # 计算新间隔
    new_reps = repetitions + 1

    if new_reps == 1:
        new_interval = SM2_INTERVALS[0]   # 1 天
    elif new_reps == 2:
        new_interval = SM2_INTERVALS[1]   # 6 天
    else:
        new_interval = round(interval * new_ef)

    action = "easy" if quality >= 5 else "good"

    return {
        "repetitions": new_reps,
        "ef": new_ef,
        "interval": new_interval,
        "next_date": (today + timedelta(days=new_interval)).isoformat(),
        "action": action,
    }


# ═══════════════════════════════════════════════════════════
# 复习状态管理
# ═══════════════════════════════════════════════════════════

class SpacedRepetition:
    """间隔复习调度器"""

    def __init__(
        self,
        state_path: Path | None = None,
        error_log_path: Path | None = None,
    ):
        self.state_path = state_path or DEFAULT_STATE_PATH
        self.error_log_path = error_log_path or DEFAULT_ERROR_LOG
        self._ensure_files()

    def _ensure_files(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self.state_path.write_text("{}", encoding="utf-8")

    # ── 状态读写 ───────────────────────────────────────────

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _write_state(self, data: dict):
        self.state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_errors(self) -> list[dict]:
        try:
            return json.loads(self.error_log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _find_error(self, error_id: int) -> dict | None:
        for e in self._read_errors():
            if e.get("id") == error_id:
                return e
        return None

    # ── 添加错题到复习队列 ─────────────────────────────────

    def add(self, error_id: int) -> bool:
        """
        将错题加入复习队列。首次加入排到明天。

        返回 True 表示新增，False 表示已在队列中。
        """
        state = self._read_state()
        key = str(error_id)

        if key in state:
            logger.info("Error #%d already in review queue", error_id)
            return False

        error = self._find_error(error_id)
        if error is None:
            logger.warning("Error #%d not found in error_log.json", error_id)
            return False

        today = date.today()
        state[key] = {
            "error_id": error_id,
            "added_at": today.isoformat(),
            "repetitions": 0,
            "ef": SM2_INITIAL_EF,
            "interval": 0,            # 0 = 未开始
            "next_date": (today + timedelta(days=1)).isoformat(),
            "last_quality": None,
            "total_reviews": 0,
            "history": [],            # [{date, quality}, ...]
            # 缓存题目摘要，避免每次重新读 error_log
            "question_preview": error.get("question", "")[:80],
            "knowledge_area": error.get("knowledge_area", ""),
            # 高频错题追踪
            "high_frequency": False,
            "consecutive_correct": 0,
            "skip_count": 0,           # 连续跳过次数（连续 3 次 → 降级为知识回顾）
            "consecutive_skips": 0,    # 从上次答题后累计跳过次数
            "variant_pass_count": 0,
            "variant_total": 0,
        }

        self._write_state(state)
        logger.info("Error #%d added to review queue → next: %s", error_id, state[key]["next_date"])
        return True

    def update_high_frequency_status(self, error_id: int, is_hf: bool) -> bool:
        """更新高频错题标记。"""
        state = self._read_state()
        key = str(error_id)
        if key not in state:
            return False
        state[key]["high_frequency"] = is_hf
        self._write_state(state)
        return True

    def add_all_errors(self) -> int:
        """将 error_log.json 中所有未在队列中的错题加入"""
        errors = self._read_errors()
        state = self._read_state()
        count = 0
        for e in errors:
            if str(e["id"]) not in state:
                self.add(e["id"])
                count += 1
        return count

    # ── 今日复习 ───────────────────────────────────────────

    def get_due_today(self) -> list[dict]:
        """获取今天该复习的所有题目"""
        today_str = date.today().isoformat()
        state = self._read_state()
        due = []

        for key, card in state.items():
            if card.get("next_date", "9999") <= today_str:
                error = self._find_error(card["error_id"])
                due.append({
                    **card,
                    "error": error,
                })

        due.sort(key=lambda x: x.get("next_date", ""))
        return due

    def get_due_tomorrow(self) -> list[dict]:
        """预览明天要复习的题目"""
        tomorrow_str = (date.today() + timedelta(days=1)).isoformat()
        state = self._read_state()
        due = []

        for key, card in state.items():
            if card.get("next_date") == tomorrow_str:
                error = self._find_error(card["error_id"])
                due.append({
                    **card,
                    "error": error,
                })

        return due

    def get_upcoming(self, days: int = 7) -> list[dict]:
        """预览未来 N 天待复习的题目"""
        end_date = (date.today() + timedelta(days=days)).isoformat()
        today_str = date.today().isoformat()
        state = self._read_state()
        upcoming = []

        for key, card in state.items():
            next_date = card.get("next_date", "9999")
            if today_str <= next_date <= end_date:
                error = self._find_error(card["error_id"])
                upcoming.append({
                    **card,
                    "error": error,
                })

        upcoming.sort(key=lambda x: x.get("next_date", ""))
        return upcoming

    # ── 评分 ───────────────────────────────────────────────

    def grade(self, error_id: int, quality: int) -> dict | None:
        """
        给已复习的错题打分。

        Args:
            error_id: 错题 ID
            quality: 0-5，参见 sm2_next()

        Returns:
            更新后的 card 信息，或 None（题目不在队列中）
        """
        if not 0 <= quality <= 5:
            raise ValueError("quality must be 0-5")

        state = self._read_state()
        key = str(error_id)

        if key not in state:
            logger.warning("Error #%d not in review queue", error_id)
            return None

        card = state[key]
        today = date.today()

        # 应用 SM-2
        result = sm2_next(
            quality=quality,
            repetitions=card["repetitions"],
            ef=card["ef"],
            interval=max(card["interval"], 1),
            today=today,
        )

        # 更新卡片
        card["repetitions"] = result["repetitions"]
        card["ef"] = result["ef"]
        card["interval"] = result["interval"]
        card["next_date"] = result["next_date"]
        card["last_quality"] = quality
        card["total_reviews"] += 1

        # 高频错题追踪：连续正确计数
        if "consecutive_correct" not in card:
            card["consecutive_correct"] = 0
        if quality >= 4:
            card["consecutive_correct"] = card["consecutive_correct"] + 1
        else:
            card["consecutive_correct"] = 0

        # 只要用户有答题行为 → 重置跳过计数（用户已经认真对待了）
        card["skip_count"] = 0
        card["consecutive_skips"] = 0

        # 确保高频相关字段存在（向后兼容旧卡）
        for _f, _d in [("high_frequency", False), ("skip_count", 0), ("consecutive_skips", 0),
                        ("variant_pass_count", 0), ("variant_total", 0)]:
            if _f not in card:
                card[_f] = _d

        # 记录历史
        if "history" not in card:
            card["history"] = []
        card["history"].append({
            "date": today.isoformat(),
            "quality": quality,
            "action": result["action"],
        })

        self._write_state(state)

        logger.info(
            "Error #%d graded %d/5 → rep=%d, ef=%.2f, interval=%dd, next=%s",
            error_id, quality,
            result["repetitions"], result["ef"],
            result["interval"], result["next_date"],
        )
        return card

    # ── 统计 ───────────────────────────────────────────────

    def get_stats(self) -> dict:
        """获取复习统计"""
        state = self._read_state()
        today_str = date.today().isoformat()

        if not state:
            return {
                "total": 0,
                "due_today": 0,
                "due_this_week": 0,
                "mastered": 0,          # interval >= 30 天
                "by_area": {},
                "avg_ef": 0,
            }

        cards = list(state.values())
        due_today = sum(1 for c in cards if c.get("next_date", "") <= today_str)

        # 本周（7天内）
        end_of_week = (date.today() + timedelta(days=7)).isoformat()
        due_this_week = sum(
            1 for c in cards
            if today_str <= c.get("next_date", "") <= end_of_week
        )

        # 已掌握（间隔 >= 30 天）
        mastered = sum(1 for c in cards if c.get("interval", 0) >= 30)

        # 按知识领域
        by_area: dict[str, int] = {}
        for c in cards:
            area = c.get("knowledge_area", "未分类")
            by_area[area] = by_area.get(area, 0) + 1

        # 平均 EF
        avg_ef = sum(c.get("ef", SM2_INITIAL_EF) for c in cards) / len(cards)

        return {
            "total": len(cards),
            "due_today": due_today,
            "due_this_week": due_this_week,
            "mastered": mastered,
            "by_area": dict(sorted(by_area.items(), key=lambda x: x[1], reverse=True)),
            "avg_ef": round(avg_ef, 2),
        }

    def get_queue(self) -> list[dict]:
        """列出所有在队列中的题目，按下次复习日期排序"""
        state = self._read_state()
        cards = list(state.values())
        cards.sort(key=lambda x: x.get("next_date", "9999"))
        return cards

    # ── 其他 ──────────────────────────────────────────────

    def remove(self, error_id: int) -> bool:
        """从复习队列中移除某题（掌握后不再需要复习）"""
        state = self._read_state()
        key = str(error_id)
        if key in state:
            del state[key]
            self._write_state(state)
            logger.info("Error #%d removed from review queue", error_id)
            return True
        return False

    def reset(self, error_id: int) -> bool:
        """重置某题的复习进度（重新开始）"""
        state = self._read_state()
        key = str(error_id)
        if key not in state:
            return False

        card = state[key]
        today = date.today()
        card["repetitions"] = 0
        card["ef"] = SM2_INITIAL_EF
        card["interval"] = 0
        card["next_date"] = (today + timedelta(days=1)).isoformat()
        card["last_quality"] = None
        card["total_reviews"] = 0
        card["history"] = []

        self._write_state(state)
        logger.info("Error #%d reset", error_id)
        return True


# ═══════════════════════════════════════════════════════════
# 格式化输出
# ═══════════════════════════════════════════════════════════

def _format_card(card: dict, index: int = 0) -> str:
    """格式化单张复习卡片"""
    error = card.get("error") or {}
    lines = []

    # 卡片头
    eid = card.get("error_id", "?")
    area = card.get("knowledge_area", error.get("knowledge_area", ""))
    ef = card.get("ef", 0)
    reps = card.get("repetitions", 0)
    interval = card.get("interval", 0)
    next_date = card.get("next_date", "")

    header = f"#{eid}"
    if area:
        header += f"  [{area}]"
    header += f"  EF={ef:.1f}  复习{reps}次  间隔{interval}天  下次: {next_date}"
    if index:
        header = f"### {index}. {header}"
    lines.append(header)

    # 题目
    question = error.get("question", card.get("question_preview", ""))
    if question:
        lines.append(f"> {question[:120]}")
    else:
        lines.append(f"> _（题目未找到，error_id={eid}）_")

    # 答案信息
    my_ans = error.get("my_answer", "")
    correct_ans = error.get("correct_answer", "")
    if my_ans and correct_ans:
        lines.append(f"❌ 你的答案: **{my_ans}**  →  ✅ 正确答案: **{correct_ans}**")

    # 解析
    explanation = error.get("explanation", "")
    if explanation:
        lines.append(f"💡 {explanation[:100]}")

    # 历史
    history = card.get("history", [])
    if history:
        last_few = history[-3:]
        hist_str = " → ".join(
            f"{h['date']}({h['quality']}/5)" for h in last_few
        )
        lines.append(f"📜 最近: {hist_str}")

    return "\n".join(lines)


def _format_stats(stats: dict) -> str:
    """格式化复习统计"""
    lines = []
    lines.append("╔══════════════════════════════════════╗")
    lines.append("║   🧠 间隔复习统计 (SM-2)             ║")
    lines.append("╚══════════════════════════════════════╝")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|----|")
    lines.append(f"| 📚 队列总数 | {stats['total']} |")
    lines.append(f"| 📅 今日待复习 | **{stats['due_today']}** |")
    lines.append(f"| 📆 本周待复习 | {stats['due_this_week']} |")
    lines.append(f"| 🏆 已掌握 (间隔≥30天) | {stats['mastered']} |")
    lines.append(f"| 📊 平均难度系数 | {stats['avg_ef']} |")

    if stats["by_area"]:
        lines.append("")
        lines.append("## 按知识领域分布\n")
        lines.append("| 领域 | 数量 |")
        lines.append("|------|------|")
        for area, count in stats["by_area"].items():
            lines.append(f"| {area} | {count} |")

    return "\n".join(lines)


def _format_due_list(cards: list[dict], title: str = "📅 今日待复习") -> str:
    """格式化待复习列表"""
    if not cards:
        return f"{title}\n\n✅ 暂无待复习题目！干得漂亮 🎉"

    lines = [f"## {title}（共 {len(cards)} 题）\n"]
    for i, card in enumerate(cards, 1):
        lines.append(_format_card(card, i))
        lines.append("")

    lines.append("---")
    lines.append("复习完后用以下命令评分：")
    for card in cards:
        eid = card.get("error_id", "")
        lines.append(f"```bash\npython pmp_athena/spaced_repetition.py grade {eid} <0-5>\n```")
    lines.append("")
    lines.append("0=完全忘记  1=有些印象  2=部分回忆  3=有困难但能回忆  4=略有犹豫  5=完美")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="间隔复习调度器 (SM-2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command", help="子命令")

    # review
    sub.add_parser("review", help="今日待复习的错题")

    # next
    sub.add_parser("next", help="预览明天要复习的题")

    # upcoming
    p_up = sub.add_parser("upcoming", help="预览未来 N 天待复习")
    p_up.add_argument("days", nargs="?", type=int, default=7, help="天数（默认 7）")

    # add
    p_add = sub.add_parser("add", help="将错题加入复习队列")
    p_add.add_argument("error_id", nargs="?", type=int, default=None, help="错题 ID")
    p_add.add_argument("--all", action="store_true", help="加入所有未在队列中的错题")

    # grade
    p_grade = sub.add_parser("grade", help="给已复习的题目打分")
    p_grade.add_argument("error_id", type=int, help="错题 ID")
    p_grade.add_argument("quality", type=int, help="自评质量 0-5")

    # stats
    sub.add_parser("stats", help="复习统计")

    # queue
    sub.add_parser("queue", help="查看所有排队中的题目")

    # remove
    p_rm = sub.add_parser("remove", help="从队列中移除（已掌握）")
    p_rm.add_argument("error_id", type=int, help="错题 ID")

    # reset
    p_reset = sub.add_parser("reset", help="重置某题复习进度")
    p_reset.add_argument("error_id", type=int, help="错题 ID")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    sr = SpacedRepetition()

    if args.command == "review":
        cards = sr.get_due_today()
        print(_format_due_list(cards))

    elif args.command == "next":
        cards = sr.get_due_tomorrow()
        if not cards:
            print("✅ 明天暂无待复习题目")
        else:
            print(_format_due_list(cards, "📆 明天待复习"))
            # 也展示后天的情况
            after_tomorrow = sr.get_upcoming(3)
            after_only = [c for c in after_tomorrow if c["next_date"] > cards[0]["next_date"]]
            if after_only:
                dates = sorted(set(c["next_date"] for c in after_only))
                for d in dates:
                    count = sum(1 for c in after_only if c["next_date"] == d)
                    print(f"  📅 {d}: {count} 题")

    elif args.command == "upcoming":
        cards = sr.get_upcoming(args.days)
        if not cards:
            print(f"✅ 未来 {args.days} 天暂无待复习题目")
        else:
            # 按日期分组
            by_date: dict[str, list] = {}
            for c in cards:
                d = c.get("next_date", "?")
                by_date.setdefault(d, []).append(c)

            print(f"📆 未来 {args.days} 天待复习（共 {len(cards)} 题）\n")
            for d in sorted(by_date.keys()):
                day_cards = by_date[d]
                print(f"### {d}（{len(day_cards)} 题）")
                for c in day_cards:
                    eid = c.get("error_id", "?")
                    area = c.get("knowledge_area", "")
                    q = c.get("question_preview", "")[:50]
                    print(f"  #{eid} [{area}] {q}...")
                print()

    elif args.command == "add":
        if args.all:
            n = sr.add_all_errors()
            print(f"✅ 已加入 {n} 条错题到复习队列")
        elif args.error_id is not None:
            ok = sr.add(args.error_id)
            if ok:
                print(f"✅ 错题 #{args.error_id} 已加入复习队列，明天开始复习")
        else:
            print("❌ 请指定 error_id 或使用 --all")
            sys.exit(1)

    elif args.command == "grade":
        try:
            card = sr.grade(args.error_id, args.quality)
            if card:
                interval = card["interval"]
                next_date = card["next_date"]
                reps = card["repetitions"]
                ef = card["ef"]
                print(f"✅ 错题 #{args.error_id} 评分 {args.quality}/5")
                print(f"   EF={ef:.1f}  复习次数={reps}  下次间隔={interval}天  下次日期={next_date}")

                if interval >= 30:
                    print("   🏆 间隔已达 30 天以上，可以考虑移出队列！")
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(1)

    elif args.command == "stats":
        stats = sr.get_stats()
        print(_format_stats(stats))

    elif args.command == "queue":
        cards = sr.get_queue()
        if not cards:
            print("📭 复习队列为空")
        else:
            print(f"📚 复习队列（共 {len(cards)} 题）\n")
            today_str = date.today().isoformat()
            for i, card in enumerate(cards, 1):
                next_date = card.get("next_date", "?")
                due_mark = " ⬅️ 今天!" if next_date <= today_str else ""
                status = "🟢" if card.get("interval", 0) >= 21 else ("🟡" if card.get("interval", 0) >= 7 else "🔴")
                print(
                    f"{status} #{card['error_id']:>3d}  "
                    f"[{card.get('knowledge_area', '?')}]  "
                    f"EF={card.get('ef', 0):.1f}  "
                    f"复习{card.get('repetitions', 0)}次  "
                    f"间隔{card.get('interval', 0)}天  "
                    f"下次: {next_date}{due_mark}"
                )

    elif args.command == "remove":
        ok = sr.remove(args.error_id)
        if ok:
            print(f"✅ 错题 #{args.error_id} 已移出复习队列")

    elif args.command == "reset":
        ok = sr.reset(args.error_id)
        if ok:
            print(f"✅ 错题 #{args.error_id} 已重置，明天重新开始")


if __name__ == "__main__":
    main()
