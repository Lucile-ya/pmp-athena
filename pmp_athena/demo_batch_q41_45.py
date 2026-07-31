#!/usr/bin/env python3
"""Q41-45 批量判卷完整演示：收录 → 逐题补录 → 汇总。"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"d:\miniconda\python.exe"
CLI = str(ROOT / "pmp_athena" / "daily_practice.py")

SAMPLE = """
41.项目经理应如何确保项目满足关闭标准？
A. 继续监控项目
B. 提交变更请求
C. 获得客户验收并释放资源
D. 更新风险登记册

42.团队冲突最佳首选策略是什么？
A. 回避
B. 强迫
C. 合作/解决问题
D. 缓和

43.WBS 的核心作用是什么？
A. 估算成本
B. 分解可交付成果
C. 制定进度基准
D. 识别风险

44.变更请求的正确流程是？
A. 直接实施
B. 先评估影响再提交 CCB
C. 口头批准即可
D. 仅更新日志

45.项目收尾时首要工作是什么？
A. 庆祝
B. 释放资源并归档
C. 开始新项目
D. 更新章程

我的答案是：CCCAB
"""

UPDATES = [
    (41, "C", "获得客户验收并释放资源，满足关闭标准。"),
    (42, "C", "冲突解决首选合作/解决问题（双赢）。"),
    (43, "B", "WBS 将可交付成果逐层分解为工作包。"),
    (44, "B", "变更先评估影响，再提交 CCB 审批。"),
    (45, "B", "收尾首要：释放资源、归档可交付成果。"),
]


def run(args: list[str], stdin: str = "") -> dict | str:
    r = subprocess.run(
        [PY, CLI, *args],
        input=stdin.encode("utf-8") if stdin else None,
        capture_output=True,
        cwd=str(ROOT),
    )
    out = r.stdout.decode("utf-8").strip()
    if args[-1] == "--json":
        import json
        return json.loads(out)
    return out


def main() -> int:
    print("=" * 50)
    print("步骤 1：批量收录（无标准答案）")
    print("=" * 50)
    r1 = run(["batch", "--stdin", "--json"], SAMPLE)
    print(r1.get("text", r1))

    print("\n" + "=" * 50)
    print("步骤 2：逐题补录标准答案 + 解析")
    print("=" * 50)
    correct, wrong = [], []
    for num, ans, expl in UPDATES:
        cmd = f"更新{num}题，正确答案是 {ans}，解析：{expl}"
        r = run(["batch-update-text", "--stdin", "--json"], cmd)
        print(r.get("text", r))
        if r.get("is_correct"):
            correct.append(num)
        else:
            wrong.append(num)

    print("\n" + "=" * 50)
    print("步骤 3：判卷汇总")
    print("=" * 50)
    total = len(UPDATES)
    print(f"📋 Q41-45 批量判卷完成（{total} 题）")
    print(f"你的答案：CCCAB")
    if wrong:
        print(f"❌ 错题：{'、'.join(str(n) for n in wrong)}（{len(wrong)} 题）")
    if correct:
        print(f"✅ 正确：{'、'.join(str(n) for n in correct)}（{len(correct)} 题）")
    print("💾 错题已同步 question_bank + error_log + error_review_state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
