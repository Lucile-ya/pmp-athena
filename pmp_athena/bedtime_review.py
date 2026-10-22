#!/usr/bin/env python3
"""
睡前复习 — 微信硬路由入口。

D-Day 自适应四档 + 今日到期错题优先 + bedtime_tracker 去重。

触发词: 睡前复习 / 睡前回顾 / 睡前清单

CLI:
  python pmp_athena/bedtime_review.py message --text "睡前复习"
  python pmp_athena/bedtime_review.py push
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from pmp_athena.config import (
        ERROR_LOG_PATH,
        NOTES_DIR,
        QUESTION_BANK_PATH,
        RETAKE_REVIEW_QUOTA,
        REVIEW_STATE_PATH,
        TODAY_QUEST_PATH,
        get_target_exam_date,
    )
    from pmp_athena.review_scheduler import (
        PRE_EXAM_30_DAYS,
        PRE_EXAM_DAYS,
        ReviewScheduler,
    )
except ModuleNotFoundError:
    from config import (  # type: ignore
        ERROR_LOG_PATH,
        NOTES_DIR,
        QUESTION_BANK_PATH,
        RETAKE_REVIEW_QUOTA,
        REVIEW_STATE_PATH,
        TODAY_QUEST_PATH,
        get_target_exam_date,
    )
    from review_scheduler import (  # type: ignore
        PRE_EXAM_30_DAYS,
        PRE_EXAM_DAYS,
        ReviewScheduler,
    )

TRACKER_PATH = NOTES_DIR / "bedtime_tracker.json"
TRIGGERS = frozenset({"睡前复习", "睡前回顾", "睡前清单", "晚上复习", "睡前"})

# 全领域池：(编号, 领域, 一句话)
KNOWLEDGE_POOL: list[tuple[int, str, str]] = [
    (1, "整合管理", "项目章程由发起人签发，正式授权项目经理动用资源"),
    (2, "范围管理", "WBS 是范围基准的核心组件，将可交付成果逐层分解为工作包"),
    (3, "进度管理", "关键路径上任何活动的延迟都会导致项目总工期延迟"),
    (4, "成本管理", "CPI = EV/AC，< 1 表示成本超支；SPI = EV/PV，< 1 表示进度落后"),
    (5, "质量管理", "管理质量（QA）关注过程是否合规，控制质量（QC）关注可交付物是否达标"),
    (6, "资源管理", "RACI 矩阵明确谁执行(A)、谁负责(R)、咨询谁(C)、告知谁(I)"),
    (7, "沟通管理", "沟通方法：交互式（双向实时）> 推式（发送但不确保接收）> 拉式（自行查阅）"),
    (8, "风险管理", "风险应对：规避 → 转移 → 减轻 → 接受"),
    (9, "干系人管理", "干系人权力利益方格：高权力高利益 = 密切管理"),
    (10, "敏捷/混合方法", "敏捷中 PO 定义需求并排优先级，Scrum Master 清除障碍，团队自组织交付"),
    (11, "敏捷/混合方法", "燃尽图反映剩余工作量，燃起图反映已完成工作量"),
    (12, "整合管理", "变更请求：先评估影响，再提交 CCB 审批，批准后才实施"),
    (13, "风险管理", "问题日志记录已发生的问题，风险登记册记录可能发生的事件"),
    (14, "质量管理", "质量审计 = 独立审查质量管理活动是否有效（管理质量工具）"),
    (15, "资源管理", "资源日历 = 每个资源可用的具体时间段"),
    (16, "采购管理", "投标人会议在投标前召开，确保所有潜在卖方对采购需求理解一致"),
    (17, "沟通管理", "沟通管理计划 = 谁需要什么信息、何时需要、怎么传递"),
    (18, "采购管理", "固定总价合同（FFP）— 买方风险最低，卖方承担成本超支风险"),
    (19, "资源管理", "Tuckman 团队发展模型：形成→震荡→规范→成熟→解散"),
    (20, "领导力/人员", "冲突解决优先级：合作/解决问题 > 妥协 > 缓和 > 强迫 > 回避"),
    (21, "敏捷/混合方法", "信息发射源（Information Radiator）— 燃尽图、看板、任务板"),
    (22, "敏捷/混合方法", "MoSCoW 优先级排序：Must > Should > Could > Won't"),
    (23, "成本管理", "类比估算（快速粗略）vs 参数估算（历史公式）vs 自下而上（最准最费时）"),
    (24, "沟通管理", "规划沟通 → 管理沟通（执行分发）→ 监督沟通（监控效果）"),
    (25, "风险管理", "应急储备（已知风险）vs 管理储备（未知风险，使用时需变更基准）"),
    (26, "整合管理", "配置管理 = 管理产品/成果的版本和变更，确保可追溯"),
    (27, "质量管理", "鱼骨图（石川图）/ 因果图 → 找根本原因，不仅是表象"),
    (28, "质量管理", "帕累托法则（80/20）→ 少数原因造成多数问题"),
    (29, "整合管理", "德尔菲技术 → 专家匿名多轮投票，消除偏见"),
    (30, "进度管理", "滚动式规划 → 近期工作详细规划，远期工作粗略规划"),
]

MUST_KNOW: list[tuple[int, str, str]] = [
    (101, "整合管理", "变更流程：评估影响 → 提交 CCB → 批准后实施。CCB 审批通过前不得执行变更。"),
    (102, "风险管理", "风险应对：规避 > 转移 > 减轻 > 接受 > 上报（超出权限）"),
    (103, "干系人管理", "干系人管理：识别 → 规划参与 → 管理参与 → 监督参与。权力利益方格是关键工具。"),
    (104, "成本管理", "挣值：CV=EV-AC，SV=EV-PV，CPI=EV/AC，SPI=EV/PV"),
    (105, "沟通管理", "信息交换方式：交互式 > 推式 > 拉式"),
    (106, "质量管理", "规划质量管理 → 管理质量(QA) → 控制质量(QC)"),
    (107, "领导力/人员", "冲突解决：合作/解决问题是第一选择，强迫是最后手段"),
    (108, "采购管理", "固定总价买方风险低、成本补偿买方风险高、工料双方共担"),
    (109, "敏捷/混合方法", "敏捷三角色：PO（定优先级）→ SM（清障碍）→ 开发团队（自组织）"),
    (110, "风险管理", "问题 = 已发生（问题日志）；风险 = 可能发生（风险登记册）"),
    (111, "干系人管理", "新干系人出现：先沟通了解需求，再更新干系人登记册。先人后工具。"),
    (112, "范围管理", "范围基准 = WBS + WBS 词典 + 范围说明书"),
]

QUICK_QUIZ: list[dict[str, str]] = [
    {
        "stem": "客户口头要求增加功能，项目经理首先应？",
        "A": "立即安排开发",
        "B": "评估影响并走变更/Backlog",
        "C": "直接拒绝以保基准",
        "D": "先上报发起人",
        "answer": "B",
        "tip": "先评估 + 走流程（P1+P3），不口头接受范围蔓延。",
    },
    {
        "stem": "风险已经发生并造成影响，应记入？",
        "A": "风险登记册",
        "B": "问题日志",
        "C": "变更日志",
        "D": "经验教训登记册",
        "answer": "B",
        "tip": "已发生 = 问题（Issue Log）；可能发生才写风险登记册。",
    },
    {
        "stem": "敏捷中谁负责对产品待办列表排优先级？",
        "A": "Scrum Master",
        "B": "项目经理",
        "C": "产品负责人(PO)",
        "D": "开发团队",
        "answer": "C",
        "tip": "PO 定优先级；SM 清障碍；团队自组织交付。",
    },
]


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _days_to_exam(today: date | None = None) -> int:
    today = today or date.today()
    return (get_target_exam_date() - today).days


def _tier(d: int) -> str:
    if d > 30:
        return "green"
    if d > 15:
        return "yellow"
    if d > 7:
        return "orange"
    return "red"


def _review_items() -> dict[str, dict]:
    raw = _load_json(REVIEW_STATE_PATH, {})
    if isinstance(raw, dict) and "items" in raw and isinstance(raw["items"], dict):
        return raw["items"]
    return raw if isinstance(raw, dict) else {}


def _error_by_id() -> dict[int, dict]:
    rows = _load_json(ERROR_LOG_PATH, [])
    if not isinstance(rows, list):
        return {}
    return {int(r["id"]): r for r in rows if isinstance(r, dict) and "id" in r}


def _row_for_error(eid: int) -> dict:
    items = _review_items()
    elog = _error_by_id()
    st = items.get(str(eid)) or items.get(eid) or {}
    if not isinstance(st, dict):
        st = {}
    err = elog.get(eid, {})
    preview = (
        st.get("question_preview")
        or (err.get("question") or "")[:40]
        or f"错题 #{eid}"
    )
    area = st.get("knowledge_area") or err.get("knowledge_area") or "综合"
    return {"id": eid, "area": area, "preview": str(preview).replace("\n", " ")[:50]}


def _today_review_gate(today: date) -> tuple[int, int, list[dict]]:
    """与今日任务一致：按补考定额判断，不扫全部历史到期。

    Returns:
        (done, quota, pending_rows) — pending 为空则放行知识点推送。
    """
    sch = ReviewScheduler()
    days = (get_target_exam_date() - today).days
    plan = sch.build_daily_plan(
        is_pre_exam=days <= PRE_EXAM_DAYS,
        is_pre30=days <= PRE_EXAM_30_DAYS,
    )
    done = int(plan.get("completed_today") or 0)
    remaining_ids = [int(x) for x in (plan.get("questions") or [])]

    quest = _load_json(TODAY_QUEST_PATH, {})
    kind = quest.get("kind") if isinstance(quest, dict) else "area"
    quota = RETAKE_REVIEW_QUOTA
    if isinstance(quest, dict) and quest.get("review_n") is not None:
        try:
            quota = int(quest["review_n"])
        except (TypeError, ValueError):
            quota = RETAKE_REVIEW_QUOTA

    # 考前清零 / 大配额日：跟调度器真实剩余
    if kind in ("finale", "mock") or quota >= 25:
        pending = [_row_for_error(eid) for eid in remaining_ids]
        total = max(done + len(pending), quota)
        return done, total, pending

    # 日常补考：定额做完即放行（多刷不算欠账）
    if quota <= 0:
        pending = [_row_for_error(eid) for eid in remaining_ids]
        return done, done + len(pending), pending

    if done >= quota:
        return min(done, quota), quota, []

    need = quota - done
    pending = [_row_for_error(eid) for eid in remaining_ids[:need]]
    return min(done, quota), quota, pending


def _tomorrow_preview(today: date) -> str:
    tomorrow = (today + timedelta(days=1)).isoformat()
    items = _review_items()
    elog = _error_by_id()
    areas: Counter[str] = Counter()
    n = 0
    for key, st in items.items():
        if not isinstance(st, dict):
            continue
        if st.get("next_date") != tomorrow:
            continue
        n += 1
        eid = int(st.get("error_id") or key)
        area = st.get("knowledge_area") or elog.get(eid, {}).get("knowledge_area") or "综合"
        areas[area] += 1
    if n == 0:
        return "📆 明日预告: 暂无到期错题"
    dist = " / ".join(f"{a} {c}题" for a, c in areas.most_common(3))
    return f"📆 明日预告: {n} 道错题待复习（{dist}）"


def _recent_error_areas(today: date, days: int = 3) -> list[tuple[str, int]]:
    rows = _load_json(ERROR_LOG_PATH, [])
    if not isinstance(rows, list):
        return []
    cutoff = (today - timedelta(days=days)).isoformat()
    cnt: Counter[str] = Counter()
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = r.get("date") or ""
        if d < cutoff:
            continue
        area = r.get("knowledge_area") or "综合"
        cnt[area] += 1
    if not cnt and days < 7:
        return _recent_error_areas(today, days=7)
    return cnt.most_common(3)


def _weak_areas(top_n: int = 3) -> list[str]:
    rows = _load_json(QUESTION_BANK_PATH, [])
    if not isinstance(rows, list):
        return []
    stats: dict[str, list[int]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        area = r.get("knowledge_area") or "综合"
        w, t = stats.setdefault(area, [0, 0])
        t += 1
        if not r.get("is_correct", True):
            w += 1
        stats[area] = [w, t]
    ranked = sorted(
        ((a, w / t if t else 0, t) for a, (w, t) in stats.items() if t >= 2),
        key=lambda x: (-x[1], -x[2]),
    )
    return [a for a, _, _ in ranked[:top_n]]


def _load_tracker() -> dict:
    return _load_json(TRACKER_PATH, {"last_pushed": None, "pushed_items": [], "history": {}})


def _save_tracker(data: dict) -> None:
    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 只保留最近 15 天
    hist = data.get("history") or {}
    if isinstance(hist, dict) and len(hist) > 15:
        keep = sorted(hist.keys())[-15:]
        data["history"] = {k: hist[k] for k in keep}
    TRACKER_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _recent_pushed_ids(tracker: dict, today: date, lookback: int = 3) -> set[int]:
    hist = tracker.get("history") or {}
    out: set[int] = set()
    for i in range(lookback):
        key = (today - timedelta(days=i)).isoformat()
        for x in hist.get(key) or []:
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                pass
    return out


def _pick_from_pool(
    pool: list[tuple[int, str, str]],
    n: int,
    exclude: set[int],
    area_filter: list[str] | None = None,
) -> list[tuple[int, str, str]]:
    candidates = [
        p for p in pool
        if p[0] not in exclude and (not area_filter or p[1] in area_filter)
    ]
    if len(candidates) < n:
        # 放宽：去掉领域过滤
        candidates = [p for p in pool if p[0] not in exclude]
    if len(candidates) < n:
        # 再放宽：允许最近推送过的
        candidates = list(pool if not area_filter else [p for p in pool if p[1] in area_filter] or pool)
    random.shuffle(candidates)
    return candidates[:n]


def _error_knowledge_lines(today: date, n: int = 3) -> list[str]:
    """从错题本提炼错题知识点（橙档）。"""
    rows = _load_json(ERROR_LOG_PATH, [])
    if not isinstance(rows, list):
        return []
    # 优先近 14 天错题
    cutoff = (today - timedelta(days=14)).isoformat()
    recent = [r for r in rows if isinstance(r, dict) and (r.get("date") or "") >= cutoff]
    src = recent or [r for r in rows if isinstance(r, dict)]
    random.shuffle(src)
    lines: list[str] = []
    seen_areas: set[str] = set()
    for r in src:
        area = r.get("knowledge_area") or "综合"
        if area in seen_areas and len(lines) < n:
            continue
        expl = (r.get("explanation") or "").strip().replace("\n", " ")
        if not expl:
            expl = "对照标准答案复盘决策链"
        tip = expl[:40]
        lines.append(f"[{area}] ❌ 易错 → 💡 {tip}")
        seen_areas.add(area)
        if len(lines) >= n:
            break
    return lines


def build_bedtime_review(today: date | None = None) -> str:
    today = today or date.today()
    d = _days_to_exam(today)
    tier = _tier(d)
    done, quota, pending = _today_review_gate(today)

    # 第1步：今日定额未完成 → 优先清错题（不扫全部历史到期）
    if pending:
        lines = [
            "🌙 睡前提醒",
            "",
            f"📚 今日错题复习进度: {done}/{quota} 已完成（还差 {len(pending)} 道定额）",
            "",
            "📝 待复习错题:",
        ]
        show = pending[:5]
        for i, row in enumerate(show, 1):
            lines.append(f"  {i}. #{row['id']} [{row['area']}]: {row['preview']}")
        if len(pending) > 5:
            lines.append(f"  ...还有 {len(pending) - 5} 道，发送「复习错题」逐一完成")
        lines.append("")
        lines.append("💡 睡前还有时间，先把今日定额清完再休息！")
        lines.append("💬 发「复习错题」开始清账")
        return "\n".join(lines)

    tracker = _load_tracker()
    exclude = _recent_pushed_ids(tracker, today, 3)
    pushed_ids: list[int] = []
    lines: list[str] = ["🌙 今日错题已全部复习完毕 ✅", ""]

    if tier == "green":
        picks = _pick_from_pool(KNOWLEDGE_POOL, 5, exclude)
        lines += ["🌙 睡前复习清单", "══════════════════════", "", "📚 今日知识点:"]
        for i, (pid, area, text) in enumerate(picks, 1):
            lines.append(f"  {i}. [{area}] {text}")
            pushed_ids.append(pid)
        recent = _recent_error_areas(today)
        lines.append("")
        lines.append("❌ 近期错题回顾:")
        if recent:
            for area, c in recent:
                lines.append(f"  · [{area}] — 近几日错 {c} 题")
        else:
            lines.append("  · 暂无近期新错题，保持手感")
        lines.append("")
        lines.append(_tomorrow_preview(today))
        lines.append("")
        lines.append(f"📅 距考试 {d} 天 · 🟢 广度优先档")
        lines.append("💤 睡前刷刷这几条，明天更进步！")

    elif tier == "yellow":
        weak = _weak_areas(3)
        picks = _pick_from_pool(KNOWLEDGE_POOL, 4, exclude, area_filter=weak or None)
        lines += ["🌙 睡前复习清单", "══════════════════════", "", "📚 今日知识点（聚焦弱项）:"]
        for i, (pid, area, text) in enumerate(picks, 1):
            lines.append(f"  {i}. [{area}] {text}")
            pushed_ids.append(pid)
        recent = _recent_error_areas(today)
        lines.append("")
        lines.append("❌ 近期错题回顾:")
        if recent:
            for area, c in recent:
                lines.append(f"  · [{area}] — 近几日错 {c} 题")
        else:
            lines.append("  · 暂无近期新错题")
        if weak:
            lines.append(f"🎯 当前弱项 Top: {' / '.join(weak)}")
        lines.append("")
        lines.append(_tomorrow_preview(today))
        lines.append("")
        lines.append(f"📅 距考试 {d} 天 · 🟡 聚焦弱项档")
        lines.append("💤 睡前刷刷这几条，明天更进步！")

    elif tier == "orange":
        ek = _error_knowledge_lines(today, 3)
        lines += ["🌙 睡前错题复习", "══════════════════", "", "📚 错题知识点回顾:"]
        if ek:
            for i, row in enumerate(ek, 1):
                lines.append(f"  {i}. {row}")
        else:
            picks = _pick_from_pool(KNOWLEDGE_POOL, 3, exclude)
            for i, (pid, area, text) in enumerate(picks, 1):
                lines.append(f"  {i}. [{area}] {text}")
                pushed_ids.append(pid)
        lines.append("")
        lines.append(_tomorrow_preview(today))
        lines.append("")
        lines.append(f"💤 距考试仅 {d} 天，查漏补缺最关键！")

    else:  # red
        picks = _pick_from_pool(MUST_KNOW, 2, exclude)
        lines += ["🌙 考前冲刺必考点", "══════════════════", "", "📚 今日必考点:"]
        for i, (pid, area, text) in enumerate(picks, 1):
            lines.append(f"  {i}. [{area}] {text}")
            pushed_ids.append(pid)
        quiz = random.choice(QUICK_QUIZ)
        lines += [
            "",
            "⚡ 快速自测:",
            quiz["stem"],
            f"A. {quiz['A']}  B. {quiz['B']}",
            f"C. {quiz['C']}  D. {quiz['D']}",
            "",
            f"（答完自查：正确答案 {quiz['answer']} — {quiz['tip']}）",
            "",
            _tomorrow_preview(today).replace("明日预告", "明天"),
            "",
            f"💤 距考试仅 {d} 天，加油！",
        ]

    # 持久化 tracker
    today_s = today.isoformat()
    hist = tracker.setdefault("history", {})
    hist[today_s] = pushed_ids
    tracker["last_pushed"] = today_s
    tracker["pushed_items"] = pushed_ids
    _save_tracker(tracker)

    return "\n".join(lines)


def is_bedtime_request(text: str) -> bool:
    t = text.strip().replace("\u200b", "").replace("\ufeff", "")
    t = t.rstrip("。！!？? \t")
    return t in TRIGGERS


def handle_message(text: str) -> str:
    if not is_bedtime_request(text):
        return (
            "⚠️ 未识别为睡前复习指令。\n"
            "💬 请发送「睡前复习」或「睡前回顾」"
        )
    return build_bedtime_review()


def main() -> None:
    parser = argparse.ArgumentParser(description="睡前复习推送")
    sub = parser.add_subparsers(dest="command")

    p_msg = sub.add_parser("message", help="解析微信消息")
    p_msg.add_argument("--text", required=True)
    p_msg.add_argument("--json", action="store_true")

    p_push = sub.add_parser("push", help="直接生成睡前清单")
    p_push.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "message":
        out = handle_message(args.text)
    elif args.command == "push":
        out = build_bedtime_review()
    else:
        parser.print_help()
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps({"status": "ok", "text": out}, ensure_ascii=False))
    else:
        print(out)


if __name__ == "__main__":
    main()
