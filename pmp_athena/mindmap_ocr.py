#!/usr/bin/env python3
"""思维导图 PNG → 结构化 Markdown — 批量 OCR + 层级整理。"""
import sys, re
from pathlib import Path
from PIL import Image
import pytesseract

NOTES_DIR = Path(__file__).resolve().parent.parent / "pmp_notes"
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# 文件名 → 标准知识领域映射
NAME_TO_DOMAIN: dict[str, str] = {
    "1.1": "整合管理", "1.2": "整合管理", "1.3": "整合管理",
    "2.1": "整合管理", "2.2": "整合管理",
    "2.3": "整合管理", "2.4": "整合管理", "2.5": "整合管理",
    "3": "敏捷/混合方法",
}

def ocr_image(path: Path) -> str:
    img = Image.open(path)
    return pytesseract.image_to_string(img, lang="chi_sim+eng")

def structure_lines(raw: str) -> list[tuple[int, str]]:
    """按 OCR 文本的行特征推断层级（缩进/编号/符号）。"""
    out: list[tuple[int, str]] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or len(s) < 2:
            continue
        # 推断层级
        depth = 0
        leading = len(line) - len(line.lstrip())
        if leading >= 6: depth = 2
        elif leading >= 3: depth = 1
        # 编号/符号提示层级
        if re.match(r"^[（(]*\d+[\.、．）)]", s): depth = max(depth, 1)
        if re.match(r"^(第[一二三四五六七八九十]|项目)", s): depth = max(depth, 0)
        if s.startswith(("·", "•", "-", "→")): depth = max(depth, 2)
        out.append((depth, s))
    return out

def to_markdown(title: str, items: list[tuple[int, str]], domain: str = "综合") -> str:
    lines = [
        "---",
        f"title: {title}",
        f"domain: {domain}",
        f"source: 思维导图 PNG OCR",
        "---",
        "",
        f"# {title}",
        "",
    ]
    for depth, text in items:
        if depth == 0:
            lines.append(f"## {text}")
        elif depth == 1:
            lines.append(f"- **{text}**")
        else:
            lines.append(f"  - {text}")
    return "\n".join(lines) + "\n"

def main():
    import sys
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

    png_files = sorted(NOTES_DIR.glob("*.png"))
    print(f"Found {len(png_files)} PNG files in {NOTES_DIR}")
    for path in png_files:
        stem = path.stem
        out_path = NOTES_DIR / f"_思维导图_{stem}.md"
        print(f"\n[OCR] {path.name} -> {out_path.name}")
        try:
            raw = ocr_image(path)
            structured = structure_lines(raw)
            domain = NAME_TO_DOMAIN.get(stem[:3], "综合")
            md = to_markdown(stem, structured, domain)
            out_path.write_text(md, encoding="utf-8")
            print(f"  OK: {len(structured)} lines, domain={domain}")
        except Exception as e:
            print(f"  FAIL: {e}")

if __name__ == "__main__":
    main()
