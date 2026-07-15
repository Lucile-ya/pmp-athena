"""
ChromaDB 向量数据库封装
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from ..config import (
    CHROMA_PERSIST_DIR,
    COLLECTION_NOTES,
    COLLECTION_SCREENSHOTS,
    COLLECTION_EXAMS,
)
from ..utils.embedding import get_embedding_function

logger = logging.getLogger(__name__)

# ── 全局单例 ────────────────────────────────────────────────
_store: Optional["VectorStore"] = None


def get_vector_store() -> "VectorStore":
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


class VectorStore:
    """ChromaDB 本地向量数据库"""

    def __init__(self):
        self._client = chromadb.PersistentClient(
            path=CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._ef = get_embedding_function()
        self._notes = self._get_or_create(COLLECTION_NOTES)
        self._screenshots = self._get_or_create(COLLECTION_SCREENSHOTS)
        self._exams = self._get_or_create(COLLECTION_EXAMS)

    def _get_or_create(self, name: str):
        return self._client.get_or_create_collection(
            name=name,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

    # ── 笔记操作 ─────────────────────────────────────────────

    def add_note(
        self,
        content: str,
        metadata: dict | None = None,
        doc_id: str | None = None,
    ) -> str:
        """添加一条笔记到向量库，返回 doc_id"""
        doc_id = doc_id or f"note_{uuid.uuid4().hex[:12]}"
        meta = metadata or {}
        meta.setdefault("created_at", datetime.now().isoformat())
        meta.setdefault("type", "note")

        self._notes.add(
            documents=[content],
            metadatas=[meta],
            ids=[doc_id],
        )
        logger.info("Note added: %s (len=%d)", doc_id, len(content))
        return doc_id

    def add_notes_batch(
        self,
        chunks: list[dict],
    ) -> list[str]:
        """批量添加笔记，chunks = [{"content": ..., "metadata": ...}, ...]"""
        if not chunks:
            return []
        ids = [f"note_{uuid.uuid4().hex[:12]}" for _ in chunks]
        self._notes.add(
            documents=[c["content"] for c in chunks],
            metadatas=[c.get("metadata", {}) for c in chunks],
            ids=ids,
        )
        logger.info("Batch added %d notes", len(chunks))
        return ids

    def search_notes(
        self,
        query: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """语义搜索笔记"""
        results = self._notes.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
        )
        return self._format_results(results)

    def search_notes_by_date_range(
        self,
        query: str,
        start_date: str,
        end_date: str,
        n_results: int = 5,
    ) -> list[dict]:
        """在指定日期范围内搜索笔记"""
        where = {
            "$and": [
                {"created_at": {"$gte": start_date}},
                {"created_at": {"$lte": end_date}},
            ]
        }
        return self.search_notes(query, n_results=n_results, where=where)

    def get_notes_count(self) -> int:
        return self._notes.count()

    # ── 截图 OCR 文本操作 ────────────────────────────────────

    def add_screenshot_text(
        self,
        text: str,
        source_file: str,
        metadata: dict | None = None,
    ) -> str:
        doc_id = f"ocr_{uuid.uuid4().hex[:12]}"
        meta = metadata or {}
        meta["source_file"] = source_file
        meta["created_at"] = datetime.now().isoformat()
        meta["type"] = "screenshot"

        self._screenshots.add(
            documents=[text],
            metadatas=[meta],
            ids=[doc_id],
        )
        logger.info("Screenshot OCR added: %s", source_file)
        return doc_id

    def search_screenshots(
        self,
        query: str,
        n_results: int = 5,
    ) -> list[dict]:
        results = self._screenshots.query(
            query_texts=[query],
            n_results=n_results,
        )
        return self._format_results(results)

    # ── 模考记录操作 ─────────────────────────────────────────

    def add_exam_record(
        self,
        scores: dict[str, float],  # {"people": 0.75, "process": 0.60, ...}
        exam_date: str | None = None,
        total_questions: int = 180,
        metadata: dict | None = None,
    ) -> str:
        doc_id = f"exam_{uuid.uuid4().hex[:12]}"
        meta = metadata or {}
        meta["exam_date"] = exam_date or datetime.now().isoformat()
        meta["total_questions"] = total_questions
        meta["type"] = "exam"
        # 把各领域得分存到 metadata
        for domain, score in scores.items():
            meta[f"score_{domain}"] = score

        # 用文本形式存储，方便语义检索
        text_parts = [f"模考记录 - {meta['exam_date']}"]
        domain_names = {
            "people": "人员/People",
            "process": "过程/Process",
            "business_environment": "商业环境/Business Environment",
        }
        for domain, score in scores.items():
            name = domain_names.get(domain, domain)
            text_parts.append(f"{name}: {score*100:.0f}%")

        self._exams.add(
            documents=["\n".join(text_parts)],
            metadatas=[meta],
            ids=[doc_id],
        )
        logger.info("Exam record added: %s", doc_id)
        return doc_id

    def get_all_exams(self) -> list[dict]:
        """获取所有模考记录"""
        results = self._exams.get()
        if not results["ids"]:
            return []
        exams = []
        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i] if results["metadatas"] else {}
            doc = results["documents"][i] if results["documents"] else ""
            exams.append({"id": doc_id, "metadata": meta, "document": doc})
        return sorted(
            exams,
            key=lambda x: x["metadata"].get("exam_date", ""),
            reverse=True,
        )

    def get_latest_exam(self) -> dict | None:
        exams = self.get_all_exams()
        return exams[0] if exams else None

    # ── 工具方法 ─────────────────────────────────────────────

    def _format_results(self, results: dict) -> list[dict]:
        out = []
        if not results.get("ids") or not results["ids"][0]:
            return out
        ids_list = results["ids"][0]
        docs_list = results["documents"][0] if results["documents"] else [""] * len(ids_list)
        metas_list = results["metadatas"][0] if results["metadatas"] else [{}] * len(ids_list)
        distances = results["distances"][0] if results.get("distances") else [0] * len(ids_list)

        for i, doc_id in enumerate(ids_list):
            out.append({
                "id": doc_id,
                "document": docs_list[i] if i < len(docs_list) else "",
                "metadata": metas_list[i] if i < len(metas_list) else {},
                "distance": distances[i] if i < len(distances) else 0,
            })
        return out

    def reset_collection(self, collection_name: str):
        """重置某个集合（删除后重建）"""
        try:
            self._client.delete_collection(collection_name)
        except Exception:
            pass
        if collection_name == COLLECTION_NOTES:
            self._notes = self._get_or_create(COLLECTION_NOTES)
        elif collection_name == COLLECTION_SCREENSHOTS:
            self._screenshots = self._get_or_create(COLLECTION_SCREENSHOTS)
        elif collection_name == COLLECTION_EXAMS:
            self._exams = self._get_or_create(COLLECTION_EXAMS)
