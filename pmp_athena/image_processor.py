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
import sys
from pathlib import Path
from typing import Optional

from PIL import Image, ImageFilter, ImageEnhance, ImageOps

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("image_processor")

# 默认输出目录（与 wechat-claude-code 的临时目录一致）
DEFAULT_OUTPUT_DIR = Path.home() / ".wechat-claude-code" / "processed"
DEFAULT_MAX_SIZE = 1500
DEFAULT_JPEG_QUALITY = 80

# OCR 可用性
try:
    import pytesseract

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


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════


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
    parser.add_argument("input", type=str, help="输入图片路径")
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

    args = parser.parse_args()

    processor = ImageProcessor(
        max_size=args.max_size,
        jpeg_quality=args.quality,
    )

    if args.ocr_only:
        # 仅 OCR 模式：打开已有图片，只做 OCR
        image = Image.open(args.input)
        text = processor._ocr(image)
        result = {
            "success": True,
            "original_path": args.input,
            "ocr_text": text,
            "ocr_available": HAS_OCR,
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(text or "(未识别到文字)")
        return

    result = processor.process(
        args.input,
        output_path=args.output,
        run_ocr=not args.no_ocr,
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

            if result["ocr_text"]:
                print(f"\n📝 OCR 识别文字:")
                print("─" * 40)
                print(result["ocr_text"])
                print("─" * 40)
        else:
            print(f"❌ 处理失败: {result['error']}")
            sys.exit(1)


if __name__ == "__main__":
    main()
