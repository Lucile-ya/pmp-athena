#!/usr/bin/env python3
"""刷题 App 截图 OCR 回归测试（章节练习 UI）。"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

# 允许直接 python pmp_athena/test_screenshot_validator.py
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pmp_athena.image_processor import AnswerValidator, ImageProcessor  # noqa: E402

CASES = [
    {
        "name": "储备分析-选A",
        "path": Path(
            r"C:\Users\gwhea\.cursor\projects\d-pmp-athena\assets"
            r"\c__Users_gwhea_AppData_Roaming_Cursor_User_workspaceStorage_53415c6ea5889517e3c3177fc8c902d4"
            r"_images_ef4227844c9c7d8263dcfd2e68ba8e3a-d012bab6-f086-4446-b899-595e72f6acf5.png"
        ),
        "my": "A",
        "correct": "B",
    },
    {
        "name": "自下而上-选C",
        "path": Path(
            r"C:\Users\gwhea\.cursor\projects\d-pmp-athena\assets"
            r"\c__Users_gwhea_AppData_Roaming_Cursor_User_workspaceStorage_53415c6ea5889517e3c3177fc8c902d4"
            r"_images_cccf0ad91748367cedb845f320346820-26822c94-9932-4957-9b2c-9703ca73721f.png"
        ),
        "my": "C",
        "correct": "B",
    },
]


def main() -> int:
    failed = 0
    proc = ImageProcessor()

    for case in CASES:
        if not case["path"].exists():
            print(f"⏭️  SKIP {case['name']}: 图片不存在")
            continue

        ocr = proc.process(case["path"], run_ocr=True)
        result = AnswerValidator().validate(Image.open(case["path"]), ocr.get("ocr_text"))
        ext = result.get("extracted", {})
        conf = result.get("answer_confidence", {})

        ok = (
            ext.get("my_answer") == case["my"]
            and ext.get("correct_answer") == case["correct"]
            and result.get("is_correct") is False
        )
        status = "✅" if ok else "❌"
        print(
            f"{status} {case['name']}: "
            f"my={ext.get('my_answer')} correct={ext.get('correct_answer')} "
            f"conf={conf.get('my')} method={conf.get('my_method')}"
        )
        if not ok:
            failed += 1

    return 1 if failed else 0


def test_labeled_correction() -> int:
    """标注行纠偏单元测试（不依赖图片）。"""
    v = AnswerValidator()
    failed = 0

    cases = [
        {
            "name": "同行标注",
            "text": "单选作答错误\n正确答案: B 我的答案: C\n解析:选B",
            "my": "C",
            "correct": "B",
            "confirm": False,
        },
        {
            "name": "丢我的答案-推断C",
            "text": "单选作答错误\n正确答案: B 我的答案:\nA.专家\nB.自下而上\n@ .三点估算\nD.类比",
            "my": "C",
            "correct": "B",
            "confirm": False,
        },
        {
            "name": "无标注需确认",
            "text": "单选题\nA.aa\nB.bb\n解析:xxx",
            "my": None,
            "correct": None,
            "confirm": True,
        },
        {
            "name": "非法字母需确认",
            "text": "单选作答错误\n正确答案: Z 我的答案: X",
            "my": None,
            "correct": None,
            "confirm": True,
        },
    ]

    for c in cases:
        r = v._resolve_answers(c["text"])
        ok = (
            r.get("my_answer") == c["my"]
            and r.get("correct_answer") == c["correct"]
            and r.get("needs_user_confirm") == c["confirm"]
        )
        print(
            f"{'✅' if ok else '❌'} {c['name']}: "
            f"my={r.get('my_answer')} correct={r.get('correct_answer')} "
            f"confirm={r.get('needs_user_confirm')}"
        )
        if not ok:
            failed += 1
    return failed


if __name__ == "__main__":
    code = main()
    code += test_labeled_correction()
    raise SystemExit(1 if code else 0)
