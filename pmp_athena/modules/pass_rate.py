"""
通过率分析模块

基于模考各领域得分，估算当前通过概率，指出薄弱知识域，
并给出针对性提升建议。
"""

import logging
import math
from typing import Optional

from ..config import PMP_DOMAINS, PASS_THRESHOLD
from ..db.vector_store import get_vector_store

logger = logging.getLogger(__name__)


class PassRateAnalyzer:
    """PMP 通过率分析器"""

    def __init__(self):
        self.store = get_vector_store()

    # ── 公开方法 ─────────────────────────────────────────────

    def analyze(
        self,
        scores: dict[str, float] | None = None,
    ) -> str:
        """
        分析通过概率。

        Args:
            scores: {"people": 0.72, "process": 0.65, "business_environment": 0.75}
                    如果为 None，则使用最新模考记录
        """
        if scores is None:
            latest = self.store.get_latest_exam()
            if latest is None:
                return self._no_data_message()
            scores = self._extract_scores(latest)

        return self._build_report(scores)

    def analyze_latest(self) -> str:
        """分析最近一次模考"""
        return self.analyze(scores=None)

    def analyze_trend(self) -> str:
        """分析成绩趋势"""
        exams = self.store.get_all_exams()
        if len(exams) < 2:
            return (
                "📊 **成绩趋势分析**\n\n"
                "需要至少 2 次模考记录才能分析趋势。\n"
                f"当前记录数：{len(exams)}\n\n"
                "使用 `exam add` 命令添加模考记录。"
            )

        return self._build_trend_report(exams)

    # ── 核心计算 ─────────────────────────────────────────────

    def calculate_pass_probability(
        self, scores: dict[str, float]
    ) -> dict:
        """
        计算通过概率。

        使用加权总分 + 方差修正模型：
        1. 加权总分 = Σ(领域得分 × 权重)
        2. 通过概率基于加权总分与通过线的差距估算
        3. 领域得分方差越大 → 风险越高 → 概率微调下调
        """
        weighted_total = 0.0
        domain_details = {}

        for domain_key, domain_info in PMP_DOMAINS.items():
            score = scores.get(domain_key, 0.0)
            weight = domain_info["weight"]
            contribution = score * weight
            weighted_total += contribution

            domain_details[domain_key] = {
                "name": domain_info["name_cn"],
                "score": score,
                "weight": weight,
                "contribution": contribution,
                "is_weak": score < PASS_THRESHOLD,
                "gap": max(0, PASS_THRESHOLD - score),
            }

        # 标准差（领域间不平衡程度）
        score_values = [scores.get(k, 0) for k in PMP_DOMAINS]
        mean_score = sum(score_values) / len(score_values)
        variance = sum((s - mean_score) ** 2 for s in score_values) / len(score_values)
        std_dev = math.sqrt(variance)

        # 基于通过线距离估算概率
        gap = weighted_total - PASS_THRESHOLD
        # 使用 sigmoid 函数将 gap 映射到概率
        # gap=0 → ~50%, gap=0.1 → ~73%, gap=0.2 → ~88%, gap=-0.1 → ~27%
        prob = 1.0 / (1.0 + math.exp(-gap * 15))

        # 方差惩罚：领域间差异越大 → 风险越高
        variance_penalty = std_dev * 0.3
        prob_adjusted = max(0.0, min(1.0, prob - variance_penalty))

        # 薄弱领域
        weak_domains = sorted(
            [
                d
                for d in domain_details.values()
                if d["is_weak"]
            ],
            key=lambda x: x["gap"],
            reverse=True,
        )

        return {
            "weighted_total": weighted_total,
            "pass_threshold": PASS_THRESHOLD,
            "gap": gap,
            "raw_probability": prob,
            "std_dev": std_dev,
            "variance_penalty": variance_penalty,
            "adjusted_probability": prob_adjusted,
            "domain_details": domain_details,
            "weak_domains": weak_domains,
        }

    # ── 报告生成 ─────────────────────────────────────────────

    def _build_report(self, scores: dict[str, float]) -> str:
        analysis = self.calculate_pass_probability(scores)
        dd = analysis["domain_details"]
        prob_pct = analysis["adjusted_probability"] * 100

        lines = []
        lines.append("╔══════════════════════════════════════╗")
        lines.append("║     📊 PMP 通过率分析报告           ║")
        lines.append("╚══════════════════════════════════════╝")
        lines.append("")

        # ── 总体评估 ─────────────────────────────────────────
        lines.append("## 📈 总体评估\n")
        lines.append(f"加权总分：**{analysis['weighted_total']:.1%}**（通过线 {PASS_THRESHOLD:.0%}）")
        lines.append(f"估算通过概率：**{prob_pct:.1f}%**")

        if prob_pct >= 85:
            lines.append("🟢 状态：**稳了！**保持节奏即可。")
        elif prob_pct >= 70:
            lines.append("🟡 状态：**有希望**——强化薄弱环节可进一步提升。")
        elif prob_pct >= 55:
            lines.append("🟠 状态：**需要加把劲**——建议集中攻克薄弱领域。")
        else:
            lines.append("🔴 状态：**危险区**——需要系统性补强。")

        lines.append(f"\n领域间标准差：{analysis['std_dev']:.3f}（越低越均衡）")

        # ── 各领域得分 ───────────────────────────────────────
        lines.append("\n## 🎯 各领域得分\n")
        lines.append(f"| 领域 | 权重 | 得分 | 贡献 | 状态 |")
        lines.append(f"|------|------|------|------|------|")

        sorted_domains = sorted(
            dd.items(),
            key=lambda x: x[1]["score"],
        )
        for key, detail in sorted_domains:
            status = "✅" if not detail["is_weak"] else "⚠️"
            lines.append(
                f"| {detail['name']} | {detail['weight']:.0%} "
                f"| {detail['score']:.0%} "
                f"| {detail['contribution']:.1%} "
                f"| {status} |"
            )

        # ── 薄弱领域分析 ─────────────────────────────────────
        if analysis["weak_domains"]:
            lines.append("\n## ⚠️ 薄弱领域详情\n")
            for wd in analysis["weak_domains"]:
                gap_pct = wd["gap"] * 100
                lines.append(f"### {wd['name']}")
                lines.append(f"- 当前得分：{wd['score']:.0%}")
                lines.append(f"- 距通过线差：{gap_pct:.0f} 个百分点")
                lines.append(f"- 权重：{wd['weight']:.0%}（权重越高越需要优先攻克）")
                lines.append(f"- 提升建议：{self._get_domain_advice(wd['name'])}")
                lines.append("")

        # ── 提分策略 ─────────────────────────────────────────
        lines.append("## 💡 提分策略\n")

        # 按 ROI 排序：gap × weight 最大的优先
        roi_sorted = sorted(
            analysis["weak_domains"],
            key=lambda x: x["gap"] * x["weight"],
            reverse=True,
        )
        for i, wd in enumerate(roi_sorted[:2], 1):
            lines.append(
                f"{i}. **优先攻克 {wd['name']}**——每提升1个百分点，"
                f"加权总分增加 {wd['weight']*100:.1f} 个百分点"
            )

        lines.append(f"\n🎯 **建议下一步**：输入 `plan` 生成针对薄弱领域的复习计划。")

        return "\n".join(lines)

    def _build_trend_report(self, exams: list[dict]) -> str:
        """生成成绩趋势报告"""
        lines = []
        lines.append("╔══════════════════════════════════════╗")
        lines.append("║     📈 PMP 成绩趋势分析             ║")
        lines.append("╚══════════════════════════════════════╝")
        lines.append("")

        # 提取每次考试的数据
        trend_data = []
        for exam in exams:
            meta = exam["metadata"]
            date = meta.get("exam_date", "未知")[:10]
            scores = self._extract_scores(exam)
            analysis = self.calculate_pass_probability(scores)
            trend_data.append({
                "date": date,
                "weighted_total": analysis["weighted_total"],
                "prob": analysis["adjusted_probability"],
                "scores": scores,
                "weak": [wd["name"] for wd in analysis["weak_domains"]],
            })

        lines.append("| 日期 | 加权总分 | 通过概率 | 薄弱领域 |")
        lines.append("|------|----------|----------|----------|")

        for t in trend_data:
            prob_str = f"{t['prob']*100:.0f}%"
            weak_str = ", ".join(t["weak"]) if t["weak"] else "无"
            lines.append(f"| {t['date']} | {t['weighted_total']:.1%} | {prob_str} | {weak_str} |")

        # 趋势判断
        if len(trend_data) >= 2:
            first = trend_data[-1]["weighted_total"]
            last = trend_data[0]["weighted_total"]
            delta = last - first
            if delta > 0.03:
                lines.append(f"\n📈 **趋势：上升**（+{delta:.1%}）——继续保持！")
            elif delta < -0.03:
                lines.append(f"\n📉 **趋势：下降**（{delta:.1%}）——需要调整复习策略。")
            else:
                lines.append(f"\n📊 **趋势：持平**——需要突破瓶颈。")

        return "\n".join(lines)

    def _no_data_message(self) -> str:
        return (
            "📭 **暂无模考数据**\n\n"
            "请先添加模考记录。你可以：\n"
            "1. 使用 `exam add` 手动输入成绩\n"
            "2. 在 pmp_notes/ 下放置模考 JSON 文件后运行 `ingest`\n\n"
            "模考 JSON 格式示例："
            """
```json
{
    "exam_date": "2025-01-15",
    "total_questions": 180,
    "scores": {
        "people": 0.72,
        "process": 0.65,
        "business_environment": 0.75
    }
}
```"""
        )

    # ── 工具方法 ─────────────────────────────────────────────

    def _extract_scores(self, exam_record: dict) -> dict[str, float]:
        """从 exam record 中提取领域得分"""
        meta = exam_record.get("metadata", {})
        scores = {}
        for domain in PMP_DOMAINS:
            key = f"score_{domain}"
            if key in meta:
                scores[domain] = float(meta[key])
        return scores

    def _get_domain_advice(self, domain_name: str) -> str:
        """根据领域给出具体建议"""
        advice_map = {
            "人员": "建议重点复习：冲突解决策略、团队发展阶段（Tuckman模型）、"
            "激励理论（Maslow/Herzberg/McGregor）、情商与领导风格、"
            "虚拟团队管理、干系人参与矩阵。",
            "过程": "建议重点复习：挣值管理（EVM）、关键路径法（CPM）、"
            "风险应对策略、变更控制流程、质量管理工具（鱼骨图/帕累托图/控制图）、"
            "采购合同类型（FFP/CPFF/T&M）。",
            "商业环境": "建议重点复习：商业论证（Business Case）、"
            "收益管理计划、合规要求、组织变革管理、"
            "项目与战略对齐、PESTLE 分析。",
        }
        return advice_map.get(domain_name, "建议针对性复习该领域的核心概念和工具技术。")
