#!/usr/bin/env python3
"""根据做题数据生成「薄弱知识点推送」汇总页 + 各领域 combo 报告。"""

from __future__ import annotations

import json
import html as H
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pmp_athena.config import ERROR_LOG_PATH, PROJECT_ROOT, QUESTION_BANK_PATH, REPORTS_DIR
from pmp_athena.knowledge_report import DOMAIN_ASCII, TITLE_ASCII, _ascii_slug, update_index

EXAM_DATE = date(2026, 9, 12)

def _area_links() -> dict[str, str]:
    d = date.today().isoformat()
    return {cn: f"{d}-{_ascii_slug(cn)}-combo.html" for cn in DOMAIN_ASCII}

GENERATE_AREAS = [
    "商业环境知识点",
    "成本管理知识点",
    "质量管理知识点",
    "进度管理知识点",
    "范围管理知识点",
    "整合管理知识点",
    "敏捷/混合方法知识点",
    "资源管理知识点",
    "干系人管理知识点",
    "沟通管理知识点",
    "风险管理知识点",
    "采购管理知识点",
]


def _stats() -> list[tuple[float, int, str, int, int]]:
    bank = json.loads(QUESTION_BANK_PATH.read_text(encoding="utf-8"))
    errors = json.loads(ERROR_LOG_PATH.read_text(encoding="utf-8"))
    area: dict[str, dict[str, int]] = defaultdict(lambda: {"c": 0, "w": 0, "err": 0})
    for r in bank:
        a = r.get("knowledge_area", "综合")
        if r.get("is_correct") is True:
            area[a]["c"] += 1
        elif r.get("is_correct") is False:
            area[a]["w"] += 1
    for e in errors:
        area[e.get("knowledge_area", "综合")]["err"] += 1
    rows: list[tuple[float, int, str, int, int]] = []
    for a, s in area.items():
        judged = s["c"] + s["w"]
        if judged >= 2:
            rows.append((s["w"] / judged, s["err"], a, s["w"], judged))
    rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return rows


def _overdue_reviews() -> int:
    try:
        from pmp_athena.config import REVIEW_STATE_PATH
        state = json.loads(REVIEW_STATE_PATH.read_text(encoding="utf-8"))
        today = date.today().isoformat()
        return sum(
            1 for v in state.values()
            if isinstance(v, dict) and v.get("next_date", "9999") <= today
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


def generate_area_reports() -> None:
    py = sys.executable
    script = PROJECT_ROOT / "pmp_athena" / "knowledge_report.py"
    for area in GENERATE_AREAS:
        subprocess.run(
            [py, str(script), "generate", "--text", area, "--level", "combo"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    subprocess.run(
        [py, str(script), "generate", "--type", "weakness"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def build_hub_html(rows: list[tuple[float, int, str, int, int]], overdue: int) -> str:
    area_links = _area_links()
    d = date.today().isoformat()
    days = max(0, (EXAM_DATE - date.today()).days)
    items: list[str] = []
    for rate, err, a, w, t in rows:
        if a == "未分类":
            continue
        risk = "🔴 优先" if rate >= 0.6 else ("🟡 加强" if rate >= 0.45 else "🟢 维持")
        href = area_links.get(a, "")
        name = H.escape(a)
        if href:
            link = f'<a href="{H.escape(href)}">{name} 知识点 L1+L2 →</a>'
        else:
            link = name
        items.append(
            f'<li><strong>{risk}</strong> {link}<br/>'
            f'<span class="meta">错误率 {rate:.0%}（{w}/{t}）· 错题本 {err} 题</span></li>'
        )

    top3 = [a for _, _, a, _, _ in rows[:3] if a != "未分类"]
    tip = "、".join(top3) if top3 else "见下方列表"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>薄弱知识点推送</title>
<style>
body{{font-family:-apple-system,"PingFang SC",sans-serif;padding:16px;background:#f7f8fa;line-height:1.65}}
.wrap{{max-width:720px;margin:0 auto;background:#fff;padding:16px;border-radius:8px}}
h1{{font-size:1.25rem;color:#1e3a8a;margin:0 0 8px}}
h2{{font-size:1.05rem;color:#1d4ed8;margin:20px 0 10px}}
.sub{{color:#64748b;font-size:.85rem;margin-bottom:16px}}
ul{{padding-left:0;list-style:none}}
li{{padding:12px;margin:10px 0;background:#f8fafc;border-left:4px solid #3b82f6;border-radius:4px}}
.meta{{font-size:.85rem;color:#64748b}}
a{{color:#2563eb;text-decoration:none;font-weight:600}}
.box{{background:#eff6ff;padding:12px;border-radius:6px;margin:16px 0;font-size:.9rem}}
footer{{margin-top:24px;font-size:.75rem;color:#94a3b8;text-align:center}}
</style></head><body><div class="wrap">
<h1>📚 薄弱知识点推送</h1>
<p class="sub">基于做题记录 · {datetime.now().strftime("%Y-%m-%d %H:%M")} · 距考试 {days} 天</p>
<div class="box">💡 今日优先攻克：<strong>{H.escape(tip)}</strong>。错题复习逾期 <strong>{overdue}</strong> 道。</div>
<p><a href="{d}-weakness.html">📊 完整薄弱点诊断报告 →</a></p>
<h2>按薄弱程度（点击进入 L1+L2 知识点）</h2>
<ul>
{"".join(items)}
</ul>
<footer>PMP Athena · 手机报告</footer>
</div></body></html>"""


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    rows = _stats()
    overdue = _overdue_reviews()
    generate_area_reports()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    hub_name = f"{date.today().isoformat()}-weak-knowledge-hub.html"
    hub_path = REPORTS_DIR / hub_name
    hub_path.write_text(build_hub_html(rows, overdue), encoding="utf-8")

    from pmp_athena.knowledge_report import update_index

    update_index()
    print(f"✅ 已生成 {len(GENERATE_AREAS)} 个领域 combo 报告")
    print(f"✅ 汇总入口: reports/{hub_name}")
    print(f"📱 小程序打开 reports/index.html")


if __name__ == "__main__":
    main()
