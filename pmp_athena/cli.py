"""
PMP Athena CLI —— 命令行交互界面

用法：
    python -m pmp_athena.cli          # 进入交互模式
    python -m pmp_athena.cli ingest   # 导入所有笔记
    python -m pmp_athena.cli plan     # 生成每日计划
    python -m pmp_athena.cli analyze  # 分析通过率
    python -m pmp_athena.cli stats    # 查看统计
"""

import argparse
import logging
import sys
from pathlib import Path

# ── Windows UTF-8 编码修复 ───────────────────────────────────
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pmp_athena")

# ── Rich 初始化 ─────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    from rich.prompt import Prompt
    from rich.text import Text

    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    console = None


def print_markdown(text: str):
    """渲染 Markdown 到终端"""
    if HAS_RICH:
        console.print(Markdown(text))
    else:
        # 去掉 markdown 标记
        import re
        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        clean = re.sub(r"\*(.+?)\*", r"\1", clean)
        clean = re.sub(r"#+ ", "", clean)
        clean = re.sub(r"`(.+?)`", r"\1", clean)
        print(clean)


def print_panel(text: str, title: str = ""):
    if HAS_RICH:
        console.print(Panel(Markdown(text), title=title))
    else:
        if title:
            print(f"\n{'='*40}\n{title}\n{'='*40}")
        print(text)


# ═══════════════════════════════════════════════════════════════
# 命令处理
# ═══════════════════════════════════════════════════════════════


def cmd_ingest(args):
    """导入所有笔记、截图 OCR、模考记录"""
    from .ingestion import MarkdownLoader, OCRProcessor, MockExamLoader, PDFLoader

    console.print("\n[bold cyan]📥 开始导入数据...[/bold cyan]\n")

    # 1. 导入 Markdown 笔记
    console.print("[bold]1/4[/bold] 导入 Markdown 笔记...")
    loader = MarkdownLoader()
    result = loader.ingest_all(reset=args.reset)
    console.print(f"  ✅ 处理 {result['files']} 个文件 → {result['chunks']} 个 chunk")

    # 2. 导入 PDF 笔记
    console.print("\n[bold]2/4[/bold] 导入 PDF 笔记...")
    pdf_loader = PDFLoader()
    pdf_result = pdf_loader.ingest_all()
    if "error" in pdf_result:
        console.print(f"  ⚠️ PDF 导入异常: {pdf_result['error']}")
    else:
        console.print(
            f"  ✅ 处理 {pdf_result['files']} 个 PDF → "
            f"{pdf_result['chunks']} 个 chunk（{pdf_result.get('total_pages', '?')} 页）"
        )

    # 3. OCR 截图
    console.print("\n[bold]3/4[/bold] OCR 处理截图...")
    ocr = OCRProcessor()
    ocr_result = ocr.ingest_all_images(reset=args.reset)
    if "error" in ocr_result:
        console.print(f"  ⚠️ OCR 不可用: {ocr_result['error']}")
        console.print("  💡 安装方法: pip install pytesseract + 安装 Tesseract OCR 引擎")
    else:
        console.print(
            f"  ✅ 处理 {ocr_result['files']} 张图片 → "
            f"{ocr_result['ocr_count']} 条 OCR 文本"
        )

    # 4. 模考记录
    console.print("\n[bold]4/4[/bold] 导入模考记录...")
    exam_loader = MockExamLoader()
    exam_result = exam_loader.ingest_all(reset=args.reset)
    console.print(f"  ✅ 处理 {exam_result['files']} 个文件 → {exam_result['records']} 条模考记录")

    console.print("\n[bold green]🎉 全部导入完成！[/bold green]")
    _print_stats()


def cmd_chat(args):
    """启动交互对话"""
    from .modules.emotion_trigger import EmotionTrigger

    emotion = EmotionTrigger()

    console.print(Panel(
        "[bold cyan]🦉 PMP Athena — 你的 PMP 备考复盘 Agent[/bold cyan]\n\n"
        "可用命令：\n"
        "  [green]/plan[/green]  — 生成今日复习计划\n"
        "  [green]/analyze[/green] — 分析最新模考通过率\n"
        "  [green]/trend[/green] — 查看成绩趋势\n"
        "  [green]/stats[/green] — 查看数据统计\n"
        "  [green]/exam add[/green] — 添加模考成绩\n"
        "  [green]/ingest[/green] — 重新导入笔记\n"
        "  [green]/quick[/green] — 快速回顾卡片\n"
        "  [green]/errors[/green] — 错题统计\n"
        "  [green]/review[/green] — 今日待复习错题 (SM-2)\n"
        "  [green]/next[/green] — 明天待复习预览\n"
        "  [green]/qb[/green] — 题库查询（today/stats/week-wrong）\n"
        "  [green]/sprint[/green] — 冲刺计划 & 进度\n"
        "  [green]/countdown[/green] — 考试倒计时\n"
        "  [green]/help[/green] — 显示帮助\n"
        "  [green]/exit[/green] — 退出\n"
        "\n直接输入问题即可对话。输入 [dim]'我好蠢'[/dim] 试试看 😉",
        title="欢迎",
    ))

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]你[/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n👋 再见！加油备考！")
            break

        if not user_input:
            continue

        # 检查命令
        if user_input.startswith("/"):
            _handle_slash_command(user_input, emotion)
            continue

        # 情绪触发检测
        response = emotion.respond(user_input)
        if response:
            console.print()
            print_markdown(response)
            continue

        # 普通对话 —— 语义搜索笔记
        _handle_chat(user_input)


def _handle_slash_command(user_input: str, emotion):
    """处理 / 开头的命令"""
    parts = user_input[1:].strip().split()
    cmd = parts[0].lower() if parts else ""

    if cmd == "exit" or cmd == "quit":
        console.print("👋 再见！加油备考！")
        sys.exit(0)

    elif cmd == "help":
        console.print(Markdown("""
**PMP Athena 帮助**

| 命令 | 功能 |
|------|------|
| `/plan` | 生成今日复习计划 |
| `/analyze` | 分析最新模考通过率 |
| `/trend` | 查看历次模考成绩趋势 |
| `/stats` | 查看数据库统计 |
| `/exam add` | 手动添加模考成绩 |
| `/ingest` | 重新扫描导入笔记 |
| `/quick` | 快速回顾卡片 |
| `/errors` | 查看错题统计 |
| `/review` | 今日待复习错题 (SM-2 间隔复习) |
| `/next` | 预览明天待复习 |
| `/sprint` | 冲刺计划进度 & 今日任务 |
| `/countdown` | 考试倒计时 & 备考阶段 |
| `/milestones` | 关键节点时间线 |
| `/help` | 显示此帮助 |
| `/exit` | 退出程序 |
"""))

    elif cmd == "plan":
        from .modules.daily_plan import DailyPlanGenerator
        gen = DailyPlanGenerator()
        plan = gen.generate()
        console.print()
        print_markdown(plan)

    elif cmd == "analyze":
        from .modules.pass_rate import PassRateAnalyzer
        analyzer = PassRateAnalyzer()
        report = analyzer.analyze_latest()
        console.print()
        print_markdown(report)

    elif cmd == "trend":
        from .modules.pass_rate import PassRateAnalyzer
        analyzer = PassRateAnalyzer()
        report = analyzer.analyze_trend()
        console.print()
        print_markdown(report)

    elif cmd == "stats":
        _print_stats()

    elif cmd == "exam" and len(parts) > 1 and parts[1] == "add":
        _interactive_add_exam()

    elif cmd == "quick":
        from .modules.daily_plan import DailyPlanGenerator
        gen = DailyPlanGenerator()
        card = gen.get_quick_review()
        console.print()
        print_markdown(card)

    elif cmd == "review":
        from .spaced_repetition import SpacedRepetition, _format_due_list
        sr = SpacedRepetition()
        cards = sr.get_due_today()
        console.print()
        print_markdown(_format_due_list(cards))

    elif cmd == "next":
        from .spaced_repetition import SpacedRepetition, _format_due_list
        sr = SpacedRepetition()
        cards = sr.get_due_tomorrow()
        console.print()
        if not cards:
            console.print("✅ 明天暂无待复习题目")
        else:
            print_markdown(_format_due_list(cards, "📆 明天待复习"))

    elif cmd == "review-stats":
        from .spaced_repetition import SpacedRepetition, _format_stats
        sr = SpacedRepetition()
        stats = sr.get_stats()
        console.print()
        print_markdown(_format_stats(stats))

    elif cmd == "sprint":
        # 支持子命令: /sprint plan 7, /sprint today, /sprint progress, /sprint done 1
        from .sprint_planner import (SprintPlanner, format_plan_markdown,
                                      format_today_markdown, format_progress_markdown)
        sp = SprintPlanner()
        sub_cmd = parts[1] if len(parts) > 1 else "today"
        if sub_cmd == "plan" or sub_cmd == "new":
            days = int(parts[2]) if len(parts) > 2 else 7
            plan = sp.generate(days=days)
            console.print()
            print_markdown(format_plan_markdown(plan))
        elif sub_cmd == "done":
            day = int(parts[2]) if len(parts) > 2 else 1
            ok = sp.mark_done(day)
            if ok:
                console.print(f"[green]✅ 第 {day} 天已标记完成！[/green]")
            else:
                console.print(f"[red]❌ 标记失败，请检查天数是否正确。[/red]")
        elif sub_cmd == "progress":
            progress = sp.get_progress()
            console.print()
            print_markdown(format_progress_markdown(progress))
        else:
            # 默认显示 today
            tasks = sp.get_today_tasks()
            console.print()
            print_markdown(format_today_markdown(tasks or {}))

    elif cmd == "countdown" or cmd == "cd":
        from .exam_timer import ExamTimer, format_countdown
        timer = ExamTimer()
        cd = timer.countdown()
        console.print()
        print_markdown(format_countdown(cd))

    elif cmd == "exam-date" or cmd == "考试日期":
        from .exam_timer import ExamTimer
        timer = ExamTimer()
        if len(parts) > 1:
            try:
                timer.set_date(parts[1])
                cd = timer.countdown()
                console.print(f"\n[green]✅ 考试日期已更新！[/green]")
                console.print(f"📆 距考试还有 [bold]{cd['days_remaining']} 天[/bold]")
                console.print(f"📖 当前阶段：[bold]{cd['phase']}[/bold]")
            except ValueError as e:
                console.print(f"[red]❌ {e}[/red]")
        else:
            cd = timer.countdown()
            if cd["status"] == "not_set":
                console.print("用法: /exam-date YYYY-MM-DD")
            else:
                console.print(f"📅 考试日期: {cd['exam_date']}")

    elif cmd == "milestones":
        from .exam_timer import ExamTimer, format_milestones
        timer = ExamTimer()
        ms = timer.get_milestones()
        console.print()
        print_markdown(format_milestones(ms))

    elif cmd == "errors":
        from .error_logger import ErrorLogger, _format_stats
        logger_inst = ErrorLogger()
        stats = logger_inst.get_stats()
        console.print()
        print_markdown(_format_stats(stats))

    elif cmd == "qb" or cmd == "题库":
        from .question_bank import (
            QuestionBank, _format_stats, _format_today,
            _format_week_wrong, _format_list,
        )
        qb = QuestionBank()
        sub_cmd = parts[1].lower() if len(parts) > 1 else "stats"

        if sub_cmd == "today" or sub_cmd == "今天":
            summary = qb.get_today_summary()
            console.print()
            print_markdown(_format_today(summary))
        elif sub_cmd == "week-wrong" or sub_cmd == "本周错题":
            summary = qb.get_week_wrong_summary()
            console.print()
            print_markdown(_format_week_wrong(summary))
        elif sub_cmd == "stats" or sub_cmd == "统计":
            stats = qb.get_stats()
            console.print()
            print_markdown(_format_stats(stats))
        elif sub_cmd == "list":
            n = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 10
            records = qb.list_recent(n)
            console.print()
            print_markdown(_format_list(records))
        else:
            console.print("用法: /qb today | week-wrong | stats | list [N]")

    elif cmd == "ingest":
        # 模拟 argparse namespace
        class Args:
            reset = "reset" in parts
        cmd_ingest(Args())

    else:
        console.print(f"❓ 未知命令: /{cmd}。输入 /help 查看可用命令。")


def _handle_chat(user_input: str):
    """通用对话——语义搜索笔记"""
    from .db.vector_store import get_vector_store

    store = get_vector_store()

    # 先在笔记中搜索
    note_results = store.search_notes(user_input, n_results=3)

    # 再在截图中搜索
    screenshot_results = store.search_screenshots(user_input, n_results=2)

    console.print()

    if not note_results and not screenshot_results:
        console.print(
            "📭 没有找到相关内容。\n\n"
            "💡 建议：\n"
            "- 确保已运行 `ingest` 导入笔记\n"
            "- 尝试使用不同的关键词\n"
            "- 使用 `/plan` 查看今日推荐"
        )
        return

    # 显示笔记结果
    if note_results:
        console.print("[bold]📝 相关笔记：[/bold]\n")
        for i, result in enumerate(note_results, 1):
            meta = result.get("metadata", {})
            title = meta.get("title", "无标题")
            date_str = meta.get("created_at", "")[:10]
            source = meta.get("source_file", "")
            domain = meta.get("domain", "")
            domain_label = {
                "people": "👥 人员",
                "process": "⚙️ 过程",
                "business_environment": "🏢 商业环境",
            }.get(domain, "")

            doc = result.get("document", "")
            preview = doc[:300] + ("..." if len(doc) > 300 else "")

            header = f"### {i}. {title}"
            if domain_label:
                header += f"  {domain_label}"
            console.print(Markdown(header))
            console.print(f"[dim]📂 {source} · 📅 {date_str}[/dim]")
            console.print(f"[dim]距离: {result.get('distance', 0):.3f}[/dim]")
            console.print(f"> {preview}")
            console.print("")

    # 显示截图 OCR 结果
    if screenshot_results:
        console.print("[bold]🖼️ 相关截图 OCR 文本：[/bold]\n")
        for i, result in enumerate(screenshot_results, 1):
            meta = result.get("metadata", {})
            source = meta.get("source_file", "未知文件")

            doc = result.get("document", "")
            preview = doc[:200] + ("..." if len(doc) > 200 else "")

            console.print(f"**{i}. {source}**")
            console.print(f"> {preview}")
            console.print("")


def _interactive_add_exam():
    """交互式添加模考成绩"""
    console.print("\n[bold]📝 添加模考成绩[/bold]\n")

    try:
        people = float(Prompt.ask("人员/People 得分（如 0.72 表示 72%）", default="0.72"))
        process = float(Prompt.ask("过程/Process 得分", default="0.65"))
        be_score = float(Prompt.ask("商业环境/Business Environment 得分", default="0.75"))
        exam_date = Prompt.ask("考试日期（YYYY-MM-DD）", default="")

        from .ingestion.mock_exam_loader import MockExamLoader
        loader = MockExamLoader()
        doc_id = loader.add_exam_manually(
            scores={
                "people": people,
                "process": process,
                "business_environment": be_score,
            },
            exam_date=exam_date if exam_date else None,
        )

        console.print(f"\n✅ 模考记录已添加（ID: {doc_id}）")

        # 立即分析
        console.print()
        from .modules.pass_rate import PassRateAnalyzer
        analyzer = PassRateAnalyzer()
        report = analyzer.analyze({
            "people": people,
            "process": process,
            "business_environment": be_score,
        })
        print_markdown(report)

    except ValueError:
        console.print("❌ 输入格式错误，请输入数字（如 0.72）")


def _print_stats():
    """打印数据库统计"""
    from .db.vector_store import get_vector_store

    store = get_vector_store()

    notes_count = store.get_notes_count()
    screenshots_count = store._screenshots.count()
    exams = store.get_all_exams()

    if HAS_RICH:
        table = Table(title="📊 PMP Athena 数据库统计")
        table.add_column("项目", style="cyan")
        table.add_column("数量", style="green")

        table.add_row("📝 笔记 Chunks", str(notes_count))
        table.add_row("🖼️ 截图 OCR 记录", str(screenshots_count))
        table.add_row("📋 模考记录", str(len(exams)))

        if exams:
            latest = exams[0]
            date = latest["metadata"].get("exam_date", "未知")[:10]
            table.add_row("📅 最近模考", date)

        # 错题统计
        from .error_logger import ErrorLogger
        error_logger = ErrorLogger()
        error_count = error_logger.get_stats()["total"]
        table.add_row("❌ 错题记录", str(error_count))

        console.print(table)
    else:
        print(f"📝 笔记 Chunks: {notes_count}")
        print(f"🖼️ 截图 OCR 记录: {screenshots_count}")
        print(f"📋 模考记录: {len(exams)}")


# ═══════════════════════════════════════════════════════════════
# 单次命令模式
# ═══════════════════════════════════════════════════════════════


def cmd_plan(args):
    from .modules.daily_plan import DailyPlanGenerator
    gen = DailyPlanGenerator()
    plan = gen.generate(custom_focus=args.focus)
    print_markdown(plan)


def cmd_analyze(args):
    from .modules.pass_rate import PassRateAnalyzer
    analyzer = PassRateAnalyzer()

    if args.trend:
        report = analyzer.analyze_trend()
    else:
        report = analyzer.analyze_latest()

    print_markdown(report)


def cmd_stats(args):
    _print_stats()


def cmd_exam_add(args):
    from .ingestion.mock_exam_loader import MockExamLoader

    loader = MockExamLoader()
    doc_id = loader.add_exam_manually(
        scores={
            "people": args.people,
            "process": args.process,
            "business_environment": args.business_environment,
        },
        exam_date=args.date,
    )
    print(f"✅ 模考记录已添加（ID: {doc_id}）")

    # 自动分析
    from .modules.pass_rate import PassRateAnalyzer
    analyzer = PassRateAnalyzer()
    report = analyzer.analyze({
        "people": args.people,
        "process": args.process,
        "business_environment": args.business_environment,
    })
    print()
    print_markdown(report)


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        prog="pmp-athena",
        description="🦉 PMP Athena — 本地 PMP 备考复盘 Agent",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # chat —— 默认命令
    parser.set_defaults(func=lambda args: cmd_chat(args))

    # ingest
    p_ingest = subparsers.add_parser("ingest", help="导入所有笔记、截图、模考记录")
    p_ingest.add_argument("--reset", action="store_true", help="清空后重新导入")
    p_ingest.set_defaults(func=cmd_ingest)

    # plan
    p_plan = subparsers.add_parser("plan", help="生成每日复习计划")
    p_plan.add_argument("--focus", "-f", type=str, help="自定义复习重点")
    p_plan.set_defaults(func=cmd_plan)

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="分析通过率")
    p_analyze.add_argument("--trend", "-t", action="store_true", help="查看成绩趋势")
    p_analyze.set_defaults(func=cmd_analyze)

    # stats
    p_stats = subparsers.add_parser("stats", help="查看数据库统计")
    p_stats.set_defaults(func=cmd_stats)

    # exam add
    p_exam = subparsers.add_parser("exam", help="手动添加模考成绩")
    p_exam.add_argument("--people", "-p", type=float, required=True, help="人员领域得分（如 0.72）")
    p_exam.add_argument("--process", "-r", type=float, required=True, help="过程领域得分")
    p_exam.add_argument("--business-environment", "-b", type=float, required=True, help="商业环境领域得分")
    p_exam.add_argument("--date", "-d", type=str, help="考试日期（YYYY-MM-DD）")
    p_exam.set_defaults(func=cmd_exam_add)

    args = parser.parse_args()

    if args.command is None:
        # 默认进入 chat 模式
        cmd_chat(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
