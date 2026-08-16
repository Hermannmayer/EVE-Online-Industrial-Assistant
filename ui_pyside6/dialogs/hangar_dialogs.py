"""机库页 — 对话框（编辑数量 / 批量成本价 / 手动添加 / 粘贴导入）"""

import re
from typing import cast

from PySide6.QtCore import QAbstractTableModel, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services.inventory_manager import get_item_price


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


class BatchCostPriceDialog(QDialog):
    """批量设置成本价 — 吉他卖价/买价/均价 × 折扣率，或手动输入数字。"""

    _PRICE_TYPES = [
        ("sell", "吉他卖价"),
        ("buy", "吉他买价"),
        ("avg", "吉他均价"),
        ("manual", "手动输入价格"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量设置成本价")
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        form = QFormLayout()
        self._source = QComboBox()
        for val, label in self._PRICE_TYPES:
            self._source.addItem(label, val)
        self._source.currentIndexChanged.connect(self._on_source_changed)
        form.addRow("价格来源:", self._source)

        self._discount = QDoubleSpinBox()
        self._discount.setRange(0.01, 1.0)
        self._discount.setDecimals(2)
        self._discount.setSingleStep(0.05)
        self._discount.setValue(0.9)
        self._discount.setSuffix(" 折")
        self._discount.setToolTip("市场价 × 折扣率")
        form.addRow("折扣率:", self._discount)

        self._manual = QDoubleSpinBox()
        self._manual.setRange(0, 1e12)
        self._manual.setDecimals(2)
        self._manual.setSingleStep(1000)
        form.addRow("价格 (ISK):", self._manual)

        layout.addLayout(form)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        btn.accepted.connect(self.accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        self._form = form
        theme.add_theme_listener(self._on_theme_changed)
        self._on_source_changed()

    def _on_source_changed(self):
        """切换价格来源：市场价显示折扣率，手动输入显示价格框"""
        is_manual = self._source.currentData() == "manual"
        d_label = self._form.labelForField(self._discount)
        if d_label:
            d_label.setVisible(not is_manual)
        self._discount.setVisible(not is_manual)
        m_label = self._form.labelForField(self._manual)
        if m_label:
            m_label.setVisible(is_manual)
        self._manual.setVisible(is_manual)

    def price_type(self) -> str:
        return cast(str, self._source.currentData())

    def discount(self) -> float:
        return float(self._discount.value())

    def manual_price(self) -> float:
        return float(self._manual.value())

    def _on_theme_changed(self):
        pass


class _SearchResultsModel(QAbstractTableModel):
    """物品搜索结果模型（type_id/中文/英文）"""

    _HEADERS = ["type_id", "中文", "英文"]

    def __init__(self, rows: list[dict]):
        super().__init__()
        self._rows = rows

    def rowCount(self, parent=None):
        return len(self._rows)

    def columnCount(self, parent=None):
        return 3

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return str(r["type_id"])
            if c == 1:
                return r.get("zh_name", "")
            if c == 2:
                return r.get("en_name", "")
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def row_at(self, row: int) -> dict | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None


class AddItemDialog(QDialog):
    """手动添加物品 — 搜索 item 表（含 terminology 基础矿物）选择后入库"""

    def __init__(self, hangar_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"添加物品 → {hangar_name}")
        self.setMinimumSize(560, 480)
        self._selected: dict | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("输入物品名称（中文/英文）...")
        self._search.setClearButtonEnabled(True)
        layout.addWidget(self._search)
        # 200ms 防抖：停止输入后再搜索
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._do_search)
        self._search.textChanged.connect(lambda: self._debounce.start())

        self._table = QTableView()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._search_model = _SearchResultsModel([])
        self._table.setModel(self._search_model)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_selected)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, w in {0: 70, 1: 180, 2: 180}.items():
            self._table.setColumnWidth(col, w)
        layout.addWidget(self._table, 1)

        form = QFormLayout()
        self._qty = QSpinBox()
        self._qty.setRange(1, 2_000_000_000)
        self._qty.setValue(1)
        form.addRow("数量:", self._qty)
        self._cost = QDoubleSpinBox()
        self._cost.setRange(0, 1e12)
        self._cost.setDecimals(2)
        self._cost.setValue(0)
        form.addRow("成本价 (ISK):", self._cost)
        layout.addLayout(form)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("添加")
        btn.accepted.connect(self._on_accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        theme.add_theme_listener(self._on_theme_changed)

    def _set_results(self, rows: list[dict]):
        """替换搜索结果模型并重连选中信号（每次 setModel 会新建 selectionModel）"""
        self._search_model = _SearchResultsModel(rows)
        self._table.setModel(self._search_model)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_selected)
        if rows:
            self._table.selectRow(0)

    def _do_search(self):
        text = self._search.text().strip()
        if not text:
            self._set_results([])
            return
        self._set_results(self._search_items(text))

    def _search_items(self, text: str) -> list[dict]:
        """名称→type_id：item 表模糊匹配 + terminology.item_overrides 反向匹配基础矿物"""
        results = get_container().item_repo.search_by_name(text, limit=20)
        # terminology.item_overrides 反向匹配（基础矿物 34-40 等不在 item 表，仅在此注册）
        from services.terminology import term

        term._ensure()
        overrides = term._data.get("item_overrides") or {}
        seen = {r["type_id"] for r in results}
        for tid_str, name in overrides.items():
            if text.lower() in str(name).lower() and int(tid_str) not in seen:
                results.append({"type_id": int(tid_str), "zh_name": name, "en_name": ""})
        return results

    def _on_row_selected(self, current, previous):
        if not current.isValid():
            return
        row = self._search_model.row_at(current.row())
        if not row:
            return
        self._selected = row
        price = get_item_price(row["type_id"])
        if price:
            self._cost.setValue(price)

    def _on_accept(self):
        if not self._selected:
            QMessageBox.warning(self, "提示", "请先在搜索结果中选择物品")
            return
        self.accept()

    def result_data(self) -> tuple[int, int, float] | None:
        if not self._selected:
            return None
        return (self._selected["type_id"], self._qty.value(), self._cost.value())

    def _on_theme_changed(self):
        self._table.viewport().update()

    def showEvent(self, event):
        super().showEvent(event)
        self._search.setFocus()


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
        for rb in (self._price_use_sell, self._price_use_buy, self._price_use_avg, self._price_use_disc):
            rb.toggled.connect(lambda checked, b=rb: self._on_price_toggle(b) if checked else None)

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
        item_repo = get_container().item_repo
        market_repo = get_container().market_repo
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
                item = item_repo.get_by_id(int(key))
                type_id = item["type_id"] if item else None
            else:
                item = item_repo.get_by_name(key)
                type_id = item["type_id"] if item else None
            if not type_id:
                errors.append(f"未找到物品: {key}")
                continue

            if price_source in ("sell", "disc"):
                price = get_item_price(type_id) or 0
                if price_source == "disc":
                    price *= discount
            elif price_source == "buy":
                price = market_repo.get_price_by_region(type_id, "buy", 10000002) or 0
            elif price_source == "avg":
                price = market_repo.get_price_by_region(type_id, "avg", 10000002) or 0
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
