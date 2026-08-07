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

try:
    from pmp_athena.config import ERROR_LOG_PATH
except ModuleNotFoundError:
    from config import ERROR_LOG_PATH

import argparse
import json
import logging
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

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
TARGET_LINE = 126    # 稳妥目标线: 126/180（70%）
PASS_RATE = 59.0

# 模考成绩截图特征词（不同小程序/UI）
EXAM_SCREENSHOT_MARKERS = (
    "模考", "模拟考试", "交卷时间", "交卷", "答对", "答错", "未答",
    "总题数", "题目总数", "共180题", "共 180 题", "考试报告", "成绩报告",
    "排名", "平均分", "用时", "得分", "PMP模考", "PMP 模考",
)


def detect_exam_screenshot(text: str) -> bool:
    """判断 OCR 文本是否为模考成绩截图（非单题/章节练习）。"""
    if not text or not text.strip():
        return False
    t = text.replace("\u200b", "")
    hits = sum(1 for m in EXAM_SCREENSHOT_MARKERS if m in t)
    if hits >= 2:
        return True
    if re.search(r"答对\s*\d+", t) and re.search(r"(?:共|总)\s*\d{2,3}\s*题", t):
        return True
    if re.search(r"\d{2,3}\s*/\s*180", t) and ("得分" in t or "成绩" in t):
        return True
    return False


def _extract_exam_date(text: str) -> str | None:
    """从交卷时间等字段提取日期 YYYY-MM-DD。"""
    for pat in [
        r"交卷时间\s*[:：]?\s*(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})",
        r"交卷\s*[:：]?\s*(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})",
        r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})\s*\d{1,2}:\d{2}",
        r"(\d{4})-(\d{2})-(\d{2})",
    ]:
        m = re.search(pat, text)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                return date(y, mo, d).isoformat()
            except ValueError:
                continue
    return None


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
    """提取排名，如 '第3名' / '排名5/200' / '排名 12' / '3/200'"""
    text = str(text)
    m = re.search(r"(?:排名?|第)\s*(\d+)\s*(?:/|／|\s*/\s*)\s*(\d+)", text)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.search(r"排名\s*[:：]?\s*(\d+)", text)
    if m:
        return m.group(1)
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
        "exam_date": None,
        "total_questions": None,
        "total_score": None,
        "score": None,
        "correct_count": None,
        "wrong_count": None,
        "unanswered_count": None,
        "average_score": None,
        "time_used_minutes": None,
        "ranking": None,
        "raw_text": ocr_text,
    }

    result["exam_date"] = _extract_exam_date(full)

    # ── 逐行关键词匹配 ──────────────────────────────────────
    for line in lines:
        # 未答
        kw_un = re.search(r"(未答|未做|漏答|空白)", line)
        if kw_un:
            result["unanswered_count"] = _extract_number_near(line, kw_un.group(1))

        # 满分/总分（区别于得分）
        kw_ts = re.search(r"(总计|满分|共\s*\d+\s*分|总计\s*\d+\s*分)", line)
        if kw_ts and result["total_score"] is None:
            n = _extract_number_near(line, kw_ts.group(1))
            if n and 50 <= n <= 200:
                result["total_score"] = n

        # 模考名称：2606PMP模考一 等
        m_pmp = re.search(
            r"(\d{4}\s*PMP\s*模考[一二三四五六七八九十\d]+|"
            r"PMP\s*模考[一二三四五六七八九十\d]+|"
            r"2606\s*PMP\s*模考[一1])",
            line,
            re.I,
        )
        if m_pmp and not result["exam_name"]:
            result["exam_name"] = re.sub(r"\s+", "", m_pmp.group(1))[:50]

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

        # 正确题数 / 答对（排除百分比行）
        kw_cr = re.search(r"(答对|正确题数|正确|对题|做对)", line)
        if kw_cr and "率" not in line and "%" not in line:
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

    # 100/180 得分格式（优先于百分比干扰）
    if result["correct_count"] is None or result["total_questions"] is None:
        m_frac = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})", full)
        if m_frac:
            a, b = int(m_frac.group(1)), int(m_frac.group(2))
            if 50 <= b <= 200 and 0 <= a <= b:
                if result["correct_count"] is None:
                    result["correct_count"] = a
                if result["total_questions"] is None:
                    result["total_questions"] = b
                if result["score"] is None:
                    result["score"] = a

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
        for line in lines[:5]:
            if re.search(r"模考|模拟|PMP", line, re.I) and len(line) >= 4:
                name = re.sub(r"\s+", "", line)[:50]
                if not re.match(r"^[\d\s\.\-,:：/]+$", name):
                    result["exam_name"] = name
                    break
        if result["exam_name"] is None:
            for line in lines[:3]:
                if len(line) >= 2 and not re.match(r"^[\d\s\.\-,:：/]+$", line):
                    result["exam_name"] = line[:50]
                    break

    # 未答数推算
    total = result["total_questions"]
    correct = result["correct_count"]
    wrong = result["wrong_count"]
    unans = result["unanswered_count"]
    if total and correct is not None and wrong is not None and unans is None:
        rem = total - correct - wrong
        if rem > 0:
            result["unanswered_count"] = rem

    return result


# ═══════════════════════════════════════════════════════════════
# 分析 & 写入
# ═══════════════════════════════════════════════════════════════


def _load_error_log_areas() -> list[tuple[str, int]]:
    """错题本领域频次 Top 列表。"""
    try:
        data = json.loads(ERROR_LOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    counts: Counter[str] = Counter()
    for e in data:
        if isinstance(e, dict):
            counts[e.get("knowledge_area") or "综合"] += 1
    return counts.most_common(5)


def _compare_history(
    recorder: ExamRecorder,
    current_rate: float,
    *,
    exclude_last: bool = True,
) -> dict[str, Any]:
    """与历史模考对比趋势。"""
    exams = [
        e for e in recorder.list_all()
        if e.get("status") == "completed"
        and e.get("total_questions", 0) >= 100
        and (e.get("correct_count") or 0) > 0
    ]
    if exclude_last and exams:
        exams = exams[:-1]

    if not exams:
        return {"has_history": False, "trend": "new", "prev_rate": None, "avg_rate": None}

    rates = []
    for e in exams:
        r = float(e.get("correct_rate") or 0)
        if r <= 1:
            r *= 100
        if r > 0:
            rates.append(round(r, 1))

    prev_rate = rates[-1] if rates else None
    avg_rate = round(sum(rates) / len(rates), 1) if rates else None
    diff = round(current_rate - prev_rate, 1) if prev_rate is not None else None

    if diff is None:
        trend = "new"
    elif diff >= 3:
        trend = "up"
    elif diff <= -3:
        trend = "down"
    else:
        trend = "flat"

    # 连续下降：最近 2 次有效模考
    decline = False
    if len(rates) >= 2:
        decline = rates[-1] < rates[-2] - 3

    return {
        "has_history": True,
        "trend": trend,
        "prev_rate": prev_rate,
        "avg_rate": avg_rate,
        "diff": diff,
        "decline": decline,
        "exam_count": len(rates),
    }


def _format_confirm(parsed: dict, rate: float) -> list[str]:
    """识别结果确认（5 行内）。"""
    name = parsed.get("exam_name") or "模考"
    total = parsed.get("total_questions") or "?"
    correct = parsed.get("correct_count") or parsed.get("score") or "?"
    lines = [
        "✅ 模考截图识别成功",
        f"📝 {name}",
    ]
    if parsed.get("exam_date"):
        lines.append(f"📅 {parsed['exam_date']}")
    lines.append(f"📊 {correct}/{total}（{rate:.1f}%）")
    extras = []
    if parsed.get("wrong_count") is not None:
        extras.append(f"错{parsed['wrong_count']}")
    if parsed.get("unanswered_count"):
        extras.append(f"未答{parsed['unanswered_count']}")
    if parsed.get("ranking"):
        extras.append(f"排名{parsed['ranking']}")
    if parsed.get("average_score") is not None:
        extras.append(f"均分{parsed['average_score']}")
    if extras:
        lines.append(" · ".join(extras))
    else:
        lines.append("💾 已自动写入 exam_records.json")
    return lines[:5]


def _format_error_linkage() -> list[str]:
    """错题联动段落。"""
    tops = _load_error_log_areas()
    if not tops:
        return []
    lines = ["", "❌ 错题联动（高频领域）"]
    for area, cnt in tops[:3]:
        lines.append(f"  · [{area}] 累计错 {cnt} 道 → 发送「{area}知识点」")
    return lines


def _format_actions(rate: float, history: dict, error_areas: list[tuple[str, int]]) -> list[str]:
    """可执行行动建议 1-3 条。"""
    actions: list[str] = []
    if rate < PASS_RATE:
        actions.append("暂停新模考，回归教材+每日一练")
    elif rate < 70:
        actions.append(f"专项突破：{error_areas[0][0] if error_areas else '薄弱领域'} 20题")
    else:
        actions.append("保持节奏，每周1次完整模考")

    if history.get("decline"):
        actions.append("发送「根因分析」查思维漏洞")
    else:
        actions.append("发送「复习错题」清到期题")

    if rate >= 70:
        actions.append("发送「分析趋势」看整体走势")
    else:
        actions.append("发送「考前分析」制定冲刺计划")

    return actions[:3]


def _trigger_push_alerts(rate: float, history: dict, record: dict) -> None:
    """模考后推送：未过线预警 / 持续下降（标准分析由 exam_recorder.add 调度）。"""
    try:
        from pmp_athena.prep_push import enqueue
    except ImportError:
        from prep_push import enqueue

    if rate < PASS_RATE:
        enqueue(
            "mock_fail_alert",
            f"🚨 模考未过线预警\n\n本次 {rate:.1f}% < 59% 通过线\n"
            f"建议：暂停模考，回归基础+错题复盘\n发送「复习计划」获取专项方案",
            delay_minutes=0,
        )

    if history.get("decline"):
        enqueue(
            "mock_decline_alert",
            f"⚠️ 模考成绩持续下降\n\n"
            f"上次 {history.get('prev_rate')}% → 本次 {rate:.1f}%\n"
            f"建议：发送「根因分析」查思维漏洞",
            delay_minutes=0,
        )


def _generate_report(
    parsed: dict,
    *,
    exam_name: str,
    total: int,
    correct: int,
    wrong: int,
    rate: float,
    record: dict,
    history: dict,
    error_areas: list[tuple[str, int]],
) -> str:
    """完整分析报告（确认 + 分析 + 错题联动 + 行动）。"""
    parts: list[str] = []

    # 1. 识别确认
    parts.extend(_format_confirm(parsed, rate * 100 if rate <= 1 else rate))
    parts.append("")

    # 2. 模考分析
    rate_pct = rate * 100 if rate <= 1 else rate
    gap_target = TARGET_LINE - correct
    pass_ok = correct >= PASS_LINE

    parts.append("══════════════════════")
    parts.append(f"📊 模考分析: {exam_name}")
    parts.append("══════════════════════")

    if parsed.get("time_used_minutes"):
        mins = parsed["time_used_minutes"]
        parts.append(f"⏱️ 用时: {mins} 分钟")

    if pass_ok:
        status = "✅ 已过59%线" if rate_pct < 70 else "🎉 已达70%目标"
    else:
        status = f"❌ 未过线（差 {PASS_LINE - correct} 题）"
    parts.append(f"🎯 {status} · 正确率 {rate_pct:.1f}%")

    # 趋势对比
    if history.get("has_history"):
        prev = history.get("prev_rate")
        diff = history.get("diff")
        avg = history.get("avg_rate")
        if diff is not None:
            arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
            emoji = "🎉" if diff >= 5 else ("⚠️" if diff <= -5 else "")
            parts.append(f"📈 vs 上次: {arrow} {abs(diff):.1f}%（上次 {prev}%）{emoji}")
        if avg is not None:
            parts.append(f"📊 历史均分: {avg}%（共 {history.get('exam_count')} 次）")
        if history.get("decline"):
            parts.append("⚠️ 连续下降趋势，需调整策略")
    else:
        parts.append("📈 首次完整模考记录")

    if parsed.get("average_score") is not None:
        diff = correct - parsed["average_score"]
        sign = "+" if diff >= 0 else ""
        parts.append(f"📉 vs 平台均分: {sign}{diff:.0f} 分")

    # 3. 错题联动
    parts.extend(_format_error_linkage())

    # 4. 行动建议
    actions = _format_actions(rate_pct, history, error_areas)
    parts.extend(["", "✅ 行动建议"])
    for i, act in enumerate(actions, 1):
        parts.append(f"{i}. {act}")

    parts.append("")
    parts.append("💾 已存入 exam_records.json · 发送「分析趋势」看走势")

    return "\n".join(parts)


def ocr_exam_image(image_path: str | Path) -> str:
    """OCR 模考截图，优先 ImageProcessor。"""
    image_path = Path(image_path)
    try:
        from pmp_athena.image_processor import ImageProcessor
        proc = ImageProcessor()
        r = proc.process(image_path, run_ocr=True)
        text = r.get("ocr_text") or ""
        if text.strip():
            return text
    except Exception:
        pass

    if not HAS_TESSERACT:
        return ""
    img = Image.open(image_path)
    return pytesseract.image_to_string(img, lang="chi_sim+eng")


def analyze_exam_screenshot(image_path: str | Path, *, save: bool = True) -> dict:
    """
    分析模考成绩截图。

    Returns:
        {
            "parsed": {...},
            "record": {...},
            "report": str,
            "confirm": str,
            "success": bool,
            "error": str | None,
        }
    """
    image_path = Path(image_path)

    result: dict = {
        "parsed": {},
        "record": {},
        "report": "",
        "confirm": "",
        "success": False,
        "error": None,
    }

    if not image_path.exists():
        result["error"] = f"文件不存在: {image_path}"
        return result

    if not HAS_TESSERACT:
        try:
            from pmp_athena.image_processor import HAS_OCR
            if not HAS_OCR:
                result["error"] = "OCR 引擎不可用。请安装 pytesseract + Tesseract。"
                return result
        except ImportError:
            result["error"] = "OCR 引擎不可用。"
            return result

    ocr_text = ocr_exam_image(image_path)
    if not ocr_text or not ocr_text.strip():
        result["error"] = "OCR 未能识别到文字，请检查截图是否清晰。"
        return result

    parsed = parse_exam_text(ocr_text)
    result["parsed"] = parsed

    total = parsed.get("total_questions")
    correct = parsed.get("correct_count") or parsed.get("score")

    if total is None or correct is None:
        missing = []
        if total is None:
            missing.append("总题数")
        if correct is None:
            missing.append("答对/得分")
        result["error"] = (
            f"未能解析: {', '.join(missing)}。可选字段已跳过。\n\n"
            f"OCR 文本（前800字）:\n{ocr_text[:800]}"
        )
        return result

    wrong = parsed.get("wrong_count")
    if wrong is None:
        unans = parsed.get("unanswered_count") or 0
        wrong = max(0, total - correct - unans)

    rate = correct / total if total else 0
    exam_name = parsed.get("exam_name") or f"模考_{date.today().isoformat()}"
    exam_date = parsed.get("exam_date")

    record = {}
    if save:
        try:
            recorder = ExamRecorder()
            record = recorder.add(
                exam_id=exam_name,
                total_questions=total,
                correct_count=correct,
                wrong_count=wrong,
                correct_rate=rate,
                time_used_minutes=parsed.get("time_used_minutes") or 0,
                source="截图录入",
                exam_date=exam_date,
            )
            result["record"] = record
        except Exception as e:
            result["error"] = f"写入 exam_records.json 失败: {e}"
            return result

    history = _compare_history(ExamRecorder(), rate * 100 if rate <= 1 else rate)
    error_areas = _load_error_log_areas()

    report = _generate_report(
        parsed,
        exam_name=exam_name,
        total=total,
        correct=correct,
        wrong=wrong,
        rate=rate,
        record=record,
        history=history,
        error_areas=error_areas,
    )
    result["report"] = report
    result["confirm"] = "\n".join(_format_confirm(parsed, rate * 100))
    result["success"] = True
    result["history"] = history

    if save and record:
        rate_pct = rate * 100 if rate <= 1 else rate
        try:
            _trigger_push_alerts(rate_pct, history, record)
        except Exception as e:
            logger.warning("Push alert failed: %s", e)

    return result


def analyze_exam_text(ocr_text: str, *, save: bool = True) -> dict:
    """从 OCR 文本直接分析（测试/桥接用）。"""
    parsed = parse_exam_text(ocr_text)
    total = parsed.get("total_questions")
    correct = parsed.get("correct_count") or parsed.get("score")
    if not total or correct is None:
        return {"success": False, "error": "解析不完整", "parsed": parsed}

    wrong = parsed.get("wrong_count") or max(0, total - correct - (parsed.get("unanswered_count") or 0))
    rate = correct / total
    exam_name = parsed.get("exam_name") or "模考"

    record = {}
    if save:
        recorder = ExamRecorder()
        record = recorder.add(
            exam_id=exam_name,
            total_questions=total,
            correct_count=correct,
            wrong_count=wrong,
            correct_rate=rate,
            time_used_minutes=parsed.get("time_used_minutes") or 0,
            source="截图录入",
            exam_date=parsed.get("exam_date"),
        )

    history = _compare_history(ExamRecorder(), rate * 100)
    error_areas = _load_error_log_areas()
    report = _generate_report(
        parsed,
        exam_name=exam_name,
        total=total,
        correct=correct,
        wrong=wrong,
        rate=rate,
        record=record,
        history=history,
        error_areas=error_areas,
    )
    return {
        "success": True,
        "parsed": parsed,
        "record": record,
        "report": report,
        "history": history,
    }


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

    parser.add_argument(
        "--json", action="store_true", help="JSON 输出"
    )

    args = parser.parse_args()

    image_path = Path(args.image)

    if not image_path.exists():
        print(f"❌ 文件不存在: {image_path}")
        sys.exit(1)

    if args.no_save:
        print(f"🔍 正在 OCR 识别: {image_path.name}（不写入）...")
        result = analyze_exam_screenshot(image_path, save=False)
        if args.raw and result.get("parsed"):
            ocr_text = ocr_exam_image(image_path)
            print(ocr_text)
        if args.json:
            print(json.dumps({
                "success": result.get("success"),
                "parsed": result.get("parsed"),
                "report": result.get("report"),
                "error": result.get("error"),
            }, ensure_ascii=False))
        elif result.get("error"):
            print(f"\n❌ {result['error']}")
        else:
            print(f"\n{result.get('report', '')}")
        sys.exit(0 if result.get("success") else 1)

    print(f"🔍 正在 OCR 识别: {image_path.name} ...")
    result = analyze_exam_screenshot(image_path, save=True)

    if args.json:
        print(json.dumps({
            "success": result.get("success"),
            "parsed": result.get("parsed"),
            "record": result.get("record"),
            "report": result.get("report"),
            "error": result.get("error"),
        }, ensure_ascii=False))
        sys.exit(0 if result.get("success") else 1)

    if result["error"]:
        print(f"\n❌ {result['error']}")
        sys.exit(1)

    print(f"\n{result['report']}")


if __name__ == "__main__":
    main()
