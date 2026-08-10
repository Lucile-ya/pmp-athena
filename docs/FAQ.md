# ❓ PMP Athena 常见问题 FAQ

## 环境安装

### Q: 运行 `pip install -r requirements.txt` 报错？

**A:** 确保 Python 版本 ≥ 3.10：
```bash
python --version   # 应该是 3.10 或更高
```

如果报 `chromadb` 安装失败（Windows 常见），先装 Visual C++ 运行时：
- 下载 [VC++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) 安装后重试
- 或者用 conda：`conda install -c conda-forge chromadb`

### Q: `python` 命令找不到？

**A:** Windows 下 Python 可能注册为 `py`：
```bash
py --version
py -m pip install -r requirements.txt
```
之后所有命令把 `python` 换成 `py`。

### Q: 我用 Miniconda，Python 路径在哪？

**A:** 通常在 `C:\Users\<用户名>\miniconda3\python.exe` 或 `D:\miniconda\python.exe`。找到后在命令里用完整路径：
```bash
d:\miniconda\python.exe -m pmp_athena.cli ingest
```

---

## 向量库 & 模型下载

### Q: `ingest` 下载模型特别慢/一直卡住？

**A:** HuggingFace 在国内访问慢，设置镜像：
```bash
# Windows PowerShell
$env:HF_ENDPOINT = "https://hf-mirror.com"
python -m pmp_athena.cli ingest

# 或设置永久环境变量
setx HF_ENDPOINT "https://hf-mirror.com"
```

模型约 470MB，用镜像一般几分钟内完成。

### Q: `ingest` 报 "No module named 'chromadb'"？

**A:** 依赖没装全：
```bash
pip install chromadb sentence-transformers
```

### Q: 向量库能删除重建吗？

**A:** 可以，删掉 `data/` 目录重新 `ingest`：
```bash
rm -rf data/
python -m pmp_athena.cli ingest
```

---

## PDF 相关

### Q: PDF 解析出来是乱码？

**A:** PDF 文件本身可能是扫描版（图片）而非文字版，`pdfplumber` 只能提取文字型 PDF。试试：
```bash
python pmp_athena/daily_practice.py audit-content   # 检查解析质量
```
如果该 PDF 解析质量差，可以手动录入题目，或导出为文本文件再导入。

### Q: 我自己有 PDF，放哪里？

**A:**
- 每日一练 PDF → 放到 `pmp_notes/每日一练/`
- 模考 PDF → 放到 `pmp_notes/模考/`

命名规范参考已有的文件：`2609每日一练X月X日.pdf`（题目）、`2609每日一练X月X日答案解析.pdf`（答案）。

---

## 知识索引

### Q: `build_knowledge_index.py` 报错？

**A:** 确认先跑过 `ingest`，向量库里有数据：
```bash
python -m pmp_athena.cli stats   # 应该显示 chunk 数 > 0
```
如果 stats 显示 0，先回到上一步 `ingest`。

### Q: 知识点速查返回空或不对？

**A:** 试试扩大搜索范围：
```bash
python retrieve_knowledge.py query 整合管理 --level L1
python retrieve_knowledge.py message --text "详细 挣值管理"
```
如果仍然无结果，检查 `pmp_notes/` 下的 `.md` 笔记是否存在，它们是知识引擎的数据源。

---

## Claude Code / AI 助手

### Q: Claude Code 说 "No CLAUDE.md found"？

**A:** 确保在仓库根目录下启动 Claude Code：
```bash
cd D:\pmp-athena
claude
```
不要在子目录里启动。

### Q: WorkBuddy / Cursor 行为不对，没有按规则来？

**A:** 检查 `AGENTS.md` 是否存在，内容是否完整。如果某个工具读取了旧缓存，重新打开项目窗口试试。

### Q: 我不想用 AI 对话，能只用命令行吗？

**A:** 完全可以。运行 `python cli_chat.py`，一个菜单驱动的命令行工具，不需要任何 AI 助手。或者直接照着 QUICKSTART.md 里的命令手敲。

---

## 做题数据

### Q: 做题数据文件在哪？克隆后没有？

**A:** 这些文件在**第一次使用**时自动生成，不需要手动创建：
- `pmp_notes/question_bank.json`
- `pmp_notes/error_log.json`
- `pmp_notes/error_review_state.json`
- `pmp_notes/exam_records.json`

第一次执行 `python pmp_athena/record_answer.py` 或 `python cli_chat.py` → 录入错题 时自动出现。

### Q: 想清空所有做题数据重新开始？

**A:**
```bash
rm pmp_notes/question_bank.json
rm pmp_notes/error_log.json
rm pmp_notes/error_review_state.json
rm pmp_notes/exam_records.json
rm pmp_notes/config.json
rm pmp_notes/knowledge_mastery.json
```
下次使用时会从空白重新初始化。

### Q: 换电脑了，做题数据怎么迁移？

**A:** 把上面这几个 JSON 文件从旧电脑复制到新电脑的 `pmp_notes/` 目录即可。`data/`（向量库）不用迁移，在新电脑重新 `ingest` 就行。

---

## 微信桥接

### Q: 微信桥接是什么？非搞不可吗？

**A:** 不搞完全不影响使用。微信桥接是作者用来自动收发微信消息、在手机微信里做题的。没有微信需求的话直接跳过，命令行或 Claude Code 完全够用。

### Q: 微信桥接连不上/掉线？

**A:** 微信协议本身不稳定，加上 Windows 锁屏会切断连接。仓库提供了自动守护：
```powershell
# 重启桥接
.\restart_bridge.ps1

# 安装计划任务（5 分钟自动检测恢复）
schtasks /Create /TN "PMP-Athena-Bridge" /SC MINUTE /MO 5 /TR 'wscript.exe "D:\pmp-athena\bridge_guard.vbs"' /IT /F
```
详见 [README 桥接章节](README.md#桥接自动守护防锁屏断连)。

### Q: 改了 CLAUDE.md，桥接行为没变化？

**A:** 桥接启动时一次性加载 CLAUDE.md，不会实时监控文件变更。改完规则后需要让它重新加载：

**v1.1 之后（自动）**：`bridge_guard.ps1` 每 5 分钟检查 CLAUDE.md/AGENTS.md 是否比桥接进程新，如果更新了会自动重启桥接。等最多 5 分钟即可。

**手动立即生效**：
```powershell
.\restart_bridge.ps1
```

### Q: 发了指令（如「模考」「复习错题」），桥接回了通用菜单？

**A:** 常见原因和对策：

| 现象 | 可能原因 | 解决 |
|------|----------|------|
| 裸「模考」无反应 | CLAUDE.md 没定义裸词行为 | 更新到最新版（v1.1 已修复） |
| 「hello」被当成知识查询 | 缺少问候类触发词 | `git pull` 最新 CLAUDE.md |
| 任何指令都回「请说明…」 | 桥接未加载最新规则 | `.\restart_bridge.ps1` |
| 单字母/A/B/C/D 无反应 | 不在复习/每日一练模式中 | 先发「复习错题」进入模式 |

**核心原理**：CLAUDE.md 里有一条触发词快查表（约 67-75 行），AI 先匹配这张表再决定做什么。如果指令不在表里，就会掉进兜底菜单。

### Q: 桥接回复质量明显下降/胡言乱语？

**A:** 大概率是对话上下文太长，Claude Code 的缓存失效了。退出当前会话重新开始即可。微信端没有正常的「新对话」按钮，但可以通过桥接重启来清空上下文：
```powershell
.\restart_bridge.ps1
```

---

## Windows 特有问题

### Q: 中文输出乱码？

**A:** 设置环境变量：
```bash
$env:PYTHONIOENCODING = "utf-8"
python pmp_athena/study_advisor.py weakness
```
或者在 PowerShell 配置文件中永久设置。

### Q: 权限拒绝（Permission Denied）？

**A:** 不要用需要管理员权限的目录（如 `C:\Program Files\`）。仓库放在用户目录或 D 盘根目录即可。

### Q: `git push` 报文件太大？

**A:** 模考 PDF 较大。GitHub 单文件限制 100MB，Push 限制 2GB。如果超限，检查是否误加入了 `.pdf` 以外的文件。正常情况 42 个 PDF 共约 41MB，完全没问题。

---

## OCR / 截图

### Q: 截图识别报错 "TesseractNotFoundError"？

**A:** Tesseract 是可选依赖，需要手动安装：
1. 下载 [UB-Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
2. 安装时勾选中文语言包（Chinese Simplified）
3. 安装后把 Tesseract 路径加到系统 PATH，或指定路径：
```python
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

**不用 OCR 的话完全不用装**，不影响其他功能。

### Q: OCR 识别准确率低？

**A:** PMP 截图字体小、中英混排，确实容易出现识别偏差。如果识别不准，建议：
- 截图只留题目区域，裁掉多余部分
- 手动补充被识别为乱码的字段
- 或者直接用 `record_answer.py` 手动录入

---

## 升级 & 维护

### Q: 仓库更新了，我怎么同步？

**A:**
```bash
git pull origin main
pip install -r requirements.txt          # 可能有新依赖
python build_knowledge_index.py          # 索引可能有更新
```
你的做题数据（`pmp_notes/*.json`）不会被覆盖，因为它们在 `.gitignore` 里，`git pull` 不会动。

### Q: `git pull` 冲突了怎么办？

**A:** 如果你改了被跟踪的文件（如 PDF），可能有冲突：
```bash
git stash          # 暂存你的改动
git pull           # 拉最新
git stash pop      # 恢复你的改动
```

---

## 其他

### Q: 能支持其他考试（软考/ACP/PRINCE2）吗？

**A:** 目前只针对 PMP。核心数据（笔记、知识索引、判题框架）都是 PMP 的。改造成其他考试理论上可行：替换 `pmp_notes/` 下的笔记、重建索引、修改 CLAUDE.md 里的判题规则。

### Q: 这项目还在维护吗？

**A:** 活跃维护中，作者备考 2026-09-12 PMP 考试。如果遇到 bug，开 GitHub Issue。

### Q: 我能贡献代码吗？

**A:** 欢迎 PR。大的改动建议先开 Issue 讨论。

### Q: 还有其他问题？

**A:** [开 GitHub Issue](https://github.com/Lucile-ya/pmp-athena/issues/new)，带上你的操作系统、Python 版本、具体报错信息。
