"""
仓库页面 — 剪贴板导入预览对话框（ImportReviewDialog）
"""

from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
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
from services.inventory_import import compute_row_delta
from services.inventory_manager import get_hangars, get_items
from ui_pyside6.icon_cache import load_item_icon

from .item_search_dialog import ItemSearchDialog


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

    def __init__(
        self,
        items: list[dict],
        hangar_name: str,
        target_hangar_id: int,
        parent=None,
        *,
        default_mode: str = "full",
    ):
        super().__init__(parent)
        self.setWindowTitle(f"导入预览 → {hangar_name}")
        self.setMinimumSize(780, 420)
        self.resize(900, 520)
        self._parsed_items = items  # list of {type_id, zh_name, en_name, qty, ...}
        self._target_hangar_id = target_hangar_id
        self._region_id = TRADE_HUB_IDS["Jita"]
        self._sell_prices: dict[int, float] = {}  # type_id → sell_price
        self._existing_qty: dict[int, int] = {}  # type_id → existing qty  in target
        self._source_hangar: dict[int, int] = {}  # type_id → source hangar id (for cross-hangar)
        self._updating = False  # 防 itemChanged 重入

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 工具栏：导入模式 + 贸易中心 + 全选/取消全选 + 折扣率 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("导入模式:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("增量累加", "incremental")
        self._mode_combo.addItem("全量同步", "full")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self._mode_combo)
        self._mode = default_mode
        # 默认模式（库存修正=全量同步）；combo 触发时 _table 尚未创建，由守卫跳过
        self._mode_combo.setCurrentIndex(0 if default_mode == "incremental" else 1)

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
        self._table.itemChanged.connect(self._on_final_changed)
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
        type_ids = list({it["type_id"] for it in self._parsed_items if it.get("type_id")})
        if not type_ids:
            return
        self._sell_prices = get_container().market_repo.get_sell_prices(type_ids, self._region_id)

    def _populate_rows(self):
        table = self._table
        self._updating = True
        try:
            for row, item in enumerate(self._parsed_items):
                type_id = item.get("type_id")
                # 未匹配行：灰显、勾选禁用、数值 0、成本禁用
                if not type_id:
                    raw = item.get("raw_name") or item.get("zh_name") or item.get("en_name") or "?"
                    self._fill_unmatched_row(row, raw)
                    continue
                name = item.get("display_name") or item.get("zh_name") or item.get("en_name") or f"ID:{type_id}"
                current = self._existing_qty.get(type_id, 0)  # 数量 = 机库现有
                # 跨机库移动行始终按增量语义（不参与全量 set）；其余按当前导入模式计算
                row_mode = "incremental" if type_id in self._source_hangar else self._mode
                delta, final = compute_row_delta(row_mode, item["qty"], current)

                # 列0：勾选（是否变更）
                cb = QCheckBox()
                cb.setChecked(True)
                cb_w = QWidget()
                cb_l = QHBoxLayout(cb_w)
                cb_l.setContentsMargins(0, 0, 0, 0)
                cb_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cb_l.addWidget(cb)
                table.setCellWidget(row, self._COL_CHECK, cb_w)

                # 列1：图标
                icon_label = QLabel()
                icon_label.setFixedSize(24, 24)
                icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                pix = load_item_icon(type_id, size=24)
                if pix:
                    icon_label.setPixmap(pix)
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
                elif delta < 0:
                    delta_item.setForeground(QColor(theme.ACCENT_RED))
                table.setItem(row, self._COL_DELTA, delta_item)

                # 列5：变化（最终数量）— 可编辑，供库存修正逐行修正数量
                final_item = QTableWidgetItem(f"{final:,}")
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
        finally:
            self._updating = False

        # 自适应列宽
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setColumnWidth(self._COL_CHECK, 28)
        table.setColumnWidth(self._COL_ICON, 28)
        for col, min_w in [(self._COL_NAME, 140), (self._COL_DELTA, 90), (self._COL_FINAL, 90), (self._COL_PRICE, 90)]:
            if table.columnWidth(col) < min_w:
                table.setColumnWidth(col, min_w)

        self._update_summary()

    def _fill_unmatched_row(self, row: int, name: str):
        """未匹配行：灰显、勾选禁用、数值 0、成本禁用"""
        cb = QCheckBox()
        cb.setChecked(False)
        cb.setEnabled(False)
        cb_w = QWidget()
        cb_l = QHBoxLayout(cb_w)
        cb_l.setContentsMargins(0, 0, 0, 0)
        cb_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cb_l.addWidget(cb)
        self._table.setCellWidget(row, self._COL_CHECK, cb_w)

        name_item = QTableWidgetItem(f"{name}（未匹配）")
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name_item.setData(Qt.ItemDataRole.UserRole, None)
        name_item.setForeground(QColor(theme.TEXT_SECONDARY))
        self._table.setItem(row, self._COL_NAME, name_item)

        for col in (self._COL_CURRENT, self._COL_DELTA, self._COL_FINAL):
            it = QTableWidgetItem("0")
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it.setForeground(QColor(theme.TEXT_SECONDARY))
            self._table.setItem(row, col, it)

        spin = QDoubleSpinBox()
        spin.setRange(0, 1e12)
        spin.setDecimals(2)
        spin.setEnabled(False)
        self._table.setCellWidget(row, self._COL_PRICE, spin)

    def _on_final_changed(self, item):
        """最终数量列被编辑：重算 delta（增减）并刷新颜色/汇总。"""
        if self._updating or item.column() != self._COL_FINAL:
            return
        row = item.row()
        cur_item = self._table.item(row, self._COL_CURRENT)
        try:
            final = int(item.text().replace(",", "").replace(" ", ""))
            current = int(cur_item.text().replace(",", "")) if cur_item else 0
        except ValueError:
            return
        delta = final - current
        delta_item = self._table.item(row, self._COL_DELTA)
        if delta_item:
            delta_item.setText(f"+{delta:,}" if delta >= 0 else f"{delta:,}")
            if delta > 0:
                delta_item.setForeground(QColor(theme.ACCENT_GREEN))
            elif delta < 0:
                delta_item.setForeground(QColor(theme.ACCENT_RED))
            else:
                delta_item.setForeground(QColor(theme.TEXT_SECONDARY))
        self._update_summary()

    def _search_match(self, row: int):
        """把未匹配行接到用户搜索选中的物品，然后重填"""
        dlg = ItemSearchDialog(self, title="搜索匹配物品")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sel = dlg.selected_item()
        if not sel:
            return
        # 表格行号 = _parsed_items 下标（_populate_rows 按顺序填充）
        if not (0 <= row < len(self._parsed_items)) or self._parsed_items[row].get("type_id"):
            return
        entry = self._parsed_items[row]
        entry.update(
            {
                "type_id": sel["type_id"],
                "zh_name": sel["zh_name"],
                "en_name": sel["en_name"],
                "status": "matched",
            }
        )
        self._fetch_existing_inventory()
        self._fetch_sell_prices()
        self._populate_rows()

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

    def _on_mode_changed(self, idx: int):
        """导入模式切换：重算每行 delta/final。"""
        self._mode = cast(str, self._mode_combo.itemData(idx))
        if not hasattr(self, "_table"):
            return  # __init__ 早期 setCurrentIndex 触发时表格尚未创建
        self._populate_rows()

    def mode(self) -> str:
        """当前导入模式："incremental" 增量累加 | "full" 全量同步"""
        return self._mode

    def get_sync_targets(self) -> dict[int, int]:
        """全量模式下返回 {type_id: 目标数量}。

        跨机库移动行（_source_hangar）保持增量移动语义，不参与全量 set。
        """
        targets: dict[int, int] = {}
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
            if type_id in self._source_hangar:
                continue
            final_item = self._table.item(row, self._COL_FINAL)
            try:
                final = int(final_item.text().replace(",", "")) if final_item else 0
            except ValueError:
                continue
            targets[type_id] = final
        return targets

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

        # 未匹配行：提供手动搜索匹配
        match_action = None
        if len(rows) == 1:
            name_item = self._table.item(rows[0], self._COL_NAME)
            if name_item and name_item.data(Qt.ItemDataRole.UserRole) is None:
                match_action = menu.addAction("搜索匹配物品…")

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
        elif match_action is not None and action == match_action:
            self._search_match(rows[0])
        elif isinstance(action, QAction) and action.data():
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

            nm = it.get("display_name") or it.get("zh_name") or it.get("en_name") or f"ID:{it['type_id']}"
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
            cb_box: QCheckBox | None = w.findChild(QCheckBox)
            if not cb_box or not cb_box.isChecked():
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
        repo = get_container().market_repo
        if price_type == "avg":
            price = repo.get_price_by_region(type_id, "avg", self._region_id)
            if price is not None:
                spin.setValue(price)
            else:
                QMessageBox.information(self, "提示", "未找到该物品在所选区域的价格数据")
        else:
            price = repo.get_price_by_region(type_id, price_type, self._region_id)
            if price is not None:
                spin.setValue(price)
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
        unmatched = 0
        for row in range(self._table.rowCount()):
            w = self._table.cellWidget(row, self._COL_CHECK)
            if not w:
                continue
            cb = w.findChild(QCheckBox)
            if not cb or not cb.isChecked():
                continue
            has_checked = True
            name_item = self._table.item(row, self._COL_NAME)
            if name_item and name_item.data(Qt.ItemDataRole.UserRole) is None:
                unmatched += 1
        if not has_checked:
            QMessageBox.warning(self, "提示", "没有勾选的物品，无法导入")
            return
        if unmatched:
            QMessageBox.information(
                self, "提示", f"{unmatched} 行未匹配物品未指定 type_id，导入时将跳过（可右键搜索匹配）"
            )
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


# ════════════════════════════════════════════════════
#  Dialog: 导入完成变动汇总
# ════════════════════════════════════════════════════


class ImportChangeDialog(QDialog):
    """导入完成后的变动汇总 — 名称/数量 前→后/成本 前→后。

    增量行绿色、减量行红色；原「成功导入 N 条」信息并入顶部汇总。
    """

    _HEADERS = ["名称", "数量（前 → 后）", "成本（前 → 后）"]

    def __init__(self, changes: list[dict], added: int, moved: int, hangar_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"导入完成 — {hangar_name}")
        self.setMinimumSize(520, 380)
        self.resize(620, 460)
        self._changes = changes

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._summary_label = QLabel(self._build_summary(changes, added, moved))
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(self._summary_label)

        self._table = QTableWidget(len(changes), 3)
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        for row, ch in enumerate(changes):
            name_item = QTableWidgetItem(ch["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, name_item)

            qty_item = QTableWidgetItem(f"{ch['qty_before']:,} → {ch['qty_after']:,}")
            qty_item.setFlags(qty_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if ch["qty_delta"] > 0:
                qty_item.setForeground(QColor(theme.ACCENT_GREEN))
            elif ch["qty_delta"] < 0:
                qty_item.setForeground(QColor(theme.ACCENT_RED))
            self._table.setItem(row, 1, qty_item)

            cost_item = QTableWidgetItem(f"{ch['cost_before']:,.2f} → {ch['cost_after']:,.2f}")
            cost_item.setFlags(cost_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            cost_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 2, cost_item)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(0, 200)
        self._table.setColumnWidth(1, 140)
        self._table.setColumnWidth(2, 140)
        layout.addWidget(self._table, 1)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        theme.add_theme_listener(self._on_theme_changed)

    @staticmethod
    def _build_summary(changes: list[dict], added: int, moved: int) -> str:
        """汇总文案：共 N 项变化（增加/减少）+ 成功导入 + 跨机库移动。"""
        if not changes:
            return f"成功导入 {added} 条，数量/成本均无变化"
        inc = sum(1 for c in changes if c["qty_delta"] > 0)
        dec = sum(1 for c in changes if c["qty_delta"] < 0)
        parts = [f"共 {len(changes)} 项变化"]
        if inc:
            parts.append(f"增加 {inc}")
        if dec:
            parts.append(f"减少 {dec}")
        if added:
            parts.append(f"成功导入 {added} 条")
        if moved:
            parts.append(f"跨机库移动 {moved} 条")
        return "，".join(parts)

    def _on_theme_changed(self):
        """主题切换时重设增量/减量前景色（跟随主题）"""
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        for row, ch in enumerate(self._changes):
            qty_item = self._table.item(row, 1)
            if qty_item is None:
                continue
            if ch["qty_delta"] > 0:
                qty_item.setForeground(QColor(theme.ACCENT_GREEN))
            elif ch["qty_delta"] < 0:
                qty_item.setForeground(QColor(theme.ACCENT_RED))
