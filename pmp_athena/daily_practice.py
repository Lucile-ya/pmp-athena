#!/usr/bin/env python3
"""
每日一练 — 微信硬路由 + CLI。

流程:
  menu     → 列出未完成日期（全部完成则提示随机）
  start    → 加载 PDF，开始出题
  grade    → 判卷并推进下一题
  resolve  → 解析用户输入的日期
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    from pmp_athena.config import NOTES_DIR
    from pmp_athena.utils.question_text import normalize_question_text
except ModuleNotFoundError:
    from config import NOTES_DIR
    from utils.question_text import normalize_question_text

DAILY_DIR = NOTES_DIR / "每日一练"
CONFIG_PATH = NOTES_DIR / "config.json"
STATE_PATH = NOTES_DIR / "daily_practice_state.json"

_YEAR = 2026

_AREA_KEYWORDS: list[tuple[str, list[str]]] = [
    ("干系人管理", ["干系人", "相关方", "stakeholder"]),
    ("敏捷", ["敏捷", "Scrum", "迭代", "产品负责人", "燃尽"]),
    ("整合管理", ["章程", "变更", "CCB", "整合"]),
    ("范围管理", ["范围", "WBS", "需求"]),
    ("进度管理", ["进度", "关键路径", "工期"]),
    ("成本管理", ["成本", "预算", "挣值", "CPI", "SPI"]),
    ("质量管理", ["质量", "审计", "控制质量"]),
    ("资源管理", ["资源", "团队", "RACI"]),
    ("沟通管理", ["沟通", "报告"]),
    ("风险管理", ["风险", "应急"]),
    ("采购管理", ["采购", "合同", "投标人"]),
    ("领导力", ["冲突", "激励", "教练"]),
]


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_pdf_text(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as e:
        raise RuntimeError("需要安装 pdfplumber") from e

    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n".join(parts)


_WATERMARK_ONLY = re.compile(r"^[料资部内育教迹骐练一日每\s]+$")


def _strip_watermark(text: str) -> str:
    """去掉水印行/短语，不逐字剥离（避免「一个→个」「内部→部」）。"""
    if not text:
        return text
    text = text.replace("内部资料", "")
    lines: list[str] = []
    for line in text.split("\n"):
        s = line.strip()
        if not s or _WATERMARK_ONLY.match(s):
            continue
        lines.append(line)
    return "\n".join(lines)


def _is_watermark_line(line: str) -> bool:
    s = line.strip()
    return not s or s == "内部资料" or bool(_WATERMARK_ONLY.match(s))


def _strip_question_header(line: str) -> str:
    """去掉题号/题型标签，避免 [单选] 被误当成第二个【】块吞掉整行题干。"""
    line = line.strip()
    line = re.sub(r"^\d+[\.．]\s*", "", line)
    line = re.sub(r"^【[^】]*】\s*", "", line)
    line = re.sub(r"^[料资部内育教迹骐练一日每\s]+", "", line)
    line = re.sub(r"^\[(?:单选|多选)[^\]]*\]\s*", "", line)
    return line.strip()


def _remove_inline_watermark_chars(text: str) -> str:
    """去掉带空格的水印字符，或已知错字模式（不泛化剥离「一/教」等常用字）。"""
    text = re.sub(
        r"(?<=[\u4e00-\u9fff])\s+[料资部内育教迹骐练]\s+(?=[\u4e00-\u9fff])",
        "",
        text,
    )
    return text


def _fix_watermark_typos(stem: str) -> str:
    """修复 PDF 水印插入导致的常见错字。"""
    for old, new in (
        ("项目经部理", "项目经理"),
        ("经部理", "经理"),
        ("（）", "（SMEs）"),
        ("包育含", "包含"),
        ("时内间", "时间"),
        ("以便部团队", "以便团队"),
        ("干系资人", "干系人"),
        ("包括干部系人", "包括干系人"),
        ("资育源", "资源"),
        ("并没 骐有", "并没有"),
        ("并没骐有", "并没有"),
        ("组织过程产", "组织过程资产"),
        ("经验训登记册", "经验教训登记册"),
        ("分配名源", "分配一名资源"),
        ("问题志", "问题日志"),
        ("问育题", "问题"),
        ("给内团队", "给团队"),
        ("下发给内团队", "下发给团队"),
        ("评估教费用", "评估费用"),
        ("料. ", ""),
        ("料.", ""),
    ):
        stem = stem.replace(old, new)
    stem = _remove_inline_watermark_chars(stem)
    stem = re.sub(r"^[单选多选\s]+", "", stem)
    stem = re.sub(r"([，,])[料资部内育教迹骐练一日每\s]+(并)", r"\1\2", stem)
    stem = re.sub(r"([A-E])\s+(公司)", r"\1\2", stem)
    idx = stem.find("？")
    if idx >= 0:
        stem = stem[: idx + 1]
    else:
        q = stem.find("?")
        if q >= 0:
            stem = stem[: q + 1]
    stem = re.sub(r"[料资部内育教迹骐练一日每\s]+$", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


def _clean_stem_legacy(stem: str) -> str:
    """旧版 PDF：中文题干 + 英文对照。"""
    stem = stem.replace("（SMEs）", "\ufffcSMEs\ufffc")
    stem = re.sub(r"[A-Za-z][A-Za-z0-9'\",.;:()\-/\s]{8,}", " ", stem)
    stem = stem.replace("\ufffcSMEs\ufffc", "（SMEs）")
    stem = re.sub(r"\s+", " ", stem).strip()
    parts = re.findall(r"[\u4e00-\u9fff0-9A-Za-z，。、；;（）()\"'\s？?]+", stem)
    merged = "".join(p.strip() for p in parts if len(p.strip()) >= 1)
    return _fix_watermark_typos(merged)


def _clean_stem(stem: str) -> str:
    """优先保留中文题干，去掉 PDF 噪声与双语 PDF 中的英文段落。"""
    stem = _strip_watermark(re.sub(r"\s+", " ", stem).strip())
    legacy = _clean_stem_legacy(stem)
    legacy_has_english = bool(
        re.search(r"(?<![（(])[A-Za-z]{4,}(?![）)])", legacy)
    )
    cn_segments = _extract_chinese_segments(stem)
    if cn_segments:
        with_q = [s for s in cn_segments if s.rstrip().endswith(("？", "?"))]
        pick = max(with_q or cn_segments, key=len)
        use_segment = legacy_has_english or len(pick) > len(legacy)
        if use_segment and len(pick) >= 12:
            return pick[:500]
    return legacy[:500] if legacy else stem[:500]


_PAREN_ACRONYM = re.compile(r"（[A-Za-z]{2,12}）")
_CHINESE_BEFORE_ENGLISH = re.compile(
    r"(?<=[。！？?；;：:）\)""''\u4e00-\u9fff])(?=[A-Za-z])"
    r"|\s+(?=[A-Z][a-z])",
)
_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9'\",.;:()\-/\s]*")
_WM_TRAIL = re.compile(r"[料资部内育教迹骐练一日每\s]+$")
_WM_AFTER_PUNCT = re.compile(r"([。！？?])[料资部内育教迹骐练一日每\s]+$")


def _split_chinese_before_english(text: str) -> str:
    parts = _CHINESE_BEFORE_ENGLISH.split(text, maxsplit=1)
    return parts[0].strip()


def _strip_latin_preserve_acronyms(cn: str) -> str:
    protected: dict[str, str] = {}

    def _keep(m: re.Match[str]) -> str:
        key = f"\ufffd{len(protected)}\ufffd"
        protected[key] = m.group(0)
        return key

    cn = _PAREN_ACRONYM.sub(_keep, cn)
    cn = _LATIN_RUN.sub("", cn)
    for key, value in protected.items():
        cn = cn.replace(key, value)
    return cn


def _strip_option_tail_noise(cn: str) -> str:
    cn = _WM_AFTER_PUNCT.sub(r"\1", cn)
    cn = _WM_TRAIL.sub("", cn)
    return cn.strip()


def _extract_chinese_segments(text: str) -> list[str]:
    """从双语选项文本中提取中文片段（兼容中文在前/英文在前两种 PDF）。"""
    segments = re.findall(
        r"[\u4e00-\u9fff][\u4e00-\u9fff0-9（）()、，。：；\s"
        r"\"'\u201c\u201dA-Za-z-？?]*[\u4e00-\u9fff。？?]?",
        text,
    )
    cleaned: list[str] = []
    for seg in segments:
        seg = re.sub(r"^[料资部内育教迹骐练一日每\s]+", "", seg.strip())
        if re.search(r"分值|单选题|多选题|问答题", seg):
            continue
        seg = _strip_latin_preserve_acronyms(seg)
        seg = _strip_option_tail_noise(_fix_watermark_typos(seg))
        seg = re.sub(r"\s+", " ", seg).strip()
        cn_count = len(re.findall(r"[\u4e00-\u9fff]", seg))
        latin_count = len(re.findall(r"[A-Za-z]", seg))
        if cn_count < 2 or latin_count > cn_count:
            continue
        if _WATERMARK_ONLY.match(seg.replace(" ", "")):
            continue
        cleaned.append(seg)
    if not cleaned:
        return []
    cleaned.sort(key=len, reverse=True)
    top: list[str] = []
    for seg in cleaned:
        if any(seg in other and seg != other for other in cleaned):
            continue
        top.append(seg)
    return top or cleaned


def _clean_option(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip()).replace("内部资料", "")
    text = re.sub(r"\s+[料资部内育教迹骐练一日每\s]+$", "", text)
    text = _fix_watermark_typos(text)

    segments = _extract_chinese_segments(text)
    if segments:
        return max(segments, key=len)[:120]

    # 旧版 PDF：中文在前、英文在后
    cn = _split_chinese_before_english(text)
    cn = re.sub(r"^[料资部内育教迹骐练一日每\s]+", "", cn)
    cn = _strip_latin_preserve_acronyms(cn)
    cn = _strip_option_tail_noise(_fix_watermark_typos(cn))
    cn = re.sub(r"\s+", " ", cn).strip()
    return cn[:120] if cn else ""


def _guess_knowledge_area(stem: str, explanation: str = "") -> str:
    text = f"{stem} {explanation}".lower()
    for area, keys in _AREA_KEYWORDS:
        for k in keys:
            if k.lower() in text:
                return area
    return "综合"


# PDF 题块/选项识别（兼容【单选题】【问答题】[单选]、A：/A、/A. 等格式）
_QUESTION_BLOCK_SPLIT = re.compile(r"(?=\n\s*\d+[\.．]\s*【)")
_OPTION_LINE = re.compile(
    r"^[料资部内育教迹骐练一日每\s]*([A-E])\s*[、\.:：]\s*(.*)$",
    re.I,
)
_ANSWER_LINE = re.compile(
    r"答案\s*[料资部内育教迹骐练一日每\s]*[:：]\s*([A-E,\s]+)",
    re.I,
)
_MULTI_MARKERS = (
    "多选题",
    "[多选",
    "选择两",
    "选两项",
    "choose two",
    "choosetwo",
    "choose 2",
)


def _normalize_pdf_text(text: str) -> str:
    text = text.replace("．", ".")
    text = re.sub(r"^内部资料\s*\n", "", text.strip())
    return text


def _is_multichoice_block(block: str) -> bool:
    lower = block.lower()
    return any(m.lower() in lower for m in _MULTI_MARKERS)


def _split_question_blocks(text: str) -> list[str]:
    return _QUESTION_BLOCK_SPLIT.split(_normalize_pdf_text(text))


def _parse_explanation(block: str) -> str:
    em = re.search(
        r"解析\s*[:：]\s*(.+?)(?=\n\s*\d+\.\s*【|\n答案\s*[:：]|$)",
        block,
        re.S,
    )
    if not em:
        return ""
    expl = em.group(1).strip()
    # 截断水印噪声行
    expl = re.sub(r"\n[料资部内育教迹骐练一日每\s]+\n", "\n", expl)
    return _strip_watermark(expl)[:200]


def _normalize_answer_text(ans: str, *, multi: bool) -> str:
    ans = ans.strip().upper().replace(",", "").replace(" ", "")
    if multi:
        return "".join(sorted(c for c in ans if c in "ABCDE"))
    return ans


def _parse_questions(text: str) -> list[dict[str, Any]]:
    blocks = _split_question_blocks(text)
    questions: list[dict[str, Any]] = []

    for block in blocks:
        m = re.match(r"\s*(\d+)\.", block)
        if not m:
            continue
        num = int(m.group(1))
        is_multi = _is_multichoice_block(block)
        opts: dict[str, str] = {}
        lines = block.split("\n")
        stem_lines: list[str] = []
        current: str | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue
            om = _OPTION_LINE.match(line)
            if om:
                current = om.group(1).upper()
                opts[current] = om.group(2)
            elif current and current in opts and not re.match(r"^\d+[\.．]", line):
                if _is_watermark_line(line):
                    continue
                opts[current] += " " + line
            elif not opts:
                if re.match(r"^\d+[\.．]", line):
                    line = _strip_question_header(line)
                if _is_watermark_line(line):
                    continue
                stem_lines.append(line)

        min_opts = 2 if is_multi else 4
        if len(opts) >= min_opts:
            stem = _clean_stem(" ".join(stem_lines))
            clean_opts = {k: _clean_option(v) for k, v in sorted(opts.items())}
            questions.append(
                {
                    "num": num,
                    "stem": stem,
                    "options": clean_opts,
                    "question_type": "multi" if is_multi else "single",
                }
            )

    return questions


def _parse_answers(text: str) -> dict[int, dict[str, str]]:
    blocks = _split_question_blocks(text)
    answers: dict[int, dict[str, str]] = {}

    for block in blocks:
        m = re.match(r"\s*(\d+)\.", block)
        if not m:
            continue
        num = int(m.group(1))
        am = _ANSWER_LINE.search(block)
        if not am:
            continue
        raw = am.group(1).upper().replace(",", "").replace(" ", "")
        is_multi = _is_multichoice_block(block) or len(raw) > 1
        answer = _normalize_answer_text(raw, multi=is_multi)
        answers[num] = {
            "answer": answer,
            "explanation": _parse_explanation(block),
            "question_type": "multi" if is_multi else "single",
        }
    return answers


def _date_from_filename(name: str) -> date | None:
    m = re.search(r"(\d{1,2})月(\d{1,2})日", name)
    if not m:
        return None
    return date(_YEAR, int(m.group(1)), int(m.group(2)))


def _format_label(d: date) -> str:
    return f"{d.month}月{d.day}日"


def _find_pdfs_for_date(d: date) -> tuple[Path | None, Path | None]:
    label = _format_label(d)
    q_pdf = a_pdf = None
    for f in DAILY_DIR.glob("*.pdf"):
        if "答案" in f.name:
            continue
        fd = _date_from_filename(f.name)
        if fd == d:
            q_pdf = f
            break
    if q_pdf:
        for f in DAILY_DIR.glob(f"*{label}*答案*.pdf"):
            a_pdf = f
            break
    return q_pdf, a_pdf


def _load_completed() -> set[str]:
    cfg = _load_json(CONFIG_PATH, {})
    items = cfg.get("daily_completed", [])
    return set(items) if isinstance(items, list) else set()


def _mark_completed(d: date) -> None:
    cfg = _load_json(CONFIG_PATH, {"daily_completed": []})
    if not isinstance(cfg.get("daily_completed"), list):
        cfg["daily_completed"] = []
    iso = d.isoformat()
    if iso not in cfg["daily_completed"]:
        cfg["daily_completed"].append(iso)
        cfg["daily_completed"].sort()
    _save_json(CONFIG_PATH, cfg)


def list_available_dates() -> list[date]:
    dates: list[date] = []
    for f in DAILY_DIR.glob("*.pdf"):
        if "答案" in f.name:
            continue
        d = _date_from_filename(f.name)
        if d:
            dates.append(d)
    return sorted(set(dates))


def list_incomplete_dates() -> list[date]:
    completed = _load_completed()
    return [d for d in list_available_dates() if d.isoformat() not in completed]


def load_questions_for_date(d: date) -> list[dict[str, Any]]:
    q_pdf, a_pdf = _find_pdfs_for_date(d)
    if not q_pdf:
        raise FileNotFoundError(f"未找到 {_format_label(d)} 的题目 PDF")

    q_text = _extract_pdf_text(q_pdf)
    questions = _parse_questions(q_text)
    if not questions:
        raise ValueError(
            f"无法解析 {_format_label(d)} 的题目（PDF 格式异常）。"
            f"请运行: python pmp_athena/daily_practice.py audit"
        )

    answers: dict[int, dict[str, str]] = {}
    if a_pdf and a_pdf.exists():
        answers = _parse_answers(_extract_pdf_text(a_pdf))

    merged: list[dict[str, Any]] = []
    for i, q in enumerate(questions, start=1):
        ans = answers.get(q["num"], {})
        stem = normalize_question_text(q["stem"])
        expl = ans.get("explanation", "")
        merged.append(
            {
                "index": i,
                "num": q["num"],
                "stem": stem,
                "options": q["options"],
                "correct_answer": ans.get("answer", ""),
                "explanation": expl,
                "knowledge_area": _guess_knowledge_area(stem, expl),
                "question_type": q.get("question_type")
                or ans.get("question_type", "single"),
            }
        )
    return merged


def load_random_questions(count: int = 10) -> tuple[list[dict[str, Any]], str]:
    pool: list[dict[str, Any]] = []
    for d in list_available_dates():
        try:
            qs = load_questions_for_date(d)
            for q in qs:
                q = dict(q)
                q["source_date"] = d.isoformat()
                q["source_label"] = _format_label(d)
                pool.append(q)
        except (FileNotFoundError, ValueError):
            continue

    if not pool:
        raise FileNotFoundError("题库为空，请确认 pmp_notes/每日一练/ 下有 PDF")

    random.shuffle(pool)
    picked = pool[: min(count, len(pool))]
    for i, q in enumerate(picked, start=1):
        q["index"] = i
    label = f"随机（{len(picked)} 题）"
    return picked, label


def _format_options(options: dict[str, str]) -> str:
    parts = []
    for letter in sorted(options.keys()):
        text = options[letter].strip()
        if len(text) > 80:
            text = text[:80] + "…"
        parts.append(f"{letter}. {text}")
    return " ".join(parts)


def _format_question(q: dict[str, Any], *, header: str = "") -> str:
    area = q.get("knowledge_area", "综合")
    multi_hint = ""
    if q.get("question_type") == "multi":
        n = len(q.get("options", {})) // 2  # 默认提示 2 项
        multi_hint = f"（多选，回复连续字母如 AB）"
    body = (
        f"📝 Q{q['index']} [{area}]{multi_hint}: {q['stem']}\n"
        f"{_format_options(q['options'])}"
    )
    return f"{header}\n\n{body}" if header else body


def _load_state() -> dict[str, Any] | None:
    data = _load_json(STATE_PATH, None)
    return data if isinstance(data, dict) else None


def _save_state(state: dict[str, Any]) -> None:
    _save_json(STATE_PATH, state)


def _clear_state() -> None:
    if STATE_PATH.exists():
        STATE_PATH.unlink()


def progress() -> dict[str, Any]:
    """扫描文件夹 + 对比 config，输出完整进度（无需 ingest）。"""
    all_dates = list_available_dates()
    completed = _load_completed()
    done = [d for d in all_dates if d.isoformat() in completed]
    incomplete = [d for d in all_dates if d.isoformat() not in completed]

    if not all_dates:
        text = (
            "⚠️ pmp_notes/每日一练/ 下暂无 PDF。\n\n"
            "请将培训机构 PDF 放入该文件夹，命名须含日期，例如：\n"
            "  2609每日一练8月1日.pdf\n"
            "  2609每日一练8月1日答案解析.pdf"
        )
        return {"status": "empty", "total_count": 0, "completed_count": 0, "text": text}

    if not incomplete:
        text = f"🎉 所有每日一练已全部完成！（共 {len(all_dates)} 天）"
        return {
            "status": "all_done",
            "total_count": len(all_dates),
            "completed_count": len(done),
            "incomplete": [],
            "text": text,
        }

    done_labels = "  ".join(_format_label(d) for d in done)
    inc_labels = "  ".join(_format_label(d) for d in incomplete)
    rate = round(len(done) / len(all_dates) * 100)
    text = (
        "📋 每日一练进度\n\n"
        f"📂 文件夹共 {len(all_dates)} 天 PDF（实时扫描，无需 ingest）\n\n"
        f"✅ 已完成（{len(done)} 天）:\n"
        f" {done_labels or '（无）'}\n\n"
        f"❌ 未完成（{len(incomplete)} 天）:\n"
        f" {inc_labels}\n\n"
        f"📊 完成率: {rate}%"
    )
    return {
        "status": "ok",
        "total_count": len(all_dates),
        "completed_count": len(done),
        "incomplete": [d.isoformat() for d in incomplete],
        "text": text,
    }


def week_check(*, today: date | None = None) -> dict[str, Any]:
    """检查本周一至周五已发布 PDF 的完成情况。"""
    today = today or date.today()
    # 本周一
    monday = today - timedelta(days=today.weekday())
    weekdays = [monday + timedelta(days=i) for i in range(5)]

    available = {d.isoformat() for d in list_available_dates()}
    completed = _load_completed()
    published = [d for d in weekdays if d.isoformat() in available]
    missing = [d for d in published if d.isoformat() not in completed]

    if not published:
        return {"status": "no_pdf", "text": ""}

    if not missing:
        text = "✅ 本周工作日每日一练已全部完成！继续保持～"
        return {"status": "all_done", "missing": [], "text": text}

    labels = "、".join(_format_label(d) for d in missing)
    prefix = "📅 上周每日一练检查\n\n" if today.weekday() == 0 else "📅 周末每日一练检查\n\n"
    text = (
        f"{prefix}"
        f"本周还有 {len(missing)} 天的每日一练未完成：{labels}\n\n"
        "💡 建议在周末补上，保持做题手感！"
    )
    return {"status": "incomplete", "missing": [d.isoformat() for d in missing], "text": text}


def menu(*, include_completed: bool = False) -> dict[str, Any]:
    incomplete = list_incomplete_dates()
    completed = _load_completed()
    all_dates = list_available_dates()

    if incomplete:
        labels = "、".join(_format_label(d) for d in incomplete)
        text = (
            "📋 每日一练\n\n"
            f"❌ 未完成（{len(incomplete)} 天）:\n"
            f" {labels}\n\n"
            "💡 回复日期开始，例如：`7月30` `7-30` `730` `30`\n"
            "已完成的日期可发：`再刷30` `重做7月30`"
        )
        return {
            "status": "select",
            "incomplete": [d.isoformat() for d in incomplete],
            "completed_count": len(completed),
            "total_count": len(all_dates),
            "text": text,
        }

    text = (
        "🎉 所有每日一练已全部完成！\n\n"
        f"✅ 已完成 {len(completed)}/{len(all_dates)} 天\n\n"
        "🎲 正在为你随机抽取 10 题…"
    )
    return {
        "status": "all_done",
        "incomplete": [],
        "completed_count": len(completed),
        "total_count": len(all_dates),
        "text": text,
    }


def _normalize_user_text(text: str) -> str:
    """全角数字 → 半角，便于解析微信输入。"""
    return text.translate(str.maketrans("０１２３４５６７８９", "0123456789")).strip()


def _try_make_date(month: int, day: int, year: int | None = None) -> date | None:
    y = year if year is not None else _YEAR
    try:
        return date(y, month, day)
    except ValueError:
        return None


def _resolve_day_in_current_month(day: int) -> date | None:
    """仅数字日期 → 当前月份 + 该日（如 30 → 7月30日）。"""
    return _try_make_date(date.today().month, day)


def _parse_compact_digits(raw: str) -> date | None:
    """
    纯数字紧凑格式：
      730 / 0730 → 7月30日
      30 / 9   → 当前月30日 / 当前月9日
    """
    if not raw.isdigit():
        return None
    n = len(raw)
    if n <= 2:
        return _resolve_day_in_current_month(int(raw))

    if n == 3:
        d = _try_make_date(int(raw[0]), int(raw[1:]))
        if d:
            return d
        return _try_make_date(int(raw[:2]), int(raw[2:]))

    if n == 4:
        d = _try_make_date(int(raw[:2]), int(raw[2:]))
        if d:
            return d
        return _try_make_date(int(raw[0]), int(raw[1:]))

    return None


def resolve_date(text: str) -> date | None:
    """
    解析用户输入的日期。支持：
      7月30日 / 7月30 / 7月30号 / 7-30 / 7.30 / 730 / 30（当前月）
    """
    text = _normalize_user_text(text.strip())
    text = re.sub(r"\s*每日一练\s*$", "", text).strip()

    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        return _try_make_date(int(m.group(2)), int(m.group(3)), int(m.group(1)))

    m = re.search(r"(\d{1,2})月(\d{1,2})(?:日|号)?", text)
    if m:
        return _try_make_date(int(m.group(1)), int(m.group(2)))

    m = re.fullmatch(r"(\d{1,2})号", text)
    if m:
        day = int(m.group(1))
        today = date.today()
        for month in range(today.month, 0, -1):
            d = _try_make_date(month, day)
            if d:
                return d
        return None

    m = re.fullmatch(r"(\d{1,2})[-.](\d{1,2})", text)
    if m:
        return _try_make_date(int(m.group(1)), int(m.group(2)))

    if re.fullmatch(r"\d{1,4}", text):
        return _parse_compact_digits(text)

    return None


def start_session(*, target_date: date | None = None, random_mode: bool = False) -> dict[str, Any]:
    _clear_state()

    session_date: date | None = target_date
    label = ""

    if random_mode:
        questions, label = load_random_questions(10)
        session_date = None
    elif target_date:
        questions = load_questions_for_date(target_date)
        label = _format_label(target_date)
    else:
        incomplete = list_incomplete_dates()
        if incomplete:
            return {
                "status": "select",
                "text": menu()["text"],
            }
        questions, label = load_random_questions(10)
        random_mode = True

    if not questions:
        return {"status": "error", "text": "⚠️ 未能加载题目，请检查 PDF 文件。"}

    missing_ans = [q for q in questions if not q.get("correct_answer")]
    if missing_ans:
        if len(missing_ans) == len(questions):
            label = _format_label(session_date) if session_date else "该套"
            return {
                "status": "error",
                "text": f"⚠️ {label} 每日一练缺少答案解析 PDF，暂无法自动判卷。",
            }
        questions = [q for q in questions if q.get("correct_answer")]

    state = {
        "mode": "random" if random_mode else "fixed",
        "date": session_date.isoformat() if session_date else None,
        "label": label,
        "questions": questions,
        "current_index": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "wrong_items": [],
    }
    _save_state(state)

    header = f"📝 {_format_label(session_date) if session_date else label}每日一练（共 {len(questions)} 题）"
    q0 = questions[0]
    return {
        "status": "question",
        "question_index": 1,
        "total": len(questions),
        "mode": state["mode"],
        "date": state["date"],
        "text": _format_question(q0, header=header),
    }


def grade_answers(user_answer: str) -> dict[str, Any]:
    """判卷入口：单选题可批量；多选题整串判当前题。"""
    raw = user_answer.strip().upper().replace(",", "").replace(" ", "")
    if not raw:
        return {"status": "error", "text": "⚠️ 请回复 A/B/C/D"}

    state = _load_state()
    if state and state.get("questions"):
        idx = int(state.get("current_index", 0))
        questions: list[dict] = state["questions"]
        if 0 <= idx < len(questions):
            if questions[idx].get("question_type") == "multi":
                return grade_current(raw)

    if len(raw) == 1:
        return grade_current(raw)
    return grade_batch(raw)


def grade_batch(user_answer: str) -> dict[str, Any]:
    raw = user_answer.strip().upper().replace(",", "").replace(" ", "")
    if not re.fullmatch(r"[A-E]+", raw):
        return {"status": "error", "text": "⚠️ 答案格式有误，请回复字母如 ACCAB"}

    state = _load_state()
    if not state or not state.get("questions"):
        return {
            "status": "error",
            "text": "⚠️ 当前没有进行中的每日一练，请发送「每日一练」开始。",
        }

    remaining = len(state["questions"]) - state["current_index"]
    if len(raw) > remaining:
        return {
            "status": "error",
            "text": f"⚠️ 提交了 {len(raw)} 个答案，但只剩 {remaining} 题。请核对后重发。",
        }

    start_correct = state["correct_count"]
    start_wrong_len = len(state.get("wrong_items", []))
    batch_correct = 0
    batch_wrong: list[dict[str, Any]] = []

    last_result: dict[str, Any] | None = None
    for letter in raw:
        state_before = _load_state() or {}
        correct_before = state_before.get("correct_count", 0)
        last_result = grade_current(letter)
        if last_result.get("status") == "error":
            return last_result
        state_mid = _load_state()
        if state_mid:
            batch_correct += state_mid.get("correct_count", 0) - correct_before
            batch_wrong = state_mid.get("wrong_items", [])[start_wrong_len:]
        elif last_result.get("done"):
            if (last_result.get("text") or "").lstrip().startswith("✅"):
                batch_correct += 1
            batch_wrong = (last_result.get("wrong_items") or [])[start_wrong_len:]

    assert last_result is not None
    if last_result.get("done") and not batch_wrong:
        batch_wrong = (last_result.get("wrong_items") or [])[start_wrong_len:]
    graded = len(raw)

    lines = [f"📊 批量判卷：正确 {batch_correct}/{graded}"]
    if batch_wrong:
        lines.append("")
        for w in batch_wrong:
            expl = (w.get("explanation") or "")[:80]
            line = (
                f"❌ Q{w['index']} [{w['knowledge_area']}]: "
                f"你的 {w['my_answer']} → 正确 {w['correct_answer']}"
            )
            if expl:
                line += f"\n  解析: {expl}"
            lines.append(line)

    if last_result.get("done"):
        lines.append("")
        total = last_result.get("total", graded)
        correct_total = last_result.get("correct", batch_correct)
        rate = last_result.get("rate", 0)
        lines.append(f"📋 每日一练完成：正确 {correct_total}/{total}（{rate}%）")
        finish_text = last_result.get("text", "")
        if "💾 已记录完成" in finish_text:
            for fl in finish_text.split("\n"):
                if fl.startswith("💾"):
                    lines.append(fl)
                    break
        return {**last_result, "text": "\n".join(lines)}

    q_part = last_result.get("text", "")
    if "📝" in q_part:
        q_part = q_part[q_part.find("📝") :]
        lines.append("")
        lines.append(q_part)
    return {**last_result, "text": "\n".join(lines)}


def grade_current(user_answer: str) -> dict[str, Any]:
    state = _load_state()
    if not state or not state.get("questions"):
        return {"status": "error", "text": "⚠️ 当前没有进行中的每日一练，请发送「每日一练」开始。"}

    idx = state["current_index"]
    questions: list[dict] = state["questions"]
    if idx >= len(questions):
        return {"status": "error", "text": "⚠️ 练习已结束，请发送「每日一练」重新开始。"}

    ans = user_answer.strip().upper().replace(",", "").replace(" ", "")
    q = questions[idx]
    q_type = q.get("question_type", "single")
    correct = str(q.get("correct_answer", "")).upper()

    if q_type == "multi":
        if not re.fullmatch(r"[A-E]{2,5}", ans):
            return {"status": "error", "text": "⚠️ 多选题请回复连续字母，如 AB 或 ABE"}
        ans = _normalize_answer_text(ans, multi=True)
        correct = _normalize_answer_text(correct, multi=True)
    elif ans not in "ABCD":
        return {"status": "error", "text": "⚠️ 请回复 A/B/C/D"}

    is_correct = ans == correct

    if is_correct:
        state["correct_count"] += 1
    else:
        state["wrong_count"] += 1
        state.setdefault("wrong_items", []).append(
            {
                "index": q["index"],
                "my_answer": ans,
                "correct_answer": correct,
                "stem": q["stem"],
                "knowledge_area": q.get("knowledge_area", "综合"),
                "explanation": q.get("explanation", ""),
            }
        )

    _record_answer(q, ans, is_correct=is_correct)

    state["current_index"] = idx + 1
    _save_state(state)

    lines: list[str] = []
    if is_correct:
        lines.append("✅ 正确！")
    else:
        expl = q.get("explanation", "")[:100]
        lines.append(f"❌ 正确答案是 {correct}" + (f" — {expl}" if expl else ""))

    if state["current_index"] >= len(questions):
        return _finish_session(state, lines)

    next_q = questions[state["current_index"]]
    lines.append("")
    lines.append(_format_question(next_q))
    return {
        "status": "question",
        "correct": is_correct,
        "question_index": state["current_index"] + 1,
        "total": len(questions),
        "done": False,
        "text": "\n".join(lines),
    }


def _record_answer(q: dict[str, Any], my_answer: str, *, is_correct: bool) -> None:
    try:
        from pmp_athena.record_answer import record_correct_answer, record_wrong_answer
    except ModuleNotFoundError:
        from record_answer import record_correct_answer, record_wrong_answer

    kwargs = dict(
        question=q["stem"],
        my_answer=my_answer,
        correct_answer=q.get("correct_answer", ""),
        knowledge_area=q.get("knowledge_area", "综合"),
        explanation=q.get("explanation", ""),
        source="daily_practice",
        parsed_by="daily_practice.py",
    )
    if is_correct:
        record_correct_answer(**kwargs)
    else:
        record_wrong_answer(**kwargs)


def _finish_session(state: dict[str, Any], prefix_lines: list[str]) -> dict[str, Any]:
    total = len(state["questions"])
    correct = state["correct_count"]
    wrong = state["wrong_count"]
    rate = round(correct / total * 100) if total else 0

    if state.get("mode") == "fixed" and state.get("date"):
        _mark_completed(date.fromisoformat(state["date"]))

    lines = list(prefix_lines)
    lines.append("")
    lines.append(f"📋 每日一练完成：正确 {correct}/{total}（{rate}%）")

    wrong_items = state.get("wrong_items", [])
    if wrong_items:
        lines.append("")
        lines.append("❌ 错题回顾：")
        for w in wrong_items:
            lines.append(
                f"Q{w['index']} [{w['knowledge_area']}]: "
                f"你的 {w['my_answer']} → 正确 {w['correct_answer']}"
            )
    else:
        lines.append("")
        lines.append("🎉 全部正确！")

    session_date = state.get("date")
    if session_date and state.get("mode") == "fixed":
        lines.append("")
        lines.append(f"💾 已记录完成：{_format_label(date.fromisoformat(session_date))}")

    _clear_state()

    return {
        "status": "done",
        "correct": correct,
        "total": total,
        "rate": rate,
        "done": True,
        "wrong_items": wrong_items,
        "text": "\n".join(lines),
    }


def audit_pdfs(*, expect_count: int = 10) -> dict[str, Any]:
    """扫描全部每日一练 PDF，报告解析完整性。"""
    rows: list[dict[str, Any]] = []
    ok_count = 0

    for d in list_available_dates():
        label = _format_label(d)
        q_pdf, a_pdf = _find_pdfs_for_date(d)
        row: dict[str, Any] = {
            "date": d.isoformat(),
            "label": label,
            "question_pdf": q_pdf.name if q_pdf else None,
            "answer_pdf": a_pdf.name if a_pdf else None,
            "ok": False,
        }
        try:
            if not q_pdf:
                row["error"] = "缺少题目 PDF"
            elif not a_pdf:
                row["error"] = "缺少答案解析 PDF"
            else:
                q_text = _extract_pdf_text(q_pdf)
                qs = _parse_questions(q_text)
                ans = _parse_answers(_extract_pdf_text(a_pdf))
                merged = load_questions_for_date(d)
                row.update(
                    {
                        "parsed_questions": len(qs),
                        "parsed_answers": len(ans),
                        "merged": len(merged),
                        "multi_count": sum(
                            1 for q in qs if q.get("question_type") == "multi"
                        ),
                        "missing_question_nums": sorted(
                            set(range(1, expect_count + 1)) - {q["num"] for q in qs}
                        ),
                        "missing_answer_nums": sorted(
                            q["num"] for q in qs if q["num"] not in ans
                        ),
                        "no_answer_in_merge": [
                            m["num"] for m in merged if not m.get("correct_answer")
                        ],
                    }
                )
                row["ok"] = (
                    len(qs) == expect_count
                    and len(ans) == expect_count
                    and len(merged) == expect_count
                    and not row["missing_answer_nums"]
                    and not row["no_answer_in_merge"]
                )
                if row["ok"]:
                    ok_count += 1
        except Exception as e:
            row["error"] = str(e)
        rows.append(row)

    failed = [r for r in rows if not r.get("ok")]
    return {
        "status": "ok" if not failed else "issues",
        "total_days": len(rows),
        "ok_days": ok_count,
        "failed_days": len(failed),
        "rows": rows,
        "text": _format_audit_report(rows, ok_count, len(rows)),
    }


def _format_audit_report(
    rows: list[dict[str, Any]], ok_count: int, total: int
) -> str:
    lines = [
        "📋 每日一练 PDF 解析审计",
        f"✅ 完整: {ok_count}/{total} 天",
        "",
    ]
    for r in rows:
        if r.get("ok"):
            lines.append(
                f"✅ {r['label']}: {r.get('merged', '?')} 题"
                f"（多选 {r.get('multi_count', 0)}）"
            )
        else:
            detail = r.get("error") or (
                f"题={r.get('parsed_questions')}/{r.get('parsed_answers')} "
                f"缺题号={r.get('missing_question_nums')} "
                f"缺答案={r.get('missing_answer_nums')}"
            )
            lines.append(f"❌ {r['label']}: {detail}")
    return "\n".join(lines)


_WM_CHAR_SET = set("料资部内育教迹骐练一日每")


def _inspect_question_quality(q: dict[str, Any]) -> list[str]:
    """检查单题题干/选项的内容质量问题。"""
    issues: list[str] = []
    num = q.get("num", "?")
    stem = q.get("stem", "")
    opts: dict[str, str] = q.get("options", {})

    if len(stem) < 12:
        issues.append(f"Q{num} 题干过短")
    if "（）" in stem or "()" in stem:
        issues.append(f"Q{num} 题干空括号")
    if re.search(r"(?<![（(])[A-Za-z]{4,}(?![）)])", stem):
        issues.append(f"Q{num} 题干含英文")
    if re.search(r"[料资部内育教迹骐练一日每]$", stem.strip()):
        issues.append(f"Q{num} 题干末尾水印")

    need = 4 if q.get("question_type") != "multi" else 2
    if len(opts) < need:
        issues.append(f"Q{num} 选项不足({len(opts)}/{need})")

    for key, val in sorted(opts.items()):
        label = f"Q{num}{key}"
        if not val.strip():
            issues.append(f"{label} 为空")
            continue
        if _WATERMARK_ONLY.match(val.replace(" ", "")):
            issues.append(f"{label} 仅水印")
        if "（）" in val or re.search(r"（\s*）", val):
            issues.append(f"{label} 空括号")
        if re.search(r"(?<![（(])[A-Za-z]{4,}(?![）)])", val):
            issues.append(f"{label} 含英文")
        if re.search(r"[。！？?][料资部内育教迹骐练]$", val):
            issues.append(f"{label} 句号后水印")
        if re.search(r"[料资部内育教迹骐练]$", val):
            issues.append(f"{label} 末尾水印")
    return issues


def audit_content(*, expect_count: int = 10) -> dict[str, Any]:
    """逐题检查全部每日一练的题干与选项内容质量。"""
    rows: list[dict[str, Any]] = []
    ok_count = 0
    total_issues = 0

    for d in list_available_dates():
        label = _format_label(d)
        row: dict[str, Any] = {"date": d.isoformat(), "label": label, "ok": False, "issues": []}
        try:
            merged = load_questions_for_date(d)
            if len(merged) != expect_count:
                row["issues"].append(f"题量 {len(merged)}/{expect_count}")
            for q in merged:
                row["issues"].extend(_inspect_question_quality(q))
            row["ok"] = not row["issues"]
            if row["ok"]:
                ok_count += 1
            else:
                total_issues += len(row["issues"])
        except Exception as e:
            row["issues"].append(str(e))
        rows.append(row)

    lines = [
        "📋 每日一练 题干/选项 质量审计",
        f"✅ 无问题: {ok_count}/{len(rows)} 天",
        f"⚠️ 共 {total_issues} 条问题",
        "",
    ]
    for r in rows:
        if r["ok"]:
            lines.append(f"✅ {r['label']}")
        else:
            lines.append(f"❌ {r['label']}:")
            for issue in r["issues"][:12]:
                lines.append(f"   · {issue}")
            if len(r["issues"]) > 12:
                lines.append(f"   · …还有 {len(r['issues']) - 12} 条")

    return {
        "status": "ok" if ok_count == len(rows) else "issues",
        "ok_days": ok_count,
        "total_days": len(rows),
        "total_issues": total_issues,
        "rows": rows,
        "text": "\n".join(lines),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="每日一练")
    sub = parser.add_subparsers(dest="command")

    p_menu = sub.add_parser("menu", help="列出未完成日期")
    p_menu.add_argument("--json", action="store_true")

    p_progress = sub.add_parser("progress", help="扫描文件夹，输出完成/未完成进度")
    p_progress.add_argument("--json", action="store_true")

    p_week = sub.add_parser("week-check", help="检查本周工作日每日一练完成情况")
    p_week.add_argument("--json", action="store_true")

    p_resolve = sub.add_parser("resolve-date", help="解析用户日期")
    p_resolve.add_argument("text")
    p_resolve.add_argument("--json", action="store_true")
    p_resolve.add_argument("--redo", action="store_true", help="已完成日期允许重刷")

    p_start = sub.add_parser("start", help="开始每日一练")
    p_start.add_argument("--date", help="YYYY-MM-DD")
    p_start.add_argument("--random", action="store_true")
    p_start.add_argument("--json", action="store_true")

    p_grade = sub.add_parser("grade", help="判卷")
    p_grade.add_argument("answer")
    p_grade.add_argument("--json", action="store_true")

    p_audit = sub.add_parser("audit", help="审计全部 PDF 解析完整性")
    p_audit.add_argument("--json", action="store_true")
    p_audit.add_argument("--expect", type=int, default=10, help="期望题数")

    p_content = sub.add_parser("audit-content", help="审计题干与选项内容质量")
    p_content.add_argument("--json", action="store_true")
    p_content.add_argument("--expect", type=int, default=10, help="期望题数")

    p_batch = sub.add_parser("batch", help="App 批量题收录/判卷（多题+答案串）")
    p_batch.add_argument("--questions", help="题目全文（含题号、选项、我的答案是）")
    p_batch.add_argument("--stdin", action="store_true", help="从标准输入读取题目全文")
    p_batch.add_argument("--key", help="标准答案串，如 CCCAB（可选；无则先收录待补录）")
    p_batch.add_argument("--json", action="store_true")

    p_bcomp = sub.add_parser("batch-complete", help="待判早餐题 + 仅答案串")
    p_bcomp.add_argument("--questions", nargs="?", default="")
    p_bcomp.add_argument("--stdin", action="store_true")
    p_bcomp.add_argument("--json", action="store_true")

    p_bupd = sub.add_parser("batch-update", help="补录批量题标准答案")
    p_bupd.add_argument("num", type=int, help="题号，如 41")
    p_bupd.add_argument("--correct-answer", "-c", required=True)
    p_bupd.add_argument("--explanation", "-e", default="")
    p_bupd.add_argument("--json", action="store_true")

    p_bupd_t = sub.add_parser("batch-update-text", help="从自然语言补录，如「更新41题，正确答案是 B」")
    p_bupd_t.add_argument("text", nargs="?", default="")
    p_bupd_t.add_argument("--stdin", action="store_true")
    p_bupd_t.add_argument("--json", action="store_true")

    p_bexp = sub.add_parser("batch-explain", help="解析最近一题（给我解析一下）")
    p_bexp.add_argument("--json", action="store_true")

    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    result: dict[str, Any]

    if args.command == "menu":
        result = menu()
    elif args.command == "progress":
        result = progress()
    elif args.command == "week-check":
        result = week_check()
    elif args.command == "resolve-date":
        d = resolve_date(args.text)
        incomplete = {x.isoformat() for x in list_incomplete_dates()}
        all_dates = {x.isoformat() for x in list_available_dates()}
        if d is None:
            result = {"status": "error", "date": None, "text": "⚠️ 无法识别日期，请发如 `7月30` `7-30` `730` `30`"}
        elif d.isoformat() not in all_dates:
            result = {"status": "error", "date": d.isoformat(), "text": f"⚠️ 题库中没有 {_format_label(d)} 的每日一练"}
        elif d.isoformat() in incomplete or not incomplete or getattr(args, "redo", False):
            result = {"status": "ok", "date": d.isoformat(), "label": _format_label(d), "text": ""}
        else:
            result = {
                "status": "already_done",
                "date": d.isoformat(),
                "text": f"📌 {_format_label(d)} 每日一练已完成。请选择未完成日期，或发送「随机每日一练」。",
            }
    elif args.command == "start":
        td = date.fromisoformat(args.date) if args.date else None
        result = start_session(target_date=td, random_mode=args.random)
    elif args.command == "grade":
        result = grade_answers(args.answer)
    elif args.command == "audit":
        result = audit_pdfs(expect_count=args.expect)
    elif args.command == "audit-content":
        result = audit_content(expect_count=args.expect)
    elif args.command == "batch":
        try:
            from pmp_athena.batch_practice import batch_complete_pending, batch_ingest
        except ModuleNotFoundError:
            from batch_practice import batch_complete_pending, batch_ingest
        body = args.questions or ""
        if args.stdin:
            body = sys.stdin.read()
        if not body.strip():
            result = {"status": "error", "text": "⚠️ 请提供题目文本（--questions 或 --stdin）"}
        else:
            result = batch_ingest(body, answer_key=args.key)
    elif args.command == "batch-complete":
        try:
            from pmp_athena.batch_practice import batch_complete_pending
        except ModuleNotFoundError:
            from batch_practice import batch_complete_pending
        body = sys.stdin.read() if args.stdin else (args.questions or "")
        if not body.strip():
            result = {"status": "error", "text": "⚠️ 请提供「我的答案是：XXX」"}
        else:
            result = batch_complete_pending(body) or {
                "status": "error",
                "text": "⚠️ 无待判批量题，请先发送早餐题或题目+答案串。",
            }
    elif args.command == "batch-update":
        try:
            from pmp_athena.batch_practice import batch_update
        except ModuleNotFoundError:
            from batch_practice import batch_update
        result = batch_update(
            args.num,
            correct_answer=args.correct_answer,
            explanation=args.explanation,
        )
    elif args.command == "batch-update-text":
        try:
            from pmp_athena.batch_practice import batch_update, parse_batch_update_command
        except ModuleNotFoundError:
            from batch_practice import batch_update, parse_batch_update_command
        body = args.text or ""
        if args.stdin:
            body = sys.stdin.read()
        parsed = parse_batch_update_command(body)
        if not parsed:
            result = {"status": "error", "text": "⚠️ 无法解析，格式：更新41题，正确答案是 B，解析：xxx"}
        else:
            result = batch_update(
                parsed["num"],
                correct_answer=parsed["correct_answer"],
                explanation=parsed["explanation"],
            )
    elif args.command == "batch-explain":
        try:
            from pmp_athena.batch_practice import batch_explain_last
        except ModuleNotFoundError:
            from batch_practice import batch_explain_last
        result = batch_explain_last()
    else:
        result = menu()

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result.get("text", ""))


if __name__ == "__main__":
    main()
