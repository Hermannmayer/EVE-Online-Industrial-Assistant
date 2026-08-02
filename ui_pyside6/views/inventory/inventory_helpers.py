"""
仓库页面 — 公共数据模型和常量

包含 InvTableModel 和 BlueprintTableModel。
"""

import os
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QSize, Qt
from PySide6.QtGui import QColor, QPixmap, QPixmapCache

import ui_pyside6.theme as theme
from core.paths import icon_cache_dir
from services.terminology import term

ICON_DIR = icon_cache_dir()


def _load_icon(type_id: int, size: int = 32) -> QPixmap | None:
    """加载物品图标（QPixmapCache 缓存）"""
    if not type_id:
        return None
    cache_key = f"invicon_{type_id}"
    pixmap = QPixmap(cache_key)
    if not pixmap.isNull():
        return pixmap
    path = os.path.join(ICON_DIR, f"{type_id}.png")
    if os.path.isfile(path):
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            QPixmapCache.insert(cache_key, pixmap)
            return pixmap
    return None


# ════════════════════════════════════════════════════
#  InvTableModel
# ════════════════════════════════════════════════════


class InvTableModel(QAbstractTableModel):
    """机库物品表格模型"""

    _HEADERS = ["图标", "名称", "库存数量", "单个成本记录", "规划占用", "规划剩余", "按卖单总价值", "拷贝/发明成本"]

    def __init__(self, items: list[dict]):
        super().__init__()
        self._items = items

    def rowCount(self, parent=None):
        return len(self._items)

    def columnCount(self, parent=None):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self._items[index.row()]
        c = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return ""
            if c == 1:
                return r.get("display_name") or r.get("zh_name") or r.get("en_name") or f"ID:{r['type_id']}"
            if c == 2:
                return f"{r['quantity']:,}"
            if c == 3:
                return f"{r['cost_price']:,.2f}" if r["cost_price"] else "-"
            if c == 4:
                return f"{r['plan_usage']:,}" if r.get("plan_usage") else "0"
            if c == 5:
                remain = r.get("plan_remain")
                return f"{remain:,}" if remain is not None else f"{r['quantity']:,}"
            if c == 6:
                sp = r.get("sell_price")
                return f"{r['quantity'] * sp:,.0f}" if sp else "-"
            if c == 7:
                rc = r.get("research_cost")
                return f"{rc:,.0f}" if rc else ""

        elif role == Qt.ItemDataRole.ToolTipRole:
            if c == 4:
                return "待启动计划预留"

        elif role == Qt.ItemDataRole.DecorationRole:
            if c == 0:
                return _load_icon(r.get("type_id"))

        elif role == Qt.ItemDataRole.SizeHintRole:
            if c == 0:
                return QSize(36, 36)

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if c >= 2:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def item_at(self, row: int) -> dict | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        keys: dict[int, Callable[[dict], Any]] = {
            1: lambda r: (
                r.get("display_name") or r.get("zh_name") or r.get("en_name") or str(r["type_id"])
            ).lower(),
            2: lambda r: r.get("quantity", 0),
            3: lambda r: r.get("cost_price") or 0,
            4: lambda r: r.get("plan_usage") or 0,
            5: lambda r: r.get("plan_remain") if r.get("plan_remain") is not None else r.get("quantity", 0),
            6: lambda r: (r.get("quantity", 0) or 0) * (r.get("sell_price") or 0),
            7: lambda r: r.get("research_cost") or 0,
        }
        key = keys.get(column)
        if key is None:
            return
        rev = order == Qt.SortOrder.DescendingOrder
        self.beginResetModel()
        # 排序副本，避免原地修改调用方传入的列表
        self._items = sorted(self._items, key=key, reverse=rev)
        self.endResetModel()


# ════════════════════════════════════════════════════
#  BlueprintTableModel
# ════════════════════════════════════════════════════


class BlueprintTableModel(QAbstractTableModel):
    """蓝图表格模型"""

    _HEADERS = [
        "图标",
        "名称",
        "类型",
        "材料等级",
        "时间等级",
        "产物名称",
        "制造时间",
        "流程数量",
        "材料成本",
        "销售收入",
        "利润率",
    ]

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
            if c == 0:
                return ""
            if c == 1:
                return (
                    r.get("zh_name")
                    or r.get("display_name")
                    or term.item_override(r.get("blueprint_type_id", 0))
                    or f"ID:{r['blueprint_type_id']}"
                )
            if c == 2:
                text = "蓝图原图" if r.get("is_bpo") else "蓝图拷贝"
                if r.get("occupied"):
                    text += "（占用中）"
                return text
            if c == 3:
                return str(r.get("me_level", 0))
            if c == 4:
                return str(r.get("te_level", 0))
            if c == 5:
                return r.get("product_name") or "-"
            if c == 6:
                secs = r.get("base_time", 0)
                if secs <= 0:
                    return "-"
                h, m = divmod(secs // 60, 60)
                d, h = divmod(h, 24)
                if d:
                    return f"{d}d {h}h {m}m"
                return f"{h}h {m}m"
            if c == 7:
                runs = r.get("runs", 1)
                if runs == -1:
                    return "无限"
                return str(runs)
            if c == 8:
                cost = r.get("material_cost")
                return f"{cost:,.0f} ISK" if cost is not None else "-"
            if c == 9:
                rev = r.get("revenue")
                return f"{rev:,.0f} ISK" if rev is not None else "-"
            if c == 10:
                margin = r.get("margin")
                if margin is None:
                    return "-"
                return f"{margin:+.1f}%"

        elif role == Qt.ItemDataRole.DecorationRole:
            if c == 0:
                prod_id = r.get("product_type_id")
                if prod_id:
                    icon_path = os.path.join(ICON_DIR, f"{prod_id}.png")
                    if os.path.exists(icon_path):
                        pix = QPixmap(icon_path)
                        if not pix.isNull():
                            return pix.scaled(
                                24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                            )
            return None

        elif role == Qt.ItemDataRole.ForegroundRole:
            if c == 2 and r.get("occupied"):
                return QColor(theme.ACCENT_ORANGE)
            if c == 10:
                margin = r.get("margin")
                if margin is not None:
                    return QColor(theme.ACCENT_GREEN) if margin >= 0 else QColor(theme.ACCENT_RED)
            return None

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if c >= 2:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def row_at(self, row: int) -> dict | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        _SORT_KEYS: dict[int, Callable[[dict], Any]] = {
            1: lambda r: r.get("zh_name") or r.get("display_name") or "",
            2: lambda r: "蓝图原图" if r.get("is_bpo") else "蓝图拷贝",
            3: lambda r: r.get("me_level", 0),
            4: lambda r: r.get("te_level", 0),
            5: lambda r: str(r.get("product_name") or ""),
            6: lambda r: r.get("base_time", 0),
            7: lambda r: r.get("runs", 1) if r.get("runs", 1) != -1 else float("inf"),
            8: lambda r: r.get("material_cost") or 0,
            9: lambda r: r.get("revenue") or 0,
            10: lambda r: r.get("margin") or float("-inf"),
        }
        key_fn = _SORT_KEYS.get(column)
        if not key_fn and column != 0:
            return
        key: Callable[[dict], Any]
        if column == 0:

            def _sort_key(r: dict) -> Any:
                return r.get("product_type_id") or 0

            key = _sort_key
        else:
            key_fn = _SORT_KEYS.get(column)
            if key_fn is None:
                return
            key = key_fn

        rev = order == Qt.SortOrder.DescendingOrder
        self.beginResetModel()
        self._rows.sort(key=key, reverse=rev)
        self.endResetModel()
