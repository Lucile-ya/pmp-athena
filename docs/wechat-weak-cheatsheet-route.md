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
| `薄弱点` | `study_advisor.py weakness` | 诊断报告（错误率排行） |
| `薄弱点速记` | `weak_area_cheatsheet.py` | 可背诵口诀+闪卡+陷阱 |
| `今日速记` | `weak_area_cheatsheet.py` | 按轮换推一个领域速记 |

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
