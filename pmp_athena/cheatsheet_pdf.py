#!/usr/bin/env python3
"""
薄弱点速记 → PDF（手机/打印背诵版）

依赖：reportlab + Windows 中文字体（优先微软雅黑/黑体）

CLI:
  python pmp_athena/cheatsheet_pdf.py all
  python pmp_athena/cheatsheet_pdf.py p0          # Process 合订（成本/进度/商业）
  python pmp_athena/cheatsheet_pdf.py overview    # 00 总览三份
  python pmp_athena/cheatsheet_pdf.py area --area 资源管理
  python pmp_athena/cheatsheet_pdf.py today
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from pmp_athena.config import CHEATSHEET_DIR
    from pmp_athena.weak_area_cheatsheet import (
        DOMAIN_FILES,
        DOMAIN_ORDER,
        _resolve_cheatsheet_area,
        _today_cheatsheet_pick,
    )
except ModuleNotFoundError:
    from config import CHEATSHEET_DIR  # type: ignore
    from weak_area_cheatsheet import (  # type: ignore
        DOMAIN_FILES,
        DOMAIN_ORDER,
        _resolve_cheatsheet_area,
        _today_cheatsheet_pick,
    )

PDF_DIR = CHEATSHEET_DIR / "pdf"
# 00 总览合订（跟领域 MD 一起按日导出）
OVERVIEW_PDF_FILES: list[tuple[str, str]] = [
    ("00-P0三领域完整知识点.md", "Process合订_成本进度商业"),
    ("00-考前攻错决策卡.md", "考前攻错决策卡"),
    ("00-三领域对比速记卡.md", "三领域对比速记卡"),
]
_FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\msyh.ttf"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
]


def _find_font() -> Path:
    for p in _FONT_CANDIDATES:
        if p.is_file():
            return p
    raise FileNotFoundError("未找到中文字体（微软雅黑/黑体/宋体）")


def _extract_mnemonic(md: str) -> str:
    m = re.search(r"^>\s*\*\*总口诀\*\*[：:]\s*\*\*(.+?)\*\*", md, re.M)
    if m:
        return m.group(1).strip()
    m = re.search(r"^>\s*\*\*总口诀\*\*[：:]\s*(.+)$", md, re.M)
    return (m.group(1).strip() if m else "").strip("* ")


def _extract_section(md: str, *titles: str) -> str:
    for title in titles:
        pat = rf"^##\s+{re.escape(title)}\s*$"
        m = re.search(pat, md, re.M)
        if not m:
            continue
        start = m.end()
        nxt = re.search(r"^##\s+", md[start:], re.M)
        end = start + (nxt.start() if nxt else len(md[start:]))
        return md[start:end].strip()
    return ""


def _parse_md_table(section: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in section.splitlines():
        if "|" not in line or set(line.strip()) <= {"|", "-", ":", " "}:
            continue
        parts = [p.strip() for p in line.split("|")]
        parts = [p for p in parts if p != ""]
        if len(parts) < 2:
            continue
        if parts[0] in ("背这句", "别踩", "❌ 错", "✅ 对", "错", "对", "问", "答"):
            continue
        rows.append((parts[0], parts[1]))
    return rows


def _plain(text: str) -> str:
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def render_area_pdf(area: str, *, out_dir: Path | None = None) -> Path:
    """生成单个领域速记 PDF，返回路径。"""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    mapped = _resolve_cheatsheet_area(area) or area
    fname = DOMAIN_FILES.get(mapped)
    if not fname:
        raise ValueError(f"无速记文件: {area}")
    md_path = CHEATSHEET_DIR / fname
    if not md_path.is_file():
        raise FileNotFoundError(md_path)

    md = md_path.read_text(encoding="utf-8")
    font_path = _find_font()
    font_name = "CheatCN"
    # ttc 用 subfontIndex=0
    if font_path.suffix.lower() == ".ttc":
        pdfmetrics.registerFont(TTFont(font_name, str(font_path), subfontIndex=0))
    else:
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))

    out_dir = out_dir or (PDF_DIR / date.today().isoformat())
    out_dir.mkdir(parents=True, exist_ok=True)
    # 文件名与源 MD 对齐：01-商业环境.pdf（不加领域后缀）
    out_path = out_dir / f"{Path(fname).stem}.pdf"
    short = "敏捷" if mapped.startswith("敏捷") else mapped

    styles = getSampleStyleSheet()
    title_s = ParagraphStyle(
        "t",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    h2 = ParagraphStyle(
        "h2",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=12,
        spaceBefore=10,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "b",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=9,
        leading=13,
        alignment=TA_LEFT,
    )
    tip = ParagraphStyle(
        "tip",
        parent=body,
        fontSize=10,
        textColor=colors.HexColor("#1a5f2a"),
        spaceAfter=8,
    )
    cell = ParagraphStyle(
        "cell",
        parent=body,
        fontSize=8,
        leading=11,
    )

    story: list = []
    story.append(Paragraph(f"PMP 薄弱点速记 · {short}", title_s))
    story.append(
        Paragraph(
            f"更新日期 {date.today().isoformat()} · 只背左列口诀",
            ParagraphStyle("meta", parent=body, alignment=TA_CENTER, fontSize=8),
        )
    )
    mnemonic = _extract_mnemonic(md)
    if mnemonic:
        story.append(Paragraph(f"总口诀：{_plain(mnemonic)}", tip))

    # 手写易错 + 自动错题口诀
    trap = _extract_section(md, "八、易错陷阱", "七、易错陷阱", "十、易错陷阱")
    auto_rows = _parse_md_table(
        re.split(r"###\s*来自你的错题", trap)[-1] if "来自你的错题" in trap else ""
    )
    hand = trap
    if "###" in trap:
        hand = trap.split("###")[0]
    hand_rows = _parse_md_table(hand)

    if hand_rows:
        story.append(Paragraph("易错对照（手写）", h2))
        data = [[Paragraph("<b>别这样</b>", cell), Paragraph("<b>要这样</b>", cell)]]
        for a, b in hand_rows[:16]:
            data.append([Paragraph(_plain(a), cell), Paragraph(_plain(b), cell)])
        t = Table(data, colWidths=[75 * mm, 95 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(t)

    if auto_rows:
        story.append(Paragraph("来自你的错题（自动 · 背左列）", h2))
        data = [[Paragraph("<b>背这句</b>", cell), Paragraph("<b>别踩</b>", cell)]]
        for a, b in auto_rows[:12]:
            data.append([Paragraph(_plain(a), cell), Paragraph(_plain(b), cell)])
        t = Table(data, colWidths=[85 * mm, 85 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecfdf5")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(t)

    # 闪卡
    flash = _extract_section(md, "🃏 闪卡", "🃏 闪卡（遮住右列自测）")
    flash_rows = _parse_md_table(flash)
    if flash_rows:
        story.append(Paragraph("闪卡自测", h2))
        data = [[Paragraph("<b>问</b>", cell), Paragraph("<b>答</b>", cell)]]
        for a, b in flash_rows[:12]:
            data.append([Paragraph(_plain(a), cell), Paragraph(_plain(b), cell)])
        t = Table(data, colWidths=[70 * mm, 100 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fff7ed")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(t)

    chain = _extract_section(md, "九、做题决策链", "八、做题决策链", "十一、做题决策链")
    if chain:
        story.append(Paragraph("做题决策链", h2))
        code = re.search(r"```(?:\w+)?\n(.*?)```", chain, re.S)
        blob = code.group(1).strip() if code else chain
        for line in blob.splitlines():
            line = line.rstrip()
            if not line.strip():
                story.append(Spacer(1, 2))
                continue
            story.append(Paragraph(_plain(line).replace(" ", "&nbsp;"), body))

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"薄弱点速记-{short}",
    )
    doc.build(story)
    return out_path


def _register_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_path = _find_font()
    font_name = "CheatCN"
    if font_path.suffix.lower() == ".ttc":
        pdfmetrics.registerFont(TTFont(font_name, str(font_path), subfontIndex=0))
    else:
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    return font_name


def _escape_xml(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_overview_pdf(
    md_name: str,
    *,
    label: str | None = None,
    out_dir: Path | None = None,
) -> Path:
    """把 00-*.md 全文结构导出为 PDF（合订/决策卡/对比卡）。"""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    md_path = CHEATSHEET_DIR / md_name
    if not md_path.is_file():
        raise FileNotFoundError(md_path)
    md = md_path.read_text(encoding="utf-8")
    font_name = _register_font()

    out_dir = out_dir or (PDF_DIR / date.today().isoformat())
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = label or md_path.stem
    out_path = out_dir / f"{md_path.stem}.pdf"

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "ov_h1", parent=styles["Heading1"], fontName=font_name,
        fontSize=14, spaceBefore=8, spaceAfter=6, alignment=TA_CENTER,
    )
    h2 = ParagraphStyle(
        "ov_h2", parent=styles["Heading2"], fontName=font_name,
        fontSize=11, spaceBefore=8, spaceAfter=3,
    )
    h3 = ParagraphStyle(
        "ov_h3", parent=styles["Heading3"], fontName=font_name,
        fontSize=10, spaceBefore=6, spaceAfter=2,
    )
    body = ParagraphStyle(
        "ov_b", parent=styles["Normal"], fontName=font_name,
        fontSize=8.5, leading=12, alignment=TA_LEFT,
    )
    quote = ParagraphStyle(
        "ov_q", parent=body, textColor=colors.HexColor("#374151"),
        leftIndent=6, spaceBefore=2, spaceAfter=2,
    )
    code_s = ParagraphStyle(
        "ov_c", parent=body, fontName=font_name, fontSize=7.5, leading=10,
        backColor=colors.HexColor("#f3f4f6"), leftIndent=4, rightIndent=4,
    )
    cell = ParagraphStyle(
        "ov_cell", parent=body, fontSize=7.5, leading=10,
    )

    story: list = []
    story.append(Paragraph(f"PMP 薄弱点速记 · {_escape_xml(stem)}", h1))
    story.append(
        Paragraph(
            f"更新日期 {date.today().isoformat()}",
            ParagraphStyle("ov_meta", parent=body, alignment=TA_CENTER, fontSize=8),
        )
    )
    story.append(Spacer(1, 4))

    lines = md.splitlines()
    i = 0
    in_code = False
    code_buf: list[str] = []

    def flush_code() -> None:
        nonlocal code_buf
        if not code_buf:
            return
        text = "\n".join(code_buf)
        # Preformatted 对中文 TTF 支持一般，改逐行 Paragraph
        block: list = []
        for ln in text.splitlines() or [""]:
            block.append(Paragraph(_escape_xml(ln) or "&nbsp;", code_s))
        story.append(KeepTogether(block))
        story.append(Spacer(1, 4))
        code_buf = []

    while i < len(lines):
        raw = lines[i]
        if raw.strip().startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(raw)
            i += 1
            continue

        # 表格块
        if raw.strip().startswith("|") and "|" in raw.strip()[1:]:
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            rows_raw = []
            for tl in table_lines:
                if set(tl.strip()) <= {"|", "-", ":", " "}:
                    continue
                parts = [p.strip() for p in tl.split("|")]
                parts = [p for p in parts if p != ""]
                if parts:
                    rows_raw.append(parts)
            if rows_raw:
                ncols = max(len(r) for r in rows_raw)
                usable = 170 * mm
                col_w = usable / ncols
                data = []
                for ri, r in enumerate(rows_raw):
                    padded = r + [""] * (ncols - len(r))
                    data.append(
                        [Paragraph(_escape_xml(_plain(c)), cell) for c in padded]
                    )
                t = Table(data, colWidths=[col_w] * ncols, repeatRows=1)
                t.setStyle(
                    TableStyle(
                        [
                            ("FONTNAME", (0, 0), (-1, -1), font_name),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
                            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 3),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                            ("TOPPADDING", (0, 0), (-1, -1), 2),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                        ]
                    )
                )
                story.append(t)
                story.append(Spacer(1, 4))
            continue

        s = raw.strip()
        if not s:
            story.append(Spacer(1, 3))
            i += 1
            continue
        if s.startswith("# "):
            story.append(Paragraph(_escape_xml(_plain(s[2:])), h1))
        elif s.startswith("## "):
            story.append(Paragraph(_escape_xml(_plain(s[3:])), h2))
        elif s.startswith("### "):
            story.append(Paragraph(_escape_xml(_plain(s[4:])), h3))
        elif s.startswith(">"):
            story.append(Paragraph(_escape_xml(_plain(s.lstrip("> ").strip())), quote))
        elif s.startswith("---"):
            story.append(Spacer(1, 6))
        else:
            story.append(Paragraph(_escape_xml(_plain(s)), body))
        i += 1

    if in_code:
        flush_code()

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=f"薄弱点速记-{stem}",
    )
    doc.build(story)
    return out_path


def render_all(*, out_dir: Path | None = None) -> list[Path]:
    out_dir = out_dir or (PDF_DIR / date.today().isoformat())
    paths: list[Path] = []
    for md_name, label in OVERVIEW_PDF_FILES:
        try:
            paths.append(render_overview_pdf(md_name, label=label, out_dir=out_dir))
        except Exception as e:
            print(f"⚠️ {md_name}: {e}", file=sys.stderr)
    for area in DOMAIN_ORDER:
        try:
            paths.append(render_area_pdf(area, out_dir=out_dir))
        except Exception as e:
            print(f"⚠️ {area}: {e}", file=sys.stderr)
    return paths


def render_today() -> Path:
    area, _why = _today_cheatsheet_pick()
    return render_area_pdf(area)


def render_p0() -> Path:
    """Process 合订（成本/进度/商业）。"""
    return render_overview_pdf(
        "00-P0三领域完整知识点.md",
        label="Process合订_成本进度商业",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="薄弱点速记导出 PDF")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("all", help="全部领域 + 00 总览合订")
    sub.add_parser("today", help="今日推荐领域")
    sub.add_parser("p0", help="导出 Process 合订（成本/进度/商业）")
    sub.add_parser("overview", help="只导出 00 总览三份")
    p_area = sub.add_parser("area", help="指定领域")
    p_area.add_argument("--area", required=True)
    args = parser.parse_args()
    cmd = args.command or "today"

    if cmd == "all":
        paths = render_all()
        print(f"✅ 已生成 {len(paths)} 份 PDF → {PDF_DIR / date.today().isoformat()}")
        for p in paths:
            print(f"  {p.name}")
    elif cmd == "overview":
        paths = []
        for md_name, label in OVERVIEW_PDF_FILES:
            paths.append(render_overview_pdf(md_name, label=label))
        print(f"✅ 已生成 {len(paths)} 份总览 PDF")
        for p in paths:
            print(f"  {p}")
    elif cmd == "p0":
        p = render_p0()
        print(f"✅ {p}")
    elif cmd == "area":
        p = render_area_pdf(args.area)
        print(f"✅ {p}")
    else:
        p = render_today()
        print(f"✅ {p}")


if __name__ == "__main__":
    main()
