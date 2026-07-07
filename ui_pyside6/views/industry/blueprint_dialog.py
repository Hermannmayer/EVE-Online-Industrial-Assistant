"""
所需蓝图清单 — 展开所有活跃计划的 BOM，列出蓝图需求与拥有情况
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container


class _StatusTableWidgetItem(QTableWidgetItem):
    """自定义排序项 — 按状态优先级排序"""

    _PRIORITY = {"缺少": 0, "齐全": 1}

    def __lt__(self, other):
        if isinstance(other, _StatusTableWidgetItem):
            p1 = self._PRIORITY.get(self.text(), 9)
            p2 = self._PRIORITY.get(other.text(), 9)
            return p1 < p2
        return super().__lt__(other)


class BlueprintRequirementsDialog(QWidget):
    """所需蓝图清单对话框"""

    _COLUMNS = ["蓝图名称", "类型", "ME", "TE", "所需数量", "已拥有", "状态"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("所需蓝图清单")
        self.setMinimumSize(800, 500)
        self.setMaximumSize(1200, 800)
        self._setup_ui()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self._status_label = QLabel("正在加载...")
        self._table = QTableWidget()
        self._table.setColumnCount(len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)

        layout.addWidget(self._table)
        layout.addWidget(self._status_label)

    def showEvent(self, event):
        super().showEvent(event)
        self.load_data()

    def load_data(self):
        """从数据库查询活跃计划，递归展开 BOM，对比蓝图库存"""
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        conn_ctx = get_container().db.connect("user", "ref", "bp")
        conn = conn_ctx.__enter__()
        try:
            # 1) 查所有活跃计划
            active_plans = conn.execute(
                "SELECT product_type_id, product_name, runs, parallels "
                "FROM production_plans WHERE status IN ('pending','in_progress','running')"
            ).fetchall()
            if not active_plans:
                self._status_label.setText("没有活跃计划")
                return

            # 2) 收集所有需要的 blueprint_type_id → {bp_type_id: needed_runs}
            #    递归展开：product_type_id → 通过 blueprint_products 找蓝图 → blueprint_materials 找材料 → 递归
            needed: dict[int, int] = {}  # blueprint_type_id → total needed count
            seen_products: set[int] = set()

            def _expand(product_type_id: int, qty: int):
                """根据 product 找到蓝图，将蓝图加入 needed，并递归其材料"""
                if product_type_id in seen_products:
                    # 已处理过，累加数量
                    # 找到该 product 对应的 blueprint_type_id
                    bp_row = conn.execute(
                        "SELECT blueprint_type_id FROM blueprint_products "
                        "WHERE product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
                        (product_type_id,),
                    ).fetchone()
                    if bp_row:
                        bp_tid = bp_row[0]
                        needed[bp_tid] = needed.get(bp_tid, 0) + qty
                    return
                seen_products.add(product_type_id)

                # 找蓝图
                bp_row = conn.execute(
                    "SELECT blueprint_type_id FROM blueprint_products "
                    "WHERE product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
                    (product_type_id,),
                ).fetchone()
                if not bp_row:
                    return  # 无蓝图，可能是原料
                bp_tid = bp_row[0]
                needed[bp_tid] = needed.get(bp_tid, 0) + qty

                # 获取蓝图产出数量（每次 run 产出几个）
                prod_row = conn.execute(
                    "SELECT quantity FROM blueprint_products "
                    "WHERE blueprint_type_id = ? AND product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
                    (bp_tid, product_type_id),
                ).fetchone()
                per_run = prod_row[0] if prod_row else 1
                if per_run < 1:
                    per_run = 1

                # 获取蓝图材料
                materials = conn.execute(
                    "SELECT material_type_id, quantity FROM blueprint_materials "
                    "WHERE blueprint_type_id = ? AND activity = 'manufacturing'",
                    (bp_tid,),
                ).fetchall()
                for mat_type_id, mat_qty in materials:
                    mat_total = (qty * mat_qty + per_run - 1) // per_run  # 向上取整
                    _expand(mat_type_id, mat_total)

            for plan in active_plans:
                _expand(plan[0], plan[2] * plan[3])  # runs * parallels

            if not needed:
                self._status_label.setText("没有蓝图需求")
                return

            # 3) 查询用户蓝图库存
            bp_inventory: dict[int, dict] = {}  # blueprint_type_id → {count, best_me, best_te, is_bpo}
            bp_rows = conn.execute(
                "SELECT blueprint_type_id, SUM(quantity), "
                "MAX(me_level), MAX(te_level), MAX(is_bpo) "
                "FROM user_blueprints GROUP BY blueprint_type_id"
            ).fetchall()
            for row in bp_rows:
                bp_inventory[row[0]] = {
                    "count": row[1] or 0,
                    "me": row[2] or 0,
                    "te": row[3] or 0,
                    "is_bpo": bool(row[4]),
                }

            # 4) 查询蓝图名称
            bp_names: dict[int, str] = {}
            bp_name_rows = conn.execute(
                "SELECT b.blueprint_type_id, COALESCE(iz.zh_name, ie.en_name, '') "
                "FROM blueprint_products b "
                "LEFT JOIN item iz ON b.blueprint_type_id = iz.type_id "
                "LEFT JOIN item ie ON b.blueprint_type_id = ie.type_id "
                "WHERE b.activity = 'manufacturing'"
            ).fetchall()
            for row in bp_name_rows:
                if row[1]:
                    bp_names[row[0]] = row[1]

            # 也尝试直接从 item 表按 blueprint_type_id 查
            for bp_tid in needed:
                if bp_tid not in bp_names:
                    name_row = conn.execute(
                        "SELECT zh_name, en_name FROM item WHERE type_id = ?",
                        (bp_tid,),
                    ).fetchone()
                    if name_row:
                        bp_names[bp_tid] = name_row[0] or name_row[1] or str(bp_tid)

        finally:
            conn_ctx.__exit__(None, None, None)

        # 5) 填充表格
        self._table.setRowCount(len(needed))
        for row_idx, (bp_tid, req_qty) in enumerate(
            sorted(needed.items(), key=lambda x: bp_names.get(x[0], str(x[0])))
        ):
            name = bp_names.get(bp_tid, str(bp_tid))
            inv = bp_inventory.get(bp_tid)
            if inv:
                bp_type = "BPO" if inv["is_bpo"] else "BPC"
                me = str(inv["me"])
                te = str(inv["te"])
                owned = inv["count"]
                status = "齐全" if owned >= req_qty else "缺少"
            else:
                bp_type = "—"
                me = "—"
                te = "—"
                owned = 0
                status = "缺少"

            items = [
                name,
                bp_type,
                me,
                te,
                str(req_qty),
                str(owned),
                status,
            ]
            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col_idx == 6:  # 状态列
                    item = _StatusTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if text == "缺少":
                        item.setForeground(theme.ACCENT_RED)
                    else:
                        item.setForeground(theme.ACCENT_GREEN)
                self._table.setItem(row_idx, col_idx, item)

        self._table.setSortingEnabled(True)
        total = len(needed)
        missing = sum(1 for bp_tid, q in needed.items() if bp_inventory.get(bp_tid, {}).get("count", 0) < q)
        self._status_label.setText(f"共 {total} 种蓝图，缺少 {missing} 种")

    def _on_theme_changed(self):
        self.setStyleSheet(theme.get_stylesheet() + "QTableWidget::item { padding: 2px 6px; }")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
