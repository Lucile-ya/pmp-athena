"""
模考记录导入器

支持 JSON 格式的模考记录文件。

JSON 格式示例：见 ./pmp_notes/exam_template.json
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import NOTES_DIR, PMP_DOMAINS
from ..db.vector_store import get_vector_store

logger = logging.getLogger(__name__)


class MockExamLoader:
    """模考记录加载器"""

    def __init__(self, notes_dir: Path | None = None):
        self.notes_dir = notes_dir or NOTES_DIR
        self.store = get_vector_store()

    # ── 公开方法 ─────────────────────────────────────────────

    def ingest_all(self, reset: bool = False) -> dict:
        """
        扫描并导入所有模考 JSON 文件。
        返回 {"files": int, "records": int}
        """
        if reset:
            self.store.reset_collection("pmp_exams")

        json_files = list(self.notes_dir.rglob("*exam*.json")) + list(
            self.notes_dir.rglob("*模考*.json")
        )
        if not json_files:
            logger.info("No exam JSON files found in %s", self.notes_dir)
            return {"files": 0, "records": 0}

        total = 0
        for filepath in json_files:
            try:
                records = self._process_file(filepath)
                for record in records:
                    self.store.add_exam_record(
                        scores=record["scores"],
                        exam_date=record.get("exam_date"),
                        total_questions=record.get("total_questions", 180),
                        metadata=record.get("metadata"),
                    )
                    total += 1
            except Exception as e:
                logger.error("Failed to process %s: %s", filepath, e)

        logger.info("Imported %d exam records from %d files", total, len(json_files))
        return {"files": len(json_files), "records": total}

    def add_exam_manually(
        self,
        scores: dict[str, float],
        exam_date: str | None = None,
        total_questions: int = 180,
        source: str = "manual",
    ) -> str:
        """
        手动添加一条模考记录。

        Args:
            scores: {"people": 0.75, "process": 0.62, "business_environment": 0.80}
            exam_date: ISO 日期字符串
            total_questions: 总题数
            source: 来源标识
        """
        return self.store.add_exam_record(
            scores=scores,
            exam_date=exam_date or datetime.now().strftime("%Y-%m-%d"),
            total_questions=total_questions,
            metadata={"source": source},
        )

    # ── 内部方法 ─────────────────────────────────────────────

    def _process_file(self, filepath: Path) -> list[dict]:
        """处理单个模考 JSON 文件"""
        data = json.loads(filepath.read_text(encoding="utf-8"))

        # 支持两种格式：
        # 1. 单个记录: {"exam_date": "...", "scores": {...}}
        # 2. 多个记录: {"exams": [{"exam_date": "...", "scores": {...}}, ...]}
        if isinstance(data, list):
            records = data
        elif "exams" in data:
            records = data["exams"]
        else:
            records = [data]

        validated = []
        for r in records:
            scores = r.get("scores", {})
            # 标准化 scores 键名
            normalized = {}
            for key in ["people", "process", "business_environment"]:
                # 支持中英文键名
                val = scores.get(key) or scores.get(
                    {"people": "人员", "process": "过程", "business_environment": "商业环境"}.get(key, "")
                )
                if val is not None:
                    normalized[key] = float(val)
                else:
                    logger.warning("Missing score for domain '%s' in %s", key, filepath)

            if normalized:
                validated.append({
                    "scores": normalized,
                    "exam_date": r.get("exam_date") or r.get("date"),
                    "total_questions": r.get("total_questions", 180),
                    "metadata": {
                        "source_file": str(filepath.relative_to(self.notes_dir)),
                        "source": r.get("source", "file"),
                    },
                })

        return validated

    @staticmethod
    def create_exam_template(output_path: Path | None = None):
        """在 pmp_notes 下生成模考 JSON 模板文件"""
        if output_path is None:
            output_path = NOTES_DIR / "exam_template.json"

        template = {
            "_comment": "PMP 模考记录模板。可以包含单次或多次模考记录。",
            "exams": [
                {
                    "exam_date": "2025-01-15",
                    "total_questions": 180,
                    "source": "模拟考试 #1",
                    "scores": {
                        "people": 0.72,
                        "process": 0.65,
                        "business_environment": 0.75,
                    },
                }
            ],
        }

        output_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Exam template created at %s", output_path)
