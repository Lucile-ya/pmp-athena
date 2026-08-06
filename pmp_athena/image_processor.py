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


def clean_explanation_text(text: str, *, max_len: int = 150) -> str:
    """清理 OCR 解析文本，去掉 UI 垃圾和「解析:」前缀。"""
    if not text:
        return ""
    expl = re.sub(r"^解析\s*[:：]\s*", "", text.strip())
    expl = re.split(r"[\$《<]|(?:\d+\s*)?\d+/\d+\s*$", expl)[0]
    expl = re.sub(r"\s+", " ", expl).strip()
    return expl[:max_len]


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
        """OCR：预处理 + 双通道取最优（不合并，避免垃圾行干扰）。"""
        if not HAS_OCR:
            return ""

        try:
            gray = self.preprocess_for_ocr(image)
            best_text = ""
            best_score = -1

            for cfg in ("", "--psm 6"):
                try:
                    if cfg:
                        raw = pytesseract.image_to_string(
                            gray, lang="chi_sim+eng", config=cfg,
                        )
                    else:
                        raw = pytesseract.image_to_string(gray, lang="chi_sim+eng")
                except Exception as e:
                    logger.debug("OCR pass failed (%s): %s", cfg or "default", e)
                    continue

                score = sum(
                    1 for m in (
                        "正确答案", "我的答", "单选题", "多选题", "作答错误", "解析",
                    ) if m in raw
                )
                if score > best_score or (score == best_score and len(raw) > len(best_text)):
                    best_text = raw
                    best_score = score

            lines = [line.strip() for line in best_text.split("\n") if line.strip()]
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
        "答错", "错误", "选错", "做错", "答错了", "作答错误",
        "incorrect", "wrong", "❌", "✗", "✘", "×",
        "你答错了", "回答错误", "不是正确答案", "单选作答错误", "多选作答错误",
    ]

    CORRECT_LABELS = [
        "答对", "正确", "选对", "做对", "答对了",
        "correct", "right", "✅", "✓", "✔", "√", "☑",
        "你答对了", "回答正确", "恭喜你",
    ]

    # OCR 中常见的关键词
    QUESTION_MARKERS = [
        "题目", "问题", "question", "题干", "第", "Q:", "Q：",
        "单选题", "多选题", "判断题",
    ]
    QUESTION_TYPE_MARKERS = ["单选题", "多选题", "判断题"]
    MY_ANSWER_MARKERS = [
        "我的答案", "你的答案", "你上次的选择", "上次的选择", "上次选择",
        "选择的答案", "所选答案", "your answer", "my answer", "你选了",
    ]
    _MY_ANSWER_LABEL = (
        r"(?:我的答[案家]|你上次的选择|上次的选择|上次选择|你的答案|选择的答案|所选答案)"
    )
    CORRECT_ANSWER_MARKERS = ["正确答案", "correct answer"]
    # "答案" 作为兜底但排除"我的答案""你的答案"等情况
    FALLBACK_ANSWER_MARKER = "答案"
    # 解析行——单独提取
    EXPLANATION_MARKERS = ["解析", "收缩解析", "解释", "explanation"]
    # 有效选项（单选题 A-D；多选题可含 E）
    VALID_CHOICES = frozenset("ABCDE")
    VALID_CHOICES_SINGLE = frozenset("ABCD")
    # 选项字母后不能紧跟 .．、（避免「我的答案: A.专家」误匹配）
    _CHOICE_TAIL = r"(?![.．、])"
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

    CAPTION_WRONG_MARKERS = ("选错了", "这题错了", "这题做错了", "答错了", "我做错了")

    def validate(
        self,
        image: Image.Image,
        ocr_text: str | None = None,
        user_caption: str | None = None,
    ) -> dict:
        """
        分析图片，判断答案是否正确。

        Args:
            image: PIL Image（原始/压缩后的都行，用于颜色检测）
            ocr_text: OCR 提取的文字（如果已执行过 OCR）
            user_caption: 用户发图时的配文（如「我的答案是A，正确答案是B」）

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

        # ── 4. 提取题目信息（无论对错都提取，用于题库记录）───
        extracted = {}
        answer_meta: dict = {}
        if text:
            extracted = self._extract_question_info(text)
            answer_meta = extracted.pop("answer_confidence", {})

        if user_caption and user_caption.strip():
            verdict, extracted, answer_meta = self._apply_caption_hints(
                verdict, extracted, answer_meta, user_caption.strip()
            )

        # ── 5. 自动动作 ────────────────────────────────────
        my_conf = float(answer_meta.get("my", 0) or 0)
        correct_conf = float(answer_meta.get("correct", 0) or 0)
        can_auto_log = (
            extracted.get("my_answer")
            and extracted.get("correct_answer")
            and my_conf >= 0.75
            and correct_conf >= 0.85
        )

        if verdict["is_correct"] is False and verdict["confidence"] >= 0.6 and can_auto_log:
            auto_action = "log_error"
        elif verdict["is_correct"] is True and verdict["confidence"] >= 0.6:
            auto_action = "log_mastered"
        else:
            auto_action = "none"

        needs_confirm = (
            verdict["confidence"] < 0.8
            or not can_auto_log
            or answer_meta.get("needs_user_confirm")
            or (verdict["is_correct"] is False and not extracted.get("my_answer"))
        )

        if answer_meta.get("needs_user_confirm"):
            auto_action = "none"

        screenshot_type = self.classify_screenshot_type(text) if text else "unknown"
        if (
            user_caption
            and extracted.get("my_answer")
            and extracted.get("correct_answer")
            and my_conf >= 0.95
            and correct_conf >= 0.95
        ):
            # 配文明确给出双答案 → 走错题入库，即便 OCR 判为纯题干
            screenshot_type = "error_result"

        result = {
            "is_correct": verdict["is_correct"],
            "confidence": verdict["confidence"],
            "signals": signals,
            "primary_signal": verdict["primary_signal"],
            "method": verdict["method"],
            "extracted": extracted,
            "answer_confidence": answer_meta,
            "auto_action": auto_action,
            "human_confirm": needs_confirm,
            "needs_user_confirm": bool(answer_meta.get("needs_user_confirm")),
            "screenshot_type": screenshot_type,
            "formatted_question": (
                self.format_question_for_display(extracted)
                if screenshot_type == "plain_question"
                else None
            ),
        }

        self._cached_result = result
        return result

    def _apply_caption_hints(
        self,
        verdict: dict,
        extracted: dict,
        answer_meta: dict,
        caption: str,
    ) -> tuple[dict, dict, dict]:
        """合并用户发图配文中的答案信息（用户纠正 > OCR）。"""
        try:
            from pmp_athena.plain_question_store import parse_both_answers, parse_my_answer
        except ImportError:
            from plain_question_store import parse_both_answers, parse_my_answer

        my, correct = parse_both_answers(caption)
        if not my:
            my = parse_my_answer(caption)

        if not correct:
            m = re.search(r"正确(?:答案)?[是为：:\s]*([A-Ea-e])", caption, re.IGNORECASE)
            if m:
                correct = m.group(1).upper()

        explicit_wrong = any(m in caption for m in self.CAPTION_WRONG_MARKERS)
        explicit_error_log = any(
            k in caption for k in ("录入错题", "录错题", "错题录入", "截图录入")
        )

        if my and correct:
            extracted["my_answer"] = my
            extracted["correct_answer"] = correct
            answer_meta["my"] = 0.98
            answer_meta["correct"] = 0.98
            answer_meta["my_method"] = "caption"
            answer_meta["correct_method"] = "caption"
            answer_meta["needs_user_confirm"] = False
            verdict["is_correct"] = my == correct
            verdict["confidence"] = max(float(verdict.get("confidence", 0) or 0), 0.95)
            verdict["primary_signal"] = "caption_both_answers"
        elif correct and not extracted.get("correct_answer"):
            extracted["correct_answer"] = correct
            answer_meta["correct"] = 0.95
            answer_meta["correct_method"] = "caption"
        elif my and not extracted.get("my_answer"):
            extracted["my_answer"] = my
            answer_meta["my"] = 0.95
            answer_meta["my_method"] = "caption"

        if explicit_wrong or explicit_error_log:
            if extracted.get("my_answer") and extracted.get("correct_answer"):
                verdict["is_correct"] = (
                    extracted["my_answer"] == extracted["correct_answer"]
                )
                verdict["confidence"] = max(
                    float(verdict.get("confidence", 0) or 0), 0.85
                )
            elif explicit_wrong and my:
                verdict["is_correct"] = False
                verdict["confidence"] = max(
                    float(verdict.get("confidence", 0) or 0), 0.75
                )

        return verdict, extracted, answer_meta

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

        # 2. 我的答案 vs 正确答案 对比（多策略稳定提取）
        resolved = self._resolve_answers(text)
        my_letter = resolved["my_answer"]
        correct_letter = resolved["correct_answer"]
        has_wrong_label = any(
            s["type"] == "text_label" and s["verdict"] == "wrong" for s in signals
        )

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
            elif not has_wrong_label:
                signals.append({
                    "type": "answer_comparison",
                    "verdict": "correct",
                    "matched": f"{my_letter}={correct_letter}",
                    "detail": f'你的答案 "{my_letter}" = 正确答案 "{correct_letter}"',
                })
        elif correct_letter and has_wrong_label:
            signals.append({
                "type": "answer_comparison",
                "verdict": "wrong",
                "matched": f"?≠{correct_letter}",
                "detail": f'作答错误，正确答案 "{correct_letter}"',
                "my_answer": my_letter,
                "correct_answer": correct_letter.upper(),
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

    def _normalize_answer_text(self, text: str) -> str:
        """OCR 答案区常见错字归一。"""
        return (
            text.replace("我的答家", "我的答案")
            .replace("正确答案，", "正确答案:")
            .replace("正确答案,", "正确答案:")
            .replace("你上次的选择", "我的答案")
            .replace("上次的选择", "我的答案")
        )

    def _is_valid_choice(self, letter: str | None) -> bool:
        return bool(letter and letter.upper() in self.VALID_CHOICES)

    def _extract_labeled_correct(self, text: str) -> str | None:
        """优先从「正确答案：X」标注行提取（仅 A-E）。"""
        normalized = self._normalize_answer_text(text)
        compact = re.sub(r"\s+", " ", normalized)

        combo = re.search(
            rf"正确答案\s*[:：,，]?\s*([A-Ea-e])\1?{self._CHOICE_TAIL}",
            compact,
        )
        if combo and self._is_valid_choice(combo.group(1)):
            return combo.group(1).upper()

        for line in normalized.split("\n"):
            if "正确答案" not in line:
                continue
            m = re.search(r"正确答案\s*[:：,，]?\s*([A-Ea-e])\1?", line)
            if m and self._is_valid_choice(m.group(1)):
                return m.group(1).upper()

        return None

    def _extract_labeled_my(self, text: str) -> str | None:
        """从「我的答案 / 你上次的选择」等标注行提取（仅 A-E）。"""
        normalized = self._normalize_answer_text(text)
        compact = re.sub(r"\s+", " ", normalized)

        combo = re.search(
            rf"{self._MY_ANSWER_LABEL}\s*[:：,，]?\s*([A-Ea-e])\1?{self._CHOICE_TAIL}",
            compact,
        )
        if combo and self._is_valid_choice(combo.group(1)):
            return combo.group(1).upper()

        lines = normalized.split("\n")
        for i, line in enumerate(lines):
            if not re.search(self._MY_ANSWER_LABEL, line):
                continue
            m = re.search(
                rf"{self._MY_ANSWER_LABEL}\s*[:：,，]?\s*([A-Ea-e])\1?{self._CHOICE_TAIL}",
                line,
            )
            if m and self._is_valid_choice(m.group(1)):
                return m.group(1).upper()
            for j in range(i + 1, min(i + 3, len(lines))):
                nxt = lines[j].strip()
                if re.match(r"^[A-Ea-e]{1,2}$", nxt) and self._is_valid_choice(nxt[0]):
                    return nxt[0].upper()
                if nxt.startswith("解析") or nxt.startswith("收缩解析"):
                    break
        return None

    def _extract_answer_letters(self, text: str) -> tuple[str | None, str | None]:
        """从 OCR 标注行提取答案（正确答案优先于我的答案）。"""
        return self._extract_labeled_my(text), self._extract_labeled_correct(text)

    def _resolve_answers(self, text: str) -> dict:
        """
        OCR 答案纠偏（标注行 > 选项推断 > 用户确认）。

        纠偏顺序：
        1. 「正确答案：X」标注行（权威）
        2. 「我的答案：X」标注行
        3. 选项 @/× 标记推断（仅补全缺失的「我的答案」）
        4. 仍不在 A-E → needs_user_confirm
        """
        corrections: list[str] = []
        has_wrong_label = any(
            lbl in text for lbl in ("作答错误", "答错", "选错", "做错", "回答错误")
        )
        normalized = self._normalize_answer_text(text)
        compact = re.sub(r"\s+", " ", normalized)

        # ── 0. 同行「正确答案 + 我的答案」（最完整）──
        correct_letter: str | None = None
        my_letter: str | None = None
        combo = re.search(
            r"正确答案\s*[:：,，]?\s*([A-Ea-e])\1?\s*"
            rf"{self._MY_ANSWER_LABEL}\s*[:：,，]?\s*([A-Ea-e])\2?{self._CHOICE_TAIL}",
            compact,
        )
        if combo:
            if self._is_valid_choice(combo.group(1)):
                correct_letter = combo.group(1).upper()
            if combo.group(2) and self._is_valid_choice(combo.group(2)):
                my_letter = combo.group(2).upper()

        if not my_letter or not correct_letter:
            combo_rev = re.search(
                rf"{self._MY_ANSWER_LABEL}\s*[:：,，]?\s*([A-Ea-e])\1?\s*"
                r"正确答案\s*[:：,，]?\s*([A-Ea-e])\2?{self._CHOICE_TAIL}",
                compact,
            )
            if combo_rev:
                if self._is_valid_choice(combo_rev.group(1)):
                    my_letter = combo_rev.group(1).upper()
                if combo_rev.group(2) and self._is_valid_choice(combo_rev.group(2)):
                    correct_letter = combo_rev.group(2).upper()

        # ── 1. 标注行（权威来源，覆盖不完整 combo）──
        if not correct_letter:
            correct_letter = self._extract_labeled_correct(text)
        if not my_letter:
            my_letter = self._extract_labeled_my(text)
        correct_method = "labeled_correct" if correct_letter else ""
        my_method = "labeled_my" if my_letter else ""

        correct_conf = 0.98 if correct_letter else 0.0
        my_conf = 0.98 if my_letter else 0.0

        # ── 2. 推断仅补全「我的答案」，永不覆盖标注的正确答案 ──
        inferred: str | None = None
        if my_letter is None and correct_letter and (
            has_wrong_label
            or "我的答案" in text
            or "你上次的选择" in text
            or "上次的选择" in text
        ):
            inferred, inf_conf, inf_method = self._infer_wrong_option_with_confidence(text)
            if inferred and self._is_valid_choice(inferred):
                my_letter = inferred
                my_conf = inf_conf
                my_method = inf_method
                corrections.append(f"my_answer: 标注缺失 → 推断 {inferred}")

        # ── 3. 标注说错但 my==correct → 用推断覆盖 my（不动 correct）──
        if (
            has_wrong_label
            and correct_letter
            and my_letter == correct_letter
        ):
            inferred, inf_conf, inf_method = self._infer_wrong_option_with_confidence(text)
            if inferred and inferred != correct_letter and self._is_valid_choice(inferred):
                old = my_letter
                my_letter = inferred
                my_conf = max(inf_conf, 0.85)
                my_method = inf_method
                corrections.append(f"my_answer: {old}→{inferred} (与正确答案相同，按标注纠偏)")

        needs_user_confirm = False
        if not self._is_valid_choice(correct_letter):
            needs_user_confirm = True
        elif has_wrong_label and not self._is_valid_choice(my_letter):
            needs_user_confirm = True

        return {
            "my_answer": my_letter,
            "correct_answer": correct_letter,
            "my_confidence": round(my_conf, 2),
            "correct_confidence": round(correct_conf, 2),
            "my_method": my_method,
            "correct_method": correct_method,
            "needs_user_confirm": needs_user_confirm,
            "corrections": corrections,
        }

    def _infer_wrong_option_with_confidence(
        self, text: str,
    ) -> tuple[str | None, float, str]:
        """推断用户错选，返回 (字母, 置信度, 方法)。"""
        options = self._parse_options_full(text)
        option_rows: list[tuple[str, str]] = []

        for line in text.split("\n"):
            s = line.strip()
            if not s:
                continue
            if re.match(r"^([A-E])[.、．)]", s):
                option_rows.append(("normal", s))
            elif re.match(r"^[@×✗✘❌]", s):
                option_rows.append(("marked", s))

        for idx, (kind, s) in enumerate(option_rows):
            if kind != "marked":
                continue

            m = re.match(r"^[@×✗✘❌]\s*([A-E])[.、．)]", s)
            if m:
                return m.group(1).upper(), 0.92, "marked_option_letter"

            content = re.sub(r"^[@×✗✘❌]\s*[.、．)]?\s*", "", s).strip()
            by_text = self._match_option_by_text(content, options)
            if by_text:
                return by_text, 0.88, "marked_option_text"

            if idx < 5:
                return ["A", "B", "C", "D", "E"][idx], 0.82, "marked_option_position"

        for s in (row[1] for row in option_rows if row[0] == "normal"):
            m = re.match(r"^([A-E])[.、．)]", s)
            if m and any(c in s for c in ("×", "✗", "✘", "❌", "@")):
                return m.group(1).upper(), 0.85, "option_line_marker"

        return None, 0.0, ""

    def _parse_options_full(self, text: str) -> dict[str, str]:
        """解析全部选项，含 OCR 把 A/C 读成 @ 行的场景。"""
        options = self._parse_options(text)
        option_rows: list[str] = []

        for line in text.split("\n"):
            s = line.strip()
            if re.match(r"^([A-E])[.、．)]", s) or re.match(r"^[@×✗✘❌]", s):
                option_rows.append(s)

        letters = ["A", "B", "C", "D", "E"]
        for idx, row in enumerate(option_rows):
            if idx >= len(letters):
                break
            letter = letters[idx]
            if letter in options:
                continue
            if re.match(r"^[@×✗✘❌]", row):
                content = re.sub(r"^[@×✗✘❌]\s*[.、．)]?\s*", "", row).strip()
                if content:
                    options[letter] = content

        return options

    def _parse_options(self, text: str) -> dict[str, str]:
        """解析 OCR 中的选项 A-E → 选项文字。"""
        options = self._parse_options_lettered(text)
        if len(options) >= 2:
            return options
        return self._parse_options_enumerated(text)

    def _parse_options_lettered(self, text: str) -> dict[str, str]:
        options: dict[str, str] = {}
        for line in text.split("\n"):
            s = line.strip()
            if self._is_ui_noise(s):
                continue
            m = re.match(r"^([A-E])[.、．)]\s*(.+)$", s)
            if m:
                options[m.group(1).upper()] = m.group(2).strip()
        return options

    def _parse_options_enumerated(self, text: str) -> dict[str, str]:
        """
        解析无 A/B/C/D 字母前缀的选项（PDF/Word 截图常见）。

        例：「、以下哪个…?」+「、项目管理计划…」+「批量生产…」
        """
        letters = ["A", "B", "C", "D", "E"]
        options: dict[str, str] = {}
        question_found = False

        for line in text.split("\n"):
            s = line.strip()
            if self._is_ui_noise(s):
                continue

            if "?" in s or "？" in s:
                question_found = True
                continue

            if not question_found:
                continue

            opt = s
            opt = re.sub(r"^([A-E])[、.．)]\s*", "", opt)
            opt = re.sub(r"^[、．.]+\s*", "", opt)
            if len(opt) < 2:
                continue

            letter = letters[len(options)]
            if len(options) >= 5:
                break
            options[letter] = opt

        return options

    def classify_screenshot_type(self, text: str) -> str:
        """
        截图类型：
        - exam_result: 模考成绩截图
        - error_result: 刷题 App 作答结果（含正确答案/我的答案）
        - plain_question: 纯题干+选项（PDF/文档/题库截图）
        - unknown: 无法判定
        """
        if not text or not text.strip():
            return "unknown"

        try:
            from pmp_athena.analyze_exam import detect_exam_screenshot
        except ImportError:
            from analyze_exam import detect_exam_screenshot

        if detect_exam_screenshot(text):
            return "exam_result"

        error_markers = (
            "作答错误", "作答正确", "正确答案", "我的答案", "我的答家",
            "你上次的选择", "上次的选择", "答错了", "单选作答错误", "多选作答错误",
        )
        if any(m in text for m in error_markers):
            return "error_result"

        lines = [l.strip() for l in text.split("\n") if l.strip()]
        question = self._extract_question_body(lines)
        options = self._parse_options_full(text)
        if question and len(options) >= 2:
            return "plain_question"
        return "unknown"

    def _match_option_by_text(
        self,
        content: str,
        options: dict[str, str],
    ) -> str | None:
        """通过选项文字反查字母（处理 C. 被 OCR 成 @ . 的情况）。"""
        norm = re.sub(r"\s+", "", content)
        if len(norm) < 2:
            return None

        best_letter: str | None = None
        best_score = 0
        for letter, opt_text in options.items():
            opt_norm = re.sub(r"\s+", "", opt_text)
            if norm in opt_norm or opt_norm in norm:
                score = min(len(norm), len(opt_norm))
                if score > best_score:
                    best_score = score
                    best_letter = letter

        if best_letter:
            return best_letter

        # 只有一个缺失选项（如 A/B/D 都在、C 被 OCR 成 @ .三点估算）
        all_letters = ["A", "B", "C", "D", "E"]
        missing = [l for l in all_letters if l not in options]
        if len(missing) == 1:
            return missing[0]

        return None

    def _infer_wrong_option(self, text: str) -> str | None:
        """OCR 丢失「我的答案」时，从选项行的错误标记推断用户选择。"""
        letter, _, _ = self._infer_wrong_option_with_confidence(text)
        return letter

    def _is_ui_noise(self, line: str) -> bool:
        """过滤刷题 App 状态栏、导航等干扰行。"""
        s = line.strip()
        if not s or len(s) < 2:
            return True
        noise = (
            r"^\d{1,2}:\d{2}",
            r"^\d{2}:\d{2}:\d{2}",
            r"章节练习",
            r"^返回",
            r"提交并查看",
            r"^下一题",
            r"^\d+/\d+\s*$",
            r"^[<>]",
            r"ODS|wifi|GB\)",
            r"^[口O中记加\s]{1,8}$",  # PDF/文档工具栏 OCR 噪音
        )
        return any(re.search(p, s) for p in noise)

    def _extract_question_body(self, lines: list[str]) -> str | None:
        """从 OCR 行列表中提取题干（跳过状态栏，在选项前截断）。"""
        stop_markers = ("作答错误", "作答正确", "正确答案", "我的答案", "你上次的选择", "解析", "收缩解析")

        for i, line in enumerate(lines):
            for qtype in self.QUESTION_TYPE_MARKERS:
                if qtype not in line:
                    continue
                parts: list[str] = []
                rest = line.split(qtype, 1)[-1].strip()
                if rest and len(rest) > 8 and not self._is_ui_noise(rest):
                    parts.append(rest)
                for j in range(i + 1, len(lines)):
                    nxt = lines[j].strip()
                    if self._is_ui_noise(nxt):
                        continue
                    if re.match(r"^[A-E@][.、．)]", nxt) or re.match(r"^[@×✗✘❌]", nxt):
                        break
                    if any(m in nxt for m in stop_markers):
                        break
                    if nxt:
                        parts.append(nxt)
                if parts:
                    return " ".join(parts)

        # 退而求其次：最长中文段落（选项前）
        best = ""
        for line in lines:
            s = line.strip()
            if self._is_ui_noise(s):
                continue
            if re.match(r"^[A-E@][.、．)]", s) or re.match(r"^[@×✗✘❌]", s):
                break
            if any(m in s for m in stop_markers):
                break
            if len(s) > len(best) and re.search(r"[\u4e00-\u9fff]", s):
                best = s

        # PDF/Word 题号格式：5、以下哪个…? 或 OCR 丢题号「、以下哪个…?」
        for i, line in enumerate(lines):
            s = line.strip()
            if self._is_ui_noise(s):
                continue
            if "?" not in s and "？" not in s:
                continue
            parts: list[str] = []
            for j in range(i - 1, -1, -1):
                prev = lines[j].strip()
                if self._is_ui_noise(prev):
                    break
                if re.match(r"^[A-E@][.、．)]", prev) or re.match(r"^[@×✗✘❌]", prev):
                    break
                if any(m in prev for m in stop_markers):
                    break
                parts.insert(0, prev)
            stem = re.sub(r"^\d+[、.．)]\s*", "", s)
            stem = re.sub(r"^[、．.]+\s*", "", stem)
            parts.append(stem)
            full = " ".join(p for p in parts if p)
            if len(full) >= 8:
                return full

        return best or None

    def format_question_for_display(self, extracted: dict) -> str:
        """格式化纯题目截图（供解析/互动）。"""
        q = extracted.get("question") or "（题干未识别）"
        options = extracted.get("options") or {}
        lines = [f"📝 {q}"]
        for letter in ("A", "B", "C", "D", "E"):
            if letter in options:
                lines.append(f"{letter}. {options[letter]}")
        return "\n".join(lines)

    # ── 题目信息提取 ──────────────────────────────────────

    def _extract_question_info(self, text: str) -> dict:
        """从 OCR 文字中提取题目、选项、解析等信息"""
        lines = text.split("\n")

        question = self._extract_question_body(lines)

        resolved = self._resolve_answers(text)
        my_letter = resolved["my_answer"]
        correct_letter = resolved["correct_answer"]

        # 提取解析
        explanation = None
        for i, line in enumerate(lines):
            for marker in self.EXPLANATION_MARKERS:
                if marker in line:
                    exp_parts = [line]
                    for j in range(i + 1, min(i + 8, len(lines))):
                        next_line = lines[j].strip()
                        if self._is_ui_noise(next_line):
                            break
                        if len(next_line) < 3:
                            break
                        exp_parts.append(next_line)
                    explanation = clean_explanation_text(" ".join(exp_parts), max_len=200)
                    break
            if explanation:
                break

        classify_text = question or text
        knowledge_area = self._classify_knowledge_area(classify_text)
        options = self._parse_options_full(text)

        return {
            "question": question[:200] if question else None,
            "my_answer": my_letter,
            "correct_answer": correct_letter,
            "knowledge_area": knowledge_area,
            "explanation": explanation,
            "options": options,
            "answer_confidence": {
                "my": resolved["my_confidence"],
                "correct": resolved["correct_confidence"],
                "my_method": resolved["my_method"],
                "correct_method": resolved.get("correct_method", ""),
                "needs_user_confirm": resolved.get("needs_user_confirm", False),
                "corrections": resolved.get("corrections", []),
            },
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

        has_wrong_label = any(
            s["type"] == "text_label" and s["verdict"] == "wrong" for s in signals
        )

        for s in signals:
            stype = s["type"]
            weight = weights.get(stype, 0.5)
            signal_types_used.add(stype)

            # OCR 常丢「我的答案」，导致 B=B 误判；有「作答错误」标签时不采信「答对」对比
            if (
                stype == "answer_comparison"
                and s["verdict"] == "correct"
                and has_wrong_label
            ):
                continue

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

_ATTEMPT_KEYWORDS_IMG: dict[str, int] = {
    "一刷": 1, "首次": 1, "第一次": 1,
    "二刷": 2, "第二次": 2, "重刷": 2,
    "三刷": 3, "第三次": 3,
    "四刷": 4, "第四次": 4,
    "五刷": 5, "第五次": 5,
}


def _parse_attempt_from_caption(caption: str | None) -> int:
    """从配文提取 attempt 关键词，未匹配返回 1。"""
    if not caption:
        return 1
    c = caption.lower()
    for kw, n in sorted(_ATTEMPT_KEYWORDS_IMG.items(), key=lambda x: -len(x[0])):
        if kw in c:
            return n
    return 1

def process_and_validate(
    input_path: str | Path,
    output_path: str | Path | None = None,
    run_ocr: bool = True,
    validate_answer: bool = True,
    auto_log_errors: bool = True,
    user_caption: str | None = None,
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

    ocr_text = result.get("ocr_text") or ""
    if ocr_text:
        try:
            from pmp_athena.analyze_exam import detect_exam_screenshot, analyze_exam_screenshot
        except ImportError:
            from analyze_exam import detect_exam_screenshot, analyze_exam_screenshot

        if detect_exam_screenshot(ocr_text):
            exam_result = analyze_exam_screenshot(input_path, save=True)
            result["screenshot_type"] = "exam_result"
            result["exam_analysis"] = exam_result
            if exam_result.get("success"):
                result["exam_report"] = exam_result.get("report")
            return result

    if validate_answer:
        try:
            img = Image.open(input_path)
            validator = AnswerValidator()
            validation = validator.validate(
                img, result.get("ocr_text"), user_caption=user_caption
            )
            result["answer_validation"] = validation

            # 自动记录错题（三文件同步）
            if (
                auto_log_errors
                and validation["auto_action"] == "log_error"
                and validation["extracted"].get("question")
            ):
                ext = validation["extracted"]
                if ext.get("my_answer") and ext.get("correct_answer"):
                    try:
                        try:
                            from .record_answer import record_wrong_answer
                        except ImportError:
                            from record_answer import record_wrong_answer
                        bank_q = ext["question"] or "（OCR 题目提取不完整，请手动补充）"
                        if ext.get("options"):
                            bank_q = AnswerValidator().format_question_for_display(ext)
                            if bank_q.startswith("📝 "):
                                bank_q = bank_q[3:]
                        rec = record_wrong_answer(
                            question=bank_q,
                            my_answer=ext["my_answer"],
                            correct_answer=ext["correct_answer"],
                            knowledge_area=ext.get("knowledge_area", "未分类"),
                            explanation=ext.get("explanation", ""),
                            source="screenshot",
                            parsed_by="ocr_validator",
                            attempt=_parse_attempt_from_caption(user_caption),
                        )
                        validation["error_log_record_id"] = rec["error_log_id"]
                        validation["question_bank_record_id"] = rec["bank_id"]
                        logger.info(
                            "Auto-logged error #%d / bank #%d via record_answer",
                            rec["error_log_id"],
                            rec["bank_id"],
                        )
                    except Exception as e:
                        logger.warning("Auto error-log failed: %s", e)
                elif ext.get("correct_answer"):
                    try:
                        from .question_bank import QuestionBank
                    except ImportError:
                        from question_bank import QuestionBank
                    try:
                        qb = QuestionBank()
                        qb_record = qb.add_from_validation(
                            validation,
                            parsed_by="ocr_validator",
                        )
                        if qb_record:
                            validation["question_bank_record_id"] = qb_record["id"]
                    except Exception as e:
                        logger.warning("Question bank log failed: %s", e)
            elif auto_log_errors and validation.get("is_correct") is True:
                ext = validation.get("extracted", {})
                if ext.get("question") and ext.get("correct_answer"):
                    try:
                        try:
                            from .record_answer import record_correct_answer
                        except ImportError:
                            from record_answer import record_correct_answer
                        rec = record_correct_answer(
                            question=ext["question"],
                            my_answer=ext.get("my_answer") or ext["correct_answer"],
                            correct_answer=ext["correct_answer"],
                            knowledge_area=ext.get("knowledge_area", "未分类"),
                            explanation=ext.get("explanation", ""),
                            source="screenshot",
                            parsed_by="ocr_validator",
                            attempt=_parse_attempt_from_caption(user_caption),
                        )
                        validation["question_bank_record_id"] = rec["bank_id"]
                    except Exception as e:
                        logger.warning("Question bank log failed: %s", e)

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
    parser.add_argument(
        "--caption",
        type=str,
        default=None,
        help="用户发图配文（如：我的答案是A，正确答案是B）",
    )

    # 默认模式：压缩 + OCR + 验证（需要 input）
    parser.add_argument("input", nargs="?", type=str, help="输入图片路径")

    args = parser.parse_args()

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
        user_caption=args.caption,
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
                # 题库记录提示
                qb_id = validation.get("question_bank_record_id")
                if qb_id:
                    print(f"   📋 已记录到题库 #{qb_id}")
        else:
            print(f"❌ 处理失败: {result.get('error', 'unknown')}")
            sys.exit(1)


if __name__ == "__main__":
    main()
