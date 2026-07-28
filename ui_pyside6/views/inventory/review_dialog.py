"""
仓库页面 — 剪贴板导入预览对话框（ImportReviewDialog）
"""

import os
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.logger import log
from services.inventory_manager import get_hangars, get_items

from .inventory_helpers import ICON_DIR


class ImportReviewDialog(QDialog):
    """粘贴导入预览 — 右键菜单设价/删除/跨机库"""

    _HUB_NAMES = {"Jita": "吉他", "Amarr": "艾玛", "Dodixie": "多迪", "Rens": "伦斯"}
    _COL_CHECK = 0
    _COL_ICON = 1
    _COL_NAME = 2
    _COL_CURRENT = 3  # 数量（机库现有）
    _COL_DELTA = 4  # 比原纪录（本次增减）
    _COL_FINAL = 5  # 变化（最终数量）
    _COL_PRICE = 6  # 成本价
    _HEADERS = ["", "图标", "名称", "数量", "比原纪录", "变化", "成本价"]

    def __init__(self, items: list[dict], hangar_name: str, target_hangar_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"导入预览 → {hangar_name}")
        self.setMinimumSize(780, 420)
        self.resize(900, 520)
        self._parsed_items = items  # list of {type_id, zh_name, en_name, qty}
        self._target_hangar_id = target_hangar_id
        self._region_id = TRADE_HUB_IDS["Jita"]
        self._sell_prices: dict[int, float] = {}  # type_id → sell_price
        self._existing_qty: dict[int, int] = {}  # type_id → existing qty  in target
        self._source_hangar: dict[int, int] = {}  # type_id → source hangar id (for cross-hangar)

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
            log.exception("获取现有库存失败")

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
            delta = item["qty"]  # 比原纪录 = 本次增减量
            current = self._existing_qty.get(type_id, 0)  # 数量 = 机库现有
            final = current + delta  # 变化 = 最终数量

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
                spin = cast(QDoubleSpinBox | None, self._table.cellWidget(row, self._COL_PRICE))
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
        elif isinstance(action, (QAction,)) and action.data():
            self._add_from_hangar(action.data())

    def _batch_set_price(self, row: int, price_type: str):
        """对单行设置价格（由批量循环调用）"""
        name_item = self._table.item(row, self._COL_NAME)
        type_id = name_item.data(Qt.ItemDataRole.UserRole) if name_item else None
        spin = cast(QDoubleSpinBox | None, self._table.cellWidget(row, self._COL_PRICE))
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

    def _set_price_from_market(self, type_id: int, price_type: str, spin: "QDoubleSpinBox"):
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

            spin = cast(QDoubleSpinBox | None, self._table.cellWidget(row, self._COL_PRICE))
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
