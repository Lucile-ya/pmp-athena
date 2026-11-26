#!/usr/bin/env python3
"""
薄弱点速记同步 — 从 error_log 追加易错陷阱、刷新 README、同步 00 总览卡、高频卡降级占位。

CLI:
  python pmp_athena/cheatsheet_sync.py sync          # 增量同步错题 → MD
  python pmp_athena/cheatsheet_sync.py refresh-readme
  python pmp_athena/cheatsheet_sync.py refresh-hf-cards
  python pmp_athena/cheatsheet_sync.py refresh-overview
  python pmp_athena/cheatsheet_sync.py all           # 全部
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from pmp_athena.config import CHEATSHEET_DIR, ERROR_LOG_PATH, QUESTION_BANK_PATH
    from pmp_athena.knowledge_retriever import normalize_area
    from pmp_athena.weak_area_cheatsheet import (
        DOMAIN_FILES,
        DOMAIN_ORDER,
        _resolve_cheatsheet_area,
        format_lecture_line,
        format_lecture_readme_table,
        get_weak_areas,
    )
except ModuleNotFoundError:
    from config import CHEATSHEET_DIR, ERROR_LOG_PATH, QUESTION_BANK_PATH
    from knowledge_retriever import normalize_area
    from weak_area_cheatsheet import (
        DOMAIN_FILES,
        DOMAIN_ORDER,
        _resolve_cheatsheet_area,
        format_lecture_line,
        format_lecture_readme_table,
        get_weak_areas,
    )

SYNC_STATE_PATH = CHEATSHEET_DIR / ".sync_state.json"
README_PATH = CHEATSHEET_DIR / "README.md"
OVERVIEW_DECISION = CHEATSHEET_DIR / "00-考前攻错决策卡.md"
OVERVIEW_COMPARE = CHEATSHEET_DIR / "00-三领域对比速记卡.md"
OVERVIEW_PROCESS = CHEATSHEET_DIR / "00-P0三领域完整知识点.md"
PROCESS_CHAIN = CHEATSHEET_DIR / "00-过程四条链.md"
# 合订章节锚点。每日一练错题按知识领域追加到对应节，不改手写口诀表。
PROCESS_CHAIN_SECTIONS: tuple[tuple[str, str], ...] = (
    ("整合管理", "整合"),
    ("进度管理", "进度"),
    ("范围管理", "范围"),
    ("质量管理", "质量"),
    ("成本管理", "成本"),
    ("风险管理", "风险"),
    ("采购管理", "采购"),
)
PROCESS_CHAIN_DAILY_CAP = 8
_PROCESS_ANCHOR_RE = re.compile(
    r'<a id="(?P<id>整合|进度|范围|质量|成本|风险|采购)"></a>'
)
AUTO_TRAP_HEADING = "### 来自你的错题（自动"
# 兼容旧标题，同步时整段替换
AUTO_TRAP_HEADING_ALIASES = (
    AUTO_TRAP_HEADING,
    "### 来自错题本（自动",
)
TRAP_SECTION_HEADERS = ("七、易错陷阱", "八、易错陷阱", "十、易错陷阱")
# 微信一屏可读；宁少勿截成半句
MAX_REMEMBER_COL = 42
MAX_PITFALL_COL = 48
MIN_FREQ_FOR_BOOST = 2
# 自动「背这句」区：去重追加、不设上限（合格口诀不丢）
MAX_NEW_TRAPS_PER_DOMAIN = 0  # 0 = 不截断
BOOTSTRAP_FREQ_ONLY = True  # 首次同步只写入错≥2次的模式

# 自动区禁止出现的「解析流水账 / OCR 残片」
_JUNK_MNEMONIC_RE = re.compile(
    r"(收缩解析|答案解析|本题考查|关键句[:：]|其余选项|易混淆选项|"
    r"^选[A-Ea-e][，,、]|解析[：:]|^\(?参考案例|"
    r"题目的问题在于|那么选项中|"
    r"^对于重大|^关键字|^D选项是最佳|^A选项|^B选项|^C选项|"
    r"不是最佳选项|首先要考虑的)"
)

_deferred_cheatsheet_sync = False


@dataclass
class SyncResult:
    traps_added: dict[str, int] = field(default_factory=dict)
    readme_updated: bool = False
    headers_updated: int = 0
    overview_updated: int = 0
    synced_ids: list[int] = field(default_factory=list)
    skipped_duplicate: int = 0
    hf_cards_count: int = 0
    hf_cards_updated: bool = False
    pdf_count: int = 0
    pdf_error: str = ""
    process_chain_rows: int = 0

    @property
    def total_traps(self) -> int:
        return sum(self.traps_added.values())

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        if self.total_traps:
            parts = [f"{a} {n}条" for a, n in self.traps_added.items() if n]
            lines.append(f"- 可背口诀已刷新 **{self.total_traps}** 条（{', '.join(parts)}）")
        if self.hf_cards_updated:
            lines.append(
                f"- 高频卡已降级占位（错≥3 仍计 **{self.hf_cards_count}** 道，不当教材）"
            )
        elif self.hf_cards_count:
            lines.append(f"- 高频顽疾索引 **{self.hf_cards_count}** 道（练题走「复习错题」）")
        if self.readme_updated:
            lines.append("- README 优先级表已刷新")
        if self.headers_updated:
            lines.append(f"- 已更新 {self.headers_updated} 份领域速记的数据头")
        if self.overview_updated:
            lines.append(f"- 已同步 {self.overview_updated} 份总览卡（攻错/对比/Process合订）")
        if self.process_chain_rows:
            lines.append(
                f"- 过程四条链已追加每日一练口诀 **{self.process_chain_rows}** 条"
            )
        if self.pdf_count:
            lines.append(
                f"- 速记 PDF 已导出 **{self.pdf_count}** 份 → `薄弱点速记/pdf/{date.today().isoformat()}/`"
            )
        if self.pdf_error:
            lines.append(f"- 速记 PDF 导出失败：{self.pdf_error[:80]}")
        if self.skipped_duplicate:
            lines.append(f"- 跳过 {self.skipped_duplicate} 条重复")
        if not lines:
            lines.append("- 速记卡已是最新")
        return lines


def _load_errors() -> list[dict]:
    try:
        data = json.loads(ERROR_LOG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _load_sync_state() -> dict:
    try:
        data = json.loads(SYNC_STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_sync_state(state: dict) -> None:
    CHEATSHEET_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _question_gist(question: str, limit: int = 22) -> str:
    q = re.sub(r"\s+", " ", (question or "").strip())
    q = re.sub(r"^[Q\d\.、\s]+", "", q)
    if len(q) > limit:
        return q[:limit] + "…"
    return q or "（题干缺失）"


def _truncate(text: str, limit: int) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= limit:
        return t
    # 尽量在顿号/逗号处切断，避免半句
    cut = t[:limit]
    for sep in ("，", "、", "；", " ", "·"):
        pos = cut.rfind(sep)
        if pos >= max(12, limit // 2):
            return cut[:pos].rstrip("，、；· ") 
    return t[: limit - 1].rstrip("，、；· ") + "…"


def _strip_mnemonic_noise(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.sub(r"^钉死[：:]\s*", "", t)
    t = re.sub(r"^(?:解析|Explanation)\s*[：:]\s*", "", t, flags=re.I)
    t = t.strip("*，,。；; ")
    return t


def _parse_pipe_mnemonic(expl: str) -> tuple[str, str] | None:
    """explanation 形如「背这句 | 别踩」时直接拆成两列。"""
    text = _strip_mnemonic_noise(expl or "")
    if "|" not in text and "｜" not in text:
        return None
    text = text.replace("｜", "|")
    left, right = [p.strip() for p in text.split("|", 1)]
    if len(left) < 6 or len(right) < 2:
        return None
    if _is_junk_mnemonic(left):
        return None
    return left, right


def _is_junk_mnemonic(text: str) -> bool:
    """不可背：解析残片、题干流水、半截 OCR。"""
    t = (text or "").strip()
    if len(t) < 6:
        return True
    if _JUNK_MNEMONIC_RE.search(t):
        return True
    if "易混淆选项" in t:
        return True
    # 半截省略号 = 未写完，一律不进自动区
    if "…" in t or "..." in t:
        return True
    # 明显未完成的半句
    if t.endswith(("和", "的", "了", "与", "及", "将", "把", "从", "在", "别", "锁")):
        return True
    return False


def _quality_trap_row(remember: str, pitfall: str) -> bool:
    if _is_junk_mnemonic(remember):
        return False
    if not pitfall or len(pitfall.strip()) < 4:
        return False
    # 右列也禁止半截
    if "…" in pitfall or "..." in pitfall:
        return False
    if pitfall.rstrip().endswith(("和", "的", "了", "与", "别", "锁", "批")):
        return False
    if _JUNK_MNEMONIC_RE.search(pitfall) and not pitfall.startswith("别"):
        return False
    return True


def build_memory_trap(error: dict, *, freq: int = 1) -> tuple[str, str]:
    """可背诵行：(背这句, 别踩)。禁止塞题干/OCR 解析。

    优先顺序：explanation 管道口诀 → 根因诊断 → 规则口诀 → 极简「别选X应选Y」。
    质量不合格时返回空串，由上层跳过该条。
    """
    try:
        from pmp_athena.error_insights import build_mnemonic, build_trap_line
        from pmp_athena.root_cause_engine import diagnose
        from pmp_athena.root_cause_variants import get_root_cause_summary
    except ImportError:
        from error_insights import build_mnemonic, build_trap_line
        from root_cause_engine import diagnose
        from root_cause_variants import get_root_cause_summary

    my_a = str(error.get("my_answer") or "?").strip().upper()
    ok_a = str(error.get("correct_answer") or "?").strip().upper()

    remember = ""
    pitfall = ""

    # 1) 人工/入库时写的「口诀 | 别踩」
    piped = _parse_pipe_mnemonic(str(error.get("explanation") or ""))
    if piped:
        remember, pitfall = piped

    # 2) 根因引擎
    diag = diagnose(error) if not remember else None
    if not remember and diag:
        summary = get_root_cause_summary(diag.get("name", ""))
        if summary and summary.get("core_distinction"):
            remember = summary["core_distinction"]
        else:
            remember = diag.get("mnemonic") or ""
        traps = (summary or {}).get("common_traps") or []
        if traps:
            pitfall = traps[0]

    # 3) 规则口诀（仍 junk 则放弃该条，不强凑半截）
    if not remember or _is_junk_mnemonic(remember):
        cand = build_mnemonic(error)
        remember = "" if (
            not cand
            or cand.startswith("记牢正确选项")
            or _is_junk_mnemonic(cand)
        ) else cand

    remember = _strip_mnemonic_noise(remember)
    if not remember:
        return "", ""

    if not pitfall or _is_junk_mnemonic(pitfall):
        try:
            tip = build_trap_line(error)
        except Exception:
            tip = ""
        if tip and not _is_junk_mnemonic(tip):
            pitfall = tip
    if not pitfall:
        pitfall = f"别选 {my_a}，应选 {ok_a}"
    elif not pitfall.startswith("别"):
        pitfall = f"别选 {my_a} · {_strip_mnemonic_noise(pitfall)}"

    # 超长宁换短句，绝不截成半句
    if len(remember) > MAX_REMEMBER_COL:
        # 管道口诀过长：保留前半完整语义失败则丢弃
        return "", ""
    left = remember
    if len(pitfall) > MAX_PITFALL_COL:
        right = f"别选 {my_a}，应选 {ok_a}"
    else:
        right = pitfall
    if freq >= MIN_FREQ_FOR_BOOST and len(right) + 4 <= MAX_PITFALL_COL:
        right = f"{right}（×{freq}）"

    if not _quality_trap_row(left, right):
        return "", ""
    return left, right


def build_trap_row(error: dict, *, freq: int = 1) -> tuple[str, str]:
    """兼容旧名：现为可背诵口诀行。"""
    return build_memory_trap(error, freq=freq)


def _row_key(wrong: str, right: str) -> str:
    # 按口诀去重（左列），同类根因只留一条
    left = re.sub(r"\s+", " ", (wrong or "")).strip().lower()
    left = re.sub(r"（×\d+）$", "", left)
    return left or re.sub(r"\s+", " ", f"{wrong}|{right}").lower()


def _existing_trap_keys(content: str) -> set[str]:
    keys: set[str] = set()
    for line in content.splitlines():
        if "|" not in line or line.strip().startswith("|---"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) >= 2 and parts[0] not in ("❌ 错", "错", "问", "背这句", "别踩"):
            keys.add(_row_key(parts[0], parts[1]))
    return keys


def _parse_auto_trap_rows(section: str) -> list[tuple[str, str]]:
    """从易错节里抽出「来自你的错题（自动）」表行，供去重追加。"""
    m = re.search(
        r"###\s*来自(?:你的错题|错题本)[^\n]*\n(.*?)(?=\n### |\n## |\Z)",
        section,
        re.DOTALL,
    )
    if not m:
        return []
    rows: list[tuple[str, str]] = []
    for line in m.group(1).splitlines():
        if "|" not in line or line.strip().startswith("|---"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 2:
            continue
        if parts[0] in ("❌ 错", "错", "问", "背这句", "别踩"):
            continue
        rows.append((parts[0], parts[1]))
    return rows


def _merge_trap_rows(
    primary: list[tuple[str, str]],
    secondary: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """primary 优先（本次同步），再追加 secondary（文件里已有），按口诀去重。"""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for remember, pitfall in list(primary) + list(secondary):
        if not _quality_trap_row(remember, pitfall):
            continue
        if remember.startswith("记牢正确选项"):
            continue
        rk = _row_key(remember, pitfall)
        if not rk or rk in seen:
            continue
        seen.add(rk)
        out.append((remember, pitfall))
    return out


def _find_trap_section_span(content: str) -> tuple[int, int] | None:
    for header in TRAP_SECTION_HEADERS:
        m = re.search(rf"^##\s*{re.escape(header)}\s*$", content, re.MULTILINE)
        if m:
            start = m.end()
            rest = content[start:]
            nxt = re.search(r"^##\s", rest, re.MULTILINE)
            end = start + (nxt.start() if nxt else len(rest))
            return start, end
    return None


def _strip_auto_trap_block(section: str) -> str:
    """删掉旧自动区（含题干流水账），保留手写易错表。"""
    pattern = re.compile(
        r"\n*###\s*来自(?:你的错题|错题本)[^\n]*\n(?:.*?)(?=\n### |\n## |\Z)",
        re.DOTALL,
    )
    cleaned = pattern.sub("\n", section)
    # 再扫一遍：防止标题缺右括号或夹在表格中间
    pattern2 = re.compile(
        r"\n*###\s*来自错题本[^\n]*\n(?:\|[^\n]*\n)+",
        re.MULTILINE,
    )
    cleaned = pattern2.sub("\n", cleaned)
    return cleaned.rstrip() + "\n"


def _is_option_letter_junk(text: str) -> bool:
    """判卷残留：别再选/锁X/应选X 等，不当教材行。"""
    t = text or ""
    return bool(
        re.search(r"别再选|别选\s*[A-Ea-e]|应选\s*[A-Ea-e]|锁\s*[A-Ea-e]|实践指南|P\d{2}\b", t)
    )


def _pitfall_to_wrong_col(pitfall: str) -> str:
    """把「别xxx」收成易错/闪卡问句。垃圾选项句返回空。"""
    if _is_option_letter_junk(pitfall):
        return ""
    t = (pitfall or "").strip()
    t = re.sub(r"^别+", "", t).strip()
    t = re.sub(r"（×\d+）$", "", t).strip()
    if len(t) > MAX_PITFALL_COL:
        t = t[: MAX_PITFALL_COL - 1] + "…"
    return t


def _clean_display_rows(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """展示用：丢掉选项字母垃圾坑，口诀仍可留。"""
    out: list[tuple[str, str]] = []
    for remember, pitfall in rows:
        if _is_option_letter_junk(remember):
            continue
        if _is_option_letter_junk(pitfall):
            # 坑是垃圾时，用短「别踩」占位，避免整行丢掉好口诀
            pitfall = "别踩干扰项"
        if len((remember or "").strip()) < 4:
            continue
        out.append((remember.strip(), pitfall.strip()))
    return out


def _scrub_hand_trap_junk_rows(
    section: str,
    auto_rows: list[tuple[str, str]] | None = None,
) -> str:
    """清掉误合并进手写易错表的垃圾行 / 与自动区重复的反转行。"""
    m = re.search(
        r"(\|\s*❌\s*错\s*\|\s*✅\s*对\s*\|\s*\n\|[-| :]+\|\s*\n)((?:\|[^\n]+\n)*)",
        section,
    )
    if not m:
        return section
    header, body = m.group(1), m.group(2)
    auto_remember = {
        re.sub(r"\s+", "", (r or "")).lower()
        for r, _p in (auto_rows or [])
        if r
    }
    auto_pit_core = {
        re.sub(r"\s+", "", _pitfall_to_wrong_col(p) or p or "").lower()
        for _r, p in (auto_rows or [])
        if p and not _is_option_letter_junk(p)
    }
    kept: list[str] = []
    for line in body.splitlines(keepends=True):
        if not line.strip().startswith("|"):
            kept.append(line)
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 2:
            kept.append(line)
            continue
        left, right = parts[0], parts[1]
        if _is_option_letter_junk(left) or _is_option_letter_junk(right):
            continue
        # 反转合并行：右列=自动口诀，或左列=自动坑 → 与自动区重复，删
        rk = re.sub(r"\s+", "", right).lower()
        lk = re.sub(r"\s+", "", left).lower()
        if rk in auto_remember or lk in auto_pit_core:
            # 保留带「模拟考试1」标注的手写精华行
            if "模拟考试" not in left and "模拟考试" not in right:
                continue
        kept.append(line)
    return section[: m.start()] + header + "".join(kept) + section[m.end() :]


def _merge_hand_trap_table(section: str, rows: list[tuple[str, str]]) -> str:
    """不再往手写易错表追加（避免日积月累重复）。只清垃圾/重复行。"""
    return _scrub_hand_trap_junk_rows(section, auto_rows=rows)


def _rewrite_xian_gaodong_auto(
    content: str,
    rows: list[tuple[str, str]],
    today: str,
) -> str:
    """在「先搞懂」下整段重写「### 自动钉死」要点（没有该章则跳过）。"""
    m = re.search(r"^##\s*先搞懂[^\n]*\s*$", content, re.MULTILINE)
    if not m:
        return content
    start = m.end()
    rest = content[start:]
    nxt = re.search(r"^##\s", rest, re.MULTILINE)
    end = start + (nxt.start() if nxt else len(rest))
    section = content[start:end]
    # 去掉旧自动钉死块
    section = re.sub(
        r"\n*###\s*自动钉死[^\n]*\n(?:.*?)(?=\n### |\n## |\Z)",
        "\n",
        section,
        flags=re.DOTALL,
    )
    if rows:
        bullets = []
        for i, (remember, pitfall) in enumerate(rows[:5], 1):
            bullets.append(f"{i}. **{remember}** — {pitfall}")
        block = (
            f"\n### 自动钉死（更新于 {today}）\n\n"
            "> 来自错题本高频口诀，跟「易错陷阱 / 背这句」同源，每天先扫这 5 条。\n\n"
            + "\n".join(bullets)
            + "\n"
        )
        # 插在「先搞懂」标题后、第一个 ### 手工节之前；若无手工 ### 则放段首
        first_h3 = re.search(r"^###\s+", section, re.MULTILINE)
        if first_h3:
            section = section[: first_h3.start()] + block + "\n" + section[first_h3.start() :]
        else:
            section = block + section
    return content[:start] + section + content[end:]


def _parse_flash_auto_rows(section: str) -> list[tuple[str, str]]:
    """从闪卡节抽出「### 自动加练」表行 → (口诀, 问句坑)，供去重追加。"""
    m = re.search(
        r"###\s*自动加练[^\n]*\n(.*?)(?=\n### |\n## |\Z)",
        section,
        re.DOTALL,
    )
    if not m:
        return []
    rows: list[tuple[str, str]] = []
    for line in m.group(1).splitlines():
        if "|" not in line or line.strip().startswith("|---"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 2:
            continue
        if parts[0] in ("问", "答", "背这句", "别踩"):
            continue
        question = parts[0].rstrip("？?").strip()
        remember = parts[1].strip()
        if len(remember) < 4 or len(question) < 4:
            continue
        # 存成 (口诀, 坑)：坑用问句原文，写出时再走 _pitfall_to_wrong_col
        rows.append((remember, question))
    return rows


def _rewrite_flash_auto(
    content: str,
    rows: list[tuple[str, str]],
    today: str,
) -> str:
    """在闪卡节末尾重写「### 自动加练」表：合格行去重追加，不覆盖、不设条数上限。"""
    m = re.search(r"^##\s*🃏\s*闪卡[^\n]*\s*$", content, re.MULTILINE)
    if not m:
        return content
    start = m.end()
    rest = content[start:]
    nxt = re.search(r"^##\s", rest, re.MULTILINE)
    end = start + (nxt.start() if nxt else len(rest))
    section = content[start:end]
    existing = _parse_flash_auto_rows(section)
    section = re.sub(
        r"\n*###\s*自动加练[^\n]*\n(?:.*?)(?=\n### |\n## |\Z)",
        "\n",
        section,
        flags=re.DOTALL,
    )
    incoming = _clean_display_rows(rows)
    # 闪卡只要「能当自测问句」的坑；占位「别踩干扰项」不进加练（口诀仍在易错表）
    incoming_flash = [
        (r, p)
        for r, p in incoming
        if (p or "").strip() not in ("别踩干扰项", "别踩", "踩干扰项")
    ]
    existing_flash = [
        (r, p)
        for r, p in existing
        if (p or "").strip() not in ("别踩干扰项", "别踩", "踩干扰项")
    ]
    # 新同步优先，再保留文件里已有加练行
    merged = _merge_trap_rows(incoming_flash, existing_flash)
    if merged:
        lines = ["| 问 | 答 |", "|----|-----|"]
        for remember, pitfall in merged:
            q = _pitfall_to_wrong_col(pitfall)
            if len(q) < 4:
                # 已有行的「问」本身往往已去「别」，再剥一次仍可用
                q = (pitfall or "").strip()
            if len(q) < 4 or q in ("踩干扰项", "别踩"):
                continue
            lines.append(f"| {q}？ | {remember} |")
        if len(lines) > 2:
            block = (
                f"\n### 自动加练（更新于 {today}）\n\n"
                "> 遮住右列自测；与错题口诀同步，**去重追加**、不设条数上限（合格行不丢）。\n\n"
                + "\n".join(lines)
                + "\n"
            )
            section = section.rstrip() + "\n" + block
    return content[:start] + section + content[end:]


def _rewrite_decision_auto_patch(
    content: str,
    rows: list[tuple[str, str]],
    today: str,
) -> str:
    """在做题决策链代码块**闭合后**追加/替换自动补丁（绝不写入 fence 内）。"""
    m = re.search(r"^##\s*.*做题决策链\s*$", content, re.MULTILINE)
    if not m:
        return content
    start = m.end()
    rest = content[start:]
    nxt = re.search(r"^##\s", rest, re.MULTILINE)
    end = start + (nxt.start() if nxt else len(rest))
    section = content[start:end]
    # 清掉误插进代码块内外的旧补丁
    section = re.sub(
        r"\n*>\s*\*\*自动补丁（[^)]+）\*\*[^\n]*\n?",
        "\n",
        section,
    )
    rows = _clean_display_rows(rows)
    if not rows:
        return content[:start] + section + content[end:]
    items = "；".join(remember for remember, _p in rows[:6])
    patch = f"\n> **自动补丁（{today}）**：{items}\n"
    # 匹配完整 ```...```，插在闭合 fence 之后
    fence = re.search(r"```[^\n]*\n.*?```", section, re.DOTALL)
    if fence:
        pos = fence.end()
        section = section[:pos] + patch + section[pos:]
    else:
        section = section.rstrip() + "\n" + patch
    return content[:start] + section + content[end:]


def _rewrite_auto_memory_section(
    content: str,
    rows: list[tuple[str, str]],
    today: str,
) -> str:
    """重写自动区：合格口诀去重追加（不截断）；手写易错表只清垃圾；钉死/决策整段覆盖；闪卡加练去重追加。"""
    rows = _clean_display_rows(rows)
    span = _find_trap_section_span(content)
    if not span:
        updated = content
        merged_rows = rows
    else:
        start, end = span
        raw_section = content[start:end]
        existing_auto = _parse_auto_trap_rows(raw_section)
        merged_rows = _merge_trap_rows(rows, existing_auto)
        section = _strip_auto_trap_block(raw_section)
        section = _merge_hand_trap_table(section, merged_rows)
        if merged_rows:
            table_rows = "".join(f"| {w} | {r} |\n" for w, r in merged_rows)
            block = (
                f"\n{AUTO_TRAP_HEADING} · 更新于 {today}）\n\n"
                "> 只背左列整句；右列是坑。半截解析/OCR 已过滤。"
                "本区**自动更新、去重追加**，合格口诀不丢、不设条数上限。\n\n"
                "| 背这句 | 别踩 |\n"
                "|--------|------|\n"
                f"{table_rows}"
            )
            section = section.rstrip() + block + "\n"
        updated = content[:start] + section + content[end:]

    # 钉死/闪卡仍只取前几条，避免「先搞懂」刷屏
    updated = _rewrite_xian_gaodong_auto(updated, merged_rows, today)
    updated = _rewrite_flash_auto(updated, merged_rows, today)
    updated = _rewrite_decision_auto_patch(updated, merged_rows, today)
    return updated


def _insert_auto_trap_rows(content: str, new_rows: list[tuple[str, str]], today: str) -> str:
    """兼容旧测试名：整段重写自动区。"""
    return _rewrite_auto_memory_section(content, new_rows, today)


def _map_error_area(error: dict) -> str | None:
    raw = error.get("knowledge_area") or ""
    mapped = _resolve_cheatsheet_area(raw)
    if mapped:
        return mapped
    area = normalize_area(raw)
    if area in DOMAIN_FILES:
        return area
    return None


_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "商业环境": ("战略", "合规", "效益", "商业", "论证", "变革", "NPV", "法规", "价值", "矩阵"),
    "成本管理": ("成本", "预算", "CPI", "EAC", "储备", "挣值", "EV", "融资", "TCPI", "AC"),
    "敏捷/混合方法": ("敏捷", "冲刺", "Sprint", "PO", "Scrum", "迭代", "看板", "燃尽", "故事"),
    "质量管理": ("质量", "QA", "QC", "审计", "缺陷", "鱼骨", "帕累托", "预防", "控制质量"),
    "进度管理": ("进度", "关键路径", "赶工", "快速跟进", "SV", "SPI", "浮动", "压缩", "WBS估算"),
    "资源管理": ("团队", "冲突", "资源", "仆人", "RACI", "导师", "隐性", "授权", "职能", "障碍", "士气", "站会"),
    "干系人管理": ("干系人", "相关方", "参与", "权力", "利益", "登记册", "抵制"),
    "整合管理": ("变更", "CCB", "章程", "整合", "收尾", "裁剪", "文档", "DoD", "验收"),
    "范围管理": ("范围", "WBS", "需求", "镀金", "蔓延", "RTM", "确认范围", "验收标准"),
}


def _relevant_to_domain(area: str, remember: str, pitfall: str) -> bool:
    """口诀须和本域沾边，防止风险/合同万能句串台。"""
    hints = _DOMAIN_HINTS.get(area)
    if not hints:
        return True
    blob = f"{remember} {pitfall}"
    return any(h in blob for h in hints)


def collect_memory_traps_by_area(
    errors: list[dict],
) -> dict[str, list[tuple[str, str, int, int]]]:
    """返回 {领域: [(背这句, 别踩, error_id, freq), ...]}。

    排序：① explanation 管道口诀（可背）→ ② 高频 → ③ 其它合格低频。
    宁缺毋滥：过滤 OCR 半截与跨域万能句；条数默认不截断（去重追加）。
    """
    by_area: dict[str, list[tuple[str, str, int, int, str, int]]] = defaultdict(list)
    # 按题干 gist 聚合频次（同一题多次错）
    freq_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for err in errors:
        area = _map_error_area(err)
        eid = err.get("id")
        if not area or not isinstance(eid, int):
            continue
        gist = _question_gist(err.get("question", ""), 40)
        freq_groups[(area, gist)].append(err)

    for (area, _gist), group in freq_groups.items():
        rep = max(group, key=lambda e: e.get("timestamp") or e.get("date") or "")
        eid = rep.get("id")
        if not isinstance(eid, int):
            continue
        freq = len(group)
        piped = 1 if _parse_pipe_mnemonic(str(rep.get("explanation") or "")) else 0
        remember, pitfall = build_memory_trap(rep, freq=freq)
        if not remember or not pitfall:
            continue
        if not piped and not _relevant_to_domain(area, remember, pitfall):
            continue
        ts = str(rep.get("timestamp") or rep.get("date") or "")
        by_area[area].append((remember, pitfall, eid, freq, ts, piped))

    out: dict[str, list[tuple[str, str, int, int]]] = {}
    for area, items in by_area.items():
        # 管道口诀优先，再高频，再新
        items.sort(key=lambda x: (-x[5], -x[3], x[4]))
        trimmed: list[tuple[str, str, int, int]] = []
        seen: set[str] = set()
        for remember, pitfall, eid, freq, _ts, _piped in items:
            if not _quality_trap_row(remember, pitfall):
                continue
            rk = _row_key(remember, pitfall)
            if not rk or rk in seen:
                continue
            if remember.startswith("记牢正确选项"):
                continue
            seen.add(rk)
            trimmed.append((remember, pitfall, eid, freq))
            if MAX_NEW_TRAPS_PER_DOMAIN > 0 and len(trimmed) >= MAX_NEW_TRAPS_PER_DOMAIN:
                break
        if trimmed:
            out[area] = trimmed
    return out


def collect_trap_candidates(
    errors: list[dict],
    synced_ids: set[int],
) -> dict[str, list[tuple[str, str, int]]]:
    """兼容旧接口：转成 [(背这句, 别踩, id), ...]。"""
    _ = synced_ids
    raw = collect_memory_traps_by_area(errors)
    return {
        area: [(a, b, eid) for a, b, eid, _f in rows]
        for area, rows in raw.items()
    }


def _cell(text: str, limit: int) -> str:
    t = re.sub(r"\s+", "", (text or "").strip())
    t = t.replace("|", "／")
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


_NARRATIVE_REMEMBER = re.compile(
    r"^(那么|这暗示|当一个|所以要|在这个|一个|项目经理正在|并要求|提供一个|这个计划|通过回顾|家公司)"
)
_ACTION_PRIMARY = ("应该", "先", "不要", "协商", "沟通")
_ACTION_SECONDARY = ("验证", "计划", "CCB", "QA", "QC")


def _usable_daily_remember(text: str) -> bool:
    """合订只收能当口诀的句子，不收题干残片。"""
    t = (text or "").strip()
    if not t or _NARRATIVE_REMEMBER.search(t) or _is_junk_mnemonic(t):
        return False
    return any(h in t for h in _ACTION_PRIMARY + _ACTION_SECONDARY)


def _fallback_daily_remember(explanation: str) -> str:
    """解析被「选X是最佳」开头挡住时，抽一句带动作的分句。"""
    t = re.sub(r"\s+", "", explanation or "")
    t = re.sub(r"^[A-E]选项是最佳选项[。.]?", "", t)
    t = re.sub(r"^选[A-E][,，]", "", t)
    t = re.sub(r"^(首先|在这个问题中)[,，]?", "", t)
    primary = ""
    secondary = ""
    for part in re.split(r"[。；]", t):
        for seg in re.split(r"[，,]", part):
            seg = seg.strip()
            if not (8 <= len(seg) <= MAX_REMEMBER_COL):
                continue
            if not _usable_daily_remember(seg):
                continue
            if any(h in seg for h in _ACTION_PRIMARY) and len(seg) >= len(primary):
                primary = seg
            elif any(h in seg for h in _ACTION_SECONDARY) and len(seg) >= len(secondary):
                secondary = seg
    return primary or secondary


def _daily_practice_dates() -> dict[int, str]:
    """error_log_id → 最近一次每日一练日期。错题本本身不记 source。"""
    try:
        bank = json.loads(QUESTION_BANK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(bank, list):
        return {}
    dates: dict[int, str] = {}
    for row in bank:
        if row.get("source") != "daily_practice" or row.get("is_correct") is not False:
            continue
        eid = row.get("error_log_id")
        if not isinstance(eid, int):
            continue
        day = str(row.get("date") or "")[:10]
        if day > dates.get(eid, ""):
            dates[eid] = day
    return dates


def collect_process_chain_daily_rows(
    errors: list[dict],
    dated_ids: dict[int, str],
) -> dict[str, list[tuple[str, str, str]]]:
    """{锚点: [(题干, 背这句, 别踩), ...]}，每节只留最近若干条每日一练。"""
    area_to_anchor = dict(PROCESS_CHAIN_SECTIONS)
    by_anchor: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    seen_remember: dict[str, set[str]] = defaultdict(set)
    by_id = {e.get("id"): e for e in errors if isinstance(e.get("id"), int)}
    ranked = sorted(
        dated_ids.items(),
        key=lambda item: str((by_id.get(item[0]) or {}).get("timestamp") or item[1]),
        reverse=True,
    )

    for eid, day in ranked:
        err = by_id.get(eid)
        if not err:
            continue
        anchor = area_to_anchor.get(_map_error_area(err) or "")
        if not anchor:
            continue
        remember, pitfall = build_memory_trap(err)
        if remember and not _usable_daily_remember(remember):
            remember = ""
        if not remember:
            remember = _fallback_daily_remember(str(err.get("explanation") or ""))
            my_a = str(err.get("my_answer") or "?").strip().upper()
            ok_a = str(err.get("correct_answer") or "?").strip().upper()
            pitfall = f"别选 {my_a}，应选 {ok_a}"
        if not remember or not _usable_daily_remember(remember):
            continue
        if not _quality_trap_row(remember, pitfall):
            continue
        if len(by_anchor[anchor]) >= PROCESS_CHAIN_DAILY_CAP:
            continue
        key = _row_key(remember, pitfall)
        if not key or key in seen_remember[anchor]:
            continue
        seen_remember[anchor].add(key)
        gist = _cell(_question_gist(err.get("question", ""), 18), 18)
        stamp = str(err.get("timestamp") or day)
        by_anchor[anchor].append(
            (gist, _cell(remember, MAX_REMEMBER_COL), _cell(pitfall, MAX_PITFALL_COL), stamp)
        )

    out: dict[str, list[tuple[str, str, str]]] = {}
    for anchor, rows in by_anchor.items():
        rows.sort(key=lambda r: r[3], reverse=True)
        out[anchor] = [(g, rem, pit) for g, rem, pit, _stamp in rows]
    return out


def _upsert_daily_append_block(
    section: str,
    rows: list[tuple[str, str, str]],
    today: str,
) -> str:
    """在手写口诀表之后插入/替换「每日一练追加」，不改上面的手写行。"""
    section = re.sub(
        r"\n*### 每日一练追加（自动[^\n]*\n(?:.*?)(?=\n### |\n## |\Z)",
        "\n",
        section,
        flags=re.DOTALL,
    )
    if not rows:
        return section
    lines = ["| 题干 | 背这句 | 别踩 |", "|------|--------|------|"]
    for gist, remember, pitfall in rows:
        lines.append(f"| {gist} | {remember} | {pitfall} |")
    block = (
        f"\n### 每日一练追加（自动 · 更新于 {today}）\n\n"
        "> 每日一练错题口诀，每节保留最近 "
        f"{PROCESS_CHAIN_DAILY_CAP} 条。上面的手写表不动。\n\n"
        + "\n".join(lines)
        + "\n"
    )
    marker = re.search(r"^### 决策链\s*$", section, re.M)
    if not marker:
        marker = re.search(r"^## 这几天怎么用\s*$", section, re.M)
    if marker:
        return section[: marker.start()].rstrip() + "\n" + block + "\n" + section[marker.start() :]
    return section.rstrip() + "\n" + block + "\n"


def apply_process_chain_daily(
    content: str,
    rows_by_anchor: dict[str, list[tuple[str, str, str]]],
    today: str,
) -> str:
    matches = list(_PROCESS_ANCHOR_RE.finditer(content))
    if not matches:
        return content
    pieces = [content[: matches[0].start()]]
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        anchor = match.group("id")
        section = content[match.start() : end]
        pieces.append(_upsert_daily_append_block(section, rows_by_anchor.get(anchor, []), today))
    return "".join(pieces)


def sync_process_chain_daily(
    errors: list[dict] | None = None,
    *,
    dry_run: bool = False,
) -> int:
    """把每日一练错题口诀追加进过程四条链对应章节。返回写入条数。"""
    if not PROCESS_CHAIN.is_file():
        return 0
    errors = _load_errors() if errors is None else errors
    rows = collect_process_chain_daily_rows(errors, _daily_practice_dates())
    content = PROCESS_CHAIN.read_text(encoding="utf-8")
    updated = apply_process_chain_daily(content, rows, date.today().isoformat())
    if updated == content:
        return 0
    if not dry_run:
        PROCESS_CHAIN.write_text(updated, encoding="utf-8")
    return sum(len(v) for v in rows.values())


def sync_traps_from_errors(*, dry_run: bool = False) -> SyncResult:
    """按错题本回写各领域：先搞懂钉死点 + 易错表合并 + 背这句区 + 决策补丁 + 闪卡加练。"""
    result = SyncResult()
    errors = _load_errors()
    state = _load_sync_state()
    synced_ids: set[int] = set(state.get("synced_error_ids") or [])
    today = date.today().isoformat()

    by_area = collect_memory_traps_by_area(errors)

    for area, fname in DOMAIN_FILES.items():
        path = CHEATSHEET_DIR / fname
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        rows_meta = by_area.get(area, [])
        rows = [(r, p) for r, p, _eid, _f in rows_meta]
        new_ids = [eid for _r, _p, eid, _f in rows_meta if eid not in synced_ids]

        if not dry_run:
            updated = _rewrite_auto_memory_section(content, rows, today)
            if updated != content:
                path.write_text(updated, encoding="utf-8")
                if rows:
                    result.traps_added[area] = len(rows)
                result.synced_ids.extend(new_ids)
                synced_ids.update(eid for _r, _p, eid, _f in rows_meta)
            elif new_ids:
                synced_ids.update(new_ids)
        else:
            if rows:
                result.traps_added[area] = len(rows)
            result.synced_ids.extend(new_ids)

    if not dry_run:
        for e in errors:
            eid = e.get("id")
            if isinstance(eid, int) and _map_error_area(e):
                synced_ids.add(eid)
        state["synced_error_ids"] = sorted(synced_ids)
        state["last_trap_sync"] = today
        state["bootstrapped"] = True
        state["memory_format"] = "背这句/别踩"
        _save_sync_state(state)

    result.process_chain_rows = sync_process_chain_daily(errors, dry_run=dry_run)
    return result


def _error_counts_by_area(errors: list[dict]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for e in errors:
        area = _map_error_area(e)
        if area:
            counts[area] += 1
    return dict(counts)


def _priority_tag(rate: float | None, err_count: int) -> str:
    if rate is not None and rate >= 0.6:
        return "🔴 P0"
    if err_count >= 25 or (rate is not None and rate >= 0.4):
        return "🟡 P1"
    return "🟢 P2"


def _priority_emoji(tag: str) -> str:
    return tag.split()[0] if tag else "🟢"


def extract_mnemonic(content: str) -> str:
    """从领域 MD 顶部引用块读取总口诀。兼容 `**总口诀**：**xxx**`。"""
    for raw in content.splitlines():
        line = raw.lstrip("> ").strip()
        m = re.search(r"总口诀\*+[：:]\s*\*+(.+?)\*+\s*$", line)
        if not m:
            m = re.search(r"总口诀[：:]\s*\**(.+?)\**\s*$", line)
        if m:
            text = m.group(1).strip().strip("*").strip()
            if text and text != "总口诀":
                return text
    return ""


def _sprint_cmd_area(area: str) -> str:
    return "敏捷" if area.startswith("敏捷") else area


def _sprint_short_area(area: str) -> str:
    return "敏捷" if area.startswith("敏捷") else area


SPRINT_WINDOW = 9  # 考前最后 9 个学习日（不含考试当天）


def _exam_day() -> date:
    try:
        from pmp_athena.config import get_target_exam_date
        return get_target_exam_date()
    except Exception:
        return date(2026, 12, 5)


EXAM_DAY = _exam_day()


def sprint_day_index(d_day: int, window: int = SPRINT_WINDOW) -> int:
    """考前日历下标：D=9→0（首个薄弱），D=8→1，D=1→8（考前一天）。"""
    return max(0, window - max(int(d_day), 1))


def sprint_slot(
    ranked: list[tuple[str, str, str]],
    d_day: int,
) -> dict:
    """按考试锚定日历取当日槽位。kind=area|finale。"""
    non_p2 = [(num, area) for tag, num, area in ranked if not tag.startswith("🟢")]
    p0 = [area for tag, _num, area in ranked if tag.startswith("🔴")]
    idx = sprint_day_index(d_day)
    if not non_p2 or d_day <= 1 or idx >= len(non_p2):
        focus = list(p0) if p0 else [a for _n, a in non_p2[:2]]
        return {"kind": "finale", "area": None, "num": None, "focus": focus}
    num, area = non_p2[idx]
    focus = [area]
    for p0_area in p0:
        if p0_area not in focus:
            focus.append(p0_area)
    return {"kind": "area", "area": area, "num": num, "focus": focus}


def _plan_slot_for_day(
    day: date,
    ranked: list[tuple[str, str, str]],
) -> dict:
    """优先补考周历；考前 9 天再回落到薄弱轮换。"""
    day_d = (EXAM_DAY - day).days
    if day_d > SPRINT_WINDOW:
        try:
            from pmp_athena.retake_calendar import enriched_slot
        except ModuleNotFoundError:
            from retake_calendar import enriched_slot  # type: ignore
        slot = enriched_slot(day)
        if slot:
            area = slot.get("area")
            num = None
            if area:
                for _tag, n, a in ranked:
                    if a == area or (area.startswith("敏捷") and a.startswith("敏捷")):
                        num = n
                        break
            return {
                "kind": slot.get("kind") or "area",
                "area": area,
                "num": num,
                "focus": slot.get("focus") or ([] if not area else [area]),
            }
    return sprint_slot(ranked, day_d)


def build_recitation_plan(
    ranked: list[tuple[str, str, str]],
    *,
    d_day: int,
    today: date,
) -> str:
    """按剩余天数 + 周历/薄弱优先级生成背诵计划。ranked: (tag, 文件编号, 领域)。

    D>9：跟 `2026-12-补考学习计划.md`；考前 9 天：薄弱轮换。
    """
    from datetime import timedelta

    last_study = EXAM_DAY - timedelta(days=1)
    if today > last_study:
        last_s = f"{last_study.month}/{last_study.day}"
        return (
            "## 学习计划已结束\n\n"
            f"背诵计划只排到考试前一天（{last_s}）。考试日及之后不再排任务。"
        )

    heading = "## 推荐 7 天背诵计划" if d_day > 11 else f"## 考前 {max(d_day, 1)} 天背诵计划"
    study_days = 7 if d_day > 11 else max(min(d_day, SPRINT_WINDOW), 1)
    study_days = min(study_days, (last_study - today).days + 1)

    lines = [
        heading,
        "",
        "| 天 | 日期 | 上午（背口诀+陷阱） | 下午（专项刷题） |",
        "|----|------|---------------------|------------------|",
    ]
    for i in range(study_days):
        day = today + timedelta(days=i)
        date_s = f"{day.month}/{day.day}"
        slot = _plan_slot_for_day(day, ranked)
        if slot["kind"] in ("finale", "exam", "mock") or not slot.get("area"):
            if slot["kind"] == "mock":
                morning = "模考日：轻量口诀"
                afternoon = "全真模考"
            else:
                morning = "[00-考前攻错决策卡](./00-考前攻错决策卡.md) + [三领域对比](./00-三领域对比速记卡.md)"
                afternoon = "`复习错题` / 弱项专项"
        else:
            num = slot.get("num") or ""
            morning = f"{num} {_sprint_short_area(slot['area'])}".strip()
            afternoon = f"`专项 {_sprint_cmd_area(slot['area'])}`"
        lines.append(f"| D{i + 1} | {date_s} | {morning} | {afternoon} |")
    return "\n".join(lines)


def today_focus_areas(
    ranked: list[tuple[str, str, str]],
    d_day: int,
) -> list[str]:
    """按考前剩余天数取今日领域，并始终带上 P0。ranked: (tag, num, area)。"""
    return sprint_slot(ranked, d_day).get("focus") or []


def _d_day(today: date | None = None) -> int:
    today = today or date.today()
    return (_exam_day() - today).days


def _ranked_area_triples() -> list[tuple[str, str, str]]:
    """[(tag, 文件编号, 领域), ...] 按 P0/P1/P2 + 错误率。"""
    weak = get_weak_areas()
    weak_map = {a: (rate, wrong, total) for a, rate, wrong, total in weak}
    err_counts = _error_counts_by_area(_load_errors())
    rows: list[tuple[str, str, str, float | None]] = []
    for area in DOMAIN_ORDER:
        fname = DOMAIN_FILES[area]
        num = fname.split("-")[0]
        info = weak_map.get(area)
        rate_val = info[0] if info else None
        tag = _priority_tag(rate_val, err_counts.get(area, 0))
        rows.append((tag, num, area, rate_val))
    rows.sort(key=lambda r: (
        0 if r[0] == "🔴 P0" else (1 if r[0] == "🟡 P1" else 2),
        -(r[3] if r[3] is not None else -1.0),
    ))
    return [(tag, num, area) for tag, num, area, _ in rows]


def _insert_daily_hf_section(content: str, section: str) -> str:
    """把今日顽疾号插入 README（考前加练段之后）。"""
    new_content, n = re.subn(
        r"## 今日(?:推荐摘要卡（10分钟）|顽疾号（不要读长摘要卡）)\n.*?"
        r"(?=\n---\n\n## (?:每份文档结构|三、每份文档怎么读))",
        section.strip() + "\n",
        content,
        count=1,
        flags=re.DOTALL,
    )
    if n:
        return new_content
    for marker in (
        "\n---\n\n## 三、每份文档怎么读",
        "\n---\n\n## 每份文档结构",
    ):
        if marker in content:
            insert = (
                "\n\n**每日睡前**：过下方「今日顽疾号」→ 发「复习错题」"
                f"\n\n---\n\n{section.strip()}\n{marker}"
            )
            return content.replace(marker, insert, 1)
    return content.rstrip() + "\n\n" + section.strip() + "\n"


def _volume_why(rank: int, area: str, err_n: int, rate_val: float | None) -> str:
    # 本周若在补考周历里，优先提示「本周专项」
    try:
        from pmp_athena.retake_calendar import day_plan
    except ModuleNotFoundError:
        from retake_calendar import day_plan  # type: ignore
    today_plan = day_plan(date.today())
    if today_plan and area in (today_plan.areas or []):
        return "本周周历专项，优先背+刷"
    if rank == 1:
        return "存量最大，People 卷面占比高"
    if area.startswith("敏捷"):
        return "题量大且持续弱点"
    if area == "成本管理":
        return "错误率高但近期题少，读「先搞懂」即可"
    if area == "商业环境":
        return "本轮补考重点域，跟周历刷"
    if err_n >= 50:
        return "存量大，反复出现"
    if rate_val is not None and rate_val >= 0.55 and err_n < 40:
        return "错误率高但题量不大"
    return f"错题本 {err_n} 道"


def _build_volume_table(
    rows: list[tuple[str, str, str, str, str, str, float | None]],
) -> str:
    """按错题本存量排序的分领域表。"""
    rows_vol = sorted(rows, key=lambda r: -int(r[4] or 0))
    lines = [
        "| 顺序 | 打开 | 错题本 | 错误率 | 为什么现在攻它 |",
        "|:----:|------|:------:|:------:|----------------|",
    ]
    for i, (_tag, _num, area, rate_str, err_n, _mnemonic, rate_val) in enumerate(rows_vol, 1):
        fname = DOMAIN_FILES[area]
        stem = fname.replace(".md", "")
        short = "敏捷/混合方法" if area.startswith("敏捷") else area
        link = f"[{stem}](./{fname})" if not area.startswith("敏捷") else f"[{short}](./{fname})"
        why = _volume_why(i, area, int(err_n or 0), rate_val)
        lines.append(f"| {i} | {link} | **{err_n}** | {rate_str} | {why} |")
    return "\n".join(lines)


def refresh_readme(*, dry_run: bool = False, hf_cards_count: int | None = None) -> bool:
    if not README_PATH.is_file():
        return False

    weak = get_weak_areas()
    weak_map = {a: (rate, wrong, total) for a, rate, wrong, total in weak}
    err_counts = _error_counts_by_area(_load_errors())
    today = date.today()

    d_day = _d_day(today)

    phase = "🔥 冲刺模考期" if d_day <= 11 else ("⚡ 强化刷题期" if d_day <= 30 else "📖 基础巩固期")

    rows: list[tuple[str, str, str, str, str, str, float | None]] = []
    for area in DOMAIN_ORDER:
        fname = DOMAIN_FILES[area]
        num = fname.split("-")[0]
        info = weak_map.get(area)
        err_n = err_counts.get(area, 0)
        rate_str = "—"
        rate_val: float | None = None
        if info:
            rate_val, wrong, total = info
            rate_str = f"**{rate_val:.0%}**"

        tag = _priority_tag(rate_val, err_n)
        md_path = CHEATSHEET_DIR / fname
        mnemonic = extract_mnemonic(md_path.read_text(encoding="utf-8")) if md_path.is_file() else ""
        rows.append((tag, num, area, rate_str, str(err_n), mnemonic, rate_val))

    rows.sort(key=lambda r: (
        0 if r[0] == "🔴 P0" else (1 if r[0] == "🟡 P1" else 2),
        -(r[6] if r[6] is not None else -1.0),
    ))
    rows_vol = sorted(rows, key=lambda r: -int(r[4] or 0))
    catalog_first = False

    content = README_PATH.read_text(encoding="utf-8")
    catalog_first = "## 一、摘要卡清单" in content
    ranked_for_focus = (
        [(r[0], r[1], r[2]) for r in rows_vol]
        if catalog_first
        else [(r[0], r[1], r[2]) for r in rows]
    )

    header = (
        f"> 生成日期：{today.isoformat()} · 距考试 {max(d_day, 0)} 天 · 阶段：{phase}  \n"
        f"> 用法：先看下方清单有哪些卡 → 再按做题数据决定今天攻哪张 → 读「先搞懂」再做题"
    )
    content = re.sub(
        r"> 生成日期：.*?(?:→ 做专项 10 题|→ 读「先搞懂」再做题)",
        header,
        content,
        count=1,
        flags=re.DOTALL,
    )

    vol_table = _build_volume_table(rows)
    content, n_vol = re.subn(
        r"(### 分领域顺序\n\n)(\| 顺序.*?)(\n\n## )",
        lambda m: m.group(1) + vol_table + m.group(3),
        content,
        count=1,
        flags=re.DOTALL,
    )
    if not n_vol:
        table_lines = [
            "| 优先级 | 文件 | 错误率 | 错题本 | 总口诀 |",
            "|:------:|------|:------:|:------:|--------|",
        ]
        for tag, num, area, rate_str, err_n, mnemonic, _rate in rows:
            stem = DOMAIN_FILES[area].replace(".md", "")
            link = f"[{stem}](./{DOMAIN_FILES[area]})"
            table_lines.append(
                f"| {tag} | {link} | {rate_str} | **{err_n}** | {mnemonic or '—'} |"
            )
        new_table = "\n".join(table_lines)
        content = re.sub(
            r"(## 你的薄弱优先级（按紧急度排序）\n\n)(.*?)(\n\n---\n\n## (?:推荐 7 天|考前 \d+ 天))",
            lambda m: m.group(1) + new_table + m.group(3),
            content,
            count=1,
            flags=re.DOTALL,
        )

    plan = build_recitation_plan(
        [(r[0], r[1], r[2]) for r in rows_vol] if catalog_first else [(r[0], r[1], r[2]) for r in rows],
        d_day=d_day,
        today=today,
    )
    content = re.sub(
        r"## (?:推荐 7 天|考前 \d+ 天|学习计划已结束)背诵计划\n\n.*?(?=\n\n\*\*考前加练\*\*)",
        plan,
        content,
        count=1,
        flags=re.DOTALL,
    )
    # 兼容旧「考前 5 天背诵计划」硬编码（9/7–9/11）
    content = re.sub(
        r"## 考前 5 天背诵计划\n\n.*?(?=\n\n\*\*考前加练\*\*)",
        plan,
        content,
        count=1,
        flags=re.DOTALL,
    )

    content = re.sub(
        r"\*\*(?:P0 完整合订|Process 合订)\*\*：.*",
        "**Process 合订**：[00-P0三领域完整知识点](./00-P0三领域完整知识点.md)"
        "（成本/进度公式 + 商业环境速查；主战场仍按存量：资源→敏捷→干系人→整合）",
        content,
        count=1,
    )

    # 总览卡入口：攻错/对比优先；高频长摘要降级
    content = re.sub(
        r"\| \[00-高频错题摘要卡\]\(\./00-高频错题摘要卡\.md\) \|[^\n]+\|",
        "| [00-高频错题摘要卡](./00-高频错题摘要卡.md) | **已降级** · 不当教材；顽疾发「复习错题」 |",
        content,
        count=1,
    )
    content = re.sub(
        r"\*\*先过总览卡，不要直接扎进 01–09：\*\*\n\n.*?(?=\n\n### 分领域顺序)",
        "**先过总览卡，不要直接扎进 01–09：**\n\n"
        "1. [00-考前攻错决策卡](./00-考前攻错决策卡.md) — 你近四成错是跳步骤，跟领域关系不大  \n"
        "2. [00-三领域对比速记卡](./00-三领域对比速记卡.md) — 做题前 30 秒判断「卡在哪件事」  \n"
        "3. [00-P0三领域完整知识点](./00-P0三领域完整知识点.md) — 成本/进度公式 + 商业环境速查（不当主刷）",
        content,
        count=1,
        flags=re.DOTALL,
    )
    content = re.sub(
        r"\*\*每日睡前\*\*：.*",
        "**每日睡前**：过下方「今日顽疾号」→ 发「复习错题」做完整题（不要读长摘要卡）",
        content,
        count=1,
    )

    lecture_table = format_lecture_readme_table()
    content, n_lec_readme = re.subn(
        r"## 讲义对照（薄弱点用）\n.*?(?=\n---\n\n## )",
        lecture_table,
        content,
        count=1,
        flags=re.DOTALL,
    )
    if not n_lec_readme:
        # 插在「一、摘要卡清单」整段之后
        marker = "\n---\n\n## 二、根据做题数据"
        if marker in content:
            content = content.replace(
                marker,
                "\n\n" + lecture_table + "---\n\n## 二、根据做题数据",
                1,
            )
        else:
            content = content.rstrip() + "\n\n" + lecture_table

    if hf_cards_count is not None:
        content = _update_readme_hf_line(content, hf_cards_count)

    try:
        from pmp_athena.export_hf_cards import (
            format_daily_hf_table,
            pick_daily_hf_cards,
        )
        from pmp_athena.error_insights import rank_high_frequency_errors
    except ModuleNotFoundError:
        from export_hf_cards import format_daily_hf_table, pick_daily_hf_cards
        from error_insights import rank_high_frequency_errors

    # 今日摘要卡领域：优先补考周历，再回落薄弱
    try:
        from pmp_athena.retake_calendar import day_plan as _retake_day
    except ModuleNotFoundError:
        from retake_calendar import day_plan as _retake_day  # type: ignore
    retake = _retake_day(today)
    if retake and retake.areas:
        focus = list(retake.areas)
    elif catalog_first:
        focus = [r[2] for r in rows_vol[:2]]
    else:
        focus = today_focus_areas(ranked_for_focus, d_day)
    hf_items = rank_high_frequency_errors(top_n=50, min_mistakes=3)
    err_map = {e["id"]: e for e in _load_errors() if e.get("id")}
    section = format_daily_hf_table(
        pick_daily_hf_cards(hf_items, focus),
        err_map,
        focus_areas=focus,
        today=today,
        link_cards_file=True,
    )
    content = _insert_daily_hf_section(content, section)

    if not dry_run:
        README_PATH.write_text(content, encoding="utf-8")
    return True


def refresh_domain_headers(*, dry_run: bool = False) -> int:
    """更新各 MD 顶部 blockquote 中的错误率/错题本数量。"""
    weak = get_weak_areas()
    weak_map = {a: (rate, wrong, total) for a, rate, wrong, total in weak}
    err_counts = _error_counts_by_area(_load_errors())
    updated = 0

    for area, fname in DOMAIN_FILES.items():
        path = CHEATSHEET_DIR / fname
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        info = weak_map.get(area)
        err_n = err_counts.get(area, 0)
        rate_val: float | None = None
        if info:
            rate_val, wrong, total = info
            bank_line = f"错误率 **{rate_val:.0%}**（{wrong}/{total}）"
        else:
            bank_line = "错误率 —"
        new_data = f"> **你的数据**：{bank_line} · 错题本 {err_n} 题"
        emoji = _priority_emoji(_priority_tag(rate_val, err_n))

        new_content, n = re.subn(
            r"> \*\*你的数据\*\*：[^\n]+",
            new_data,
            content,
            count=1,
        )
        new_content, n_title = re.subn(
            r"^# [🔴🟡🟢] ",
            f"# {emoji} ",
            new_content,
            count=1,
            flags=re.MULTILINE,
        )
        lecture = format_lecture_line(area)
        if lecture:
            # 清掉全部旧「讲义对照」行（含历史重复），再只留一行
            stripped, n_rm = re.subn(
                r"(?:\n)?^> \*\*讲义对照\*\*[^\n]*",
                "",
                new_content,
                flags=re.MULTILINE,
            )
            new_content = stripped
            new_content, n_lec = re.subn(
                r"(> \*\*总口诀\*\*：[^\n]+)",
                rf"\1\n{lecture}",
                new_content,
                count=1,
            )
            if not n_lec:
                new_content, n_lec = re.subn(
                    r"(> \*\*你的数据\*\*：[^\n]+)",
                    rf"\1\n{lecture}",
                    new_content,
                    count=1,
                )
            if n_rm and not n_lec:
                n_lec = n_rm  # 至少记一次变更
        else:
            n_lec = 0
        if (n or n_title or n_lec) and new_content != content:
            if not dry_run:
                path.write_text(new_content, encoding="utf-8")
            updated += 1

    return updated


def sync_hf_cards(
    *,
    dry_run: bool = False,
    top_n: int = 50,
    min_mistakes: int = 3,
    focus_areas: list[str] | None = None,
) -> tuple[int, bool]:
    """从 error_log 重生成 00-高频错题摘要卡.md。返回 (题数, 是否写入)。"""
    try:
        from pmp_athena.error_insights import rank_high_frequency_errors
        from pmp_athena.export_hf_cards import export_cards
    except ModuleNotFoundError:
        from error_insights import rank_high_frequency_errors
        from export_hf_cards import export_cards

    if focus_areas is None:
        focus_areas = today_focus_areas(_ranked_area_triples(), _d_day())

    count = len(rank_high_frequency_errors(top_n=top_n, min_mistakes=min_mistakes))
    if dry_run:
        return count, False

    export_cards(top_n=top_n, min_mistakes=min_mistakes, focus_areas=focus_areas)
    return count, True


def _update_readme_hf_line(content: str, count: int) -> str:
    pattern = r"\*\*考前加练\*\*：.*"
    repl = (
        f"**考前加练**：发「复习错题」过完整题"
        f"（错 ≥3 次约 **{count}** 道；长摘要卡已降级，不当教材）"
    )
    new_content, n = re.subn(pattern, repl, content, count=1)
    if n:
        return new_content
    marker = "## 推荐 7 天背诵计划"
    if marker in content and "**考前加练**" not in content:
        return content.replace(marker, f"\n{repl}\n\n{marker}", 1)
    return content


def _process_order_pct() -> int | None:
    errors = _load_errors()
    typed = [e for e in errors if str(e.get("error_type") or "").strip()]
    if not typed:
        return None
    n = sum(1 for e in typed if e.get("error_type") == "流程顺序错")
    return round(100 * n / len(typed))


def _next_hard_node(today: date | None = None) -> str:
    today = today or date.today()
    try:
        from pmp_athena.retake_calendar import day_plan
    except ModuleNotFoundError:
        from retake_calendar import day_plan  # type: ignore
    from datetime import timedelta

    for i in range(0, 21):
        d = today + timedelta(days=i)
        plan = day_plan(d)
        if not plan:
            continue
        if plan.kind == "mock":
            return f"{d.month}/{d.day} 模考"
        if plan.kind == "exam":
            return f"{d.month}/{d.day} 考试"
    return "12/5 考试"


def refresh_overview_cards(*, dry_run: bool = False) -> int:
    """同步三份总览卡的日期头 + 实时错题数据（与 01–09 同频）。"""
    today = date.today()
    d_day = _d_day(today)
    phase = "🔥 冲刺模考期" if d_day <= 11 else ("⚡ 强化刷题期" if d_day <= 30 else "📖 基础巩固期")
    next_node = _next_hard_node(today)
    weak = get_weak_areas()
    weak_map = {a: (rate, wrong, total) for a, rate, wrong, total in weak}
    err_counts = _error_counts_by_area(_load_errors())
    updated = 0

    def _rate_wrong(area: str) -> tuple[str, int]:
        info = weak_map.get(area)
        err_n = err_counts.get(area, 0)
        if info:
            return f"{info[0]:.0%}", err_n
        return "—", err_n

    # —— 考前攻错决策卡 ——
    if OVERVIEW_DECISION.is_file():
        content = OVERVIEW_DECISION.read_text(encoding="utf-8")
        pct = _process_order_pct()
        pct_s = f"**{pct}%**" if pct is not None else "约四成"
        header = (
            f"> 生成日期：{today.isoformat()} · 距 **2026-12-05** 补考约 {max(d_day, 0)} 天"
            f" · 阶段：{phase} · 下一关：**{next_node}**  \n"
            f"> 不是背句子。每道题先在脑子里走完「发生了什么 → 现在该哪一步」，再看选项。  \n"
            f"> 你约 {pct_s} 的错是**流程顺序错**：把后面正确的事，当成了现在该做的事。  \n"
            f"> **讲义对照**：先看本文流水线 → 再翻 [三十六种套路速查](../摘要/三十六种套路_速查.md)；"
            f"分域讲义见 [README 讲义对照](./README.md#讲义对照薄弱点用)。"
        )
        new_content, n = re.subn(
            r"^> 生成日期：.*?(?=\n\n---)",
            header,
            content,
            count=1,
            flags=re.DOTALL | re.MULTILINE,
        )
        if n and new_content != content:
            if not dry_run:
                OVERVIEW_DECISION.write_text(new_content, encoding="utf-8")
            updated += 1

    # —— 三领域对比速记卡 ——
    if OVERVIEW_COMPARE.is_file():
        content = OVERVIEW_COMPARE.read_text(encoding="utf-8")
        n_res = err_counts.get("资源管理", 0)
        n_agile = err_counts.get("敏捷", 0) + err_counts.get("敏捷/混合方法", 0)
        n_stk = err_counts.get("干系人管理", 0)
        n_int = err_counts.get("整合管理", 0)
        agile_info = weak_map.get("敏捷") or weak_map.get("敏捷/混合方法")
        agile_rate = f"{agile_info[0]:.0%}" if agile_info else "—"
        header = (
            f"> 生成日期：{today.isoformat()} · 距 **2026-12-05** 约 {max(d_day, 0)} 天"
            f" · 阶段：{phase} · 用途：做题前 30 秒分域  \n"
            f"> 按错题本存量，这四块仍是主战场：资源 **{n_res}** · 敏捷 **≈{n_agile}**"
            f" · 干系人 **{n_stk}** · 整合 **{n_int}**  \n"
            f"> 口诀只是最后提醒。先判「卡在哪件事」，再选动作。  \n"
            f"> **讲义对照**：四域见 [README 讲义对照表](./README.md#讲义对照薄弱点用)"
            f"（资源 PMP12-13 · 整合 PMP5-6 · 敏捷 PMP4 · 干系人 PMP11）。"
        )
        new_content, n = re.subn(
            r"^> 生成日期：.*?(?=\n\n资源 /)",
            header + "\n",
            content,
            count=1,
            flags=re.DOTALL | re.MULTILINE,
        )
        # 正文里敏捷错误率一句
        new_content2, n2 = re.subn(
            r"你敏捷错误率仍约 \*\*[^*]+\*\*",
            f"你敏捷错误率仍约 **{agile_rate}**",
            new_content,
            count=1,
        )
        if (n or n2) and new_content2 != content:
            if not dry_run:
                OVERVIEW_COMPARE.write_text(new_content2, encoding="utf-8")
            updated += 1

    # —— Process 合订（成本/进度/商业环境）——
    if OVERVIEW_PROCESS.is_file():
        content = OVERVIEW_PROCESS.read_text(encoding="utf-8")
        cost_r, cost_n = _rate_wrong("成本管理")
        sch_r, sch_n = _rate_wrong("进度管理")
        biz_r, biz_n = _rate_wrong("商业环境")
        header = (
            f"> 生成日期：{today.isoformat()} · 距 **2026-12-05** 约 {max(d_day, 0)} 天"
            f" · 阶段：{phase} · 下一关：**{next_node}**  \n"
            f"> **定位**：这是「公式 + 概念」合订，不是今天主刷顺序。  \n"
            f"> 主战场按**错题本存量**仍是：资源 → 敏捷 → 干系人 → 整合，见 "
            f"[README](./README.md) / [攻错决策卡](./00-考前攻错决策卡.md)。  \n"
            f"> 成本/进度：**错误率仍高**（约 {cost_r} / {sch_r}），题量不大，适合模考前扫公式。  \n"
            f"> 商业环境：新版权重抬高；错题本约 {biz_n}，模考一要求域正确率 ≥**60%**。  \n"
            f"> 用法：模考前扫决策链 + 闪卡；不要拿本册替代「今日任务」周历。  \n"
            f"> **讲义对照**：成本 [PMP10 摘要](../摘要/PMP10_财务管理.md)/"
            f"[PDF](../讲义/PMP10.财务管理-骐迹教育.pdf) · "
            f"进度 [PMP8-9 摘要](../摘要/PMP8-9_进度管理.md)/"
            f"[PDF](../讲义/PMP8-9.进度管理-骐迹教育.pdf) · "
            f"商业 [PMP2 摘要](../摘要/PMP2_价值交付体系.md)/"
            f"[PDF](../讲义/PMP2.价值交付体系-骐迹教育.pdf) · "
            f"完整表 [README](./README.md#讲义对照薄弱点用)。"
        )
        new_content, n = re.subn(
            r"^> 生成日期：.*?(?=\n\n\| 领域 \|)",
            header + "\n",
            content,
            count=1,
            flags=re.DOTALL | re.MULTILINE,
        )
        table = (
            "| 领域 | 错误率（约） | 错题本（约） | 总口诀 | 本轮怎么用 |\n"
            "|------|:------------:|:------------:|--------|------------|\n"
            f"| 🟡 成本管理 | **{cost_r}** | {cost_n} | 挣值先算 EV，储备分应急和管理 | 公式必背；错 ≥3 次再专项 |\n"
            f"| 🟡 进度管理 | **{sch_r}** | {sch_n} | 关键路径零浮动，赶工加钱并行险 | 压缩手段必分清；模考前闪卡 |\n"
            f"| 🟢 商业环境 | **{biz_r}** | {biz_n} | 先论证价值，再谈怎么干 | 跟周历刷；论证/合规/选项目 |"
        )
        new_content2, n2 = re.subn(
            r"\| 领域 \| 错误率（约） \| 错题本（约） \| 总口诀 \| 本轮怎么用 \|\n"
            r".*?\n\| 🟢 商业环境 \|[^\n]+\|",
            table,
            new_content,
            count=1,
            flags=re.DOTALL,
        )
        if (n or n2) and new_content2 != content:
            if not dry_run:
                OVERVIEW_PROCESS.write_text(new_content2, encoding="utf-8")
            updated += 1

    return updated


def _touch_daily_refresh() -> None:
    state = _load_sync_state()
    state["last_daily_refresh"] = date.today().isoformat()
    _save_sync_state(state)


def sync_all(*, dry_run: bool = False, export_pdf: bool = True) -> SyncResult:
    trap_result = sync_traps_from_errors(dry_run=dry_run)
    hf_count, hf_written = sync_hf_cards(dry_run=dry_run)
    trap_result.hf_cards_count = hf_count
    trap_result.hf_cards_updated = hf_written
    trap_result.readme_updated = refresh_readme(dry_run=dry_run, hf_cards_count=hf_count)
    trap_result.headers_updated = refresh_domain_headers(dry_run=dry_run)
    trap_result.overview_updated = refresh_overview_cards(dry_run=dry_run)
    if not dry_run and export_pdf:
        try:
            try:
                from pmp_athena.cheatsheet_pdf import render_all
            except ModuleNotFoundError:
                from cheatsheet_pdf import render_all  # type: ignore
            paths = render_all()
            trap_result.pdf_count = len(paths)
        except Exception as e:
            # PDF 失败不阻断速记同步
            trap_result.pdf_error = str(e)
    if not dry_run:
        _touch_daily_refresh()
    return trap_result


def ensure_daily_sync(*, silent: bool = True) -> SyncResult | None:
    """每天首次触达时刷新速记（README 优先级 + 高频摘要卡 + 增量陷阱）。"""
    state = _load_sync_state()
    if state.get("last_daily_refresh") == date.today().isoformat():
        return None
    try:
        return sync_all()
    except Exception:
        if silent:
            return None
        raise


def _run_auto_sync(*, silent: bool = True) -> SyncResult | None:
    """执行增量同步；失败时不阻断错题入库主流程。"""
    try:
        return sync_all()
    except Exception:
        if silent:
            return None
        raise


def schedule_cheatsheet_sync() -> None:
    """标记有待同步的新错题（批量判卷时 defer 使用）。"""
    global _deferred_cheatsheet_sync
    _deferred_cheatsheet_sync = True


def flush_cheatsheet_sync(*, silent: bool = True) -> SyncResult | None:
    """批量录入结束后一次性同步速记卡。"""
    global _deferred_cheatsheet_sync
    if not _deferred_cheatsheet_sync:
        return None
    _deferred_cheatsheet_sync = False
    return _run_auto_sync(silent=silent)


def auto_sync_on_new_error(*, error_is_new: bool, defer: bool = False) -> SyncResult | None:
    """
    新错题入库后触发速记同步。

    - defer=False：立即 sync（微信单题、截图录入）
    - defer=True：仅标记，由 flush_cheatsheet_sync() 在批次结束时执行
    """
    if not error_is_new:
        return None
    if defer:
        schedule_cheatsheet_sync()
        return None
    return _run_auto_sync(silent=True)


def run_sync_after_weakness(*, dry_run: bool = False) -> str:
    """薄弱点诊断后调用：同步陷阱 + 刷新 README。"""
    result = sync_all(dry_run=dry_run)
    return "\n".join(result.summary_lines())


def format_sync_brief(result: SyncResult | None) -> str:
    """判卷/做题后一行摘要，无变更时返回空串。"""
    if result is None:
        return ""
    if not (
        result.total_traps
        or result.hf_cards_updated
        or result.readme_updated
        or result.overview_updated
        or result.process_chain_rows
    ):
        return ""
    return "📌 速记已同步：" + " · ".join(
        line.lstrip("- ") for line in result.summary_lines()
    )


def format_wechat_sync_report(result: SyncResult) -> str:
    lines = ["📌 **速记卡已同步**", ""]
    lines.extend(result.summary_lines())
    lines.extend([
        "",
        "💬 发「今日速记」背诵 · 「薄弱点速记」看优先级 · 「复习错题」过顽疾原题",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="薄弱点速记同步")
    sub = parser.add_subparsers(dest="command")

    for name, help_text in (
        ("sync", "增量同步错题到易错陷阱"),
        ("refresh-readme", "刷新 README 优先级表"),
        ("refresh-headers", "刷新各领域 MD 数据头"),
        ("refresh-overview", "同步三份总览卡数据头"),
        ("refresh-hf-cards", "刷新高频卡降级占位页"),
        ("all", "全部同步"),
        ("run", "同 all"),
    ):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--dry-run", action="store_true")
        sp.add_argument("--json", action="store_true")

    args = parser.parse_args()
    cmd = args.command or "all"
    dry = getattr(args, "dry_run", False)

    if cmd == "sync":
        result = sync_traps_from_errors(dry_run=dry)
    elif cmd == "refresh-readme":
        result = SyncResult(readme_updated=refresh_readme(dry_run=dry))
    elif cmd == "refresh-headers":
        result = SyncResult(headers_updated=refresh_domain_headers(dry_run=dry))
    elif cmd == "refresh-overview":
        result = SyncResult(overview_updated=refresh_overview_cards(dry_run=dry))
    elif cmd == "refresh-hf-cards":
        count, written = sync_hf_cards(dry_run=dry)
        result = SyncResult(hf_cards_count=count, hf_cards_updated=written)
        if written and not dry:
            refresh_readme(hf_cards_count=count)
            result.readme_updated = True
    else:
        result = sync_all(dry_run=dry)

    if getattr(args, "json", False):
        print(json.dumps({
            "traps_added": result.traps_added,
            "readme_updated": result.readme_updated,
            "headers_updated": result.headers_updated,
            "overview_updated": result.overview_updated,
            "hf_cards_count": result.hf_cards_count,
            "hf_cards_updated": result.hf_cards_updated,
            "total_traps": result.total_traps,
            "summary": result.summary_lines(),
        }, ensure_ascii=False, indent=2))
    else:
        for line in result.summary_lines():
            print(line)


if __name__ == "__main__":
    main()
