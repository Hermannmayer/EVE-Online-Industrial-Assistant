"""
填料总表（BOM展开） — 从活跃计划递归展开 BOM，与库存对比

功能:
  - 显示每种材料的总需求、已有库存、缺口
  - 三色状态标记: 已到位(绿)、部分到位(橙)、未到位(红)
  - 每行"复制"按钮一键复制名称+需购量到剪贴板
  - 顶部"一键复制全部"按钮
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services.plan_aggregator import (
    check_inventory,
    expand_material_requirements,
    get_market_prices,
)


class _CopyButton(QPushButton):
    """材料行内的复制按钮"""

    def __init__(self, text_to_copy: str, mat_name: str, gap: float, parent=None):
        super().__init__("复制", parent)
        self._text = text_to_copy
        self._mat_name = mat_name
        self._gap = gap
        self.setFixedSize(50, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("复制名称和需购量到剪贴板")
        self.clicked.connect(self._on_copy)

    def _on_copy(self):
        QApplication.clipboard().setText(self._text)
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            self,
            "已复制",
            f"{self._mat_name}\n需购: {self._gap:,.0f}\n已复制到剪贴板",
        )


class MaterialsSummaryDialog(QDialog):
    """填料总表对话框"""

    _COLUMNS = ["材料名称", "层级", "总需求", "库存", "缺口", "单价", "总价", "体积", "状态", "复制采购"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("填料总表")
        self.setMinimumSize(950, 600)
        self.setMaximumSize(1400, 900)
        self._setup_ui()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        # 顶栏：总览 + 一键复制全部
        top_bar = QHBoxLayout()
        self._status_label = QLabel("正在加载...")
        top_bar.addWidget(self._status_label, 1)
        self._copy_all_btn = QPushButton("一键复制全部")
        self._copy_all_btn.setFixedHeight(26)
        self._copy_all_btn.clicked.connect(self._on_copy_all)
        top_bar.addWidget(self._copy_all_btn)
        layout.addLayout(top_bar)

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

    def showEvent(self, event):
        super().showEvent(event)
        self.load_data()

    def load_data(self):
        """查询活跃计划 BOM + 库存 + 市场价格，填充表格"""
        self._table.setRowCount(0)
        self._data_rows: list[dict] = []  # 存储行数据供"一键复制"使用

        with get_container().db.connect("user", "ref", "bp", "mkt") as conn:
            # 1) 活跃计划
            active_plans = conn.execute(
                "SELECT product_type_id, runs, parallels, me_level "
                "FROM production_plans WHERE status IN ('pending','in_progress','running','ready')"
            ).fetchall()
            if not active_plans:
                self._status_label.setText("没有活跃计划")
                return

            plans = [
                {
                    "product_type_id": r[0],
                    "runs": r[1],
                    "parallels": r[2],
                    "me_level": r[3],
                }
                for r in active_plans
            ]

            # 2) 展开 BOM 到叶子节点
            materials = expand_material_requirements(conn, plans)
            if not materials:
                self._status_label.setText("没有材料需求")
                return

            # 3) 库存
            inventory = check_inventory(conn, set(materials.keys()))

            # 4) 市场价
            prices = get_market_prices(conn, set(materials.keys()))

        # 5) 填充表格 — 按层级排序
        sorted_mats = sorted(materials.items(), key=lambda x: (x[1].get("_level", 0), x[1]["name"]))

        self._table.setRowCount(len(sorted_mats))
        total_cost = 0.0
        self._data_rows = []

        for row_idx, (type_id, info) in enumerate(sorted_mats):
            needed = info["total_qty"]
            owned = inventory.get(type_id, 0)
            gap = max(0, int(needed) - owned)
            unit_price = prices.get(type_id, {}).get("sell", 0.0)
            line_cost = gap * unit_price
            if unit_price:
                total_cost += line_cost
            vol = info.get("volume", 0)

            # 状态
            if gap <= 0:
                status_text = "已到位"
                status_color = theme.ACCENT_GREEN
            elif owned > 0:
                status_text = "部分到位"
                status_color = theme.ACCENT_YELLOW
            else:
                status_text = "未到位"
                status_color = theme.ACCENT_RED

            # 缺口着色
            if gap > 0:
                gap_color = theme.ACCENT_RED
            else:
                gap_color = theme.ACCENT_GREEN

            items_text = [
                info["name"],
                "0",  # 所有叶子节点层级为 0（原料）
                f"{needed:,.0f}",
                f"{owned:,}",
                f"{gap:,}",
                _fmt_isk(unit_price),
                _fmt_isk(line_cost),
                f"{vol:.2f}" if vol else "—",
                status_text,
            ]

            for col_idx, text in enumerate(items_text):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col_idx == 4:  # 缺口
                    item.setForeground(QColor(gap_color))
                if col_idx == 8:  # 状态
                    item.setForeground(QColor(status_color))
                self._table.setItem(row_idx, col_idx, item)

            # 复制按钮列
            copy_text = f"{info['name']}\t{gap:,.0f}"
            copy_btn = _CopyButton(copy_text, info["name"], gap)
            self._table.setCellWidget(row_idx, 9, copy_btn)

            # 保存行数据供"一键复制"
            self._data_rows.append(
                {
                    "name": info["name"],
                    "gap": gap,
                    "unit_price": unit_price,
                }
            )

        total_types = len(sorted_mats)
        ready_count = sum(1 for r in self._data_rows if r["gap"] <= 0)
        partial_count = sum(
            1
            for tid, info in sorted_mats
            if 0 < max(0, int(info["total_qty"]) - inventory.get(tid, 0)) < int(info["total_qty"])
        )
        # 部分到位的修正：排除已到位的
        missing_count = total_types - ready_count - partial_count
        self._status_label.setText(
            f"共 {total_types} 种材料，已到位 {ready_count} 种，"
            f"部分到位 {partial_count} 种，未到位 {missing_count} 种，缺口总价 {_fmt_isk(total_cost)}"
        )

    def _on_copy_all(self):
        """一键复制全部待采购材料到剪贴板"""
        if not self._data_rows:
            return
        lines = []
        total_gap = 0
        for r in self._data_rows:
            if r["gap"] > 0:
                lines.append(f"{r['name']}* {r['gap']:.0f}")
                total_gap += r["gap"]
        if not lines:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(self, "提示", "所有材料已到位，无需采购")
            return

        QApplication.clipboard().setText("\n".join(lines))
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(self, "已复制", f"已复制 {len(lines)} 种待采购材料（共 {total_gap:,.0f} 个）到剪贴板")

    def _on_theme_changed(self):
        self.setStyleSheet(theme.get_stylesheet() + "QTableWidget::item { padding: 2px 6px; }")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")


def _fmt_isk(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"
