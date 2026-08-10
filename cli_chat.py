#!/usr/bin/env python3
"""
PMP Athena · 命令行聊天（零依赖作弊纸）
==========================================
用法：python cli_chat.py
不需要 Claude Code，不需要微信，打开终端就能用。

支持的命令（打字或输入数字）：
  知识速查 / 检索 / 查  → 知识点速查（L1 精华摘要）
  复习错题 / 复习        → 今日到期错题复习
  薄弱点 / 弱点 / 诊断   → 薄弱领域分析
  做题统计 / 统计        → 题库统计数据
  学习计划 / 计划        → 制定 14 天备考计划
  每日一练 / 进度        → 每日一练完成进度
  录入错题 / 录入        → 手动录入一道错题
  倒计时 / 还有多久      → 显示考试倒计时
  帮助 / help / ?        → 重新打印菜单
  退出 / quit / exit     → 退出
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable  # 当前运行的 python，跨平台通用
EXAM_DATE = datetime(2026, 9, 12)

# ── 工具函数 ───────────────────────────────────────────

def run(cmd: list[str], timeout: int = 30) -> None:
    """运行一条 Python 命令，实时输出结果。"""
    print()
    try:
        # 统一用 PYTHONIOENCODING=utf-8 确保中文不乱码
        env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [PYTHON, *cmd],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.stdout:
            print(result.stdout.strip())
        if result.stderr:
            # stderr 有时只是警告，照常打印
            print(result.stderr.strip())
        if result.returncode != 0 and not result.stdout and not result.stderr:
            print(f"⚠️  命令执行失败（退出码 {result.returncode}）")
    except subprocess.TimeoutExpired:
        print("⚠️  命令执行超时（> 30 秒），请检查环境。")
    except FileNotFoundError:
        print(f"⚠️  找不到 Python：{PYTHON}。请确认 Python 3.10+ 已安装。")
    except Exception as exc:
        print(f"⚠️  执行出错：{exc}")


def countdown() -> str:
    """考试倒计时。"""
    now = datetime.now()
    delta = EXAM_DATE - now
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    if days < 0:
        return "🎉 考试日到了！祝大王旗开得胜！"
    return f"📅 距离 2026-09-12 PMP 考试还有 {days} 天 {hours} 小时 {minutes} 分钟"


def print_banner() -> None:
    print()
    print("═" * 50)
    print("🦉  PMP Athena · 命令行助手")
    print("═" * 50)
    print(countdown())
    print("─" * 50)
    print("""
  [1] 📚 知识速查     [5] 📋 学习计划
  [2] 🔄 复习错题     [6] 📆 每日一练进度
  [3] 🔍 薄弱点分析   [7] ✏️  录入错题
  [4] 📊 做题统计     [8] ⏰ 倒计时

  输入数字 或 文字（如 "查 挣值"），q 退出
""")


# ── 处理器字典 ─────────────────────────────────────────

def handle_knowledge(text: str) -> None:
    """知识速查：提取关键词 → L1 检索。"""
    # 去掉前缀词
    for prefix in ["查", "查询", "检索", "知识", "知识点"]:
        text = text.replace(prefix, "", 1)
    keyword = text.strip().strip("：:").strip()
    if not keyword:
        keyword = input("  请输入要查的知识领域 / 关键词：").strip()
    if keyword:
        run(["retrieve_knowledge.py", "query", keyword, "--level", "L1"])
    else:
        print("⚠️  已取消。")


def handle_review(_text: str = "") -> None:
    """错题复习。"""
    run(["pmp_athena/study_advisor.py", "review-today"], timeout=60)


def handle_weakness(_text: str = "") -> None:
    """薄弱点分析。"""
    run(["pmp_athena/study_advisor.py", "weakness"], timeout=60)


def handle_stats(_text: str = "") -> None:
    """做题统计。"""
    run(["pmp_athena/question_bank.py", "stats"], timeout=30)


def handle_plan(_text: str = "") -> None:
    """14 天备考计划。"""
    run(["pmp_athena/study_advisor.py", "plan", "--days", "14"], timeout=60)


def handle_progress(_text: str = "") -> None:
    """每日一练进度。"""
    run(["pmp_athena/daily_practice.py", "progress"], timeout=30)


def handle_countdown(_text: str = "") -> None:
    """倒计时。"""
    print()
    print(countdown())


def handle_add_error(_text: str = "") -> None:
    """手动录入一道错题。"""
    print()
    print("  ✏️  录入错题（输入 q 可随时取消）")
    print("─" * 40)
    try:
        question = input("  题干（回车提交）：").strip()
        if question.lower() == "q":
            return
        my_answer = input("  你的答案（A/B/C/D）：").strip().upper()
        if my_answer.lower() == "Q":
            return
        correct_answer = input("  正确答案（A/B/C/D）：").strip().upper()
        if correct_answer.lower() == "Q":
            return
        print("  常见知识领域：整合管理 / 范围管理 / 进度管理 / 成本管理")
        print("              质量管理 / 资源管理 / 沟通管理 / 风险管理")
        print("              采购管理 / 干系人管理 / 敏捷混合 / 商业环境")
        knowledge_area = input("  知识领域：").strip()
        if knowledge_area.lower() == "q":
            return
        explanation = input("  一句话解析（可选）：").strip()
        if explanation.lower() == "q":
            return

        cmd = [
            "pmp_athena/record_answer.py", "wrong",
            "--question", question,
            "--my-answer", my_answer,
            "--correct-answer", correct_answer,
            "--knowledge-area", knowledge_area,
            "--explanation", explanation or "手动录入",
            "--source", "manual",
        ]
        run(cmd, timeout=30)
    except (EOFError, KeyboardInterrupt):
        print("\n⚠️  已取消。")


# ── 主循环 ─────────────────────────────────────────────

ROUTES = {
    # 数字
    "1": handle_knowledge,
    "2": handle_review,
    "3": handle_weakness,
    "4": handle_stats,
    "5": handle_plan,
    "6": handle_progress,
    "7": handle_add_error,
    "8": handle_countdown,
    # 文字别名
    "复习": handle_review,
    "复习错题": handle_review,
    "错题复习": handle_review,
    "薄弱": handle_weakness,
    "薄弱点": handle_weakness,
    "弱点": handle_weakness,
    "诊断": handle_weakness,
    "统计": handle_stats,
    "做题统计": handle_stats,
    "题库": handle_stats,
    "计划": handle_plan,
    "学习计划": handle_plan,
    "备考计划": handle_plan,
    "进度": handle_progress,
    "每日一练": handle_progress,
    "每日一练进度": handle_progress,
    "倒计时": handle_countdown,
    "还有多久": handle_countdown,
    "考试": handle_countdown,
    "录入": handle_add_error,
    "录入错题": handle_add_error,
    "加错题": handle_add_error,
    "帮助": lambda _: print_banner(),
    "help": lambda _: print_banner(),
    "?": lambda _: print_banner(),
    "菜单": lambda _: print_banner(),
    "知识": handle_knowledge,
    "查": handle_knowledge,
    "检索": handle_knowledge,
    "查询": handle_knowledge,
}


def main() -> None:
    print_banner()
    while True:
        try:
            raw = input("\n🦉 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见，加油备考！")
            break

        if not raw:
            continue

        low = raw.lower()
        if low in ("q", "quit", "exit", "退出", "88"):
            print("👋 再见，加油备考！")
            break

        # 数字直接路由
        handler = ROUTES.get(raw)
        if handler:
            handler("")
            continue

        # 文字模糊匹配
        matched = False
        for key, handler in ROUTES.items():
            if key in ("1", "2", "3", "4", "5", "6", "7", "8"):
                continue  # 跳过纯数字 key
            if low.startswith(key):
                handler(raw)
                matched = True
                break

        if not matched:
            print(f"  🤔 没看懂「{raw}」")
            print("  试试这些：查 X知识点 | 复习错题 | 薄弱点 | 统计 | 计划 | 进度 | 录入错题 | 倒计时")
            print("  输入 ? 或 帮助 看完整菜单")


if __name__ == "__main__":
    main()
