"""贸易页面 — Table Model 类"""

import os

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor, QPixmap

import ui_pyside6.theme as theme
from core.paths import ICON_DIR


class TradeHubTableModel(QAbstractTableModel):
    """跨区域价格对比表模型"""

    _HEADERS = ["贸易中心", "买价", "卖价", "价差", "价差%", "成交量"]

    def __init__(self, rows: list[dict]):
        super().__init__()
        self._rows = rows

    def rowCount(self, parent=None):
        return len(self._rows)

    def columnCount(self, parent=None):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                r.get("hub", ""),
                f"{r.get('buy_price', 0):,.2f}",
                f"{r.get('sell_price', 0):,.2f}",
                f"{r.get('spread', 0):,.2f}",
                f"{r.get('spread_pct', 0):.1f}%",
                f"{r.get('volume', 0):,}",
            ][c]
        elif role == Qt.ItemDataRole.DecorationRole:
            if c == 0:  # 贸易中心列 — 显示物品图标
                type_id = r.get("type_id")
                if type_id:
                    icon_path = os.path.join(ICON_DIR, f"{type_id}.png")
                    if os.path.exists(icon_path):
                        pix = QPixmap(icon_path)
                        if not pix.isNull():
                            return pix.scaled(
                                32,
                                32,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                return None
        elif role == Qt.ItemDataRole.ForegroundRole:
            if c == 4:
                sp = r.get("spread_pct", 0)
                return QColor(theme.ACCENT_GREEN) if sp > 0 else (QColor(theme.ACCENT_RED) if sp < 0 else None)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None
