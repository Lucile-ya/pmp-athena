"""
以 模拟题1.docx 为准，重建 新考纲_模拟考试1_答案钥.json。

案例内「问题1/2/3…」映射为：最近一次「单选题 N/180」起的 N、N+1、N+2…
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parent.parent
DOCX = ROOT / "pmp_notes" / "模考" / "模拟题1.docx"
OUT = ROOT / "pmp_notes" / "模考" / "新考纲_模拟考试1_答案钥.json"
OLD = OUT  # compare in-place previous if exists

Q_GLOBAL = re.compile(r"^(?:单选题|多选题)\s*(\d+)/180")
Q_CASE = re.compile(r"^问题\s*(\d+)\s*[：:]")
ANS = re.compile(r"答案\s*[：:]\s*([A-Ea-e]{1,5})")


def normalize_answer(raw: str) -> str:
    letters = re.findall(r"[A-Ea-e]", raw)
    # 多选保持出现顺序去重；判卷侧通常再排序等价
    seen: list[str] = []
    for ch in letters:
        u = ch.upper()
        if u not in seen:
            seen.append(u)
    return "".join(seen)


def extract_answers(docx_path: Path) -> dict[str, str]:
    doc = Document(str(docx_path))
    texts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    answers: dict[str, str] = {}
    current: int | None = None
    case_base: int | None = None

    for t in texts:
        gm = Q_GLOBAL.match(t)
        if gm:
            current = int(gm.group(1))
            case_base = current
            continue

        cm = Q_CASE.match(t)
        if cm and case_base is not None:
            current = case_base + int(cm.group(1)) - 1
            continue

        am = ANS.search(t)
        if am and current is not None:
            answers[str(current)] = normalize_answer(am.group(1))
            # 同一案例连续「问题K」下，答完一题后默认指向下一题号，
            # 若下一段是新的全局题号/问题K 会再覆盖。
            current += 1

    return dict(sorted(answers.items(), key=lambda x: int(x[0])))


def main() -> int:
    if not DOCX.exists():
        print(f"⚠️ 找不到 {DOCX}", file=sys.stderr)
        return 1

    prev = {}
    if OLD.exists():
        try:
            prev = json.loads(OLD.read_text(encoding="utf-8")).get("answers") or {}
        except json.JSONDecodeError:
            prev = {}

    answers = extract_answers(DOCX)
    missing = [str(i) for i in range(1, 181) if str(i) not in answers]
    extra = [k for k in answers if int(k) < 1 or int(k) > 180]

    diffs = []
    for i in range(1, 181):
        k = str(i)
        if answers.get(k) != prev.get(k):
            diffs.append({"q": k, "before": prev.get(k), "docx": answers.get(k)})

    payload = {
        "source": "pmp_notes/模考/模拟题1.docx",
        "source_note": "答案以 docx 为准（覆盖 PDF 内联答案）",
        "question_count": len(answers),
        "answers": answers,
        "missing_questions": missing,
        "changed_from_previous": diffs,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"✅ 已写入 {OUT}")
    print(f"   题数: {len(answers)}/180")
    if missing:
        print(f"⚠️ 缺失题号: {', '.join(missing)}")
    if extra:
        print(f"⚠️ 异常题号: {', '.join(extra)}")
    print(f"   相对旧钥变更: {len(diffs)} 题")
    for d in diffs[:25]:
        print(f"   Q{d['q']}: {d['before']} → {d['docx']}")
    if len(diffs) > 25:
        print(f"   ...另有 {len(diffs) - 25} 题")
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
