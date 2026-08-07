#!/usr/bin/env python3
"""为所有使用 config 常量的文件注入 import。"""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "pmp_athena"

# 所有 config 导出的常量名
ALL_CONSTANTS = {
    "QUESTION_BANK_PATH", "ERROR_LOG_PATH", "REVIEW_STATE_PATH",
    "EXAM_RECORDS_PATH", "EXAM_CONFIG_PATH", "ERROR_EVOLUTION_PATH",
    "REVIEW_CONFIG_PATH", "MOCK_EXAM_STATE_PATH", "OPTIONS_SUPPLEMENT_PATH",
    "NOTES_DIR", "PROJECT_ROOT", "BATCH_PRACTICE_STATE_PATH",
}

IMPORT_STUB = """try:
    from pmp_athena.config import {names}
except ModuleNotFoundError:
    from config import {names}
"""

# Files that need import fix (sed already replaced Path() with constant names)
FILES_NEEDING_IMPORT = [
    "analyze_exam.py",
    "backfill_question_options.py",
    "dedup_error_log.py",
    "error_evolution.py",
    "error_insights.py",
    "error_logger.py",
    "exam_recorder.py",
    "exam_timer.py",
    "knowledge_error_linkage.py",
    "log_review_quality.py",
    "mock_exam_state.py",
    "practice_overview.py",
    "pre_exam_analysis.py",
    "prep_analytics.py",
    "question_bank.py",
    "review_scheduler.py",
    "root_cause_engine.py",
    "semantic_anchors.py",
    "spaced_repetition.py",
    "sprint_planner.py",
    "study_advisor.py",
]


def fix_file(fname: str):
    path = PKG / fname
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")

    # Already has import?
    if "from pmp_athena.config import" in text or "from config import" in text:
        return

    # Guard: skip files that don't use any config constants
    needed = sorted(c for c in ALL_CONSTANTS
                    if re.search(rf'\b{re.escape(c)}\b', text))
    if not needed:
        return

    # Also remove self-assignment lines like `ERROR_LOG_PATH = ERROR_LOG_PATH`
    for c in needed:
        text = re.sub(rf'^{c}\s*=\s*{c}\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(rf'^{c}\s*=\s*Path\(\s*\)\s*$', '', text, flags=re.MULTILINE)

    # Insert import after shebang + module docstring
    lines = text.splitlines()
    insert_at = 0

    # Skip shebang
    if lines and lines[0].startswith("#!"):
        insert_at = 1

    # Skip module docstring (triple-quoted block at top)
    in_docstring = False
    for i in range(insert_at, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if in_docstring:
                insert_at = i + 1
                break
            in_docstring = True
        elif not in_docstring and stripped and not stripped.startswith("#"):
            insert_at = i
            break

    # Skip blank lines
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1

    # Skip from __future__ line
    while insert_at < len(lines) and "from __future__" in lines[insert_at]:
        insert_at += 1

    # Build import block
    names_str = ", ".join(needed)
    import_block = IMPORT_STUB.format(names=names_str)

    new_lines = lines[:insert_at] + [import_block] + lines[insert_at:]
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"  [OK] {fname}: added {len(needed)} imports")


def main():
    for fname in FILES_NEEDING_IMPORT:
        fix_file(fname)
    print("Done")


if __name__ == "__main__":
    main()
