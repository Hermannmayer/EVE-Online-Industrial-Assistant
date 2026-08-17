"""工业制造 — Table Model 类"""

from datetime import UTC, datetime
from typing import cast

from PySide6.QtCore import QAbstractTableModel, Qt


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


def _sort_key(value):
    """列排序键：数值（含 bool）按大小、文本按小写，类型混合也不崩。

    返回 (组, 值) 元组保证任何组合可比：数值组在前（0）、文本组在后（1）。
    None/空值归入文本组空串，升序时排后。
    """
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, int | float):
        return (0, value)
    return (1, str(value or "").lower())


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
    _EDITABLE_COLS = {4, 8, 13}

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
        14: "output_hangar",
        15: "material_cost",
        16: "profit",
        17: "market_margin",
        18: "personal_margin",
    }

    # 数值列（排序时按数字比较）
    _NUMERIC_SORT_COLS = {0, 5, 6, 9, 10, 11, 12, 15, 16, 17, 18}

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
        self._collapsed_groups: set[int] = set()  # 被折叠的 group_id 集合

    # ── 折叠/展开 ──────────────────────────────────────────────

    def toggle_collapse(self, group_id: int) -> None:
        """切换指定组的折叠状态"""
        if group_id in self._collapsed_groups:
            self._collapsed_groups.discard(group_id)
        else:
            self._collapsed_groups.add(group_id)
        self.beginResetModel()
        self.endResetModel()

    def _is_visible(self, plan: dict) -> bool:
        """判断行是否可见（未被折叠隐藏）"""
        gid = plan.get("group_id") or plan.get("group_number") or 0
        lvl = int(plan.get("child_level") or plan.get("sub_level") or 0)
        if lvl == 0:
            return True  # 母项始终可见
        return gid not in self._collapsed_groups

    def _visible_plans(self) -> list[dict]:
        """返回过滤后的可见行列表"""
        return [p for p in self._plans if self._is_visible(p)]

    def _has_children(self, group_id: int) -> bool:
        """判断指定 group 是否有子项"""
        return any(
            (p.get("group_id") or p.get("group_number") or 0) == group_id
            and int(p.get("child_level") or p.get("sub_level") or 0) > 0
            for p in self._plans
        )

    def _row_map(self, filtered_row: int) -> int:
        """过滤行号 → 原始行号映射"""
        visible = self._visible_plans()
        if filtered_row >= len(visible):
            return filtered_row
        target = visible[filtered_row]
        for i, p in enumerate(self._plans):
            if p is target:
                return i
        return filtered_row

    def rowCount(self, parent=None):
        if self._collapsed_groups:
            return len(self._visible_plans())
        return len(self._plans)

    def columnCount(self, parent=None):
        return 19

    # ── data() — 只暴露已算数据（DisplayRole）+ 原始行（UserRole） ──

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        actual_row = self._row_map(index.row()) if self._collapsed_groups else index.row()
        p = self._plans[actual_row]
        c = index.column()
        if role == Qt.ItemDataRole.UserRole:
            return p
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_text(p, c)
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
            name = cast(str, p.get("product_name", f"ID:{p.get('product_type_id', '')}"))
            lvl = int(p.get("child_level") or 0)
            gid = p.get("group_id") or p.get("group_number") or 0
            if lvl > 0:
                return ("  " * lvl) + name  # 子项按层级缩进（配合 delegate 层级箭头）
            # 母项：如果有子项，显示折叠/展开图标
            if gid and self._has_children(gid):
                icon = "▼" if gid not in self._collapsed_groups else "▶"
                return f"{icon} {name}"
            return name
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
            return f"{parallels}X{runs}"
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
            return p.get("output_hangar", "") or "-"
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
            actual_row = self._row_map(index.row()) if self._collapsed_groups else index.row()
            row = self._plans[actual_row] if actual_row < len(self._plans) else {}
            if row.get("status") not in ("completed", "done"):
                return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        actual_row = self._row_map(index.row()) if self._collapsed_groups else index.row()
        col = index.column()
        if col not in self._EDITABLE_COLS:
            return False
        plan = self._plans[actual_row]
        # 直接写内存模型
        if col == 4:
            plan["notes"] = str(value)
        elif col == 8:
            plan["char_name"] = str(value)
        elif col == 13:
            plan["facility"] = str(value)
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
            self._plans.sort(key=lambda p: _sort_key(p.get(key)), reverse=reverse)
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
        actual_row = self._row_map(row) if self._collapsed_groups else row
        return self._plans[actual_row] if 0 <= actual_row < len(self._plans) else {}

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
