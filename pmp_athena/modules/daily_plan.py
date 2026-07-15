"""
每日推送模块 —— 自动生成复习计划

基于：
1. 最近一次模考的薄弱领域
2. 向量检索找到最相关的笔记
3. 组合成每日复习计划
"""

import logging
from datetime import datetime
from typing import Optional

from ..config import PMP_DOMAINS, DAILY_PLAN_NOTES_COUNT, DAILY_PLAN_WEAK_DOMAINS_COUNT
from ..db.vector_store import get_vector_store

logger = logging.getLogger(__name__)


class DailyPlanGenerator:
    """每日复习计划生成器"""

    def __init__(self):
        self.store = get_vector_store()

    # ── 公开方法 ─────────────────────────────────────────────

    def generate(self, custom_focus: str | None = None) -> str:
        """
        生成当日复习计划。

        Args:
            custom_focus: 可选的自定义复习重点描述
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # 确定薄弱领域
        weak_domains = self._get_weak_domains()

        # 检索推荐笔记
        recommended_notes = self._retrieve_recommendations(
            weak_domains=weak_domains,
            custom_focus=custom_focus,
        )

        # 生成计划
        return self._build_plan(
            date=today,
            weak_domains=weak_domains,
            notes=recommended_notes,
            custom_focus=custom_focus,
        )

    def get_quick_review(self) -> str:
        """快速回顾卡片——精简版每日推送"""
        weak_domains = self._get_weak_domains()
        notes = self._retrieve_recommendations(
            weak_domains=weak_domains,
            n_results=3,
        )
        return self._build_quick_card(weak_domains, notes)

    # ── 内部方法 ─────────────────────────────────────────────

    def _get_weak_domains(self) -> list[dict]:
        """从最新模考获取薄弱领域"""
        latest = self.store.get_latest_exam()

        if latest is None:
            # 无模考数据 → 返回所有领域
            return [
                {"key": k, "name": v["name_cn"], "weight": v["weight"]}
                for k, v in PMP_DOMAINS.items()
            ]

        meta = latest.get("metadata", {})
        weak = []
        for domain_key, domain_info in PMP_DOMAINS.items():
            score_key = f"score_{domain_key}"
            score = float(meta.get(score_key, 0))

            weak.append({
                "key": domain_key,
                "name": domain_info["name_cn"],
                "weight": domain_info["weight"],
                "score": score,
                "gap": max(0, 0.63 - score),
            })

        # 按 gap × weight 排序（ROI 最大的优先）
        weak.sort(key=lambda x: x["gap"] * x["weight"], reverse=True)
        return weak[:DAILY_PLAN_WEAK_DOMAINS_COUNT]

    def _retrieve_recommendations(
        self,
        weak_domains: list[dict],
        custom_focus: str | None = None,
        n_results: int | None = None,
    ) -> list[dict]:
        """检索推荐的笔记"""
        if n_results is None:
            n_results = DAILY_PLAN_NOTES_COUNT

        all_notes = []
        seen_ids = set()

        # 为每个薄弱领域搜索笔记
        for wd in weak_domains:
            domain_name = wd["name"]
            queries = self._build_search_queries(domain_name)
            for query in queries:
                try:
                    results = self.store.search_notes(
                        query=query,
                        n_results=3,
                        where={"domain": wd["key"]},
                    )
                except Exception:
                    # 如果 metadata filter 不支持，退化为全局搜索
                    results = self.store.search_notes(
                        query=query,
                        n_results=3,
                    )

                for r in results:
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        r["target_domain"] = wd["name"]
                        all_notes.append(r)

        # 如果有自定义焦点
        if custom_focus:
            custom_results = self.store.search_notes(
                query=custom_focus,
                n_results=3,
            )
            for r in custom_results:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    r["target_domain"] = "自定义重点"
                    all_notes.append(r)

        # 按相关度排序，取 top N
        all_notes.sort(key=lambda x: x.get("distance", 1))
        return all_notes[:n_results]

    def _build_search_queries(self, domain_name: str) -> list[str]:
        """为领域构建搜索查询"""
        query_map = {
            "人员": [
                "团队管理 冲突解决 干系人沟通",
                "领导力 激励理论 团队建设",
                "情商 虚拟团队 教练辅导",
            ],
            "过程": [
                "挣值管理 关键路径 进度控制",
                "风险管理 变更控制 质量管理",
                "采购管理 合同类型 WBS",
            ],
            "商业环境": [
                "商业论证 收益管理 合规",
                "组织变革 战略对齐 PESTLE",
            ],
        }
        return query_map.get(domain_name, [f"{domain_name} 重点知识点"])

    def _build_plan(
        self,
        date: str,
        weak_domains: list[dict],
        notes: list[dict],
        custom_focus: str | None = None,
    ) -> str:
        """构建完整的每日复习计划"""
        lines = []

        # 头
        weekday = self._get_weekday_cn(date)
        lines.append("╔══════════════════════════════════════╗")
        lines.append(f"║  📅 {date} {weekday} 复习计划        ║")
        lines.append("╚══════════════════════════════════════╝")
        lines.append("")

        # 薄弱领域概览
        lines.append("## 🎯 今日重点领域\n")
        for i, wd in enumerate(weak_domains, 1):
            score_str = f"（最近得分 {wd['score']:.0%}）" if wd.get("score") else ""
            priority = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
            lines.append(f"{priority} **{wd['name']}** {score_str}— 权重 {wd['weight']:.0%}")

        # 自定义焦点
        if custom_focus:
            lines.append(f"\n🎯 自定义重点：**{custom_focus}**")

        # 推荐笔记
        lines.append(f"\n## 📝 今日推荐笔记（共 {len(notes)} 篇）\n")
        if not notes:
            lines.append(
                "📭 暂无匹配笔记。请先运行 `ingest` 导入你的 PMP 笔记。\n"
                "把笔记 .md 文件放到 `pmp_notes/` 目录下即可。"
            )
        else:
            for i, note in enumerate(notes, 1):
                meta = note.get("metadata", {})
                title = meta.get("title", "无标题")
                source = meta.get("source_file", "")
                domain_tag = meta.get("domain", note.get("target_domain", ""))
                date_str = meta.get("created_at", "")[:10]
                char_count = meta.get("char_count", 0)

                doc = note.get("document", "")
                preview = doc[:150] + ("..." if len(doc) > 150 else "")

                lines.append(f"### {i}. {title}")
                lines.append(f"📂 {source} · 📅 {date_str} · 📏 {char_count} 字")
                if domain_tag:
                    domain_label = {
                        "people": "👥 人员",
                        "process": "⚙️ 过程",
                        "business_environment": "🏢 商业环境",
                    }.get(domain_tag, domain_tag)
                    lines.append(f"🏷️ {domain_label}")
                lines.append(f"> {preview}")
                lines.append("")

        # 今日学习建议
        lines.append("## ✅ 今日任务清单\n")
        lines.append("1. 📖 逐一阅读上方推荐笔记（预计 30-45 分钟）")
        lines.append("2. ✍️ 每读完一篇，用自己的话总结 3 个关键点")
        lines.append("3. ❓ 完成对应领域的 20 道练习题")
        lines.append("4. 📊 记录错题，标记不确定的选项")
        lines.append("5. 🔄 睡前 15 分钟回顾今日笔记的核心概念")

        # 一句鼓励
        encouragements = [
            "💪 PMP 不是考记忆力，是考思维方式——你已经走在正确的路上了。",
            "🎯 每一步都很重要。今天的复习就是明天考场上的一道题。",
            "📈 持续学习的力量远超临时抱佛脚。保持节奏！",
            "🌟 项目管理是一门手艺——每一个概念的理解都让你成为更好的 PM。",
            "⚡ 不要追求完美，追求进步。每天进步 1%，100 天后是 2.7 倍。",
        ]
        import random
        lines.append(f"\n> {random.choice(encouragements)}")

        return "\n".join(lines)

    def _build_quick_card(
        self,
        weak_domains: list[dict],
        notes: list[dict],
    ) -> str:
        """快速回顾卡片"""
        lines = []
        lines.append("─" * 40)
        lines.append("📋 **快速回顾卡片**")
        lines.append("")

        if weak_domains:
            lines.append("🎯 薄弱领域：")
            for wd in weak_domains:
                lines.append(f"  • {wd['name']}（权重 {wd['weight']:.0%}）")

        if notes:
            lines.append("\n📝 核心笔记：")
            for note in notes[:3]:
                title = note.get("metadata", {}).get("title", "无标题")
                lines.append(f"  • {title}")

        lines.append("\n─" * 40)
        return "\n".join(lines)

    @staticmethod
    def _get_weekday_cn(date_str: str) -> str:
        """获取中文星期"""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            return days[dt.weekday()]
        except Exception:
            return ""
