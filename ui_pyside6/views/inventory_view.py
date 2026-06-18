"""
仓库页面 — 多机库库存管理
"""

import os
import re

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.paths import icon_cache_dir
from services.database_manager import get_db as _get_db_view

_inv_db = _get_db_view()
from services.inventory_manager import (
    add_item,
    create_hangar,
    delete_hangar,
    get_hangars,
    get_item_price,
    get_items,
    init_db,
    move_items,
    remove_item,
    rename_hangar,
    update_quantity,
)
from services.scoring import TRADE_HUB_IDS
from ui_pyside6.theme import (
    BG_SURFACE,
    BORDER,
    PRIMARY,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
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

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

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
                return f"{r['cost_price']:,.2f}" if r["cost_price"] else "-"
            if c == 4:
                return f"{r['plan_usage']:,}" if r.get("plan_usage") else "0"
            if c == 5:
                return f"{r['plan_remain']:,}" if r.get("plan_remain") else f"{r['quantity']:,}"
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
                            return pix.scaled(
                                24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                            )
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
        with _inv_db.connect("ref") as conn:
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
                    with _inv_db.connect("mkt") as conn2:
                        c2 = conn2.cursor()
                        c2.execute(
                            "SELECT buy_price FROM market_prices WHERE type_id = ? AND region_id = 10000002 LIMIT 1",
                            (type_id,),
                        )
                        r = c2.fetchone()
                        price = r[0] or 0 if r else 0
                else:
                    price = 0

                results.append((type_id, qty, price))

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
#  Dialog: 剪贴板导入预览
# ════════════════════════════════════════════════════


class ImportReviewDialog(QDialog):
    """从剪贴板解析物品后展示确认表格，支持逐行设价/删除"""

    _HUB_NAMES = {"Jita": "吉他", "Amarr": "艾玛", "Dodixie": "多迪", "Rens": "伦斯"}
    _COL_CHECK = 0
    _COL_ICON = 1
    _COL_NAME = 2
    _COL_QTY = 3
    _COL_PRICE = 4
    _COL_ACTIONS = 5
    _HEADERS = ["", "图标", "名称", "数量", "成本价", "操作"]

    def __init__(self, items: list[dict], hangar_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"导入预览 → {hangar_name}")
        self.setMinimumSize(720, 420)
        self.resize(800, 500)
        self._parsed_items = items  # list of {type_id, zh_name, en_name, qty}
        self._region_id = TRADE_HUB_IDS["Jita"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 工具栏行：贸易中心 + 全选/取消全选 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("价格来源贸易中心:"))
        self._hub_combo = QComboBox()
        for hub_name in ["Jita", "Amarr", "Dodixie", "Rens"]:
            label = f"{hub_name} ({self._HUB_NAMES[hub_name]})"
            self._hub_combo.addItem(label, hub_name)
        self._hub_combo.currentIndexChanged.connect(self._on_hub_changed)
        toolbar.addWidget(self._hub_combo)

        toolbar.addStretch()

        self._select_all_btn = QPushButton("全选")
        self._select_all_btn.setFixedWidth(56)
        self._select_all_btn.clicked.connect(self._on_select_all)
        toolbar.addWidget(self._select_all_btn)

        self._deselect_all_btn = QPushButton("取消全选")
        self._deselect_all_btn.setFixedWidth(72)
        self._deselect_all_btn.clicked.connect(self._on_deselect_all)
        toolbar.addWidget(self._deselect_all_btn)

        layout.addLayout(toolbar)

        # ── 表格 ──
        self._table = QTableWidget(len(items), len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.verticalHeader().setVisible(False)
        self._table.setColumnWidth(self._COL_CHECK, 28)
        self._table.setColumnWidth(self._COL_ICON, 28)
        self._table.setColumnWidth(self._COL_NAME, 200)
        self._table.setColumnWidth(self._COL_QTY, 80)
        self._table.setColumnWidth(self._COL_PRICE, 160)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        # ── 统计栏 ──
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(self._summary_label)

        # ── 底部按钮 ──
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("确定导入")
        btn.accepted.connect(self._on_accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        # 填充表格行
        self._populate_rows()

    def _populate_rows(self):
        """填充表格每行：勾选、图标、名称、数量、价格控件、操作按钮"""
        table = self._table
        for row, item in enumerate(self._parsed_items):
            type_id = item["type_id"]
            name = item.get("zh_name") or item.get("en_name") or f"ID:{type_id}"
            qty = item["qty"]

            # 列0：勾选
            cb = QCheckBox()
            cb.setChecked(True)
            cb_w = QWidget()
            cb_l = QHBoxLayout(cb_w)
            cb_l.setContentsMargins(0, 0, 0, 0)
            cb_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_l.addWidget(cb)
            table.setCellWidget(row, self._COL_CHECK, cb_w)

            # 列1：图标
            icon_path = os.path.join(ICON_DIR, f"{type_id}.png")
            icon_label = QLabel()
            icon_label.setFixedSize(24, 24)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if os.path.exists(icon_path):
                pix = QPixmap(icon_path)
                if not pix.isNull():
                    icon_label.setPixmap(
                        pix.scaled(
                            24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                        )
                    )
            table.setCellWidget(row, self._COL_ICON, icon_label)

            # 列2：名称
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(Qt.ItemDataRole.UserRole, type_id)
            table.setItem(row, self._COL_NAME, name_item)

            # 列3：数量
            qty_item = QTableWidgetItem(f"{qty:,}")
            qty_item.setFlags(qty_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row, self._COL_QTY, qty_item)

            # 列4：成本价 (QDoubleSpinBox)
            price_w = QWidget()
            price_l = QHBoxLayout(price_w)
            price_l.setContentsMargins(2, 0, 2, 0)
            price_l.setSpacing(3)

            spin = QDoubleSpinBox()
            spin.setRange(0, 1e12)
            spin.setDecimals(2)
            spin.setSingleStep(1000)
            spin.setFixedWidth(100)
            spin.setValue(0)
            price_l.addWidget(spin)

            btn_sell = QPushButton("卖价")
            btn_sell.setFixedWidth(38)
            btn_sell.setToolTip("查询该物品在当前贸易中心的卖单价格")
            price_l.addWidget(btn_sell)

            btn_buy = QPushButton("买价")
            btn_buy.setFixedWidth(38)
            btn_buy.setToolTip("查询该物品在当前贸易中心的买入价格")
            price_l.addWidget(btn_buy)

            price_l.addStretch()
            table.setCellWidget(row, self._COL_PRICE, price_w)

            # 列5：操作（删除）
            actions_w = QWidget()
            actions_l = QHBoxLayout(actions_w)
            actions_l.setContentsMargins(2, 0, 2, 0)
            actions_l.setSpacing(3)

            del_btn = QPushButton("删除")
            del_btn.setFixedWidth(44)
            actions_l.addWidget(del_btn)
            actions_l.addStretch()
            table.setCellWidget(row, self._COL_ACTIONS, actions_w)

            # 连接信号 — 注意：不捕获 row 索引，用控件引用查找当前行
            btn_sell.clicked.connect(lambda checked, t=type_id, s=spin: self._set_price_from_market(t, "sell", s))
            btn_buy.clicked.connect(lambda checked, t=type_id, s=spin: self._set_price_from_market(t, "buy", s))
            del_btn.clicked.connect(lambda checked, w=actions_w: self._remove_row_by_widget(w))
            cb.toggled.connect(lambda: self._update_summary())

        self._update_summary()

    def _on_hub_changed(self, idx: int):
        hub_name = self._hub_combo.itemData(idx)
        self._region_id = TRADE_HUB_IDS.get(hub_name, TRADE_HUB_IDS["Jita"])

    def _on_select_all(self):
        for row in range(self._table.rowCount()):
            w = self._table.cellWidget(row, self._COL_CHECK)
            if w:
                cb = w.findChild(QCheckBox)
                if cb:
                    cb.setChecked(True)

    def _on_deselect_all(self):
        for row in range(self._table.rowCount()):
            w = self._table.cellWidget(row, self._COL_CHECK)
            if w:
                cb = w.findChild(QCheckBox)
                if cb:
                    cb.setChecked(False)

    def _set_price_from_market(self, type_id: int, price_type: str, spin: QDoubleSpinBox):
        """查询市场价格并填入指定行的价格控件"""
        col = "sell_price" if price_type == "sell" else "buy_price"
        with _inv_db.connect("mkt") as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT {col} FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                (type_id, self._region_id),
            )
            row = cursor.fetchone()
            if row and row[0] is not None:
                spin.setValue(row[0])
            else:
                QMessageBox.information(self, "提示", "未找到该物品在所选区域的价格数据")

    def _remove_row_by_widget(self, actions_widget: QWidget):
        """根据操作栏控件引用查找所在行并删除（避免 stale lambda 问题）"""
        for row in range(self._table.rowCount()):
            if self._table.cellWidget(row, self._COL_ACTIONS) == actions_widget:
                self._table.removeRow(row)
                if row < len(self._parsed_items):
                    del self._parsed_items[row]
                self._update_summary()
                return

    def _update_summary(self):
        """更新底部统计信息"""
        checked = 0
        total_value = 0.0
        for row in range(self._table.rowCount()):
            w = self._table.cellWidget(row, self._COL_CHECK)
            if w:
                cb = w.findChild(QCheckBox)
                if cb and cb.isChecked():
                    checked += 1
                    price_w = self._table.cellWidget(row, self._COL_PRICE)
                    if price_w:
                        spin = price_w.findChild(QDoubleSpinBox)
                        if spin:
                            # 获取数量
                            qty_item = self._table.item(row, self._COL_QTY)
                            qty = 0
                            if qty_item:
                                try:
                                    qty = int(qty_item.text().replace(",", ""))
                                except ValueError:
                                    pass
                            total_value += spin.value() * qty
        total_items = self._table.rowCount()
        self._summary_label.setText(
            f"已勾选 {checked} 项 / 总计 {total_items} 项 / 预估进货成本 {total_value:,.0f} ISK"
        )

    def _on_accept(self):
        """确定导入前检查"""
        has_checked = False
        for row in range(self._table.rowCount()):
            w = self._table.cellWidget(row, self._COL_CHECK)
            if w:
                cb = w.findChild(QCheckBox)
                if cb and cb.isChecked():
                    has_checked = True
                    break
        if not has_checked:
            QMessageBox.warning(self, "提示", "没有勾选的物品，无法导入")
            return
        self.accept()

    def get_import_data(self) -> list[tuple[int, int, float]]:
        """获取最终导入数据 list[(type_id, qty, cost_price)]"""
        result = []
        for row in range(self._table.rowCount()):
            w = self._table.cellWidget(row, self._COL_CHECK)
            if not w:
                continue
            cb = w.findChild(QCheckBox)
            if not cb or not cb.isChecked():
                continue

            name_item = self._table.item(row, self._COL_NAME)
            type_id = name_item.data(Qt.ItemDataRole.UserRole) if name_item else None
            if not type_id:
                continue

            qty_item = self._table.item(row, self._COL_QTY)
            try:
                qty = int(qty_item.text().replace(",", "")) if qty_item else 0
            except ValueError:
                continue

            spin = self._table.cellWidget(row, self._COL_PRICE).findChild(QDoubleSpinBox)
            price = spin.value() if spin else 0.0

            result.append((type_id, qty, price))
        return result


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
        if (
            QMessageBox.question(
                self,
                "确认",
                f"删除机库「{name}」及其所有物品？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        delete_hangar(self._current_hangar_id)
        self._load_hangars()

    # ── 剪贴板导入 ──

    def _parse_clipboard(self, raw: str) -> list[dict]:
        """解析 EVE 仓库复制格式 → list[{type_id, zh_name, en_name, qty}]"""
        lines = raw.strip().split("\n")
        results = []
        errors = []
        with _inv_db.connect("ref") as conn:
            c = conn.cursor()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # EVE 仓库格式: 物品名\t数量\t...（全部列分割）
                cols = line.split("\t")
                if len(cols) < 2:
                    errors.append(f"格式错误: {line}")
                    continue
                name_part = cols[0].strip()
                qty_str = cols[1].strip()
                try:
                    qty = int(qty_str.replace(",", ""))
                except ValueError:
                    errors.append(f"数量无效: {qty_str}")
                    continue

                # 去掉尾部星号（EVE 中 meta 等级标记等）
                name_clean = name_part.rstrip("*")
                if not name_clean:
                    continue

                type_id = None
                c.execute("SELECT type_id FROM item WHERE zh_name = ? LIMIT 1", (name_clean,))
                r = c.fetchone()
                if r:
                    type_id = r[0]
                else:
                    c.execute("SELECT type_id FROM item WHERE en_name = ? LIMIT 1", (name_clean,))
                    r = c.fetchone()
                    if r:
                        type_id = r[0]
                if not type_id:
                    errors.append(f"未找到物品: {name_part}")
                    continue

                # 查询名称
                c.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (type_id,))
                nrow = c.fetchone()
                results.append(
                    {
                        "type_id": type_id,
                        "qty": qty,
                        "zh_name": nrow[0] if nrow else name_clean,
                        "en_name": nrow[1] if nrow else "",
                    }
                )
        if errors:
            # 最多显示 3 个错误
            err_msg = "\n".join(errors[:3])
            if len(errors) > 3:
                err_msg += f"\n...还有 {len(errors) - 3} 个错误"
            QMessageBox.warning(self, "解析警告", err_msg)
        return results

    def _on_paste_import(self):
        if not self._current_hangar_id:
            return
        # 自动读取剪贴板
        raw = QApplication.clipboard().text().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "剪贴板为空，请先在游戏中复制物品（Ctrl+C）")
            return
        parsed = self._parse_clipboard(raw)
        if not parsed:
            return
        hangar_name = self._hangar_combo.currentText()
        dlg = ImportReviewDialog(parsed, hangar_name, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_import_data()
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
                act.triggered.connect(
                    lambda checked, hid=h["id"], iid=item["id"]: move_items([iid], hid) or self._refresh()
                )
                move_menu.addAction(act)

        menu.addSeparator()
        copy_name = QAction("复制名称", self)
        copy_name.triggered.connect(
            lambda: (
                QApplication.instance()
                .clipboard()
                .setText(item.get("zh_name") or item.get("en_name") or str(item["type_id"]))
            )
        )
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
        if (
            QMessageBox.question(
                self, "确认", f"删除 {name}？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            == QMessageBox.StandardButton.Yes
        ):
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
        total = sum((it["quantity"] * (it.get("sell_price") or 0)) for it in items if it.get("sell_price"))
        self._total_label.setText(f"按卖单价格: {total:,.0f} ISK")

    def refresh_display(self):
        self._refresh()
