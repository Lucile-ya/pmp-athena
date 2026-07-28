#!/usr/bin/env python3
"""
模考成绩截图分析工具 —— OCR 识别 + 结构化提取 + 写入 exam_records.json + 分析报告

用法:
    python pmp_athena/analyze_exam.py <image_path>
    python pmp_athena/analyze_exam.py D:/pmp-athena/screenshots/exam_result.png

    也可作为模块导入:
    from pmp_athena.analyze_exam import analyze_exam_screenshot
    report = analyze_exam_screenshot("path/to/screenshot.png")
"""

import argparse
import json
import logging
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from PIL import Image

from .exam_recorder import ExamRecorder

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("analyze_exam")

# ── OCR 初始化 ──────────────────────────────────────────────────
try:
    import pytesseract

    if sys.platform == "win32":
        _tesseract_path = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        if _tesseract_path.exists():
            pytesseract.pytesseract.tesseract_cmd = str(_tesseract_path)

    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

# ── PMP 通过线与目标 ──────────────────────────────────────────
PASS_LINE = 106      # PMP 官方通过线: 106/180（约 59%）
TARGET_LINE = 126    # 稳妥目标线: 126/180（70%），日常训练以 70% 为基准


# ═══════════════════════════════════════════════════════════════
# 文本解析
# ═══════════════════════════════════════════════════════════════


def _norm(text: str) -> str:
    """规范化 OCR 文本：去首尾空白、合并多余空格、统一全角/半角"""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    # 全角数字 → 半角
    full_to_half = str.maketrans(
        "０１２３４５６７８９．：％／",
        "0123456789.:%/",
    )
    text = text.translate(full_to_half)
    return text


def _extract_number(text: str) -> Optional[int]:
    """从文本中提取第一个整数"""
    m = re.search(r"(\d+)", str(text))
    return int(m.group(1)) if m else None


def _extract_number_near(text: str, keyword: str) -> Optional[int]:
    """从文本中提取关键词之中或之后的第一个整数（避免误匹配前面的数字）"""
    idx = text.find(keyword)
    if idx >= 0:
        # 先在关键词本身中找（如"共180题"→180）
        m = re.search(r"(\d+)", keyword)
        if m:
            return int(m.group(1))
        # 再从关键词之后找
        tail = text[idx + len(keyword):]
        m = re.search(r"(\d+)", tail)
        if m:
            return int(m.group(1))
    # 回退：全文搜索
    return _extract_number(text)


def _extract_float(text: str) -> Optional[float]:
    """从文本中提取第一个浮点数"""
    m = re.search(r"(\d+\.?\d*)", str(text))
    return float(m.group(1)) if m else None


def _extract_time_minutes(text: str) -> Optional[int]:
    """从时间文本中提取总分钟数，支持 '2小时30分钟' / '150分钟' / '2h30m'"""
    text = str(text)
    total = 0
    h = re.search(r"(\d+)\s*(?:小时|h|H)", text)
    m = re.search(r"(\d+)\s*(?:分钟|分|min|m)", text)
    if h:
        total += int(h.group(1)) * 60
    if m:
        total += int(m.group(1))
    if total > 0:
        return total
    # 纯数字（分钟）
    num = _extract_number(text)
    if num and 10 <= num <= 300:
        return num
    return None


def _extract_ranking(text: str) -> Optional[str]:
    """提取排名，如 '第3名' / '排名5/200' / '3/200'"""
    text = str(text)
    m = re.search(r"(?:排名?|第)\s*(\d+)\s*(?:/|／|\s*/\s*)\s*(\d+)", text)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.search(r"第\s*(\d+)\s*名", text)
    if m:
        return m.group(1)
    return None


def parse_exam_text(ocr_text: str) -> dict:
    """
    从 OCR 文本中提取模考结构化数据。

    解析策略：
    1. 先按行扫描，用关键词匹配提取各字段
    2. 兜底：用数值模式匹配（如 '总分180 得分120' → total=180, score=120）

    Returns:
        {
            "exam_name": str | None,
            "total_questions": int | None,
            "score": int | None,
            "correct_count": int | None,
            "wrong_count": int | None,
            "average_score": float | None,
            "time_used_minutes": int | None,
            "ranking": str | None,
            "raw_text": str,
        }
    """
    lines = ocr_text.split("\n")
    lines = [_norm(line) for line in lines]
    full = "\n".join(lines)

    result: dict = {
        "exam_name": None,
        "total_questions": None,
        "score": None,
        "correct_count": None,
        "wrong_count": None,
        "average_score": None,
        "time_used_minutes": None,
        "ranking": None,
        "raw_text": ocr_text,
    }

    # ── 逐行关键词匹配 ──────────────────────────────────────
    for line in lines:
        # 模考名称
        m_name = re.search(r"(模考名称|模拟考试|模考|模拟|试卷名称|试卷|考试名称)", line)
        if m_name:
            kw = m_name.group(1)
            # 去掉标签前缀
            raw = re.sub(
                r"^(?:模考名称|模拟考试|试卷名称|考试名称|模考|模拟|试卷)\s*[:：]?\s*",
                "", line
            ).strip()
            # 截断：在遇到后续数据字段时停止
            name = re.split(
                r"\s{3,}|[，,。；;]{2,}|\s*(?:得分|答对|答错|正确|错误|排名|用时|平均分|题数)\s*",
                raw, maxsplit=1
            )[0].strip()
            # 去掉残留符号
            name = re.sub(r"[：:＝=→➡️]$", "", name).strip()
            # 如果只剩 1 个字符（如"二"），组合回关键词（"模考二"）
            if name and len(name) == 1 and kw in ("模考", "模拟", "试卷"):
                name = kw + name
            if name and len(name) >= 2:
                result["exam_name"] = name[:50]

        # 总题数（排除"答对题数"/"答错题数"的干扰）
        kw_tq = re.search(r"(?<!答对)(?<!答错)(?<!正确)(?<!错误)(总题数|题目总数|题目数量|题数|共\s*\d+\s*题)", line)
        if kw_tq:
            result["total_questions"] = _extract_number_near(line, kw_tq.group(1))
        # "总分180" 单独成行时通常表示总题数/满分
        elif (
            result["total_questions"] is None
            and re.search(r"^[总分题量]{1,3}\s*[:：]?\s*\d{2,3}\s*$", line)
        ):
            n = _extract_number(line)
            if n and 50 <= n <= 200:
                result["total_questions"] = n

        # 得分
        kw_sc = re.search(r"(得分|成绩|总分|考试得分|你的得分)", line)
        if kw_sc and "average" not in line.lower():
            result["score"] = _extract_number_near(line, kw_sc.group(1))

        # 正确题数 / 答对
        kw_cr = re.search(r"(答对|正确题数|正确|对题|做对)", line)
        if kw_cr:
            result["correct_count"] = _extract_number_near(line, kw_cr.group(1))

        # 错误题数 / 答错
        kw_wr = re.search(r"(答错|错误题数|错误|错题|做错)", line)
        if kw_wr:
            result["wrong_count"] = _extract_number_near(line, kw_wr.group(1))

        # 平均分
        kw_avg = re.search(r"(平均分|平均成绩|均分|avg)", line, re.IGNORECASE)
        if kw_avg:
            result["average_score"] = _extract_float(line[kw_avg.start():])

        # 用时
        kw_tm = re.search(r"(用时|耗时|考试用时|答题用时|时间)", line)
        if kw_tm:
            result["time_used_minutes"] = _extract_time_minutes(line[kw_tm.start():])

        # 排名
        kw_rk = re.search(r"(排名|名次|排位)", line)
        if kw_rk:
            rank = _extract_ranking(line[kw_rk.start():])
            if rank:
                result["ranking"] = rank

    # ── 兜底：数值模式匹配 ──────────────────────────────────
    # 如果逐行没匹配到，用全文模式匹配

    # 题数兜底: 只匹配明确的题数标识，排除"答对/答错 X题"
    if result["total_questions"] is None:
        for pat in [
            r"(?:共|总共|共计|一共|合计)\s*(\d{2,3})\s*[题Tt]",
            r"(?:总题|题目总数|题量)\s*[:：]?\s*(\d{2,3})",
            r"(\d{2,3})\s*/\s*\1",  # "180/180" 格式
            r"[题Tt]\s*[:：]?\s*(\d{2,3})\s*$",
        ]:
            m = re.search(pat, full)
            if m:
                result["total_questions"] = int(m.group(1))
                break

    # 得分: "得分 120" / "成绩 120" / "分数 120"
    if result["score"] is None:
        for pat in [r"(?:得分|成绩|分数|总分)\s*[:：]?\s*(\d{2,3})",
                      r"(\d{2,3})\s*(?:分|/180)"]:
            m = re.search(pat, full)
            if m:
                val = int(m.group(1))
                if 50 <= val <= 180:
                    result["score"] = val
                    break

    # 正确/错误数
    if result["correct_count"] is None:
        for pat in [r"(?:正确|答对|做对)\s*[:：]?\s*(\d{2,3})",
                      r"(\d{2,3})\s*(?:题正确|题答对|题做对)"]:
            m = re.search(pat, full)
            if m:
                result["correct_count"] = int(m.group(1))
                break

    if result["wrong_count"] is None:
        for pat in [r"(?:错误|答错|做错)\s*[:：]?\s*(\d{2,3})",
                      r"(\d{2,3})\s*(?:题错误|题答错|题做错)"]:
            m = re.search(pat, full)
            if m:
                result["wrong_count"] = int(m.group(1))
                break

    # ── 交叉推算 ──────────────────────────────────────────
    # 先做 score ↔ correct_count 的互推（大多数平台得分=正确数）
    score = result["score"]
    correct = result["correct_count"]

    if score and correct is None:
        result["correct_count"] = score
        correct = score
    elif correct and score is None:
        result["score"] = correct
        score = correct

    # 再做 total/correct/wrong 三者的互推
    total = result["total_questions"]
    wrong = result["wrong_count"]

    if total and correct and wrong is None:
        result["wrong_count"] = total - correct
    elif total and wrong and correct is None:
        result["correct_count"] = total - wrong
    elif correct and wrong and total is None:
        result["total_questions"] = correct + wrong

    # 名称兜底
    if result["exam_name"] is None:
        # 尝试从第一行或前几行中提取考试名
        for line in lines[:3]:
            if len(line) >= 2 and not re.match(r"^[\d\s\.\-,:：/]+$", line):
                result["exam_name"] = line[:50]
                break

    return result


# ═══════════════════════════════════════════════════════════════
# 分析 & 写入
# ═══════════════════════════════════════════════════════════════


def analyze_exam_screenshot(image_path: str | Path) -> dict:
    """
    分析模考成绩截图。

    Args:
        image_path: 截图文件路径

    Returns:
        {
            "parsed": {...},        # 解析结果
            "record": {...},        # 写入 exam_records.json 的记录
            "report": str,          # 格式化的分析报告
            "success": bool,
            "error": str | None,
        }
    """
    image_path = Path(image_path)

    result: dict = {
        "parsed": {},
        "record": {},
        "report": "",
        "success": False,
        "error": None,
    }

    # ── 1. 检查文件 ──────────────────────────────────────────
    if not image_path.exists():
        result["error"] = f"文件不存在: {image_path}"
        return result

    if not HAS_TESSERACT:
        result["error"] = (
            "OCR 引擎不可用。请安装: pip install pytesseract + 安装 Tesseract OCR 引擎。\n"
            "Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
        )
        return result

    # ── 2. OCR 识别 ──────────────────────────────────────────
    try:
        img = Image.open(image_path)
        ocr_text = pytesseract.image_to_string(img, lang="chi_sim+eng")
    except Exception as e:
        result["error"] = f"OCR 识别失败: {e}"
        return result

    if not ocr_text or not ocr_text.strip():
        result["error"] = "OCR 未能识别到文字，请检查截图是否清晰。"
        return result

    # ── 3. 解析文本 ──────────────────────────────────────────
    parsed = parse_exam_text(ocr_text)
    result["parsed"] = parsed

    # ── 4. 校验必要数据 ─────────────────────────────────────
    if parsed["total_questions"] is None or parsed["correct_count"] is None:
        result["error"] = (
            "未能从截图中解析出完整数据。请确认截图包含以下信息:\n"
            "- 总题数 / 题目总数\n"
            "- 答对题数 / 得分\n\n"
            f"OCR 识别到的文本:\n```\n{ocr_text[:800]}\n```"
        )
        return result

    # ── 5. 写入 exam_records.json ───────────────────────────
    total = parsed["total_questions"]
    correct = parsed["correct_count"]
    wrong = parsed["wrong_count"] or (total - correct)
    rate = correct / total

    exam_name = parsed["exam_name"] or f"模考 {date.today().isoformat()}"

    try:
        recorder = ExamRecorder()
        record = recorder.add(
            exam_id=exam_name,
            total_questions=total,
            correct_count=correct,
            wrong_count=wrong,
            correct_rate=rate,
            time_used_minutes=parsed["time_used_minutes"] or 0,
        )
        result["record"] = record
    except Exception as e:
        result["error"] = f"写入 exam_records.json 失败: {e}"
        return result

    # ── 6. 生成分析报告 ─────────────────────────────────────
    gap_to_target = TARGET_LINE - correct
    pass_line_gap = PASS_LINE - correct

    if correct >= TARGET_LINE:
        pass_status = f"✅ 已达目标（{TARGET_LINE}/180，70%）"
    elif correct >= PASS_LINE:
        pass_status = f"⚠️ 已过通过线但未达目标（差 {gap_to_target} 题到 70% 目标）"
    else:
        pass_status = f"❌ 未过线（差 {pass_line_gap} 题到通过线，差 {gap_to_target} 题到 70% 目标）"

    lines_report = []
    lines_report.append("══════════════════════════════")
    lines_report.append(f"📊 模考成绩分析: {exam_name}")
    lines_report.append("══════════════════════════════\n")

    lines_report.append(f"📝 得分: {correct}/{total}（{rate*100:.1f}%）")
    if parsed["wrong_count"] or wrong:
        lines_report.append(f"   答对: {correct} 题 | 答错: {wrong} 题")

    if parsed["time_used_minutes"]:
        mins = parsed["time_used_minutes"]
        lines_report.append(f"⏱️  用时: {mins} 分钟（{mins//60}h{mins%60}m）")

    if parsed["average_score"] is not None:
        avg = parsed["average_score"]
        diff = correct - avg
        sign = "+" if diff >= 0 else ""
        lines_report.append(f"📈 平均分对比: 你的 {correct} vs 平均 {avg}（{sign}{diff}）")

    if parsed["ranking"]:
        lines_report.append(f"🏆 排名: {parsed['ranking']}")

    lines_report.append(f"\n🎯 目标判定: {pass_status}")
    lines_report.append(f"   PMP 通过线: {PASS_LINE}/180（59%）→ 稳妥目标: {TARGET_LINE}/180（70%）")
    lines_report.append(f"   你的正确率: {rate*100:.1f}%")

    # 建议（以 70% 目标为基准）
    lines_report.append("\n💡 建议:")
    if rate >= 0.80:
        lines_report.append("   1. ✅ 正确率稳定在 80%+，远超 70% 目标，保持节奏")
        lines_report.append("   2. 重点回顾薄弱知识领域的错题，追求零失误")
    elif rate >= 0.70:
        lines_report.append("   1. ✅ 已达 70% 稳妥目标，继续巩固优势领域")
        lines_report.append("   2. 查漏补缺：分析错题集中在哪些知识领域，定向刷题")
    elif rate >= 0.65:
        lines_report.append(f"   1. ⚠️ 距 70% 目标还差 {gap_to_target} 题，整体差距不大")
        lines_report.append("   2. 建议：集中突破错误率最高的 2-3 个知识领域")
        lines_report.append("   3. 每天做一套每日一练，保持题感")
    elif rate >= 0.59:
        lines_report.append(f"   1. 🟡 刚过通过线，距 70% 目标还差 {gap_to_target} 题")
        lines_report.append("   2. 存在明显短板，建议回顾 PMBOK 核心章节")
        lines_report.append("   3. 优先攻克：整合管理、风险管理、敏捷/混合方法（高频考点）")
    else:
        lines_report.append(f"   1. 🔴 未达通过线，距 70% 目标还差 {gap_to_target} 题")
        lines_report.append("   2. 基础薄弱，建议回归教材系统复习 + 每日一练高频刷题")
        lines_report.append("   3. 重点：整合管理、风险管理、敏捷/混合方法 + 错题反复练习")

    report = "\n".join(lines_report)
    result["report"] = report
    result["success"] = True

    return result


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="模考成绩截图分析 —— OCR 识别 + 写入 exam_records.json + 分析报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python pmp_athena/analyze_exam.py screenshot.png
  python pmp_athena/analyze_exam.py D:/pmp-athena/screenshots/exam_result.png
        """,
    )
    parser.add_argument(
        "image", type=str, help="模考成绩截图文件路径"
    )
    parser.add_argument(
        "--no-save", action="store_true", help="仅分析不写入 exam_records.json"
    )
    parser.add_argument(
        "--raw", action="store_true", help="输出 OCR 原始文本（调试用）"
    )

    args = parser.parse_args()

    image_path = Path(args.image)

    if not image_path.exists():
        print(f"❌ 文件不存在: {image_path}")
        sys.exit(1)

    print(f"🔍 正在 OCR 识别: {image_path.name} ...")

    if not HAS_TESSERACT:
        print("❌ OCR 引擎不可用。请安装: pip install pytesseract")
        sys.exit(1)

    # OCR
    try:
        img = Image.open(image_path)
        ocr_text = pytesseract.image_to_string(img, lang="chi_sim+eng")
    except Exception as e:
        print(f"❌ OCR 识别失败: {e}")
        sys.exit(1)

    if args.raw:
        print("\n── OCR 原始文本 ──")
        print(ocr_text)
        print("── 原始文本结束 ──\n")

    # 解析
    parsed = parse_exam_text(ocr_text)
    print(json.dumps(parsed, ensure_ascii=False, indent=2))

    # 校验
    if parsed["total_questions"] is None or parsed["correct_count"] is None:
        print("\n❌ 未能从截图中解析出完整数据。请确认截图包含: 总题数、答对题数/得分。")
        if not args.raw:
            print(f"\nOCR 识别到的文本:\n```\n{ocr_text[:800]}\n```")
        sys.exit(1)

    # 分析
    result = analyze_exam_screenshot(image_path)
    if result["error"]:
        print(f"\n❌ {result['error']}")
        sys.exit(1)

    if args.no_save:
        print("\n⚠️  未写入 exam_records.json（--no-save）")

    print(f"\n{result['report']}")


if __name__ == "__main__":
    main()
