"""
仓库页面 — 公共数据模型和常量

包含 InvTableModel 和 BlueprintTableModel。
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QSize, Qt
from PySide6.QtGui import QColor

from services.terminology import term
from ui_qml.icon_cache import load_item_icon
from ui_qml.theme import registry as theme

# ════════════════════════════════════════════════════
#  InvTableModel
# ════════════════════════════════════════════════════


class InvTableModel(QAbstractTableModel):
    """机库物品表格模型"""

    _HEADERS = ["图标", "名称", "库存数量", "单个成本记录", "规划占用", "规划剩余", "按卖单总价值", "拷贝/发明成本"]

    def __init__(self, items: list[dict]):
        super().__init__()
        self._items = items
        # 当前排序设置（-1 = 未排序）。**模型自己记住**，刷新换行后要照着重排，
        # 否则表头还亮着 ▲ 而内容已被打回原始顺序，见 `reapply_sort`。
        self._sort_col = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

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
                return load_item_icon(r.get("type_id"))

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
        key = self._sort_key(column)
        if key is None:
            return
        self._sort_col = column
        self._sort_order = order
        self.beginResetModel()
        self.reapply_sort()
        self.endResetModel()

    def _sort_key(self, column: int) -> Callable[[dict], Any] | None:
        """列的排序键（纯函数、不碰状态）。`None` = 该列不可排。"""
        return {
            1: lambda r: (r.get("display_name") or r.get("zh_name") or r.get("en_name") or str(r["type_id"])).lower(),
            2: lambda r: r.get("quantity", 0),
            3: lambda r: r.get("cost_price") or 0,
            4: lambda r: r.get("plan_usage") or 0,
            5: lambda r: r.get("plan_remain") if r.get("plan_remain") is not None else r.get("quantity", 0),
            6: lambda r: (r.get("quantity", 0) or 0) * (r.get("sell_price") or 0),
            7: lambda r: r.get("research_cost") or 0,
        }.get(column)

    def reapply_sort(self) -> None:
        """按**当前**排序设置重排 `self._items`。

        **不自己 `begin/endResetModel`** —— 调用方负责，这样 `InventoryQmlModel.set_rows`
        能在同一次模型重置里把「换数据」和「重排」一步做完。

        为什么必须重排：刷新（载入机库库存、移库、加入制造规划…）走的是 `set_rows`，
        它整份换掉行数据 —— 不重排就悄悄回到原始顺序，而桥那边的排序指示还亮着，
        用户看到的就是「操作完排序失效了」。
        """
        if self._sort_col < 0:
            return
        key = self._sort_key(self._sort_col)
        if key is None:
            return
        # 排序副本，避免原地修改调用方传入的列表
        self._items = sorted(self._items, key=key, reverse=self._sort_order == Qt.SortOrder.DescendingOrder)


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
        # 当前排序设置（-1 = 未排序）。刷新换行后要照着重排，见 `reapply_sort`。
        self._sort_col = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

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
                if r.get("is_bpo"):
                    return "无限"
                return str(r.get("runs", 0))
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
                pix = load_item_icon(r.get("product_type_id"), size=24)
                if pix is not None:
                    return pix
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
        key = self._sort_key(column)
        if key is None:
            return
        self._sort_col = column
        self._sort_order = order
        self.beginResetModel()
        self.reapply_sort()
        self.endResetModel()

    def _sort_key(self, column: int) -> Callable[[dict], Any] | None:
        """列的排序键（纯函数、不碰状态）。`None` = 该列不可排。"""
        if column == 0:  # 图标列按产物 type_id 排（等价于按图标分组）
            return lambda r: r.get("product_type_id") or 0
        return {
            1: lambda r: r.get("zh_name") or r.get("display_name") or "",
            2: lambda r: "蓝图原图" if r.get("is_bpo") else "蓝图拷贝",
            3: lambda r: r.get("me_level", 0),
            4: lambda r: r.get("te_level", 0),
            5: lambda r: str(r.get("product_name") or ""),
            6: lambda r: r.get("base_time", 0),
            7: lambda r: float("inf") if r.get("is_bpo") else r.get("runs", 0),
            8: lambda r: r.get("material_cost") or 0,
            9: lambda r: r.get("revenue") or 0,
            10: lambda r: r.get("margin") or float("-inf"),
        }.get(column)

    def reapply_sort(self) -> None:
        """按**当前**排序设置重排 `self._rows`。

        **不自己 `begin/endResetModel`** —— 调用方负责，这样 `BlueprintQmlModel.set_rows`
        能在同一次模型重置里把「换数据」和「重排」一步做完。

        为什么必须重排：「加入制造规划」「修改蓝图等级」「粘贴导入」等操作跑完都会
        `loadBlueprints()` → `set_rows` 整份换掉行数据；不重排就悄悄回到原始顺序，
        而桥那边的排序指示（`blueprintSortColumn`）还亮着 —— 用户看到的就是
        「点了加入制造规划之后排序失效了」。
        """
        if self._sort_col < 0:
            return
        key = self._sort_key(self._sort_col)
        if key is None:
            return
        self._rows = sorted(self._rows, key=key, reverse=self._sort_order == Qt.SortOrder.DescendingOrder)
