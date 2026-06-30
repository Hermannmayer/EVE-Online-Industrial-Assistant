"""
仓库页面 — 多机库库存管理
"""

import os
import re

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QPixmap
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
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from core.paths import icon_cache_dir
from services.inventory_manager import (
    add_item,
    create_hangar,
    delete_blueprints_batch,
    delete_hangar,
    get_blueprint_materials_batch,
    get_blueprint_product_info_batch,
    get_blueprint_reaction_ids,
    get_blueprint_tech_levels,
    get_blueprints,
    get_hangars,
    get_item_price,
    get_items,
    init_db,
    move_blueprints_to_hangar,
    move_items,
    remove_item,
    rename_hangar,
    update_blueprints_batch,
    update_quantity,
)
from services.scoring import TRADE_HUB_IDS, resolve_item_name

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
        self.setMinimumSize(500, 380)
        self._result: list[tuple[int, int, float]] = []

        layout = QVBoxLayout(self)

        self._hint = QLabel(
            "支持格式（每行一条，Tab 分隔）：\n"
            "1. 物品名[TAB]数量\n"
            "2. EVE列表视图格式（自动识别）\n"
            "从游戏中复制（Ctrl+C）后粘贴到下面："
        )
        self._hint.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._text = QLineEdit()
        self._text.setPlaceholderText("在此粘贴...")
        self._text.setMinimumHeight(60)
        layout.addWidget(self._text)

        # 价格来源选择
        layout.addWidget(QLabel("成本价来源:"))
        price_row = QHBoxLayout()
        price_row.setSpacing(4)

        self._price_use_sell = QPushButton("卖价")
        self._price_use_sell.setCheckable(True)
        self._price_use_sell.setChecked(True)
        price_row.addWidget(self._price_use_sell)

        self._price_use_buy = QPushButton("买价")
        self._price_use_buy.setCheckable(True)
        price_row.addWidget(self._price_use_buy)

        self._price_use_avg = QPushButton("均价")
        self._price_use_avg.setCheckable(True)
        self._price_use_avg.setToolTip("卖价和买价的平均值")
        price_row.addWidget(self._price_use_avg)

        self._price_use_disc = QPushButton("折后价")
        self._price_use_disc.setCheckable(True)
        self._price_use_disc.setToolTip("对卖价应用折扣率")
        price_row.addWidget(self._price_use_disc)

        self._discount_spin = QDoubleSpinBox()
        self._discount_spin.setRange(0.01, 1.0)
        self._discount_spin.setDecimals(2)
        self._discount_spin.setSingleStep(0.05)
        self._discount_spin.setValue(0.9)
        self._discount_spin.setPrefix("× ")
        self._discount_spin.setFixedWidth(72)
        self._discount_spin.setToolTip("折扣率：0.9=9折, 0.85=85折")
        price_row.addWidget(self._discount_spin)

        price_row.addStretch()
        layout.addLayout(price_row)

        # 互斥
        for btn in (self._price_use_sell, self._price_use_buy, self._price_use_avg, self._price_use_disc):
            btn.toggled.connect(lambda checked, b=btn: self._on_price_toggle(b) if checked else None)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self._parse)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

    def _on_price_toggle(self, clicked):
        for btn in (self._price_use_sell, self._price_use_buy, self._price_use_avg, self._price_use_disc):
            if btn != clicked:
                btn.setChecked(False)

    def _get_price_source(self) -> str:
        if self._price_use_sell.isChecked():
            return "sell"
        elif self._price_use_buy.isChecked():
            return "buy"
        elif self._price_use_avg.isChecked():
            return "avg"
        elif self._price_use_disc.isChecked():
            return "disc"
        return "sell"

    def _get_discount(self) -> float:
        return self._discount_spin.value()

    def _parse(self):
        raw = self._text.text().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "粘贴内容为空")
            return

        lines = raw.split("\n")
        results = []
        errors = []
        price_source = self._get_price_source()
        discount = self._get_discount()
        with get_container().db.connect("ref", "bp") as conn:
            c = conn.cursor()
            with get_container().db.connect("mkt") as conn2:
                c2 = conn2.cursor()
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

                    if price_source in ("sell", "disc"):
                        price = get_item_price(type_id) or 0
                        if price_source == "disc":
                            price *= discount
                    elif price_source == "buy":
                        c2.execute(
                            "SELECT buy_price FROM market_prices WHERE type_id = ? AND region_id = 10000002 LIMIT 1",
                            (type_id,),
                        )
                        r = c2.fetchone()
                        price = r[0] or 0 if r else 0
                    elif price_source == "avg":
                        c2.execute(
                            "SELECT sell_price, buy_price FROM market_prices WHERE type_id = ? AND region_id = 10000002 LIMIT 1",
                            (type_id,),
                        )
                        r = c2.fetchone()
                        if r and r[0] and r[1]:
                            price = (r[0] + r[1]) / 2
                        elif r:
                            price = r[0] or r[1] or 0
                        else:
                            price = 0
                    else:
                        price = 0

                    results.append((type_id, qty, round(price, 2)))

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

    def showEvent(self, event):
        """显示前重新应用主题样式"""
        super().showEvent(event)
        self._reapply_styles()

    def _reapply_styles(self):
        self._hint.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")


# ════════════════════════════════════════════════════
#  Dialog: 剪贴板导入预览
# ════════════════════════════════════════════════════


class ImportReviewDialog(QDialog):
    """粘贴导入预览 — 右键菜单设价/删除/跨机库"""

    _HUB_NAMES = {"Jita": "吉他", "Amarr": "艾玛", "Dodixie": "多迪", "Rens": "伦斯"}
    _COL_CHECK = 0
    _COL_ICON = 1
    _COL_NAME = 2
    _COL_CURRENT = 3   # 数量（机库现有）
    _COL_DELTA = 4      # 比原纪录（本次增减）
    _COL_FINAL = 5      # 变化（最终数量）
    _COL_PRICE = 6      # 成本价
    _HEADERS = ["", "图标", "名称", "数量", "比原纪录", "变化", "成本价"]

    def __init__(self, items: list[dict], hangar_name: str, target_hangar_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"导入预览 → {hangar_name}")
        self.setMinimumSize(780, 420)
        self.resize(900, 520)
        self._parsed_items = items  # list of {type_id, zh_name, en_name, qty}
        self._target_hangar_id = target_hangar_id
        self._region_id = TRADE_HUB_IDS["Jita"]
        self._sell_prices: dict[int, float] = {}       # type_id → sell_price
        self._existing_qty: dict[int, int] = {}         # type_id → existing qty  in target
        self._source_hangar: dict[int, int] = {}        # type_id → source hangar id (for cross-hangar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 工具栏：贸易中心 + 全选/取消全选 + 折扣率 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("贸易中心:"))
        self._hub_combo = QComboBox()
        for hub_name in ["Jita", "Amarr", "Dodixie", "Rens"]:
            label = f"{hub_name} ({self._HUB_NAMES[hub_name]})"
            self._hub_combo.addItem(label, hub_name)
        self._hub_combo.currentIndexChanged.connect(self._on_hub_changed)
        toolbar.addWidget(self._hub_combo)

        toolbar.addStretch()

        self._select_all_btn = QPushButton("全选")
        self._select_all_btn.clicked.connect(self._on_select_all)
        toolbar.addWidget(self._select_all_btn)

        self._deselect_all_btn = QPushButton("取消全选")
        self._deselect_all_btn.clicked.connect(self._on_deselect_all)
        toolbar.addWidget(self._deselect_all_btn)

        toolbar.addStretch()

        toolbar.addWidget(QLabel("折扣率:"))
        self._discount_spin = QDoubleSpinBox()
        self._discount_spin.setRange(0.01, 1.0)
        self._discount_spin.setDecimals(2)
        self._discount_spin.setSingleStep(0.05)
        self._discount_spin.setValue(0.9)
        self._discount_spin.setSuffix(" 折")
        self._discount_spin.setFixedWidth(80)
        self._discount_spin.setToolTip("右键菜单中折后价使用的折扣率")
        toolbar.addWidget(self._discount_spin)

        layout.addLayout(toolbar)

        # ── 表格 ──
        self._table = QTableWidget(len(items), len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.verticalHeader().setDefaultSectionSize(32)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._table, 1)

        # ── 统计栏 ──
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(self._summary_label)

        # ── 底部按钮 ──
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("确定导入")
        btn.accepted.connect(self._on_accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        # 预加载数据
        self._fetch_existing_inventory()
        self._fetch_sell_prices()
        self._populate_rows()

    def _fetch_existing_inventory(self):
        """查询目标机库中已有物品的库存量"""
        try:
            existing = get_items(self._target_hangar_id)
            for it in existing:
                self._existing_qty[it["type_id"]] = it["quantity"]
        except Exception:
            pass

    def _fetch_sell_prices(self):
        """预加载所有物品在当前贸易中心的卖单价"""
        type_ids = list({it["type_id"] for it in self._parsed_items})
        if not type_ids:
            return
        with get_container().db.connect("mkt") as conn:
            c = conn.cursor()
            placeholders = ",".join("?" * len(type_ids))
            c.execute(
                f"SELECT type_id, sell_price FROM market_prices WHERE type_id IN ({placeholders}) AND region_id = ?",
                (*type_ids, self._region_id),
            )
            for tid, price in c.fetchall():
                if price:
                    self._sell_prices[tid] = price

    def _populate_rows(self):
        table = self._table
        for row, item in enumerate(self._parsed_items):
            type_id = item["type_id"]
            name = item.get("zh_name") or item.get("en_name") or f"ID:{type_id}"
            delta = item["qty"]                                 # 比原纪录 = 本次增减量
            current = self._existing_qty.get(type_id, 0)         # 数量 = 机库现有
            final = current + delta                               # 变化 = 最终数量

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
                    icon_label.setPixmap(pix.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            table.setCellWidget(row, self._COL_ICON, icon_label)

            # 列2：名称
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(Qt.ItemDataRole.UserRole, type_id)
            table.setItem(row, self._COL_NAME, name_item)

            # 列3：数量（机库现有）
            cur_item = QTableWidgetItem(f"{current:,}")
            cur_item.setFlags(cur_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            cur_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row, self._COL_CURRENT, cur_item)

            # 列4：比原纪录（本次增减）
            delta_item = QTableWidgetItem(f"+{delta:,}" if delta >= 0 else f"{delta:,}")
            delta_item.setFlags(delta_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            delta_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if delta > 0:
                delta_item.setForeground(QColor(theme.ACCENT_GREEN))
            table.setItem(row, self._COL_DELTA, delta_item)

            # 列5：变化（最终数量）
            final_item = QTableWidgetItem(f"{final:,}")
            final_item.setFlags(final_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            final_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row, self._COL_FINAL, final_item)

            # 列6：成本价
            spin = QDoubleSpinBox()
            spin.setRange(0, 1e12)
            spin.setDecimals(2)
            spin.setSingleStep(1000)
            spin.setValue(self._sell_prices.get(type_id, 0))
            table.setCellWidget(row, self._COL_PRICE, spin)

            cb.toggled.connect(lambda: self._update_summary())

        # 自适应列宽
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setColumnWidth(self._COL_CHECK, 28)
        table.setColumnWidth(self._COL_ICON, 28)
        for col, min_w in [(self._COL_NAME, 140), (self._COL_DELTA, 90), (self._COL_FINAL, 90), (self._COL_PRICE, 90)]:
            if table.columnWidth(col) < min_w:
                table.setColumnWidth(col, min_w)

        self._update_summary()

    def _on_hub_changed(self, idx: int):
        hub_name = self._hub_combo.itemData(idx)
        self._region_id = TRADE_HUB_IDS.get(hub_name, TRADE_HUB_IDS["Jita"])
        self._sell_prices.clear()
        self._fetch_sell_prices()
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, self._COL_NAME)
            if name_item:
                type_id = name_item.data(Qt.ItemDataRole.UserRole)
                spin = self._table.cellWidget(row, self._COL_PRICE)
                if spin and type_id:
                    spin.setValue(self._sell_prices.get(type_id, 0))
        self._update_summary()

    def _on_select_all(self):
        self._set_all_checked(True)

    def _on_deselect_all(self):
        self._set_all_checked(False)

    def _set_all_checked(self, checked: bool):
        for row in range(self._table.rowCount()):
            w = self._table.cellWidget(row, self._COL_CHECK)
            if w:
                cb = w.findChild(QCheckBox)
                if cb:
                    cb.setChecked(checked)

    def _selected_rows(self) -> list[int]:
        """返回所有选中行的行号列表"""
        return sorted({idx.row() for idx in self._table.selectionModel().selectedRows()})

    def _on_context_menu(self, pos):
        rows = self._selected_rows()
        idx = self._table.indexAt(pos)
        if idx.isValid() and idx.row() not in rows:
            rows = [idx.row()]  # 右键到未选中行时只操作该行
        if not rows:
            return

        menu = QMenu(self)

        set_sell = menu.addAction("设置为卖单价")
        set_buy = menu.addAction("设置为买单价")
        set_avg = menu.addAction("设置为均价")
        menu.addSeparator()
        del_action = menu.addAction(f"删除选中行 ({len(rows)})" if len(rows) > 1 else "删除该行")
        menu.addSeparator()
        disc_rate = self._discount_spin.value()
        disc_sell = menu.addAction(f"卖价 × {disc_rate:.0%}")
        disc_buy = menu.addAction(f"买价 × {disc_rate:.0%}")
        menu.addSeparator()

        # 来自其他机库
        other_hangars = [h for h in get_hangars() if h["id"] != self._target_hangar_id]
        if other_hangars:
            from_hangar_menu = menu.addMenu("来自其他机库")
            for h in other_hangars:
                ha = from_hangar_menu.addAction(h["name"])
                ha.setData(h["id"])

        menu.addSeparator()
        filter_nochange = menu.addAction("过滤无变化项")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))

        if action == set_sell:
            for r in rows:
                self._batch_set_price(r, "sell")
        elif action == set_buy:
            for r in rows:
                self._batch_set_price(r, "buy")
        elif action == set_avg:
            for r in rows:
                self._batch_set_price(r, "avg")
        elif action == del_action:
            for r in reversed(rows):
                self._table.removeRow(r)
                if r < len(self._parsed_items):
                    del self._parsed_items[r]
            self._update_summary()
        elif action == disc_sell:
            for r in rows:
                self._batch_set_price(r, "sell")
                spin = self._table.cellWidget(r, self._COL_PRICE)
                if spin:
                    spin.setValue(round(spin.value() * disc_rate, 2))
        elif action == disc_buy:
            for r in rows:
                self._batch_set_price(r, "buy")
                spin = self._table.cellWidget(r, self._COL_PRICE)
                if spin:
                    spin.setValue(round(spin.value() * disc_rate, 2))
        elif action == filter_nochange:
            self._filter_no_change()
        elif isinstance(action, QAction) and action.data():
            self._add_from_hangar(action.data())

    def _batch_set_price(self, row: int, price_type: str):
        """对单行设置价格（由批量循环调用）"""
        name_item = self._table.item(row, self._COL_NAME)
        type_id = name_item.data(Qt.ItemDataRole.UserRole) if name_item else None
        spin = self._table.cellWidget(row, self._COL_PRICE)
        if type_id and spin:
            self._set_price_from_market(type_id, price_type, spin)

    def _filter_no_change(self):
        """取消勾选比原纪录为 0 的行（无实际数量变化）"""
        filtered = 0
        for row in range(self._table.rowCount()):
            delta_item = self._table.item(row, self._COL_DELTA)
            if delta_item:
                try:
                    delta = int(delta_item.text().replace(",", "").replace("+", ""))
                    if delta == 0:
                        w = self._table.cellWidget(row, self._COL_CHECK)
                        if w:
                            cb = w.findChild(QCheckBox)
                            if cb:
                                cb.setChecked(False)
                                filtered += 1
                except ValueError:
                    pass
        self._update_summary()
        if filtered:
            self._summary_label.setText(self._summary_label.text() + f"  [已过滤 {filtered} 项无变化]")

    def _add_from_hangar(self, source_hangar_id: int):
        """从其他机库选择物品加入导入列表"""
        source_items = get_items(source_hangar_id)
        if not source_items:
            QMessageBox.information(self, "提示", "该机库中无物品")
            return

        # 简单弹窗：列出物品供勾选
        dlg = QDialog(self)
        dlg.setWindowTitle("选择要移动的物品")
        dlg.setMinimumSize(500, 350)
        dl = QVBoxLayout(dlg)

        table = QTableWidget(len(source_items), 3)
        table.setHorizontalHeaderLabels(["", "名称", "数量"])
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.verticalHeader().setVisible(False)

        for i, it in enumerate(source_items):
            cb = QCheckBox()
            cb.setChecked(True)
            cb_w = QWidget()
            cb_l = QHBoxLayout(cb_w)
            cb_l.setContentsMargins(0, 0, 0, 0)
            cb_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_l.addWidget(cb)
            table.setCellWidget(i, 0, cb_w)

            nm = it.get("zh_name") or it.get("en_name") or f"ID:{it['type_id']}"
            ni = QTableWidgetItem(nm)
            ni.setFlags(ni.flags() & ~Qt.ItemFlag.ItemIsEditable)
            ni.setData(Qt.ItemDataRole.UserRole, it["type_id"])
            table.setItem(i, 1, ni)

            qi = QTableWidgetItem(f"{it['quantity']:,}")
            qi.setFlags(qi.flags() & ~Qt.ItemFlag.ItemIsEditable)
            qi.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(i, 2, qi)

        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setColumnWidth(0, 28)
        dl.addWidget(table)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dl.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # 将勾选的物品加入当前列表
        added = 0
        for i in range(table.rowCount()):
            w = table.cellWidget(i, 0)
            if not w:
                continue
            cb = w.findChild(QCheckBox)
            if not cb or not cb.isChecked():
                continue
            name_item = table.item(i, 1)
            qty_item = table.item(i, 2)
            if not name_item or not qty_item:
                continue
            type_id = name_item.data(Qt.ItemDataRole.UserRole)
            try:
                qty = int(qty_item.text().replace(",", ""))
            except ValueError:
                continue
            # 加入 parsed_items（正值 = 从来源机库移入）
            self._parsed_items.append({"type_id": type_id, "zh_name": name_item.text(), "en_name": "", "qty": qty})
            self._source_hangar[type_id] = source_hangar_id
            added += 1

        if added:
            # 重新填充表格
            self._fetch_existing_inventory()
            self._fetch_sell_prices()
            self._table.setRowCount(len(self._parsed_items))
            self._populate_rows()

    def _set_price_from_market(self, type_id: int, price_type: str, spin: QDoubleSpinBox):
        with get_container().db.connect("mkt") as conn:
            cursor = conn.cursor()
            if price_type == "avg":
                cursor.execute(
                    "SELECT sell_price, buy_price FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                    (type_id, self._region_id),
                )
                r = cursor.fetchone()
                if r and r[0] and r[1]:
                    spin.setValue(round((r[0] + r[1]) / 2, 2))
                elif r:
                    spin.setValue(r[0] or r[1] or 0)
                else:
                    QMessageBox.information(self, "提示", "未找到该物品在所选区域的价格数据")
            else:
                col = "sell_price" if price_type == "sell" else "buy_price"
                cursor.execute(
                    f"SELECT {col} FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                    (type_id, self._region_id),
                )
                r = cursor.fetchone()
                if r and r[0] is not None:
                    spin.setValue(r[0])
                else:
                    QMessageBox.information(self, "提示", "未找到该物品在所选区域的价格数据")

    def _update_summary(self):
        checked = 0
        total_value = 0.0
        total_delta = 0
        for row in range(self._table.rowCount()):
            w = self._table.cellWidget(row, self._COL_CHECK)
            if w:
                cb = w.findChild(QCheckBox)
                if cb and cb.isChecked():
                    checked += 1
                    delta_item = self._table.item(row, self._COL_DELTA)
                    if delta_item:
                        try:
                            total_delta += int(delta_item.text().replace(",", "").replace("+", ""))
                        except ValueError:
                            pass
                    spin = self._table.cellWidget(row, self._COL_PRICE)
                    if spin:
                        try:
                            delta = int(delta_item.text().replace(",", "").replace("+", "")) if delta_item else 0
                        except ValueError:
                            delta = 0
                        total_value += spin.value() * delta
        total_items = self._table.rowCount()
        self._summary_label.setText(
            f"已勾选 {checked} 项 / 总计 {total_items} 项 / 总增减 {total_delta:,} / 预估成本 {total_value:,.0f} ISK"
        )

    def _on_accept(self):
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

    def get_import_data(self) -> list[tuple[int, int, float, int | None]]:
        """获取最终导入数据 list[(type_id, delta_qty, cost_price, source_hangar_id)]"""
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

            delta_item = self._table.item(row, self._COL_DELTA)
            try:
                delta = int(delta_item.text().replace(",", "").replace("+", "")) if delta_item else 0
            except ValueError:
                continue

            spin = self._table.cellWidget(row, self._COL_PRICE)
            price = spin.value() if spin else 0.0

            src = self._source_hangar.get(type_id)
            result.append((type_id, delta, price, src))
        return result

    def showEvent(self, event):
        """显示前重新应用主题样式"""
        super().showEvent(event)
        self._reapply_styles()

    def _reapply_styles(self):
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")


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
    """仓库管理 — 机库管理 + 蓝图管理"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        init_db()
        self.setObjectName("inventory_page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 0)
        layout.setSpacing(6)

        # ── 共享机库选择器 ──
        hangar_bar = QHBoxLayout()
        hangar_bar.addWidget(QLabel("机库:"))
        self._hangar_combo = QComboBox()
        self._hangar_combo.setMinimumWidth(140)
        hangar_bar.addWidget(self._hangar_combo)

        self._new_h_btn = QPushButton("+新建")
        self._new_h_btn.clicked.connect(self._on_new_hangar)
        hangar_bar.addWidget(self._new_h_btn)

        self._rename_h_btn = QPushButton("重命名")
        self._rename_h_btn.clicked.connect(self._on_rename_hangar)
        hangar_bar.addWidget(self._rename_h_btn)

        self._del_h_btn = QPushButton("删除")
        self._del_h_btn.clicked.connect(self._on_del_hangar)
        hangar_bar.addWidget(self._del_h_btn)

        hangar_bar.addStretch()
        layout.addLayout(hangar_bar)

        self._current_hangar_id: int | None = None
        self._load_hangars()

        self._tabs = QTabWidget()
        self._tabs.setObjectName("storage_tabs")

        self._hangar_tab = HangarTab(self)
        self._blueprint_tab = BlueprintTab(self)

        self._tabs.addTab(self._hangar_tab, "机库管理")
        self._tabs.addTab(self._blueprint_tab, "蓝图管理")

        layout.addWidget(self._tabs)

        self._hangar_combo.currentIndexChanged.connect(self._on_hangar_changed)

        theme.add_theme_listener(self._on_theme_changed)

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式表"""
        self._hangar_tab._on_theme_changed()
        self._blueprint_tab._on_theme_changed()

    def hangar_id(self) -> int | None:
        return self._current_hangar_id

    def _load_hangars(self):
        hs = get_hangars()
        self._hangar_combo.blockSignals(True)
        self._hangar_combo.clear()
        for h in hs:
            self._hangar_combo.addItem(h["name"], h["id"])
        self._hangar_combo.blockSignals(False)
        if hs:
            self._current_hangar_id = hs[0]["id"]
            self._hangar_combo.setCurrentIndex(0)

    def _on_hangar_changed(self, idx):
        if idx < 0:
            return
        self._current_hangar_id = self._hangar_combo.itemData(idx)
        self._hangar_tab._refresh()
        self._blueprint_tab._load_blueprints()

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
        reply = QMessageBox.question(self, "确认", f"删除机库「{name}」及其所有物品？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            delete_hangar(self._current_hangar_id)
            self._load_hangars()

    def refresh_display(self):
        self._hangar_tab._refresh()


class HangarTab(QWidget):
    """机库管理 — 多机库库存管理"""

    def __init__(self, inventory_page):
        super().__init__()
        self._page = inventory_page
        self.setObjectName("hangar_tab")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._build_action_bar(layout)

        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSortingEnabled(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.verticalHeader().setDefaultSectionSize(32)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, w in {0: 28, 1: 150, 2: 70, 3: 90, 4: 65, 5: 65, 6: 100}.items():
            self._table.setColumnWidth(col, w)
        layout.addWidget(self._table, 1)

        self._model: InvTableModel | None = None
        self._refresh()

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
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        bar.addWidget(self._count_label)

        layout.addLayout(bar)

        self._total_label = QLabel("按卖单价格: -- ISK")
        self._total_label.setStyleSheet(f"font-weight: bold; color: {theme.PRIMARY}; font-size: 13px;")
        layout.addWidget(self._total_label)

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式表"""
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        self._total_label.setStyleSheet(f"font-weight: bold; color: {theme.PRIMARY}; font-size: 13px;")

    # ── 剪贴板导入 ──

    def _parse_clipboard(self, raw: str) -> list[dict]:
        """解析 EVE 剪贴板格式 → list[{type_id, zh_name, en_name, qty}]

        支持两种格式（自动识别）：
        1. 仓库/精简格式: 物品名\\t数量
        2. 列表视图格式: 物品名\\t数量\\t分类\\t尺寸\\t槽位\\t体积\\t估价  (≥6个tab字段)
        """
        lines = raw.strip().split("\n")
        results = []
        errors = []
        with get_container().db.connect("ref", "bp") as conn:
            c = conn.cursor()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                cols = line.split("\t")
                if len(cols) < 2:
                    errors.append(f"格式错误: {line}")
                    continue

                # 自动识别：列表视图格式（≥6 个 tab 字段，第6字段含 "m3"）
                is_list_view = len(cols) >= 6 and "m3" in (cols[5] if len(cols) > 5 else "")

                if is_list_view:
                    name_part = cols[0].strip()
                    qty_str = cols[1].strip()
                else:
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
                nm = resolve_item_name(c, type_id)
                results.append(
                    {
                        "type_id": type_id,
                        "qty": qty,
                        "zh_name": nm if not nm.isdigit() else name_clean,
                        "en_name": nm if not nm.isdigit() else "",
                    }
                )
        if errors:
            err_msg = "\n".join(errors[:3])
            if len(errors) > 3:
                err_msg += f"\n...还有 {len(errors) - 3} 个错误"
            QMessageBox.warning(self, "解析警告", err_msg)
        return results

    def _on_paste_import(self):
        if not self._page.hangar_id():
            return
        # 自动读取剪贴板
        raw = QApplication.clipboard().text().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "剪贴板为空，请先在游戏中复制物品（Ctrl+C）")
            return
        parsed = self._parse_clipboard(raw)
        if not parsed:
            return
        hangar_name = self._page._hangar_combo.currentText()
        dlg = ImportReviewDialog(parsed, hangar_name, self._page.hangar_id(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_import_data()
        if not data:
            return
        added = 0
        moved = 0
        for type_id, delta, price, src_hangar in data:
            if delta <= 0:
                continue
            if src_hangar is not None:
                # 来自其他机库：先找到源机库中该物品的 item_id，再移动
                src_items = get_items(src_hangar)
                src_item = next((it for it in src_items if it["type_id"] == type_id), None)
                if src_item:
                    move_items([src_item["id"]], self._page.hangar_id())
                    moved += 1
            else:
                rid = add_item(self._page.hangar_id(), type_id, delta, price)
                if rid != -1:
                    added += 1
        self._refresh()
        msg = f"成功导入 {added} 条"
        if moved:
            msg += f"，跨机库移动 {moved} 条"
        QMessageBox.information(self, "完成", msg)

    # ── 移动 ──

    def _on_move_items(self):
        if not self._page.hangar_id() or not self._model:
            return
        sel = self._table.selectionModel().selectedRows()
        if not sel:
            QMessageBox.information(self, "提示", "请先选中要移动的物品")
            return
        ids = [self._model.item_at(r.row())["id"] for r in sel]
        hangars = get_hangars()
        targets = [h for h in hangars if h["id"] != self._page.hangar_id()]
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

        edit_act = QAction("编辑数量", self)
        edit_act.triggered.connect(lambda: self._on_edit_qty(item))
        menu.addAction(edit_act)

        del_act = QAction("删除", self)
        del_act.triggered.connect(lambda: self._on_del_item(item))
        menu.addAction(del_act)

        move_menu = menu.addMenu("移动到")
        for h in get_hangars():
            if h["id"] != self._page.hangar_id():
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
        if not self._page.hangar_id():
            return
        items = get_items(self._page.hangar_id())
        self._model = InvTableModel(items)
        self._table.setModel(self._model)
        self._count_label.setText(f"共 {len(items)} 项")

        # 计算总价
        total = sum((it["quantity"] * (it.get("sell_price") or 0)) for it in items if it.get("sell_price"))
        self._total_label.setText(f"按卖单价格: {total:,.0f} ISK")


# ════════════════════════════════════════════════════
#  蓝图管理 Tab
# ════════════════════════════════════════════════════

class BlueprintTableModel(QAbstractTableModel):
    _HEADERS = ["图标", "名称", "类型", "材料等级", "时间等级", "产物名称", "制造时间", "流程数量",
                "材料成本", "销售收入", "利润率"]

    def __init__(self, rows: list[dict]):
        super().__init__()
        self._rows = rows

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        c = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return ""
            if c == 1:
                return r.get("zh_name") or r.get("display_name") or f"ID:{r['blueprint_type_id']}"
            if c == 2:
                return "蓝图原图" if r.get("is_bpo") else "蓝图拷贝"
            if c == 3:
                return str(r.get("me_level", 0))
            if c == 4:
                return str(r.get("te_level", 0))
            if c == 5:
                return r.get("product_name") or "-"
            if c == 6:
                secs = r.get("base_time", 0)
                if secs <= 0:
                    return "-"
                h, m = divmod(secs // 60, 60)
                d, h = divmod(h, 24)
                if d:
                    return f"{d}d {h}h {m}m"
                return f"{h}h {m}m"
            if c == 7:
                runs = r.get("runs", 1)
                if runs == -1:
                    return "无限"
                return str(runs)
            if c == 8:
                cost = r.get("material_cost")
                return f"{cost:,.0f} ISK" if cost is not None else "-"
            if c == 9:
                rev = r.get("revenue")
                return f"{rev:,.0f} ISK" if rev is not None else "-"
            if c == 10:
                margin = r.get("margin")
                if margin is None:
                    return "-"
                return f"{margin:+.1f}%"

        elif role == Qt.ItemDataRole.DecorationRole:
            if c == 0:
                prod_id = r.get("product_type_id")
                if prod_id:
                    icon_path = os.path.join(ICON_DIR, f"{prod_id}.png")
                    if os.path.exists(icon_path):
                        pix = QPixmap(icon_path)
                        if not pix.isNull():
                            return pix.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            return None

        elif role == Qt.ItemDataRole.ForegroundRole:
            if c == 10:
                margin = r.get("margin")
                if margin is not None:
                    return QColor(theme.ACCENT_GREEN) if margin >= 0 else QColor(theme.ACCENT_RED)
            return None

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if c >= 2:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def row_at(self, row: int) -> dict | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        _SORT_KEYS = {
            1: lambda r: r.get("zh_name") or r.get("display_name") or "",
            2: lambda r: "蓝图原图" if r.get("is_bpo") else "蓝图拷贝",
            3: lambda r: r.get("me_level", 0),
            4: lambda r: r.get("te_level", 0),
            5: "product_name",
            6: lambda r: r.get("base_time", 0),
            7: lambda r: r.get("runs", 1) if r.get("runs", 1) != -1 else float("inf"),
            8: lambda r: r.get("material_cost") or 0,
            9: lambda r: r.get("revenue") or 0,
            10: lambda r: r.get("margin") or float("-inf"),
        }
        key = _SORT_KEYS.get(column)
        if not key and column != 0:
            return
        if column == 0:
            key = lambda r: r.get("product_type_id") or 0
        if isinstance(key, str):
            k = key
            key = lambda r: (r.get(k) or "") if isinstance(r.get(k), str) else str(r.get(k) or "")

        rev = order == Qt.SortOrder.DescendingOrder
        self.beginResetModel()
        self._rows.sort(key=key, reverse=rev)
        self.endResetModel()


class _BlueprintImportWorker(QThread):
    """后台线程：解析剪贴板 → 比对库 → 替换写入"""
    progress = Signal(int, int, str)
    finished = Signal(int, int, int)  # added, removed, total

    def __init__(self, raw: str, hangar_id: int):
        super().__init__()
        self._raw = raw
        self._hangar_id = hangar_id

    def run(self):
        # 1. 解析剪贴板
        pasted: list[tuple] = []  # (bpid, is_bpo, me, te, runs)
        with get_container().db.connect("ref", "bp") as conn:
            c = conn.cursor()
            lines = [l for l in self._raw.split("\n") if l.strip()]
            total = len(lines)
            for i, line in enumerate(lines):
                cols = line.split("\t")
                if len(cols) < 5:
                    continue
                name_part = cols[0].strip().rstrip("*")
                try:
                    me = int(cols[1].strip())
                    te = int(cols[2].strip())
                    runs = int(cols[3].strip())
                except ValueError:
                    continue
                is_bpo = "原图" in cols[4].strip() or "原本" in cols[4].strip()
                bpid = self._lookup_bpid(c, name_part, cols)
                if not bpid:
                    continue
                pasted.append((bpid, int(is_bpo), me, te, runs))
                if i % 100 == 0:
                    self.progress.emit(i, total, f"解析中... {i}/{total}")

        # 2. 读取库中现有蓝图（保留 id 用于精确删除）
        existing_map: dict[tuple, int] = {}  # (bpid, is_bpo, me, te, runs) → row_id
        with get_container().db.connect("user") as uc:
            c = uc.cursor()
            c.execute("SELECT id, blueprint_type_id, is_bpo, me_level, te_level, runs FROM user_blueprints WHERE hangar_id = ?",
                      (self._hangar_id,))
            for row in c.fetchall():
                existing_map[(row[1], row[2], row[3], row[4], row[5])] = row[0]

        # 3. 比对变化（用 list 比较，保留重复数量）
        from collections import Counter
        pasted_counter = Counter(pasted)
        existing_counter = Counter(existing_map.keys())
        all_keys = set(pasted_counter) | set(existing_counter)

        to_add: list[tuple] = []
        to_remove: list[int] = []
        added = 0
        removed = 0
        for key in all_keys:
            p_cnt = pasted_counter.get(key, 0)
            e_cnt = existing_counter.get(key, 0)
            if p_cnt > e_cnt:
                # 需要新增 p_cnt - e_cnt 条
                to_add.extend([key] * (p_cnt - e_cnt))
                added += p_cnt - e_cnt
            elif p_cnt < e_cnt:
                # 需要删除 e_cnt - p_cnt 条
                # 找到所有匹配 key 的 row_id
                for ek, rid in existing_map.items():
                    if ek == key:
                        to_remove.append(rid)
                        if len(to_remove) >= e_cnt - p_cnt + removed:
                            break
                removed += e_cnt - p_cnt

        # 4. 无变化则跳过
        if added == 0 and removed == 0:
            self.finished.emit(0, 0, len(pasted))
            return

        # 5. 增量更新
        with get_container().db.connect("user") as uc:
            c = uc.cursor()
            for row_id in to_remove:
                c.execute("DELETE FROM user_blueprints WHERE id = ?", (row_id,))
            uc.commit()

            for i, bp in enumerate(to_add):
                c.execute(
                    "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity) VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (self._hangar_id, bp[0], bp[1], bp[2], bp[3], bp[4]))
                if i % 200 == 0 or i == len(to_add) - 1:
                    uc.commit()
                    self.progress.emit(i + 1, len(to_add), f"写入中... {i + 1}/{len(to_add)}")
            uc.commit()

        self.finished.emit(added, removed, len(pasted))

    def _lookup_bpid(self, c, name_part, cols):
        # 1. 精确匹配
        c.execute("SELECT type_id FROM item WHERE zh_name = ? OR en_name = ? LIMIT 1", (name_part, name_part))
        r = c.fetchone()
        if r:
            return r[0]
        # 2. 产物反查：蓝图名替换 "蓝图 X" → " X" → 产物名 → 制造蓝图
        for suffix in ("蓝图 II", "蓝图 I", "蓝图 III"):
            if suffix in name_part:
                prod_name = name_part.replace(suffix, suffix.replace("蓝图", ""))
                c.execute("SELECT type_id FROM item WHERE zh_name = ? LIMIT 1", (prod_name,))
                r = c.fetchone()
                if r:
                    c.execute(
                        "SELECT blueprint_type_id FROM blueprint_products WHERE product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
                        (r[0],))
                    r2 = c.fetchone()
                    if r2:
                        return r2[0]
                break  # 只尝试第一个匹配的后缀
        return None


class BlueprintTab(QWidget):
    """蓝图管理 — 管理用户拥有的蓝图"""

    def __init__(self, inventory_page):
        super().__init__()
        self._page = inventory_page
        self.setObjectName("blueprint_tab")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 工具栏 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        paste_btn = QPushButton("粘贴导入蓝图")
        paste_btn.clicked.connect(self._on_paste_blueprint)
        toolbar.addWidget(paste_btn)

        self._refresh_econ_btn = QPushButton("刷新计算")
        self._refresh_econ_btn.clicked.connect(self._on_refresh_economics)
        toolbar.addWidget(self._refresh_econ_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # ── 过滤器 ──
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        filter_bar.addWidget(QLabel("类型:"))
        self._type_filter = QComboBox()
        self._type_filter.addItems(["全部", "蓝图原图", "蓝图拷贝", "反应公式"])
        self._type_filter.currentIndexChanged.connect(self._on_search)
        filter_bar.addWidget(self._type_filter)

        filter_bar.addWidget(QLabel("科技等级:"))
        self._tech_filter = QComboBox()
        self._tech_filter.addItems(["全部", "T1", "T2", "T3"])
        self._tech_filter.currentIndexChanged.connect(self._on_search)
        filter_bar.addWidget(self._tech_filter)

        filter_bar.addWidget(QLabel("市场分类:"))
        self._market_filter = QComboBox()
        self._market_filter.addItem("全部", None)
        self._market_filter.currentIndexChanged.connect(self._on_search)
        filter_bar.addWidget(self._market_filter, 1)

        layout.addLayout(filter_bar)

        # ── 搜索栏 ──
        search_bar = QHBoxLayout()
        search_bar.setSpacing(6)
        search_bar.addWidget(QLabel("搜索:"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("输入蓝图/产物名称...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search)
        search_bar.addWidget(self._search_input, 1)
        layout.addLayout(search_bar)

        # ── 蓝图列表 ──
        self._bp_table = QTableView()
        self._bp_table.setAlternatingRowColors(True)
        self._bp_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._bp_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._bp_table.horizontalHeader().setStretchLastSection(True)
        self._bp_table.setSortingEnabled(True)
        self._bp_table.verticalHeader().setDefaultSectionSize(32)
        self._bp_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._bp_table.customContextMenuRequested.connect(self._on_context_menu)
        self._bp_table.clicked.connect(self._on_cell_clicked)
        # 固定列宽（避免 ResizeToContents 扫描全表 O(n) 卡顿）
        hdr = self._bp_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, w in {0: 28, 1: 140, 2: 70, 3: 60, 4: 60, 5: 120, 6: 80, 7: 65, 8: 90, 9: 90, 10: 70}.items():
            self._bp_table.setColumnWidth(col, w)
        self._bp_table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._bp_table, 1)

        # ── 状态栏 ──
        status_bar = QHBoxLayout()
        self._bp_count_label = QLabel("")
        self._bp_count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        status_bar.addWidget(self._bp_count_label)
        status_bar.addStretch()
        layout.addLayout(status_bar)

        self._bp_model: BlueprintTableModel | None = None
        self._all_rows: list[dict] = []
        self._tech_levels: dict[int, int] = {}
        self._reaction_ids: set[int] = set()

        self._load_market_categories()
        self._load_blueprints()

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式表"""
        self._bp_count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")

    def _load_market_categories(self):
        """加载根级市场分类到下拉框"""
        with get_container().db.connect("ref") as conn:
            c = conn.cursor()
            c.execute("SELECT market_group_id, zh_name FROM market_tree WHERE parent_group_id IS NULL ORDER BY zh_name")
            for mgid, name in c.fetchall():
                if name:
                    self._market_filter.addItem(name, mgid)

    def _load_blueprints(self):
        """从 user_blueprints 加载用户拥有的蓝图"""
        if not self._tech_levels:
            self._tech_levels = get_blueprint_tech_levels()
        if not self._reaction_ids:
            self._reaction_ids = get_blueprint_reaction_ids()

        rows = []
        bps = get_blueprints(self._page.hangar_id())

        # 批量获取产物信息（1300 次 DB → 1 次）
        bp_ids = [bp["blueprint_type_id"] for bp in bps]
        prod_info_map = get_blueprint_product_info_batch(bp_ids)

        for bp in bps:
            bpid = bp["blueprint_type_id"]
            prod_info = prod_info_map.get(bpid)
            if prod_info:
                bp["product_type_id"] = prod_info["product_type_id"]
                bp["product_name"] = prod_info["product_name"]
                bp["product_quantity"] = prod_info["product_quantity"]
                bp["base_time"] = prod_info["base_time"]
            else:
                bp["product_type_id"] = None
                bp["product_name"] = "-"
                bp["product_quantity"] = 1
                bp["base_time"] = 0
            # T2 蓝图缺名时从产物名推导
            if not bp.get("zh_name") and bp.get("product_name") and bp["product_name"] != "-":
                bp["display_name"] = bp["product_name"].replace(" II", "蓝图 II").replace(" I", "蓝图 I")
            bp["tech_level"] = self._tech_levels.get(bpid, 1)
            bp["is_reaction"] = bpid in self._reaction_ids
            rows.append(bp)

        self._all_rows = rows
        self._calc_economics()
        self._apply_filter()

    def _calc_economics(self):
        """批量计算所有蓝图的经济指标"""
        if not self._all_rows:
            return

        # 批量获取材料（1300 次 DB → 1 次）
        bp_ids = [r["blueprint_type_id"] for r in self._all_rows]
        bp_materials = get_blueprint_materials_batch(bp_ids)

        mat_ids: set[int] = set()
        for mats in bp_materials.values():
            for mid, _ in mats:
                mat_ids.add(mid)

        prod_ids: set[int] = {r["product_type_id"] for r in self._all_rows if r.get("product_type_id")}

        # 批量查价格
        prices: dict[int, float] = {}
        all_ids = mat_ids | prod_ids
        if all_ids:
            with get_container().db.connect("mkt") as conn:
                c = conn.cursor()
                placeholders = ",".join("?" * len(all_ids))
                c.execute(
                    f"SELECT type_id, sell_price FROM market_prices WHERE type_id IN ({placeholders}) AND region_id = 10000002",
                    tuple(all_ids))
                for tid, price in c.fetchall():
                    if price:
                        prices[tid] = price

        # 计算每行
        for row in self._all_rows:
            bpid = row["blueprint_type_id"]
            mats = bp_materials.get(bpid, [])
            total_cost = 0.0
            for mid, qty in mats:
                p = prices.get(mid)
                if p:
                    total_cost += qty * p

            prod_id = row.get("product_type_id")
            prod_qty = row.get("product_quantity", 1)
            prod_price = prices.get(prod_id) if prod_id else None

            row["material_cost"] = total_cost if total_cost > 0 else None
            if prod_price:
                row["revenue"] = prod_price * prod_qty
            else:
                row["revenue"] = None

            cost = row["material_cost"]
            rev = row["revenue"]
            if cost and rev:
                row["margin"] = (rev - cost) / cost * 100
            else:
                row["margin"] = None

    def _on_refresh_economics(self):
        self._refresh_econ_btn.setEnabled(False)
        self._refresh_econ_btn.setText("计算中...")
        self._calc_economics()
        self._apply_filter()
        self._refresh_econ_btn.setEnabled(True)
        self._refresh_econ_btn.setText("刷新计算")

    def _apply_filter(self):
        search = self._search_input.text().strip().lower() if self._search_input else ""
        type_sel = self._type_filter.currentText()
        tech_sel = self._tech_filter.currentText()
        market_id = self._market_filter.currentData()

        filtered = self._all_rows

        # 类型过滤
        if type_sel == "蓝图原图":
            filtered = [r for r in filtered if r.get("is_bpo") and not r.get("is_reaction")]
        elif type_sel == "蓝图拷贝":
            filtered = [r for r in filtered if not r.get("is_bpo") and not r.get("is_reaction")]
        elif type_sel == "反应公式":
            filtered = [r for r in filtered if r.get("is_reaction")]

        # 科技等级过滤
        if tech_sel != "全部":
            target = int(tech_sel[1])  # "T1" → 1
            filtered = [r for r in filtered if r.get("tech_level") == target]

        # 市场分类过滤（按产物所属分类）
        if market_id is not None:
            matching_ids = self._get_market_descendants(market_id)
            filtered = [r for r in filtered if r.get("product_type_id") in matching_ids]

        # 搜索过滤
        if search:
            filtered = [
                r for r in filtered
                if search in (r.get("zh_name") or "").lower()
                or search in (r.get("en_name") or "").lower()
                or search in (r.get("product_name") or "").lower()
                or search in str(r.get("blueprint_type_id", ""))
            ]

        self._bp_model = BlueprintTableModel(filtered)
        self._bp_table.setModel(self._bp_model)
        self._bp_count_label.setText(f"共 {len(filtered)} 个蓝图")

    def _get_market_descendants(self, market_group_id: int) -> set[int]:
        """递归获取指定市场分类下所有物品 type_id"""
        try:
            with get_container().db.connect("ref") as conn:
                c = conn.cursor()
                c.execute("""
                    WITH RECURSIVE sub AS (
                        SELECT market_group_id FROM market_tree WHERE market_group_id = ?
                        UNION ALL
                        SELECT m.market_group_id FROM market_tree m JOIN sub ON m.parent_group_id = sub.market_group_id
                    )
                    SELECT DISTINCT i.type_id FROM item i
                    WHERE i.market_group_id IN (SELECT market_group_id FROM sub)
                """, (market_group_id,))
                return {r[0] for r in c.fetchall()}
        except Exception:
            return set()

    def _on_search(self):
        self._apply_filter()

    def _on_cell_clicked(self, idx):
        if not idx.isValid() or not self._bp_model or idx.column() == 0:
            return
        text = self._bp_model.data(idx, Qt.ItemDataRole.DisplayRole)
        if text and text not in ("", "-"):
            QApplication.clipboard().setText(str(text))

    def _on_context_menu(self, pos):
        # 收集选中行的 id
        sel_rows = {idx.row() for idx in self._bp_table.selectionModel().selectedRows()}
        idx = self._bp_table.indexAt(pos)
        if idx.isValid() and idx.row() not in sel_rows:
            sel_rows = {idx.row()}  # 右键到未选中行时只操作该行
        if not sel_rows or not self._bp_model:
            return
        selected = [self._bp_model.row_at(r) for r in sorted(sel_rows)]
        selected = [bp for bp in selected if bp]
        if not selected:
            return
        bp_ids = [bp["id"] for bp in selected]

        menu = QMenu(self)

        research = menu.addAction("研究分析")
        menu.addSeparator()
        del_action = menu.addAction("删除行" if len(bp_ids) == 1 else f"删除行 ({len(bp_ids)})")
        menu.addSeparator()
        move_action = menu.addAction("修改蓝图所在机库")
        cost_action = menu.addAction("修改蓝图每流程成本")
        auto_cost = menu.addAction("自动填写每流程成本(T2发明)")
        menu.addSeparator()
        add_plan = menu.addAction("加入制造业规划")
        menu.addSeparator()
        edit_level = menu.addAction("修改蓝图等级")
        edit_runs = menu.addAction("修改流程数")
        add_research = menu.addAction("加入效率研究规划")

        action = menu.exec(self._bp_table.viewport().mapToGlobal(pos))

        if action == del_action:
            self._delete_blueprints(selected)
        elif action == move_action:
            self._move_blueprints(bp_ids)
        elif action == cost_action:
            self._set_cost_per_run(bp_ids)
        elif action == edit_level:
            self._edit_levels(bp_ids)
        elif action == edit_runs:
            self._edit_runs(bp_ids)
        # 占位项：暂无操作
        elif action in (research, auto_cost, add_plan, add_research):
            QMessageBox.information(self, "提示", "此功能即将上线")

    def _delete_blueprints(self, selected: list[dict]):
        n = len(selected)
        reply = QMessageBox.question(self, "确认删除", f"确定要删除 {n} 行蓝图吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        ids = [bp["id"] for bp in selected]
        delete_blueprints_batch(ids)
        self._load_blueprints()

    def _move_blueprints(self, bp_ids: list[int]):
        hangars = get_hangars()
        names = [h["name"] for h in hangars]
        name, ok = QInputDialog.getItem(self, "修改蓝图所在机库", "目标机库:", names, 0, False)
        if ok and name:
            target_id = next(h["id"] for h in hangars if h["name"] == name)
            move_blueprints_to_hangar(bp_ids, target_id)
            self._load_blueprints()

    def _set_cost_per_run(self, bp_ids: list[int]):
        val, ok = QInputDialog.getDouble(self, "修改每流程成本", "成本 (ISK):", 0, 0, 1e12, 2)
        if ok:
            update_blueprints_batch(bp_ids, cost_per_run=val)
            self._load_blueprints()

    def _edit_levels(self, bp_ids: list[int]):
        dlg = QDialog(self)
        dlg.setWindowTitle("修改蓝图等级")
        fl = QFormLayout(dlg)
        me = QDoubleSpinBox(); me.setRange(0, 10); me.setDecimals(0)
        te = QDoubleSpinBox(); te.setRange(0, 10); te.setDecimals(0)
        fl.addRow("材料等级:", me)
        fl.addRow("时间等级:", te)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(dlg.accept); btn.rejected.connect(dlg.reject)
        fl.addRow(btn)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            update_blueprints_batch(bp_ids, me_level=int(me.value()), te_level=int(te.value()))
            self._load_blueprints()

    def _edit_runs(self, bp_ids: list[int]):
        val, ok = QInputDialog.getInt(self, "修改流程数", "流程数:", 1, -1, 99999, 1)
        if ok:
            update_blueprints_batch(bp_ids, runs=val)
            self._load_blueprints()

    def _on_paste_blueprint(self):
        if not self._page.hangar_id():
            return
        raw = QApplication.clipboard().text().strip()
        if not raw:
            return

        main_win = self._page._main
        main_win.show_progress("正在导入蓝图...", 0)
        self._worker = _BlueprintImportWorker(raw, self._page.hangar_id())
        self._worker.progress.connect(
            lambda cur, total, text: main_win.update_progress(cur, text) if total else None)
        self._worker.finished.connect(self._on_import_done)
        self._worker.start()

    def _on_import_done(self, added: int, removed: int, total: int):
        self._page._main.hide_progress(f"共 {total} 条蓝图")
        if added == 0 and removed == 0:
            self._bp_count_label.setText("蓝图库无变化")
        else:
            parts = [f"共 {total} 条"]
            if added:
                parts.append(f"新增 {added}")
            if removed:
                parts.append(f"删除 {removed}")
            self._bp_count_label.setText("，".join(parts))
        self._load_blueprints()
        self._worker = None
