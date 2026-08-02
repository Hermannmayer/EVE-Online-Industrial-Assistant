"""工业制造 — Table Model 类"""

import os
from datetime import UTC, datetime
from typing import cast

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor, QPixmap, QPixmapCache

import ui_pyside6.theme as theme
from core.paths import ICON_DIR


def _fmt_dhms(seconds) -> str:
    """把秒格式化为 d/h/m"""
    seconds = int(seconds or 0)
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    if d > 0:
        return f"{d}d{h}h{m}m"
    if h > 0:
        return f"{h}h{m}m"
    return f"{m}m"


def _remaining(p: dict, now: datetime | None = None) -> int | None:
    """计划剩余秒（进行中）；非进行中/无 started_at 返回 None"""
    from services.plan_execution import remaining_seconds

    return remaining_seconds(p, now=now)


class RankTableModel(QAbstractTableModel):
    """利润排行表模型"""

    _HEADERS = ["成品", "利润/run", "利润率%", "ISK/h", "评分", "成本/unit", "时/run"]

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
    """19 列生产计划模型 — 支持 checkbox、类别、图标、行内编辑、排序"""

    _HEADERS = [
        "☐",  # 0  勾选/备料
        "类别",  # 1  制造/拷贝/发明/反应
        "图标",  # 2
        "产品",  # 3
        "备注",  # 4
        "组号",  # 5
        "子级",  # 6
        "状态",  # 7
        "人物",  # 8
        "流程",  # 9
        "蓝图",  # 10
        "时长",  # 11
        "产能",  # 12
        "设施",  # 13
        "输出",  # 14
        "成本",  # 15
        "利润",  # 16
        "市场利润率%",  # 17
        "个人利润率%",  # 18
    ]

    # 可编辑列集合（仅 active 状态下生效）
    _EDITABLE_COLS = {4, 8, 13, 14}

    # 排序键映射: column index → dict key
    _SORT_KEYS = {
        0: "materials_ready",
        1: "category",
        2: None,
        3: "product_name",
        4: "notes",
        5: "group_id",
        6: "child_level",
        7: "status",
        8: "char_name",
        9: "_runs",
        10: "_me_level",
        11: "_calculated_time",
        12: "_daily_output",
        13: "facility",
        14: "output",
        15: "material_cost",
        16: "profit",
        17: "market_margin",
        18: "personal_margin",
    }

    # 数值列（排序时按数字比较）
    _NUMERIC_SORT_COLS = {0, 5, 11, 12, 15, 16, 17, 18}

    # 状态 → 显示文本
    _STATUS_LABELS = {
        "pending": "待生产",
        "in_progress": "生产中",
        "ready": "待下线",
        "completed": "已完成",
        "running": "生产中",
        "done": "已完成",
    }

    def __init__(self, plans: list[dict]):
        super().__init__()
        self._plans = plans
        self._sort_col: int = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    def rowCount(self, parent=None):
        return len(self._plans)

    def columnCount(self, parent=None):
        return 19

    # ── 图标列 DecorationRole ────────────────────────────────────

    def _load_icon(self, type_id: int) -> QPixmap | None:
        """从缓存或磁盘加载 32px 图标，失败返回 None"""
        if not type_id:
            return None
        cache_key = f"icon_{type_id}"
        pixmap = QPixmap(cache_key)
        if not pixmap.isNull():
            return pixmap
        path = os.path.join(ICON_DIR, f"{type_id}.png")
        if not os.path.isfile(path):
            return None
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return None
        pixmap = pixmap.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        QPixmapCache.insert(cache_key, pixmap)
        return pixmap

    # ── DisplayRole ──────────────────────────────────────────────

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self._plans[index.row()]
        c = index.column()

        # DecorationRole — 图标列
        if role == Qt.ItemDataRole.DecorationRole and c == 2:
            return self._load_icon(p.get("product_type_id"))

        # SizeHintRole — 图标列 / 备料勾选列（固定窄列，适配图标与复选框尺寸）
        if role == Qt.ItemDataRole.SizeHintRole and c in (0, 2):
            from PySide6.QtCore import QSize

            return QSize(26, 26) if c == 0 else QSize(36, 36)

        # 类别行底色（制造默认透明，拷贝/发明/反应浅色底）
        if role == Qt.ItemDataRole.BackgroundRole:
            from services.plan_category import category_color

            color = category_color(str(p.get("category", "manufacturing")))
            if color:
                from PySide6.QtGui import QColor as _QColor

                return _QColor(color)

        # 备料勾选列 → 真实复选框（CheckStateRole 渲染；点击切换由 view 的 clicked 处理）
        if role == Qt.ItemDataRole.CheckStateRole and c == 0:
            return Qt.CheckState.Checked if p.get("materials_ready", 0) else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.TextAlignmentRole and c == 0:
            return Qt.AlignmentFlag.AlignCenter

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_text(p, c)

        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(p, c)

        return None

    def _display_text(self, p: dict, c: int) -> str:
        """列 0~18 的 DisplayRole 文本"""
        if c == 0:
            return ""  # 备料列由 CheckStateRole 渲染真实复选框
        if c == 1:
            from services.plan_category import category_symbol

            return category_symbol(str(p.get("category", "manufacturing")))  # 类别符号
        if c == 2:
            return ""  # 图标列不显示文本
        if c == 3:
            return cast(str, p.get("product_name", f"ID:{p.get('product_type_id', '')}"))
        if c == 4:
            return cast(str, p.get("notes", "")) or ""
        if c == 5:
            return str(p.get("group_id", 0))
        if c == 6:
            return str(p.get("child_level", 0))
        if c == 7:
            return cast(str, self._STATUS_LABELS.get(p.get("status", ""), p.get("status", "")))
        if c == 8:
            return p.get("char_name", "") or "-"
        if c == 9:
            runs = p.get("runs", 0)
            parallels = p.get("parallels", 1)
            return f"{runs}X{parallels}"
        if c == 10:
            me = p.get("me_level", 0)
            te = p.get("te_level", 0)
            has_img = "有图" if p.get("has_image", False) else "没图"
            bound = " *" if p.get("assigned_blueprint_id") else ""
            return f"{me}-{te}[{has_img}]{bound}"
        if c == 11:
            status = p.get("status", "")
            if status in ("in_progress", "running"):
                rem = _remaining(p)
                if rem is None:
                    return _fmt_dhms(p.get("calculated_time", 0))
                if rem <= 0:
                    return "已超时"
                return f"剩余 {_fmt_dhms(rem)}"
            if status == "ready":
                return "待下线"
            if status in ("completed", "done"):
                return "已完成"
            return _fmt_dhms(p.get("calculated_time", 0))
        if c == 12:
            daily = p.get("daily_output", 0) or 0
            return f"{daily:,.2f}"
        if c == 13:
            return p.get("facility", "") or "-"
        if c == 14:
            output = p.get("output", 0) or 0
            return f"{output:,.0f}"
        if c == 15:
            cost = p.get("material_cost", 0) or 0
            return f"{cost:,.0f}"
        if c == 16:
            profit = p.get("profit", 0) or 0
            return f"{profit:,.0f}"
        if c == 17:
            margin = p.get("market_margin", 0) or 0
            return f"{margin:.1f}%"
        if c == 18:
            margin = p.get("personal_margin", 0) or 0
            return f"{margin:.1f}%"
        return ""

    # ── ForegroundRole ───────────────────────────────────────────

    def _foreground(self, p: dict, c: int):
        if c == 16:
            profit = p.get("profit", 0) or 0
            if profit > 0:
                return QColor(theme.GREEN)
            if profit < 0:
                return QColor(theme.RED)
        if c == 11:
            status = p.get("status", "")
            if status in ("in_progress", "running"):
                rem = _remaining(p)
                if rem is not None and rem <= 0:
                    return QColor(theme.ACCENT_RED)
                return QColor(theme.PRIMARY)
            if status == "ready":
                return QColor(theme.ACCENT_ORANGE)
        if c == 7:
            status = p.get("status", "")
            if status in ("completed", "done"):
                return QColor(theme.GREEN)
            if status in ("in_progress", "running"):
                return QColor(theme.PRIMARY)
            if status == "ready":
                return QColor(theme.ACCENT_ORANGE)
            if status == "pending":
                return QColor(theme.TEXT_SECONDARY)
        return None

    # ── headerData ───────────────────────────────────────────────

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            label = self._HEADERS[section]
            if section == self._sort_col:
                arrow = " ▲" if self._sort_order == Qt.SortOrder.AscendingOrder else " ▼"
                label = label.rstrip(" ↓↑▲▼") + arrow
            return label
        return None

    # ── flags / setData — 行内编辑 ───────────────────────────────

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        col = index.column()
        if col in self._EDITABLE_COLS:
            row = self._plans[index.row()] if index.row() < len(self._plans) else {}
            if row.get("status") not in ("completed", "done"):
                return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        row_idx = index.row()
        col = index.column()
        if col not in self._EDITABLE_COLS:
            return False
        plan = self._plans[row_idx]
        # 直接写内存模型
        if col == 4:
            plan["notes"] = str(value)
        elif col == 8:
            plan["char_name"] = str(value)
        elif col == 13:
            plan["facility"] = str(value)
        elif col == 14:
            try:
                plan["output"] = int(value)
            except (ValueError, TypeError):
                plan["output"] = 0
        else:
            return False
        self.dataChanged.emit(index, index, [role])
        return True

    # ── 排序 ─────────────────────────────────────────────────────

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        key = self._SORT_KEYS.get(column)
        if key is None:
            return
        self.beginResetModel()
        reverse = order == Qt.SortOrder.DescendingOrder
        if column in self._NUMERIC_SORT_COLS:
            self._plans.sort(key=lambda p: p.get(key, 0) or 0, reverse=reverse)
        else:
            self._plans.sort(key=lambda p: (p.get(key, "") or "").lower(), reverse=reverse)
        self._sort_col = column
        self._sort_order = order
        self.endResetModel()

    # ── 原地更新数据（保留选中 / selection model）───────────────

    def set_plans(self, plans: list[dict]) -> None:
        """替换所有数据 — 保持同一个 model 实例，避免 setModel 清除选中"""
        self.beginResetModel()
        self._plans = plans
        self._sort_col = -1
        self.endResetModel()

    def get_plan(self, row: int) -> dict:
        return self._plans[row] if 0 <= row < len(self._plans) else {}

    def tick(self) -> list[int]:
        """倒计时 tick：遍历进行中行算剩余；≤0 内存置 ready；对变动行 emit dataChanged。

        返回本次转为 ready 的 plan_id 列表，供上层一次 UPDATE 持久化（倒计时到期 → 待下线）。
        """
        now = datetime.now(UTC)
        expired: list[int] = []
        for row in range(len(self._plans)):
            p = self._plans[row]
            if p.get("status") not in ("in_progress", "running"):
                continue
            rem = _remaining(p, now=now)
            if rem is None:
                continue
            if rem <= 0 and p.get("status") != "ready":
                p["status"] = "ready"
                if p.get("id"):
                    expired.append(p["id"])
                self.dataChanged.emit(
                    self.index(row, 7),
                    self.index(row, 11),
                    [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole],
                )
            else:
                self.dataChanged.emit(
                    self.index(row, 11),
                    self.index(row, 11),
                    [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole],
                )
        return expired


class MaterialTableModel(QAbstractTableModel):
    _HEADERS = ["材料", "总需求", "单价", "总价"]

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

    def rowCount(self, parent=None):
        return len(self._items)

    def columnCount(self, parent=None):
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
        "材料成本",
        "利润",
        "利润率",
        "评分",
        "时均产量",
        "状态",
        "创建时间",
    ]

    # 状态 → 中文映射
    STATUS_LABELS = {"pending": "待排", "running": "运行", "done": "完成", "paused": "暂停"}

    def __init__(self, plans: list[dict]):
        super().__init__()
        self._plans = plans

    def rowCount(self, parent=None):
        return len(self._plans)

    def columnCount(self, parent=None):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self._plans[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            cols = [
                p.get("product_name", f"ID:{p.get('product_type_id', '')}"),
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
            if c == 2:
                return QColor(theme.GREEN) if p.get("profit", 0) > 0 else QColor(theme.RED)
            if c == 4:
                s = p.get("score", 0)
                return QColor(theme.GREEN) if s >= 70 else (QColor(theme.RED) if s < 30 else QColor(theme.PRIMARY))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def get_plan(self, row: int) -> dict:
        return self._plans[row] if 0 <= row < len(self._plans) else {}
