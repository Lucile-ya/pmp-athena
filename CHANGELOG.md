# Changelog

本文件记录 PMP Athena 的所有功能更新和重要变更。版本号遵循 [Semantic Versioning](https://semver.org/)。

---

## — 2026-08-31

### 🆕 新增

- **高频错题摘要卡**（`export_hf_cards.py`）：从错题本导出错 ≥3 次的题目为 `pmp_notes/薄弱点速记/00-高频错题摘要卡.md`（等级 / 锚点 / 口诀 / 历次错选）；微信触发词 `高频错题摘要卡` / `高频摘要卡` / `错题摘要卡` 等（见 `docs/wechat-frequent-errors-route.md`）
- **摘要卡自动同步**（`cheatsheet_sync.py`）：`sync_all()`、错题入库、`薄弱点` 诊断、`刷新速记`、批量刷题 flush 时自动重生成摘要卡并更新 README「考前加练」计数
- **P0 三领域合订知识点**（`00-P0三领域完整知识点.md`）：商业环境 + 成本管理 + 进度管理完整背诵版（概念 / 公式 / 陷阱 / 闪卡 / 7 天攻坚计划）
- **领域专项刷题种子库**（`pmp_notes/area_seeds/`）：`专项 <领域>` 合并种子 JSON + 题库可解析题，按领域随机抽题（默认上限 **15** 题）；首批 `商业环境.json`（12 道）+ 题库 4 道

### 🔧 修复 / 改进

- **微信速记闪卡漏推**（`weak_area_cheatsheet.py`）：`## 🃏 闪卡（遮住右列自测）` 等带括号后缀的节标题无法匹配 → `_extract_section` 支持标题后括号说明
- **专项练习行内选项解析**（`daily_practice.py`）：`在哪找？A.xxx B.yyy` 一行内选项格式以前无法解析 → lookbehind 正则，兼容 `?/？` 后紧跟选项字母
- **8 月 31 日每日一练 Q10 漏题**（`daily_practice.py`）：PDF 丢 `C.` 前缀时，已有 A/B 且下一行英文大写开头 → 自动补孤儿选项 C/D
- **做题汇总每日一练明细**（`practice_overview_light.py`）：月度视图增加每日一练逐日正确率（日期 / 首次 / 二次），与模考明细并列
- **速记即时同步**（`record_answer.py` + `batch_practice.py` + `mock_exam_engine.py`）：单题入库后立即同步薄弱点速记；App 批量刷题结束 flush 时一并同步

### 📝 文档

- `AGENTS.md` / `CLAUDE.md`：补充「高频错题摘要卡」与「薄弱点速记」区别及触发词
- `docs/wechat-frequent-errors-route.md`：微信桥接高频摘要卡硬路由说明
- `docs/wechat-weak-cheatsheet-route.md`：速记菜单补 P0 合订本入口

### 📋 已知限制（专项练习）

- **成本管理 / 进度管理**：尚无 `area_seeds` 种子文件，专项练习依赖题库内带完整 A–D 选项的记录；题量不足时提示「未找到可用题目」
- **P0 合订本**（`00-P0三领域完整知识点.md`）：Cursor / 本地 MD 阅读；微信端对应 `速记 <领域>` 精简一屏版

---

## — 2026-08-27

### 🆕 新增

- **2609期模考一（骐迹）接入**（`mock_exam_engine.py`）：微信/终端 `开始模考七` → 180 题完整模考（题目 + 答案解析双 PDF）；`load_qiji_mock_exam()` + v2 缓存
- **2609英文模考（希赛）接入**（`hisai_mock_parser.py` + `mock_exam_engine.py`）：`开始模考八` → 180 题英文卷 + 参考答案网格；支持 18 道多选题（含 6 选项题）
- **薄弱点速记**（`weak_area_cheatsheet.py`）：13 领域 MD 口诀 + 闪卡 + 易错陷阱 + 做题链；微信硬路由 `薄弱点速记` / `今日速记` / `速记 <领域>`（见 `docs/wechat-weak-cheatsheet-route.md`）
- **速记自动同步**（`cheatsheet_sync.py`）：`薄弱点` 诊断后自动把错题陷阱追加到 `pmp_notes/薄弱点速记/*.md`「来自错题本（自动）」段，并刷新 README 优先级；微信 `刷新速记` / `同步速记`
- **模考 PDF 完整性审计**（`mock_exam_audit.py`）：CLI `python pmp_athena/mock_exam_audit.py` 检查已接入试卷题量 / 答案 / 解析，并列出目录中未接入 PDF
- **每日一练 PDF 审计**（`daily_practice.py audit` / `audit-content`）：扫描全部每日一练 PDF 解析完整性

### 🔧 修复 / 改进

- **每日一练 / 模考 PDF 题目不完整**（`daily_practice.py` + `mock_exam_engine.py`）：
  - 骐迹水印修复：题号前 `骐18.【`、题号中 `104迹.【` 归一化，2609 模考一可解析 **180/180** 题 + 答案
  - 孤儿选项行恢复（PDF 丢字母前缀时补回 C/D 等）
  - 随机模考复用 `daily_practice` 完整解析器
  - 文字版模考（模拟一/二）多行选项合并
  - 解析缓存升级至 `_cached_v2.json`（升级 parser 后强制重建）
- **每日一练多选答案中文逗号**（`daily_practice.py`）：`答案:C，E` 不再被截断为单选 `C`；回归测试覆盖 8 月 24 日 Q10
- **做题汇总模考显示重复**（`practice_overview_light.py`）：月度模考从「每记录一行 `模考：3 次`」改为「一行汇总 + 逐卷明细（日期 / 正确率 / 得分）」
- **模拟一 / 模拟二**：文字版 PDF 已验证 **180/180** 题 + 答案 + 解析完整（v2 缓存）

### 📋 已知限制（模考资源）

| 试卷 | 状态 |
|------|------|
| 模拟一 / 模拟二（模考五/六） | ✅ 180 题完整 |
| **2609期模考一（模考七）** | ✅ **180 题完整（已接入）** |
| **PMP®模考题-2609（模考八）** | ✅ **180 题完整（已接入）** |
| 考前冲刺卷 1/2/3（模考一/二/三） | ⚠️ 扫描版 PDF，OCR 缓存不完整（71/57/13 题）；不足 180 时从每日一练补足 |
| ~~2609期模考一骐迹 / PMP®模考题-2609~~ | ~~未接入~~ → 见上「模考七/八」 |

### 📋 已知限制（每日一练）

- **8月27日**：缺答案解析 PDF，暂不能答案串对账；可互动出题
- 其余 7–8 月卷：**30/31** 天结构审计通过（每套 10 题）

### 📝 文档

- `AGENTS.md` / `README.md`：补充薄弱点速记与同步说明
- CHANGELOG 补录 2026-08-27 条目

---

## — 2026-08-25

### 🆕 新增

- **模考重发当前题**（`mock_exam_engine.py`）：新增 `show` 子命令 + `show_current()`，模考 `active` 态可重发当前待答题（供微信「继续」「当前题」等触发）
- **微信桥接 Windows 原生守护**（wechat-claude-code fork）：新增 `scripts/daemon.ps1` + `scripts/daemon-cli.mjs`；`npm run daemon -- start|stop|restart|status|logs` 在 Windows 上走 PowerShell，不再依赖 WSL/bash（修复 `execvpe /bin/bash failed`）
- **每日一练 PDF**：8月19日～8月25日（题目 + 答案解析，8月25日仅题目）
- **模考 PDF**：2609期 PMP®模考题 + 参考答案、骐迹 2609期模考一（8月22日）答案解析

### 🔧 修复 / 改进

- **模考进行中误触「模考」/发「继续」无题目**：微信 `athena-router.ts` 在 `active` 态下，`继续`/`继续模考`/`当前题`/`重发题目`/`模考` 等 → 硬路由 `mock_exam_engine.py show` 重发本题；未知指令提示补「发当前题可重发本题」
- **恢复模考题目双发**：`recover` 返回时 Python 已将 `next` 合并进 `text`，路由侧不再重复拼接 `next?.text`
- **重新 setup 扫码后桥接未生效**：setup 绑定新 bot 账号后需 `npm run daemon -- restart`（或 `restart_bridge.ps1`）；工作目录应填 `D:\pmp-athena`；旧对话积压消息可能因 seq 去重新消息被丢弃，需在新对话发新消息验证
- **重新绑定后微信完全无回复**：`msg-dedup` 仅按 seq 去重，新 bot 的 seq 从 1 重计与旧 `1.marker` 冲突 → 全部消息被 `cross-process duplicate` 丢弃；改为按 `{accountId}-{seq}` 去重 + setup/启动时清理旧 marker
- **消息队列优化**（对齐 [上游 wechat-claude-code](https://github.com/Wechat-ggGitHub/wechat-claude-code) README 后续计划）：入站短消息 700ms 合并（A/B/C/D、拆词指令）；出站 `sendText` 串行链防串线；`flushPending` 失败时保留剩余队列项

### 📝 文档

- CHANGELOG 补录 2026-08-25 条目

---

## — 2026-08-18

### 🔧 修复

- **每日一练题号后全角空格漏题**：部分 PDF 题头在题号与句点之间夹了全角空格（如 `4 ．【单选题】`，其余题是紧凑的 `5.【单选题】`），切题正则 `\d+[\.．]` 要求数字后紧跟句点，匹配不上导致题块切不开、整题被吞进上一题（8月17日 Q4 漏题，报「共 9 题」）→ `_normalize_pdf_text` 补两条归一化：题号与句点之间的空格、`【单 选 题】` 内部空格
- **根因变式题格式校验**：截图录入的坏题（解析页「正确答案/我的答案/全站正确率」表格被当成题干）会被当作变式题推给用户 → 推送前校验（污染标记 + 恰好 A/B/C/D 四个选项 + 正确答案 + 题干完整），坏题自动跳过并记录到 `pmp_notes/broken_questions.log`（同题去重），连续 3 道坏题且凑不够可用题时提示「暂无可用的变式题」

### 🆕 新增

- **每日一练 PDF**：8月17日（题目 + 答案解析）、8月18日（题目 + 答案解析）
- **模考 PDF**：2609期PMP模考一（8月22日）骐迹教育，180 题（170 单选 + 10 多选）；暂无答案解析 PDF，且题头有 7 处水印字污染 + 题号到 180，现有模考引擎暂未接入（待答案 PDF 到位后适配解析器再注册）
- **备考建议三步走 + 专项练习**：`study_advice.py three-step` 输出「① 清账（复习错题）→ ② 定点爆破（薄弱领域各刷 15-20 题）→ ③ 高频错题收尾」三步计划；`daily_practice.py area-start --area <领域>` 支持「专项 成本管理」按领域从题库抽题互动判卷（`source=area_practice`，坏题/多选题自动过滤，题干去重）

---

## — 2026-08-17

### 🔧 修复

- **桥接守护去掉 .vbs 依赖**：计划任务 `PMP-Athena-Bridge` 从 `wscript bridge_guard.vbs` 改为 `conhost --headless powershell.exe -WindowStyle Hidden -File bridge_guard.ps1`，彻底无窗口 + 避免杀毒软件误删 .vbs 导致每 5 分钟弹「脚本找不到」；移除 `bridge_guard.vbs`，同步更新 `monitor_bridge.ps1` / README / FAQ
- **截图录入 OCR 崩溃**：`image_processor.py` 的 main() 缺 stdout UTF-8 编码，Windows GBK 下输出含 emoji 时抛 UnicodeEncodeError，导致发图录入错题 fall back 到兜底菜单 → 补 `sys.stdout.reconfigure(encoding="utf-8")`
- **发图+配文被微信拆成两条消息**：桥接逐条处理导致「先文后图」场景配文失效 → 桥接记住上一条文字消息，图片消息无配文时自动关联

---

## — 2026-08-14

### 🆕 新增

- **高频顽疾专项处理**：错题累计错误 ≥4 次升级为「高频顽疾」，走深度拆解流程
  - 深度拆解：完整错误记录（每次错选答案 + 日期）+ 根因诊断 + 反向训练预告
  - 反向训练：答对后推送同考点变式题，连续答对 2 道才移出高频列表（新增 `variant_streak` 字段持久化到 review_state）
  - 复习 header 统计「🔥 高频顽疾：X 道待攻克」
  - 错 3 次保留原「高频错题」增强格式，行为不回退
- **趋势分析**（`trend_analysis.py`）：读 exam_records + question_bank，输出模考趋势 / 每日一练趋势 / 通过概率报告；微信端「分析趋势 / 通过率预测 / 趋势分析」硬路由

### 🐛 修复

- **「分析趋势」被误路由为知识点**：athena-router 缺硬路由，被动态知识查询兜底正则（任意 2-16 汉字）捕获 → 新增 TREND_TRIGGERS + trend_analysis.py 硬路由
- **变式判卷失败**：`_study_advisor_review_next` 直接运行脚本时 `from pmp_athena.study_advisor` 无 fallback，最后一道变式题判卷抛 ModuleNotFoundError → 补 try/except 兜底
- **统计口径虚低**：待判卷题（is_correct=None，App 批量刷题阶段1收录未判卷）被误算成错题，月度正确率虚低 → 待判卷题单独归类、不计入正确率，月度明细标注待判卷数

---

## — 2026-08-13

### 🆕 新增

- **两套新模考卷**：`模拟一`（希赛 8 月 PMP 模拟题 1）、`模拟二`（希赛 8 月 PMP 模拟题 2），各 180 题
  - 文字版单 PDF（题干+选项+「试题答案」「试题解析」内联），无需 OCR，直接解析并缓存 JSON
  - 微信端 `开始模考五/六` 硬路由；终端 `mock_exam_engine.py start --paper five/six`
- **识别结果纠错**（`correction.py`）：三类纠错统一入口，自动级联维护 question_bank / error_log / error_review_state 三文件并重算领域正确率
  - `answer` 改答案：wrong↔correct 双向，自动移除/新建错题 + 复习队列
  - `area` 改知识领域：三文件同步 + 重算新旧领域正确率
  - `delete` 删题：三文件一并清理
  - `latest` 查看最新记录，供定位题目
- **模考放弃归档可恢复**：`abandon` 不再直接清空，进度先归档到 `mock_exam_engine.abandoned.json`；新增 `recover` 命令 + 微信端「恢复模考」硬路由

### 🐛 修复

- 每日一练切题漏题：题号与【之间卡水印字（如「7．迹【单选题】」）导致整题被吞进上一题
- 每日一练题号错位（`3【. 单选题】`，【 与 . 顺序颠倒）导致漏题
- 每日一练双语题干被截断（英文问号在前、中文问号在后，`find` 截到英文 ? 把中文题干砍掉）→ 改 `rfind` 取最后一个问号
- **模考「继续」失效**：暂停后 resume 未分发，`继续` 落到 Claude；进度显示读错字段恒为 0 → 补 resume 分发 + 改读 `current_index`
- **截图录入错题失效**（微信发图 → 落到通用菜单）：`analyze_exam.py` 相对导入 `from .exam_recorder` 在桥接以独立脚本调用时 `ImportError`，改 try/except 兜底
- **选项解析越界**：`_parse_options_enumerated` 在选项 ≥5 时 `letters[len(options)]` 越界，越界保护提前
- **答案表头+值分两行解析失败**：希赛作答页「正确答案/我的答案」表头与值（B/C）分两行，单行正则失效致 `my_answer`/`correct_answer` 均 None；新增 `_extract_table_answers` 按表头顺序映射下一行字母
- **统计表头误判为答对信号**：「全站正确率」含「正确」被当「答对」，与「答错」对比信号冲突致置信度 0.98→0.26；`text_without_noise` 增加过滤全站正确率/正确率/正确选项
- `question_bank.update()` 静默忽略 `error_log_id` → 加入可更新字段，顺带修复 `record_answer.py` 重录错题时关联丢失

### 📝 文档

- CLAUDE.md 模考入口菜单补「开始模考五/六」
- CLAUDE.md：纠正记录章节补充 `correction.py` 推荐入口

---

## — 2026-08-11

### 🆕 新增

- **微信端模考引擎**（`mock_exam_engine.py`）：状态机驱动的逐题模考系统，完全硬路由
  - 四套试卷：考前冲刺卷 1/2/3 + 模考卷二
  - 冲刺卷 1/2 支持扫描版 PDF OCR（Tesseract + pdfplumber 图片提取）+ JSON 缓存
  - 回退方案：每日一练 175 道文字版 PDF 解析组卷
  - 支持开始/作答/暂停/继续/放弃/自动判卷/多选/报告生成
  - 错题自动同步 error_log + question_bank + exam_records
- **「帮助/菜单/hello/倒计时」硬路由**：TypeScript 直接处理，不经过 Claude
- **桥接守护自动热重载**：CLAUDE.md/AGENTS.md 更新后 5 分钟内自动重启

### 🐛 修复

- 裸「模考」→ 硬路由入口菜单；`hello` → 功能菜单；`倒计时` → 精确计秒
- `开始模考一` 被知识查询通配拦截 → MOCK_EXAM_TRIGGERS 排除
- PDF 水印污染 → 五重正则清洗（孤立行/选项内/英文词间/连续短语/中英混排中文优选）
- 多选题不识别 → `_MULTI_MARKERS` 扩展 14 个关键词 + 题干文字回退检测
- 模考多选 `CDE` 被判为三个单选 → 引擎排序归一化 + 路由多字母透传
- 每日一练 `CDE` 被拒「只剩 2 题」→ `grade_answers` 题干多选关键词检测

### 📝 文档

- FAQ：桥接行为诊断 / 平台兼容 / AI 助手矩阵 / CLI-only 用法 / 两层路由 / GBK 编码
- QUICKSTART：平台矩阵 + AI 助手表格 + 升级指南
- README：Badge + 典型话术表 + 输出示例 + 设计原则 + 隐私表

---

## [1.1.0] — 2026-08-10

### 🆕 新增

- **错题分类标签**：引入 `error_type` 字段，六种类型（概念混淆 / 流程顺序错 / 角色越权 / 陷阱误导 / 粗心 / 知识盲区）
  - `error_logger.py`：add()/update() 支持 error_type，CLI 新增 `--error-type` 参数
  - `record_answer.py`：wrong 命令支持 `--error-type`，三文件同步写入
  - `study_advisor.py`：薄弱点分析新增"错误类型分布"章节（表格 + 诊断建议）
  - `CLAUDE.md`：自动分类规则（7 级优先级匹配）+ 判卷格式 `🏷️ 错误类型: X`
- **考前 30 天自动切换**：D ≤ 30 时自动触发三项行为变更
  - 复习错题 → 只推 T1（高频）+ T2（近期），T3 完全延期至考前 7 天
  - 知识点速查 → 默认 L1 精华摘要，用户说"详细"才展开 L2
  - 每日一练 → 自动建议 30 题（3 套）
  - `review_scheduler.py`：新增 `should_activate_pre30()`、`days_to_exam()`
  - `study_advisor.py`：`review_today()`/`review_next()` 接入 pre30 模式
- **`cli_chat.py`**：命令行聊天脚本，零依赖、菜单驱动，`python cli_chat.py` 开箱即用
- **`AGENTS.md`**：同步 CLAUDE.md，兼容 WorkBuddy / Cursor Agent 等 AI 助手
- **题目 PDF 共享**：42 份培训机构 PDF（34 份每日一练 + 8 份模考）纳入版本控制，克隆即可用
- **`docs/FAQ.md`**：20+ 常见问题（环境 / 模型 / PDF / Windows / OCR / 微信桥接）
- **`QUICKSTART.md`**：5 分钟上手指南，三级用法（纯 CLI → AI 助手 → 微信桥接）
- **FB-001 两阶段截图解析**：先纯文字推理再视觉标记对照，防截图颜色/标签锚定偏见
- **FB-002 思路先于选项规则**：判题推理框架新增 Step 0，禁止直接扫 ABCD 找答案
- **`CHANGELOG.md`**：完整版本历史（v0.1 ~ v1.1.0），70+ 条记录

### 🔧 改进

- 根因变式巩固 v2：去重 + 降级总结 + 实战模拟挑战
- 做题质量审计：过滤 OCR 损坏题，防止污染变式题库
- 月度练习汇总：趋势分析 + 扩展触发词
- 模考看板：可视化仪表盘 + 完成追踪
- 模考断点续做增强：暂停/继续/时间追踪
- **桥接守护自动热重载**：`bridge_guard.ps1` 监控 CLAUDE.md/AGENTS.md 修改时间，规则更新后 5 分钟内自动重启桥接，无需手动 `.restart_bridge.ps1`

### 🐛 修复

- **「模考」触发词不识别**：补全默认行为触发词列表，`模考`/`开始模考`/`随机模考`/`继续模考` 直接命中，不再掉入兜底菜单
- **裸「模考」无响应**：单独发「模考」二字时展示模考入口菜单（可选试卷/随机模考），不再茫然
- **「hello」误触发知识查询**：新增 `帮助`/`菜单`/`hello`/`hi`/`你好` 触发词，统一回复功能菜单

### 📝 文档

- README 链接 QUICKSTART + AGENTS.md 多工具兼容说明
- `.gitignore` 开放 PDF 上传，保持做题数据隐私

---

## [1.0.0] — 2026-08-07

**🎉 首个正式版发布。** 经过三周密集开发（7/15 立项 → 8/7 发布），Athena 从一个 CLI 工具集成长为完整的 PMP 备考系统。

### 核心能力（18 个模块）

| 模块 | 说明 |
|------|------|
| 🧠 知识领域引擎 | 13 领域结构化知识（定义/49 过程/工具/输出/易错点） |
| 📖 动态知识查询 | L1(框架速查) / L2(全领域展开) / L3(情景套路) / 关联(邻接矩阵) |
| 📚 向量知识库 | ChromaDB + sentence-transformers 语义检索 |
| 🎯 PMP 判题推理框架 | 六步推理链 + P1-P6 优先级 + T01-T12 陷阱模式 |
| 📝 每日一练 | 解析培训机构 PDF，互动出题 / 批量对账 / 判卷 / 自动入库 |
| 📱 App 批量刷题 | 多题+答案串 → 收录 → 补录解析后判卷入库 |
| ❌ 错题本 + SM-2 | 三文件同步（error_log / error_review_state / question_bank） |
| 🔬 根因诊断引擎 | 12 种错误模式自动识别 + 专属破解口诀 |
| 🧬 错题演化追踪 | 错误 ≥3 次自动生成摇摆/陷阱/信任洞察报告 |
| 🔑 语义记忆锚点 | 12 种根因各有专属锚点话术 + 视觉线索 |
| 📊 智能复习排期 | 四层错题分级（T0-T3）+ 每日限量 + 考前冲刺清零 |
| 🎯 学习顾问 | 薄弱点诊断 / 今日错题复习 / 备考计划 |
| 📊 模考 | PDF 模考 / 断点续做 / 时间·速度·精度三维诊断 |
| 🖼️ 截图 OCR | 题目截图 / 模考成绩 / 章节练习统计识别入库 |
| 🗺️ 思维导图结构化 | PNG 思维导图 OCR → 13 份 PMBOK 标准表格 MD |
| 💬 微信桥接 | 硬路由 25+ 指令 + 桥接自动守护（防锁屏断连） |
| 🌙 睡前复习 | D-Day 自适应策略（四档位）+ 错题优先 + 明日预告 |
| 🔍 考前风险评估 | 累计题量 / 错题分布 / 模考趋势 / 风险等级 / 行动计划 |

---

## v0.x — 开发里程碑（2026-07-15 ~ 2026-08-06）

### v0.5 · 错题系统全面升级 — 2026-08-07

- 高频错题解读（`error_insights.py`）：31 条场景规则 → 诊断摘要 + 记忆口诀
- 错题演化追踪（`error_evolution.py`）：≥3 次错误 → 摇摆/陷阱/信任洞察
- 语义记忆锚点（`semantic_anchors.py`）：12 种根因专属锚点话术
- 根因诊断引擎（`root_cause_engine.py`）：12 条诊断规则，关键词 + 错选模式双重匹配
- 根因变式巩固 v2（`root_cause_variants.py`）：去重 + 总结降级 + 实战模拟
- 智能复习排期引擎（`review_scheduler.py`）：T0-T3 四层分级 + 每日限量 + 进度条
- 做题质量审计：过滤 OCR 损坏题
- 做题总览（`practice_overview.py`）：时间线 + 领域统计
- 模考看板（`mock_exam_kanban.py`）：可视化仪表盘
- 全局路径统一（`config.py`）：消除 `D:/pmp-athena` 硬编码

### v0.4 · 知识引擎 + 推理框架 — 2026-07-31 ~ 2026-08-06

- 知识领域引擎（`knowledge_domain_engine.py`）：13 领域 × 49 过程，L1/L2/L3 三层
- 动态知识查询（`dynamic_knowledge.py`）：领域速查 + 套路映射 + 邻接矩阵
- PMP 判题推理框架：六步推理链（项目类型→阶段→ECO→问题→问法→仲裁）
- P1-P6 优先级原则：先分析 → 先协作 → 先流程 → 先根因 → 预防 → 团队参与
- 12 陷阱模式（T01-T12）：过早行动 / 过早升级 / 绕过流程 / … / 镀金
- 思维导图 OCR（`mindmap_ocr.py` → `build_mindmap_md.py`）：PNG → 13 份结构化 MD
- 微信桥接守护（`bridge_guard.ps1` + 计划任务）：锁屏断连自动恢复
- 刷题总览（`practice_overview.py`） + 章节练习入库（`chapter_practice_recorder.py`）
- 考前深度分析（`pre_exam_analysis.py`）

### v0.3 · 微信交互 + 自动化 — 2026-07-29 ~ 2026-07-30

- CLAUDE.md 行为规则文件：判卷格式 / 出题规则 / 触发词路由
- 睡前复习推送（`bedtime_review`）：知识点 + 错题回顾 + 明日预告
- 出题静默规则：禁止附带答案 / 解析 / 历史作答 / 闲聊追问
- 铁律置顶：连续字母 = 答题 = 逐题判卷 + 错题自动入库
- App 批量刷题（`batch_practice.py`）：两阶段（收录 → 补录判卷）
- 硬路由系统：25+ 指令直接调 Python CLI，不经过 LLM
- 日常任务自动检测：周末每日一练检查 / 下午跟进提醒

### v0.2 · 做题系统骨架 — 2026-07-21 ~ 2026-07-28

- 题库模块（`question_bank.py`）：做题记录 CRUD，按日期/领域统计
- 学习顾问（`study_advisor.py`）：薄弱点诊断 / 错题复习 / 备考计划
- 模考系统：截图分析（`analyze_exam.py`）+ 记录（`exam_recorder.py`）
- 模考状态持久化（`mock_exam_state.py`）：断点续做，暂停/继续/超时计数
- 每日一练完成追踪：`config.json` 自动记录完成日期
- 周末综合评估：摸底考试（错题+新题组卷 / 分领域诊断 / 下周策略）
- 刷题记录截图分析：OCR → 领域识别 → 写入 + 对比
- 70% 训练目标线确立（126/180）

### v0.1 · 项目启动 — 2026-07-15 ~ 2026-07-16

- 🏗️ 项目骨架：CLI 入口（`cli.py`）、项目结构、依赖声明
- ❌ 错题本（`error_logger.py`）：CRUD + JSON 持久化 + 题干去重
- 🧠 SM-2 间隔复习（`spaced_repetition.py`）：标准 SM-2 算法，EF/q/interval 参数
- 🖼️ 截图预处理（`image_processor.py`）：压缩 + OCR + 答案验证
- 🎯 冲刺计划器（`sprint_planner.py`）：倒计时 + 每日任务分配
- ✅ 答案校验器（`answer_validator.py`）：截图中的答案标记自动识别
- ⏰ 考试计时器（`exam_timer.py`）：倒计时 + 阶段判定 + 里程碑提醒
- 🐕 看门狗保活脚本：微信桥接进程守护
- 📋 首批 PMP 截图解析规则（答案+解析+记忆口诀 三要素格式）

---

## 版本号规则

| 类型 | 示例 | 含义 |
|------|------|------|
| **主版本** | `1.x.x` | 正式版、架构大改 |
| **次版本** | `x.1.x` | 新模块/新功能 |
| **修订** | `x.x.1` | 文档、bug 修复、小改进 |

---

*最新更新：2026-09-01*
