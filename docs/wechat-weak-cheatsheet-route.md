# 微信桥接：薄弱点速记硬路由

> **状态：已接入**（`wechat-claude-code` → `src/athena-router.ts` → `runWeakCheatsheet`）

## 触发词

| 用户发送 | Python 命令 |
|----------|-------------|
| `薄弱点速记` / `薄弱速记` / `速记清单` | `weak_area_cheatsheet.py message --text "<原文>"` → 菜单 |
| `今日速记` / `今天速记` | 同上 → 按薄弱优先级+日期轮换推一个领域 |
| `速记 商业环境` / `成本速记` | 同上 → 指定领域速记 |

统一入口：`message --text`，由 Python 内部解析意图。

## 与「薄弱点」的区别

| 指令 | 模块 | 输出 |
|------|------|------|
| `薄弱点` | `study_advisor.py weakness` | 诊断报告（**末尾自动同步速记卡**） |
| `薄弱点速记` | `weak_area_cheatsheet.py` | 可背诵口诀+闪卡+陷阱 |
| `今日速记` | `weak_area_cheatsheet.py` | 按轮换推一个领域速记 |
| `刷新速记` / `同步速记` | `cheatsheet_sync.py` | 错题→易错陷阱 + 刷新 README + **高频错题摘要卡** |

## 自动同步机制

1. **增量陷阱**：新录入 `error_log.json` 的错题 → 追加到对应 MD 的「来自错题本（自动）」表格（去重，每领域每次最多 8 条）
2. **首次同步**：只写入错 ≥2 次的模式，其余标记已处理
3. **README 刷新**：重算错误率、错题本数量、P0/P1/P2 优先级
4. **触发方式**：发 `薄弱点`（诊断末尾自动跑）或 `刷新速记`

## 主动推送（无需手打「刷新速记」）

| 场景 | 行为 |
|------|------|
| **每天 08:00** | `prep_push.py tick` 晨间推送含：复习计划 + 速记同步摘要 + **今日速记**（需 Windows 任务计划运行 `prep_push_tick.bat`） |
| **每日一练/模考判卷后** | 有新错题时，判卷结果末尾自动附一行「📌 速记已同步：…」 |
| **发 `薄弱点`** | 诊断报告末尾附完整同步摘要 |
| **发 `今日速记`** | 静默同步后推送当日背诵领域 |

后台 `ensure_daily_sync` 仍会写 MD 文件，但**不单独发微信**；要看同步报告请用以上入口，或手动发 `刷新速记`。

状态文件：`pmp_notes/薄弱点速记/.sync_state.json`（已同步的错题 id）

## 今日任务（分步闯关）

> **状态：已接入**（`athena-router.ts` → `daily_quest.py`）

| 用户发送 | 行为 |
|----------|------|
| `今日任务` / `今天任务` / `今日闯关` | 微信一屏清单 + 勾选进度 |
| `开始任务` / `下一步` / `继续任务` | ①清错题 → ②当日专项 → ③摘要卡 10 张 |

做题中途直接答 A/B/C/D。复习/专项进行中不会被「下一步」抢走。不要用裸「开始」（会撞「开始模考」）。

```powershell
$env:PYTHONIOENCODING='utf-8'
d:\miniconda\python.exe pmp_athena/daily_quest.py message --text "今日任务"
d:\miniconda\python.exe pmp_athena/daily_quest.py next
```

## 路由位置

在 `routeAthenaMessage()` 中，**须在 `dynamic_knowledge` 裸关键词兜底之前**，避免「薄弱点速记」被知识查询拦截。

```typescript
function isCheatsheetRequest(text: string): boolean { /* ... */ }
function runWeakCheatsheet(config, text) {
  return runPythonScript(config, 'weak_area_cheatsheet.py', ['message', '--text', text]);
}
```

## 数据来源

- Markdown：`pmp_notes/薄弱点速记/*.md`
- 今日轮换优先级：读取 `error_log.json` / `question_bank.json` 错误率

## 本地验证

```powershell
$env:PYTHONIOENCODING='utf-8'
d:\miniconda\python.exe pmp_athena/weak_area_cheatsheet.py message --text "薄弱点速记"
d:\miniconda\python.exe pmp_athena/weak_area_cheatsheet.py message --text "今日速记"
d:\miniconda\python.exe pmp_athena/weak_area_cheatsheet.py message --text "速记 成本管理"
```

## 部署

修改 `athena-router.ts` 或 Python 后：

```powershell
cd C:\Users\gwhea\.claude\skills\wechat-claude-code
npm run build
npm run run   # 或 restart_bridge.ps1
```
