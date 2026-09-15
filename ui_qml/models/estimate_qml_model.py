"""把 `ui_pyside6` 的表格模型适配成 QML 可消费的形式。

**这是所有表格迁移的样板。** QML 的 `TableView` 与 QWidgets 的 `QTableView`
对模型的要求差两点，本模块就是补这两点：

1. **QML 只认命名角色**：QWidgets 用 `Qt.DisplayRole`/`DecorationRole` 这类枚举，
   QML 的 delegate 却要写 `model.name`、`model.qtyText`，因此必须提供 `roleNames()`。
2. **QML 渲染不了 `QPixmap`**：`DecorationRole` 返回的 `QPixmap` 在 QML 里拿不到，
   这里改为给**图标文件的 URL**（图标本来就是磁盘上的 PNG，QML 的 `Image`
   直接吃 URL，还能用 QML 自带的图片缓存）。

做法是**继承**原模型而不是包装：原模型的 `_rows`/`_recalc_totals`/`sort` 等逻辑
全部复用，QWidgets 视图（`data(DisplayRole)` 等）也照常工作——迁移期两个视图
可以共用同一个模型实例。
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QModelIndex, Qt, QUrl

from ui_qml.icon_cache import item_icon_path
from ui_qml.models.estimate_models import EstimateTableModel

__all__ = ["EstimateQmlModel", "ROLE_NAMES"]

# 角色号 → QML 里的名字（QML delegate 写 model.name / model.qtyText ...）
ROLE_NAMES: dict[int, bytes] = {
    Qt.ItemDataRole.UserRole + 1: b"typeId",
    Qt.ItemDataRole.UserRole + 2: b"iconUrl",
    Qt.ItemDataRole.UserRole + 3: b"name",
    Qt.ItemDataRole.UserRole + 4: b"qty",
    Qt.ItemDataRole.UserRole + 5: b"qtyText",
    Qt.ItemDataRole.UserRole + 6: b"unitPriceText",
    Qt.ItemDataRole.UserRole + 7: b"sellTotalText",
    Qt.ItemDataRole.UserRole + 8: b"buyTotalText",
    Qt.ItemDataRole.UserRole + 9: b"volumeText",
    Qt.ItemDataRole.UserRole + 10: b"rowIndex",
}

_TYPE_ID = Qt.ItemDataRole.UserRole + 1
_ICON_URL = Qt.ItemDataRole.UserRole + 2
_NAME = Qt.ItemDataRole.UserRole + 3
_QTY = Qt.ItemDataRole.UserRole + 4
_QTY_TEXT = Qt.ItemDataRole.UserRole + 5
_UNIT_TEXT = Qt.ItemDataRole.UserRole + 6
_SELL_TEXT = Qt.ItemDataRole.UserRole + 7
_BUY_TEXT = Qt.ItemDataRole.UserRole + 8
_VOLUME_TEXT = Qt.ItemDataRole.UserRole + 9
_ROW_INDEX = Qt.ItemDataRole.UserRole + 10


def _icon_url(type_id: Any) -> str:
    """图标文件 URL；文件不存在返回空串。

    必须给 `file:///...` 形式的 URL——直接把 Windows 路径（`C:\\...`）塞给
    QML 的 `Image.source` 解析不了。文件不存在时返回空串，免得 QML 刷警告。
    """
    if not type_id:
        return ""
    path = item_icon_path(int(type_id))
    if not os.path.isfile(path):
        return ""
    return QUrl.fromLocalFile(path).toString()


class EstimateQmlModel(EstimateTableModel):
    """估价表格模型 + QML 命名角色。逻辑全在父类，这里只补角色。"""

    # PySide6 的桩把 roleNames 标成 dict[int, QByteArray]，运行时 bytes 同样被接受
    # （QML 侧两种都认），这里按 bytes 写更好读。
    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return ROLE_NAMES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]

        if role == _TYPE_ID:
            return row.get("type_id")
        if role == _ICON_URL:
            return _icon_url(row.get("type_id"))
        if role == _NAME:
            return row.get("name", "?")
        if role == _QTY:
            return row.get("qty", 0)
        if role == _ROW_INDEX:
            return index.row()
        if role == _QTY_TEXT:
            return f"{row.get('qty', 0):,}"
        if role == _UNIT_TEXT:
            value = row.get("unit_price", 0) or 0
            return f"{value:,.2f}" if value else "---"
        if role == _SELL_TEXT:
            value = row.get("sell_total", 0) or 0
            return f"{value:,.2f}" if value else "---"
        if role == _BUY_TEXT:
            value = row.get("buy_total", 0) or 0
            return f"{value:,.2f}" if value else "---"
        if role == _VOLUME_TEXT:
            value = row.get("volume", 0) or 0
            return f"{value:,.2f}" if value else "---"

        # 其余角色（Display/Decoration/Foreground/UserRole…）交回父类，
        # 这样 QWidgets 版的 EstimatePage 仍能用同一个模型实例。
        return super().data(index, role)

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """排序后行号全变，必须让 QML 重新拉取 rowIndex。"""
        super().sort(column, order)
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, 0), list(ROLE_NAMES))
