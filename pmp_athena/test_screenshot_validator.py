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
        {
            "name": "你上次的选择",
            "text": (
                "项目经理估算项目成本\n超出预算?( )\n"
                "A.成本汇总\nB.储备分析\n"
                "正确答案: B         你上次的选择: A\n收缩解析"
            ),
            "my": "A",
            "correct": "B",
            "confirm": False,
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


def test_structure() -> int:
    """纯题干/枚举选项结构解析测试。"""
    v = AnswerValidator()
    failed = 0
    text = (
        "口 O 中 记 加\n、以下哪个不是项目的可交付成果?\n"
        "、项目管理困队所编制的项目管理计划\n批量生产的汽车零配件\n"
        "、学校新开发的课程\n、研究课题所发现的新知识"
    )
    st = v.classify_screenshot_type(text)
    ext = v._extract_question_info(text)
    ok = st == "plain_question" and len(ext.get("options") or {}) == 4
    print(f"{'✅' if ok else '❌'} plain-deliverable: type={st} q={ext.get('question')[:20]}...")
    return 0 if ok else 1


def test_plain_followup_flow() -> int:
    """纯题干 + 用户报选错 → 自动入库流程。"""
    from pmp_athena import plain_question_store as pqs

    failed = 0
    pqs.clear_pending()
    try:
        pqs._save({
            "question": "【测试】以下哪个不是项目的可交付成果?",
            "options": {
                "A": "项目管理计划",
                "B": "批量生产的汽车零配件",
                "C": "学校新开发的课程",
                "D": "研究课题所发现的新知识",
            },
            "formatted_question": "【测试】以下哪个不是项目的可交付成果?\nA. 项目管理计划\nB. 批量生产的汽车零配件",
            "knowledge_area": "范围管理",
            "my_answer": None,
            "correct_answer": None,
            "explanation": None,
        })

        r1 = pqs.parse_my_answer("我选 A")
        r2 = pqs.parse_claude_answer("答案：B\n解析：批量生产属于运营，非项目独特产出。\n记忆口诀：批量运营非项目。")
        ok_parse = r1 == "A" and r2[0] == "B" and "运营" in r2[1]
        print(f"{'✅' if ok_parse else '❌'} plain-parse: my={r1} correct={r2[0]}")
        if not ok_parse:
            failed += 1

        pqs.followup_user_text("我选A")
        r3 = pqs.apply_claude_parse(
            "答案：B\n解析：批量生产属于运营。\n记忆口诀：批量运营非项目。"
        )
        ok_log = r3.get("status") == "logged" and r3.get("my_answer") == "A"
        print(f"{'✅' if ok_log else '❌'} plain-auto-log: status={r3.get('status')} id={r3.get('error_log_id')}")
        if not ok_log:
            failed += 1

        ok_clear = pqs.get_pending() is None
        print(f"{'✅' if ok_clear else '❌'} plain-pending-cleared")
        if not ok_clear:
            failed += 1
    finally:
        pqs.clear_pending()

    return failed


def test_caption_triggers() -> int:
    """配文触发录入：合并用户说明中的答案。"""
    v = AnswerValidator()
    failed = 0

    text = (
        "、以下哪个不是项目的可交付成果?\n"
        "A、项目管理计划\nB、批量生产的汽车零配件\n"
        "C、学校新开发的课程\nD、研究课题所发现的新知识"
    )
    from PIL import Image

    img = Image.new("RGB", (10, 10), "white")

    cases = [
        {
            "name": "caption-both",
            "caption": "我的答案是A，正确答案是B",
            "my": "A",
            "correct": "B",
            "is_correct": False,
            "auto": "log_error",
        },
        {
            "name": "caption-correct-only",
            "caption": "正确答案是B",
            "my": None,
            "correct": "B",
            "is_correct": None,
            "auto": None,
        },
        {
            "name": "caption-wrong-intent",
            "caption": "选错了，我选A，正确答案是B",
            "my": "A",
            "correct": "B",
            "is_correct": False,
            "auto": "log_error",
        },
    ]

    for c in cases:
        v._cached_result = None
        r = v.validate(img, text, user_caption=c["caption"])
        ext = r.get("extracted", {})
        ok = (
            ext.get("my_answer") == c["my"]
            and ext.get("correct_answer") == c["correct"]
            and r.get("is_correct") == c["is_correct"]
        )
        if c["auto"]:
            ok = ok and r.get("auto_action") == c["auto"]
        print(
            f"{'✅' if ok else '❌'} {c['name']}: "
            f"my={ext.get('my_answer')} correct={ext.get('correct_answer')} "
            f"action={r.get('auto_action')}"
        )
        if not ok:
            failed += 1

    return failed


def test_multi_merge_logic() -> int:
    """多图语义合并单元测试（不依赖图片）。"""
    from pmp_athena.multi_screenshot_merge import (
        ScreenshotSlice,
        classify_slice,
        extract_question_num,
        group_slices,
        merge_group,
        stems_overlap,
    )

    failed = 0

    if extract_question_num("Q3 以下哪个…") != "3":
        print("❌ multi-num-q3")
        failed += 1
    else:
        print("✅ multi-num-q3")

    if not stems_overlap("以下哪个不是项目的可交付成果", "以下哪个不是项目的可交付成果？"):
        print("❌ multi-stem-overlap")
        failed += 1
    else:
        print("✅ multi-stem-overlap")

    primary = ScreenshotSlice(
        index=0,
        path="a.png",
        ocr_text="5、以下哪个不是项目的可交付成果?\nA.aa\n正确答案: B 我的答案: A",
        validation={
            "extracted": {
                "question": "以下哪个不是项目的可交付成果?",
                "my_answer": "A",
                "correct_answer": "B",
                "knowledge_area": "范围管理",
                "options": {"A": "aa", "B": "bb"},
            }
        },
        question="以下哪个不是项目的可交付成果?",
    )
    primary.role = classify_slice(primary)

    secondary = ScreenshotSlice(
        index=1,
        path="b.png",
        ocr_text="【解析】批量生产属于运营，不是项目独特交付物。",
        validation={"extracted": {}},
    )
    secondary.role = classify_slice(secondary)

    ok_roles = primary.role in ("primary", "mixed") and secondary.role == "secondary"
    print(f"{'✅' if ok_roles else '❌'} multi-roles: primary={primary.role} secondary={secondary.role}")
    if not ok_roles:
        failed += 1

    groups, unmatched = group_slices([primary, secondary])
    ok_group = len(groups) == 1 and len(unmatched) == 0
    print(f"{'✅' if ok_group else '❌'} multi-group: groups={len(groups)} unmatched={len(unmatched)}")
    if not ok_group:
        failed += 1

    merged = merge_group(groups[0])
    ok_merge = (
        merged.get("my_answer") == "A"
        and merged.get("correct_answer") == "B"
        and "运营" in (merged.get("explanation") or "")
    )
    print(f"{'✅' if ok_merge else '❌'} multi-merge: expl={merged.get('explanation', '')[:30]}")
    if not ok_merge:
        failed += 1

    return failed


def test_chapter_practice_parse() -> int:
    """章节练习统计 OCR 解析单元测试。"""
    from pmp_athena.chapter_practice_recorder import (
        extract_chapter_from_caption,
        is_chapter_practice_screenshot,
        map_chapter_to_area,
        parse_chapter_practice_text,
    )

    failed = 0

    text = (
        "章节练习\n范围管理\n正确率 20%\n答对 6 题\n总题数 30\n"
        "答错 24 题\n用时 11 分钟"
    )
    parsed = parse_chapter_practice_text(text)
    ok = (
        parsed.get("total_questions") == 30
        and parsed.get("correct_count") == 6
        and parsed.get("time_used_minutes") == 11
        and abs((parsed.get("correct_rate") or 0) - 0.2) < 0.01
    )
    print(f"{'✅' if ok else '❌'} chapter-parse: {parsed}")
    if not ok:
        failed += 1

    ok2 = (
        map_chapter_to_area("范围") == "范围管理"
        and map_chapter_to_area("项目成本管理") == "成本管理"
        and extract_chapter_from_caption("录入章节练习 质量管理") == "质量管理"
        and is_chapter_practice_screenshot(text)
    )
    print(f"{'✅' if ok2 else '❌'} chapter-map-detect")
    if not ok2:
        failed += 1

    garbled = (
        "¢ 20% °?\n本次练习未及格，需要加强学习!\n"
        "30          om        105} 598\n"
    )
    parsed_g = parse_chapter_practice_text(garbled)
    ok3 = (
        parsed_g.get("total_questions") == 30
        and parsed_g.get("correct_count") == 6
        and parsed_g.get("time_used_minutes") == 11
    )
    print(f"{'✅' if ok3 else '❌'} chapter-garbled-ocr: {parsed_g}")
    if not ok3:
        failed += 1

    return failed


if __name__ == "__main__":
    code = main()
    code += test_labeled_correction()
    code += test_structure()
    code += test_plain_followup_flow()
    code += test_caption_triggers()
    code += test_multi_merge_logic()
    code += test_chapter_practice_parse()
    raise SystemExit(1 if code else 0)
