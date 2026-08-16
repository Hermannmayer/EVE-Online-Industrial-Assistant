"""待采购对话框 - 根据生产计划和库存计算需要采购的材料"""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
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
from core.logger import log
from ui_pyside6.icon_cache import load_item_icon


def _resolve_item_name(mid: int, zh_name: str | None, en_name: str | None) -> str:
    """统一物品名解析：item 表 → terminology.json → str(id)"""
    if zh_name:
        return zh_name
    if en_name:
        return en_name
    from services.terminology import term

    override = term.item_override(mid)
    if override:
        return override
    return str(mid)


class ProcureTableModel(QAbstractTableModel):
    """待采购表格模型，含图标列"""

    _HEADERS = ["物品名称", "总需求", "库存", "需采购", "单价", "总价", "体积(m³)"]

    def __init__(self, rows: list[dict]):
        super().__init__()
        self._rows = rows

    def rowCount(self, parent=None):
        return len(self._rows)

    def columnCount(self, parent=None):
        return len(self._HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        c = index.column()
        keys = ["name", "need", "owned", "to_buy", "price", "total", "volume"]

        # 图标（DecorationRole）— 第 0 列
        if role == Qt.ItemDataRole.DecorationRole and c == 0:
            return load_item_icon(r.get("type_id"), size=24)

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

        self._complete_all_btn = QPushButton("完成所有")
        self._complete_all_btn.clicked.connect(self._on_complete_all)
        self._complete_all_btn.setVisible(False)
        toolbar.addWidget(self._complete_all_btn)

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
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")

    def _on_price_type_changed(self):
        """价格类型或来源变更时重新计算"""
        self._calculate()

    def _calculate(self):
        """根据生产计划和库存计算需要采购的材料"""
        from services.procurement_service import calculate_procurement

        self._rows = []
        price_type = "buy" if self._price_combo.currentText() == "买价" else "sell"
        hub = self._hub_combo.currentText()

        rows, total_cost, total_volume = calculate_procurement(
            self._active_plans,
            hangar_id=self._hangar_id,
            hub=hub,
            price_type=price_type,
        )
        self._rows = rows
        if not self._rows:
            self._table.setModel(None)
            self._summary_label.setText("无活跃计划材料需求")
            return

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

        # 检查是否有「待下线」的计划，显示「完成所有」按钮
        ready_plans = [p for p in self._active_plans if p.get("status") == "ready"]
        if ready_plans:
            self._complete_all_btn.setText(f"完成所有 ({len(ready_plans)} 项)")
            self._complete_all_btn.setVisible(True)
        else:
            self._complete_all_btn.setVisible(False)

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
        """将待采购清单复制到剪贴板（格式：凡晶石*4）"""
        model = self._table.model()
        if not model or not isinstance(model, ProcureTableModel):
            return
        rows = model._rows
        if not rows:
            return

        lines = []
        for r in rows:
            name = r.get("name", "?")
            to_buy = r.get("to_buy", 0)
            lines.append(f"{name}* {to_buy:.0f}")

        QApplication.clipboard().setText("\n".join(lines))
        total_qty = sum(r.get("to_buy", 0) for r in rows)
        QMessageBox.information(self, "已复制", f"已复制 {len(rows)} 种材料（共 {total_qty:,.0f} 个）到剪贴板")

    def _on_complete_all(self):
        """一键完成所有待下线计划：标记为 completed + 自动入库（经 plan_execution.complete_plan）"""
        ready_plans = [p for p in self._active_plans if p.get("status") == "ready"]
        if not ready_plans:
            return

        from services import plan_execution

        completed = 0
        deposited = 0
        for plan in ready_plans:
            plan_id = plan.get("id")
            if not plan_id:
                continue
            try:
                res = plan_execution.complete_plan(plan)
                if res.get("ok"):
                    completed += 1
                    deposited += 1 if res.get("deposited") else 0
                else:
                    log.warning("完成计划 %s 失败: %s", plan_id, res.get("message"))
            except Exception:
                log.exception("完成计划 %s 失败", plan_id)

        if completed > 0:
            msg = f"已完成 {completed}/{len(ready_plans)} 项计划"
            if deposited > 0:
                msg += f"\n{deposited} 项成品已自动入库"
            QMessageBox.information(self, "完成", msg)
            self._calculate()
        else:
            QMessageBox.information(self, "提示", "没有可完成的计划")

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
