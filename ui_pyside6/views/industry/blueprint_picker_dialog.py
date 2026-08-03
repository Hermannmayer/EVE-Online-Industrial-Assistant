"""蓝图选择弹窗 — 单击计划蓝图列 / 右键「绑定库存蓝图」时弹出。

列出该产品对应的库存蓝图（BPO/BPC、ME/TE、剩余流程、机库、占用状态），
单选绑定到计划；BPC 已被其他活跃计划占用或容量不足的行置灰。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services import plan_execution


class BlueprintPickerDialog(QDialog):
    """绑定库存蓝图弹窗"""

    _HEADERS = ["选择", "类型", "ME", "TE", "可用流程", "机库", "状态"]

    def __init__(self, plan: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._plan = plan
        self.selected_blueprint_id: int | None = None
        self.unbound: bool = False
        self._options: list[dict] = []
        self._selected_row: int = -1
        self._blueprint_type_id: int | None = None

        self.setWindowTitle(f"绑定库存蓝图 - {plan.get('product_name', '')}")
        self.setMinimumSize(640, 440)
        self._build_ui()
        self._load()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        self._need_label = QLabel("")
        root.addWidget(self._need_label)

        self._table = QTableWidget()
        self._table.setColumnCount(len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.cellClicked.connect(self._on_cell_clicked)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._table, 1)

        self._empty_hint = QLabel("")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._empty_hint)

        btns = QDialogButtonBox()
        npc_btn = QPushButton("查看NPC卖家")
        npc_btn.clicked.connect(self._on_npc_seller)
        btns.addButton(npc_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self._unbind_btn = QPushButton("解除绑定")
        self._unbind_btn.clicked.connect(self._on_unbind)
        self._unbind_btn.setEnabled(bool(self._plan.get("assigned_blueprint_id")))
        btns.addButton(self._unbind_btn, QDialogButtonBox.ButtonRole.ActionRole)
        bind_btn = QPushButton("绑定")
        bind_btn.clicked.connect(self._on_bind)
        btns.addButton(bind_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton(QDialogButtonBox.StandardButton.Cancel)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ── 数据加载 ──────────────────────────────────────────────

    def _load(self) -> None:
        product_type_id = self._plan.get("product_type_id")
        runs = max(int(self._plan.get("runs", 1)), 1)
        parallels = max(int(self._plan.get("parallels", 1)), 1)
        need_runs = runs * parallels
        self._need_label.setText(
            f"产品 {self._plan.get('product_name', '')}  需要蓝图流程: {need_runs}（{parallels} 并行 × {runs} 流程）"
        )

        assigned_id = self._plan.get("assigned_blueprint_id")
        with get_container().db.connect("user", "bp", "ref") as conn:
            cur = conn.execute(
                "SELECT blueprint_type_id FROM bp.blueprint_products "
                "WHERE product_type_id=? AND activity='manufacturing' LIMIT 1",
                (product_type_id,),
            )
            row = cur.fetchone()
            if not row:
                self._empty_hint.setText("无法确定该产品的蓝图类型")
                self._table.setEnabled(False)
                return
            self._blueprint_type_id = row[0]
            options = plan_execution.find_available_blueprints(conn, row[0])

        self._options = options
        if not options:
            self._empty_hint.setText("库存中没有该蓝图。可通过「查看NPC卖家」购买原图，或从游戏粘贴导入。")
            self._table.setEnabled(False)
            return

        self._table.setRowCount(len(options))
        for i, opt in enumerate(options):
            disabled = not opt.get("is_bpo") and (opt.get("occupied") or (opt.get("available_runs") or 0) < need_runs)
            bp_type = "原图" if opt.get("is_bpo") else "拷贝"
            avail = "无限" if opt.get("is_bpo") else f"{opt.get('available_runs', 0):,.0f}"
            status = "占用中" if opt.get("occupied") else "可用"
            if not opt.get("is_bpo") and not opt.get("occupied") and (opt.get("available_runs") or 0) < need_runs:
                status = "流程不足"

            cells = [
                "",
                bp_type,
                str(opt.get("me_level", 0)),
                str(opt.get("te_level", 0)),
                avail,
                opt.get("hangar_name", "") or "-",
                status,
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if disabled:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    item.setForeground(QColor(theme.TEXT_SECONDARY))
                else:
                    item.setForeground(QColor(theme.TEXT_PRIMARY))
                self._table.setItem(i, c, item)
            if opt.get("id") == assigned_id and not disabled:
                self._selected_row = i

        self._refresh_selector()
        if self._selected_row >= 0:
            self._table.selectRow(self._selected_row)
        else:
            self._table.selectRow(0)
            self._selected_row = 0
        self._table.resizeColumnsToContents()

    # ── 交互 ──────────────────────────────────────────────────

    def _on_cell_clicked(self, row: int, _col: int) -> None:
        item = self._table.item(row, 0)
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        self._selected_row = row
        self._refresh_selector()
        self._table.selectRow(row)

    def _refresh_selector(self) -> None:
        for i in range(self._table.rowCount()):
            item = self._table.item(i, 0)
            if item is None:
                continue
            item.setText("●" if i == self._selected_row else "")

    def _on_bind(self) -> None:
        if self._selected_row < 0 or self._selected_row >= len(self._options):
            return
        opt = self._options[self._selected_row]
        plan_id = self._plan.get("id")
        if not plan_id:
            return
        if not plan_execution.bind_blueprint(plan_id, opt["id"]):
            QMessageBox.warning(self, "绑定失败", "该蓝图已被其他活跃计划占用")
            return
        self.selected_blueprint_id = int(opt["id"])
        self.accept()

    def _on_unbind(self) -> None:
        """解除当前蓝图绑定（释放占用），不消耗 BPC"""
        plan_id = self._plan.get("id")
        if not plan_id:
            return
        plan_execution.release_blueprint(plan_id)
        self.unbound = True
        self.accept()

    def _on_npc_seller(self) -> None:
        from ui_pyside6.dialogs.npc_seller_dialog import NpcSellerDialog

        bp_id = self._blueprint_type_id
        if not bp_id:
            return
        name = self._plan.get("product_name", str(bp_id))
        dlg = NpcSellerDialog(bp_id, name, self)
        dlg.exec()

    # ── 主题 ──────────────────────────────────────────────────

    def _on_theme_changed(self) -> None:
        self.setStyleSheet(
            f"QDialog {{ background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; }}"
            f"QLabel {{ color: {theme.TEXT_PRIMARY}; background: transparent; font-size: 12px; }}"
            f"QTableWidget {{ background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f" border: 1px solid {theme.BORDER}; border-radius: 4px; gridline-color: {theme.BORDER}; }}"
            f"QHeaderView::section {{ background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f" border: 1px solid {theme.BORDER}; padding: 3px 6px; }}"
            f"QTableWidget::item:selected {{ background: {theme.PRIMARY}; color: {theme.TEXT_BRIGHT}; }}"
            f"QPushButton {{ padding: 4px 16px; border: 1px solid {theme.BORDER}; border-radius: 4px;"
            f" background: transparent; color: {theme.TEXT_PRIMARY}; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {theme.PRIMARY}; color: {theme.PRIMARY}; }}"
        )
