#!/usr/bin/env python3
"""
手机可读 HTML 报告 — 知识点 / 薄弱点 / 学习计划等，供 GH HTML 查看器小程序阅读。

用法:
    python pmp_athena/knowledge_report.py generate --text "成本管理知识点"
    python pmp_athena/knowledge_report.py generate --text "挣值" --level L2
    python pmp_athena/knowledge_report.py generate --text "挣值" --level combo
    python pmp_athena/knowledge_report.py generate --type weakness
    python pmp_athena/knowledge_report.py generate --type plan
    python pmp_athena/knowledge_report.py generate --type session --title "8月26日每日一练" --body "..."
    python pmp_athena/knowledge_report.py list
    python pmp_athena/knowledge_report.py generate --text "敏捷知识点" --push
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from pmp_athena.config import PROJECT_ROOT, REPORTS_DIR
except ModuleNotFoundError:
    from config import PROJECT_ROOT, REPORTS_DIR

_TYPE_ALIASES: dict[str, str] = {
    "薄弱点": "weakness",
    "弱点": "weakness",
    "弱点分析": "weakness",
    "诊断报告": "weakness",
    "学习计划": "plan",
    "备考计划": "plan",
    "复习计划": "plan",
}


DOMAIN_ASCII: dict[str, str] = {
    "商业环境": "business",
    "成本管理": "cost",
    "质量管理": "quality",
    "进度管理": "schedule",
    "范围管理": "scope",
    "整合管理": "integration",
    "敏捷/混合方法": "agile",
    "敏捷混合方法": "agile",
    "敏捷": "agile",
    "资源管理": "resource",
    "干系人管理": "stakeholder",
    "沟通管理": "communication",
    "风险管理": "risk",
    "采购管理": "procurement",
    "领导力/人员": "leadership",
}

TITLE_ASCII: dict[str, str] = {
    "薄弱知识点推送": "weak-knowledge-hub",
    "薄弱点诊断": "weakness",
    "学习计划": "study-plan",
}


def _ascii_slug(text: str) -> str:
    """文件名用纯 ASCII，避免小程序/GitHub 中文路径 404。"""
    t = (text or "").strip()
    for cn, en in TITLE_ASCII.items():
        if cn in t:
            return en
    # 长领域名优先
    for cn, en in sorted(DOMAIN_ASCII.items(), key=lambda x: len(x[0]), reverse=True):
        if cn in t:
            return en
    t = re.sub(r"[^\w\-]+", "-", t, flags=re.ASCII)
    t = re.sub(r"-+", "-", t).strip("-").lower()
    return t or "report"


def _slug(text: str, *, max_len: int = 40) -> str:
    return _ascii_slug(text)[:max_len]


def _escape(s: str) -> str:
    return html.escape(s or "", quote=True)


def _inline_md(text: str) -> str:
    """粗体 **x**、行内代码 `x`"""
    out = _escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return out


def text_to_html(text: str) -> str:
    """将 CLI 输出的纯文本/Markdown 轻量转为 mp-html 友好 HTML。"""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    parts: list[str] = []
    in_ul = False
    in_ol = False
    in_table = False
    table_rows: list[list[str]] = []

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            parts.append("</ul>")
            in_ul = False
        if in_ol:
            parts.append("</ol>")
            in_ol = False

    def flush_table() -> None:
        nonlocal in_table, table_rows
        if not in_table:
            return
        if table_rows:
            parts.append('<table class="data">')
            for i, row in enumerate(table_rows):
                tag = "th" if i == 0 else "td"
                cells = "".join(f"<{tag}>{_inline_md(c.strip())}</{tag}>" for c in row)
                parts.append(f"<tr>{cells}</tr>")
            parts.append("</table>")
        table_rows = []
        in_table = False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            close_lists()
            flush_table()
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            close_lists()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.match(r"^[-:\s]+$", c) for c in cells):
                continue
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(cells)
            continue

        flush_table()

        if stripped.startswith("=" * 10):
            continue

        if stripped.startswith("## "):
            close_lists()
            parts.append(f"<h2>{_inline_md(stripped[3:])}</h2>")
            continue

        if stripped.startswith("# "):
            close_lists()
            parts.append(f"<h2>{_inline_md(stripped[2:])}</h2>")
            continue

        m_ol = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m_ol:
            if in_ul:
                parts.append("</ul>")
                in_ul = False
            if not in_ol:
                parts.append("<ol>")
                in_ol = True
            parts.append(f"<li>{_inline_md(m_ol.group(2))}</li>")
            continue

        if stripped.startswith(("- ", "· ", "• ", "* ")):
            if in_ol:
                parts.append("</ol>")
                in_ol = False
            if not in_ul:
                parts.append("<ul>")
                in_ul = True
            parts.append(f"<li>{_inline_md(stripped[2:])}</li>")
            continue

        close_lists()
        if stripped.startswith("📚") or stripped.startswith("📊") or stripped.startswith("🎯"):
            parts.append(f"<h3>{_inline_md(stripped)}</h3>")
        elif stripped.startswith("💡") or stripped.startswith("⚠️"):
            parts.append(f'<p class="hint">{_inline_md(stripped)}</p>')
        else:
            parts.append(f"<p>{_inline_md(stripped)}</p>")

    close_lists()
    flush_table()
    return "\n".join(parts) if parts else "<p>（无内容）</p>"


def wrap_html(
    *,
    title: str,
    subtitle: str,
    body_html: str,
    nav_links: list[tuple[str, str]] | None = None,
) -> str:
    nav = ""
    if nav_links:
        items = "".join(
            f'<a href="{_escape(href)}">{_escape(label)}</a>' for label, href in nav_links
        )
        nav = f'<nav class="nav">{items}</nav>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1"/>
<title>{_escape(title)}</title>
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 16px;
  line-height: 1.65;
  color: #1a1a1a;
  background: #f7f8fa;
  margin: 0;
  padding: 0;
}}
.wrap {{
  max-width: 720px;
  margin: 0 auto;
  padding: 16px 16px 32px;
  background: #fff;
  min-height: 100vh;
  box-sizing: border-box;
}}
header {{
  border-bottom: 2px solid #2563eb;
  padding-bottom: 12px;
  margin-bottom: 20px;
}}
h1 {{
  font-size: 1.35rem;
  margin: 0 0 6px;
  color: #1e3a8a;
  line-height: 1.35;
}}
.sub {{
  font-size: 0.85rem;
  color: #64748b;
  margin: 0;
}}
h2 {{
  font-size: 1.1rem;
  color: #1d4ed8;
  margin: 22px 0 10px;
  border-left: 4px solid #93c5fd;
  padding-left: 8px;
}}
h3 {{
  font-size: 1rem;
  color: #334155;
  margin: 16px 0 8px;
}}
p {{ margin: 8px 0; }}
ul, ol {{ margin: 8px 0 8px 20px; padding: 0; }}
li {{ margin: 6px 0; }}
.hint {{
  background: #eff6ff;
  border-left: 4px solid #3b82f6;
  padding: 10px 12px;
  border-radius: 4px;
}}
code {{
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.92em;
}}
table.data {{
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 0.9rem;
}}
table.data th, table.data td {{
  border: 1px solid #e2e8f0;
  padding: 8px 6px;
  text-align: left;
}}
table.data th {{
  background: #f8fafc;
  font-weight: 600;
}}
.nav {{
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px dashed #cbd5e1;
  font-size: 0.9rem;
}}
.nav a {{
  display: inline-block;
  margin: 4px 12px 4px 0;
  color: #2563eb;
  text-decoration: none;
}}
footer {{
  margin-top: 28px;
  font-size: 0.75rem;
  color: #94a3b8;
  text-align: center;
}}
.section-gap {{ height: 8px; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{_escape(title)}</h1>
  <p class="sub">{_escape(subtitle)}</p>
</header>
<main>
{body_html}
</main>
{nav}
<footer>PMP Athena · 手机报告</footer>
</div>
</body>
</html>
"""


def _countdown_line() -> str:
    exam = date(2026, 9, 12)
    d = max(0, (exam - date.today()).days)
    return f"📅 距考试还有 {d} 天（2026-09-12）"


def resolve_report_type(text: str, explicit: str | None) -> str:
    if explicit and explicit != "auto":
        return explicit
    t = (text or "").strip()
    for k, v in _TYPE_ALIASES.items():
        if k in t:
            return v
    return "knowledge"


def fetch_content(
    *,
    report_type: str,
    text: str,
    level: str = "L1",
    body: str = "",
) -> dict[str, Any]:
    """拉取报告正文（纯文本）。"""
    if report_type == "session":
        if not body.strip():
            return {"status": "error", "text": "⚠️ session 类型需提供 --body 或 --body-file"}
        return {
            "status": "ok",
            "title": text or "学习会话",
            "text": body.strip(),
            "kind": "session",
        }

    if report_type == "weakness":
        try:
            from pmp_athena.study_advisor import analyze_weakness
        except ModuleNotFoundError:
            from study_advisor import analyze_weakness
        return {
            "status": "ok",
            "title": "薄弱点诊断",
            "text": analyze_weakness(),
            "kind": "weakness",
        }

    if report_type == "plan":
        try:
            from pmp_athena.study_advisor import generate_plan
        except ModuleNotFoundError:
            from study_advisor import generate_plan
        return {
            "status": "ok",
            "title": "学习计划",
            "text": generate_plan(),
            "kind": "plan",
        }

    # knowledge
    try:
        from pmp_athena.dynamic_knowledge import handle_message, retrieve_knowledge
    except ModuleNotFoundError:
        from dynamic_knowledge import handle_message, retrieve_knowledge

    query_text = text.strip() or "整合管理知识点"
    sections: list[str] = []
    nav: list[tuple[str, str]] = []
    title = query_text

    if level.upper() == "COMBO":
        r1 = handle_message(query_text)
        if r1.get("status") == "skip":
            r1 = retrieve_knowledge(query_text, "L1")
        r2 = retrieve_knowledge(
            r1.get("entry_name") or query_text.replace("知识点", "").strip() or query_text,
            "L2",
        )
        if r1.get("text"):
            sections.append("## L1 速查\n\n" + r1["text"])
        if r2.get("text"):
            sections.append("## L2 详细\n\n" + r2["text"])
        nav = [("L1 速查", "#l1"), ("L2 详细", "#l2")]
        title = r1.get("entry_name") or query_text
        body_text = "\n\n".join(sections)
    else:
        if level.upper() in ("L2", "L3"):
            result = retrieve_knowledge(
                query_text.replace("详细", "").replace("套路", "").strip() or query_text,
                level.upper(),  # type: ignore[arg-type]
            )
        else:
            result = handle_message(query_text)
            if result.get("status") == "skip":
                result = retrieve_knowledge(query_text, "L1")
        if result.get("status") == "error" or not result.get("text"):
            return {
                "status": "error",
                "text": result.get("text") or "⚠️ 未找到相关内容",
            }
        body_text = result["text"]
        title = result.get("entry_name") or query_text
        lvl = result.get("level", level.upper())
        nav = [(f"详细（L2）", f"combo-{ _slug(title) }.html")] if lvl == "L1" else []

    header = _countdown_line()
    full = header + "\n\n" + body_text
    return {
        "status": "ok",
        "title": str(title),
        "text": full,
        "kind": "knowledge",
        "level": level.upper(),
        "nav_suggest": nav,
    }


def _report_filename(kind: str, title: str, level: str) -> str:
    today = date.today().isoformat()
    slug = _slug(title)
    lvl = "" if kind != "knowledge" else f"-{level.lower()}"
    return f"{today}-{slug}{lvl}.html"


def generate_report(
    *,
    text: str = "",
    report_type: str = "auto",
    level: str = "L1",
    title: str = "",
    body: str = "",
    out_dir: Path | None = None,
) -> dict[str, Any]:
    out = out_dir or REPORTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    rtype = resolve_report_type(text, report_type)
    content = fetch_content(
        report_type=rtype,
        text=title or text,
        level=level,
        body=body,
    )
    if content.get("status") == "error":
        return content

    display_title = title.strip() or content.get("title") or text or rtype
    subtitle = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} · {_countdown_line()}"

    body_html = text_to_html(content["text"])
    if level.upper() == "COMBO":
        body_html = body_html.replace(
            "<h2>L1 速查</h2>",
            '<h2 id="l1">L1 速查</h2>',
            1,
        ).replace(
            "<h2>L2 详细</h2>",
            '<h2 id="l2">L2 详细</h2>',
            1,
        )

    nav_links: list[tuple[str, str]] = []
    if rtype == "knowledge" and level.upper() == "L1":
        combo_name = _report_filename("knowledge", display_title, "combo")
        nav_links.append(("查看 L2 详细版", combo_name))

    html_doc = wrap_html(
        title=display_title,
        subtitle=subtitle,
        body_html=body_html,
        nav_links=nav_links or None,
    )

    fname = _report_filename(rtype if rtype != "knowledge" else "knowledge", display_title, level)
    path = out / fname
    path.write_text(html_doc, encoding="utf-8")

    update_index(out)

    rel = path.relative_to(PROJECT_ROOT).as_posix()
    return {
        "status": "ok",
        "path": str(path),
        "relative_path": rel,
        "filename": fname,
        "title": display_title,
        "report_type": rtype,
        "text": f"✅ 已生成 {rel}\n📱 在 GH HTML 查看器中打开此文件",
    }


def _label_for_file(name: str) -> str:
    if "weak-knowledge-hub" in name:
        return "⭐ 薄弱知识点推送（入口）"
    if "-weakness" in name:
        return "薄弱点诊断"
    if "-study-plan" in name:
        return "学习计划"
    for cn, en in DOMAIN_ASCII.items():
        if f"-{en}-combo" in name:
            return f"{cn} L1+L2"
        if f"-{en}-l1" in name:
            return f"{cn} L1"
    return Path(name).stem


def update_index(out_dir: Path | None = None) -> Path:
    """刷新 reports/index.html 列表。"""
    out = out_dir or REPORTS_DIR
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [
            p
            for p in out.glob("*.html")
            if p.name not in ("index.html", "gallery.html")
        ],
        key=lambda p: (
            0 if "weak-knowledge-hub" in p.name else 1,
            -p.stat().st_mtime,
        ),
    )
    items = "\n".join(
        f'    <li><a href="{_escape(p.name)}">{_escape(_label_for_file(p.name))}</a></li>'
        for p in files[:30]
    )
    index_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>PMP Athena 报告索引</title>
<style>
body {{ font-family: sans-serif; padding: 16px; background: #f7f8fa; }}
h1 {{ font-size: 1.2rem; color: #1e3a8a; }}
ul {{ padding-left: 20px; }}
li {{ margin: 10px 0; }}
a {{ color: #2563eb; text-decoration: none; font-size: 1rem; }}
</style>
</head>
<body>
<h1>📚 PMP Athena 手机报告</h1>
<p>最近更新 {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
<ul>
{items or "    <li>暂无报告，运行 knowledge_report.py generate</li>"}
</ul>
</body>
</html>
"""
    index_path = out / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    return index_path


def list_reports(out_dir: Path | None = None) -> dict[str, Any]:
    out = out_dir or REPORTS_DIR
    if not out.exists():
        return {"status": "empty", "files": [], "text": "📂 reports/ 目录为空"}
    files = sorted(out.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    lines = ["📂 手机报告列表\n"]
    for p in files[:20]:
        lines.append(f"  · {p.name}")
    return {"status": "ok", "files": [p.name for p in files], "text": "\n".join(lines)}


def git_push(paths: list[str] | None = None) -> dict[str, Any]:
    """可选：commit + push reports（需已配置 git remote）。"""
    targets = paths or ["reports/"]
    try:
        subprocess.run(["git", "add", *targets], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True)
        msg = f"reports: update mobile study pages {date.today().isoformat()}"
        r = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0 and "nothing to commit" in (r.stdout + r.stderr):
            return {"status": "ok", "text": "📌 无新变更，跳过 commit"}
        subprocess.run(["git", "push"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True)
        return {"status": "ok", "text": "✅ 已 push 到 GitHub，可在小程序刷新查看"}
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or str(e))[:300]
        return {"status": "error", "text": f"⚠️ git 失败: {err}"}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="PMP Athena 手机 HTML 报告")
    sub = parser.add_subparsers(dest="command")

    p_gen = sub.add_parser("generate", help="生成 HTML 报告")
    p_gen.add_argument("--text", "-t", default="", help="查询词，如 成本管理知识点 / 挣值")
    p_gen.add_argument("--type", default="auto", choices=["auto", "knowledge", "weakness", "plan", "session"])
    p_gen.add_argument("--level", "-l", default="L1", help="L1 | L2 | L3 | combo")
    p_gen.add_argument("--title", help="session 标题")
    p_gen.add_argument("--body", help="session 正文（Markdown/纯文本）")
    p_gen.add_argument("--body-file", help="从文件读取 session 正文")
    p_gen.add_argument("--out", type=Path, default=None, help="输出目录，默认 reports/")
    p_gen.add_argument("--push", action="store_true", help="生成后 git commit + push")
    p_gen.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="列出已有报告")
    p_list.add_argument("--json", action="store_true")

    p_idx = sub.add_parser("index", help="仅刷新 index.html")
    p_idx.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "list":
        result = list_reports()
    elif args.command == "index":
        p = update_index()
        result = {"status": "ok", "path": str(p), "text": f"✅ 已更新 {p}"}
    else:
        body = args.body or ""
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        result = generate_report(
            text=args.text,
            report_type=args.type,
            level=args.level,
            title=args.title or "",
            body=body,
            out_dir=args.out,
        )
        if result.get("status") == "ok" and args.push:
            push_result = git_push()
            result["push"] = push_result
            result["text"] = result.get("text", "") + "\n" + push_result.get("text", "")

    if args.json if hasattr(args, "json") else False:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result.get("text") or json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
