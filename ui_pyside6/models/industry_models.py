"""工业制造 — Table Model 类"""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

import ui_pyside6.theme as theme


class RankTableModel(QAbstractTableModel):
    """利润排行表模型"""

    _HEADERS = ["成品", "利润/run", "利润率%", "ISK/h", "评分", "成本/unit", "时/run"]

    def __init__(self, rows: list[dict]):
        super().__init__()
        self._rows = rows

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                r.get("_name", f"ID:{r.get('_type_id')}"),
                f"{r.get('profit_per_run', 0):,.0f}",
                f"{r.get('margin_pct', 0):.1f}",
                f"{r.get('isk_per_hour', 0):,.0f}",
                f"{r.get('score', 0):.0f}",
                f"{r.get('cost_per_unit', 0):,.0f}",
                f"{r.get('hours_per_run', 0):.1f}",
            ][c]
        elif role == Qt.ItemDataRole.ForegroundRole:
            if c == 1:
                return QColor(theme.GREEN) if r.get("profit_per_run", 0) > 0 else QColor(theme.RED)
            if c == 4:
                s = r.get("score", 0)
                return QColor(theme.GREEN) if s >= 70 else (QColor(theme.RED) if s < 30 else QColor(theme.PRIMARY))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def get_row(self, row: int) -> dict:
        return self._rows[row] if 0 <= row < len(self._rows) else {}


class PlanTableModel(QAbstractTableModel):
    _HEADERS = [
        "产品",
        "批次",
        "并行",
        "ME",
        "TE",
        "材料区域",
        "角色",
        "利润",
        "利润率",
        "评分",
        "时均/h",
        "状态",
    ]

    def __init__(self, plans: list[dict]):
        super().__init__()
        self._plans = plans

    def rowCount(self, parent=QModelIndex()):
        return len(self._plans)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self._plans[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            cols = [
                p.get("product_name", f"ID:{p['product_type_id']}"),
                str(p["runs"]),
                str(p["parallels"]),
                str(p["me_level"]),
                str(p["te_level"]),
                p.get("mat_hub", "Jita"),
                p.get("char_name") or "-",
                f"{p.get('profit', 0):,.0f}" if p.get("profit") else "-",
                f"{p.get('margin', 0):.1f}%" if p.get("margin") else "-",
                f"{p.get('score', 0):.0f}" if p.get("score") else "-",
                f"{p.get('iskph', 0):,.0f}" if p.get("iskph") else "-",
                {"pending": "待排", "running": "运行", "done": "完成"}.get(p.get("status", ""), p.get("status", "")),
            ]
            return cols[c]
        elif role == Qt.ItemDataRole.ForegroundRole:
            if c == 7:
                return QColor(theme.GREEN) if p.get("profit", 0) > 0 else QColor(theme.RED)
            if c == 9:
                s = p.get("score", 0)
                return QColor(theme.GREEN) if s >= 70 else (QColor(theme.RED) if s < 30 else QColor(theme.PRIMARY))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def get_plan(self, row: int) -> dict:
        return self._plans[row] if 0 <= row < len(self._plans) else {}


class MaterialTableModel(QAbstractTableModel):
    _HEADERS = ["材料", "总需求", "单价", "总价"]

    def __init__(self, rows: list[dict]):
        super().__init__()
        self._rows = rows

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                r.get("name", ""),
                str(r.get("need", 0)),
                f"{r.get('price', 0):,.2f}",
                f"{r.get('total', 0):,.2f}",
            ][c]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None


class ProcurementTableModel(QAbstractTableModel):
    """代采购表模型"""

    _HEADERS = ["物品名", "数量", "采购中心", "优先级", "状态", "备注", "创建时间", "下单时间", "到货时间"]

    # 优先级显示映射
    PRIORITY_LABELS = {"urgent": "紧急", "high": "高", "normal": "中", "low": "低"}
    # 状态显示映射
    STATUS_LABELS = {"pending": "待采购", "ordered": "已下单", "received": "已到货"}

    def __init__(self, items: list[dict]):
        super().__init__()
        self._items = items

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                item.get("item_name", f"ID:{item.get('type_id', '')}"),
                str(item.get("quantity", 0)),
                item.get("hub", "Jita"),
                self.PRIORITY_LABELS.get(item.get("priority", ""), item.get("priority", "")),
                self.STATUS_LABELS.get(item.get("status", ""), item.get("status", "")),
                item.get("notes", "") or "-",
                item.get("created_at", "") or "-",
                item.get("ordered_at", "") or "-",
                item.get("received_at", "") or "-",
            ][c]
        elif role == Qt.ItemDataRole.ForegroundRole:
            if c == 3:  # 优先级列
                pri = item.get("priority", "")
                if pri == "urgent":
                    return QColor(theme.RED)
                elif pri == "high":
                    return QColor(theme.ACCENT_ORANGE)
                elif pri == "low":
                    return QColor(theme.TEXT_SECONDARY)
            if c == 4:  # 状态列
                st = item.get("status", "")
                if st == "received":
                    return QColor(theme.GREEN)
                elif st == "ordered":
                    return QColor(theme.PRIMARY)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def get_item(self, row: int) -> dict:
        return self._items[row] if 0 <= row < len(self._items) else {}


class ProductionTableModel(QAbstractTableModel):
    """生产执行跟踪表模型 — 面向 production_plans 表的字段"""

    _HEADERS = [
        "产品",
        "批次",
        "并行",
        "材料成本",
        "利润",
        "利润率",
        "评分",
        "时均/h",
        "状态",
        "创建时间",
    ]

    # 状态 → 中文映射
    STATUS_LABELS = {"pending": "待排", "running": "运行", "done": "完成", "paused": "暂停"}

    def __init__(self, plans: list[dict]):
        super().__init__()
        self._plans = plans

    def rowCount(self, parent=QModelIndex()):
        return len(self._plans)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self._plans[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            cols = [
                p.get("product_name", f"ID:{p.get('product_type_id', '')}"),
                str(p.get("runs", 0)),
                str(p.get("parallels", 1)),
                f"{p.get('material_cost', 0):,.0f}" if p.get("material_cost") else "-",
                f"{p.get('profit', 0):,.0f}" if p.get("profit") is not None else "-",
                f"{p.get('margin', 0):.1f}%" if p.get("margin") else "-",
                f"{p.get('score', 0):.0f}" if p.get("score") else "-",
                f"{p.get('iskph', 0):,.0f}" if p.get("iskph") else "-",
                self.STATUS_LABELS.get(p.get("status", ""), p.get("status", "")),
                p.get("created_at", "") or "-",
            ]
            return cols[c]
        elif role == Qt.ItemDataRole.ForegroundRole:
            if c == 4:  # 利润列
                return QColor(theme.GREEN) if p.get("profit", 0) > 0 else QColor(theme.RED)
            if c == 6:  # 评分列
                s = p.get("score", 0)
                return QColor(theme.GREEN) if s >= 70 else (QColor(theme.RED) if s < 30 else QColor(theme.PRIMARY))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def get_plan(self, row: int) -> dict:
        return self._plans[row] if 0 <= row < len(self._plans) else {}
