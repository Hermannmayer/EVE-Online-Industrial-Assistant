"""
仓库页面 — 多机库库存管理
"""
import os
import re
import sqlite3

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QTableView, QHeaderView,
    QAbstractItemView, QMenu, QMessageBox, QDialog, QFormLayout,
    QDialogButtonBox, QInputDialog, QApplication,
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, QThread
from PySide6.QtGui import QAction, QColor, QPixmap

from core.paths import DB_PATH, icon_cache_dir
from ui_pyside6.theme import (
    BG_DARK, BG_SURFACE, PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY, GREEN, RED, BORDER,
)
from services.inventory_manager import (
    init_db, get_hangars, get_items, get_item_price, add_item,
    remove_item, update_quantity, move_items,
    create_hangar, rename_hangar, delete_hangar,
)

ICON_DIR = icon_cache_dir()


# ════════════════════════════════════════════════════
#  Table Model
# ════════════════════════════════════════════════════

class InvTableModel(QAbstractTableModel):
    _HEADERS = ["图标", "名称", "库存数量", "单个成本记录", "规划占用", "规划剩余", "按卖单总价值"]

    def __init__(self, items: list[dict]):
        super().__init__()
        self._items = items

    def rowCount(self, parent=QModelIndex()): return len(self._items)
    def columnCount(self, parent=QModelIndex()): return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self._items[index.row()]
        c = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return ""
            if c == 1:
                return r.get("zh_name") or r.get("en_name") or f"ID:{r['type_id']}"
            if c == 2:
                return f"{r['quantity']:,}"
            if c == 3:
                return f"{r['cost_price']:,.2f}" if r['cost_price'] else "-"
            if c == 4:
                return f"{r['plan_usage']:,}" if r.get('plan_usage') else "0"
            if c == 5:
                return f"{r['plan_remain']:,}" if r.get('plan_remain') else f"{r['quantity']:,}"
            if c == 6:
                sp = r.get("sell_price")
                return f"{r['quantity'] * sp:,.0f}" if sp else "-"

        elif role == Qt.ItemDataRole.DecorationRole:
            if c == 0:
                type_id = r.get("type_id")
                if type_id:
                    icon_path = os.path.join(ICON_DIR, f"{type_id}.png")
                    if os.path.exists(icon_path):
                        pix = QPixmap(icon_path)
                        if not pix.isNull():
                            return pix.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            return None

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if c >= 2:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def item_at(self, row: int) -> dict | None:
        return self._items[row] if 0 <= row < len(self._items) else None


# ════════════════════════════════════════════════════
#  Dialog: 粘贴导入
# ════════════════════════════════════════════════════

class PasteImportDialog(QDialog):
    def __init__(self, hangar_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"粘贴导入 → {hangar_name}")
        self.setMinimumSize(460, 350)
        self._result: list[tuple[int, int, float]] = []

        layout = QVBoxLayout(self)

        hint = QLabel(
            "支持格式（每行一条，Tab 或空格分隔）：\n"
            "1. type_id[TAB]数量\n"
            "2. 物品名[TAB]数量\n"
            "从游戏中复制（Ctrl+C）后粘贴到下面："
        )
        hint.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._text = QLineEdit()
        self._text.setPlaceholderText("在此粘贴...")
        self._text.setMinimumHeight(60)
        layout.addWidget(self._text)

        # 价格来源选择
        layout.addWidget(QLabel("成本价来源:"))
        price_row = QHBoxLayout()
        self._price_use_sell = QPushButton("卖价")
        self._price_use_sell.setCheckable(True)
        self._price_use_sell.setChecked(True)
        price_row.addWidget(self._price_use_sell)
        self._price_use_buy = QPushButton("买价")
        self._price_use_buy.setCheckable(True)
        price_row.addWidget(self._price_use_buy)
        self._price_use_zero = QPushButton("无记录")
        self._price_use_zero.setCheckable(True)
        price_row.addWidget(self._price_use_zero)
        layout.addLayout(price_row)

        # 互斥
        for btn in (self._price_use_sell, self._price_use_buy, self._price_use_zero):
            btn.toggled.connect(lambda checked, b=btn: self._on_price_toggle(b) if checked else None)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self._parse)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

    def _on_price_toggle(self, clicked):
        for btn in (self._price_use_sell, self._price_use_buy, self._price_use_zero):
            if btn != clicked:
                btn.setChecked(False)

    def _get_price_source(self) -> str:
        if self._price_use_sell.isChecked():
            return "sell"
        elif self._price_use_buy.isChecked():
            return "buy"
        return "none"

    def _parse(self):
        raw = self._text.text().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "粘贴内容为空")
            return

        lines = raw.split("\n")
        results = []
        errors = []
        price_source = self._get_price_source()
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                parts = re.split(r"[\t,;|]\s*", line, maxsplit=1)
                if len(parts) < 2:
                    errors.append(f"格式错误: {line}")
                    continue
                key, qty_str = parts[0].strip(), parts[1].strip()
                try:
                    qty = int(qty_str.replace(",", ""))
                except ValueError:
                    errors.append(f"数量无效: {qty_str}")
                    continue

                type_id = None
                if key.isdigit():
                    type_id = int(key)
                else:
                    c.execute("SELECT type_id FROM item WHERE zh_name = ? OR en_name = ? LIMIT 1", (key, key))
                    r = c.fetchone()
                    if r:
                        type_id = r[0]
                if not type_id:
                    errors.append(f"未找到物品: {key}")
                    continue

                if price_source == "sell":
                    price = get_item_price(type_id) or 0
                elif price_source == "buy":
                    conn2 = sqlite3.connect(DB_PATH)
                    try:
                        c2 = conn2.cursor()
                        c2.execute("SELECT buy_price FROM market_prices WHERE type_id = ? AND region_id = 10000002 LIMIT 1", (type_id,))
                        r = c2.fetchone()
                        price = r[0] or 0 if r else 0
                    finally:
                        conn2.close()
                else:
                    price = 0

                results.append((type_id, qty, price))
        finally:
            conn.close()

        if not results:
            QMessageBox.warning(self, "导入结果", f"未能解析任何有效数据\n{chr(10).join(errors[:5])}")
            return

        self._result = results
        msg = f"成功解析 {len(results)} 条"
        if errors:
            msg += f"\n{len(errors)} 条错误（显示前3）:\n" + "\n".join(errors[:3])
        QMessageBox.information(self, "导入结果", msg)
        self.accept()

    def result_data(self) -> list:
        return self._result


# ════════════════════════════════════════════════════
#  Dialog: 编辑数量
# ════════════════════════════════════════════════════

class EditQtyDialog(QDialog):
    def __init__(self, item_name: str, current_qty: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"编辑数量 — {item_name}")
        layout = QFormLayout(self)
        self._qty = QLineEdit(str(current_qty))
        layout.addRow("数量:", self._qty)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self.accept)
        btn.rejected.connect(self.reject)
        layout.addRow(btn)

    def quantity(self) -> int:
        try:
            return int(self._qty.text())
        except ValueError:
            return -1


# ════════════════════════════════════════════════════
#  Main Page
# ════════════════════════════════════════════════════

class InventoryPage(QWidget):
    """仓库管理"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        init_db()
        self.setObjectName("inventory_page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._build_hangar_bar(layout)
        self._build_action_bar(layout)

        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSortingEnabled(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self._table, 1)

        self._current_hangar_id: int | None = None
        self._model: InvTableModel | None = None
        self._load_hangars()

    def _build_hangar_bar(self, layout):
        bar = QHBoxLayout()
        bar.setSpacing(6)

        lbl = QLabel("机库:")
        lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold;")
        bar.addWidget(lbl)

        self._hangar_combo = QComboBox()
        self._hangar_combo.setMinimumWidth(140)
        self._hangar_combo.currentIndexChanged.connect(self._on_hangar_changed)
        bar.addWidget(self._hangar_combo)

        self._new_h_btn = QPushButton("+新建")
        self._new_h_btn.setFixedWidth(54)
        self._new_h_btn.clicked.connect(self._on_new_hangar)
        bar.addWidget(self._new_h_btn)

        self._rename_h_btn = QPushButton("重命名")
        self._rename_h_btn.setFixedWidth(54)
        self._rename_h_btn.clicked.connect(self._on_rename_hangar)
        bar.addWidget(self._rename_h_btn)

        self._del_h_btn = QPushButton("删除")
        self._del_h_btn.setFixedWidth(44)
        self._del_h_btn.clicked.connect(self._on_del_hangar)
        bar.addWidget(self._del_h_btn)

        bar.addStretch()

        # 右上角：按卖单总价
        self._total_label = QLabel("按卖单价格: -- ISK")
        self._total_label.setStyleSheet(f"font-weight: bold; color: {PRIMARY}; font-size: 13px;")
        bar.addWidget(self._total_label)

        layout.addLayout(bar)

    def _build_action_bar(self, layout):
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self._paste_btn = QPushButton("粘贴导入")
        self._paste_btn.clicked.connect(self._on_paste_import)
        bar.addWidget(self._paste_btn)

        self._move_btn = QPushButton("移动到")
        self._move_btn.clicked.connect(self._on_move_items)
        bar.addWidget(self._move_btn)

        bar.addStretch()

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        bar.addWidget(self._count_label)

        layout.addLayout(bar)

    # ── 机库操作 ──

    def _load_hangars(self):
        hangars = get_hangars()
        self._hangar_combo.blockSignals(True)
        self._hangar_combo.clear()
        for h in hangars:
            self._hangar_combo.addItem(h["name"], h["id"])
        self._hangar_combo.blockSignals(False)
        if hangars:
            self._hangar_combo.setCurrentIndex(0)
            self._on_hangar_changed(0)

    def _on_hangar_changed(self, idx: int):
        if idx < 0:
            return
        self._current_hangar_id = self._hangar_combo.itemData(idx)
        self._refresh()

    def _on_new_hangar(self):
        name, ok = QInputDialog.getText(self, "新建机库", "机库名:")
        if ok and name.strip():
            rid = create_hangar(name.strip())
            if rid == -1:
                QMessageBox.warning(self, "提示", "机库名已存在")
            else:
                self._load_hangars()
                for i in range(self._hangar_combo.count()):
                    if self._hangar_combo.itemData(i) == rid:
                        self._hangar_combo.setCurrentIndex(i)
                        break

    def _on_rename_hangar(self):
        if not self._current_hangar_id:
            return
        old = self._hangar_combo.currentText()
        name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=old)
        if ok and name.strip() and name != old:
            rename_hangar(self._current_hangar_id, name.strip())
            self._load_hangars()

    def _on_del_hangar(self):
        if not self._current_hangar_id:
            return
        name = self._hangar_combo.currentText()
        if QMessageBox.question(self, "确认", f"删除机库「{name}」及其所有物品？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        delete_hangar(self._current_hangar_id)
        self._load_hangars()

    # ── 粘贴导入 ──

    def _on_paste_import(self):
        if not self._current_hangar_id:
            return
        hangar_name = self._hangar_combo.currentText()
        dlg = PasteImportDialog(hangar_name, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data:
            return
        added = 0
        for type_id, qty, price in data:
            rid = add_item(self._current_hangar_id, type_id, qty, price)
            if rid != -1:
                added += 1
        self._refresh()
        QMessageBox.information(self, "完成", f"成功导入 {added}/{len(data)} 条")

    # ── 移动 ──

    def _on_move_items(self):
        if not self._current_hangar_id or not self._model:
            return
        sel = self._table.selectionModel().selectedRows()
        if not sel:
            QMessageBox.information(self, "提示", "请先选中要移动的物品")
            return
        ids = [self._model.item_at(r.row())["id"] for r in sel]
        hangars = get_hangars()
        targets = [h for h in hangars if h["id"] != self._current_hangar_id]
        if not targets:
            QMessageBox.information(self, "提示", "没有其他机库可移动")
            return
        names = [h["name"] for h in targets]
        name, ok = QInputDialog.getItem(self, "移动到", "目标机库:", names, 0, False)
        if ok and name:
            target_id = next(h["id"] for h in targets if h["name"] == name)
            move_items(ids, target_id)
            self._refresh()

    # ── 右键菜单 ──

    def _on_context_menu(self, pos):
        idx = self._table.currentIndex()
        if not idx.isValid() or not self._model:
            return
        item = self._model.item_at(idx.row())
        if not item:
            return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {BG_SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
            QMenu::item {{ padding: 6px 20px; }}
            QMenu::item:selected {{ background: {PRIMARY}; color: #fff; }}
        """)

        edit_act = QAction("编辑数量", self)
        edit_act.triggered.connect(lambda: self._on_edit_qty(item))
        menu.addAction(edit_act)

        del_act = QAction("删除", self)
        del_act.triggered.connect(lambda: self._on_del_item(item))
        menu.addAction(del_act)

        move_menu = menu.addMenu("移动到")
        for h in get_hangars():
            if h["id"] != self._current_hangar_id:
                act = QAction(h["name"], self)
                act.triggered.connect(lambda checked, hid=h["id"], iid=item["id"]: move_items([iid], hid) or self._refresh())
                move_menu.addAction(act)

        menu.addSeparator()
        copy_name = QAction("复制名称", self)
        copy_name.triggered.connect(lambda: QApplication.instance().clipboard().setText(
            item.get("zh_name") or item.get("en_name") or str(item["type_id"])))
        menu.addAction(copy_name)

        copy_id = QAction("复制 type_id", self)
        copy_id.triggered.connect(lambda: QApplication.instance().clipboard().setText(str(item["type_id"])))
        menu.addAction(copy_id)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _on_edit_qty(self, item: dict):
        dlg = EditQtyDialog(item.get("zh_name") or item.get("en_name") or str(item["type_id"]), item["quantity"], self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            qty = dlg.quantity()
            if qty >= 0:
                update_quantity(item["id"], qty)
                self._refresh()

    def _on_del_item(self, item: dict):
        name = item.get("zh_name") or item.get("en_name") or str(item["type_id"])
        if QMessageBox.question(self, "确认", f"删除 {name}？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            remove_item(item["id"])
            self._refresh()

    # ── 刷新 ──

    def _refresh(self):
        if not self._current_hangar_id:
            return
        items = get_items(self._current_hangar_id)
        self._model = InvTableModel(items)
        self._table.setModel(self._model)
        self._table.setColumnWidth(0, 28)
        self._table.setColumnWidth(1, 160)
        self._table.setColumnWidth(2, 80)
        self._table.setColumnWidth(3, 100)
        self._table.setColumnWidth(4, 70)
        self._table.setColumnWidth(5, 70)
        self._table.setColumnWidth(6, 100)
        self._count_label.setText(f"共 {len(items)} 项")

        # 计算总价
        total = sum(
            (it["quantity"] * (it.get("sell_price") or 0))
            for it in items if it.get("sell_price")
        )
        self._total_label.setText(f"按卖单价格: {total:,.0f} ISK")

    def refresh_display(self):
        self._refresh()
