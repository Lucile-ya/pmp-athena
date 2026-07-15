"""
Markdown 笔记导入器

遍历 ./pmp_notes 下的 .md 文件，按标题切分为 chunk，索引入 ChromaDB。
支持 YAML frontmatter 提取元数据（日期、标签等）。
"""

import re
import logging
from datetime import datetime
from pathlib import Path

from ..config import NOTES_DIR
from ..db.vector_store import get_vector_store

logger = logging.getLogger(__name__)


class MarkdownLoader:
    """Markdown 笔记加载 & 索引器"""

    def __init__(self, notes_dir: Path | None = None):
        self.notes_dir = notes_dir or NOTES_DIR
        self.store = get_vector_store()

    # ── 公开方法 ─────────────────────────────────────────────

    def ingest_all(self, reset: bool = False) -> dict:
        """
        扫描并导入所有 .md 文件。
        返回 {"files": int, "chunks": int}
        """
        if reset:
            self.store.reset_collection("pmp_notes")

        md_files = list(self.notes_dir.rglob("*.md"))
        if not md_files:
            logger.warning("No .md files found in %s", self.notes_dir)
            return {"files": 0, "chunks": 0}

        total_chunks = 0
        for filepath in md_files:
            try:
                chunks = self._process_file(filepath)
                if chunks:
                    self.store.add_notes_batch(chunks)
                    total_chunks += len(chunks)
            except Exception as e:
                logger.error("Failed to process %s: %s", filepath, e)

        logger.info(
            "Ingested %d files → %d chunks", len(md_files), total_chunks
        )
        return {"files": len(md_files), "chunks": total_chunks}

    def ingest_file(self, filepath: Path) -> int:
        """导入单个文件，返回 chunk 数量"""
        chunks = self._process_file(filepath)
        if chunks:
            self.store.add_notes_batch(chunks)
        return len(chunks)

    # ── 内部方法 ─────────────────────────────────────────────

    def _process_file(self, filepath: Path) -> list[dict]:
        """处理单个 .md 文件，切分为 chunks"""
        content = filepath.read_text(encoding="utf-8")
        if not content.strip():
            return []

        # 提取 frontmatter
        frontmatter = self._parse_frontmatter(content)
        body = self._strip_frontmatter(content)

        # 按 ## 标题切分
        chunks = self._split_by_headings(body, filepath, frontmatter)
        return chunks

    def _parse_frontmatter(self, content: str) -> dict:
        """解析 YAML frontmatter (--- ... ---)"""
        meta = {}
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not match:
            return meta

        yaml_text = match.group(1)
        # 简单的手写 YAML 解析（避免依赖 pyyaml）
        for line in yaml_text.strip().split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip().lower()
                val = val.strip().strip('"').strip("'")
                meta[key] = val
        return meta

    def _strip_frontmatter(self, content: str) -> str:
        return re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL)

    def _split_by_headings(
        self,
        body: str,
        filepath: Path,
        frontmatter: dict,
    ) -> list[dict]:
        """按 ## 标题切分正文为独立 chunk"""
        # 用正则匹配所有 ## 标题位置
        sections = re.split(r"(?=^## )", body, flags=re.MULTILINE)

        chunks = []
        file_stem = filepath.stem
        relative_path = str(filepath.relative_to(self.notes_dir))

        # 从 frontmatter 中获取日期
        created_at = frontmatter.get("date") or frontmatter.get("created_at")
        if not created_at:
            # 尝试从文件名推断日期
            created_at = self._guess_date_from_filename(file_stem)
        if not created_at:
            created_at = datetime.fromtimestamp(filepath.stat().st_mtime).isoformat()

        for i, section in enumerate(sections):
            text = section.strip()
            if not text:
                continue

            # 提取标题
            title_match = re.match(r"^## (.+)$", text, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else file_stem

            # 对于非标题开头的第一段，使用文件名作为标题
            if i == 0 and not text.startswith("## "):
                title = file_stem

            # 生成元数据
            tags = frontmatter.get("tags", "")
            domain = self._classify_domain(text, frontmatter)

            meta = {
                "source_file": relative_path,
                "title": title,
                "created_at": created_at,
                "tags": tags,
                "domain": domain,
                "chunk_index": i,
                "char_count": len(text),
            }

            chunks.append({
                "content": text,
                "metadata": meta,
            })

        return chunks

    def _classify_domain(self, text: str, frontmatter: dict) -> str:
        """根据内容关键词自动分类到 PMP 领域"""
        domain = frontmatter.get("domain", "")
        if domain:
            return domain

        text_lower = text.lower()
        people_kw = ["团队", "冲突", "干系人", "stakeholder", "沟通", "领导", "team", "conflict", "leadership", "coach", "motivation"]
        process_kw = ["过程", "风险", "进度", "预算", "质量", "范围", "变更", "采购", "risk", "schedule", "budget", "quality", "scope", "change", "procurement", "wbs", "critical path"]
        be_kw = ["合规", "商业", "利益", "战略", "compliance", "business", "benefit", "strategic", "organization"]

        people_score = sum(1 for kw in people_kw if kw in text_lower)
        process_score = sum(1 for kw in process_kw if kw in text_lower)
        be_score = sum(1 for kw in be_kw if kw in text_lower)

        if people_score >= process_score and people_score >= be_score:
            return "people"
        elif process_score >= be_score:
            return "process"
        else:
            return "business_environment"

    def _guess_date_from_filename(self, stem: str) -> str | None:
        """从文件名推断日期，如 2024-03-15-xxx.md"""
        match = re.match(r"(\d{4}-\d{2}-\d{2})", stem)
        if match:
            return match.group(1)
        match = re.match(r"(\d{8})", stem)
        if match:
            ds = match.group(1)
            return f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
        return None
