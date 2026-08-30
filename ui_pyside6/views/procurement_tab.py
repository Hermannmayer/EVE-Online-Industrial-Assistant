"""待采购对话框 - 根据生产计划和库存计算需要采购的材料"""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QCursor
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
    QToolTip,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from core.logger import log
from ui_pyside6.icon_cache import load_item_icon


def _resolve_item_name(mid: int | None, zh_name: str | None, en_name: str | None) -> str:
    """统一物品名解析：item 表 → terminology.json → str(id)"""
    if zh_name:
        return zh_name
    if en_name:
        return en_name
    if mid is None:
        return ""
    from services.terminology import term

    override = term.item_override(mid)
    if override:
        return override
    return str(mid)


def _display_name(r: dict) -> str:
    """行的显示名：与表格第 0 列 data() 同口径（zh → en → 术语覆盖 → id）。

    双击复制 / 整单复制 / 复制此行共用，避免覆盖物 id 行输出与界面不一致的裸 name。
    """
    mid: int | None = r.get("type_id")
    return _resolve_item_name(mid, r.get("zh_name"), r.get("en_name"))


def _split_sections(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """按 to_buy 拆分为 (需采购, 库存已备足) 分区。纯函数，便于单测。"""
    to_buy = [r for r in rows if r.get("to_buy", 0) > 0]
    done = [r for r in rows if r.get("to_buy", 0) <= 0]
    return to_buy, done


class ProcureTableModel(QAbstractTableModel):
    """待采购表格模型，含图标列"""

    _HEADERS = ["物品名称", "总需求", "库存", "需采购", "单价", "总价", "体积(m³)"]
    _SORT_FIELDS = ["name", "need", "owned", "to_buy", "price", "total", "volume"]

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
                    return _display_name(r)
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

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """按列排序并重映射持久索引，保证排序后 selection 仍指向同一行对象。

        若省略 changePersistentIndexList，layoutChanged 后选区会粘在旧行号，
        「删除此行/修改数量」将操作错行。
        """
        if not 0 <= column < len(self._SORT_FIELDS):
            return
        field = self._SORT_FIELDS[column]
        reverse = order == Qt.SortOrder.DescendingOrder
        old = list(self._rows)  # 排序前快照（对象引用），排序后旧行号即失效
        old_ps = self.persistentIndexList()
        self.layoutAboutToBeChanged.emit()
        if field == "name":
            self._rows.sort(key=lambda r: _display_name(r).casefold(), reverse=reverse)
        else:
            self._rows.sort(key=lambda r: r.get(field) or 0.0, reverse=reverse)
        new_pos = {id(r): i for i, r in enumerate(self._rows)}
        reloc = [new_pos[id(old[i])] for i in range(len(old))]
        new_ps = [self.index(reloc[pi.row()], pi.column()) for pi in old_ps]
        self.changePersistentIndexList(old_ps, new_ps)
        self.layoutChanged.emit()

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
            self.dataChanged.emit(self.index(row, 2), self.index(row, 5))  # type: ignore[call-arg]  # roles 可选，新版存根误判


class ProcurementDialog(QDialog):
    """待采购对话框 - 根据生产计划和库存计算需要采购的材料"""

    def __init__(self, active_plans, default_mat_hangar_id: int | None, hangar_label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"待采购 - 材料需求 ({hangar_label})")
        # 窄高窗口：方便一眼浏览全部待采购物品
        self.setMinimumSize(620, 400)
        self.resize(720, 800)

        self._active_plans = active_plans
        self._default_mat_hangar_id = default_mat_hangar_id
        self._rows: list[dict] = []
        self._price_type = "sell"
        self._sort_state: dict[int, tuple[int, Qt.SortOrder]] = {}

        self._build_ui()
        self._calculate()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)
        self._body_layout = main_layout

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

        self._add_to_hangar_btn = QPushButton("增量添加到仓库")
        self._add_to_hangar_btn.setToolTip(
            "读取剪贴板（游戏内复制已购材料 Ctrl+C），按增量累加的方式加入默认材料机库（只增不减）"
        )
        self._add_to_hangar_btn.clicked.connect(self._on_add_to_hangar)
        toolbar.addWidget(self._add_to_hangar_btn)

        self._complete_all_btn = QPushButton("完成所有")
        self._complete_all_btn.clicked.connect(self._on_complete_all)
        self._complete_all_btn.setVisible(False)
        toolbar.addWidget(self._complete_all_btn)

        main_layout.addLayout(toolbar)

        # 分区一：需采购（to_buy > 0），分区二：库存已备足（to_buy <= 0）
        self._buy_label = QLabel("")
        self._stock_label = QLabel("")
        self._buy_table = QTableView()
        self._stock_table = QTableView()
        for table in (self._buy_table, self._stock_table):
            self._style_table(table)
        main_layout.addWidget(self._buy_label)
        main_layout.addWidget(self._buy_table, 1)
        main_layout.addWidget(self._stock_label)
        main_layout.addWidget(self._stock_table, 1)

        # Summary bar
        summary_bar = QHBoxLayout()
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        summary_bar.addWidget(self._summary_label)
        summary_bar.addStretch()
        main_layout.addLayout(summary_bar)

    def _style_table(self, table: QTableView):
        """两表共用的表格样式 + 双击复制 + 表头排序 + 右键菜单。"""
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.verticalHeader().setDefaultSectionSize(28)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_context_menu)
        table.setSortingEnabled(True)
        table.doubleClicked.connect(self._on_row_double_click)
        table.horizontalHeader().sortIndicatorChanged.connect(
            lambda section, order, t=table: self._remember_sort(t, section, order)
        )

    def _remember_sort(self, table: QTableView, section: int, order: Qt.SortOrder):
        self._sort_state[id(table)] = (int(section), order)

    def _size_columns(self, table: QTableView):
        """Auto-size columns — 名称列 Stretch 占满，其余按内容，名称列最小 160px。"""
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        for i in range(header.count()):
            resize = QHeaderView.ResizeMode.Stretch if i == 0 else QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(i, resize)
        if header.sectionSize(0) < 160:
            header.resizeSection(0, 160)

    def _rebuild_sections(self):
        """按当前 rows 重建两个分区：设模型、显示/隐藏空分区、重放排序、更新汇总。"""
        buy_rows, stock_rows = _split_sections(self._rows)

        from services.terminology import term

        self._buy_label.setText(f"{term.label('procure_buy')}({len(buy_rows)})")
        self._stock_label.setText(f"{term.label('procure_stocked')}({len(stock_rows)})")

        self._buy_table.setModel(ProcureTableModel(buy_rows))
        self._stock_table.setModel(ProcureTableModel(stock_rows))
        self._size_columns(self._buy_table)
        self._size_columns(self._stock_table)

        self._buy_label.setVisible(bool(buy_rows))
        self._buy_table.setVisible(bool(buy_rows))
        self._stock_label.setVisible(bool(stock_rows))
        self._stock_table.setVisible(bool(stock_rows))

        # 纵向空间按行数比例分配（PySide6 的 setStretch 只接受布局槽位 index）
        self._body_layout.setStretch(self._body_layout.indexOf(self._buy_table), max(len(buy_rows), 1))
        self._body_layout.setStretch(self._body_layout.indexOf(self._stock_table), max(len(stock_rows), 1))

        for table in (self._buy_table, self._stock_table):
            state = self._sort_state.get(id(table))
            if state is not None:
                col, order = state
                table.horizontalHeader().setSortIndicator(col, order)

        self._update_summary()

    def _on_theme_changed(self):
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        self._buy_label.setStyleSheet(f"color: {theme.ACCENT_RED}; font-weight: 600;")
        self._stock_label.setStyleSheet(f"color: {theme.GREEN}; font-weight: 600;")

    def _on_price_type_changed(self):
        """价格类型或来源变更时重新计算"""
        self._calculate()

    def _calculate(self):
        """根据生产计划和库存计算需要采购的材料"""
        from core.container import get_container
        from services.plan_aggregator import aggregate_procurement

        self._rows = []
        price_type = "buy" if self._price_combo.currentText() == "买价" else "sell"
        hub = self._hub_combo.currentText()
        self._price_type = price_type
        self._hub_text = hub

        # 与状态栏「备料中采购」口径一致：仅统计未运行且已勾选备料的计划，
        # ready/running 计划材料已扣库存，计入会虚高。
        proc_plans = [
            p for p in self._active_plans if p.get("materials_ready", 0) and (p.get("status") or "pending") == "pending"
        ]
        with get_container().db.connect("user", "ref", "bp", "mkt") as conn:
            rows, _cost, _vol = aggregate_procurement(
                conn,
                proc_plans,
                hangar_id=None,
                default_hangar_id=self._default_mat_hangar_id,
                region_id=TRADE_HUB_IDS.get(hub, 10000002),
                price_type=price_type,
            )
        self._rows = rows

        # 检查是否有「待下线」的计划，显示「完成所有」按钮
        ready_plans = [p for p in self._active_plans if p.get("status") == "ready"]
        if ready_plans:
            self._complete_all_btn.setText(f"完成所有 ({len(ready_plans)} 项)")
            self._complete_all_btn.setVisible(True)
        else:
            self._complete_all_btn.setVisible(False)

        if not self._rows:
            self._buy_table.setModel(None)
            self._stock_table.setModel(None)
            self._buy_label.setVisible(False)
            self._buy_table.setVisible(False)
            self._stock_label.setVisible(False)
            self._stock_table.setVisible(False)
            self._summary_label.setText("无活跃计划材料需求")
            return

        self._rebuild_sections()

    def _on_row_double_click(self, index: QModelIndex):
        """双击行 → 复制物品名（不含数量）到剪贴板，便于游戏内挂买单。"""
        model = index.model()
        if not isinstance(model, ProcureTableModel):
            return
        r = model.get_row(index.row())
        if not r:
            return
        name = _display_name(r)
        QApplication.clipboard().setText(name)
        QToolTip.showText(QCursor.pos(), f"已复制: {name}")

    def _on_context_menu(self, pos):
        table = self.sender()
        if not isinstance(table, QTableView):
            return
        sel = table.selectionModel().selectedRows()
        if not sel:
            return
        model = table.model()
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

        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == a_delete:
            self._on_delete_row(table, sel, model)
        elif action == a_edit_qty:
            self._on_edit_qty(table, sel, model)
        elif action == a_copy_qty:
            self._on_copy_qty(table, sel, model)
        elif action == a_copy_line:
            self._on_copy_line(table, sel, model)

    def _on_delete_row(self, table: QTableView, sel, model: ProcureTableModel):
        rows = sorted({r.row() for r in sel}, reverse=True)
        for row in rows:
            model.remove_row(row)
        self._update_summary()

    def _on_edit_qty(self, table: QTableView, sel, model: ProcureTableModel):
        item = model.get_row(sel[0].row())
        if not item:
            return
        qty, ok = QInputDialog.getDouble(
            self,
            "修改采购数量",
            f"输入新采购数量 ({_display_name(item)}):",
            value=item.get("to_buy", 0),
            minValue=0,
            maxValue=99999999,
            decimals=2,
        )
        if not ok:
            return
        old = item.get("to_buy", 0)
        model.update_qty(sel[0].row(), qty)
        # 跨分区边界（>0 ↔ <=0）时把行搬去另一分区；否则就地更新保持选区
        if (old > 0) != (qty > 0):
            self._rebuild_sections()
        else:
            self._update_summary()

    def _on_copy_qty(self, table: QTableView, sel, model: ProcureTableModel):
        item = model.get_row(sel[0].row())
        if item:
            qty = item.get("to_buy", 0)
            QApplication.clipboard().setText(str(int(qty) if qty == int(qty) else qty))
            QMessageBox.information(self, "已复制", f"数量 {qty:,.2f} 已复制到剪贴板")

    def _on_copy_line(self, table: QTableView, sel, model: ProcureTableModel):
        item = model.get_row(sel[0].row())
        if item:
            text = f"{_display_name(item)}\t{item['to_buy']:,.2f}\t{item['price']:,.2f}\t{item['total']:,.2f}"
            QApplication.clipboard().setText(text)

    def _on_copy_to_clipboard(self):
        """将需采购清单复制到剪贴板（格式：凡晶石*4）——只复制 to_buy>0 的需采购分区。"""
        model = self._buy_table.model()
        if not model or not isinstance(model, ProcureTableModel):
            return
        rows = model._rows
        if not rows:
            return

        lines = [f"{_display_name(r)}* {r.get('to_buy', 0):.0f}" for r in rows]

        QApplication.clipboard().setText("\n".join(lines))
        total_qty = sum(r.get("to_buy", 0) for r in rows)
        QMessageBox.information(self, "已复制", f"已复制 {len(rows)} 种材料（共 {total_qty:,.0f} 个）到剪贴板")

    def _on_add_to_hangar(self):
        """增量添加到仓库 — 读取剪贴板（游戏内复制已购材料），走仓库同款导入预览后增量入默认材料机库。"""
        from services.inventory_manager import get_default_mat_hangar_and_system, get_hangar_name
        from ui_pyside6.views.inventory.review_dialog import run_clipboard_import

        hid, _sys = get_default_mat_hangar_and_system()
        if not hid:
            QMessageBox.warning(self, "提示", "未设置默认材料机库，请先在设置中指定")
            return
        hangar_name = get_hangar_name(hid) or f"机库{hid}"
        run_clipboard_import(hid, hangar_name, self, mode="incremental")
        self._calculate()

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
        """更新底部统计（两分区汇总）"""
        all_rows: list[dict] = []
        for t in (self._buy_table, self._stock_table):
            m = t.model()
            if isinstance(m, ProcureTableModel):
                all_rows.extend(m._rows)
        total_cost = sum(r.get("total", 0) for r in all_rows)
        total_volume = sum(r.get("volume", 0) for r in all_rows)
        hub = getattr(self, "_hub_text", "Jita")
        price_type = self._price_type
        self._summary_label.setText(
            f"共 {len(all_rows)} 种材料 | 需采购总金额: {total_cost:,.0f} ISK | 总体积: {total_volume:,.2f} m\\u00b3"
            f" | 来源: {hub} ({price_type})"
        )
