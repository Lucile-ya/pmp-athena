# 🦉 PMP Athena · 新手快速上手

> 写给克隆了仓库但不知道从哪开始的朋友。

## 这是个啥？

PMP 备考刷题工具，帮你做三件事：

1. **判卷对答案** — 培训机构 PDF 每日一练/模考，自动逐题比对，错题自动记录
2. **SM-2 错题复习** — 科学间隔复习算法，到期自动提醒，薄弱领域一目了然
3. **知识速查** — 13 个 PMP 知识领域结构化检索，L1 速查 / L2 详解 / L3 套路

**不需要 API Key，全部本地运行。**

---

## 环境准备

你只需要两样东西：

- **Python 3.10+**（必须）
- **pip**（必须）

装好 Python 后打开终端，进入仓库目录：

```bash
cd pmp-athena

# 安装依赖（3 个核心包 + 2 个 PDF 包，很简单）
pip install -r requirements.txt

# 导入笔记、建向量库（首次会下载一个 470MB 的 embedding 模型，之后离线可用）
python -m pmp_athena.cli ingest

# 建知识点索引
python build_knowledge_index.py
```

验证一下能不能用：

```bash
python retrieve_knowledge.py query 挣值 --level L1
```

如果能输出挣值管理的知识点，就说明环境 OK 了。

---

## 三种用法，从简到繁

### 🥉 Level 1：纯命令行（最简单，不需要任何额外东西）

所有功能通过终端命令调用。核心命令一览：

```bash
# ── 知识速查 ──
python retrieve_knowledge.py query 风险管理 --level L1    # L1 = 速查（5-7 行精华）
python retrieve_knowledge.py query 风险管理 --level L2    # L2 = 完整章节 + 公式
python retrieve_knowledge.py query 风险管理 --level L3    # L3 = 情景套路

# ── 录入错题（做完题后手动记录）──
python pmp_athena/record_answer.py wrong \
  --question "题干内容..." \
  --my-answer B \
  --correct-answer C \
  --knowledge-area "风险管理" \
  --explanation "P1：先分析再行动" \
  --source manual

# ── 录入做对的题 ──
python pmp_athena/record_answer.py correct \
  --question "题干内容..." \
  --my-answer A \
  --correct-answer A \
  --knowledge-area "范围管理" \
  --source manual

# ── 查看薄弱领域 ──
python pmp_athena/study_advisor.py weakness

# ── 查看今日待复习错题 ──
python pmp_athena/study_advisor.py review-today

# ── 题库统计 ──
python pmp_athena/error_logger.py stats
python pmp_athena/question_bank.py stats

# ── 生成 14 天备考计划 ──
python pmp_athena/study_advisor.py plan --days 14
```

**这就够了。** 每天做题 → 录入 → 薄弱点分析 → 错题复习，形成闭环。

### 🥈 Level 2：配合 Claude Code（有对话交互）

如果你装了 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)（`npm install -g @anthropic-ai/claude-code`），在仓库目录下打开终端：

```bash
claude
```

然后可以直接用自然语言对话：

> "复习错题"
> "薄弱点分析"
> "风险管理的知识点有哪些"
> "分析趋势"
> "随机每日一练"

Claude Code 会自动读取 `CLAUDE.md` 里的规则，帮你执行对应的 Python 命令。不需要记命令。

### 🥇 Level 3：加微信桥接（在微信里用）

这是仓库作者目前在用的方式。需要额外安装 `wechat-claude-code`（一个 Node.js 微信机器人），配置比较折腾。详情见 [README 微信接入章节](README.md#💬-微信接入) 和 `docs/wechat-bridge-patch.md`。

**不确定要不要搞的话就跳过，Level 2 体验已经很好。**

---

## 数据文件是干嘛的

项目跑起来后会自动在这些文件里存数据（都在 `pmp_notes/` 下，不上传 Git）：

| 文件 | 内容 |
|------|------|
| `question_bank.json` | 所有做题记录 |
| `error_log.json` | 错题本（按题干去重） |
| `error_review_state.json` | 错题复习排期（SM-2 算法） |
| `exam_records.json` | 模考成绩历史 |
| `config.json` | 每日一练完成日期 |

如果你想清空数据重新开始，删掉这些文件就行。

---

## 常见问题

**Q: `ingest` 下载模型太慢怎么办？**
A: 模型是从 HuggingFace 下的，国内可能慢。可以设置镜像：
```bash
set HF_ENDPOINT=https://hf-mirror.com
python -m pmp_athena.cli ingest
```

**Q: PDF 解析乱码？**
A: `pdfplumber` 对中文 PDF 支持因文件而异。如果某份 PDF 解析质量差，可以导出为文本再手动录入。

**Q: 我没有 PDF，能直接用吗？**
A: 可以。用 Level 1 的 `record_answer.py` 手动录入题目，或直接用 Level 2 对话刷题。

**Q: `CLAUDE.md` 是什么？**
A: 这是 Claude Code 的行为规则文件，告诉 AI 怎么判卷、怎么回复、用什么格式。如果你用 Claude Code，它会自动读取。纯命令行用不到它。

**Q: 这项目支持其他考试吗（软考/ACP/PRINCE2）？**
A: 目前只针对 PMP，知识库和判题框架都是 PMP 的。改造成其他考试需要替换笔记和规则。

**Q: 我的做题数据会传到网上吗？**
A: 不会。所有数据存本地，向量库也是本地 ChromaDB。只有当你用 Claude Code 时，对话内容会经过 Anthropic 的 API（但题目数据不上传 Git）。用 Level 1 纯命令行完全离线。

---

## 下一步

1. `python -m pmp_athena.cli stats` — 看看向量库里有哪些内容
2. `python pmp_athena/study_advisor.py plan --days 14` — 生成一份备考计划
3. 做几道题，用 `record_answer.py` 录入
4. `python pmp_athena/study_advisor.py weakness` — 看看薄弱点
5. `python pmp_athena/study_advisor.py review-today` — 复习错题

做完这五步，你就算上手了 🎉
