"""
仓库页面 — 机库管理 Tab

包含 HangarTab（主视图）、EditQtyDialog、PasteImportDialog。
"""

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from core.eve_formulas import resolve_item_name
from services.inventory_manager import (
    add_item,
    get_hangars,
    get_item_price,
    get_items,
    move_items,
    remove_item,
    update_quantity,
)

from .inventory_helpers import InvTableModel

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
#  Dialog: 粘贴导入（简版）
# ════════════════════════════════════════════════════


class PasteImportDialog(QDialog):
    """粘贴导入 — 简易版本（支持单行输入）"""

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
                            "SELECT sell_price, buy_price FROM market_prices"
                            " WHERE type_id = ? AND region_id = 10000002 LIMIT 1",
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
#  Hangar Tab
# ════════════════════════════════════════════════════


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
                    if not qty_str:
                        continue
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
                # basic mineral fallback (from terminology.json item_overrides)
                if not type_id:
                    from services.terminology import term

                    term._ensure()
                    overrides = term._data.get("item_overrides") or {}
                    _mr = {v: k for k, v in overrides.items()}
                    type_id = int(_mr.get(name_clean, 0))
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
        from .review_dialog import ImportReviewDialog

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
