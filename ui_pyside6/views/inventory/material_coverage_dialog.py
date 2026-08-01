"""
仓库页面 — 材料覆盖率/缺口视图对话框

以某个机库为材料机库的活跃生产计划聚合材料需求，展示 需求/现有/缺口，
缺口 > 0 的行用红色高亮。空态提示该机库未被任何计划用作材料机库。
"""

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableView,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from services.plan_execution import aggregate_material_requirements, get_plans_for_mat_hangar

# ════════════════════════════════════════════════════
#  CoverageModel
# ════════════════════════════════════════════════════


class CoverageModel(QAbstractTableModel):
    """材料覆盖表格模型（材料/需求/现有/缺口）"""

    _HEADERS = ["材料", "需求", "现有", "缺口"]

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
                return r.get("name", "")
            if c == 1:
                return f"{r['need']:,}"
            if c == 2:
                return f"{r['owned']:,}"
            if c == 3:
                return f"{r['missing']:,}"

        elif role == Qt.ItemDataRole.ForegroundRole:
            if c == 3 and (r.get("missing") or 0) > 0:
                return QColor(theme.ACCENT_RED)

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if c >= 1:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def row_at(self, row: int) -> dict | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None


# ════════════════════════════════════════════════════
#  MaterialCoverageDialog
# ════════════════════════════════════════════════════


class MaterialCoverageDialog(QDialog):
    """材料覆盖率/缺口 — 以该机库为材料机库的活跃计划聚合材料需求"""

    def __init__(self, hangar_id: int, hangar_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"材料覆盖 — {hangar_name}")
        self.setMinimumSize(520, 420)
        self.resize(620, 500)
        self._hangar_id = hangar_id
        self._plans_label: QLabel | None = None
        self._summary_label: QLabel | None = None
        self._empty_label: QLabel | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        plans = get_plans_for_mat_hangar(hangar_id)

        # 顶部计划汇总
        self._plans_label = QLabel(self._plans_summary(plans))
        self._plans_label.setWordWrap(True)
        self._plans_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(self._plans_label)

        # 表格
        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        if not plans:
            # 空态：未被任何计划用作材料机库
            self._empty_label = QLabel("该机库未被任何计划用作材料机库")
            self._empty_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
            self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self._empty_label)
            self._table.setModel(CoverageModel([]))
            self._summary_label = QLabel("关联计划 0 条")
        else:
            rows = aggregate_material_requirements(plans, hangar_id)
            self._table.setModel(CoverageModel(rows))
            missing_kind = sum(1 for r in rows if (r.get("missing") or 0) > 0)
            missing_total = sum(int(r.get("missing") or 0) for r in rows)
            self._summary_label = QLabel(f"缺 {missing_kind} 种 / 共 {missing_total:,} 件")

        if self._summary_label is not None:
            self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
            layout.addWidget(self._summary_label)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        theme.add_theme_listener(self._on_theme_changed)

    @staticmethod
    def _plans_summary(plans: list[dict]) -> str:
        """顶部汇总：关联计划条数与名称列表。"""
        if not plans:
            return "关联计划 0 条"
        names = []
        for p in plans:
            status = p.get("status", "")
            label = {"pending": "待生产", "in_progress": "生产中", "ready": "待完成"}.get(status, status)
            names.append(f"「{p.get('product_name') or p.get('product_type_id', '')}」({label})")
        head = " | ".join(names[:6])
        if len(plans) > 6:
            head += f" 等 {len(plans)} 条计划"
        else:
            head += f" · 共 {len(plans)} 条计划"
        return head

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式并重绘表格（缺口红色跟随主题）"""
        if self._plans_label is not None:
            self._plans_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        if self._summary_label is not None:
            self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        if self._empty_label is not None:
            self._empty_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        self._table.viewport().update()
