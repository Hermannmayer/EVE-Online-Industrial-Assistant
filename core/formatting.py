"""数值格式化 —— 跨 UI 层共用（Widgets 视图与 QML 桥都要用同一份）。

放在 `core/` 而不是某个对话框模块里：这两个函数的调用方一在 Widgets 视图
（`estimate_view` 的精炼结果弹窗）、一在 QML 桥（成本明细），谁都不该反向依赖对方。

注意与 `ui_qml.bridge.summary_dialog.fmt_isk` 的区别：那个是**缩写**（B/M/K），
用于汇总表的窄列；这里是**精确**金额（千分位 + 两位小数），用于成本明细这类
要能直接核对的场合。
"""

from __future__ import annotations

__all__ = ["fmt_isk_exact", "fmt_tag"]


def fmt_isk_exact(value: float) -> str:
    """精确金额：整数不带小数点，否则保留两位。"""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def fmt_tag(daily_profit: float, veto: str | bool = "") -> str:
    """把日均利润格式化为等级标签（S/A/B/C/D），`veto` 非空则为 ✗。

    原先在 `score_dialogs.py` 与 `compare/compare_models.py` 各有一份**逐字重复**
    的实现（只差类型注解），随批次 6.0 合并到这里。
    """
    if veto:
        return "✗"
    if daily_profit >= 50_000_000:
        return f"{daily_profit / 100_000_000:.1f}亿 S"
    if daily_profit >= 10_000_000:
        return f"{daily_profit / 10_000:.0f}万 A"
    if daily_profit >= 1_000_000:
        return f"{daily_profit / 10_000:.0f}万 B"
    if daily_profit >= 100_000:
        return f"{daily_profit / 10_000:.0f}万 C"
    return f"{daily_profit / 10_000:.0f}万 D"
