"""
从带答案的模考 PDF 生成「仅试题」PDF，并导出答案钥 JSON。

用法:
  python scripts/strip_mock_answers.py "pmp_notes/模考/新考纲_模拟考试1.pdf"
  python scripts/strip_mock_answers.py input.pdf -o output.pdf --key answers.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pdfplumber
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

Q_SPLIT = re.compile(r"(?=(?:单选题|多选题)\s*\d+/180)")
Q_HEAD = re.compile(r"^(单选题|多选题)\s*(\d+)/180[、.\s]*(.*)$", re.S)
ANS_LINE = re.compile(r"答案[：:]\s*([A-E]+)")
ANS_CUT = re.compile(r"\n?\s*答案[：:]")
JX_CUT = re.compile(r"\n?\s*解析[：:]")


def _register_cjk_font() -> str:
    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttf"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
        Path(r"C:\Windows\Fonts\SIMSUN.TTC"),
    ]
    for p in candidates:
        if not p.exists():
            continue
        name = "CJKFont"
        try:
            pdfmetrics.registerFont(TTFont(name, str(p), subfontIndex=0))
            return name
        except Exception:
            try:
                pdfmetrics.registerFont(TTFont(name, str(p)))
                return name
            except Exception:
                continue
    raise RuntimeError("未找到可用中文字体（msyh/simhei/simsun）")


def strip_answers_from_text(text: str) -> str:
    """去掉答案与解析，保留题干与选项。"""
    text = text.replace("\x00", "")
    chunks = Q_SPLIT.split(text)
    kept: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        chunk = ANS_CUT.split(chunk, maxsplit=1)[0]
        chunk = JX_CUT.split(chunk, maxsplit=1)[0]
        chunk = chunk.rstrip()
        if chunk:
            kept.append(chunk)
    return "\n\n".join(kept).strip()


def extract_answer_key(full_text: str) -> dict[str, str]:
    key: dict[str, str] = {}
    parts = Q_SPLIT.split(full_text)
    for part in parts:
        m = re.search(r"(?:单选题|多选题)\s*(\d+)/180", part)
        a = ANS_LINE.search(part)
        if m and a:
            key[m.group(1)] = a.group(1).upper()
    return dict(sorted(key.items(), key=lambda x: int(x[0])))


def extract_pages(pdf_path: Path) -> tuple[list[str], dict[str, str]]:
    pages_raw: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages_raw.append(page.extract_text() or "")
    full = "\n\n".join(pages_raw)
    answers = extract_answer_key(full)
    cleaned_pages = []
    for raw in pages_raw:
        cleaned = strip_answers_from_text(raw)
        # 整页只剩空白或极短残留（纯答案页）则跳过
        if len(re.sub(r"\s+", "", cleaned)) < 20:
            continue
        cleaned_pages.append(cleaned)
    return cleaned_pages, answers


def _escape_para(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def build_pdf(pages: list[str], out_path: Path, title: str) -> None:
    font = _register_cjk_font()
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "BodyCJK",
        parent=styles["Normal"],
        fontName=font,
        fontSize=10,
        leading=14,
        spaceAfter=6,
    )
    h1 = ParagraphStyle(
        "TitleCJK",
        parent=styles["Heading1"],
        fontName=font,
        fontSize=14,
        leading=18,
        spaceAfter=12,
    )
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=title,
    )
    story = [
        Paragraph(_escape_para(title), h1),
        Paragraph(
            _escape_para("（仅题干与选项 · 供模考作答）"),
            body,
        ),
        Spacer(1, 8),
    ]
    # 合并全文再按题切开，避免跨页题干被拆散后难读
    merged = "\n\n".join(pages)
    chunks = [c.strip() for c in Q_SPLIT.split(merged) if c.strip()]
    if not any(re.search(r"(?:单选题|多选题)\s*\d+/180", c) for c in chunks):
        chunks = pages

    for chunk in chunks:
        story.append(Paragraph(_escape_para(chunk), body))
        story.append(Spacer(1, 10))

    doc.build(story)


def main() -> int:
    ap = argparse.ArgumentParser(description="模考 PDF 去答案")
    ap.add_argument("input", help="带答案的模考 PDF")
    ap.add_argument(
        "-o",
        "--output",
        help="输出无答案 PDF（默认：同目录 *_试题.pdf）",
    )
    ap.add_argument(
        "--key",
        help="答案钥 JSON（默认：同目录 *_答案钥.json）",
    )
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"⚠️ 文件不存在: {src}", file=sys.stderr)
        return 1

    out = Path(args.output) if args.output else src.with_name(src.stem + "_试题.pdf")
    key_path = (
        Path(args.key) if args.key else src.with_name(src.stem + "_答案钥.json")
    )

    pages, answers = extract_pages(src)
    if not pages:
        print("⚠️ 未能提取到可用试题文本", file=sys.stderr)
        return 1

    title = f"{src.stem} · 试题版"
    build_pdf(pages, out, title)

    key_path.write_text(
        json.dumps(
            {
                "source": str(src).replace("\\", "/"),
                "question_count": len(answers),
                "answers": answers,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"✅ 试题 PDF: {out}")
    print(f"✅ 答案钥: {key_path}（{len(answers)} 题）")
    missing = [str(i) for i in range(1, 181) if str(i) not in answers]
    if missing:
        print(f"⚠️ 未解析到答案的题号: {', '.join(missing[:20])}"
              + ("..." if len(missing) > 20 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
