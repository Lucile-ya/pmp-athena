# 🦉 PMP Athena — 本地 PMP 备考复盘 Agent

![PMP备考](https://img.shields.io/badge/领域-PMP备考-blue)
![开源免费](https://img.shields.io/badge/开源-MIT-brightgreen)
![Python](https://img.shields.io/badge/Python-3.10+-yellow)
![AI助手](https://img.shields.io/badge/支持-Claude_Code_|_Cursor_|_WorkBuddy-purple)
![微信桥接](https://img.shields.io/badge/扩展-微信远程刷题-orange)
![版本](https://img.shields.io/badge/版本-v1.1.0-red)

> **不同于传统题库只提供「答案 + 解析」，PMP Athena 更关注：为什么错？考什么？下次怎么避免？**
>
> 把零散的刷题变成：做题 → 判卷 → 错因诊断 → 间隔复习 → 能力画像 → 考前冲刺，建立属于自己的 PMP 备考系统。
>
> 完全本地运行，**不需要 API Key**，做题数据只存你的电脑。基于 ChromaDB + sentence-transformers + SM-2 间隔复习算法。

**考试目标**：2026-09-12 PMP | 训练目标正确率 70%（126/180）

---

## ✨ 核心能力

| 模块 | 说明 | 入口 |
|------|------|------|
| 🧠 **知识领域引擎** | 13 领域结构化知识（定义/49过程/工具/输出/易错点） | `knowledge_domain_engine.py` |
| 📖 **动态知识查询** | L1(框架速查) / L2(全领域展开) / L3(情景套路) / 关联(邻接矩阵) | `dynamic_knowledge.py` |
| 📚 **向量知识库** | 导入 `.md` / `.pdf` 笔记，语义检索 | `python -m pmp_athena.cli ingest` |
| 📝 **每日一练** | 解析培训机构 PDF，互动出题 / 批量对账 / 判卷 | `daily_practice.py` |
| 📱 **App 批量刷题** | 一次发多题 + 答案串 → 收录 → 补录解析后判卷入库 | `daily_practice.py batch` |
| ❌ **错题本 + SM-2** | 三文件同步（`error_log` / `error_review_state` / `question_bank`） | `error_logger.py` / `spaced_repetition.py` |
| 🎯 **PMP 判题推理框架** | 六步推理链 + P1-P6 优先级 + 12 陷阱模式 | `CLAUDE.md` |
| 🎯 **学习顾问** | 薄弱点诊断、今日错题复习、备考计划 | `study_advisor.py` |
| 📊 **模考** | PDF 模考 / 状态持久化 / 成绩写入 / 时间·速度·精度三维诊断 | `mock_exam_state.py` / `exam_recorder.py` |
| 🖼️ **截图 OCR** | 题目截图、模考成绩、章节练习统计图识别入库 | `image_processor.py` |
| 🗺️ **思维导图结构化** | PNG 思维导图 OCR → PMBOK 标准表格 MD | `mindmap_ocr.py` / `build_mindmap_md.py` |
| 💬 **微信桥接** | 硬路由绕过 LLM，25+ 指令直接调 Python CLI | [wechat-claude-code](https://github.com/Wechat-ggGitHub/wechat-claude-code) + `athena-router.ts` |

---

## 💬 典型对话

接上 Claude Code / Cursor / WorkBuddy 后，直接用自然语言：

| 用户说 | Athena 做什么 |
|--------|--------------|
| `复习错题` | SM-2 排期 + 逐题出题 + 判卷 + 错因诊断 |
| `薄弱点分析` | 各领域正确率 + 错误类型分布 + 针对性建议 |
| `挣值知识点` | L1 速查（5 行精华）+ 可追问 L2/L3 |
| `7月31日每日一练答案：CBCBDCDDC` | 自动判卷 + 错题三文件同步入库 |
| `做 8月10日 每日一练` | 逐题互动出题，边做边判 |
| `开始模考一` | 180 题完整模考，时间·速度·精度三维诊断 |
| `随机每日一练` | 从 34 套 PDF 随机抽 10 题 |
| `睡前复习` | D-Day 自适应知识点推送 + 错题回顾 + 明日预告 |
| `分析趋势` | 模考趋势 + 通过概率预测 |
| `帮我生成 14 天冲刺计划` | 按薄弱领域定制每日任务 |

> 💡 **不用 AI 也能用**：`python cli_chat.py` 一行命令启动菜单式命令行工具，纯键盘操作。

---

## 🧠 知识领域引擎 · 分层查询

### 架构

```
用户查询 "资源管理知识点"
  │
  ├─ L1 (速查)  → 13 领域引擎 → 核心定义 + 过程框架 + 高频考点 + 关联领域
  ├─ L2 (详细)  → 全领域 PMBOK 49 过程展开 + 工具/技术 + 易错点
  ├─ L3 (套路)  → 领域映射过滤 36 种套路 → 只返回相关情景题套路
  └─ 关联        → 子模块 + PMBOK 邻接矩阵（强度柱 + 原因）
```

### L1 速查示例

```markdown
📚 资源管理 · 速查

📖 资源管理是识别、获取和管理所需资源以成功完成项目的各个过程。

🎯 核心目标：确保项目在正确的时间有正确的人力和物力资源。

📋 核心过程：
  9.1 规划资源管理（规划）→ 资源管理计划、团队章程
  9.2 估算活动资源（规划）→ 资源需求、估算依据
  9.3 获取资源（执行）→ 物质资源分配单、项目团队派工单
  9.4 建设团队（执行）→ 团队绩效评价
  9.5 管理团队（执行）→ 变更请求、更新的项目管理计划
  9.6 控制资源（监控）→ 工作绩效信息

⭐ 考试高频：冲突解决策略选择 / RACI 矩阵 / Tuckman 模型 / 仆人式领导

🔗 关联领域：沟通管理 / 领导力/人员 / 干系人管理

💡 回复「详细」看全领域工具与技术 | 「套路」看情景题套路 | 「关联」看相邻领域
```

### L2 详细示例

全领域 PMBOK 过程展开，按五大过程组组织，含工具/技术、输出、关键概念、易错点。

```markdown
📖 资源管理 · 详解

◆ 规划过程组
  9.1 规划资源管理
  主要输出：资源管理计划、团队章程
  关键工具：RACI 矩阵、组织图、文本型岗位描述
  ...
◆ 执行过程组
  9.3 获取资源 → 谈判、预分派、虚拟团队、多标准决策分析
  9.4 建设团队 → 团队建设活动、培训、集中办公、认可与奖励
  9.5 管理团队 → 冲突管理、情商、影响力、领导力
  ...

⚠️ 常见易错点：冲突解决优先选合作/解决问题；不要跳过震荡期直接到规范
```

### 三十六种套路 ↔ 知识领域映射

| 知识领域 | 关联套路编号 |
|----------|-------------|
| 资源管理 | #9 冲突管理 / #10 团队组建 / #11 干系人需求 / #27 启动大会 |
| 风险管理 | #14 风险情景 / #15 EMV / #32 风险工具 |
| 干系人管理 | #17-20 相关方情景 |
| 整合管理 | #1 章程 / #4-6 变更 / #21 问题处理 / #24 参考文件 |

### 查询方式

```bash
# 微信 / CLI 通用
python retrieve_knowledge.py query 资源管理 --level L1
python retrieve_knowledge.py query 资源管理 --level L2
python retrieve_knowledge.py query 资源管理 --level L3
python retrieve_knowledge.py message --text "详细 挣值"
python retrieve_knowledge.py message --text "套路 沟通管理"
```

---

## 🎯 PMP 判题推理框架

所有判卷场景统一使用**六步推理链 + P1-P6 优先级 + 12 陷阱模式**：

### 六步推理链

```
Step 1: 项目类型 → Predictive / Agile / Hybrid
Step 2: 项目阶段 → Initiating / Planning / Executing / Monitoring / Closing
Step 3: ECO 领域 → People / Process / Business Environment
Step 4: 问题类型 → 变更 / 风险 / Issue / 干系人 / 质量 / 资源 / 采购 / 整合
Step 5: 问法意图 → First / Next / Best / Most Appropriate / Should
Step 6: 优先级仲裁 → P1-P6 逐层过滤
```

### P1-P6 优先级

```
P1  Analysis Before Action      先分析，再行动
P2  Collaborate Before Escalate 先协作沟通，再升级
P3  Follow Process Before Changing 先走流程，再变更
P4  Root Cause Before Solution  先找根因，再解决
P5  Preventive Before Corrective 预防优于纠正
P6  Team Participation          团队参与优于 PM 独断
```

### 12 陷阱模式 (T01-T12)

| ID | 陷阱 | ID | 陷阱 |
|----|------|----|------|
| T01 | 过早行动（未分析即执行） | T07 | Risk/Issue 混淆 |
| T02 | 过早升级（第一步找高管） | T08 | 过度反应 |
| T03 | 绕过流程（跳过 CCB/CR） | T09 | 反应不足 |
| T04 | First 选 Best（流程顺序错） | T10 | 敏捷过度文档 |
| T05 | 绝对化（always/never） | T11 | 预测型文档不足 |
| T06 | 角色越权（SM 定优先级） | T12 | 镀金/范围蔓延 |

### 判卷输出格式

```
❌ Q3 [干系人管理]: 你的答案 B → 正确答案 C
   决策链: 预测型 · 启动 · People · 干系人 · First
   B 触犯 T11（文档不足），C 符合 P2（先协作沟通再登记）
```

*Credit: 推理框架借鉴 [liedern/pmp-ai-coach-skill](https://github.com/liedern/pmp-ai-coach-skill) 的设计思想。*

---

## 📋 输出示例

**每日一练判卷**：
```
📋 7月31日每日一练 对账结果（7/10 正确）

❌ Q3 [风险管理]: 你的答案 B → 正确答案 C
   🏷️ 错误类型: 流程顺序错
   决策链: 预测型 · 执行阶段 · Process · 风险 · First
   B 触犯 T02（过早升级），C 符合 P1（先分析再行动）
```

**薄弱点分析**：
```
📊 薄弱点诊断报告

🎯 薄弱领域 TOP 3
| 领域 | 错误率 | 错/总 | 风险 |
| 范围管理 | 77% | 23/36 | 🔴 高危 |
| 成本管理 | 70% | 19/32 | 🔴 高危 |

📊 错误类型分布
| 概念混淆 | 12 道 | 概念记反了 |
| 流程顺序错 | 9 道 | 步骤顺序不对 |
| 陷阱误导 | 6 道 | 被干扰项骗了 |

💡 针对性建议
1. 优先攻克 范围管理：每天专项练习 10 题
2. 概念混淆偏多：建议用对比表格梳理相似概念
```

**知识点速查**：
```
📚 挣值管理 (EVM) 核心公式 · 速查

1. SV = EV - PV（进度偏差）| SV > 0 = 进度超前
2. CV = EV - AC（成本偏差）| CV > 0 = 成本节约
3. SPI = EV / PV | CPI = EV / AC
⭐ 高频考点：SPI < 1 & CPI > 1 的组合判断

💡 回复「详细」看完整公式表格 | 「套路」看情景题套路
```

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
├── pmp_athena/              # Python 核心代码
├── tests/                   # 单元测试（unittest discover）
├── pmp_notes/               # 笔记 + 做题数据（大部分不上传 Git）
│   ├── *.md                 # 结构化学习笔记（思维导图 × 13 份）
│   ├── 每日一练/            # 培训机构 PDF（本地，*.pdf 已 gitignore）
│   ├── 模考/                # 模考 PDF（本地）
│   ├── config.json          # 每日一练完成日期（本地）
│   ├── question_bank.json
│   ├── error_log.json
│   └── error_review_state.json
├── data/                    # ChromaDB 持久化（不上传 Git）
├── pmp_knowledge_index.json # 知识点索引（可重建）
├── CLAUDE.md                # Agent 行为规则 + 判题推理框架（微信 / Cursor 共用）
├── restart_bridge.ps1       # 重启微信桥接
├── bridge_guard.ps1         # 桥接自动守护脚本（防锁屏断连）
├── start_bridge.bat         # 手动启动桥接
└── docs/                    # 桥接补丁说明
```

### 3. 导入笔记

```bash
python -m pmp_athena.cli ingest
python -m pmp_athena.cli stats      # 查看向量库统计
python build_knowledge_index.py     # 重建知识点索引
```

### 4. 常用 CLI

```bash
# ── 知识查询（L1/L2/L3）──
python retrieve_knowledge.py query 资源管理 --level L1
python retrieve_knowledge.py query 挣值 --level L2
python retrieve_knowledge.py message --text "详细 风险管理"
python retrieve_knowledge.py message --text "套路 干系人管理"

# ── 每日一练 ──
python pmp_athena/daily_practice.py menu              # 未完成日期菜单
python pmp_athena/daily_practice.py progress          # 扫描文件夹，完成/未完成进度
python pmp_athena/daily_practice.py week-check        # 本周工作日完成情况
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

> 💡 **第一次用？** 看 [QUICKSTART.md](QUICKSTART.md) — 从零到第一次对话，5 分钟上手。<br>
> ❓ **遇到问题？** 查 [docs/FAQ.md](docs/FAQ.md) — 环境安装 / 微信桥接 / PDF 乱码 / Windows 坑 / OCR 等 25+ 常见问题。

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
| 资源管理知识点 / 挣值 / 敏捷速查 | `dynamic_knowledge.py` (L1/L2/L3) |

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

### 桥接自动守护（防锁屏断连）

Windows Modern Standby（锁屏）会切断用户态 TCP 连接，导致桥接长轮询断开。`bridge_guard.ps1` + Windows 计划任务实现自动恢复：

```powershell
# 一次性配置计划任务（每 5 分钟检测，桥接死了自动拉起）
schtasks /Create `
  /TN "PMP-Athena-Bridge" `
  /SC MINUTE /MO 5 `
  /TR 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:\pmp-athena\bridge_guard.ps1"' `
  /IT /F
```

| 文件 | 用途 |
|------|------|
| `bridge_guard.ps1` | 检测桥接存活 → 清了残留锁 → `npm build` → 启动（计划任务直接调 PowerShell，零窗口） |
| `bridge_guard.log` | 只记录拉起操作（桥接正常时静默，不写日志） |
| `monitor_bridge.ps1` | 持续监控（30s 循环），Claude Monitor 后台运行 |

**工作原理**：

```
三层防护：
  Monitor(30s) → 计划任务(5min) → bridge_guard.ps1
  ├─ 桥接活着 → exit 0（静默）
  └─ 桥接死了 → 清 bridge.pid → tsc 编译 → 启动 → 写 log
```

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
| `knowledge_query_state.json` | 知识点追问上下文（L1→L2→L3 状态跟踪） |
| `knowledge_mastery.json` | 各领域掌握度分数 + 趋势 |
| `prep_push_queue.json` | 备考推送队列（本地） |

**入库规则**：错题必须 `error_logger.py add` → `question_bank.py add --error-log-id N` 两步同步；推荐使用 `record_answer.py` 统一封装。

---

## 🏗️ 项目结构

```
pmp_athena/                       # 核心业务代码
├── knowledge_domain_engine.py    # [新] 13 领域结构化引擎（定义/过程/工具/输出/映射）
├── dynamic_knowledge.py          # [重构] L1/L2/L3 动态知识检索
├── build_mindmap_md.py           # [新] PNG 思维导图 → 结构化 MD 表格
├── mindmap_ocr.py                # [新] 批量 OCR 工具
├── cli.py                        # 主 CLI：ingest / plan / analyze / stats
├── daily_practice.py             # 每日一练 PDF 解析、判卷、batch 子命令
├── batch_practice.py             # App 批量刷题解析与两阶段入库
├── question_bank.py              # 题库 CRUD
├── error_logger.py               # 错题本
├── record_answer.py              # 做对/做错统一入库（三文件同步）
├── spaced_repetition.py          # SM-2 间隔复习
├── study_advisor.py              # 薄弱点 / 复习 / 计划
├── mock_exam_state.py            # 模考断点续做
├── exam_recorder.py              # 模考记录
├── practice_overview.py          # 刷题总览（含时间线）
├── practice_summary.py           # 月度 / 备考汇总
├── prep_analytics.py             # 周月总结、错题专项计划
├── prep_push.py                  # 备考推送队列
├── pre_exam_analysis.py          # 考前深度分析
├── knowledge_retriever.py        # 向量库领域速查
├── knowledge_fuzzy_match.py      # 知识点模糊匹配（别名/同义词/多级打分）
├── knowledge_pdf_search.py       # PDF 深度检索（优先章节索引）
├── knowledge_error_linkage.py    # 错题联动（知识点→历史错题）
├── analyze_exam.py               # 模考成绩截图 OCR 入库
├── image_processor.py            # 截图压缩 + OCR + 结构化入库
├── sprint_planner.py             # 冲刺计划
├── chapter_practice_recorder.py  # 章节练习统计入库
├── error_insights.py             # 高频错题解读
├── root_cause_engine.py          # 错题根因分析引擎
├── db/vector_store.py            # ChromaDB
├── db/knowledge_base.py          # 知识库管理
├── ingestion/                    # md / pdf / ocr 导入
└── utils/                        # embedding、题干规范化

tests/                            # 单元测试（unittest discover）
```

### pmp_notes/ 结构化笔记（13 份）

| 文件 | 内容 |
|------|------|
| `1.1_项目的基本要素.md` | 项目定义、生命周期、5 大过程组、商业文件 |
| `1.2_项目运行环境.md` | EEF/OPA、组织结构对比、PMO 类型 |
| `1.3_项目经理角色.md` | 能力三角、领导力 vs 管理、核心技能 |
| `2.1_项目的启动.md` | 章程、商业文件、干系人识别、kick-off |
| `2.2_项目规划(上).md` | **范围/进度/成本** — WBS、CPM、EVM 公式、储备分析 |
| `2.2_项目规划(下).md` | **质量/资源/沟通/风险/采购/干系人** — 6 领域完整表格 |
| `2.3_项目执行.md` | 10 个执行过程、知识管理、关键决策点 |
| `2.4_项目监控.md` | 12 个监控过程、变更控制流程 |
| `2.5_项目收尾.md` | 收尾检查清单、合同收尾 vs 行政收尾 |
| `3_敏捷.md` | Scrum 三角色/五事件、估算、12 原则 |
| `了解23个常用模型.md` | Tuckman→蒙特卡洛→帕累托→PDCA |
| `了解60个方法.md` | 数据收集→分析→决策→人际技能 |
| `了解76个工件.md` | 规划文档→基准→登记册→绩效文档 |

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

**仓库只发布功能和题目资料，不发布任何个人数据：**

| 数据 | 是否上传 Git | 说明 |
|------|-------------|------|
| 代码 & 规则文件 | ✅ 是 | `pmp_athena/`、`CLAUDE.md` |
| 培训机构 PDF | ✅ 是 | 42 份每日一练 + 模考，克隆即可用 |
| 做题记录 | ❌ 否 | `question_bank.json`、`error_log.json` 等 |
| 模考成绩 | ❌ 否 | `exam_records.json` |
| 向量数据库 | ❌ 否 | `data/`（每台机器自己生成） |
| 微信 Token | ❌ 否 | `~/.wechat-claude-code/`，不在本仓库 |

> 💡 **克隆仓库不会带入任何作者的错题、成绩或学习记录。** 你的做题数据从第一次使用开始自动生成，互不干扰。

### 设计原则

- **可维护**：知识/流程/数据分离，CLI + AI 双通道
- **可移植**：`pmp_notes/*.json` 数据文件不绑定代码，换电脑直接复制
- **可扩展**：模块化 Python 包，新增领域或题型只需加文件
- **隐私优先**：所有个人数据默认不入 Git，`.gitignore` 预设完整

---

## 🛠️ 技术栈

| 组件 | 技术 |
|------|------|
| 向量库 | ChromaDB（本地持久化） |
| Embedding | paraphrase-multilingual-MiniLM-L12-v2 |
| OCR | Tesseract + pytesseract |
| PDF | pdfplumber + pypdf |
| 间隔复习 | SM-2（`spaced_repetition.py`） |
| 终端 UI | Rich |
| 微信桥接 | wechat-claude-code（Node.js + 硬路由） |
| 知识索引 | 本地 JSON（`pmp_knowledge_index.json`，113 条） |
| 判题推理 | 六步推理链 + P1-P6 优先级 + T01-T12 陷阱模式 |

---

## 📄 License

MIT
