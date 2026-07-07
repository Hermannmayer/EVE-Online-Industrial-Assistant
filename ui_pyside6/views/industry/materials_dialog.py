"""
填料总表（BOM展开） — 从活跃计划递归展开 BOM，与库存对比
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


class MaterialsSummaryDialog(QWidget):
    """填料总表对话框"""

    _COLUMNS = ["材料名称", "层级", "所需数量", "库存数量", "缺口", "单价", "总价", "体积"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("填料总表")
        self.setMinimumSize(900, 600)
        self.setMaximumSize(1400, 900)
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

        layout.addWidget(self._table)
        layout.addWidget(self._status_label)

    def showEvent(self, event):
        super().showEvent(event)
        self.load_data()

    def load_data(self):
        """查询活跃计划 BOM + 库存"""
        self._table.setRowCount(0)

        conn_ctx = get_container().db.connect("user", "ref", "bp")
        conn = conn_ctx.__enter__()
        try:
            # 1) 活跃计划
            active_plans = conn.execute(
                "SELECT product_type_id, runs, parallels FROM production_plans "
                "WHERE status IN ('pending','in_progress','running')"
            ).fetchall()
            if not active_plans:
                self._status_label.setText("没有活跃计划")
                return

            # 2) 递归展开 BOM
            # materials[type_id] = {"name": ..., "total_qty": ..., "level": ...}
            materials: dict[int, dict] = {}
            seen: set[int] = set()

            def _expand(product_type_id: int, qty: int, level: int):
                if product_type_id in seen:
                    if product_type_id in materials:
                        materials[product_type_id]["total_qty"] += qty
                    return
                seen.add(product_type_id)

                # 找蓝图
                bp_row = conn.execute(
                    "SELECT blueprint_type_id FROM blueprint_products "
                    "WHERE product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
                    (product_type_id,),
                ).fetchone()
                if not bp_row:
                    # 原料，记录
                    name = _get_name(conn, product_type_id)
                    vol = _get_volume(conn, product_type_id)
                    if product_type_id in materials:
                        materials[product_type_id]["total_qty"] += qty
                    else:
                        materials[product_type_id] = {
                            "name": name,
                            "total_qty": qty,
                            "level": level,
                            "volume": vol,
                        }
                    return

                bp_tid = bp_row[0]
                prod_row = conn.execute(
                    "SELECT quantity FROM blueprint_products "
                    "WHERE blueprint_type_id = ? AND product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
                    (bp_tid, product_type_id),
                ).fetchone()
                per_run = prod_row[0] if prod_row else 1
                if per_run < 1:
                    per_run = 1

                # 材料
                mats = conn.execute(
                    "SELECT material_type_id, quantity FROM blueprint_materials "
                    "WHERE blueprint_type_id = ? AND activity = 'manufacturing'",
                    (bp_tid,),
                ).fetchall()
                for mat_tid, mat_qty in mats:
                    mat_total = (qty * mat_qty + per_run - 1) // per_run
                    if mat_tid in materials:
                        materials[mat_tid]["total_qty"] += mat_total
                    else:
                        name = _get_name(conn, mat_tid)
                        vol = _get_volume(conn, mat_tid)
                        materials[mat_tid] = {
                            "name": name,
                            "total_qty": mat_total,
                            "level": level,
                            "volume": vol,
                        }
                    # 递归展开中间产物
                    _expand(mat_tid, mat_total, level + 1)

            for plan in active_plans:
                _expand(plan[0], plan[1] * plan[2], 0)

            if not materials:
                self._status_label.setText("没有材料需求")
                return

            # 3) 库存
            inv_rows = conn.execute("SELECT type_id, SUM(quantity) FROM inventory_items GROUP BY type_id").fetchall()
            inventory: dict[int, int] = {r[0]: r[1] or 0 for r in inv_rows}

            # 4) 市场单价（均价）
            price_rows = conn.execute("SELECT type_id, average_price FROM market_prices").fetchall()
            prices: dict[int, float] = {r[0]: r[1] or 0.0 for r in price_rows}

        finally:
            conn_ctx.__exit__(None, None, None)

        # 5) 填充表格 — 按 level 排序（0=原料在前）
        sorted_mats = sorted(materials.items(), key=lambda x: (x[1]["level"], x[1]["name"]))
        self._table.setRowCount(len(sorted_mats))
        total_cost = 0.0

        for row_idx, (type_id, info) in enumerate(sorted_mats):
            needed = info["total_qty"]
            owned = inventory.get(type_id, 0)
            gap = max(0, needed - owned)
            unit_price = prices.get(type_id, 0.0)
            line_cost = gap * unit_price
            total_cost += line_cost
            vol = info["volume"]

            items = [
                info["name"],
                str(info["level"]),
                f"{needed:,}",
                f"{owned:,}",
                f"{gap:,}",
                _fmt_isk(unit_price),
                _fmt_isk(line_cost),
                f"{vol:.2f}" if vol else "—",
            ]
            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col_idx == 4 and gap > 0:
                    item.setForeground(theme.ACCENT_RED)
                elif col_idx == 4 and gap == 0:
                    item.setForeground(theme.ACCENT_GREEN)
                self._table.setItem(row_idx, col_idx, item)

        total = len(sorted_mats)
        total_gap = sum(max(0, m["total_qty"] - inventory.get(tid, 0)) for tid, m in sorted_mats)
        self._status_label.setText(f"共 {total} 种材料，缺口 {total_gap} 项，缺口总价 {_fmt_isk(total_cost)}")

    def _on_theme_changed(self):
        self.setStyleSheet(theme.get_stylesheet() + "QTableWidget::item { padding: 2px 6px; }")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")


def _get_name(conn, type_id: int) -> str:
    row = conn.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (type_id,)).fetchone()
    if row:
        return row[0] or row[1] or str(type_id)
    return str(type_id)


def _get_volume(conn, type_id: int) -> float:
    row = conn.execute("SELECT volume FROM item WHERE type_id = ?", (type_id,)).fetchone()
    return row[0] if row else 0.0


def _fmt_isk(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"
