"""待采购对话框 - 根据生产计划和库存计算需要采购的材料"""

import os

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QPixmap, QPixmapCache
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.eve_formulas import _MINERAL_NAMES
from core.paths import ICON_DIR


def _load_icon(type_id: int, size: int = 24) -> QPixmap | None:
    """加载物品图标（缓存）"""
    if not type_id:
        return None
    cache_key = f"procicon_{type_id}"
    pixmap = QPixmap(cache_key)
    if not pixmap.isNull():
        return pixmap
    path = os.path.join(ICON_DIR, f"{type_id}.png")
    if os.path.isfile(path):
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            QPixmapCache.insert(cache_key, pixmap)
            return pixmap
    return None


def _resolve_item_name(mid: int, zh_name: str | None, en_name: str | None) -> str:
    """统一物品名解析：item 表 → mineral 硬编码 → str(id)"""
    if zh_name:
        return zh_name
    if en_name:
        return en_name
    if mid in _MINERAL_NAMES:
        return _MINERAL_NAMES[mid]
    # 再试一次从 item 表查（矿物可能不在 ref.item 中但在 mineral 映射中）
    return str(mid)


class ProcureTableModel(QAbstractTableModel):
    """待采购表格模型，含图标列"""

    _HEADERS = ["物品名称", "总需求", "库存", "需采购", "单价", "总价", "体积(m³)"]

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
        keys = ["name", "need", "owned", "to_buy", "price", "total", "volume"]

        # 图标（DecorationRole）— 第 0 列
        if role == Qt.ItemDataRole.DecorationRole and c == 0:
            return _load_icon(r.get("type_id"))

        if role == Qt.ItemDataRole.DisplayRole:
            if c < len(keys):
                val = r.get(keys[c], "")
                if c == 0:
                    return _resolve_item_name(r.get("type_id"), r.get("zh_name"), r.get("en_name"))
                if isinstance(val, float):
                    if c in (2, 3):
                        return f"{val:,.0f}"  # 库存/需采购整数
                    if c in (4, 5):
                        return f"{val:,.2f}"  # 价格/总价
                    if c == 6:
                        return f"{val:,.2f}"  # 体积
                    return f"{val:.2f}"
                return str(val)
            return ""
        if role == Qt.ItemDataRole.ForegroundRole:
            if c == 3:
                v = r.get("to_buy", 0)
                return QColor(theme.ACCENT_RED) if v > 0 else QColor(theme.GREEN)
            if c == 5:
                v = r.get("total", 0)
                return QColor(theme.ACCENT_RED) if v > 0 else QColor(theme.TEXT_PRIMARY)
        if role == Qt.ItemDataRole.UserRole:
            return r
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section] if section < len(self._HEADERS) else ""
        return None

    def get_row(self, row: int) -> dict:
        return self._rows[row] if 0 <= row < len(self._rows) else {}

    def remove_row(self, row: int):
        if 0 <= row < len(self._rows):
            self.beginRemoveRows(QModelIndex(), row, row)
            self._rows.pop(row)
            self.endRemoveRows()

    def update_qty(self, row: int, to_buy: float):
        if 0 <= row < len(self._rows):
            self._rows[row]["to_buy"] = to_buy
            self._rows[row]["total"] = to_buy * self._rows[row]["price"]
            self.dataChanged.emit(self.index(row, 2), self.index(row, 5))


class ProcurementDialog(QDialog):
    """待采购对话框 - 根据生产计划和库存计算需要采购的材料"""

    def __init__(self, active_plans, hangar_id, hangar_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"待采购 - 材料需求 ({hangar_name})")
        # 窄高窗口：方便一眼浏览全部待采购物品
        self.setMinimumSize(620, 400)
        self.resize(720, 800)

        self._active_plans = active_plans
        self._hangar_id = hangar_id
        self._hangar_name = hangar_name
        self._rows: list[dict] = []
        self._price_type = "sell"

        self._build_ui()
        self._calculate()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        toolbar.addWidget(QLabel("价格类型:"))
        self._price_combo = QComboBox()
        self._price_combo.addItems(["卖价", "买价"])
        self._price_combo.currentTextChanged.connect(self._on_price_type_changed)
        toolbar.addWidget(self._price_combo)

        toolbar.addWidget(QLabel("来源:"))
        self._hub_combo = QComboBox()
        self._hub_combo.addItems(list(TRADE_HUB_IDS.keys()))
        self._hub_combo.setCurrentText("Jita")
        self._hub_combo.currentTextChanged.connect(self._on_price_type_changed)
        toolbar.addWidget(self._hub_combo)

        toolbar.addStretch()

        self._refresh_btn = QPushButton("刷新计算")
        self._refresh_btn.clicked.connect(self._calculate)
        toolbar.addWidget(self._refresh_btn)

        self._copy_btn = QPushButton("复制到剪贴板")
        self._copy_btn.clicked.connect(self._on_copy_to_clipboard)
        toolbar.addWidget(self._copy_btn)

        main_layout.addLayout(toolbar)

        # Table
        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSortingEnabled(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        main_layout.addWidget(self._table, 1)

        # Summary bar
        summary_bar = QHBoxLayout()
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        summary_bar.addWidget(self._summary_label)
        summary_bar.addStretch()
        main_layout.addLayout(summary_bar)

        # Calculate on build
        self._calculate()

    def _on_theme_changed(self):
        self.setStyleSheet(f"QDialog {{ background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; }}")
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")

    def _on_price_type_changed(self):
        """价格类型或来源变更时重新计算"""
        self._calculate()

    def _calculate(self):
        """根据生产计划和库存计算需要采购的材料"""
        self._rows = []
        price_type = "buy" if self._price_combo.currentText() == "买价" else "sell"
        hub = self._hub_combo.currentText()
        region_id = TRADE_HUB_IDS.get(hub, 10000002)

        # Get material requirements from all active plans
        material_map: dict[int, dict] = {}
        with get_container().db.connect("user", "ref", "mkt", "bp") as conn:
            c = conn.cursor()
            for plan in self._active_plans:
                pid = plan["product_type_id"]
                runs = plan["runs"] * plan["parallels"]
                me = plan["me_level"]
                waste = 1.0 + 0.1 * (1.0 - me / 10.0)

                c.execute(
                    """SELECT bm.material_type_id, bm.quantity
                    FROM bp.blueprint_products bp
                    JOIN bp.blueprint_materials bm ON bm.blueprint_type_id = bp.blueprint_type_id
                        AND bm.activity = bp.activity
                    WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing'""",
                    (pid,),
                )
                for mid, qty in c.fetchall():
                    need = round(qty * waste * runs, 2)
                    if mid in material_map:
                        material_map[mid]["need"] += need
                    else:
                        material_map[mid] = {"need": need}

            if not material_map:
                self._table.setModel(None)
                self._summary_label.setText("无活跃计划材料需求")
                return

            # Get inventory from the selected hangar
            inv_map: dict[int, float] = {}
            c.execute(
                "SELECT type_id, quantity FROM inventory_items WHERE hangar_id = ?",
                (self._hangar_id,),
            )
            for tid, qty in c.fetchall():
                inv_map[tid] = qty

            # Build rows
            total_cost = 0.0
            total_volume = 0.0
            for mid, info in material_map.items():
                need = info["need"]
                owned = inv_map.get(mid, 0)
                to_buy = max(0, need - owned)

                # Get item info
                c.execute(
                    "SELECT zh_name, en_name, volume FROM ref.item WHERE type_id = ?",
                    (mid,),
                )
                r = c.fetchone()
                zh_name = r[0] if r else None
                en_name = r[1] if r else None
                name = _resolve_item_name(mid, zh_name, en_name)
                volume = r[2] if r and r[2] else 0.01

                # Get price
                c.execute(
                    f"SELECT {price_type + '_price'} FROM mkt.market_prices "
                    "WHERE type_id = ? AND region_id = ? LIMIT 1",
                    (mid, region_id),
                )
                pr = c.fetchone()
                price = pr[0] if pr and pr[0] else 0.0

                subtotal = to_buy * price
                total_cost += subtotal
                total_volume += to_buy * volume

                if to_buy > 0 or True:
                    self._rows.append(
                        {
                            "type_id": mid,
                            "name": name,
                            "zh_name": zh_name,
                            "en_name": en_name,
                            "need": need,
                            "owned": owned,
                            "to_buy": to_buy,
                            "price": price,
                            "total": subtotal,
                            "volume": to_buy * volume,
                        }
                    )

            self._rows.sort(key=lambda x: x["total"], reverse=True)
            self._table.setModel(ProcureTableModel(self._rows))

            # Auto-size columns — 自适应列宽
            header = self._table.horizontalHeader()
            header.setStretchLastSection(False)
            # 名称列 stretch，体积列按内容
            for i in range(header.count()):
                if i == 0:  # 物品名称含图标 → stretch
                    header.setSectionResizeMode(i, QHeaderView.Stretch)
                elif i == 6:  # 体积
                    header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
                else:
                    header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
            # 确保名称列最小 160px
            if header.sectionSize(0) < 160:
                header.resizeSection(0, 160)

            self._summary_label.setText(
                f"共 {len(self._rows)} 种材料 | "
                f"需采购总金额: {total_cost:,.0f} ISK | "
                f"总体积: {total_volume:,.2f} m\\u00b3 | "
                f"来源: {hub} ({price_type})"
            )

    def _on_context_menu(self, pos):
        sel = self._table.selectionModel().selectedRows()
        if not sel:
            return
        model = self._table.model()
        if not isinstance(model, ProcureTableModel):
            return

        item = model.get_row(sel[0].row())
        if not item:
            return

        menu = QMenu(self)
        menu.setObjectName("procure_context")

        a_delete = menu.addAction("删除此行")
        a_edit_qty = menu.addAction("修改数量")
        a_copy_qty = menu.addAction("复制数量")
        menu.addSeparator()
        a_copy_line = menu.addAction("复制此行")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == a_delete:
            self._on_delete_row(sel, model)
        elif action == a_edit_qty:
            self._on_edit_qty(sel, model)
        elif action == a_copy_qty:
            self._on_copy_qty(sel, model)
        elif action == a_copy_line:
            self._on_copy_line(sel, model)

    def _on_delete_row(self, sel, model):
        rows = sorted({r.row() for r in sel}, reverse=True)
        for row in rows:
            model.remove_row(row)
        self._update_summary()

    def _on_edit_qty(self, sel, model):
        item = model.get_row(sel[0].row())
        if not item:
            return
        from PySide6.QtWidgets import QInputDialog
        qty, ok = QInputDialog.getDouble(
            self,
            "修改采购数量",
            f"输入新采购数量 ({item['name']}):",
            value=item.get("to_buy", 0),
            minValue=0,
            maxValue=99999999,
            decimals=2,
        )
        if ok:
            model.update_qty(sel[0].row(), qty)
            self._update_summary()

    def _on_copy_qty(self, sel, model):
        item = model.get_row(sel[0].row())
        if item:
            qty = item.get("to_buy", 0)
            QApplication.clipboard().setText(str(int(qty) if qty == int(qty) else qty))
            QMessageBox.information(self, "已复制", f"数量 {qty:,.2f} 已复制到剪贴板")

    def _on_copy_line(self, sel, model):
        item = model.get_row(sel[0].row())
        if item:
            text = f"{item['name']}\\t{item['to_buy']:,.2f}\\t{item['price']:,.2f}\\t{item['total']:,.2f}"
            QApplication.clipboard().setText(text)

    def _on_copy_to_clipboard(self):
        """将待采购清单复制到剪贴板"""
        model = self._table.model()
        if not model or not isinstance(model, ProcureTableModel):
            return
        rows = model._rows
        if not rows:
            return

        lines = ["物品名称\\t总需求\\t库存\\t需采购\\t单价\\t总价\\t体积(m\\u00b3)"]
        total_cost = 0.0
        total_volume = 0.0
        for r in rows:
            lines.append(
                f"{r['name']}\\t{r['need']:,.2f}\\t{r['owned']:,.0f}\\t"
                f"{r['to_buy']:,.2f}\\t{r['price']:,.2f}\\t{r['total']:,.2f}\\t{r['volume']:,.2f}"
            )
            total_cost += r["total"]
            total_volume += r["volume"]
        lines.append("")
        lines.append(f"合计\\t\\t\\t\\t\\t{total_cost:,.0f} ISK\\t{total_volume:,.2f} m\\u00b3")

        QApplication.clipboard().setText("\\n".join(lines))
        QMessageBox.information(self, "已复制", f"待采购清单 ({len(rows)} 项, {total_cost:,.0f} ISK) 已复制到剪贴板")

    def _update_summary(self):
        """更新底部统计"""
        model = self._table.model()
        if not model or not isinstance(model, ProcureTableModel):
            return
        rows = model._rows
        total_cost = sum(r.get("total", 0) for r in rows)
        total_volume = sum(r.get("volume", 0) for r in rows)
        self._summary_label.setText(
            f"共 {len(rows)} 种材料 | 需采购总金额: {total_cost:,.0f} ISK | 总体积: {total_volume:,.2f} m\\u00b3"
        )
