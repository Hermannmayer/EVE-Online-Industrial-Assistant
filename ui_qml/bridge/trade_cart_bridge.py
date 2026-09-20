"""贸易购物车窗口的 QML 后端。

`_page` 是 `ui_qml.views.trade_cart_window.TradeCartController`（避免循环导入用 `Any`）。
本类只做转发 + 把控制器数据整理成 QML 好渲染的形状，**不含业务规则**。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

__all__ = ["TradeCartBridge"]


class TradeCartBridge(QObject):
    """购物车窗口的 QML 后端。"""

    stateChanged = Signal()

    def __init__(self, page: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._page = page
        self._page.changed.connect(self.stateChanged)

    # ── 数据 ────────────────────────────────────────────────

    @Property(list, notify=stateChanged)
    def groups(self) -> list[dict]:
        return list(self._page.groups())

    @Property(str, notify=stateChanged)
    def summaryText(self) -> str:
        t = self._page.totals()
        return (
            f"合计 {t['count']} 项 · 金额 {t['amount']:,.0f} · 体积 {t['volume']:,.2f} m³ · 预计利润 {t['profit']:,.0f}"
        )

    @Property(bool, notify=stateChanged)
    def isEmpty(self) -> bool:
        return int(self._page.count()) == 0

    @Property(str, notify=stateChanged)
    def hintText(self) -> str:
        return str(self._page.hint())

    @Property(bool, notify=stateChanged)
    def pinned(self) -> bool:
        return bool(self._page.pinned())

    # ── 操作 ────────────────────────────────────────────────

    @Slot(bool)
    def setPinned(self, checked: bool) -> None:
        self._page.set_pinned(bool(checked))

    @Slot(int, int, int)
    def setQty(self, group_index: int, row_index: int, qty: int) -> None:
        self._page.set_qty(group_index, row_index, qty)

    @Slot(int, int)
    def togglePurchased(self, group_index: int, row_index: int) -> None:
        self._page.toggle_purchased(group_index, row_index)

    @Slot(int, int)
    def removeItem(self, group_index: int, row_index: int) -> None:
        self._page.remove(group_index, row_index)

    @Slot(int, int)
    def copyName(self, group_index: int, row_index: int) -> None:
        self._page.copy_name(group_index, row_index)

    @Slot()
    def clearPurchased(self) -> None:
        self._page.clear_purchased()

    @Slot(bool)
    def onWindowVisibleChanged(self, visible: bool) -> None:
        self._page.window_visibility_changed(bool(visible))
