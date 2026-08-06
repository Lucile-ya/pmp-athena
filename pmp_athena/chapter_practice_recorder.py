#!/usr/bin/env python3
"""
章节练习统计截图录入 —— OCR + 写入 exam_records.json

用法:
    python pmp_athena/chapter_practice_recorder.py record \\
        --image stats.png --chapter 范围管理 --json

    python pmp_athena/chapter_practice_recorder.py parse --image stats.png
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pmp_athena.analyze_exam import HAS_TESSERACT, _extract_time_minutes, _norm, parse_exam_text
from pmp_athena.exam_recorder import ExamRecorder, KNOWLEDGE_AREAS

CHAPTER_ALIASES: dict[str, str] = {
    "项目整合管理": "整合管理",
    "项目范围管理": "范围管理",
    "项目进度管理": "进度管理",
    "项目成本管理": "成本管理",
    "项目质量管理": "质量管理",
    "项目资源管理": "资源管理",
    "项目沟通管理": "沟通管理",
    "项目风险管理": "风险管理",
    "项目采购管理": "采购管理",
    "项目干系人管理": "干系人管理",
    "整合": "整合管理",
    "整体": "整合管理",
    "范围": "范围管理",
    "进度": "进度管理",
    "时间": "进度管理",
    "成本": "成本管理",
    "费用": "成本管理",
    "质量": "质量管理",
    "资源": "资源管理",
    "团队": "资源管理",
    "沟通": "沟通管理",
    "风险": "风险管理",
    "采购": "采购管理",
    "干系人": "干系人管理",
    "相关方": "干系人管理",
    "敏捷": "敏捷/混合方法",
    "混合": "敏捷/混合方法",
    "商业": "商业环境",
    "领导力": "领导力/人员",
    "人员": "领导力/人员",
}

STATS_MARKERS = (
    "正确率", "总题数", "答对", "答错", "用时", "耗时",
    "章节练习", "练习统计", "做题报告", "刷题报告", "正确题数",
)

PENDING_PATH = Path(__file__).resolve().parent.parent / "pmp_notes" / "chapter_practice_pending.json"


def ocr_image(image_path: str | Path) -> str:
    from pmp_athena.image_processor import ImageProcessor

    proc = ImageProcessor()
    result = proc.process(image_path, run_ocr=True)
    return result.get("ocr_text") or ""


def map_chapter_to_area(chapter: str) -> str:
    t = (chapter or "").strip().replace("\u200b", "")
    if not t:
        return "综合"

    # 完整章节名优先（如「项目成本管理」）
    for alias, area in sorted(CHAPTER_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in t or t == alias:
            return area

    for area in KNOWLEDGE_AREAS:
        if area == t or area in t:
            return area

    for alias, area in CHAPTER_ALIASES.items():
        if alias == t or t.startswith(alias):
            return area

    return t if t in KNOWLEDGE_AREAS else "综合"


def extract_chapter_from_caption(caption: str) -> str | None:
    if not caption or not caption.strip():
        return None
    for alias, area in sorted(CHAPTER_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in caption:
            return area
    for area in KNOWLEDGE_AREAS:
        if area in caption:
            return area
    for alias, area in CHAPTER_ALIASES.items():
        if re.search(rf"(?<![\u4e00-\u9fff]){re.escape(alias)}", caption):
            return area
    return None


CHAPTER_TOTAL_CANDIDATES = (10, 15, 20, 25, 30, 40, 50, 60, 80, 100)


def _extract_percent_value(ocr_text: str) -> int | None:
    for pat in (
        r"正确率\s*[:：]?\s*(\d{1,3})\s*[%％]",
        r"(\d{1,3})\s*[%％]\s*(?:正确率|°\?)?",
    ):
        m = re.search(pat, ocr_text)
        if m:
            return int(m.group(1))
    return None


def _parse_garbled_duration(ocr_text: str) -> int | None:
    """OCR 乱码如 105} 598 → 10分59秒。"""
    m = re.search(r"(\d{2,3})\s*[}:]\s*(\d{2,3})", ocr_text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(0))
    if len(digits) < 4:
        return None
    mins = int(digits[:2])
    secs = int(digits[2:4])
    if 0 <= mins <= 120 and 0 <= secs <= 59:
        return mins + (1 if secs >= 30 else 0)
    return None


def _reconcile_chapter_stats(
    ocr_text: str,
    total: int | None,
    correct: int | None,
    wrong: int | None,
    correct_rate: float | None,
    time_min: int | None,
) -> tuple[int | None, int | None, int | None, int | None]:
    """弱 OCR 下用正确率 + 常见题量推断，避免把 20% 误当总题数。"""
    pct_num = _extract_percent_value(ocr_text)

    if correct_rate is not None and 0 < correct_rate <= 1:
        nums = [int(x) for x in re.findall(r"(?<![\d.])(\d{1,3})(?![\d%％])", ocr_text)]
        best: tuple[int, int, int] | None = None
        for cand_total in nums:
            if pct_num is not None and cand_total == pct_num:
                continue
            if cand_total < 5 or cand_total > 200:
                continue
            exp_correct = round(cand_total * correct_rate)
            if exp_correct < 0 or exp_correct > cand_total:
                continue
            if abs(exp_correct / cand_total - correct_rate) > 0.05:
                continue

            score = 0
            if cand_total in CHAPTER_TOTAL_CANDIDATES:
                score += 3
            if re.search(rf"(?<![\d]){exp_correct}\s*题", ocr_text):
                score += 4
            elif str(exp_correct) in ocr_text:
                score += 2
            if total == cand_total and correct == exp_correct:
                score += 2
            if total == pct_num and cand_total != pct_num:
                score += 5

            if best is None or score > best[0]:
                best = (score, cand_total, exp_correct)

        if best and best[0] >= 3:
            total, correct = best[1], best[2]

    if time_min is None:
        time_min = _parse_garbled_duration(ocr_text)

    if total and correct is None and wrong is not None:
        correct = total - wrong
    if total and wrong is None and correct is not None:
        wrong = total - correct

    return total, correct, wrong, time_min


def parse_chapter_practice_text(ocr_text: str) -> dict[str, Any]:
    base = parse_exam_text(ocr_text)
    full = _norm(ocr_text.replace("\n", " "))

    correct_rate: float | None = None
    for pat in (
        r"正确率\s*[:：]?\s*(\d+\.?\d*)\s*[%％]",
        r"(\d+\.?\d*)\s*[%％]\s*(?:正确率)?",
        r"准确率\s*[:：]?\s*(\d+\.?\d*)\s*[%％]",
    ):
        m = re.search(pat, full)
        if m:
            val = float(m.group(1))
            correct_rate = val / 100 if val > 1 else val
            break

    total = base.get("total_questions")
    correct = base.get("correct_count")
    wrong = base.get("wrong_count")
    time_min = base.get("time_used_minutes")

    pct_num = _extract_percent_value(ocr_text)
    if pct_num is not None and total == pct_num and correct_rate is not None:
        total = None
        if correct is not None and correct == round(total or pct_num * correct_rate):
            correct = None

    if total is None or correct is None:
        for m in re.finditer(r"(\d{1,3})\s*[/／]\s*(\d{1,3})", full):
            a, b = int(m.group(1)), int(m.group(2))
            if 1 <= b <= 100 and 0 <= a <= b:
                correct, total = a, b
                break

    if time_min is None:
        m = re.search(
            r"(?:用时|耗时|答题用时)\s*[:：]?\s*(\d+\s*(?:小时|h))?\s*(\d+\s*(?:分钟|分|min))?",
            full,
        )
        if m:
            time_min = _extract_time_minutes(m.group(0))
        else:
            m2 = re.search(r"(?:用时|耗时)\s*[:：]?\s*(\d{1,3})", full)
            if m2:
                n = int(m2.group(1))
                if 1 <= n <= 300:
                    time_min = n

    # 刷题 App 布局：总题数 30   6题   10分:59秒
    if total is None or correct is None:
        m = re.search(
            r"(\d{1,3})\s+(\d{1,3})\s*题?\s+(\d{1,2})\s*分\s*[:：]?\s*(\d{1,2})\s*秒",
            ocr_text.replace("\n", " "),
        )
        if m:
            total = int(m.group(1))
            correct = int(m.group(2))
            time_min = int(m.group(3)) + (1 if int(m.group(4)) >= 30 else 0)

    if time_min is None:
        m = re.search(r"(\d{1,2})\s*分\s*[:：]?\s*(\d{1,2})\s*秒", ocr_text)
        if m:
            time_min = int(m.group(1)) + (1 if int(m.group(2)) >= 30 else 0)

    # 正确率 + 总题数/答对：从整数列推断
    if (total is None or correct is None) and correct_rate is not None:
        nums = [int(x) for x in re.findall(r"\b(\d{1,3})\b", ocr_text) if 1 <= int(x) <= 100]
        for i, n in enumerate(nums):
            if n >= 10 and i + 1 < len(nums):
                cand_total, cand_correct = n, nums[i + 1]
                if cand_correct <= cand_total:
                    if abs(cand_correct / cand_total - correct_rate) < 0.05:
                        total, correct = cand_total, cand_correct
                        break
        if total and correct is None:
            correct = round(total * correct_rate)
        elif correct_rate and total is None and len(nums) >= 1:
            for n in nums:
                if n >= 10:
                    total = n
                    correct = round(n * correct_rate)
                    break

    if time_min is None:
        time_min = _parse_garbled_duration(ocr_text)

    total, correct, wrong, time_min = _reconcile_chapter_stats(
        ocr_text, total, correct, wrong, correct_rate, time_min
    )

    if correct_rate is None and total and correct is not None and total > 0:
        correct_rate = correct / total

    return {
        "total_questions": total,
        "correct_count": correct,
        "wrong_count": wrong,
        "correct_rate": correct_rate,
        "time_used_minutes": time_min,
        "raw_text": ocr_text,
    }


def is_chapter_practice_screenshot(ocr_text: str) -> bool:
    if not ocr_text:
        return False
    hits = sum(1 for m in STATS_MARKERS if m in ocr_text)
    if hits >= 2:
        return True
    if "正确率" in ocr_text and re.search(r"\d+\s*[/／]\s*\d+", ocr_text):
        return True
    if "章节练习" in ocr_text:
        return True
    if "练习统计" in ocr_text and "正确率" in ocr_text:
        return True
    if "本次练习" in ocr_text and re.search(r"\d+\s*[%％°?]", ocr_text):
        return True
    if re.search(r"\d+\s*[%％]", ocr_text) and re.search(r"\b30\b", ocr_text):
        if "练习" in ocr_text or "题" in ocr_text or "及格" in ocr_text:
            return True
    return False


def format_confirm_reply(area: str, record: dict) -> str:
    total = record.get("total_questions") or 0
    correct = record.get("correct_count") or 0
    rate = record.get("correct_rate") or 0
    mins = record.get("time_used_minutes") or 0
    attempt = record.get("attempt", 1)
    pct = rate * 100 if rate <= 1 else rate
    lines = [
        f"✅ 已录入 {area} 章节练习",
        f"📊 正确率：{pct:.0f}%（{correct}/{total}）",
        f"⏱️ 用时：{mins} 分钟",
    ]
    if attempt >= 2:
        comparison = build_comparison_text(area, record)
        if comparison:
            lines.append("")
            lines.append(comparison)
    lines.append("💾 已同步到 exam_records.json，将参与趋势分析")
    return "\n".join(lines)


# ── attempt 检测关键词 ──────────────────────────────────────────
_ATTEMPT_KEYWORDS: dict[str, int] = {
    "一刷": 1, "首次": 1, "第一次": 1,
    "二刷": 2, "第二次": 2, "重刷": 2,
    "三刷": 3, "第三次": 3,
    "四刷": 4, "第四次": 4,
    "五刷": 5, "第五次": 5,
    "六刷": 6, "第六次": 6,
}


def detect_attempt(chapter: str, caption: str | None = None) -> int:
    """三优先级判断第几次做该章节练习。

    Priority:
    1. 用户配文关键词（一刷/二刷/重刷等）
    2. 查 exam_records.json 中同 exam_id 的历史最大 attempt + 1
    3. 默认首次（返回 1）
    """
    # 优先级1：配文关键词
    caption_lower = (caption or "").lower()
    for kw, n in sorted(_ATTEMPT_KEYWORDS.items(), key=lambda x: -len(x[0])):
        if kw in caption_lower:
            return n

    # 优先级2：历史记录
    recorder = ExamRecorder()
    exam_id_prefix = f"章节练习_{chapter}"
    history_attempts: list[int] = []
    for e in recorder.list_all():
        if isinstance(e, dict) and (e.get("exam_id") or "").startswith(exam_id_prefix):
            history_attempts.append(e.get("attempt", 1))
    if history_attempts:
        return max(history_attempts) + 1

    # 优先级3：默认
    return 1


def build_comparison_text(area: str, current_record: dict) -> str:
    """根据历史记录生成多刷对比文本。"""
    recorder = ExamRecorder()
    exam_id_prefix = f"章节练习_{area}"
    history: list[dict] = sorted(
        [e for e in recorder.list_all()
         if isinstance(e, dict) and (e.get("exam_id") or "").startswith(exam_id_prefix)],
        key=lambda e: e.get("attempt", 1),
    )
    if len(history) < 2:
        return ""

    attempt = current_record.get("attempt", 1) or 1

    if attempt == 2:
        prev = history[-2] if len(history) >= 2 else history[0]
        prev_rate = prev.get("correct_rate") or 0
        cur_rate = current_record.get("correct_rate") or 0
        if prev_rate <= 1:
            prev_pct = prev_rate * 100
        else:
            prev_pct = prev_rate
        if cur_rate <= 1:
            cur_pct = cur_rate * 100
        else:
            cur_pct = cur_rate
        prev_total = prev.get("total_questions") or 0
        prev_correct = prev.get("correct_count") or 0
        diff = cur_pct - prev_pct
        emoji = "🎉" if diff > 0 else ("📉" if diff < 0 else "➡️")
        return "\n".join([
            f"📊 {area} · 章节练习",
            f"📈 本次：{current_record.get('total_questions')} 题，正确率 {cur_pct:.0f}%（{current_record.get('correct_count')}/{current_record.get('total_questions')}）",
            f"📈 上次：{prev_total} 题，正确率 {prev_pct:.0f}%（{prev_correct}/{prev_total}）",
            f"📈 提升：{diff:+.0f}% {emoji}",
        ])

    # attempt ≥ 3：趋势线
    rates: list[float] = []
    for e in history:
        r = e.get("correct_rate") or 0
        rates.append(r * 100 if r <= 1 else r)
    trend = " → ".join(f"{r:.0f}%" for r in rates)
    lines = [
        f"📊 {area} · 章节练习（第{attempt}次）",
        f"📈 趋势：{trend}",
    ]
    target = max(rates[-1] + 10, 90)
    lines.append(f"🎯 下次目标：≥ {target:.0f}%")
    return "\n".join(lines)


def save_chapter_pending(image_path: str, parsed: dict[str, Any]) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(
        json.dumps({
            "image_path": str(image_path),
            "parsed": parsed,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_chapter_pending() -> dict | None:
    if not PENDING_PATH.exists():
        return None
    try:
        data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("image_path") else None
    except (json.JSONDecodeError, OSError):
        return None


def clear_chapter_pending() -> None:
    if PENDING_PATH.exists():
        PENDING_PATH.unlink()


def record_chapter_pending(chapter_hint: str) -> dict[str, Any]:
    pending = load_chapter_pending()
    if not pending:
        return {"success": False, "error": "no_pending"}
    result = record_chapter_practice(
        pending["image_path"],
        chapter_hint,
    )
    if result.get("success"):
        clear_chapter_pending()
    return result


def preflight_chapter_practice(image_path: str | Path) -> dict[str, Any]:
    """预检：是否为章节练习统计截图，并尝试从 OCR 提取章节名。"""
    image_path = Path(image_path)
    if not image_path.exists():
        return {"is_stats": False, "chapter": None}

    ocr_text = ocr_image(image_path)
    is_stats = is_chapter_practice_screenshot(ocr_text)
    chapter = extract_chapter_from_caption(ocr_text)
    parsed = parse_chapter_practice_text(ocr_text) if ocr_text else {}
    return {
        "is_stats": is_stats,
        "chapter": chapter,
        "parsed": parsed,
        "ocr_preview": (ocr_text or "")[:120],
    }


def record_chapter_practice(
    image_path: str | Path,
    chapter_hint: str,
    *,
    caption: str | None = None,
) -> dict[str, Any]:
    image_path = Path(image_path)
    if not image_path.exists():
        return {"success": False, "error": f"文件不存在: {image_path}"}

    if not HAS_TESSERACT:
        return {"success": False, "error": "OCR 不可用（未安装 pytesseract）"}

    area = map_chapter_to_area(
        chapter_hint or extract_chapter_from_caption(caption or "") or ""
    )

    ocr_text = ocr_image(image_path)
    if not ocr_text.strip():
        return {"success": False, "error": "OCR 未识别到文字，请换一张更清晰的截图"}

    parsed = parse_chapter_practice_text(ocr_text)
    total = parsed.get("total_questions")
    correct = parsed.get("correct_count")

    if total is None or correct is None:
        return {
            "success": False,
            "error": "无法从截图识别总题数/答对题数",
            "parsed": parsed,
            "ocr_preview": ocr_text[:300],
            "hint": "请确认截图包含正确率、答对/总题数、用时，并重发「范围管理」+ 截图",
        }

    wrong = parsed.get("wrong_count")
    if wrong is None:
        wrong = total - correct

    rate = parsed.get("correct_rate")
    if rate is None and total > 0:
        rate = correct / total

    time_min = parsed.get("time_used_minutes") or 0

    knowledge_areas = {
        area: {
            "correct": correct,
            "total": total,
            "rate": round(rate or 0, 4),
        }
    }

    weak_areas = [area] if (rate or 0) < 0.6 else []

    attempt = detect_attempt(area, caption)

    recorder = ExamRecorder()
    record = recorder.add(
        exam_id=f"章节练习_{area}",
        total_questions=total,
        correct_count=correct,
        wrong_count=wrong,
        correct_rate=rate or 0,
        time_used_minutes=time_min,
        scores={"people": 0, "process": 0, "business_environment": 0},
        weak_areas=weak_areas,
        knowledge_areas=knowledge_areas,
        status="completed",
        exam_type="chapter_practice",
        source="截图录入",
        attempt=attempt,
    )

    return {
        "success": True,
        "area": area,
        "record": record,
        "parsed": parsed,
        "message": format_confirm_reply(area, record),
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="章节练习统计截图录入")
    sub = parser.add_subparsers(dest="command")

    p_rec = sub.add_parser("record", help="OCR + 写入 exam_records")
    p_rec.add_argument("--image", "-i", required=True)
    p_rec.add_argument("--chapter", "-c", required=True, help="章节/知识领域名")
    p_rec.add_argument("--caption", default=None)
    p_rec.add_argument("--json", action="store_true")

    p_parse = sub.add_parser("parse", help="仅 OCR 解析")
    p_parse.add_argument("--image", "-i", required=True)
    p_parse.add_argument("--json", action="store_true")

    p_pf = sub.add_parser("preflight", help="预检是否为章节练习统计页")
    p_pf.add_argument("--image", "-i", required=True)
    p_pf.add_argument("--json", action="store_true")

    p_pending = sub.add_parser("record-pending", help="用 pending 截图 + 章节名入库")
    p_pending.add_argument("--chapter", "-c", required=True)
    p_pending.add_argument("--json", action="store_true")

    p_save_p = sub.add_parser("save-pending", help="保存待补章节名的统计截图")
    p_save_p.add_argument("--image", "-i", required=True)
    p_save_p.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "parse":
        text = ocr_image(args.image)
        out = {
            "ocr_text": text,
            "parsed": parse_chapter_practice_text(text),
            "is_stats": is_chapter_practice_screenshot(text),
            "chapter": extract_chapter_from_caption(text),
        }
    elif args.command == "preflight":
        out = preflight_chapter_practice(args.image)
    elif args.command == "record-pending":
        out = record_chapter_pending(args.chapter)
    elif args.command == "save-pending":
        pf = preflight_chapter_practice(args.image)
        if pf.get("is_stats") and pf.get("parsed"):
            save_chapter_pending(args.image, pf["parsed"])
            out = {"success": True, "status": "pending", "parsed": pf["parsed"]}
        else:
            out = {"success": False, "error": "not_chapter_stats"}
    else:
        out = record_chapter_practice(
            args.image,
            args.chapter,
            caption=args.caption,
        )

    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
