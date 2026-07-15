"""
情绪触发模块 —— "打脸式鼓励"

当检测到用户输入情绪化关键词时：
1. 识别情绪类型（自我怀疑 / 沮丧 / 焦虑）
2. 检索三个月前写得最好的笔记
3. 生成"打脸式"鼓励回复
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Optional

from ..config import EMOTION_TRIGGERS
from ..db.vector_store import get_vector_store

logger = logging.getLogger(__name__)


class EmotionTrigger:
    """情绪检测 & 鼓励生成"""

    def __init__(self):
        self.store = get_vector_store()
        self._build_index()

    def _build_index(self):
        """构建关键词 → 情绪类型的反向索引"""
        self._keyword_map = {}
        for emotion_type, keywords in EMOTION_TRIGGERS.items():
            for kw in keywords:
                self._keyword_map[kw.lower()] = emotion_type

    # ── 公开方法 ─────────────────────────────────────────────

    def detect(self, text: str) -> Optional[str]:
        """检测文本是否包含情绪触发词，返回情绪类型或 None"""
        text_lower = text.lower()
        for keyword, emotion_type in self._keyword_map.items():
            if keyword in text_lower:
                return emotion_type
        return None

    def respond(self, user_input: str) -> str:
        """
        根据用户输入生成鼓励回复。
        如果检测到情绪触发，返回完整回复；否则返回空字符串。
        """
        emotion = self.detect(user_input)
        if not emotion:
            return ""

        # 获取三个月前的日期范围
        three_months_ago = datetime.now() - timedelta(days=90)
        start_date = (three_months_ago - timedelta(days=15)).strftime("%Y-%m-%d")
        end_date = (three_months_ago + timedelta(days=15)).strftime("%Y-%m-%d")

        # 搜索三个月前最好的笔记
        best_notes = self._find_best_notes(start_date, end_date)

        # 生成回复
        return self._build_response(emotion, best_notes, user_input)

    # ── 内部方法 ─────────────────────────────────────────────

    def _find_best_notes(self, start_date: str, end_date: str) -> list[dict]:
        """检索三个月前质量最高的笔记"""
        # 用"总结 重点 关键 考点 方法论"作为查询词，找到高质量笔记
        queries = [
            "PMP 重点总结 关键知识点",
            "项目管理 核心概念 方法论",
            "考试要点 易错点 解题技巧",
        ]

        all_results = []
        for query in queries:
            try:
                results = self.store.search_notes_by_date_range(
                    query=query,
                    start_date=start_date,
                    end_date=end_date,
                    n_results=5,
                )
                all_results.extend(results)
            except Exception as e:
                logger.debug("Search failed for query '%s': %s", query, e)

        if not all_results:
            # 放宽日期限制，直接搜索
            logger.info("No notes in 3-month range, searching all notes")
            for query in queries:
                try:
                    results = self.store.search_notes(query=query, n_results=5)
                    all_results.extend(results)
                except Exception:
                    pass

        # 去重 & 按质量排序（优先长笔记、有结构的笔记）
        seen = set()
        unique = []
        for r in all_results:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique.append(r)

        # 按字符数降序（长笔记通常质量更高）
        unique.sort(
            key=lambda x: len(x.get("document", "")),
            reverse=True,
        )
        return unique[:5]

    def _build_response(
        self,
        emotion: str,
        notes: list[dict],
        user_input: str,
    ) -> str:
        """构建鼓励回复"""
        parts = []

        # ── 开场白 ───────────────────────────────────────────
        openers = {
            "self_doubt": [
                "🤨 停。你说什么来着？",
                "📢 打住！让我帮你回忆一下。",
                "⛔ 等等——这话我可不能当没听见。",
            ],
            "frustration": [
                "😤 我知道你很烦，但先看看这个。",
                "🫂 累了就先停一下，但别否定自己。",
                "💪 来，深呼吸。然后看看这个。",
            ],
            "anxiety": [
                "😌 焦虑很正常——说明你在乎。但数据不会骗人。",
                "🧘 先放松。你知道三个月前的你有多强吗？",
                "📊 别信情绪，信证据。来看看。",
            ],
        }

        closer_emotion_map = {
            "self_doubt": [
                "\n💡 **所以——你不是蠢，你只是暂时忘了自己有多强。**",
                "\n🎯 **看到了吗？这些是你写的。你早就懂了。**",
                "\n⚡ **三个月前你能写出这些，现在的你只会更强。**",
            ],
            "frustration": [
                "\n🔄 **进度不是线性的。卡住 ≠ 退步。**",
                "\n🌱 **学习本来就是螺旋上升的。你今天卡住的地方，三个月前你连概念都不认识。**",
                "\n🔋 **休息一下，回来再看。你比你以为的走得远。**",
            ],
            "anxiety": [
                "\n📈 **你的笔记质量就是最好的证明——你已经掌握了核心知识。**",
                "\n🎯 **考试考的是理解，不是完美。你理解得很好了。**",
                "\n✨ **记住：PMP 考的是项目管理思维，你已经有了。**",
            ],
        }

        parts.append(random.choice(openers.get(emotion, openers["self_doubt"])))

        # ── 展示历史笔记 ─────────────────────────────────────
        if notes:
            parts.append(f"\n{'─' * 50}")
            parts.append("📝 **这是你三个月前写的笔记：**\n")

            # 找出日期信息
            for i, note in enumerate(notes[:2], 1):
                meta = note.get("metadata", {})
                date_str = meta.get("created_at", "某个时候")[:10]
                title = meta.get("title", "无标题")
                domain = meta.get("domain", "")
                domain_label = {
                    "people": "👥 人员",
                    "process": "⚙️ 过程",
                    "business_environment": "🏢 商业环境",
                }.get(domain, "")

                doc = note.get("document", "")
                # 截取前 300 字作为预览
                preview = doc[:300] + ("..." if len(doc) > 300 else "")

                parts.append(
                    f"### {domain_label} · {date_str} · {title}\n"
                    f"{preview}\n"
                )

            if len(notes) > 2:
                parts.append(f"_...还有 {len(notes) - 2} 条相关笔记_\n")
        else:
            parts.append("\n📭 （暂时没找到历史笔记——但这不代表你没进步！）")

        # ── 结尾 ─────────────────────────────────────────────
        parts.append(random.choice(closer_emotion_map.get(emotion, closer_emotion_map["self_doubt"])))

        # ── 行动建议 ─────────────────────────────────────────
        if emotion == "self_doubt":
            parts.append("\n🎯 **建议**：用 `analyze` 看看你的模考数据，让数据说话。")
        elif emotion == "frustration":
            parts.append("\n🎯 **建议**：试试 `plan` 命令，换个弱项针对性复习。")
        elif emotion == "anxiety":
            parts.append("\n🎯 **建议**：用 `stats` 看看你的复习数据，心里有数就不慌了。")

        return "\n".join(parts)
