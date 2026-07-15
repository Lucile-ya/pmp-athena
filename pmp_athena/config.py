"""
全局配置
"""

import os
from pathlib import Path

# ── 项目根目录 ──────────────────────────────────────────────
PROJECT_ROOT = Path(os.environ.get("PMP_ATHENA_ROOT", Path(__file__).parent.parent))

# ── 数据目录 ────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "data"
CHROMA_PERSIST_DIR = str(DATA_DIR / "chromadb")

# ── 笔记目录 ────────────────────────────────────────────────
NOTES_DIR = PROJECT_ROOT / "pmp_notes"

# ── Embedding 模型 ──────────────────────────────────────────
# 使用多语言模型，中英文混合场景表现好
EMBEDDING_MODEL = os.environ.get(
    "PMP_EMBEDDING_MODEL",
    "paraphrase-multilingual-MiniLM-L12-v2",
)

# ── ChromaDB 集合名称 ───────────────────────────────────────
COLLECTION_NOTES = "pmp_notes"
COLLECTION_SCREENSHOTS = "pmp_screenshots"
COLLECTION_EXAMS = "pmp_exams"

# ── PMP 考试领域 & 权重 ─────────────────────────────────────
PMP_DOMAINS = {
    "people": {
        "name_cn": "人员",
        "name_en": "People",
        "weight": 0.42,
        "tasks": [
            "管理冲突",
            "领导团队",
            "支持团队绩效",
            "赋能团队成员和干系人",
            "确保团队成员/干系人充分培训",
            "建设团队",
            "解决和消除障碍、 impediments 和 blockers",
            "谈判项目协议",
            "与干系人协作",
            "建立共识",
            "参与和组织虚拟团队",
            "定义团队基本规则",
            "辅导相关干系人",
            "运用情商提升团队绩效",
        ],
    },
    "process": {
        "name_cn": "过程",
        "name_en": "Process",
        "weight": 0.50,
        "tasks": [
            "以交付商业价值所需的紧迫性执行项目",
            "管理沟通",
            "评估和管理风险",
            "让干系人参与",
            "规划并管理预算和资源",
            "规划和管理进度计划",
            "规划和管理产品/可交付成果的质量",
            "规划和管理范围",
            "整合项目规划活动",
            "管理项目变更",
            "规划和管理采购",
            "管理项目工件",
            "确定适当的项目方法论/方法和实践",
            "制定项目治理结构",
            "管理项目问题",
            "确保知识转移以实现项目连续性",
            "规划和管理项目/阶段的收尾或移交",
        ],
    },
    "business_environment": {
        "name_cn": "商业环境",
        "name_en": "Business Environment",
        "weight": 0.08,
        "tasks": [
            "规划和管理项目合规性",
            "评估和交付项目利益与价值",
            "评估和应对外部商业环境变化对范围的影响",
            "为组织变革提供支持",
        ],
    },
}

# ── 通过分数线估算 ──────────────────────────────────────────
# PMI 不公开具体分数线，业界估算在 61%-65% 左右
PASS_THRESHOLD = float(os.environ.get("PMP_PASS_THRESHOLD", "0.63"))

# ── 情绪触发关键词 ──────────────────────────────────────────
EMOTION_TRIGGERS = {
    "self_doubt": [
        "我好蠢", "我好笨", "我学不会", "我记不住",
        "太难了", "我不行", "我废了", "没救了",
        "考不过", "放弃了", "崩溃", "心态炸了",
        "I'm so dumb", "I can't do this", "I'll never pass",
        "this is hopeless", "I'm failing",
    ],
    "frustration": [
        "烦死了", "好累", "不想学了", "学不动了",
        "没进展", "又错了", "又是错的",
        "so frustrated", "exhausted", "stuck",
    ],
    "anxiety": [
        "好焦虑", "好紧张", "睡不着", "怕考不过",
        "时间不够", "来不及了",
        "so anxious", "nervous", "worried",
    ],
}

# ── 每日推送配置 ────────────────────────────────────────────
DAILY_PLAN_NOTES_COUNT = 5  # 每天推荐的笔记数量
DAILY_PLAN_WEAK_DOMAINS_COUNT = 2  # 聚焦最薄弱的几个领域
