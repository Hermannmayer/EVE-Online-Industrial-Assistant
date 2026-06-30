"""代采购管理 Tab"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from ui_pyside6.dialogs.industry_dialogs import ProcurementDialog
from ui_pyside6.models.industry_models import ProcurementTableModel


class ProcurementTab(QWidget):
    """代采购管理 Tab — 查看/管理 procurement_items"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = parent

        self.setObjectName("procurement_tab")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 工具栏 ──
        toolbar = QHBoxLayout()

        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self.load_items)
        toolbar.addWidget(self._refresh_btn)

        self._add_btn = QPushButton("添加代采购")
        self._add_btn.clicked.connect(self._on_add)
        toolbar.addWidget(self._add_btn)

        toolbar.addStretch()

        toolbar.addWidget(QLabel("状态:"))
        self._status_filter = QComboBox()
        self._status_filter.addItems(["全部", "待采购", "已下单", "已到货"])
        self._status_filter.currentTextChanged.connect(lambda: self.load_items())
        toolbar.addWidget(self._status_filter)

        toolbar.addWidget(QLabel("排序:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["按创建时间", "按优先级", "按数量"])
        self._sort_combo.currentTextChanged.connect(lambda: self.load_items())
        toolbar.addWidget(self._sort_combo)

        layout.addLayout(toolbar)

        # ── 表格 ──
        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSortingEnabled(False)
        self._table.verticalHeader().setDefaultSectionSize(26)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._table, 1)

        # ── 统计 ──
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        layout.addWidget(self._count_label)

        # ── 数据 ──
        self._items: list[dict] = []

        # 主题监听
        theme.add_theme_listener(self._on_theme_changed)

        # 初始加载
        self.load_items()

    def _on_theme_changed(self):
        """主题切换时重新应用样式"""
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")

    # ═══════════════════════════════════
    #  数据加载
    # ═══════════════════════════════════

    def load_items(self):
        """从 user.db 加载代采购条目，按状态筛选和排序"""
        status_map = {
            "全部": None,
            "待采购": "pending",
            "已下单": "ordered",
            "已到货": "received",
        }
        status_val = status_map.get(self._status_filter.currentText())

        sort_map = {
            "按创建时间": "created_at DESC",
            "按优先级": (
                "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 WHEN 'low' THEN 3 END"
            ),
            "按数量": "quantity DESC",
        }
        order_by = sort_map.get(self._sort_combo.currentText(), "created_at DESC")

        with get_container().db.connect("user") as conn:
            c = conn.cursor()
            if status_val:
                c.execute(
                    f"SELECT * FROM procurement_items WHERE status = ? ORDER BY {order_by}",
                    (status_val,),
                )
            else:
                c.execute(f"SELECT * FROM procurement_items ORDER BY {order_by}")
            cols = [d[0] for d in c.description]
            self._items = [dict(zip(cols, r)) for r in c.fetchall()]

        self._table.setModel(ProcurementTableModel(self._items))
        self._count_label.setText(f"共 {len(self._items)} 条代采购")

    # ═══════════════════════════════════
    #  添加
    # ═══════════════════════════════════

    def _on_add(self):
        """打开 ProcurementDialog 添加代采购"""
        dlg = ProcurementDialog(0, "", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data or not data.get("type_id"):
            QMessageBox.warning(self, "提示", "未选择物品")
            return
        conn = get_container().db.direct_connect("user")
        try:
            conn.execute(
                "INSERT INTO procurement_items (type_id, item_name, quantity, hub, priority, status, notes) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (data["type_id"], data["name"], data["quantity"], data["hub"], data["priority"], data["notes"]),
            )
            conn.commit()
        finally:
            conn.close()
        self.load_items()

    # ═══════════════════════════════════
    #  右键菜单
    # ═══════════════════════════════════

    def _on_context_menu(self, pos):
        sel = self._table.selectionModel().selectedRows()
        if not sel:
            return
        model = self._table.model()
        if not isinstance(model, ProcurementTableModel):
            return

        # 对单行操作取第一行
        item = model.get_item(sel[0].row())
        if not item:
            return

        menu = QMenu(self)
        menu.setObjectName("procurement_context")

        a_delete = menu.addAction("删除")
        a_mark_ordered = menu.addAction("标记为已下单")
        a_mark_received = menu.addAction("标记为已到货")
        menu.addSeparator()
        a_modify_qty = menu.addAction("修改数量")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == a_delete:
            self._on_delete_selected(sel, model)
        elif action == a_mark_ordered:
            self._on_set_status(model, sel, "ordered")
        elif action == a_mark_received:
            self._on_set_status(model, sel, "received")
        elif action == a_modify_qty:
            self._on_modify_qty(sel, model)

    def _on_delete_selected(self, sel, model):
        ids = [model.get_item(r.row())["id"] for r in sel]
        if (
            QMessageBox.question(
                self,
                "确认",
                f"删除 {len(ids)} 条代采购条目？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        with get_container().db.connect("user") as conn:
            conn.executemany("DELETE FROM procurement_items WHERE id = ?", [(i,) for i in ids])
        self.load_items()

    def _on_set_status(self, model, sel, status):
        ids = [model.get_item(r.row())["id"] for r in sel]
        with get_container().db.connect("user") as conn:
            conn.executemany(
                "UPDATE procurement_items SET status = ? WHERE id = ?",
                [(status, i) for i in ids],
            )
        self.load_items()

    def _on_modify_qty(self, sel, model):
        """弹出输入框修改数量"""
        item = model.get_item(sel[0].row())
        if not item:
            return

        qty, ok = QInputDialog.getInt(
            self,
            "修改数量",
            f"输入新数量 ({item.get('item_name', '')})",
            value=item.get("quantity", 1),
            min=1,
            max=999999,
        )
        if not ok:
            return
        with get_container().db.connect("user") as conn:
            conn.execute(
                "UPDATE procurement_items SET quantity = ? WHERE id = ?",
                (qty, item["id"]),
            )
        self.load_items()

    # ═══════════════════════════════════
    #  外部刷新
    # ═══════════════════════════════════

    def refresh(self):
        self.load_items()
