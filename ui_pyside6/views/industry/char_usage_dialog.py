"""
人物占用情况 — 按角色统计活跃计划数和占用详情
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


class CharacterUsageDialog(QWidget):
    """人物占用情况对话框"""

    _COLUMNS = ["角色名称", "活跃计划数", "队列时长", "技能等级", "占用详情"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("人物占用情况")
        self.setMinimumSize(700, 400)
        self.setMaximumSize(1100, 700)
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
        """按 char_name GROUP BY 统计活跃计划"""
        self._table.setRowCount(0)

        conn_ctx = get_container().db.connect("user")
        conn = conn_ctx.__enter__()
        try:
            rows = conn.execute(
                "SELECT char_name, COUNT(*) as cnt, "
                "GROUP_CONCAT(COALESCE(product_name, CAST(product_type_id TEXT)), ', ') as details "
                "FROM production_plans "
                "WHERE status IN ('pending', 'in_progress', 'running') "
                "GROUP BY char_name "
                "ORDER BY cnt DESC"
            ).fetchall()
        finally:
            conn_ctx.__exit__(None, None, None)

        if not rows:
            self._status_label.setText("没有活跃计划")
            return

        self._table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            char_name = row[0] or "(未分配)"
            plan_count = row[1]
            details = row[2] or "—"

            items = [
                char_name,
                str(plan_count),
                "N/A",
                "N/A",
                details,
            ]
            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col_idx == 4:  # 占用详情列左对齐
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                # 活跃计划数着色
                if col_idx == 1:
                    if plan_count >= 5:
                        item.setForeground(theme.ACCENT_RED)
                    elif plan_count >= 3:
                        item.setForeground(theme.ACCENT_YELLOW)
                    else:
                        item.setForeground(theme.ACCENT_GREEN)
                self._table.setItem(row_idx, col_idx, item)

        total_plans = sum(row[1] for row in rows)
        self._status_label.setText(f"共 {len(rows)} 个角色，{total_plans} 个活跃计划")

    def _on_theme_changed(self):
        self.setStyleSheet(theme.get_stylesheet() + "QTableWidget::item { padding: 2px 6px; }")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
