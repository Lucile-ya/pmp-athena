"""
PDF 笔记导入器

遍历 ./pmp_notes 下的 .pdf 文件，提取文本内容，
按页/段落切分为 chunk，索引入 ChromaDB。

支持两种后端：
- pdfplumber（优先，提取质量好）
- PyPDF2（回退，速度更快）
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import NOTES_DIR
from ..db.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# ── 后端检测 ────────────────────────────────────────────────
try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    logger.warning("pdfplumber not installed. Falling back to PyPDF2.")

try:
    import PyPDF2

    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False
    logger.warning("PyPDF2 not installed. PDF import disabled.")


class PDFLoader:
    """PDF 笔记加载 & 索引器"""

    def __init__(self, notes_dir: Path | None = None):
        self.notes_dir = notes_dir or NOTES_DIR
        self.store = get_vector_store()

    # ── 公开方法 ─────────────────────────────────────────────

    def ingest_all(self, reset: bool = False) -> dict:
        """
        扫描并导入所有 .pdf 文件。
        返回 {"files": int, "chunks": int, "total_pages": int}
        """
        if not HAS_PDFPLUMBER and not HAS_PYPDF2:
            return {"files": 0, "chunks": 0, "total_pages": 0,
                    "error": "No PDF library available. Install pdfplumber or PyPDF2."}

        pdf_files = list(self.notes_dir.rglob("*.pdf")) + list(
            self.notes_dir.rglob("*.PDF")
        )

        if not pdf_files:
            logger.info("No PDF files found in %s", self.notes_dir)
            return {"files": 0, "chunks": 0, "total_pages": 0}

        total_chunks = 0
        total_pages = 0
        for filepath in pdf_files:
            try:
                chunks = self._process_pdf(filepath)
                if chunks:
                    total_pages += sum(
                        1 for c in chunks if c["metadata"].get("page_number")
                    )
                    self.store.add_notes_batch(chunks)
                    total_chunks += len(chunks)
            except Exception as e:
                logger.error("Failed to process PDF %s: %s", filepath.name, e)

        logger.info(
            "PDF ingest: %d files → %d chunks, %d pages",
            len(pdf_files), total_chunks, total_pages,
        )
        return {
            "files": len(pdf_files),
            "chunks": total_chunks,
            "total_pages": total_pages,
        }

    # ── 内部方法 ─────────────────────────────────────────────

    def _process_pdf(self, filepath: Path) -> list[dict]:
        """处理单个 PDF 文件"""
        filename = filepath.name
        relative_path = str(filepath.relative_to(self.notes_dir))
        created_at = datetime.fromtimestamp(filepath.stat().st_mtime).isoformat()

        # 提取文本
        pages_text = self._extract_text(filepath)

        if not pages_text:
            logger.warning("No text extracted from %s", filename)
            return []

        # 分类领域
        full_text = "\n".join(pages_text)
        domain = self._classify_domain(full_text)

        # 切分为 chunks：按页切分，长页再按段落切
        chunks = []
        for page_num, page_text in enumerate(pages_text, 1):
            if not page_text.strip():
                continue

            # 如果一页很长，按段落切
            paragraphs = self._split_paragraphs(page_text)
            for i, para in enumerate(paragraphs):
                if not para.strip():
                    continue

                # 生成标题
                title = self._extract_or_generate_title(para, filename, page_num)

                meta = {
                    "source_file": relative_path,
                    "original_filename": filename,
                    "title": title,
                    "created_at": created_at,
                    "domain": domain,
                    "page_number": page_num,
                    "chunk_index": i,
                    "char_count": len(para),
                    "type": "pdf_note",
                }

                chunks.append({
                    "content": para,
                    "metadata": meta,
                })

        # 去重合并：相邻的同页 chunk 如果很短，合并
        merged = self._merge_short_chunks(chunks)
        logger.info(
            "PDF %s: %d pages → %d chunks",
            filename, len(pages_text), len(merged),
        )
        return merged

    def _extract_text(self, filepath: Path) -> list[str]:
        """
        提取 PDF 文本，返回按页的文本列表。

        优先使用 pdfplumber（提取质量更好），回退到 PyPDF2。
        """
        if HAS_PDFPLUMBER:
            return self._extract_with_pdfplumber(filepath)
        elif HAS_PYPDF2:
            return self._extract_with_pypdf2(filepath)
        return []

    def _extract_with_pdfplumber(self, filepath: Path) -> list[str]:
        """使用 pdfplumber 提取文本"""
        pages = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                try:
                    text = page.extract_text()
                    pages.append(text or "")
                except Exception as e:
                    logger.debug("pdfplumber page error: %s", e)
                    pages.append("")
        return pages

    def _extract_with_pypdf2(self, filepath: Path) -> list[str]:
        """使用 PyPDF2 提取文本"""
        pages = []
        with open(filepath, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                try:
                    text = page.extract_text()
                    pages.append(text or "")
                except Exception as e:
                    logger.debug("PyPDF2 page error: %s", e)
                    pages.append("")
        return pages

    def _split_paragraphs(self, text: str) -> list[str]:
        """将一页文本按段落/换行切分为多个 chunk"""
        # 按双换行优先
        paras = re.split(r"\n\s*\n", text)

        chunks = []
        for para in paras:
            para = para.strip()
            if not para:
                continue
            # 如果段落太长，按单换行再切
            if len(para) > 3000:
                lines = para.split("\n")
                current = ""
                for line in lines:
                    if len(current) + len(line) < 2000:
                        current += "\n" + line if current else line
                    else:
                        if current.strip():
                            chunks.append(current.strip())
                        current = line
                if current.strip():
                    chunks.append(current.strip())
            else:
                chunks.append(para)

        return chunks

    def _extract_or_generate_title(
        self, text: str, filename: str, page_num: int
    ) -> str:
        """从文本中提取标题，或生成一个"""
        # 尝试匹配 ## 标题
        match = re.search(r"^#{1,3}\s+(.+)$", text, re.MULTILINE)
        if match:
            return match.group(1).strip()

        # 尝试匹配全大写或粗体行
        lines = text.strip().split("\n")
        first_line = lines[0].strip()
        # 如果第一行比较短（< 80 字符），作为标题
        if 3 < len(first_line) < 80:
            # 去掉标点符号
            title = re.sub(r'[：:，,。.]$', '', first_line)
            return title

        return f"{filename} - 第{page_num}页"

    def _classify_domain(self, text: str) -> str:
        """根据 PDF 内容分类到 PMP 领域"""
        from .markdown_loader import MarkdownLoader

        loader = MarkdownLoader()
        return loader._classify_domain(text, {})

    def _merge_short_chunks(self, chunks: list[dict]) -> list[dict]:
        """合并过短的相邻同页 chunk"""
        if len(chunks) <= 1:
            return chunks

        merged = []
        current = chunks[0]

        for next_chunk in chunks[1:]:
            # 同一页 且 合并后不太长
            same_page = (
                current["metadata"].get("page_number")
                == next_chunk["metadata"].get("page_number")
            )
            if (
                same_page
                and len(current["content"]) + len(next_chunk["content"]) < 3000
            ):
                current["content"] += "\n\n" + next_chunk["content"]
                current["metadata"]["char_count"] = len(current["content"])
            else:
                merged.append(current)
                current = next_chunk

        merged.append(current)
        return merged
