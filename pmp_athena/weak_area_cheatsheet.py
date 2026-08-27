#!/usr/bin/env python3
"""
薄弱点速记推送 — 微信硬路由入口。

从 pmp_notes/薄弱点速记/ 读取 MD，输出微信一屏可读的背诵版。

触发词:
  薄弱点速记 / 薄弱速记 / 速记清单
  今日速记
  速记 <领域> / <领域>速记  例: 速记 商业环境、成本速记

CLI:
  python pmp_athena/weak_area_cheatsheet.py message --text "今日速记"
  python pmp_athena/weak_area_cheatsheet.py push --area 成本管理
  python pmp_athena/weak_area_cheatsheet.py today
  python pmp_athena/weak_area_cheatsheet.py menu
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from pmp_athena.config import NOTES_DIR, QUESTION_BANK_PATH
    from pmp_athena.knowledge_retriever import normalize_area
except ModuleNotFoundError:
    from config import NOTES_DIR, QUESTION_BANK_PATH
    from knowledge_retriever import normalize_area

CHEATSHEET_DIR = NOTES_DIR / "薄弱点速记"
WECHAT_MAX_CHARS = 3800

# 标准领域 → MD 文件名
DOMAIN_FILES: dict[str, str] = {
    "商业环境": "01-商业环境.md",
    "成本管理": "02-成本管理.md",
    "敏捷/混合方法": "03-敏捷混合方法.md",
    "质量管理": "04-质量管理.md",
    "进度管理": "05-进度管理.md",
    "资源管理": "06-资源管理.md",
    "干系人管理": "07-干系人管理.md",
    "整合管理": "08-整合管理.md",
    "范围管理": "09-范围管理.md",
}

# 展示顺序（与 README 优先级一致）
DOMAIN_ORDER = list(DOMAIN_FILES.keys())

_MENU_TRIGGERS = frozenset({
    "薄弱点速记", "薄弱速记", "速记菜单", "速记清单", "速记列表",
})
_TODAY_TRIGGERS = frozenset({"今日速记", "今天速记", "每日速记"})


def _load_bank() -> list[dict]:
    try:
        data = json.loads(QUESTION_BANK_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def get_weak_areas(min_judged: int = 2) -> list[tuple[str, float, int, int]]:
    """返回 [(领域, 错误率, 错题数, 总题数), ...] 按错误率降序。"""
    stats: dict[str, dict[str, int]] = {}
    for r in _load_bank():
        area = r.get("knowledge_area") or "未分类"
        if area not in stats:
            stats[area] = {"total": 0, "correct": 0, "wrong": 0}
        stats[area]["total"] += 1
        if r.get("is_correct") is True:
            stats[area]["correct"] += 1
        elif r.get("is_correct") is False:
            stats[area]["wrong"] += 1

    out: list[tuple[str, float, int, int]] = []
    for area, s in stats.items():
        judged = s["correct"] + s["wrong"]
        if judged >= min_judged:
            rate = s["wrong"] / judged
            out.append((area, rate, s["wrong"], s["total"]))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def _resolve_cheatsheet_area(raw: str) -> str | None:
    """映射到速记 MD 的标准领域名。"""
    area = normalize_area(raw)
    if area and area in DOMAIN_FILES:
        return area
    # 敏捷别名
    if area == "敏捷/混合方法":
        return "敏捷/混合方法"
    t = (raw or "").strip()
    for domain in DOMAIN_ORDER:
        if domain in t or t in domain:
            return domain
    return None


def parse_cheatsheet_request(text: str) -> tuple[str, str | None]:
    """
    解析用户消息。
    返回 (action, area): action = menu|today|list|push|None
    """
    t = (text or "").strip().replace("\u200b", "").replace("\ufeff", "")
    if not t:
        return ("none", None)

    if t in _MENU_TRIGGERS:
        return ("menu", None)
    if t in _TODAY_TRIGGERS:
        return ("today", None)

    for pat in (
        re.compile(r"^速记\s*(.+)$"),
        re.compile(r"^(.+?)速记$"),
        re.compile(r"^薄弱点速记\s*(.+)$"),
    ):
        m = pat.match(t)
        if m:
            sub = m.group(1).strip()
            if not sub or sub in ("清单", "列表", "菜单"):
                return ("menu", None)
            area = _resolve_cheatsheet_area(sub)
            if area:
                return ("push", area)
            return ("unknown_area", sub)

    return ("none", None)


def is_cheatsheet_request(text: str) -> bool:
    action, _ = parse_cheatsheet_request(text)
    return action != "none"


def _read_md(filename: str) -> str:
    path = CHEATSHEET_DIR / filename
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _extract_blockquote_mnemonic(content: str) -> str:
    for raw in content.splitlines():
        line = raw.lstrip("> ").strip()
        if "总口诀" in line:
            m = re.search(r"总口诀[：:]\s*\*\*([^*]+)\*\*", line)
            if m:
                text = m.group(1).strip()
                if text != "总口诀":
                    return text
    return ""


def _extract_section(content: str, *headers: str) -> str:
    """提取 ## 标题 到下一个 ## 之间的内容。"""
    for header in headers:
        pattern = re.compile(
            rf"^##\s*{re.escape(header)}\s*$",
            re.MULTILINE,
        )
        m = pattern.search(content)
        if not m:
            continue
        start = m.end()
        rest = content[start:]
        nxt = re.search(r"^##\s", rest, re.MULTILINE)
        block = rest[: nxt.start()] if nxt else rest
        return block.strip()
    return ""


def _trim_for_wechat(text: str, limit: int = WECHAT_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n\n…（内容较长，发「速记 完整 X」在 Cursor 看全文）"


def format_wechat_push(area: str, *, full: bool = False) -> str:
    """将 MD 速记转为微信推送格式。"""
    filename = DOMAIN_FILES.get(area)
    if not filename:
        return f"⚠️ 暂无「{area}」速记文件。"

    content = _read_md(filename)
    if not content:
        return f"⚠️ 速记文件不存在: {filename}"

    if full:
        return _trim_for_wechat(content, 6000)

    mnemonic = _extract_blockquote_mnemonic(content)
    traps = _extract_section(content, "八、易错陷阱", "七、易错陷阱", "十、易错陷阱")
    flash = _extract_section(content, "🃏 闪卡")
    chain = _extract_section(
        content,
        "九、做题决策链",
        "八、做题决策链",
        "十一、做题决策链",
    )
    high_freq = _extract_section(
        content,
        "七、高频考点",
        "六、高频考点",
        "九、高频考点",
    )

    # 用户错误率
    weak = get_weak_areas()
    rate_line = ""
    for a, rate, wrong, total in weak:
        if a == area or (area == "敏捷/混合方法" and "敏捷" in a):
            rate_line = f"你的错误率 **{rate:.0%}**（{wrong}/{total}）"
            break

    lines = [
        f"📌 **{area} · 薄弱点速记**",
        "",
    ]
    if rate_line:
        lines.append(f"📊 {rate_line}")
    if mnemonic:
        lines.append(f"💡 总口诀：**{mnemonic}**")
    lines.append("")

    if high_freq:
        lines.append("⭐ **高频考点**")
        for line in high_freq.splitlines()[:6]:
            if line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "-")):
                lines.append(line.strip())
        lines.append("")

    if traps:
        lines.append("⚠️ **易错陷阱**")
        for line in traps.splitlines():
            if "|" in line and "❌" not in line and "---" not in line:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 2 and parts[0] not in ("❌ 错", "错"):
                    lines.append(f"  · {parts[0]} → {parts[1]}")
        lines.append("")

    if flash:
        lines.append("🃏 **闪卡自测**")
        for line in flash.splitlines():
            if line.strip().startswith("|") and "问" not in line and "---" not in line:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) == 2:
                    lines.append(f"  Q: {parts[0]}")
                    lines.append(f"  A: {parts[1]}")
        lines.append("")

    if chain:
        chain_text = re.sub(r"```", "", chain.strip())
        lines.append("🔗 **做题链**")
        for cl in chain_text.splitlines()[:12]:
            s = cl.rstrip()
            if s and not s.startswith("---"):
                lines.append(f"  {s}")
        lines.append("")

    lines.append(f"💬 发「专项 {area}」刷 10 题 | 「速记清单」看全部领域")
    return _trim_for_wechat("\n".join(lines))


def push_menu() -> str:
    """速记入口菜单。"""
    weak = get_weak_areas()
    weak_map = {a: (rate, w, t) for a, rate, w, t in weak}

    lines = [
        "📌 **薄弱点速记**",
        "",
        "根据你的做题数据，优先攻这些：",
        "",
    ]
    for i, area in enumerate(DOMAIN_ORDER[:5], 1):
        fname = DOMAIN_FILES[area]
        mnemonic = _extract_blockquote_mnemonic(_read_md(fname))
        info = weak_map.get(area)
        if info:
            rate, _, _ = info
            tag = "🔴" if rate >= 0.6 else "🟡"
            lines.append(f"{tag} {i}. **{area}**（错误率 {rate:.0%}）")
        else:
            lines.append(f"   {i}. **{area}**")
        if mnemonic:
            lines.append(f"   💡 {mnemonic}")
        lines.append("")

    lines.extend([
        "📖 **用法**",
        "  发「今日速记」→ 自动推今天该背的领域",
        "  发「速记 成本管理」→ 指定领域",
        "  发「速记清单」→ 本菜单",
        "",
        "📁 完整版在 Cursor: pmp_notes/薄弱点速记/",
    ])
    return "\n".join(lines)


def push_today() -> str:
    """按薄弱优先级 + 日期轮换，推送今日速记。"""
    weak = get_weak_areas()
    # 可推送的领域（有 MD 文件）
    candidates: list[str] = []
    seen: set[str] = set()
    for area, _, _, _ in weak:
        mapped = _resolve_cheatsheet_area(area)
        if mapped and mapped not in seen:
            candidates.append(mapped)
            seen.add(mapped)
    for area in DOMAIN_ORDER:
        if area not in seen:
            candidates.append(area)

    if not candidates:
        return push_menu()

    idx = date.today().toordinal() % len(candidates)
    area = candidates[idx]

    header = [
        f"🌅 **今日速记 · {date.today().strftime('%m月%d日')}**",
        f"📍 今日推荐：**{area}**（薄弱点轮换 {idx + 1}/{len(candidates)}）",
        "",
    ]
    body = format_wechat_push(area)
    return "\n".join(header) + body


def push_list() -> str:
    return push_menu()


def handle_message(text: str) -> str:
    action, area = parse_cheatsheet_request(text)

    if action == "menu" or action == "list":
        return push_menu()
    if action == "today":
        return push_today()
    if action == "push" and area:
        return format_wechat_push(area)
    if action == "unknown_area":
        return (
            f"⚠️ 未找到「{area}」速记。\n"
            f"支持：{' / '.join(DOMAIN_ORDER)}\n"
            "💡 发「速记清单」查看全部"
        )
    return push_menu()


def main() -> None:
    parser = argparse.ArgumentParser(description="薄弱点速记微信推送")
    sub = parser.add_subparsers(dest="command")

    p_msg = sub.add_parser("message", help="解析微信消息")
    p_msg.add_argument("--text", required=True)
    p_msg.add_argument("--json", action="store_true")

    p_push = sub.add_parser("push", help="推送指定领域")
    p_push.add_argument("--area", required=True)

    sub.add_parser("today", help="今日速记")
    sub.add_parser("menu", help="速记菜单")

    args = parser.parse_args()

    if args.command == "message":
        out = handle_message(args.text)
    elif args.command == "push":
        resolved = _resolve_cheatsheet_area(args.area)
        out = format_wechat_push(resolved) if resolved else f"⚠️ 未知领域: {args.area}"
    elif args.command == "today":
        out = push_today()
    elif args.command == "menu":
        out = push_menu()
    else:
        parser.print_help()
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps({"text": out}, ensure_ascii=False))
    else:
        print(out)


if __name__ == "__main__":
    main()
