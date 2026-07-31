#!/usr/bin/env python3
"""
多图关联入库 —— 题干截图 + 解析截图自动合并后录入错题。

用法:
    python pmp_athena/multi_screenshot_merge.py img1.png img2.png --json
    python pmp_athena/multi_screenshot_merge.py img1.png img2.png --caption "选错了" --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

QUESTION_NUM_PATTERNS = (
    re.compile(r"[Qq](\d+)"),
    re.compile(r"第(\d+)题"),
    re.compile(r"题号[：:\s]*(\d+)"),
    re.compile(r"^(\d+)[、.．)]"),
)

EXPLANATION_MARKERS = ("【解析】", "答案详解", "详解", "解析", "解释")
PRIMARY_MARKERS = ("我的答案", "正确答案", "作答错误", "作答正确")
STEM_MIN_LEN = 6
STEM_KEY_LEN = 20
OVERLAP_MIN = 8


@dataclass
class ScreenshotSlice:
    index: int
    path: str
    ocr_text: str = ""
    validation: dict = field(default_factory=dict)
    role: str = "unknown"
    question_num: str | None = None
    question: str | None = None
    explanation: str | None = None

    def stem_key(self) -> str | None:
        q = (self.question or "").strip()
        if not q:
            return None
        norm = re.sub(r"\s+", "", q)
        if len(norm) < STEM_MIN_LEN:
            return None
        return norm[:STEM_KEY_LEN]

    def match_key(self) -> str:
        if self.question_num:
            return f"num:{self.question_num}"
        sk = self.stem_key()
        if sk:
            return f"stem:{sk}"
        return f"idx:{self.index}"


def _import_processor():
    try:
        from pmp_athena.image_processor import (
            AnswerValidator,
            clean_explanation_text,
            process_and_validate,
        )
    except ModuleNotFoundError:
        from image_processor import (
            AnswerValidator,
            clean_explanation_text,
            process_and_validate,
        )
    return AnswerValidator, clean_explanation_text, process_and_validate


def extract_question_num(text: str) -> str | None:
    if not text:
        return None
    for pat in QUESTION_NUM_PATTERNS:
        m = pat.search(text.strip())
        if m:
            return m.group(1)
    return None


def extract_explanation_body(text: str, max_len: int = 200) -> str:
    if not text:
        return ""
    _, clean_explanation_text, _ = _import_processor()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        for marker in EXPLANATION_MARKERS:
            if marker in line:
                parts = [line.split(marker, 1)[-1].strip() or line]
                for j in range(i + 1, min(i + 10, len(lines))):
                    nxt = lines[j]
                    if any(m in nxt for m in PRIMARY_MARKERS):
                        break
                    if re.match(r"^[A-E@][.、．)]", nxt):
                        break
                    parts.append(nxt)
                return clean_explanation_text(" ".join(parts), max_len=max_len)
    # 整页像解析：取最长中文段
    best = ""
    for line in lines:
        if len(line) > len(best) and re.search(r"[\u4e00-\u9fff]", line):
            if not re.match(r"^\d{1,2}:\d{2}", line):
                best = line
    return clean_explanation_text(best, max_len=max_len) if best else ""


def classify_slice(slice_: ScreenshotSlice) -> str:
    ext = slice_.validation.get("extracted") or {}
    text = slice_.ocr_text or ""
    has_question = bool(ext.get("question"))
    has_options = len(ext.get("options") or {}) >= 2
    has_answers = bool(ext.get("my_answer") or ext.get("correct_answer"))
    has_expl_marker = any(m in text for m in EXPLANATION_MARKERS)
    expl_body = extract_explanation_body(text)

    if has_question or has_options or has_answers:
        if has_expl_marker and expl_body:
            return "mixed"
        return "primary"

    if has_expl_marker or (expl_body and len(expl_body) >= 15):
        return "secondary"

    st = slice_.validation.get("screenshot_type")
    if st == "error_result":
        return "primary"
    if st == "plain_question":
        return "primary"
    return "unknown"


def stems_overlap(a: str | None, b: str | None) -> bool:
    na = re.sub(r"\s+", "", a or "")[:STEM_KEY_LEN]
    nb = re.sub(r"\s+", "", b or "")[:STEM_KEY_LEN]
    if len(na) < STEM_MIN_LEN or len(nb) < STEM_MIN_LEN:
        return False
    if na == nb:
        return True
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    return short[:OVERLAP_MIN] in long


def keys_match(a: ScreenshotSlice, b: ScreenshotSlice) -> bool:
    if a.question_num and b.question_num:
        return a.question_num == b.question_num
    if stems_overlap(a.question, b.question):
        return True
    # 副图题干摘要出现在主图题干中
    sec_q = extract_explanation_body(b.ocr_text) or b.question or ""
    if a.question and sec_q and len(sec_q) >= STEM_MIN_LEN:
        if re.sub(r"\s+", "", sec_q)[:OVERLAP_MIN] in re.sub(r"\s+", "", a.question):
            return True
    return False


def ocr_slice(index: int, path: str, user_caption: str | None) -> ScreenshotSlice:
    AnswerValidator, _, process_and_validate = _import_processor()
    # 配文只合并进第一张（题目图通常在先）
    cap = user_caption if index == 0 else None
    result = process_and_validate(
        path,
        run_ocr=True,
        validate_answer=True,
        auto_log_errors=False,
        user_caption=cap,
    )
    validation = result.get("answer_validation") or {}
    ext = validation.get("extracted") or {}
    ocr_text = result.get("ocr_text") or ""

    sl = ScreenshotSlice(
        index=index,
        path=path,
        ocr_text=ocr_text,
        validation=validation,
        question=ext.get("question"),
        explanation=ext.get("explanation"),
    )
    sl.question_num = extract_question_num(ocr_text) or extract_question_num(sl.question or "")
    sl.role = classify_slice(sl)
    if sl.role == "secondary" and not sl.explanation:
        sl.explanation = extract_explanation_body(ocr_text)
    return sl


def group_slices(slices: list[ScreenshotSlice]) -> tuple[list[dict], list[ScreenshotSlice]]:
    """返回 (groups, unmatched_secondaries)。"""
    primaries = [s for s in slices if s.role in ("primary", "mixed")]
    secondaries = [s for s in slices if s.role == "secondary"]
    unknowns = [s for s in slices if s.role == "unknown"]

    # unknown 但有题干 → 当 primary
    for u in unknowns:
        if u.question:
            primaries.append(u)
        elif extract_explanation_body(u.ocr_text):
            secondaries.append(u)

    groups: list[dict[str, Any]] = []
    used_secondary: set[int] = set()

    for p in primaries:
        matched_secs: list[ScreenshotSlice] = []
        for sec in secondaries:
            if sec.index in used_secondary:
                continue
            if keys_match(p, sec):
                matched_secs.append(sec)
                used_secondary.add(sec.index)
        groups.append({"primary": p, "secondaries": matched_secs})

    unmatched = [s for s in secondaries if s.index not in used_secondary]

    # 兜底：仅 1 主 + 1 副 → 强制配对
    if len(groups) == 1 and len(unmatched) == 1 and not groups[0]["secondaries"]:
        groups[0]["secondaries"] = unmatched
        unmatched = []

    return groups, unmatched


def _question_for_bank(primary: ScreenshotSlice) -> str:
    AnswerValidator, _, _ = _import_processor()
    ext = dict(primary.validation.get("extracted") or {})
    if not ext.get("options") and primary.validation.get("formatted_question"):
        fq = primary.validation["formatted_question"]
        return fq.replace("📝 ", "", 1) if fq.startswith("📝 ") else fq
    v = AnswerValidator()
    if ext.get("question") or ext.get("options"):
        text = v.format_question_for_display(ext)
        return text.replace("📝 ", "", 1) if text.startswith("📝 ") else text
    return primary.question or "（OCR 题目提取不完整）"


def merge_group(group: dict) -> dict[str, Any]:
    primary: ScreenshotSlice = group["primary"]
    secondaries: list[ScreenshotSlice] = group.get("secondaries") or []
    ext = dict(primary.validation.get("extracted") or {})

    explanation = (ext.get("explanation") or primary.explanation or "").strip()
    for sec in secondaries:
        exp = (sec.explanation or extract_explanation_body(sec.ocr_text)).strip()
        if exp and exp not in explanation:
            explanation = f"{explanation} {exp}".strip() if explanation else exp
    explanation = explanation[:200]

    my_answer = ext.get("my_answer")
    correct_answer = ext.get("correct_answer")
    knowledge_area = ext.get("knowledge_area") or "综合"
    question = _question_for_bank(primary)

    return {
        "question": question,
        "my_answer": my_answer,
        "correct_answer": correct_answer,
        "knowledge_area": knowledge_area,
        "explanation": explanation,
        "primary_index": primary.index + 1,
        "secondary_indices": [s.index + 1 for s in secondaries],
        "can_log": bool(my_answer and correct_answer and my_answer != correct_answer),
        "is_correct": my_answer == correct_answer if my_answer and correct_answer else None,
    }


def process_multi_screenshot(
    image_paths: list[str],
    user_caption: str | None = None,
) -> dict[str, Any]:
    if len(image_paths) < 2:
        return {"status": "error", "error": "需要至少 2 张图片"}

    slices = [ocr_slice(i, p, user_caption) for i, p in enumerate(image_paths)]
    groups, unmatched = group_slices(slices)

    if not groups:
        return {
            "status": "unmatched",
            "message": _format_unmatched_prompt(slices, unmatched, reason="no_primary"),
            "slices": [_slice_summary(s) for s in slices],
        }

    merged_list = [merge_group(g) for g in groups]
    loggable = [m for m in merged_list if m["can_log"]]

    if not loggable:
        # 有合但缺答案
        if unmatched:
            return {
                "status": "unmatched",
                "message": _format_unmatched_prompt(slices, unmatched, merged_list),
                "merged": merged_list,
                "slices": [_slice_summary(s) for s in slices],
            }
        missing = [m for m in merged_list if not m.get("my_answer") or not m.get("correct_answer")]
        if missing:
            prev = (missing[0].get("question") or "")[:50]
            return {
                "status": "need_answers",
                "message": (
                    "⚠️ 多图已关联，但缺少答案信息，无法入库。\n"
                    f"📝 {prev}{'…' if len(prev) >= 50 else ''}\n"
                    "请补充：我的答案 X，正确答案 Y"
                ),
                "merged": merged_list,
            }
        return {
            "status": "correct",
            "message": "✅ 识别为答对，无需录入错题。",
            "merged": merged_list,
        }

    try:
        from pmp_athena.record_answer import record_wrong_answer
    except ModuleNotFoundError:
        from record_answer import record_wrong_answer

    logged = []
    for m in loggable:
        rec = record_wrong_answer(
            question=m["question"],
            my_answer=m["my_answer"],
            correct_answer=m["correct_answer"],
            knowledge_area=m["knowledge_area"],
            explanation=m.get("explanation") or "",
            source="screenshot",
            parsed_by="multi_screenshot_merge",
        )
        logged.append({**m, **rec})

    reply_parts = [
        f"✅ 多图关联入库完成（{len(logged)} 道）",
    ]
    for item in logged:
        qprev = (item.get("question") or "")[:50]
        sec_note = ""
        if item.get("secondary_indices"):
            sec_note = f" ← 关联图 {','.join(map(str, item['secondary_indices']))}"
        reply_parts.append(
            f"\n📌 错题 #{item['error_log_id']} [{item.get('knowledge_area', '综合')}]{sec_note}\n"
            f"📝 {qprev}{'…' if len(qprev) >= 50 else ''}\n"
            f"❌ {item['my_answer']} → ✅ {item['correct_answer']}"
        )
    if unmatched:
        reply_parts.append("\n" + _format_unmatched_secondary(unmatched))

    reply_parts.append("\n💾 已同步 question_bank.json + error_review_state.json")

    return {
        "status": "logged",
        "message": "".join(reply_parts),
        "logged": logged,
        "merged": merged_list,
        "unmatched_secondaries": [_slice_summary(s) for s in unmatched],
    }


def _slice_summary(s: ScreenshotSlice) -> dict:
    return {
        "index": s.index + 1,
        "role": s.role,
        "question_num": s.question_num,
        "question_preview": (s.question or extract_explanation_body(s.ocr_text) or "")[:40],
    }


def _format_unmatched_secondary(unmatched: list[ScreenshotSlice]) -> str:
    lines = ["⚠️ 以下解析图未能匹配到题目："]
    for s in unmatched:
        prev = (s.explanation or extract_explanation_body(s.ocr_text) or "（未识别）")[:40]
        lines.append(f"  · 图{s.index + 1}：{prev}…")
    lines.append("请确认是否为同一题，或分条重新发送。")
    return "\n".join(lines)


def _format_unmatched_prompt(
    slices: list[ScreenshotSlice],
    unmatched: list[ScreenshotSlice],
    merged_list: list[dict] | None = None,
    reason: str = "",
) -> str:
    lines = ["⚠️ 无法自动匹配多图内容，请确认："]
    for s in slices:
        role_label = {"primary": "题目", "secondary": "解析", "mixed": "题目+解析"}.get(
            s.role, "未识别"
        )
        prev = (s.question or s.explanation or extract_explanation_body(s.ocr_text) or "—")[:45]
        lines.append(f"  图{s.index + 1}（{role_label}）：{prev}…")
    if merged_list:
        lines.append("\n已部分关联，但仍缺答案或题号不一致。")
    if unmatched:
        lines.append("\n未匹配的解析图：")
        for s in unmatched:
            prev = (s.explanation or "—")[:40]
            lines.append(f"  · 图{s.index + 1}：{prev}…")
    lines.append("\n💡 可回复「图2是图1的解析」，或合并配文：我的答案 X，正确答案 Y")
    return "\n".join(lines)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="多图关联错题入库")
    parser.add_argument("images", nargs="+", help="截图路径（按发送顺序）")
    parser.add_argument("--caption", default=None, help="用户配文")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    out = process_multi_screenshot(args.images, args.caption)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(out.get("message") or json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
