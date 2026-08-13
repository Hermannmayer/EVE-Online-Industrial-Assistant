"""
仓库页面 — 移库对话框（HangarTransferDialog）

从源机库按剪贴板数量把材料移到当前机库。剪贴板数量超出源库现有时自动 clamp
（移动到源库现有量并在该行标注「源库不足」）；未匹配行可右键「搜索匹配物品」后纳入。
"""

from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from services.inventory_import import compute_transfer_rows
from services.inventory_manager import get_hangar_stock, get_hangars, get_items, move_quantity
from ui_pyside6.icon_cache import load_item_icon

from .item_search_dialog import ItemSearchDialog


class HangarTransferDialog(QDialog):
    """移库 — 从源机库按剪贴板数量把材料移到当前机库。"""

    _COL_CHECK = 0
    _COL_ICON = 1
    _COL_NAME = 2
    _COL_CLIP = 3  # 剪贴板数量
    _COL_SRC = 4  # 源库现有
    _COL_MOVE = 5  # 移动数量（QSpinBox）
    _COL_COST = 6  # 源库单位成本
    _COL_TARGET = 7  # 目标现有
    _HEADERS = ["", "图标", "名称", "剪贴板数量", "源库现有", "移动数量", "单位成本", "目标现有"]

    def __init__(self, rows: list[dict], target_hangar_id: int, hangar_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"移库 → {hangar_name}")
        self.setMinimumSize(880, 480)
        self.resize(1000, 560)
        self._parsed = rows  # [{type_id|None, raw_name, zh_name, en_name, qty, status}]
        self._target_hangar_id = target_hangar_id
        self._result = {"moved": 0, "capped": 0}
        self._source_items: dict[int, dict] = {}  # type_id → 源库 item（取 cost_price）
        self._source_stock: dict[int, int] = {}
        self._target_stock: dict[int, int] = {}
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 来源机库选择 ──
        top = QHBoxLayout()
        top.addWidget(QLabel("来源机库:"))
        self._source_combo = QComboBox()
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        top.addWidget(self._source_combo, 1)
        layout.addLayout(top)

        # ── 预览表 ──
        self._table = QTableWidget(0, len(self._HEADERS))
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
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("确定移库")
        btn.accepted.connect(self._on_accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)
        self._ok_btn = btn.button(QDialogButtonBox.StandardButton.Ok)

        self._load_hangars()
        theme.add_theme_listener(self._on_theme_changed)

    # ── 数据加载 ──

    def _load_hangars(self):
        others = [h for h in get_hangars() if h["id"] != self._target_hangar_id]
        for h in others:
            self._source_combo.addItem(h["name"], h["id"])
        if not others:
            self._ok_btn.setEnabled(False)
            self._summary_label.setText("没有其他机库可移动")
            return
        self._on_source_changed()

    def _on_source_changed(self):
        src_id = self._source_combo.currentData()
        if not src_id:
            return
        self._source_items = {it["type_id"]: it for it in get_items(src_id)}
        self._source_stock = get_hangar_stock(src_id)
        self._target_stock = get_hangar_stock(self._target_hangar_id)
        self._populate_rows()

    # ── 表格填充 ──

    def _populate_rows(self):
        matched = [r for r in self._parsed if r.get("type_id")]
        unmatched = [r for r in self._parsed if not r.get("type_id")]
        transfers = compute_transfer_rows(matched, self._source_stock, self._target_stock)

        self._table.setRowCount(0)
        self._table.setRowCount(len(matched) + len(unmatched))
        self._updating = True
        row = 0
        for r, t in zip(matched, transfers, strict=True):
            self._fill_matched_row(row, r, t)
            row += 1
        for r in unmatched:
            self._fill_unmatched_row(row, r)
            row += 1
        self._updating = False

        # 自适应列宽
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(self._COL_CHECK, 28)
        self._table.setColumnWidth(self._COL_ICON, 28)
        for col, min_w in [
            (self._COL_NAME, 140),
            (self._COL_CLIP, 70),
            (self._COL_SRC, 70),
            (self._COL_MOVE, 70),
            (self._COL_COST, 80),
            (self._COL_TARGET, 70),
        ]:
            if self._table.columnWidth(col) < min_w:
                self._table.setColumnWidth(col, min_w)

        self._update_summary()

    def _fill_matched_row(self, row: int, r: dict, t: dict):
        """已匹配行：勾选 + 图标 + 名称 + 剪贴板/源库/移动数量/成本/目标"""
        type_id = t["type_id"]

        cb = QCheckBox()
        cb.setChecked(True)
        cb_w = QWidget()
        cb_l = QHBoxLayout(cb_w)
        cb_l.setContentsMargins(0, 0, 0, 0)
        cb_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cb_l.addWidget(cb)
        cb.toggled.connect(lambda: self._update_summary())
        self._table.setCellWidget(row, self._COL_CHECK, cb_w)

        icon_label = QLabel()
        icon_label.setFixedSize(24, 24)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = load_item_icon(type_id, size=24)
        if pix:
            icon_label.setPixmap(pix)
        self._table.setCellWidget(row, self._COL_ICON, icon_label)

        name = r.get("zh_name") or r.get("en_name") or r.get("raw_name") or f"ID:{type_id}"
        name_item = QTableWidgetItem(name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name_item.setData(Qt.ItemDataRole.UserRole, type_id)
        if t["capped"]:
            name_item.setText(f"{name}（源库不足）")
            name_item.setForeground(QColor(theme.ACCENT_ORANGE))
        self._table.setItem(row, self._COL_NAME, name_item)

        self._table.setItem(row, self._COL_CLIP, self._right_item(f"{t['clipboard_qty']:,}"))
        self._table.setItem(row, self._COL_SRC, self._right_item(f"{t['source_avail']:,}"))

        move_spin = QSpinBox()
        move_spin.setRange(0, max(t["source_avail"], 0))
        move_spin.setValue(t["move_qty"])
        move_spin.valueChanged.connect(lambda: self._update_summary())
        self._table.setCellWidget(row, self._COL_MOVE, move_spin)

        cost = self._source_items.get(type_id, {}).get("cost_price") or 0
        self._table.setItem(row, self._COL_COST, self._right_item(f"{cost:,.2f}"))
        self._table.setItem(row, self._COL_TARGET, self._right_item(f"{t['target_avail']:,}"))

    def _fill_unmatched_row(self, row: int, r: dict):
        """未匹配行：灰显、勾选禁用，右键可搜索匹配"""
        raw = r.get("raw_name") or "?"
        name_item = QTableWidgetItem(f"{raw}（未匹配）")
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name_item.setData(Qt.ItemDataRole.UserRole, None)
        name_item.setForeground(QColor(theme.TEXT_SECONDARY))
        self._table.setItem(row, self._COL_NAME, name_item)
        for col in (self._COL_CLIP, self._COL_SRC, self._COL_COST, self._COL_TARGET):
            item = QTableWidgetItem("-")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setForeground(QColor(theme.TEXT_SECONDARY))
            self._table.setItem(row, col, item)

    @staticmethod
    def _right_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return item

    # ── 右键菜单 ──

    def _selected_rows(self) -> list[int]:
        return sorted({idx.row() for idx in self._table.selectionModel().selectedRows()})

    def _on_context_menu(self, pos):
        rows = self._selected_rows()
        idx = self._table.indexAt(pos)
        if idx.isValid() and idx.row() not in rows:
            rows = [idx.row()]
        if not rows:
            return

        menu = QMenu(self)
        match_action = None
        if len(rows) == 1:
            name_item = self._table.item(rows[0], self._COL_NAME)
            if name_item and name_item.data(Qt.ItemDataRole.UserRole) is None:
                match_action = menu.addAction("搜索匹配物品…")
        del_action = menu.addAction(f"删除选中行 ({len(rows)})" if len(rows) > 1 else "删除该行")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if match_action is not None and action == match_action:
            self._search_match(rows[0])
        elif action == del_action:
            for r in reversed(rows):
                if r < len(self._parsed):
                    del self._parsed[r]
            self._populate_rows()

    def _search_match(self, row: int):
        """把未匹配行接到用户搜索选中的物品，然后重填（纳入移库计划）"""
        dlg = ItemSearchDialog(self, title="搜索匹配物品")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sel = dlg.selected_item()
        if not sel:
            return
        # 表格行号 = _parsed 下标（matched 在前、unmatched 在后，顺序一致）
        if not (0 <= row < len(self._parsed)) or self._parsed[row].get("type_id"):
            return
        entry = self._parsed[row]
        entry.update(
            {
                "type_id": sel["type_id"],
                "zh_name": sel["zh_name"],
                "en_name": sel["en_name"],
                "status": "matched",
            }
        )
        self._on_source_changed()  # 重取源库存并重填

    # ── 统计与确认 ──

    def _update_summary(self):
        if self._updating:
            return
        checked = 0
        total_move = 0
        capped = 0
        unmatched = 0
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, self._COL_NAME)
            if not name_item:
                continue
            if name_item.data(Qt.ItemDataRole.UserRole) is None:
                unmatched += 1
                continue
            w = self._table.cellWidget(row, self._COL_CHECK)
            if not w:
                continue
            cb = w.findChild(QCheckBox)
            if not cb or not cb.isChecked():
                continue
            checked += 1
            spin = cast(QSpinBox | None, self._table.cellWidget(row, self._COL_MOVE))
            total_move += spin.value() if spin else 0
            if "（源库不足）" in name_item.text():
                capped += 1
        parts = [f"共 {self._table.rowCount()} 项"]
        if checked:
            parts.append(f"勾选 {checked} 项")
            parts.append(f"将移动 {total_move:,} 件")
        if capped:
            parts.append(f"源库不足 {capped} 项")
        if unmatched:
            parts.append(f"未匹配 {unmatched} 项")
        self._summary_label.setText(" / ".join(parts))

    def _on_accept(self):
        src_id = self._source_combo.currentData()
        if not src_id:
            QMessageBox.warning(self, "提示", "没有可用的来源机库")
            return
        moved = 0
        capped = 0
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, self._COL_NAME)
            if not name_item:
                continue
            type_id = name_item.data(Qt.ItemDataRole.UserRole)
            if not type_id:
                continue
            w = self._table.cellWidget(row, self._COL_CHECK)
            if not w:
                continue
            cb = w.findChild(QCheckBox)
            if not cb or not cb.isChecked():
                continue
            spin = cast(QSpinBox | None, self._table.cellWidget(row, self._COL_MOVE))
            qty = spin.value() if spin else 0
            if qty <= 0:
                continue
            actual = move_quantity(src_id, type_id, qty, self._target_hangar_id)
            moved += actual
            if "（源库不足）" in name_item.text():
                capped += 1
        if moved == 0:
            QMessageBox.warning(self, "提示", "没有可移动的物品")
            return
        self._result = {"moved": moved, "capped": capped}
        self.accept()

    def result_summary(self) -> dict:
        """返回 {"moved": 实际移动件数, "capped": 源库不足条目数}"""
        return self._result

    def _on_theme_changed(self):
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")

    def showEvent(self, event):
        super().showEvent(event)
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
