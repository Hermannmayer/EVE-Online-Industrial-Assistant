"""`core.formatting` 的纯函数护栏。

`fmt_tag` 原先在 `score_dialogs.py` 与 `compare/compare_models.py` 里各有一份**逐字重复**
的实现（只差类型注解），批次 6.0 合并到 `core/formatting.fmt_tag`。
它的两条用例原本散在 `tests/test_score_dialogs.py` / `tests/test_compare_dialog.py` 里
—— 那两个文件测的是已经删掉的 Widgets 对话框，随批次 6.2 一起没了，
所以把**纯函数**这部分单独收在这里，别让覆盖一起丢掉。
"""

from __future__ import annotations

import pytest

from core.formatting import fmt_isk_exact, fmt_tag


@pytest.mark.parametrize(
    ("daily_profit", "expected"),
    [
        (50_000_000, "0.5亿 S"),
        (10_000_000, "1000万 A"),
        (1_000_000, "100万 B"),
        (100_000, "10万 C"),
        (50_000, "5万 D"),
    ],
    ids=["S", "A", "B", "C", "D"],
)
def test_fmt_tag_ranks(daily_profit, expected):
    assert fmt_tag(daily_profit) == expected


def test_fmt_tag_veto_wins_over_rank():
    """被否决时一律 ✗，不看金额。"""
    assert fmt_tag(100_000_000, veto="no_depth") == "✗"


def test_fmt_isk_exact_keeps_full_precision():
    """`fmt_isk_exact` 与 `fmt_tag` 是两回事：前者要精确到分位、不加单位后缀。"""
    assert fmt_isk_exact(1234.5) == "1,234.50"
