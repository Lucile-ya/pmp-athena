# 微信图片预处理补丁

让 wechat-claude-code 在发送图片给 Claude 前，自动调用 PMP Athena 的图片处理器进行压缩和 OCR。

## 背景

wechat-claude-code 收到微信图片后，会将原始图片的 base64 直接传给 Claude API。大图会消耗大量 token 且可能触发限制。这个补丁在图片进入 Claude 之前插入一个 Python 预处理步骤：

```
原始图片 → 压缩到 1500px → 转 JPEG → OCR 提取文字 → 传给 Claude
```

## 手动打补丁

### 1. 修改 `src/claude/provider.ts`

在 `import` 区域添加：

```typescript
import { spawn, type ChildProcess, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { loadConfig } from '../config.js';
```

在 `cleanupTempFiles` 函数后面添加预处理函数：

```typescript
const IMAGE_PROCESSOR_SCRIPT = process.env.PMP_IMAGE_PROCESSOR ||
  join(process.cwd(), 'pmp_athena', 'image_processor.py');

const PYTHON_BIN = process.env.PYTHON_BIN || 'python';

function preprocessImage(imagePath: string) { /* ... */ }
function preprocessImages(imagePaths: string[]) { /* ... */ }
```

在 `saveImageTemp` 之后插入预处理调用：

```typescript
const { finalPaths, ocrTexts, processedPathsToCleanup } = preprocessImages(tempImagePaths);
if (ocrTexts.length > 0) {
  fullPrompt = '[图片OCR文字]\n' + ocrTexts.join('\n---\n') + '\n[/图片OCR文字]\n\n' + fullPrompt;
}
```

### 2. 修改 `src/config.ts`

添加 `pythonBin` 字段：

```typescript
export interface Config {
  workingDirectory: string;
  model?: string;
  systemPrompt?: string;
  pythonBin?: string;  // ← 新增
}
```

### 3. 修改 `config.json`

```json
{
  "workingDirectory": "D:/pmp-athena",
  "pythonBin": "D:/miniconda/python.exe",
  "systemPrompt": "你是 PMP Athena..."
}
```

### 4. 重新编译 + 重启

```bash
cd ~/.claude/skills/wechat-claude-code
npm run build
node dist/main.js start
```

## 更好的做法：直接使用打了补丁的 fork

```bash
cd ~/.claude/skills
rm -rf wechat-claude-code
git clone https://github.com/<your-fork>/wechat-claude-code.git
cd wechat-claude-code && npm install
```

（如果你 fork 了 wechat-claude-code 并合入了这些改动，其他人可以直接 clone 使用。）

## 验证

发送一张截图到微信，检查日志：

```bash
tail -f ~/.wechat-claude-code/logs/bridge-$(date +%Y-%m-%d).log | grep -i "preprocess\|OCR\|compress"
```

## 独立测试图片处理器

```bash
# 压缩 + OCR
python pmp_athena/image_processor.py ~/.wechat-claude-code/processed/test.jpg --json

# 仅 OCR
python pmp_athena/image_processor.py screenshot.png --ocr-only
```
