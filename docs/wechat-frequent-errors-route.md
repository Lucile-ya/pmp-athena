# 微信桥接：高频错题 / 摘要卡硬路由

> **状态：已接入**（`wechat-claude-code` → `athena-router.ts` → `study_advisor.py frequent-errors`）

## 触发词

| 用户发送 | 行为 |
|----------|------|
| `高频错题` / `常错题` / `反复错的题` / `错题高频` / `高频错误` | Top **5** 高频清单（锚点+总结+解答+口诀） |
| `高频错题摘要卡` / `高频错题摘要` / `高频摘要卡` / `错题摘要卡` / `高频错题清单` / `生成高频错题` | Top **50** 全量高频清单 |

统一命令：

```powershell
d:\miniconda\python.exe pmp_athena/study_advisor.py frequent-errors --json [--top N]
```

## 与本地 MD 的关系

- 微信：**实时**从 `error_log.json` 生成，不读 `pmp_notes/薄弱点速记/00-高频错题摘要卡.md`
- 本地 MD：`cheatsheet_sync.py all` 或 `export_hf_cards.py` 导出；与微信内容同源（实时 error_log）

## 部署

修改 `athena-router.ts` 后：

```powershell
cd C:\Users\gwhea\.claude\skills\wechat-claude-code
npm run build
# 重启桥接
```
