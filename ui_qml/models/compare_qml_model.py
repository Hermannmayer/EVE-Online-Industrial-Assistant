"""对比结果表的 QML 适配（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/compare/compare_models.py::CompareTableModel` ——
**展示规则一行都不重写**：ISK 缩写、利润率百分号、状态中文、利润正负染色、
金额列右对齐、物品列图标，全部仍走父类 `data()`，本类只补**命名角色**。

子类化而不是另写一份，是因为这些规则原本就只该有一份实现：另写一份
`compare_rows()` 就多出一个「改了 Widgets 版忘了改 QML 版」的分裂点。
与 `WatchlistQmlModel` 同一套路。

`roleNames()` 里的 `text` 角色同时供 `HorizontalHeaderView` 的 `textRole` 使用
（表头与单元格共用一个角色名，Qt 的 header 只读它拿不到的列标题，无妨）。
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QModelIndex, Qt, QUrl
from PySide6.QtGui import QColor

from ui_pyside6.icon_cache import item_icon_path
from ui_pyside6.views.compare.compare_models import CompareTableModel

__all__ = ["ROLE_NAMES", "CompareQmlModel"]

_BASE = Qt.ItemDataRole.UserRole
ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"fg",
    _BASE + 3: b"iconUrl",
    _BASE + 4: b"alignRight",
    _BASE + 5: b"typeId",
    _BASE + 6: b"name",
}
_TEXT = _BASE + 1
_FG = _BASE + 2
_ICON_URL = _BASE + 3
_ALIGN_RIGHT = _BASE + 4
_TYPE_ID = _BASE + 5
_NAME = _BASE + 6

#: 物品列（图标 + 名称，左对齐；其余列是数值，右对齐 —— 对齐父类的 TextAlignmentRole）
_NAME_KEY = "name"


def _icon_url(type_id: Any) -> str:
    """物品图标 → QML `Image.source` 的 URL；没有图标文件返回空串。

    父类是在 `DecorationRole` 里返回 `QIcon`（QML 用不上），这里改给 URL：
    图标文件路径的唯一来源仍是 `ui_pyside6.icon_cache.item_icon_path`。
    """
    if not type_id:
        return ""
    path = item_icon_path(int(type_id))
    if not os.path.isfile(path):
        return ""
    return QUrl.fromLocalFile(path).toString()


class CompareQmlModel(CompareTableModel):
    """对比结果表：命名角色（行数据与展示规则仍走父类）。"""

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return ROLE_NAMES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        key = self._cols[col][2]

        if role == _TEXT:
            return super().data(index, Qt.ItemDataRole.DisplayRole)
        if role == _FG:
            color = super().data(index, Qt.ItemDataRole.ForegroundRole)
            # 父类只在「利润/利润率/毛利/状态」几列给颜色，其余返回 None → 交给 QML 的默认前景色
            return color.name(QColor.NameFormat.HexArgb) if isinstance(color, QColor) else ""
        if role == _ICON_URL:
            return _icon_url(row.get("type_id")) if key == _NAME_KEY else ""
        if role == _ALIGN_RIGHT:
            return key != _NAME_KEY
        if role == _TYPE_ID:
            return row.get("type_id")
        if role == _NAME:
            return row.get(_NAME_KEY) or ""
        return super().data(index, role)
