#!/usr/bin/env python3
"""
薄弱点速记同步 — 从 error_log 追加易错陷阱、刷新 README 优先级表、重生成高频错题摘要卡。

CLI:
  python pmp_athena/cheatsheet_sync.py sync          # 增量同步错题 → MD
  python pmp_athena/cheatsheet_sync.py refresh-readme
  python pmp_athena/cheatsheet_sync.py refresh-hf-cards
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
    from pmp_athena.config import CHEATSHEET_DIR, ERROR_LOG_PATH
    from pmp_athena.knowledge_retriever import normalize_area
    from pmp_athena.weak_area_cheatsheet import (
        DOMAIN_FILES,
        DOMAIN_ORDER,
        _resolve_cheatsheet_area,
        get_weak_areas,
    )
except ModuleNotFoundError:
    from config import CHEATSHEET_DIR, ERROR_LOG_PATH
    from knowledge_retriever import normalize_area
    from weak_area_cheatsheet import (
        DOMAIN_FILES,
        DOMAIN_ORDER,
        _resolve_cheatsheet_area,
        get_weak_areas,
    )

SYNC_STATE_PATH = CHEATSHEET_DIR / ".sync_state.json"
README_PATH = CHEATSHEET_DIR / "README.md"
AUTO_TRAP_HEADING = "### 来自你的错题（自动"
# 兼容旧标题，同步时整段替换
AUTO_TRAP_HEADING_ALIASES = (
    AUTO_TRAP_HEADING,
    "### 来自错题本（自动",
)
TRAP_SECTION_HEADERS = ("七、易错陷阱", "八、易错陷阱", "十、易错陷阱")
MAX_REMEMBER_COL = 32
MAX_PITFALL_COL = 40
MIN_FREQ_FOR_BOOST = 2
MAX_NEW_TRAPS_PER_DOMAIN = 10
BOOTSTRAP_FREQ_ONLY = True  # 首次同步只写入错≥2次的模式

_deferred_cheatsheet_sync = False


@dataclass
class SyncResult:
    traps_added: dict[str, int] = field(default_factory=dict)
    readme_updated: bool = False
    headers_updated: int = 0
    synced_ids: list[int] = field(default_factory=list)
    skipped_duplicate: int = 0
    hf_cards_count: int = 0
    hf_cards_updated: bool = False

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
                f"- 高频错题摘要卡已刷新（**{self.hf_cards_count}** 道，"
                "`00-高频错题摘要卡.md`）"
            )
        elif self.hf_cards_count:
            lines.append(f"- 高频错题摘要卡待刷新（当前 **{self.hf_cards_count}** 道）")
        if self.readme_updated:
            lines.append("- README 优先级表已刷新")
        if self.headers_updated:
            lines.append(f"- 已更新 {self.headers_updated} 份领域速记的数据头")
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
    return t[: limit - 1] + "…"


def _strip_mnemonic_noise(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.sub(r"^钉死[：:]\s*", "", t)
    t = t.strip("*，,。；; ")
    return t


def build_memory_trap(error: dict, *, freq: int = 1) -> tuple[str, str]:
    """可背诵行：(背这句, 别踩)。禁止塞题干/OCR 解析。"""
    try:
        from pmp_athena.error_insights import build_mnemonic, build_summary
        from pmp_athena.root_cause_engine import diagnose
        from pmp_athena.root_cause_variants import get_root_cause_summary
    except ImportError:
        from error_insights import build_mnemonic, build_summary
        from root_cause_engine import diagnose
        from root_cause_variants import get_root_cause_summary

    remember = ""
    diag = diagnose(error)
    if diag:
        summary = get_root_cause_summary(diag.get("name", ""))
        if summary and summary.get("core_distinction"):
            remember = summary["core_distinction"]
        else:
            remember = diag.get("mnemonic") or ""

    if not remember:
        remember = build_mnemonic(error)
    if not remember or remember.startswith("记牢正确选项"):
        remember = build_summary(error)

    remember = _strip_mnemonic_noise(remember)
    my_a = str(error.get("my_answer") or "?").strip().upper()
    ok_a = str(error.get("correct_answer") or "?").strip().upper()

    pitfall = ""
    if diag:
        summary = get_root_cause_summary(diag.get("name", ""))
        traps = (summary or {}).get("common_traps") or []
        if traps:
            pitfall = traps[0]
    if not pitfall:
        summary = build_summary(error)
        if summary and "易混淆选项" not in summary and summary != remember:
            pitfall = summary
    if not pitfall:
        pitfall = f"别选 {my_a}，应选 {ok_a}"
    elif not pitfall.startswith("别"):
        pitfall = f"别选 {my_a} · {pitfall}"

    left = _truncate(remember, MAX_REMEMBER_COL)
    right = _truncate(pitfall, MAX_PITFALL_COL)
    if freq >= MIN_FREQ_FOR_BOOST:
        right = _truncate(f"{right}（×{freq}）", MAX_PITFALL_COL)
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


def _rewrite_auto_memory_section(
    content: str,
    rows: list[tuple[str, str]],
    today: str,
) -> str:
    """整段重写自动区为可背口诀表。rows 为空则只清理旧垃圾。"""
    span = _find_trap_section_span(content)
    if not span:
        return content

    start, end = span
    section = _strip_auto_trap_block(content[start:end])
    if rows:
        table_rows = "".join(f"| {w} | {r} |\n" for w, r in rows)
        block = (
            f"\n{AUTO_TRAP_HEADING} · 更新于 {today}\n\n"
            "> 只背左列；右列是你常踩的坑。错题一更新这里就刷新。\n\n"
            "| 背这句 | 别踩 |\n"
            "|--------|------|\n"
            f"{table_rows}"
        )
        section = section.rstrip() + block + "\n"
    return content[:start] + section + content[end:]


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


def collect_memory_traps_by_area(
    errors: list[dict],
) -> dict[str, list[tuple[str, str, int, int]]]:
    """返回 {领域: [(背这句, 别踩, error_id, freq), ...]}，按频次去重。"""
    by_area: dict[str, list[tuple[str, str, int, int, str]]] = defaultdict(list)
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
        if freq < MIN_FREQ_FOR_BOOST and len(group) == 1:
            # 单次错也收录，但排序靠后；首批仍优先高频
            pass
        remember, pitfall = build_memory_trap(rep, freq=freq)
        ts = str(rep.get("timestamp") or rep.get("date") or "")
        by_area[area].append((remember, pitfall, eid, freq, ts))

    out: dict[str, list[tuple[str, str, int, int]]] = {}
    for area, items in by_area.items():
        items.sort(key=lambda x: (-x[3], x[4]))
        trimmed: list[tuple[str, str, int, int]] = []
        seen: set[str] = set()
        # 先收高频，不够再补低频
        for prefer_freq in (True, False):
            for remember, pitfall, eid, freq, _ts in items:
                if prefer_freq and freq < MIN_FREQ_FOR_BOOST:
                    continue
                if not prefer_freq and freq >= MIN_FREQ_FOR_BOOST:
                    continue
                rk = _row_key(remember, pitfall)
                if not rk or rk in seen:
                    continue
                if remember.startswith("记牢正确选项"):
                    continue
                seen.add(rk)
                trimmed.append((remember, pitfall, eid, freq))
                if len(trimmed) >= MAX_NEW_TRAPS_PER_DOMAIN:
                    break
            if len(trimmed) >= MAX_NEW_TRAPS_PER_DOMAIN:
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


def sync_traps_from_errors(*, dry_run: bool = False) -> SyncResult:
    """按当前错题本整段重写各领域「来自你的错题」可背区。"""
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
            from pmp_athena.retake_calendar import day_plan
        except ModuleNotFoundError:
            from retake_calendar import day_plan  # type: ignore
        p = day_plan(day)
        if p:
            slot = p.as_slot()
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
                morning = "[00-高频错题摘要卡](./00-高频错题摘要卡.md) + [三领域对比](./00-三领域对比速记卡.md)"
                afternoon = "复习错题 / 随机模考"
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
    """把今日推荐摘要卡插入 README（考前加练段之后）。"""
    new_content, n = re.subn(
        r"## 今日推荐摘要卡（10分钟）\n.*?(?=\n---\n\n## (?:每份文档结构|三、每份文档怎么读))",
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
                "\n\n**每日睡前**：过下方「今日推荐摘要卡」（当日领域 + 顽疾，约 10 道）"
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
        r"\*\*P0 完整合订\*\*：.*",
        "**P0 完整合订**：[00-P0三领域完整知识点](./00-P0三领域完整知识点.md)"
        "（成本 + 进度 为当前 P0；商业环境已降至 P2，合订本仍可对照）",
        content,
        count=1,
    )

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
        if (n or n_title) and new_content != content:
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
    pattern = (
        r"(\*\*考前加练\*\*：\[00-高频错题摘要卡\]\(\./00-高频错题摘要卡\.md\))"
        r"（错 ≥3 次的 \d+ 道题 · 锚点\+口诀）"
    )
    repl = rf"\1（错 ≥3 次的 {count} 道题 · 锚点+口诀）"
    new_content, n = re.subn(pattern, repl, content, count=1)
    if n:
        return new_content
    # 兼容旧版无该行 README
    marker = "## 推荐 7 天背诵计划"
    insert = (
        f"\n**考前加练**：[00-高频错题摘要卡](./00-高频错题摘要卡.md)"
        f"（错 ≥3 次的 {count} 道题 · 锚点+口诀）\n"
    )
    if marker in content and "00-高频错题摘要卡" not in content:
        return content.replace(marker, insert + marker, 1)
    return content


def _touch_daily_refresh() -> None:
    state = _load_sync_state()
    state["last_daily_refresh"] = date.today().isoformat()
    _save_sync_state(state)


def sync_all(*, dry_run: bool = False) -> SyncResult:
    trap_result = sync_traps_from_errors(dry_run=dry_run)
    hf_count, hf_written = sync_hf_cards(dry_run=dry_run)
    trap_result.hf_cards_count = hf_count
    trap_result.hf_cards_updated = hf_written
    trap_result.readme_updated = refresh_readme(dry_run=dry_run, hf_cards_count=hf_count)
    trap_result.headers_updated = refresh_domain_headers(dry_run=dry_run)
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
    if not (result.total_traps or result.hf_cards_updated or result.readme_updated):
        return ""
    return "📌 速记已同步：" + " · ".join(
        line.lstrip("- ") for line in result.summary_lines()
    )


def format_wechat_sync_report(result: SyncResult) -> str:
    lines = ["📌 **速记卡已同步**", ""]
    lines.extend(result.summary_lines())
    lines.extend([
        "",
        "💬 发「今日速记」背诵 · 「薄弱点速记」看优先级 · 「高频错题摘要卡」微信速查",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="薄弱点速记同步")
    sub = parser.add_subparsers(dest="command")

    for name, help_text in (
        ("sync", "增量同步错题到易错陷阱"),
        ("refresh-readme", "刷新 README 优先级表"),
        ("refresh-headers", "刷新各领域 MD 数据头"),
        ("refresh-hf-cards", "重生成高频错题摘要卡 MD"),
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
