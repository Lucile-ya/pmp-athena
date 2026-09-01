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
AUTO_TRAP_HEADING = "### 来自错题本（自动"
TRAP_SECTION_HEADERS = ("七、易错陷阱", "八、易错陷阱", "十、易错陷阱")
MAX_WRONG_COL = 48
MAX_RIGHT_COL = 56
MIN_FREQ_FOR_BOOST = 2
MAX_NEW_TRAPS_PER_DOMAIN = 8
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
            parts = [f"{a} +{n}" for a, n in self.traps_added.items() if n]
            lines.append(f"- 新增 **{self.total_traps}** 条易错陷阱（{', '.join(parts)}）")
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


def build_trap_row(error: dict, *, freq: int = 1) -> tuple[str, str]:
    """生成易错陷阱表格行 (❌, ✅)。"""
    my_a = (error.get("my_answer") or "?").strip()
    ok_a = (error.get("correct_answer") or "?").strip()
    gist = _question_gist(error.get("question", ""))
    wrong = f"{gist}（选{my_a}）"
    if freq >= MIN_FREQ_FOR_BOOST:
        wrong += f" ×{freq}"
    expl = _truncate(error.get("explanation") or f"应选 {ok_a}", MAX_RIGHT_COL)
    if ok_a not in expl and ok_a != "?":
        expl = f"应选 {ok_a} — {expl}"
    return (_truncate(wrong, MAX_WRONG_COL), _truncate(expl, MAX_RIGHT_COL))


def _row_key(wrong: str, right: str) -> str:
    return re.sub(r"\s+", " ", f"{wrong}|{right}").lower()


def _existing_trap_keys(content: str) -> set[str]:
    keys: set[str] = set()
    for line in content.splitlines():
        if "|" not in line or line.strip().startswith("|---"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) >= 2 and parts[0] not in ("❌ 错", "错", "问"):
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


def _insert_auto_trap_rows(content: str, new_rows: list[tuple[str, str]], today: str) -> str:
    if not new_rows:
        return content

    span = _find_trap_section_span(content)
    if not span:
        return content

    start, end = span
    section = content[start:end]
    heading_re = re.compile(
        rf"^{re.escape(AUTO_TRAP_HEADING)}[^\n]*\n\n\| ❌ 错 \| ✅ 对 \|\n\|[-| ]+\|\n",
        re.MULTILINE,
    )
    table_rows = "".join(f"| {w} | {r} |\n" for w, r in new_rows)

    if heading_re.search(section):

        def _repl(m: re.Match[str]) -> str:
            head = m.group(0)
            if "更新于" in head:
                head = re.sub(r"更新于 \d{4}-\d{2}-\d{2}", f"更新于 {today}", head)
            else:
                head = head.replace(
                    AUTO_TRAP_HEADING,
                    f"{AUTO_TRAP_HEADING} · 更新于 {today}",
                    1,
                )
            return head + table_rows

        section = heading_re.sub(_repl, section, count=1)
    else:
        block = (
            f"\n{AUTO_TRAP_HEADING} · 更新于 {today}\n\n"
            "| ❌ 错 | ✅ 对 |\n"
            "|------|------|\n"
            f"{table_rows}"
        )
        section = section.rstrip() + block + "\n"

    return content[:start] + section + content[end:]


def _map_error_area(error: dict) -> str | None:
    raw = error.get("knowledge_area") or ""
    mapped = _resolve_cheatsheet_area(raw)
    if mapped:
        return mapped
    area = normalize_area(raw)
    if area in DOMAIN_FILES:
        return area
    return None


def collect_trap_candidates(
    errors: list[dict],
    synced_ids: set[int],
) -> dict[str, list[tuple[str, str, int]]]:
    """返回 {领域: [(wrong, right, error_id), ...]}，优先高频与未同步。"""
    by_area: dict[str, list[tuple[str, str, int, int, str]]] = defaultdict(list)
    freq_groups: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)

    for err in errors:
        area = _map_error_area(err)
        eid = err.get("id")
        if not area or not isinstance(eid, int):
            continue
        gist = _question_gist(err.get("question", ""), 30)
        key = (area, gist, str(err.get("my_answer", "")), str(err.get("correct_answer", "")))
        freq_groups[key].append(err)

    first_bootstrap = len(synced_ids) == 0

    for (_area, _gist, _my, _ok), group in freq_groups.items():
        area = _area
        rep = max(group, key=lambda e: e.get("timestamp") or e.get("date") or "")
        eid = rep.get("id")
        if not isinstance(eid, int):
            continue
        freq = len(group)
        unsynced = [e for e in group if e.get("id") not in synced_ids]

        if first_bootstrap and BOOTSTRAP_FREQ_ONLY and freq < MIN_FREQ_FOR_BOOST:
            continue
        if not unsynced and eid in synced_ids:
            continue

        wrong, right = build_trap_row(rep, freq=freq if freq >= MIN_FREQ_FOR_BOOST else 1)
        ts = str(rep.get("timestamp") or rep.get("date") or "")
        by_area[area].append((wrong, right, eid, freq, ts))

    out: dict[str, list[tuple[str, str, int]]] = {}
    for area, items in by_area.items():
        items.sort(key=lambda x: (-x[3], x[4]))
        trimmed: list[tuple[str, str, int]] = []
        seen: set[str] = set()
        for wrong, right, eid, _freq, _ts in items:
            rk = _row_key(wrong, right)
            if rk in seen:
                continue
            seen.add(rk)
            trimmed.append((wrong, right, eid))
            if len(trimmed) >= MAX_NEW_TRAPS_PER_DOMAIN:
                break
        if trimmed:
            out[area] = trimmed
    return out


def sync_traps_from_errors(*, dry_run: bool = False) -> SyncResult:
    result = SyncResult()
    errors = _load_errors()
    state = _load_sync_state()
    synced_ids: set[int] = set(state.get("synced_error_ids") or [])
    first_bootstrap = len(synced_ids) == 0
    today = date.today().isoformat()

    candidates = collect_trap_candidates(errors, synced_ids)

    for area, rows_with_ids in candidates.items():
        filename = DOMAIN_FILES.get(area)
        if not filename:
            continue
        path = CHEATSHEET_DIR / filename
        if not path.is_file():
            continue

        content = path.read_text(encoding="utf-8")
        existing = _existing_trap_keys(content)
        to_add: list[tuple[str, str]] = []
        new_ids: list[int] = []

        for wrong, right, eid in rows_with_ids:
            if _row_key(wrong, right) in existing:
                result.skipped_duplicate += 1
                synced_ids.add(eid)
                continue
            if eid in synced_ids:
                continue
            to_add.append((wrong, right))
            new_ids.append(eid)
            existing.add(_row_key(wrong, right))

        if not to_add:
            continue

        if not dry_run:
            updated = _insert_auto_trap_rows(content, to_add, today)
            path.write_text(updated, encoding="utf-8")

        result.traps_added[area] = len(to_add)
        result.synced_ids.extend(new_ids)
        synced_ids.update(new_ids)

    if not dry_run:
        if first_bootstrap:
            for e in errors:
                eid = e.get("id")
                if isinstance(eid, int) and _map_error_area(e):
                    synced_ids.add(eid)
        if result.synced_ids or result.skipped_duplicate or first_bootstrap:
            state["synced_error_ids"] = sorted(synced_ids)
            state["last_trap_sync"] = today
            if first_bootstrap:
                state["bootstrapped"] = True
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


def refresh_readme(*, dry_run: bool = False, hf_cards_count: int | None = None) -> bool:
    if not README_PATH.is_file():
        return False

    weak = get_weak_areas()
    weak_map = {a: (rate, wrong, total) for a, rate, wrong, total in weak}
    err_counts = _error_counts_by_area(_load_errors())
    today = date.today()

    try:
        from pmp_athena.exam_timer import days_until_exam
        d_day = days_until_exam()
    except Exception:
        d_day = (date(2026, 9, 12) - today).days

    phase = "🔥 冲刺模考期" if d_day <= 11 else ("⚡ 强化刷题期" if d_day <= 30 else "📖 基础巩固期")

    rows: list[tuple[str, str, str, str, str, str]] = []
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
        mnemonic = ""
        if md_path.is_file():
            for raw in md_path.read_text(encoding="utf-8").splitlines():
                line = raw.lstrip("> ").strip()
                m = re.search(r"总口诀[：:]\s*\*\*([^*]+)\*\*", line)
                if m and m.group(1).strip() != "总口诀":
                    mnemonic = m.group(1).strip()
                    break

        rows.append((tag, num, area, rate_str, str(err_n), mnemonic))

    rows.sort(key=lambda r: (0 if r[0] == "🔴 P0" else (1 if r[0] == "🟡 P1" else 2), r[2]))

    table_lines = [
        "| 优先级 | 文件 | 错误率 | 错题本 | 总口诀 |",
        "|:------:|------|:------:|:------:|--------|",
    ]
    for tag, num, area, rate_str, err_n, mnemonic in rows:
        stem = DOMAIN_FILES[area].replace(".md", "")
        link = f"[{stem}](./{DOMAIN_FILES[area]})"
        table_lines.append(f"| {tag} | {link} | {rate_str} | **{err_n}** | {mnemonic or '—'} |")

    content = README_PATH.read_text(encoding="utf-8")
    header = (
        f"> 生成日期：{today.isoformat()} · 距考试 {max(d_day, 0)} 天 · 阶段：{phase}  \n"
        f"> 用法：**每天攻 1 个领域** → 先背口诀 → 看易错陷阱 → 做专项 10 题"
    )
    content = re.sub(
        r"> 生成日期：.*?→ 做专项 10 题",
        header,
        content,
        count=1,
        flags=re.DOTALL,
    )

    new_table = "\n".join(table_lines)
    content = re.sub(
        r"(## 你的薄弱优先级（按紧急度排序）\n\n)(.*?)(\n\n---\n\n## 推荐 7 天)",
        lambda m: m.group(1) + new_table + m.group(3),
        content,
        count=1,
        flags=re.DOTALL,
    )

    if hf_cards_count is not None:
        content = _update_readme_hf_line(content, hf_cards_count)

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
        if info:
            rate, wrong, total = info
            bank_line = f"错误率 **{rate:.0%}**（{wrong}/{total}）"
        else:
            bank_line = "错误率 —"
        new_data = f"> **你的数据**：{bank_line} · 错题本 {err_n} 题"

        new_content, n = re.subn(
            r"> \*\*你的数据\*\*：[^\n]+",
            new_data,
            content,
            count=1,
        )
        if n and new_content != content:
            if not dry_run:
                path.write_text(new_content, encoding="utf-8")
            updated += 1

    return updated


def sync_hf_cards(*, dry_run: bool = False, top_n: int = 50, min_mistakes: int = 3) -> tuple[int, bool]:
    """从 error_log 重生成 00-高频错题摘要卡.md。返回 (题数, 是否写入)。"""
    try:
        from pmp_athena.error_insights import rank_high_frequency_errors
        from pmp_athena.export_hf_cards import export_cards
    except ModuleNotFoundError:
        from error_insights import rank_high_frequency_errors
        from export_hf_cards import export_cards

    count = len(rank_high_frequency_errors(top_n=top_n, min_mistakes=min_mistakes))
    if dry_run:
        return count, False

    export_cards(top_n=top_n, min_mistakes=min_mistakes)
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


def sync_all(*, dry_run: bool = False) -> SyncResult:
    trap_result = sync_traps_from_errors(dry_run=dry_run)
    hf_count, hf_written = sync_hf_cards(dry_run=dry_run)
    trap_result.hf_cards_count = hf_count
    trap_result.hf_cards_updated = hf_written
    trap_result.readme_updated = refresh_readme(dry_run=dry_run, hf_cards_count=hf_count)
    trap_result.headers_updated = refresh_domain_headers(dry_run=dry_run)
    return trap_result


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
