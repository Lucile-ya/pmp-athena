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
