"""
所需蓝图清单 — 展开所有活跃计划的 BOM，列出蓝图需求与拥有情况

考虑蓝图剩余流程数: BPO 无限, BPC 按 quantity × runs 计算可用流程。
三色状态: 足够(绿)、不足(黄)、缺少(红)
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services.plan_aggregator import (
    check_user_blueprints,
    expand_blueprint_requirements,
)


class _StatusTableWidgetItem(QTableWidgetItem):
    """自定义排序项 — 按状态优先级排序"""

    _PRIORITY = {"缺少": 0, "不足": 1, "足够": 2, "—": 9}

    def __lt__(self, other):
        if isinstance(other, _StatusTableWidgetItem):
            p1 = self._PRIORITY.get(self.text(), 9)
            p2 = self._PRIORITY.get(other.text(), 9)
            return p1 < p2
        return super().__lt__(other)


class BlueprintRequirementsDialog(QDialog):
    """所需蓝图清单对话框"""

    _COLUMNS = ["蓝图名称", "类型", "材料等级", "时间等级", "所需流程数", "可用流程数", "状态"]

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
        """从数据库查询活跃计划，通过 plan_aggregator 展开 BOM 并对比蓝图库存"""
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        with get_container().db.connect("user", "ref", "bp") as conn:
            # 1) 查所有活跃计划
            active_plans = conn.execute(
                "SELECT id, product_type_id, product_name, runs, parallels, me_level "
                "FROM production_plans WHERE status IN ('pending','in_progress','running','ready')"
            ).fetchall()

            if not active_plans:
                self._status_label.setText("没有活跃计划")
                return

            plans = [
                {
                    "product_type_id": r[1],
                    "product_name": r[2],
                    "runs": r[3],
                    "parallels": r[4],
                    "me_level": r[5],
                }
                for r in active_plans
            ]

            # 2) 展开蓝图需求
            needed = expand_blueprint_requirements(conn, plans)

            if not needed:
                self._status_label.setText("没有蓝图需求")
                return

            # 3) 查询用户蓝图库存
            bp_inv = check_user_blueprints(conn, set(needed.keys()))

        # 4) 填充表格
        self._table.setRowCount(len(needed))
        for row_idx, (bp_tid, info) in enumerate(
            sorted(needed.items(), key=lambda x: x[1].get("name", str(x[0])))
        ):
            name = info["name"]
            needed_runs = info["needed_runs"]
            inv = bp_inv.get(bp_tid, {})

            if inv.get("is_bpo"):
                bp_type = "BPO"
                me = str(inv.get("best_me", 0))
                te = str(inv.get("best_te", 0))
                available = "无限"
                status = "足够"
                status_color = theme.ACCENT_GREEN
            elif inv.get("available_runs", 0) >= needed_runs:
                bp_type = "BPC"
                me = str(inv.get("best_me", 0))
                te = str(inv.get("best_te", 0))
                avail_runs = int(inv.get("available_runs", 0))
                available = f"{avail_runs:,}"
                status = "足够"
                status_color = theme.ACCENT_GREEN
            elif inv.get("available_runs", 0) > 0:
                bp_type = "BPC"
                me = str(inv.get("best_me", 0))
                te = str(inv.get("best_te", 0))
                avail_runs = int(inv.get("available_runs", 0))
                available = f"{avail_runs:,}"
                status = "不足"
                status_color = theme.ACCENT_YELLOW
            else:
                bp_type = "—"
                me = "—"
                te = "—"
                available = "—"
                status = "缺少"
                status_color = theme.ACCENT_RED

            items = [
                name,
                bp_type,
                me,
                te,
                f"{needed_runs:,}",
                available,
                status,
            ]
            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col_idx == 6:  # 状态列
                    item = _StatusTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setForeground(QColor(status_color))
                self._table.setItem(row_idx, col_idx, item)

        self._table.setSortingEnabled(True)
        total = len(needed)
        missing = sum(
            1 for bp_tid, info in needed.items()
            if bp_inv.get(bp_tid, {}).get("available_runs", 0) <= 0
        )
        insufficient = sum(
            1 for bp_tid, info in needed.items()
            if 0 < bp_inv.get(bp_tid, {}).get("available_runs", 0) < info["needed_runs"]
        )
        enough = total - missing - insufficient
        self._status_label.setText(
            f"共 {total} 类蓝图，足够 {enough} 种，不足 {insufficient} 种，缺少 {missing} 种"
        )

    def _on_theme_changed(self):
        self.setStyleSheet(theme.get_stylesheet() + "QTableWidget::item { padding: 2px 6px; }")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
