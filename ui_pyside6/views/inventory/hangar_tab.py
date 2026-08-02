"""
仓库页面 — 机库管理 Tab

包含 HangarTab（主视图）、EditQtyDialog、PasteImportDialog。
"""

import re
from typing import cast

from PySide6.QtCore import QAbstractTableModel, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.eve_formulas import resolve_item_name
from services.inventory_import import split_clipboard_lines
from services.inventory_manager import (
    add_item,
    get_hangars,
    get_item_price,
    get_items,
    move_items,
    remove_item,
    set_item_quantity,
    update_cost_price,
    update_quantity,
)
from services.name_resolver import search_item_type_id

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
#  Dialog: 批量设置成本价
# ════════════════════════════════════════════════════


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


# ════════════════════════════════════════════════════
#  Dialog: 手动添加物品
# ════════════════════════════════════════════════════


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
        results: list[dict] = []
        like = f"%{text}%"
        with get_container().db.connect("ref") as conn:
            c = conn.cursor()
            c.execute(
                "SELECT type_id, zh_name, en_name FROM item "
                "WHERE (zh_name LIKE ? OR en_name LIKE ?) "
                "ORDER BY CASE WHEN en_name=? OR zh_name=? THEN 0 ELSE 1 END, "
                "LENGTH(en_name), type_id LIMIT 20",
                (like, like, text, text),
            )
            results = [{"type_id": r[0], "zh_name": r[1] or "", "en_name": r[2] or ""} for r in c.fetchall()]
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
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)

        self._model: InvTableModel | None = None
        self._refresh()
        self._apply_header_style()

    def _build_action_bar(self, layout):
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self._adjust_btn = QPushButton("库存修正")
        self._adjust_btn.clicked.connect(self._on_adjust_inventory)
        bar.addWidget(self._adjust_btn)

        self._transfer_btn = QPushButton("移库")
        self._transfer_btn.clicked.connect(self._on_transfer)
        bar.addWidget(self._transfer_btn)

        self._cov_btn = QPushButton("查看规划缺失材料")
        self._cov_btn.clicked.connect(self._on_material_coverage)
        bar.addWidget(self._cov_btn)

        self._add_btn = QPushButton("手动添加物品")
        self._add_btn.clicked.connect(self._on_add_item)
        bar.addWidget(self._add_btn)

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
        self._apply_header_style()

    # ── 列布局 ──

    def _apply_column_layout(self):
        """列宽自适应：图标列 Fixed，其余内容自适应 + 最小宽度兜底 + 名称列上限。

        顺序仿工业制造 PlanTable：全部 ResizeToContents → resizeColumnsToContents
        → 再 re-fix 图标列（resize 会无视 Fixed 重置宽度，顺序不能反）。
        """
        if self._model is None:
            return
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(24)
        ncols = len(InvTableModel._HEADERS)
        for col in range(ncols):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.resizeColumnsToContents()
        # 图标列收紧
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 36)
        # 名称列：最小 120，最大不超过可用宽度一半，允许手动调整
        avail = max(header.width(), 800)
        name_w = min(max(header.sectionSize(1), 120), avail // 2)
        header.resizeSection(1, name_w)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        # 其余数字列最小宽度兜底（内容过窄时）
        for col, min_w in {2: 70, 3: 90, 4: 70, 5: 70, 6: 100, 7: 100}.items():
            if header.sectionSize(col) < min_w:
                header.resizeSection(col, min_w)

    def _apply_header_style(self):
        """表头紧凑 QSS（仿工业制造 PlanTable），避免「图标」等短表头撑宽列。

        作用在 horizontalHeader 上，不覆盖整表主题样式。
        """
        self._table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{ background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f" border: 1px solid {theme.BORDER}; padding: 2px 4px; font-size: 11px; }}"
        )

    # ── 剪贴板导入 ──

    def _parse_clipboard(self, raw: str) -> list[dict]:
        """解析 EVE 剪贴板 → list[{type_id|None, raw_name, zh_name, en_name, qty, status}]

        名称匹配走 search_item_type_id（精确 → 模糊 → 引号归一化 → terminology 反向）；
        未命中 item 的行保留为 status='unmatched'（type_id=None），供弹窗手动映射。
        """
        rows: list[dict] = []
        with get_container().db.connect("ref") as conn:
            for entry in split_clipboard_lines(raw):
                name = entry["name"]
                type_id = search_item_type_id(conn, name)
                if type_id:
                    nm = resolve_item_name(conn, type_id)
                    rows.append(
                        {
                            "type_id": type_id,
                            "raw_name": name,
                            "zh_name": nm if not nm.isdigit() else name,
                            "en_name": "" if nm.isdigit() else nm,
                            "qty": entry["qty"],
                            "status": "matched",
                        }
                    )
                else:
                    rows.append(
                        {
                            "type_id": None,
                            "raw_name": name,
                            "zh_name": "",
                            "en_name": "",
                            "qty": entry["qty"],
                            "status": "unmatched",
                        }
                    )
        return rows

    def _on_adjust_inventory(self):
        """库存修正 — 游戏全选复制 → 比对剪贴板与库存 → 逐物品确认增减/成本/是否变更。"""
        from services.inventory_import import compute_import_diff

        from .review_dialog import ImportChangeDialog, ImportReviewDialog

        if not self._page.hangar_id():
            return
        hid = self._page.hangar_id()
        # 自动读取剪贴板
        raw = QApplication.clipboard().text().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "剪贴板为空，请先在游戏中复制物品（Ctrl+C）")
            return
        parsed = self._parse_clipboard(raw)
        if not parsed:
            return
        hangar_name = self._page._hangar_combo.currentText()
        # 导入前快照（数量+成本），供全量同步差异对比
        before_items = get_items(hid)
        before = {it["type_id"]: (it["quantity"], it.get("cost_price") or 0) for it in before_items}
        names_before = {it["type_id"]: self._item_name(it) for it in before_items}

        # 库存修正默认全量同步（以游戏剪贴板为权威覆盖）
        dlg = ImportReviewDialog(parsed, hangar_name, hid, self, default_mode="full")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_import_data()
        if not data:
            return
        mode = dlg.mode()
        added = 0
        moved = 0
        if mode == "full":
            # 全量同步：以剪贴板为权威覆盖（增/减/归零删除）；跨机库行保持移动语义
            targets = dlg.get_sync_targets()
            for type_id, _delta, price, src_hangar in data:
                if src_hangar is not None:
                    if self._move_from_hangar(src_hangar, type_id):
                        moved += 1
                    continue
                final_qty = targets.get(type_id)
                if final_qty is None:
                    continue
                if set_item_quantity(hid, type_id, final_qty, price):
                    added += 1
        else:
            # 增量累加：delta>0 累加；跨机库行移动
            for type_id, delta, price, src_hangar in data:
                if delta <= 0:
                    continue
                if src_hangar is not None:
                    if self._move_from_hangar(src_hangar, type_id):
                        moved += 1
                else:
                    rid = add_item(hid, type_id, delta, price)
                    if rid != -1:
                        added += 1
        self._refresh()
        # 导入后快照 → 差异对比 → 变动弹窗（原「成功导入 N 条」信息并入其中）
        after_items = get_items(hid)
        after = {it["type_id"]: (it["quantity"], it.get("cost_price") or 0) for it in after_items}
        names_after = {it["type_id"]: self._item_name(it) for it in after_items}
        type_ids = list(dict.fromkeys(list(before) + list(after)))
        names = {**names_before, **names_after}
        changes = compute_import_diff(before, after, names, type_ids)
        ImportChangeDialog(changes, added, moved, hangar_name, self).exec()

    def _on_transfer(self):
        """移库 — 游戏全选复制源机库 → 选择来源机库 → 按剪贴板数量移到当前机库。"""
        if not self._page.hangar_id():
            return
        raw = QApplication.clipboard().text().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "剪贴板为空，请先在游戏中复制物品（Ctrl+C）")
            return
        parsed = self._parse_clipboard(raw)
        if not parsed:
            return
        from .transfer_dialog import HangarTransferDialog

        dlg = HangarTransferDialog(
            parsed, self._page.hangar_id(), self._page._hangar_combo.currentText(), self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh()

    def _move_from_hangar(self, src_hangar: int, type_id: int) -> bool:
        """从源机库找到该物品并整体移动到当前机库，返回是否移动。"""
        src_item = next((it for it in get_items(src_hangar) if it["type_id"] == type_id), None)
        if src_item:
            move_items([src_item["id"]], self._page.hangar_id())
            return True
        return False

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

    def _selected_rows(self) -> list[int]:
        """当前选中行号（升序）"""
        return sorted({idx.row() for idx in self._table.selectionModel().selectedRows()})

    def _on_context_menu(self, pos):
        if not self._model:
            return
        # 多行选择：右键到选中区外则只操作该行
        rows = self._selected_rows()
        idx = self._table.indexAt(pos)
        if idx.isValid() and idx.row() not in rows:
            rows = [idx.row()]
        if not rows:
            return
        items = [self._model.item_at(r) for r in rows if self._model.item_at(r)]
        if not items:
            return
        n = len(items)

        menu = QMenu(self)

        # 编辑数量：仅单行生效（批量数量编辑语义不明确）
        if n == 1:
            edit_act = QAction("编辑数量", self)
            edit_act.triggered.connect(lambda: self._on_edit_qty(items[0]))
            menu.addAction(edit_act)

        # 批量编辑成本价：吉他卖价/买价/均价 × 折扣率，或手动输入数字
        cost_act = QAction("编辑成本价", self)
        cost_act.triggered.connect(lambda: self._on_edit_cost_batch(items))
        menu.addAction(cost_act)

        # 批量删除
        del_act = QAction(f"删除 ({n})" if n > 1 else "删除", self)
        del_act.triggered.connect(lambda: self._on_del_items(items))
        menu.addAction(del_act)

        # 批量移动到
        move_menu = menu.addMenu(f"移动到 ({n})" if n > 1 else "移动到")
        ids = [it["id"] for it in items]
        for h in get_hangars():
            if h["id"] != self._page.hangar_id():
                act = QAction(h["name"], self)
                act.triggered.connect(lambda checked, hid=h["id"], ids_=ids: self._on_move_batch(ids_, hid))
                move_menu.addAction(act)

        menu.addSeparator()
        # 复制名称 / type_id（多行时换行拼接）
        copy_name = QAction("复制名称", self)
        copy_name.triggered.connect(
            lambda: QApplication.instance().clipboard().setText("\n".join(self._item_name(it) for it in items))
        )
        menu.addAction(copy_name)

        copy_id = QAction("复制 type_id", self)
        copy_id.triggered.connect(
            lambda: QApplication.instance().clipboard().setText("\n".join(str(it["type_id"]) for it in items))
        )
        menu.addAction(copy_id)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    @staticmethod
    def _item_name(item: dict) -> str:
        """统一显示名：display_name（terminology 覆盖优先）→ zh → en → str(id)"""
        return item.get("display_name") or item.get("zh_name") or item.get("en_name") or str(item.get("type_id", ""))

    def _on_edit_qty(self, item: dict):
        dlg = EditQtyDialog(self._item_name(item), item["quantity"], self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            qty = dlg.quantity()
            if qty >= 0:
                update_quantity(item["id"], qty)
                self._refresh()

    def _on_del_item(self, item: dict):
        name = self._item_name(item)
        if (
            QMessageBox.question(
                self, "确认", f"删除 {name}？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            == QMessageBox.StandardButton.Yes
        ):
            remove_item(item["id"])
            self._refresh()

    def _on_edit_cost_batch(self, items: list[dict]):
        """批量设置成本价：吉他卖价/买价/均价 × 折扣率，或手动输入数字。"""
        dlg = BatchCostPriceDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        source = dlg.price_type()
        updated = 0
        skipped: list[str] = []
        if source == "manual":
            manual = dlg.manual_price()
            for it in items:
                update_cost_price(it["id"], manual)
                updated += 1
        else:
            discount = dlg.discount()
            prices = self._fetch_market_prices([it["type_id"] for it in items], source)
            for it in items:
                base = prices.get(it["type_id"])
                if base is None:
                    skipped.append(self._item_name(it))
                    continue
                update_cost_price(it["id"], round(base * discount, 2))
                updated += 1
        self._refresh()
        msg = f"已更新 {updated} 项成本价"
        if skipped:
            shown = "、".join(skipped[:3])
            if len(skipped) > 3:
                shown += " 等"
            msg += f"；{len(skipped)} 项无市场价未更新（{shown}）"
        QMessageBox.information(self, "完成", msg)

    def _fetch_market_prices(self, type_ids: list[int], price_type: str) -> dict[int, float]:
        """批量查询吉他(Jita)市场价格 {type_id: 卖价/买价/均价}。"""
        tids = list(dict.fromkeys(type_ids))
        if not tids:
            return {}
        result: dict[int, float] = {}
        placeholders = ",".join("?" * len(tids))
        with get_container().db.connect("mkt") as conn:
            c = conn.cursor()
            if price_type == "avg":
                c.execute(
                    f"SELECT type_id, sell_price, buy_price FROM market_prices"
                    f" WHERE type_id IN ({placeholders}) AND region_id = ?",
                    (*tids, TRADE_HUB_IDS["Jita"]),
                )
                for tid, sell, buy in c.fetchall():
                    if sell and buy:
                        result[tid] = (sell + buy) / 2
                    elif sell or buy:
                        result[tid] = sell or buy
            else:
                col = "sell_price" if price_type == "sell" else "buy_price"
                c.execute(
                    f"SELECT type_id, {col} FROM market_prices"
                    f" WHERE type_id IN ({placeholders}) AND region_id = ?",
                    (*tids, TRADE_HUB_IDS["Jita"]),
                )
                for tid, price in c.fetchall():
                    if price is not None:
                        result[tid] = float(price)
        return result

    def _on_del_items(self, items: list[dict]):
        """批量删除（含单行）"""
        if len(items) == 1:
            self._on_del_item(items[0])
            return
        names = "、".join(self._item_name(it) for it in items[:3])
        if len(items) > 3:
            names += f" 等 {len(items)} 项"
        if (
            QMessageBox.question(
                self, "确认", f"删除 {names}？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            == QMessageBox.StandardButton.Yes
        ):
            for it in items:
                remove_item(it["id"])
            self._refresh()

    def _on_move_batch(self, item_ids: list[int], target_id: int):
        """批量移动到目标机库"""
        move_items(item_ids, target_id)
        self._refresh()

    def _on_add_item(self):
        if not self._page.hangar_id():
            return
        hangar_name = self._page._hangar_combo.currentText()
        dlg = AddItemDialog(hangar_name, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data:
            return
        type_id, qty, cost = data
        rid = add_item(self._page.hangar_id(), type_id, qty, cost)
        if rid == -1:
            QMessageBox.warning(self, "提示", "添加失败")
            return
        self._refresh()

    def _on_material_coverage(self):
        if not self._page.hangar_id():
            return
        hangar_name = self._page._hangar_combo.currentText()
        from .material_coverage_dialog import MaterialCoverageDialog

        MaterialCoverageDialog(self._page.hangar_id(), hangar_name, self).exec()

    # ── 刷新 ──

    def _refresh(self):
        if not self._page.hangar_id():
            return
        items = get_items(self._page.hangar_id())
        self._model = InvTableModel(items)
        self._table.setModel(self._model)
        self._apply_column_layout()
        self._count_label.setText(f"共 {len(items)} 项")

        # 计算总价
        total = sum((it["quantity"] * (it.get("sell_price") or 0)) for it in items if it.get("sell_price"))
        self._total_label.setText(f"按卖单价格: {total:,.0f} ISK")
