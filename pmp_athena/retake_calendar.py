#!/usr/bin/env python3
"""补考周历 — 从 2026-12-补考学习计划.md 解析当天任务。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

try:
    from pmp_athena.config import RETAKE_PLAN_PATH
    from pmp_athena.knowledge_retriever import AREA_ALIASES, normalize_area
except ModuleNotFoundError:
    from config import RETAKE_PLAN_PATH  # type: ignore
    from knowledge_retriever import AREA_ALIASES, normalize_area  # type: ignore

_ROW_RE = re.compile(
    r"\|\s*\*\*(\d{1,2})/(\d{1,2})\s*[一二三四五六日]?\*\*\s*\|\s*([^|]*)\|\s*([^|]*)\|"
)
_EXTRA_ALIASES: list[tuple[str, list[str]]] = [
    ("商业环境", ["业务环境", "价值交付", "合规", "可持续"]),
    ("整合管理", ["变更流程", "变更", "经验教训", "项目执行", "收尾"]),
    ("风险管理", ["问题日志", "风险应对"]),
    ("范围管理", ["镀金", "范围蔓延", "WBS"]),
    ("质量管理", ["QA/QC", "质量审计"]),
    ("成本管理", ["CPI", "TCPI", "储备"]),
    ("进度管理", ["关键路径", "压缩", "赶工"]),
    ("干系人管理", ["People", "发起人"]),
    ("敏捷/混合方法", ["Backlog", "PO", "迭代", "适应"]),
]


@dataclass
class DayPlan:
    day: date
    live: str
    athena: str
    areas: list[str] = field(default_factory=list)
    question_n: int = 20
    review_n: int = 5
    kind: str = "area"  # area | finale | mock | exam
    skip_live: bool = False

    @property
    def primary(self) -> str | None:
        if self.kind in ("finale", "exam", "mock"):
            return None
        return self.areas[0] if self.areas else None

    @property
    def plan_key(self) -> str:
        return f"{self.day.isoformat()}|{self.kind}|{','.join(self.areas)}|{self.question_n}|{self.review_n}"

    def why_line(self) -> str:
        task = re.sub(r"\*\*", "", re.sub(r"\s+", " ", self.athena)).strip()
        if len(task) > 42:
            task = task[:40] + "…"
        live = re.sub(r"\s+", " ", self.live).strip()
        if self.kind == "exam":
            return "考试日：只过口诀，不准刷新题"
        if self.kind == "mock":
            return f"周历硬节点：{task or '全真模考'}"
        if self.skip_live:
            return f"周历：{task}"
        if live and live not in ("—", "-"):
            return f"周历：{task} · 课：{live[:18]}"
        return f"周历：{task}"

    def as_slot(self) -> dict:
        return {
            "kind": self.kind,
            "area": self.primary,
            "focus": list(self.areas),
            "question_n": self.question_n,
            "review_n": self.review_n,
            "why": self.why_line(),
            "athena": self.athena,
            "live": self.live,
            "plan_key": self.plan_key,
            "skip_live": self.skip_live,
        }


def _extract_areas(text: str) -> list[str]:
    found: list[str] = []
    pairs: list[tuple[str, str]] = []
    for area, aliases in list(AREA_ALIASES) + _EXTRA_ALIASES:
        for alias in aliases:
            pairs.append((area, alias))
        pairs.append((area, area))
    pairs.sort(key=lambda x: len(x[1]), reverse=True)
    for area, alias in pairs:
        if alias and alias in text and area not in found:
            mapped = normalize_area(area) or area
            if mapped not in found:
                found.append(mapped)
    return found


def _question_n(athena: str, kind: str) -> int:
    if kind in ("exam", "finale", "mock"):
        return 0
    if re.search(r"错题复习|错题清账|只复盘", athena) and "额度" in athena:
        return 0
    nums = [int(x) for x in re.findall(r"(\d+)\s*(?:道|题)", athena)]
    nums = [n for n in nums if 5 <= n <= 40]
    if not nums:
        if re.search(r"少刷|整理笔记|轻量复习|口诀|放松", athena):
            return 0
        return 20
    if len(nums) >= 2 and nums[0] <= 15 and nums[1] <= 15:
        return nums[0] + nums[1]
    return max(nums)


def _review_n(athena: str, kind: str) -> int:
    m = re.search(r"错题[^\d]{0,6}(\d+)\s*(?:道|题)", athena)
    if m:
        return int(m.group(1))
    if re.search(r"只复盘|错题清账", athena):
        return 25
    if kind in ("exam",):
        return 0
    return 5


def _kind(live: str, athena: str) -> str:
    blob = live + athena
    if "考试" in blob and "模考" not in blob:
        return "exam"
    if re.search(r"模考[一二]|全天模考", blob):
        return "mock"
    if re.search(r"停新题|只复盘|放松|早睡", athena):
        return "finale"
    return "area"


def _skip_live(live: str, athena: str) -> bool:
    return bool(re.search(r"跳过|倍速|可倍速", live + athena))


def _parse(path: Path | None = None) -> dict[date, DayPlan]:
    src = path or RETAKE_PLAN_PATH
    try:
        text = src.read_text(encoding="utf-8")
    except OSError:
        return {}
    year = 2026
    ym = re.search(r"(20\d{2})\s*年\s*12\s*月", text)
    if ym:
        year = int(ym.group(1))
    out: dict[date, DayPlan] = {}
    for m in _ROW_RE.finditer(text):
        month, day = int(m.group(1)), int(m.group(2))
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        live = m.group(3).strip()
        athena = m.group(4).strip()
        kind = _kind(live, athena)
        areas = _extract_areas(athena) if kind == "area" else []
        if kind == "area" and not areas:
            areas = _extract_areas(live)
        qn = _question_n(athena, kind)
        if kind == "area" and not areas and qn == 0:
            kind = "finale"
        out[d] = DayPlan(
            day=d,
            live=live,
            athena=athena,
            areas=areas,
            question_n=qn,
            review_n=_review_n(athena, kind),
            kind=kind,
            skip_live=_skip_live(live, athena),
        )
    return out


_CACHE: dict[date, DayPlan] | None = None


def all_days(path: Path | None = None) -> dict[date, DayPlan]:
    global _CACHE
    if path is None and _CACHE is not None:
        return _CACHE
    data = _parse(path)
    if path is None:
        _CACHE = data
    return data


def day_plan(day: date | None = None, path: Path | None = None) -> DayPlan | None:
    day = day or date.today()
    return all_days(path).get(day)


def next_plan(day: date | None = None, path: Path | None = None) -> DayPlan | None:
    day = day or date.today()
    table = all_days(path)
    nxt = day + timedelta(days=1)
    return table.get(nxt)


def latest_mock_weak_ranking(*, limit: int = 6) -> list[str]:
    """最近一次完整模考的弱域排序（错题多→少），映射到标准领域名。

    优先：exam_records 最近 completed 且 ≥100 题的 weak_areas；
    其次：错题本/题库里带「模拟考试」标记或 source=mock_exam 的近期错题计数；
    再退：历史薄弱错误率。
    """
    ranked: list[str] = []

    # 1) exam_records.weak_areas
    try:
        try:
            from pmp_athena.config import EXAM_RECORDS_PATH
        except ModuleNotFoundError:
            from config import EXAM_RECORDS_PATH  # type: ignore
        import json

        raw = json.loads(EXAM_RECORDS_PATH.read_text(encoding="utf-8"))
        exams = raw.get("exams") if isinstance(raw, dict) else raw
        mocks = [
            e
            for e in (exams or [])
            if isinstance(e, dict)
            and e.get("status", "completed") == "completed"
            and int(e.get("total_questions") or 0) >= 100
        ]
        mocks.sort(key=lambda e: str(e.get("exam_date") or e.get("date") or ""), reverse=True)
        if mocks:
            for name in mocks[0].get("weak_areas") or []:
                mapped = normalize_area(str(name)) or str(name)
                if mapped and mapped not in ranked:
                    ranked.append(mapped)
    except Exception:
        pass

    # 2) 错题本：模拟考试题干 / mock_exam 来源
    if len(ranked) < 2:
        from collections import Counter

        counts: Counter[str] = Counter()
        try:
            try:
                from pmp_athena.config import ERROR_LOG_PATH, QUESTION_BANK_PATH
            except ModuleNotFoundError:
                from config import ERROR_LOG_PATH, QUESTION_BANK_PATH  # type: ignore
            import json

            err = json.loads(ERROR_LOG_PATH.read_text(encoding="utf-8"))
            items = err.get("errors") if isinstance(err, dict) else err
            for e in items or []:
                if not isinstance(e, dict):
                    continue
                q = str(e.get("question") or "")
                if "模拟考试" not in q and "模考" not in q[:20]:
                    continue
                area = normalize_area(e.get("knowledge_area") or "") or e.get("knowledge_area")
                if area:
                    counts[str(area)] += 1
            if not counts:
                bank = json.loads(QUESTION_BANK_PATH.read_text(encoding="utf-8"))
                qs = bank if isinstance(bank, list) else bank.get("questions") or []
                for r in qs:
                    if not isinstance(r, dict):
                        continue
                    if r.get("is_correct") is not False:
                        continue
                    if (r.get("source") or "") != "mock_exam":
                        continue
                    area = normalize_area(r.get("knowledge_area") or "") or r.get(
                        "knowledge_area"
                    )
                    if area:
                        counts[str(area)] += 1
            for area, _n in counts.most_common(limit):
                if area not in ranked:
                    ranked.append(area)
        except Exception:
            pass

    # 3) 历史薄弱兜底
    if len(ranked) < 2:
        try:
            try:
                from pmp_athena.weak_area_cheatsheet import get_weak_areas
            except ModuleNotFoundError:
                from weak_area_cheatsheet import get_weak_areas  # type: ignore

            for area, _rate, _w, _t in get_weak_areas():
                mapped = normalize_area(area) or area
                if mapped and mapped not in ranked:
                    ranked.append(mapped)
                if len(ranked) >= limit:
                    break
        except Exception:
            pass

    return ranked[:limit]


def resolve_day_areas(plan: DayPlan | None) -> list[str]:
    """解析当天领域；支持周历「模考最弱域 / 次弱域」动态占位。"""
    if plan is None:
        return []
    areas = list(plan.areas or [])
    blob = f"{plan.athena} {plan.live}"
    need_dynamic = bool(
        re.search(r"最弱域|次弱域|模考最弱|模考次弱", blob)
    ) or (plan.kind == "area" and not areas)

    if need_dynamic:
        ranking = latest_mock_weak_ranking()
        if re.search(r"次弱域|模考次弱", blob):
            pick = ranking[1] if len(ranking) > 1 else (ranking[0] if ranking else None)
            areas = [pick] if pick else areas
        elif re.search(r"最弱域|模考最弱", blob) or not areas:
            pick = ranking[0] if ranking else None
            if pick:
                # 「最弱+次弱」类文案可带两个
                if re.search(r"最弱.?次弱|次弱.?最弱", blob) and len(ranking) > 1:
                    areas = ranking[:2]
                else:
                    areas = [pick]

    # 规范化
    out: list[str] = []
    for a in areas:
        mapped = normalize_area(a) or a
        if mapped and mapped not in out:
            out.append(mapped)
    return out


def enriched_slot(day: date | None = None, path: Path | None = None) -> dict:
    """day_plan.as_slot() + 动态弱域解析（供今日任务 / 今日速记共用）。"""
    p = day_plan(day, path)
    if not p:
        return {}
    slot = p.as_slot()
    areas = resolve_day_areas(p)
    if areas:
        slot["area"] = areas[0]
        slot["focus"] = areas
        if re.search(r"最弱域|次弱域", p.athena):
            label = "+".join(
                ("敏捷" if a.startswith("敏捷") else a) for a in areas[:2]
            )
            task = re.sub(r"\*\*", "", p.athena).strip()
            if len(task) > 28:
                task = task[:26] + "…"
            slot["why"] = f"周历：{task} → {label}"
    return slot
