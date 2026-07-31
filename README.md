# 🦉 PMP Athena — 本地 PMP 备考复盘 Agent

完全本地运行的 PMP 备考助手：**向量知识库 + 每日一练/模考判卷 + 错题 SM-2 复习 + 微信硬路由**。基于 ChromaDB + sentence-transformers，无需 LLM API Key 即可完成核心刷题流程。

**考试目标**：2026-09-12 PMP | 日常训练正确率目标 70%（126/180）

---

## ✨ 核心能力

| 模块 | 说明 | 入口 |
|------|------|------|
| 📚 **向量知识库** | 导入 `.md` / `.pdf` 笔记，语义检索 | `python -m pmp_athena.cli ingest` |
| 📝 **每日一练** | 解析培训机构 PDF，互动出题 / 批量对账 / 判卷 | `daily_practice.py` |
| 📱 **App 批量刷题** | 一次发多题 + 答案串 → 收录 → 补录解析后判卷入库 | `daily_practice.py batch` |
| ❌ **错题本 + SM-2** | 三文件同步（`error_log` / `error_review_state` / `question_bank`） | `error_logger.py` / `spaced_repetition.py` |
| 🎯 **学习顾问** | 薄弱点诊断、今日错题复习、备考计划 | `study_advisor.py` |
| 📊 **模考** | PDF 模考 / 状态持久化 / 成绩写入 / 趋势分析 | `mock_exam_state.py` / `exam_recorder.py` |
| 🖼️ **截图 OCR** | 题目截图、模考成绩、章节练习统计图识别入库 | `image_processor.py` |
| 💬 **微信桥接** | 硬路由绕过 LLM，直接调 Python CLI | [wechat-claude-code](https://github.com/Wechat-ggGitHub/wechat-claude-code) + `athena-router.ts` |

---

## 🚀 快速开始

### 1. 环境

```bash
# Python 3.10+ 推荐
pip install -r requirements.txt

# PDF 解析（每日一练 / 模考）
pip install pdfplumber

# 截图 OCR（可选）
pip install pytesseract Pillow
# Windows Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
```

首次 `ingest` 会从 HuggingFace 下载 embedding 模型（约 470MB），之后可离线使用。

### 2. 目录约定

```
pmp-athena/
├── pmp_athena/          # Python 核心代码
├── pmp_notes/           # 笔记 + 做题数据（部分不上传 Git）
│   ├── *.md             # 学习笔记
│   ├── 每日一练/        # 培训机构 PDF（题目 + 答案解析）
│   ├── 模考/            # 模考 PDF
│   ├── config.json      # 每日一练完成日期等
│   ├── question_bank.json
│   ├── error_log.json
│   └── error_review_state.json
├── data/                # ChromaDB 持久化（不上传 Git）
├── CLAUDE.md            # Agent 行为规则（微信 / Cursor 共用）
├── restart_bridge.ps1   # 重启微信桥接（Windows）
└── docs/                # 桥接补丁说明
```

### 3. 导入笔记

```bash
python -m pmp_athena.cli ingest
python -m pmp_athena.cli stats      # 查看向量库统计
```

### 4. 常用 CLI

```bash
# ── 每日一练 ──
python pmp_athena/daily_practice.py menu              # 未完成日期菜单
python pmp_athena/daily_practice.py start --date 2026-07-31
python pmp_athena/daily_practice.py grade ACCAB...    # 判卷（需先 start）
python pmp_athena/daily_practice.py audit-content     # PDF 解析质量审计

# ── App 批量刷题（培训机构 App 复制题）──
python pmp_athena/daily_practice.py batch --stdin     #  stdin 粘贴「多题 + 我的答案是：CCCAB」
python pmp_athena/daily_practice.py batch --stdin --key CCCAB   # 有标准答案时一步判卷
python pmp_athena/daily_practice.py batch-update 41 --correct-answer C --explanation "..."

# ── 学习顾问 ──
python pmp_athena/study_advisor.py weakness           # 薄弱点分析
python pmp_athena/study_advisor.py review-today       # 今日到期错题
python pmp_athena/study_advisor.py plan --days 14     # 备考计划

# ── 错题 / 题库 ──
python pmp_athena/error_logger.py stats
python pmp_athena/question_bank.py stats
python pmp_athena/record_answer.py wrong --question "..." --my-answer B --correct-answer C ...

# ── 模考状态 ──
python pmp_athena/mock_exam_state.py status
python pmp_athena/exam_recorder.py stats
```

Windows 下若使用 Miniconda，可将上述 `python` 换成本机路径（如 `d:\miniconda\python.exe`）。

---

## 📱 App 批量刷题（两阶段）

适用于从刷题 App **复制多道题 + 选项**，暂不掌握官方解析的场景。

**阶段 1 — 收录**（微信发长文，或 CLI `--stdin`）：

```
41.题干……
A. … B. … C. … D. …
42.题干……
…
我的答案是：CCCAB
```

→ 写入 `question_bank.json`，记录你的作答，**待补标准答案**。

**阶段 2 — 补录解析**：

```
更新43题，正确答案是 B，解析：WBS 将可交付成果逐层分解
```

→ 自动判卷；错题同步 `error_log` + `error_review_state`（SM-2 队列）。

题号映射保存在 `pmp_notes/batch_practice_state.json`（本地，不上传 Git）。

演示脚本：

```bash
python pmp_athena/demo_batch_q41_45.py
```

---

## 💬 微信接入

配合 [wechat-claude-code](https://github.com/Wechat-ggGitHub/wechat-claude-code)，在 `athena-router.ts` 中硬路由以下指令（**不经过 LLM**）：

| 用户说法 | Python 命令 |
|----------|-------------|
| 每日一练 / 7月31 / 随机每日一练 | `daily_practice.py` |
| 多题 + `我的答案是：XXX` | `daily_practice.py batch --stdin` |
| 更新41题，正确答案是 B | `daily_practice.py batch-update-text` |
| 复习错题 / 薄弱点 / 学习计划 | `study_advisor.py` |
| 录入错题（截图） | `image_processor.py` + `record_answer.py` |

### 配置要点

`~/.wechat-claude-code/config.json`（示例）：

```json
{
  "workingDirectory": "D:/pmp-athena",
  "pythonBin": "D:/miniconda/python.exe",
  "systemPrompt": "见仓库 system_prompt.txt / CLAUDE.md"
}
```

### 重启桥接（Windows）

修改 `athena-router.ts` 或 Python 后：

```powershell
.\restart_bridge.ps1
```

脚本会：停止旧进程 → `npm run build`（桥接目录）→ 启动单实例守护。

图片 OCR 集成见 [docs/wechat-bridge-patch.md](docs/wechat-bridge-patch.md)。

---

## 🗂️ 数据文件说明

| 文件 | 用途 |
|------|------|
| `question_bank.json` | 全部做题记录（每日一练 / 模考 / App 批量 / 截图） |
| `error_log.json` | 错题本（按题干去重） |
| `error_review_state.json` | SM-2 间隔复习状态 |
| `exam_records.json` | 完整模考历史 |
| `config.json` | `daily_completed` 等配置 |
| `daily_practice_state.json` | 进行中的每日一练会话 |
| `mock_exam_state.json` | 进行中的模考进度 |
| `batch_practice_state.json` | App 批量题号 → 题库 ID 映射 |

**入库规则**：错题必须 `error_logger.py add` → `question_bank.py add --error-log-id N` 两步同步；推荐使用 `record_answer.py` 统一封装。

---

## 🏗️ 项目结构

```
pmp_athena/
├── cli.py                    # 主 CLI：ingest / plan / analyze / stats
├── config.py                 # 路径、领域权重
├── daily_practice.py         # 每日一练 PDF 解析、判卷、batch 子命令
├── batch_practice.py         # App 批量刷题解析与两阶段入库
├── question_bank.py          # 题库 CRUD
├── error_logger.py           # 错题本
├── record_answer.py          # 做对/做错统一入库（三文件同步）
├── spaced_repetition.py      # SM-2 间隔复习
├── study_advisor.py          # 薄弱点 / 复习 / 计划
├── mock_exam_state.py        # 模考断点续做
├── exam_recorder.py          # 模考记录
├── sprint_planner.py         # 冲刺计划
├── image_processor.py        # 截图压缩 + OCR + 结构化入库
├── analyze_exam.py           # 模考成绩截图分析
├── practice_summary.py       # 刷题汇总（月度等）
├── chapter_practice_recorder.py
├── error_insights.py         # 高频错题解读
├── db/vector_store.py        # ChromaDB
├── ingestion/                # md / pdf / ocr 导入
├── modules/                    # 情绪触发、通过率、日计划
└── utils/                      # embedding、题干规范化
```

### 测试

```bash
# 运行全部单元测试
python -m unittest discover -s tests -t . -v

# 单个模块
python tests/test_daily_practice_parser.py   # PDF 解析回归
python tests/test_batch_practice.py          # 批量刷题解析
python pmp_athena/daily_practice.py audit-content # 全部每日一练 PDF 内容审计
```

---

## 📋 模考记录格式（exam_records.json）

```json
{
  "exams": [
    {
      "exam_id": "模考卷二",
      "exam_date": "2026-07-28",
      "status": "completed",
      "total_questions": 180,
      "correct_count": 117,
      "correct_rate": 0.65,
      "scores": {
        "people": 0.72,
        "process": 0.65,
        "business_environment": 0.75
      },
      "weak_areas": ["质量管理", "干系人管理"]
    }
  ]
}
```

也可发模考截图 +「分析模考」，由 `analyze_exam.py` 自动 OCR 写入。

---

## 🔒 隐私与 Git

- 所有做题数据、向量库 **仅存本地**
- `.gitignore` 已排除 `data/`、`question_bank.json`、`error_log.json` 等个人数据
- 微信 Token 在 `~/.wechat-claude-code/`，不在本仓库

---

## 🛠️ 技术栈

| 组件 | 技术 |
|------|------|
| 向量库 | ChromaDB（本地持久化） |
| Embedding | paraphrase-multilingual-MiniLM-L12-v2 |
| OCR | Tesseract + pytesseract |
| PDF | pdfplumber |
| 间隔复习 | SM-2（`spaced_repetition.py`） |
| 终端 UI | Rich |
| 微信桥接 | wechat-claude-code（Node.js + 硬路由） |

---

## 📄 License

MIT
