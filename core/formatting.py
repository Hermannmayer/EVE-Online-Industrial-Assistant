"""数值格式化 —— 跨 UI 层共用（Widgets 视图与 QML 桥都要用同一份）。

放在 `core/` 而不是某个对话框模块里：这两个函数的调用方一在 Widgets 视图
（`estimate_view` 的精炼结果弹窗）、一在 QML 桥（成本明细），谁都不该反向依赖对方。

注意与 `ui_qml.bridge.summary_dialog.fmt_isk` 的区别：那个是**缩写**（B/M/K），
用于汇总表的窄列；这里是**精确**金额（千分位 + 两位小数），用于成本明细这类
要能直接核对的场合。
"""

from __future__ import annotations

__all__ = ["fmt_isk_exact"]


def fmt_isk_exact(value: float) -> str:
    """精确金额：整数不带小数点，否则保留两位。"""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"
