"""
OCR 处理器 —— 对截图/图片进行文字识别并索引入库

依赖：Tesseract OCR
- Windows: 安装 Tesseract 并确保在 PATH 中，或设置 TESSERACT_CMD 环境变量
- macOS: brew install tesseract tesseract-lang
- Linux: apt install tesseract-ocr tesseract-ocr-chi-sim

支持中英文混合识别。
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

from ..config import NOTES_DIR
from ..db.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# 尝试导入 pytesseract
try:
    import pytesseract

    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False
    logger.warning("pytesseract not installed. OCR features disabled.")


class OCRProcessor:
    """图片 OCR 处理器"""

    SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}

    def __init__(
        self,
        notes_dir: Path | None = None,
        lang: str = "chi_sim+eng",
    ):
        """
        Args:
            notes_dir: 图片所在目录
            lang: Tesseract 语言参数，默认中英混合
        """
        self.notes_dir = notes_dir or NOTES_DIR
        self.lang = lang
        self.store = get_vector_store()

        if not HAS_TESSERACT:
            logger.warning(
                "OCR 功能不可用。请安装: pip install pytesseract "
                "并安装 Tesseract OCR 引擎"
            )

    # ── 公开方法 ─────────────────────────────────────────────

    def ingest_all_images(self, reset: bool = False) -> dict:
        """
        扫描并 OCR 所有图片文件。
        返回 {"files": int, "ocr_count": int, "skipped": int}
        """
        if not HAS_TESSERACT:
            return {"files": 0, "ocr_count": 0, "skipped": 0, "error": "pytesseract not installed"}

        if reset:
            self.store.reset_collection("pmp_screenshots")

        image_files = []
        for ext in self.SUPPORTED_EXTENSIONS:
            image_files.extend(self.notes_dir.rglob(f"*{ext}"))
            image_files.extend(self.notes_dir.rglob(f"*{ext.upper()}"))

        if not image_files:
            logger.info("No image files found in %s", self.notes_dir)
            return {"files": 0, "ocr_count": 0, "skipped": 0}

        ocr_count = 0
        skipped = 0
        for filepath in image_files:
            try:
                text = self.ocr_image(filepath)
                if text and text.strip():
                    self._index_ocr_result(filepath, text)
                    ocr_count += 1
                else:
                    skipped += 1
                    logger.info("Empty OCR result for %s, skipped", filepath.name)
            except Exception as e:
                skipped += 1
                logger.error("OCR failed for %s: %s", filepath, e)

        logger.info(
            "OCR done: %d images → %d indexed, %d skipped",
            len(image_files), ocr_count, skipped,
        )
        return {"files": len(image_files), "ocr_count": ocr_count, "skipped": skipped}

    def ocr_image(self, filepath: Path) -> str:
        """
        对单张图片执行 OCR，返回识别文本。

        用户可根据需要扩展此方法，例如：
        - 图像预处理（去噪、二值化、增强对比度）
        - 使用 PaddleOCR 等更高级的 OCR 引擎
        - 分段识别 + 结构化提取
        """
        if not HAS_TESSERACT:
            raise RuntimeError("pytesseract not installed")

        # 打开图像
        image = Image.open(filepath)

        # ── 预处理（可选，按需取消注释）──────────────────────
        # from PIL import ImageFilter, ImageEnhance
        # # 灰度化
        # image = image.convert("L")
        # # 增强对比度
        # enhancer = ImageEnhance.Contrast(image)
        # image = enhancer.enhance(2.0)
        # # 锐化
        # image = image.filter(ImageFilter.SHARPEN)

        # 执行 OCR
        text = pytesseract.image_to_string(image, lang=self.lang)

        # 基本后处理：移除多余空行
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        cleaned = "\n".join(lines)

        logger.info("OCR on %s: %d chars extracted", filepath.name, len(cleaned))
        return cleaned

    def ocr_image_with_preprocess(
        self,
        filepath: Path,
        preprocess: bool = True,
    ) -> str:
        """
        带预处理的 OCR（框架方法，用户可自定义预处理管线）。

        常见预处理步骤：
        1. 灰度化 (grayscale)
        2. 二值化 (binarization) — 对文字图片效果好
        3. 去噪 (denoising)
        4. 倾斜校正 (deskew)
        """
        if not HAS_TESSERACT:
            raise RuntimeError("pytesseract not installed")

        image = Image.open(filepath)

        if preprocess:
            from PIL import ImageFilter, ImageEnhance, ImageOps

            # 灰度化
            image = image.convert("L")
            # 增强对比度
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)
            # 锐化
            image = image.filter(ImageFilter.SHARPEN)
            # 自动色阶
            image = ImageOps.autocontrast(image)

        text = pytesseract.image_to_string(image, lang=self.lang)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return "\n".join(lines)

    # ── 内部方法 ─────────────────────────────────────────────

    def _index_ocr_result(self, filepath: Path, text: str):
        """将 OCR 结果写入向量库"""
        relative_path = str(filepath.relative_to(self.notes_dir))
        created_at = datetime.fromtimestamp(filepath.stat().st_mtime).isoformat()

        # 尝试从文本内容分类领域
        domain = self._classify_ocr_domain(text)

        metadata = {
            "source_file": relative_path,
            "original_filename": filepath.name,
            "created_at": created_at,
            "domain": domain,
        }

        self.store.add_screenshot_text(
            text=text,
            source_file=relative_path,
            metadata=metadata,
        )

    def _classify_ocr_domain(self, text: str) -> str:
        """根据 OCR 文本内容分类"""
        from .markdown_loader import MarkdownLoader

        loader = MarkdownLoader()
        return loader._classify_domain(text, {})
