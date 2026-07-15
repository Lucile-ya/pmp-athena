# 🦉 PMP Athena — 本地 PMP 备考复盘 Agent

一个完全本地运行的 PMP 备考助手，基于 ChromaDB + sentence-transformers，无需任何 API Key。

## ✨ 核心功能

| 模块 | 功能 |
|------|------|
| 📝 **向量知识库** | 自动导入 .md / .pdf 笔记，语义检索 |
| 🔥 **情绪触发** | 检测焦虑/沮丧关键词 → 检索三个月前最佳笔记 → "打脸式"鼓励 |
| 📊 **通过率分析** | 输入模考各领域得分 → 计算通过概率、定位薄弱领域、给出提升建议 |
| 📅 **每日推送** | 基于薄弱环节自动生成今日复习计划 |
| 🖼️ **图片 OCR** | 微信收到的截图自动压缩 + OCR 提取文字（需配 wechat-claude-code） |
| 💬 **CLI 对话** | 终端内直接对话、检索笔记、执行命令 |

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt

# PDF 支持
pip install PyPDF2 pdfplumber

# 图片 OCR（可选）
pip install pytesseract Pillow
# 并安装 Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki
```

### 2. 放入你的笔记

```
pmp_notes/
├── 2025-01-10-知识领域总结.md
├── 错题记录.md
├── 模考成绩.json       # 格式见下方
├── PMBOK讲义.pdf
└── 截图错题.png
```

### 3. 一键导入

```bash
python -m pmp_athena.cli ingest
```

首次运行会自动从 HuggingFace 下载 embedding 模型（约 470MB），之后完全离线。

### 4. 开始对话

```bash
python -m pmp_athena.cli          # 交互模式
python -m pmp_athena.cli plan     # 生成复习计划
python -m pmp_athena.cli analyze  # 分析通过率
python -m pmp_athena.cli stats    # 查看数据统计
```

### 5. 接入微信（可选）

配合 [wechat-claude-code](https://github.com/Wechat-ggGitHub/wechat-claude-code) 可将 PMP Athena 接入微信：

```bash
# 1. 安装微信桥接
npx skills add Wechat-ggGitHub/wechat-claude-code

# 2. 配置工作目录为 PMP Athena
# 编辑 ~/.wechat-claude-code/config.json，添加：
#   "workingDirectory": "D:/pmp-athena",
#   "systemPrompt": "你是 PMP Athena..."

# 3. 扫码绑定
cd ~/.claude/skills/wechat-claude-code && node dist/main.js setup

# 4. 启动守护进程
node dist/main.js start
```

**图片预处理增强**（可选）：将 `pmp_athena/image_processor.py` 集成到微信桥接中，使微信收到的图片自动压缩到 1500px + OCR 提取文字。详见 [wechat-bridge-patch.md](docs/wechat-bridge-patch.md)。

## 📋 模考 JSON 格式

```json
{
  "exams": [
    {
      "exam_date": "2025-04-01",
      "total_questions": 180,
      "scores": {
        "people": 0.72,
        "process": 0.65,
        "business_environment": 0.75
      }
    }
  ]
}
```

## 🏗️ 项目结构

```
pmp-athena/
├── pmp_athena/
│   ├── cli.py               # 命令行交互界面
│   ├── config.py            # 全局配置（领域权重、阈值等）
│   ├── image_processor.py   # 图片压缩 + OCR（独立工具）
│   ├── db/
│   │   └── vector_store.py  # ChromaDB 向量库封装
│   ├── ingestion/
│   │   ├── markdown_loader.py  # .md 笔记导入
│   │   ├── pdf_loader.py       # .pdf 笔记导入
│   │   ├── ocr_processor.py    # 截图 OCR
│   │   └── mock_exam_loader.py # 模考记录导入
│   ├── modules/
│   │   ├── emotion_trigger.py  # 情绪检测 + 鼓励生成
│   │   ├── pass_rate.py        # 通过率分析
│   │   └── daily_plan.py       # 每日复习计划
│   └── utils/
│       └── embedding.py     # sentence-transformers 封装
├── pmp_notes/               # 📁 你的笔记（不上传 Git）
├── data/                    # 📁 ChromaDB 持久化（不上传 Git）
├── requirements.txt
└── README.md
```

## 🔒 隐私说明

- **所有数据本地存储**，不上传云端
- ChromaDB 向量库存储在 `./data/` 目录
- Embedding 模型使用开源 sentence-transformers，无需 API Key
- 接入微信时，微信账号 Token 存储在 `~/.wechat-claude-code/`（项目代码不涉及）
- `pmp_notes/` 和 `data/` 已加入 `.gitignore`，不会误上传 GitHub

## 🛠️ 技术栈

| 组件 | 技术 |
|------|------|
| 向量数据库 | ChromaDB (本地持久化) |
| Embedding | paraphrase-multilingual-MiniLM-L12-v2 |
| OCR | Tesseract + pytesseract |
| PDF 解析 | pdfplumber / PyPDF2 |
| 终端 UI | Rich |
| 微信桥接 | wechat-claude-code (Node.js) |

## 📄 License

MIT
