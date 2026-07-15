#!/usr/bin/env python3
"""
微信图片预处理工具

当微信桥接收到图片时，本模块负责：
1. 压缩图片到最大 1500x1500 像素
2. 转换为 JPEG 格式（降低体积）
3. OCR 提取图片中的文字（如果有）
4. 输出处理后图片路径 + OCR 文本

用法：
    python image_processor.py <input_path> [--output <output_path>] [--no-ocr] [--max-size 1500]
"""

import argparse
import io
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter, ImageEnhance, ImageOps, ImageStat

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("image_processor")

# 默认输出目录（与 wechat-claude-code 的临时目录一致）
DEFAULT_OUTPUT_DIR = Path.home() / ".wechat-claude-code" / "processed"
DEFAULT_MAX_SIZE = 1500
DEFAULT_JPEG_QUALITY = 80

# OCR 可用性
try:
    import pytesseract

    # Windows 下显式指定 Tesseract 路径
    if sys.platform == "win32":
        _tesseract_path = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        if _tesseract_path.exists():
            pytesseract.pytesseract.tesseract_cmd = str(_tesseract_path)
        else:
            logger.warning("Tesseract not found at %s, OCR may fail", _tesseract_path)

    HAS_OCR = True
except ImportError:
    HAS_OCR = False
    logger.warning("pytesseract not available, OCR disabled")


class ImageProcessor:
    """图片预处理：压缩 + OCR"""

    def __init__(
        self,
        max_size: int = DEFAULT_MAX_SIZE,
        jpeg_quality: int = DEFAULT_JPEG_QUALITY,
        output_dir: Path | None = None,
    ):
        self.max_size = max_size
        self.jpeg_quality = jpeg_quality
        self.output_dir = output_dir or DEFAULT_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── 公开 API ─────────────────────────────────────────────

    def process(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        run_ocr: bool = True,
    ) -> dict:
        """
        处理单张图片。

        返回:
        {
            "success": bool,
            "original_path": str,
            "processed_path": str | None,
            "original_size": (w, h),
            "processed_size": (w, h),
            "original_bytes": int,
            "processed_bytes": int,
            "ocr_text": str | None,
            "ocr_available": bool,
            "error": str | None,
        }
        """
        input_path = Path(input_path)
        result = {
            "success": False,
            "original_path": str(input_path),
            "processed_path": None,
            "original_size": None,
            "processed_size": None,
            "original_bytes": input_path.stat().st_size if input_path.exists() else 0,
            "processed_bytes": 0,
            "ocr_text": None,
            "ocr_available": HAS_OCR,
            "error": None,
        }

        try:
            # 1. 打开图片
            image = Image.open(input_path)
            result["original_size"] = image.size
            original_mode = image.mode

            # 2. 压缩尺寸
            image = self._resize(image)

            # 3. 转 RGB（JPEG 不支持 RGBA/P）
            if image.mode in ("RGBA", "P", "LA", "PA"):
                background = Image.new("RGB", image.size, (255, 255, 255))
                if image.mode == "P":
                    image = image.convert("RGBA")
                if image.mode in ("RGBA", "LA", "PA"):
                    background.paste(
                        image, mask=image.split()[-1] if image.mode in ("RGBA", "LA", "PA") else None
                    )
                image = background
            elif image.mode not in ("RGB",):
                image = image.convert("RGB")

            # 4. 保存为 JPEG
            if output_path is None:
                stem = input_path.stem
                output_filename = f"{stem}_processed.jpg"
                output_path = self.output_dir / output_filename
            else:
                output_path = Path(output_path)

            image.save(output_path, "JPEG", quality=self.jpeg_quality, optimize=True)
            result["processed_path"] = str(output_path)
            result["processed_size"] = image.size
            result["processed_bytes"] = output_path.stat().st_size

            # 5. OCR 提取文字（可选）
            if run_ocr and HAS_OCR:
                ocr_text = self._ocr(image)
                if ocr_text and ocr_text.strip():
                    result["ocr_text"] = ocr_text.strip()

            result["success"] = True

        except Exception as e:
            result["error"] = str(e)
            logger.error("Image processing failed: %s", e)

        return result

    def process_batch(
        self, input_paths: list[str], run_ocr: bool = True
    ) -> list[dict]:
        """批量处理图片"""
        return [self.process(p, run_ocr=run_ocr) for p in input_paths]

    # ── 内部方法 ─────────────────────────────────────────────

    def _resize(self, image: Image.Image) -> Image.Image:
        """等比缩放，使最长边 ≤ max_size"""
        w, h = image.size
        longest = max(w, h)

        if longest <= self.max_size:
            return image.copy()

        ratio = self.max_size / longest
        new_size = (int(w * ratio), int(h * ratio))
        # 使用 LANCZOS 高质量重采样
        return image.resize(new_size, Image.Resampling.LANCZOS)

    def _ocr(self, image: Image.Image) -> str:
        """
        OCR 识别图片中的文字。

        对图片做预处理（灰度化、增强对比度、二值化）以提高识别率。
        """
        if not HAS_OCR:
            return ""

        try:
            # 预处理：灰度化
            gray = image.convert("L")

            # 预处理：增强对比度
            enhancer = ImageEnhance.Contrast(gray)
            gray = enhancer.enhance(2.0)

            # 预处理：锐化
            gray = gray.filter(ImageFilter.SHARPEN)

            # OCR（中英文混合）
            text = pytesseract.image_to_string(gray, lang="chi_sim+eng")

            # 基本后处理：去掉纯空白行
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            return "\n".join(lines)

        except Exception as e:
            logger.warning("OCR failed: %s", e)
            return ""

    def preprocess_for_ocr(self, image: Image.Image) -> Image.Image:
        """
        更激进的 OCR 预处理：灰度 + 对比度增强 + 二值化 + 去噪。

        适合文字截图、表格图片等场景。
        """
        # 灰度化
        gray = image.convert("L")

        # 自适应对比度
        gray = ImageOps.autocontrast(gray, cutoff=5)

        # 增强对比度
        enhancer = ImageEnhance.Contrast(gray)
        gray = enhancer.enhance(3.0)

        # 锐化
        gray = gray.filter(ImageFilter.SHARPEN)

        # 去噪（中值滤波）
        gray = gray.filter(ImageFilter.MedianFilter(size=3))

        return gray


# ═══════════════════════════════════════════════════════════
# 答题正误识别器 (Answer Validator)
# ═══════════════════════════════════════════════════════════

class AnswerValidator:
    """
    从题库截图的 OCR 文本 + 像素颜色中自动判断题目答对/答错。

    识别信号（优先级从高到低）：
    1. 颜色标记 — 图片中红色区域 ≈ 答错，绿色区域 ≈ 答对
    2. 文字标签 — "答错"/"答对"/"正确"/"错误"/"Correct"/"Incorrect"
    3. 符号标记 — ✗/✘/× (错) vs ✓/✔/√ (对)
    4. 选项对比 — OCR 中出现了"我的答案 X"和"正确答案 Y"，X≠Y 即错

    如果判断为答错，自动提取题目信息供 error_logger 使用。
    """

    # ── 文字匹配规则 ───────────────────────────────────────

    WRONG_LABELS = [
        "答错", "错误", "选错", "做错", "答错了",
        "incorrect", "wrong", "❌", "✗", "✘", "×",
        "你答错了", "回答错误", "不是正确答案",
    ]

    CORRECT_LABELS = [
        "答对", "正确", "选对", "做对", "答对了",
        "correct", "right", "✅", "✓", "✔", "√", "☑",
        "你答对了", "回答正确", "恭喜你",
    ]

    # OCR 中常见的关键词
    QUESTION_MARKERS = ["题目", "问题", "question", "题干", "第", "Q:", "Q："]
    MY_ANSWER_MARKERS = ["我的答案", "你的答案", "选择的答案", "所选答案", "your answer", "my answer", "你选了"]
    CORRECT_ANSWER_MARKERS = ["正确答案", "correct answer"]
    # "答案" 作为兜底但排除"我的答案""你的答案"等情况
    FALLBACK_ANSWER_MARKER = "答案"
    # 解析行——单独提取
    EXPLANATION_MARKERS = ["解析", "解释", "explanation"]
    AREA_KEYWORDS = {
        "整合管理": ["整合", "章程", "变更控制", "知识管理", "收尾"],
        "范围管理": ["范围", "WBS", "需求", "可交付", "范围基准"],
        "进度管理": ["进度", "关键路径", "CPM", "赶工", "快速跟进", "浮动时间"],
        "成本管理": ["成本", "挣值", "EVM", "EAC", "CPI", "SPI", "预算"],
        "质量管理": ["质量", "因果图", "控制图", "帕累托", "鱼骨图", "缺陷"],
        "资源管理": ["资源", "团队", "RACI", "责任分配", "虚拟团队"],
        "沟通管理": ["沟通", "信息分发", "沟通渠道", "报告"],
        "风险管理": ["风险", "应对", "概率", "影响", "储备", "应急"],
        "采购管理": ["采购", "合同", "FFP", "CPFF", "T&M", "供应商"],
        "干系人管理": ["干系人", "利益相关", "参与", "stakeholder"],
        "敏捷/混合方法": ["敏捷", "Scrum", "冲刺", "迭代", "看板", "每日站会"],
        "商业环境": ["商业", "论证", "合规", "收益", "战略", "PESTLE"],
        "领导力/人员": ["领导力", "激励", "Tuckman", "情商", "冲突"],
    }

    # ── 颜色检测阈值 ───────────────────────────────────────

    # HSV 范围（用于检测红/绿标记）
    RED_LOWER_1 = np.array([0, 50, 50])
    RED_UPPER_1 = np.array([10, 255, 255])
    RED_LOWER_2 = np.array([160, 50, 50])
    RED_UPPER_2 = np.array([180, 255, 255])
    GREEN_LOWER = np.array([36, 40, 40])
    GREEN_UPPER = np.array([86, 255, 255])

    # 颜色判定阈值：红/绿像素占比超过此值即认为有标记
    COLOR_THRESHOLD = 0.03          # 3% 的像素是红/绿 → 有颜色标记
    DOMINANCE_RATIO = 1.5           # 红:绿 > 1.5 → 判错；绿:红 > 1.5 → 判对

    def __init__(self):
        self._cached_result: dict | None = None

    # ── 公开 API ──────────────────────────────────────────

    def validate(
        self,
        image: Image.Image,
        ocr_text: str | None = None,
    ) -> dict:
        """
        分析图片，判断答案是否正确。

        Args:
            image: PIL Image（原始/压缩后的都行，用于颜色检测）
            ocr_text: OCR 提取的文字（如果已执行过 OCR）

        Returns:
            {
                "is_correct": bool | None,    # True=对, False=错, None=无法判断
                "confidence": float,           # 0.0 ~ 1.0
                "signals": [...],              # 匹配到的信号列表
                "primary_signal": str,         # 最强的判定信号
                "method": "text" | "color" | "text+color" | "none",
                "extracted": {                 # 提取到的题目信息
                    "question": str | None,
                    "my_answer": str | None,
                    "correct_answer": str | None,
                    "knowledge_area": str | None,
                    "explanation": str | None,
                },
                "auto_action": "log_error" | "log_mastered" | "none",
            }
        """
        if self._cached_result is not None:
            return self._cached_result

        signals: list[dict] = []
        text = ocr_text or ""

        # ── 1. 颜色检测（优先）──────────────────────────────
        color_result = self._detect_color_signal(image)
        if color_result["has_signal"]:
            signals.append(color_result)

        # ── 2. 文字标签检测 ────────────────────────────────
        if text:
            text_signals = self._detect_text_signals(text)
            signals.extend(text_signals)

        # ── 3. 综合判定 ────────────────────────────────────
        verdict = self._synthesize_verdict(signals)

        # ── 4. 提取题目信息（仅答错时有用）─────────────────
        extracted = {}
        if text and not verdict["is_correct"]:
            extracted = self._extract_question_info(text)

        # ── 5. 自动动作 ────────────────────────────────────
        if verdict["is_correct"] is False and verdict["confidence"] >= 0.6:
            auto_action = "log_error"
        elif verdict["is_correct"] is True and verdict["confidence"] >= 0.6:
            auto_action = "log_mastered"
        else:
            auto_action = "none"

        result = {
            "is_correct": verdict["is_correct"],
            "confidence": verdict["confidence"],
            "signals": signals,
            "primary_signal": verdict["primary_signal"],
            "method": verdict["method"],
            "extracted": extracted,
            "auto_action": auto_action,
            "human_confirm": verdict["confidence"] < 0.8,
        }

        self._cached_result = result
        return result

    # ── 颜色检测 ──────────────────────────────────────────

    def _detect_color_signal(self, image: Image.Image) -> dict:
        """
        检测图片中是否存在红/绿色正确答案/错误答案标记。

        中国主流刷题 App（粉笔、对啊、万题库等）的 UI 模式：
        - 答错：选项背景或边框变红，出现红色 ×
        - 答对：选项背景或边框变绿，出现绿色 ✓
        """
        try:
            # 转 HSV
            img_rgb = image.convert("RGB")
            arr = np.array(img_rgb)

            # 用 PIL 的 ImageStat 做快速通道分析
            r_band = arr[:, :, 0].astype(float)
            g_band = arr[:, :, 1].astype(float)
            b_band = arr[:, :, 2].astype(float)

            # 红色判断：R 显著高于 G 和 B
            # 典型红色标记: R > 180, G < 100, B < 100
            red_mask = (
                (r_band > 150) &
                (g_band < 120) &
                (b_band < 120) &
                (r_band - g_band > 50) &
                (r_band - b_band > 50)
            )
            # 绿色判断：G 显著高于 R 和 B
            green_mask = (
                (g_band > 130) &
                (r_band < 120) &
                (b_band < 120) &
                (g_band - r_band > 40) &
                (g_band - b_band > 40)
            )

            total_pixels = arr.shape[0] * arr.shape[1]
            red_pct = red_mask.sum() / total_pixels
            green_pct = green_mask.sum() / total_pixels

            result = {
                "type": "color",
                "red_pct": round(red_pct, 4),
                "green_pct": round(green_pct, 4),
                "has_signal": False,
            }

            # 需要信号足够强才判定
            if red_pct >= self.COLOR_THRESHOLD or green_pct >= self.COLOR_THRESHOLD:
                result["has_signal"] = True
                if red_pct >= green_pct * self.DOMINANCE_RATIO:
                    result["verdict"] = "wrong"
                    result["detail"] = f"红色标记占 {red_pct:.1%}，绿色 {green_pct:.1%}"
                elif green_pct >= red_pct * self.DOMINANCE_RATIO:
                    result["verdict"] = "correct"
                    result["detail"] = f"绿色标记占 {green_pct:.1%}，红色 {red_pct:.1%}"
                else:
                    result["verdict"] = "ambiguous"
                    result["detail"] = f"红绿比例接近（红{red_pct:.1%} 绿{green_pct:.1%}）"
            else:
                result["verdict"] = "no_color_signal"
                result["detail"] = f"未检测到明显红/绿标记（红{red_pct:.1%} 绿{green_pct:.1%}）"

            return result

        except Exception as e:
            logger.debug("Color detection failed: %s", e)
            return {
                "type": "color",
                "has_signal": False,
                "verdict": "error",
                "detail": str(e),
            }

    # ── 文字信号检测 ──────────────────────────────────────

    def _detect_text_signals(self, text: str) -> list[dict]:
        """从 OCR 文字中检测答对/答错信号"""
        signals: list[dict] = []
        text_lower = text.lower()

        # 排除"正确答案"中的"正确"——不应该算作答对信号
        def text_without_noise(s: str) -> str:
            """移除会干扰判定的短语"""
            return s.replace("正确答案", "").replace("correct answer", "")

        clean_text = text_without_noise(text)
        clean_lower = clean_text.lower()

        # 1. 精确标签
        for label in self.WRONG_LABELS:
            if label.lower() in text_lower:
                signals.append({
                    "type": "text_label",
                    "verdict": "wrong",
                    "matched": label,
                    "detail": f'OCR 文字中包含"{label}"',
                })
                break  # 找到一个就够了

        for label in self.CORRECT_LABELS:
            if label.lower() in clean_lower:
                signals.append({
                    "type": "text_label",
                    "verdict": "correct",
                    "matched": label,
                    "detail": f'OCR 文字中包含"{label}"',
                })
                break

        # 2. 我的答案 vs 正确答案 对比
        my_answer = self._find_answer(text, self.MY_ANSWER_MARKERS)
        correct_answer = self._find_answer(text, self.CORRECT_ANSWER_MARKERS)
        if not correct_answer:
            correct_answer = self._find_answer(text, [self.FALLBACK_ANSWER_MARKER])

        if my_answer and correct_answer:
            my_letter = self._extract_option_letter(my_answer)
            correct_letter = self._extract_option_letter(correct_answer, prefer_last=True)

            if my_letter and correct_letter:
                if my_letter.upper() != correct_letter.upper():
                    signals.append({
                        "type": "answer_comparison",
                        "verdict": "wrong",
                        "matched": f"{my_letter}≠{correct_letter}",
                        "detail": f'你的答案 "{my_letter}" ≠ 正确答案 "{correct_letter}"',
                        "my_answer": my_letter.upper(),
                        "correct_answer": correct_letter.upper(),
                    })
                else:
                    signals.append({
                        "type": "answer_comparison",
                        "verdict": "correct",
                        "matched": f"{my_letter}={correct_letter}",
                        "detail": f'你的答案 "{my_letter}" = 正确答案 "{correct_letter}"',
                    })

        # 3. 符号标记
        for char in ["✗", "✘", "×", "❌"]:
            if char in text and "√" not in text and "✓" not in text:
                signals.append({
                    "type": "symbol",
                    "verdict": "wrong",
                    "matched": char,
                    "detail": f"发现错误标记符号",
                })
                break

        return signals

    def _find_answer(self, text: str, markers: list[str]) -> str | None:
        """从文本中找到答案行。排除"我的答案"等干扰。"""
        lines = text.split("\n")
        for i, line in enumerate(lines):
            for marker in markers:
                if marker not in line:
                    continue
                # 用正则找出所有匹配位置，过滤掉"我的答案""你的答案"中的"答案"
                for m in re.finditer(re.escape(marker), line):
                    start = m.start()
                    if start > 0:
                        prefix = line[:start]
                        # "答案"在"我的/你的"后面 → 跳过
                        if marker == "答案" and re.search(r'(我的|你的|正确|参考)\s*$', prefix):
                            continue
                    # 找到有效匹配
                    combined = line
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        if len(next_line) < 50 and next_line:
                            combined += " " + next_line
                    return combined
        return None

    def _extract_option_letter(self, text: str, prefer_last: bool = False) -> str | None:
        """
        提取选项字母。

        Args:
            text: 包含选项字母的文本
            prefer_last: True=优先取最后一个字母（用于正确答案提取，
                         因为"正确答案: B"中的B通常在文本末尾）
        """
        # 匹配独立字母
        matches = list(re.finditer(r'\b([A-Ea-e])\b', text))

        if not matches:
            # 尝试括号匹配
            matches_paren = list(re.finditer(r'[（(]([A-Ea-e])[）)]', text))
            if matches_paren:
                return matches_paren[-1 if prefer_last else 0].group(1).upper()
            return None

        if prefer_last:
            return matches[-1].group(1).upper()
        return matches[0].group(1).upper()

    # ── 题目信息提取 ──────────────────────────────────────

    def _extract_question_info(self, text: str) -> dict:
        """从 OCR 文字中提取题目、选项、解析等信息"""
        lines = text.split("\n")

        # 提取题目文字
        question = None
        for i, line in enumerate(lines):
            for marker in self.QUESTION_MARKERS:
                if marker in line:
                    # 取这一行 + 接下来直到遇到选项的行
                    parts = [line]
                    for j in range(i + 1, min(i + 5, len(lines))):
                        next_line = lines[j].strip()
                        if re.match(r'^[A-E][.、．)]', next_line):
                            break
                        if next_line:
                            parts.append(next_line)
                    question = " ".join(parts)
                    break
            if question:
                break

        if not question:
            # 退而求其次：取前 3 行非空行
            question = " ".join(lines[:3])

        # 提取我的答案
        my_answer = self._find_answer(text, self.MY_ANSWER_MARKERS)
        my_letter = self._extract_option_letter(my_answer or "") if my_answer else None

        # 提取正确答案（先用精确标记，再用"答案"兜底）
        correct_answer = self._find_answer(text, self.CORRECT_ANSWER_MARKERS)
        if not correct_answer:
            correct_answer = self._find_answer(text, [self.FALLBACK_ANSWER_MARKER])
        correct_letter = self._extract_option_letter(correct_answer or "", prefer_last=True) if correct_answer else None

        # 提取解析
        explanation = None
        for i, line in enumerate(lines):
            for marker in self.EXPLANATION_MARKERS:
                if marker in line:
                    exp_parts = [line]
                    for j in range(i + 1, min(i + 5, len(lines))):
                        next_line = lines[j].strip()
                        if len(next_line) < 5:
                            break
                        exp_parts.append(next_line)
                    explanation = " ".join(exp_parts)[:200]
                    break
            if explanation:
                break

        # 推断知识领域
        knowledge_area = self._classify_knowledge_area(text)

        return {
            "question": question[:200] if question else None,
            "my_answer": my_letter,
            "correct_answer": correct_letter,
            "my_answer_raw": my_answer,
            "correct_answer_raw": correct_answer,
            "knowledge_area": knowledge_area,
            "explanation": explanation,
        }

    def _classify_knowledge_area(self, text: str) -> str:
        """从 OCR 文本中推断知识领域"""
        scores = {}
        text_lower = text.lower()
        for area, keywords in self.AREA_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > 0:
                scores[area] = score

        if not scores:
            return "未分类"

        return max(scores, key=scores.get)

    # ── 综合判定 ──────────────────────────────────────────

    def _synthesize_verdict(self, signals: list[dict]) -> dict:
        """
        综合所有信号，给出最终判定。

        规则（优先级从高到低）：
        1. 颜色信号 + 文字信号一致 → 高置信度
        2. 颜色信号单独 → 中高置信度
        3. "答案对比"信号 → 高置信度
        4. 文字标签信号 → 中置信度
        5. 符号信号 → 低置信度
        6. 信号冲突 → 置信度降低，标记为需要人工确认
        """
        if not signals:
            return {
                "is_correct": None,
                "confidence": 0.0,
                "primary_signal": "无信号",
                "method": "none",
            }

        # 按置信度权重打分
        weights = {
            "answer_comparison": 0.95,
            "text_label": 0.85,
            "color": 0.80,
            "symbol": 0.50,
        }

        wrong_score = 0.0
        correct_score = 0.0
        signal_types_used = set()

        for s in signals:
            stype = s["type"]
            weight = weights.get(stype, 0.5)
            signal_types_used.add(stype)

            if s["verdict"] == "wrong":
                wrong_score += weight
            elif s["verdict"] == "correct":
                correct_score += weight

        # 多信号加成
        if len(signal_types_used) >= 2:
            wrong_score *= 1.15
            correct_score *= 1.15

        # 冲突检测
        has_conflict = wrong_score > 0 and correct_score > 0
        conflict_penalty = 0.5 if has_conflict else 1.0

        total = wrong_score + correct_score
        if total == 0:
            return {
                "is_correct": None,
                "confidence": 0.0,
                "primary_signal": "信号无效",
                "method": "none",
            }

        if wrong_score > correct_score:
            confidence = min(0.98, (wrong_score / (wrong_score + correct_score)) * conflict_penalty)
            return {
                "is_correct": False,
                "confidence": round(confidence, 2),
                "primary_signal": self._describe_primary(signals, "wrong"),
                "method": "text+color" if "color" in signal_types_used else "text",
            }
        elif correct_score > wrong_score:
            confidence = min(0.98, (correct_score / (wrong_score + correct_score)) * conflict_penalty)
            return {
                "is_correct": True,
                "confidence": round(confidence, 2),
                "primary_signal": self._describe_primary(signals, "correct"),
                "method": "text+color" if "color" in signal_types_used else "text",
            }
        else:
            return {
                "is_correct": None,
                "confidence": 0.3,
                "primary_signal": "信号冲突",
                "method": "text+color" if "color" in signal_types_used else "text",
            }

    def _describe_primary(self, signals: list[dict], verdict: str) -> str:
        """描述主要判定依据"""
        matching = [s for s in signals if s["verdict"] == verdict]
        if not matching:
            return "未知"
        # 找最高质量的信号
        priority = ["answer_comparison", "color", "text_label", "symbol"]
        for p in priority:
            for s in matching:
                if s["type"] == p:
                    return s.get("detail", s["type"])
        return matching[0].get("detail", matching[0]["type"])


# ═══════════════════════════════════════════════════════════
# 一键处理：压缩 + OCR + 答题验证 + 错题记录（集成入口）
# ═══════════════════════════════════════════════════════════

def process_and_validate(
    input_path: str | Path,
    output_path: str | Path | None = None,
    run_ocr: bool = True,
    validate_answer: bool = True,
    auto_log_errors: bool = True,
) -> dict:
    """
    一站式处理：压缩 → OCR → 验证答案 → 错题记录。

    Args:
        input_path: 输入图片路径
        output_path: 输出图片路径
        run_ocr: 是否执行 OCR
        validate_answer: 是否验证答案正误
        auto_log_errors: 答错时是否自动调用 error_logger

    Returns:
        完整处理结果字典
    """
    processor = ImageProcessor()
    result = processor.process(input_path, output_path, run_ocr)

    if not result["success"]:
        return result

    if validate_answer:
        try:
            img = Image.open(input_path)
            validator = AnswerValidator()
            validation = validator.validate(img, result.get("ocr_text"))
            result["answer_validation"] = validation

            # 自动记录错题
            if (auto_log_errors and
                    validation["auto_action"] == "log_error" and
                    validation["extracted"].get("question")):

                ext = validation["extracted"]
                if ext.get("my_answer") and ext.get("correct_answer"):
                    try:
                        from .error_logger import ErrorLogger
                        el = ErrorLogger()
                        record = el.add(
                            question=ext["question"] or "（OCR 题目提取不完整，请手动补充）",
                            my_answer=ext["my_answer"],
                            correct_answer=ext["correct_answer"],
                            knowledge_area=ext.get("knowledge_area", "未分类"),
                            explanation=ext.get("explanation", ""),
                            parsed_by="ocr_validator",
                        )
                        validation["error_log_record_id"] = record["id"]
                        logger.info("Auto-logged error #%d via answer validator", record["id"])
                    except Exception as e:
                        logger.warning("Auto error-log failed: %s", e)

        except Exception as e:
            result["answer_validation"] = {
                "is_correct": None,
                "confidence": 0.0,
                "error": str(e),
            }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="微信图片预处理：压缩 + OCR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 压缩图片到 1500px，输出到默认目录
  python image_processor.py screenshot.png

  # 指定输出路径
  python image_processor.py large_photo.jpg -o compressed.jpg

  # 不执行 OCR（纯压缩）
  python image_processor.py diagram.png --no-ocr

  # 自定义最大尺寸
  python image_processor.py photo.jpg --max-size 1200

  # JSON 输出（供程序调用）
  python image_processor.py photo.jpg --json
""",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None, help="输出图片路径"
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE,
        help=f"最大边长（默认 {DEFAULT_MAX_SIZE}）",
    )
    parser.add_argument(
        "--no-ocr", action="store_true", help="跳过 OCR"
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_JPEG_QUALITY,
        help=f"JPEG 质量 1-100（默认 {DEFAULT_JPEG_QUALITY}）",
    )
    parser.add_argument(
        "--json", action="store_true", help="以 JSON 格式输出结果"
    )
    parser.add_argument(
        "--ocr-only",
        action="store_true",
        help="仅 OCR，不压缩（图片已是压缩后的）",
    )
    parser.add_argument(
        "--validate", "-v",
        action="store_true",
        default=True,
        help="自动识别答对/答错（默认开启）",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="跳过答题验证",
    )
    parser.add_argument(
        "--no-auto-log",
        action="store_true",
        help="答错时不自动记录到错题本",
    )

    subp = parser.add_subparsers(dest="mode", help="子模式")

    # validate 子命令：仅验证已有 OCR 文本或图片
    p_val = subp.add_parser("validate", help="仅验证答案正误（不做压缩）")
    p_val.add_argument("image_path", type=str, help="图片路径")
    p_val.add_argument("--ocr-text", type=str, help="已有的 OCR 文本（跳过 OCR）")
    p_val.add_argument("--json", action="store_true", help="JSON 输出")

    # 默认模式需要 input
    parser.add_argument("input", nargs="?", type=str, help="输入图片路径")

    args = parser.parse_args()

    # ── validate 子命令 ───────────────────────────────────
    if args.mode == "validate":
        img = Image.open(args.image_path)
        validator = AnswerValidator()
        ocr_text = args.ocr_text
        if not ocr_text:
            # 临时做 OCR
            processor = ImageProcessor()
            ocr_text = processor._ocr(img)

        result = validator.validate(img, ocr_text)
        result["ocr_text"] = ocr_text

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            verdict_str = {
                True: "✅ 答对了",
                False: "❌ 答错了",
                None: "⚠️ 无法判断",
            }
            print(verdict_str.get(result["is_correct"], "?"))
            print(f"   置信度: {result['confidence']:.0%}")
            print(f"   信号: {result['primary_signal']}")
            print(f"   方法: {result['method']}")
            if result["auto_action"] == "log_error":
                print(f"   🔧 建议: 自动记录错题")
                ext = result.get("extracted", {})
                if ext.get("my_answer"):
                    print(f"   你的答案: {ext['my_answer']} → 正确答案: {ext['correct_answer']}")
                if ext.get("knowledge_area"):
                    print(f"   知识领域: {ext['knowledge_area']}")
        return

    # ── 完整管线：压缩 + OCR + 验证 ───────────────────────
    if not args.input:
        parser.print_help()
        sys.exit(1)

    do_validate = not args.no_validate and getattr(args, "validate", True)
    auto_log = not args.no_auto_log

    result = process_and_validate(
        args.input,
        output_path=args.output,
        run_ocr=not args.no_ocr,
        validate_answer=do_validate,
        auto_log_errors=auto_log,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["success"]:
            orig = result["original_size"]
            proc = result["processed_size"]
            orig_kb = result["original_bytes"] / 1024
            proc_kb = result["processed_bytes"] / 1024

            print(f"✅ 压缩完成")
            print(f"   原始: {orig[0]}x{orig[1]} ({orig_kb:.0f} KB)")
            print(f"   压缩后: {proc[0]}x{proc[1]} ({proc_kb:.0f} KB)")
            print(f"   输出: {result['processed_path']}")

            if result.get("ocr_text"):
                print(f"\n📝 OCR 识别文字:")
                print("─" * 40)
                print(result["ocr_text"])
                print("─" * 40)

            # 显示验证结果
            validation = result.get("answer_validation")
            if validation:
                verdict_str = {
                    True: "✅ 答对了",
                    False: "❌ 答错了",
                    None: "⚠️ 无法判断",
                }
                print(f"\n🎯 答题判定: {verdict_str.get(validation.get('is_correct'), '?')}")
                print(f"   置信度: {validation.get('confidence', 0):.0%}")
                print(f"   依据: {validation.get('primary_signal', '')}")
                if validation.get("auto_action") == "log_error":
                    rid = validation.get("error_log_record_id", "?")
                    print(f"   📝 已自动记录错题 #{rid}")
                elif validation.get("auto_action") == "log_mastered":
                    print(f"   🏆 已掌握，不记录错题")
        else:
            print(f"❌ 处理失败: {result.get('error', 'unknown')}")
            sys.exit(1)


if __name__ == "__main__":
    main()
