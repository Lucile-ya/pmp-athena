#!/usr/bin/env python3
"""
识别结果纠错 —— 修正 OCR / 判卷误判后的题目记录。

统一处理三类纠错，并级联维护三个数据文件：
  question_bank.json / error_log.json / error_review_state.json

用法（Claude 调用）:
    # 1. 改答案（wrong ↔ correct 双向，自动维护错题本 + 复习队列）
    python pmp_athena/correction.py answer --id 83 --new-answer B
    python pmp_athena/correction.py answer --question "一个团队正在使用..." --new-answer B
    python pmp_athena/correction.py answer --latest --new-answer B

    # 2. 改知识领域（重算两个领域正确率）
    python pmp_athena/correction.py area --id 83 --new-area 范围管理

    # 3. 删除题目（question_bank + error_log + 复习队列一并清理）
    python pmp_athena/correction.py delete --id 83
    python pmp_athena/correction.py delete --latest

    # 辅助：查看最新一条（供 Claude 定位题目）
    python pmp_athena/correction.py latest
"""

from __future__ import annotations

import argparse
import json
import re
import sys

try:
    from pmp_athena.error_logger import ErrorLogger
    from pmp_athena.question_bank import QuestionBank
    from pmp_athena.spaced_repetition import SpacedRepetition
    from pmp_athena.config import REVIEW_STATE_PATH
except ModuleNotFoundError:
    from error_logger import ErrorLogger
    from question_bank import QuestionBank
    from spaced_repetition import SpacedRepetition
    from config import REVIEW_STATE_PATH


def _norm_ans(s: str) -> str:
    """答案归一化：去分隔符、大写、多选字母排序（CE == EC）。"""
    if not s:
        return ""
    s = s.strip().upper()
    s = re.sub(r"[\s,，、和&/]+", "", s)
    s = s.replace("AND", "").replace("与", "")
    if s.isalpha():
        return "".join(sorted(set(s)))
    return s


def _area_accuracy(data: list[dict], area: str) -> dict:
    """计算某知识领域正确率（仅统计明确判定的正确/错误题）。"""
    correct = total = 0
    for r in data:
        if r.get("knowledge_area", "").strip() != area:
            continue
        ic = r.get("is_correct")
        if ic is True:
            correct += 1
            total += 1
        elif ic is False:
            total += 1
    rate = correct / total if total else 0.0
    return {"correct": correct, "total": total, "rate": round(rate, 4)}


def _locate(qb: QuestionBank, record_id, question, latest) -> dict | None:
    if latest:
        data = qb.list_all()
        return data[-1] if data else None
    if record_id is not None:
        return qb.get_by_id(record_id)
    if question:
        return qb.find_by_question(question)
    return None


def _update_review_area(error_log_id: int, new_area: str) -> None:
    """同步复习队列里缓存的 knowledge_area（若有）。"""
    try:
        state = json.loads(REVIEW_STATE_PATH.read_text(encoding="utf-8"))
        key = str(error_log_id)
        if key in state:
            state[key]["knowledge_area"] = new_area
            REVIEW_STATE_PATH.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except Exception:
        pass


def correct_answer(
    record_id: int | None = None,
    question: str | None = None,
    latest: bool = False,
    new_answer: str | None = None,
) -> dict:
    """修正「我的答案」，重新判定对错并级联维护错题本 / 复习队列。"""
    qb = QuestionBank()
    err = ErrorLogger()
    sr = SpacedRepetition()

    rec = _locate(qb, record_id, question, latest)
    if rec is None:
        return {"ok": False, "error": "未找到题目记录"}

    old_my = rec.get("my_answer", "")
    correct_answer = rec.get("correct_answer", "")
    old_area = rec.get("knowledge_area", "未分类")
    old_error_log_id = rec.get("error_log_id")

    new_my = _norm_ans(new_answer or "")
    new_is_correct = new_my == _norm_ans(correct_answer)

    data_before = qb.list_all()
    before_rate = _area_accuracy(data_before, old_area)["rate"]

    # ── 级联：确定新的 error_log_id ──
    new_error_log_id = old_error_log_id
    if new_is_correct:
        # 现判定为正确：若之前在错题本中，则移除错题 + 复习队列
        if old_error_log_id:
            err.delete(old_error_log_id)
            sr.remove(old_error_log_id)
            new_error_log_id = None
    else:
        # 现判定为错误
        if old_error_log_id:
            # 仍在错题本：更新我的答案
            err.update(old_error_log_id, my_answer=new_my, knowledge_area=old_area)
        else:
            # 原判定正确、现判定错误：新建错题并加入复习队列
            new_err = err.add(
                question=rec.get("question", ""),
                my_answer=new_my,
                correct_answer=correct_answer,
                knowledge_area=old_area,
                explanation=rec.get("explanation", ""),
                parsed_by=rec.get("parsed_by", "claude"),
            )
            new_error_log_id = new_err["id"]

    qb.update(rec["id"], my_answer=new_my, is_correct=new_is_correct)
    qb.set_error_log_id(rec["id"], new_error_log_id)

    data_after = qb.list_all()
    after_rate = _area_accuracy(data_after, old_area)["rate"]

    return {
        "ok": True,
        "id": rec["id"],
        "question": rec.get("question", ""),
        "old_my": old_my,
        "new_my": new_my,
        "correct_answer": correct_answer,
        "is_correct": new_is_correct,
        "area": old_area,
        "before_rate": before_rate,
        "after_rate": after_rate,
    }


def correct_area(
    record_id: int | None = None,
    question: str | None = None,
    latest: bool = False,
    new_area: str | None = None,
) -> dict:
    """修正知识领域，重算新旧两个领域正确率。"""
    qb = QuestionBank()
    err = ErrorLogger()

    rec = _locate(qb, record_id, question, latest)
    if rec is None:
        return {"ok": False, "error": "未找到题目记录"}

    old_area = rec.get("knowledge_area", "未分类")
    new_area = (new_area or "").strip()
    if not new_area:
        return {"ok": False, "error": "未提供新领域"}
    if new_area == old_area:
        return {"ok": False, "error": "新领域与原领域相同"}

    data_before = qb.list_all()
    old_before = _area_accuracy(data_before, old_area)
    new_before = _area_accuracy(data_before, new_area)

    qb.update(rec["id"], knowledge_area=new_area)

    error_log_id = rec.get("error_log_id")
    if error_log_id:
        err.update(error_log_id, knowledge_area=new_area)
        _update_review_area(error_log_id, new_area)

    data_after = qb.list_all()
    old_after = _area_accuracy(data_after, old_area)
    new_after = _area_accuracy(data_after, new_area)

    return {
        "ok": True,
        "id": rec["id"],
        "question": rec.get("question", ""),
        "old_area": old_area,
        "new_area": new_area,
        "old_before": old_before,
        "old_after": old_after,
        "new_before": new_before,
        "new_after": new_after,
    }


def delete_question(
    record_id: int | None = None,
    question: str | None = None,
    latest: bool = False,
) -> dict:
    """删除题目，级联清理错题本 + 复习队列。"""
    qb = QuestionBank()
    err = ErrorLogger()
    sr = SpacedRepetition()

    rec = _locate(qb, record_id, question, latest)
    if rec is None:
        return {"ok": False, "error": "未找到题目记录"}

    error_log_id = rec.get("error_log_id")
    area = rec.get("knowledge_area", "未分类")
    rec_id = rec["id"]

    qb.delete(rec_id)
    if error_log_id:
        err.delete(error_log_id)
        sr.remove(error_log_id)

    data_after = qb.list_all()
    after_rate = _area_accuracy(data_after, area)["rate"]

    return {
        "ok": True,
        "id": rec_id,
        "question": rec.get("question", ""),
        "error_log_id": error_log_id,
        "area": area,
        "after_rate": after_rate,
    }


# ═══════════════════════════════════════════════════════════
# 输出格式化
# ═══════════════════════════════════════════════════════════

def _pct(rate: float) -> str:
    return f"{rate:.0%}"


def _preview(question: str, limit: int = 40) -> str:
    q = (question or "").strip()
    return q[:limit] + ("…" if len(q) > limit else "")


def _format_answer(r: dict) -> str:
    if not r.get("ok"):
        return f"⚠️ {r.get('error', '未找到题目记录')}"
    verdict = "正确 ✅" if r["is_correct"] else "错误 ❌"
    lines = [
        "✅ 已修正",
        f"📝 题目：{_preview(r['question'])}",
        f"❌ 原答案：{r['old_my'] or '—'} → ✅ 新答案：{r['new_my'] or '—'}",
        f"📊 该题现在判定为：{verdict}",
        f"📈 {r['area']}正确率：{_pct(r['before_rate'])} → {_pct(r['after_rate'])}",
    ]
    return "\n".join(lines)


def _format_area(r: dict) -> str:
    if not r.get("ok"):
        return f"⚠️ {r.get('error', '未找到题目记录')}"
    lines = [
        "✅ 已修正",
        f"📝 题目：{_preview(r['question'])}",
        f"📚 原领域：{r['old_area']} → 新领域：{r['new_area']}",
        f"📈 {r['old_area']}正确率：{_pct(r['old_before']['rate'])} → {_pct(r['old_after']['rate'])}",
        f"📈 {r['new_area']}正确率：{_pct(r['new_before']['rate'])} → {_pct(r['new_after']['rate'])}",
    ]
    return "\n".join(lines)


def _format_delete(r: dict) -> str:
    if not r.get("ok"):
        return f"⚠️ {r.get('error', '未找到题目记录')}"
    lines = [
        "✅ 已删除",
        f"📝 题目：{_preview(r['question'])}",
        "🗑️ 已从 question_bank / error_log / 复习队列 移除",
        f"📈 {r['area']}正确率：→ {_pct(r['after_rate'])}",
    ]
    return "\n".join(lines)


_TRAILER = "\n\n💬 如果还有其他错误，继续发「改一下」+ 修改内容"


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def _add_target_args(p):
    p.add_argument("--id", type=int, default=None, help="题库记录 ID（#N）")
    p.add_argument("--question", "-q", default=None, help="题干文字（用于定位）")
    p.add_argument("--latest", action="store_true", help="定位最新一条记录")


def main():
    parser = argparse.ArgumentParser(
        description="识别结果纠错工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    p_ans = sub.add_parser("answer", help="修正我的答案")
    _add_target_args(p_ans)
    p_ans.add_argument("--new-answer", "-a", required=True, help="新答案（如 B / AD）")

    p_area = sub.add_parser("area", help="修正知识领域")
    _add_target_args(p_area)
    p_area.add_argument("--new-area", "-k", required=True, help="新领域名（如 范围管理）")

    p_del = sub.add_parser("delete", help="删除题目")
    _add_target_args(p_del)

    sub.add_parser("latest", help="查看最新一条记录")

    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    if args.command == "answer":
        r = correct_answer(
            record_id=args.id, question=args.question,
            latest=args.latest, new_answer=args.new_answer,
        )
        print(_format_answer(r) + _TRAILER)

    elif args.command == "area":
        r = correct_area(
            record_id=args.id, question=args.question,
            latest=args.latest, new_area=args.new_area,
        )
        print(_format_area(r) + _TRAILER)

    elif args.command == "delete":
        r = delete_question(
            record_id=args.id, question=args.question, latest=args.latest,
        )
        print(_format_delete(r) + _TRAILER)

    elif args.command == "latest":
        qb = QuestionBank()
        data = qb.list_all()
        if not data:
            print("📭 题库为空")
        else:
            r = data[-1]
            ic = r.get("is_correct")
            icon = "✅" if ic is True else ("❌" if ic is False else "⚠️")
            print(f"📋 最新记录 #{r['id']}")
            print(f"   题目: {_preview(r.get('question', ''), 60)}")
            print(f"   答案: {r.get('my_answer', '?')} → {r.get('correct_answer', '?')}")
            print(f"   判定: {icon}")
            print(f"   领域: {r.get('knowledge_area', '未分类')}")
            print(f"   错题ID: {r.get('error_log_id', '—')}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
