"""全物品市场表的 QML 适配（阶段 4b）。

对照 Widgets 版 `ui_pyside6/models/all_items_models.py::AModel` —— **展示规则一行都不重写**：
千分位、破折号占位（`DASH`）、收益等级（`_tag`）染色、利润率正负染色、金额列右对齐、
图标列的 `DecorationRole`，全部仍走父类 `data()`，本类只补**命名角色**（QML 读不到
Qt 那几个无名角色）。

排序同样仍走既有的 `Proxy`（`QSortFilterProxyModel` + 自定义 `lessThan`：收益列按
S>A>B>C>D>✗ 的等级排，其余按去掉千分位后的数值排）。`QSortFilterProxyModel` 会把源模型的
`roleNames()` 转发下去，所以 QML 直接把**代理**当 model 用即可 —— 排序口径一份都不用重写。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor

from ui_qml.icon_cache import icon_url
from ui_qml.models.all_items_models import AModel

__all__ = ["ROLE_NAMES", "AllItemsQmlModel"]

_BASE = Qt.ItemDataRole.UserRole
ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"fg",
    _BASE + 3: b"iconUrl",
    _BASE + 4: b"alignRight",
}
_TEXT = _BASE + 1
_FG = _BASE + 2
_ICON_URL = _BASE + 3
_ALIGN_RIGHT = _BASE + 4

#: 图标列的 key（与 `BCOLS` 里的第三元一致）
_ICON_KEY = "i"
#: 左对齐的列 —— 逐字对齐父类 `TextAlignmentRole` 里的白名单
_LEFT_KEYS = ("i", "z", "e", "ms")


class AllItemsQmlModel(AModel):
    """全物品表：命名角色（文本与配色仍由父类算）。"""

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return ROLE_NAMES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        key = self._cols[index.column()][2]

        if role == _TEXT:
            return super().data(index, Qt.ItemDataRole.DisplayRole)
        if role == _FG:
            color = super().data(index, Qt.ItemDataRole.ForegroundRole)
            # 父类只在「收益等级 / 利润率」两列给颜色，其余返回 None → 交给 QML 的默认前景色
            return color.name(QColor.NameFormat.HexArgb) if isinstance(color, QColor) else ""
        if role == _ICON_URL:
            return icon_url(row.get("id")) if key == _ICON_KEY else ""
        if role == _ALIGN_RIGHT:
            return key not in _LEFT_KEYS
        return super().data(index, role)
