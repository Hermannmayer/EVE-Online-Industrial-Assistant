"""
合同市场页面 — 公开合同浏览 + 物品详情
"""

from PySide6.QtCore import (
    QModelIndex,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS, TRADE_HUBS
from core.container import get_container
from services.watchlist_manager import add_to_watchlist
from ui_pyside6.models.contract_models import (
    _CONTRACT_COLUMNS,
    _ITEM_COLUMNS,
    CONTRACT_STATUS_CN,
    CONTRACT_TYPE_CN,
    ContractFilterProxy,
    ContractItemTableModel,
    ContractTableModel,
)

# ═══════════════════════════════════════
#  后台 Worker
# ═══════════════════════════════════════


class ContractFetchWorker(QThread):
    """后台拉取公开合同数据"""

    finished_signal = Signal(bool, str)  # success, message

    def __init__(self, regions: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._regions = regions

    def run(self):
        try:
            from services.workers.getcontracts import run_contract_update

            run_contract_update(self._regions)
            self.finished_signal.emit(True, "合同数据更新完成")
        except Exception as ex:
            self.finished_signal.emit(False, str(ex))


class ContractLoadWorker(QThread):
    """后台从数据库加载合同列表"""

    finished_signal = Signal(list)  # list of contract dicts

    def __init__(self, region_id: int, contract_type: str, parent=None):
        super().__init__(parent)
        self._region_id = region_id
        self._contract_type = contract_type

    def run(self):
        try:
            with get_container().db.connect("mkt") as conn:
                c = conn.cursor()
                query = "SELECT * FROM public_contracts WHERE region_id = ?"
                params: list = [self._region_id]
                if self._contract_type != "all":
                    query += " AND type = ?"
                    params.append(self._contract_type)
                query += " ORDER BY date_issued DESC LIMIT 2000"
                c.execute(query, params)
                rows = c.fetchall()
                result = [dict(r) for r in rows]
                self.finished_signal.emit(result)
        except Exception:
            self.finished_signal.emit([])


class ContractItemsLoadWorker(QThread):
    """后台从数据库加载合同物品"""

    finished_signal = Signal(list)  # list of item dicts

    def __init__(self, contract_id: int, parent=None):
        super().__init__(parent)
        self._contract_id = contract_id

    def run(self):
        try:
            with get_container().db.connect("mkt", "ref") as conn:
                c = conn.cursor()
                c.execute(
                    """
                    SELECT ci.*, r.zh_name, r.en_name
                    FROM contract_items ci
                    LEFT JOIN ref.item r ON ci.type_id = r.type_id
                    WHERE ci.contract_id = ?
                    ORDER BY ci.record_id
                """,
                    (self._contract_id,),
                )
                rows = c.fetchall()
                result = [dict(r) for r in rows]
                self.finished_signal.emit(result)
        except Exception:
            self.finished_signal.emit([])


# ═══════════════════════════════════════
#  合同详情弹窗
# ═══════════════════════════════════════


class ContractDetailDialog(QDialog):
    """合同详情弹窗 — 显示合同信息 + 物品列表"""

    def __init__(self, contract: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"合同详情 — #{contract.get('contract_id', '')}")
        self.setMinimumSize(750, 500)
        self.setObjectName("contract_detail_dialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 合同基本信息
        info = contract
        title = info.get("title", "") or "无标题"
        type_cn = CONTRACT_TYPE_CN.get(info.get("type", ""), info.get("type", ""))
        status_cn = CONTRACT_STATUS_CN.get(info.get("status", ""), info.get("status", ""))

        header_text = f"#{info.get('contract_id', '')}  {title}"
        self._header = QLabel(header_text)
        self._header.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {theme.PRIMARY};")
        layout.addWidget(self._header)

        detail_text = (
            f"类型: {type_cn}  |  状态: {status_cn}  |  "
            f"价格: {info.get('price', 0):,.2f} ISK  |  "
            f"抵押: {info.get('collateral', 0):,.2f} ISK  |  "
            f"体积: {info.get('volume', 0):,.1f} m³  |  "
            f"运输天数: {info.get('days_completed', 0)}"
        )
        self._detail = QLabel(detail_text)
        self._detail.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._detail)

        dates_text = (
            f"签发: {info.get('date_issued', '—')}  |  "
            f"过期: {info.get('date_expired', '—')}  |  "
            f"起始站: {info.get('start_location_id', '—')}  |  "
            f"终点站: {info.get('end_location_id', '—')}  |  "
            f"企业合同: {'是' if info.get('for_corporation') else '否'}"
        )
        self._dates = QLabel(dates_text)
        self._dates.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._dates)

        # 物品列表
        items_label = QLabel("合同物品:")
        items_label.setStyleSheet(f"font-weight: bold; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(items_label)

        self._item_model = ContractItemTableModel()
        self._items_table = QTableView()
        self._items_table.setModel(self._item_model)
        self._items_table.setAlternatingRowColors(False)
        self._items_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._items_table.setSortingEnabled(True)
        self._items_table.verticalHeader().setVisible(False)
        header = self._items_table.horizontalHeader()
        header.setStretchLastSection(True)
        for i, (_, w) in enumerate(_ITEM_COLUMNS):
            header.resizeSection(i, w)
        layout.addWidget(self._items_table)

        self._items_worker: ContractItemsLoadWorker | None = None
        self._load_items(info.get("contract_id", 0))

    def _load_items(self, contract_id: int):
        self._items_worker = ContractItemsLoadWorker(contract_id, self)
        self._items_worker.finished_signal.connect(self._on_items_loaded)
        self._items_worker.start()

    def _on_items_loaded(self, items: list[dict]):
        self._item_model.set_rows(items)


# ═══════════════════════════════════════
#  主页面
# ═══════════════════════════════════════


class ContractPage(QWidget):
    """合同市场页面"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self.setObjectName("contract_page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 顶部工具栏 ──
        toolbar = QWidget()
        toolbar.setObjectName("contract_toolbar")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(12, 8, 12, 8)
        tb_layout.setSpacing(8)

        tb_layout.addWidget(QLabel("区域:"))
        self._region_combo = QComboBox()
        self._region_combo.addItems(TRADE_HUBS)
        self._region_combo.setFixedWidth(100)
        self._region_combo.currentTextChanged.connect(self._on_filter_changed)
        tb_layout.addWidget(self._region_combo)

        tb_layout.addWidget(QLabel("类型:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(["全部", "物品交换", "拍卖", "运输"])
        self._type_combo.setFixedWidth(100)
        self._type_combo.currentTextChanged.connect(self._on_filter_changed)
        tb_layout.addWidget(self._type_combo)

        tb_layout.addStretch()

        self._refresh_btn = QPushButton("↻ 刷新合同数据")
        self._refresh_btn.clicked.connect(self._on_refresh)
        tb_layout.addWidget(self._refresh_btn)

        self._count_label = QLabel("合同: —")
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        tb_layout.addWidget(self._count_label)

        layout.addWidget(toolbar)

        # ── 搜索过滤栏 ──
        filter_bar = QWidget()
        filter_bar.setObjectName("contract_filter_bar")
        fb_layout = QHBoxLayout(filter_bar)
        fb_layout.setContentsMargins(12, 4, 12, 4)
        fb_layout.setSpacing(8)

        # 物品名搜索
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 物品名搜索…")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setFixedWidth(200)
        self._search_input.textChanged.connect(self._on_filter_changed_client)
        fb_layout.addWidget(self._search_input)

        # 价格区间
        fb_layout.addWidget(QLabel("价格:"))
        self._price_min = QDoubleSpinBox()
        self._price_min.setPrefix("≥ ")
        self._price_min.setRange(0, 1e12)
        self._price_min.setDecimals(0)
        self._price_min.setSpecialValueText("无下限")
        self._price_min.valueChanged.connect(self._on_filter_changed_client)
        fb_layout.addWidget(self._price_min)

        fb_layout.addWidget(QLabel("~"))
        self._price_max = QDoubleSpinBox()
        self._price_max.setPrefix("≤ ")
        self._price_max.setRange(0, 1e12)
        self._price_max.setDecimals(0)
        self._price_max.setSpecialValueText("无上限")
        self._price_max.valueChanged.connect(self._on_filter_changed_client)
        fb_layout.addWidget(self._price_max)

        # 买卖类型
        fb_layout.addWidget(QLabel("买卖:"))
        self._buy_sell_combo = QComboBox()
        self._buy_sell_combo.addItems(["全部", "我要买", "我要卖"])
        self._buy_sell_combo.setFixedWidth(100)
        self._buy_sell_combo.currentTextChanged.connect(self._on_filter_changed_client)
        fb_layout.addWidget(self._buy_sell_combo)

        fb_layout.addStretch()

        layout.addWidget(filter_bar)

        # ── 进度条 ──
        self._progress = QProgressBar()
        self._progress.setFixedHeight(3)
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # ── 主体分割: 合同列表 (上) + 物品列表 (下) ──
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 上半区: 合同表格
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self._contract_model = ContractTableModel()
        self._contract_proxy = ContractFilterProxy(self)
        self._contract_proxy.setSourceModel(self._contract_model)

        self._contract_table = QTableView()
        self._contract_table.setModel(self._contract_proxy)
        self._contract_table.setAlternatingRowColors(True)
        self._contract_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._contract_table.setSortingEnabled(True)
        self._contract_table.verticalHeader().setVisible(False)
        self._contract_table.doubleClicked.connect(self._on_contract_double_click)
        self._contract_table.clicked.connect(self._on_contract_click)
        self._contract_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._contract_table.customContextMenuRequested.connect(self._on_contract_context_menu)

        c_header = self._contract_table.horizontalHeader()
        c_header.setStretchLastSection(True)
        for i, (_, w) in enumerate(_CONTRACT_COLUMNS):
            c_header.resizeSection(i, w)

        top_layout.addWidget(self._contract_table)
        splitter.addWidget(top_widget)

        # 下半区: 选中合同的物品
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        bottom_header = QLabel("  合同物品（点击上方合同查看）")
        bottom_header.setStyleSheet(
            f"padding: 6px 12px; font-weight: bold; color: {theme.TEXT_SECONDARY};"
            f" background-color: {theme.BG_SURFACE};"
        )
        bottom_layout.addWidget(bottom_header)

        self._item_model = ContractItemTableModel()
        self._item_table = QTableView()
        self._item_table.setModel(self._item_model)
        self._item_table.setAlternatingRowColors(True)
        self._item_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._item_table.verticalHeader().setVisible(False)

        i_header = self._item_table.horizontalHeader()
        i_header.setStretchLastSection(True)
        for i, (_, w) in enumerate(_ITEM_COLUMNS):
            i_header.resizeSection(i, w)

        bottom_layout.addWidget(self._item_table)
        splitter.addWidget(bottom_widget)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)

        # ── 状态 ──
        self._fetch_worker: ContractFetchWorker | None = None
        self._load_worker: ContractLoadWorker | None = None
        self._items_worker: ContractItemsLoadWorker | None = None

        theme.add_theme_listener(self._on_theme_changed)

    def _on_theme_changed(self):
        """主题切换后重建 inline stylesheet"""
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        # 查找并更新底部 header 样式
        for lbl in self.findChildren(QLabel):
            if "合同物品" in (lbl.text() or ""):
                lbl.setStyleSheet(
                    f"padding: 6px 12px; font-weight: bold; color: {theme.TEXT_SECONDARY};"
                    f" background-color: {theme.BG_SURFACE};"
                )

    def _on_filter_changed(self):
        """筛选条件变更"""
        self._load_contracts()

    def _on_refresh(self):
        """刷新合同数据"""
        if self._fetch_worker and self._fetch_worker.isRunning():
            self._count_label.setText("正在更新中...")
            return

        region = self._region_combo.currentText()
        self._progress.setVisible(True)
        self._count_label.setText("正在从 ESI 获取合同数据...")
        self._refresh_btn.setEnabled(False)

        self._fetch_worker = ContractFetchWorker([region], self)
        self._fetch_worker.finished_signal.connect(self._on_fetch_done)
        self._fetch_worker.start()

    def _on_fetch_done(self, success: bool, message: str):
        self._progress.setVisible(False)
        self._refresh_btn.setEnabled(True)
        if success:
            self._count_label.setText("合同数据已更新")
            self._load_contracts()
        else:
            self._count_label.setText(f"更新失败: {message}")

    def _load_contracts(self):
        """从数据库加载合同列表"""
        region_name = self._region_combo.currentText()
        rid = TRADE_HUB_IDS.get(region_name, 10000002)

        type_map = {"全部": "all", "物品交换": "item_exchange", "拍卖": "auction", "运输": "courier"}
        type_filter = type_map.get(self._type_combo.currentText(), "all")

        self._load_worker = ContractLoadWorker(rid, type_filter, self)
        self._load_worker.finished_signal.connect(self._on_contracts_loaded)
        self._load_worker.start()

    def _on_contracts_loaded(self, contracts: list[dict]):
        self._contract_model.set_rows(contracts)
        self._count_label.setText(f"合同: {len(contracts)} 条")
        # 清空物品列表
        self._item_model.set_rows([])

    def _on_contract_click(self, proxy_index: QModelIndex):
        """单击合同行 → 加载物品"""
        source_index = self._contract_proxy.mapToSource(proxy_index)
        row_data = self._contract_model.get_row(source_index.row())
        if row_data:
            self._load_items(row_data.get("contract_id", 0))

    def _on_contract_double_click(self, proxy_index: QModelIndex):
        """双击合同行 → 弹出详情"""
        source_index = self._contract_proxy.mapToSource(proxy_index)
        row_data = self._contract_model.get_row(source_index.row())
        if not row_data:
            return
        dlg = ContractDetailDialog(row_data, self)
        dlg.exec()

    def _load_items(self, contract_id: int):
        """加载合同物品"""
        if self._items_worker and self._items_worker.isRunning():
            return
        self._items_worker = ContractItemsLoadWorker(contract_id, self)
        self._items_worker.finished_signal.connect(self._on_items_loaded)
        self._items_worker.start()

    def _on_items_loaded(self, items: list[dict]):
        self._item_model.set_rows(items)

    # ═══════════════════════════════════════
    #  右键菜单
    # ═══════════════════════════════════════

    def _on_contract_context_menu(self, pos):
        """合同列表右键菜单"""
        proxy_index = self._contract_table.indexAt(pos)
        if not proxy_index.isValid():
            return
        source_index = self._contract_proxy.mapToSource(proxy_index)
        row_data = self._contract_model.get_row(source_index.row())
        if not row_data:
            return

        menu = QMenu(self)

        # 复制合同 ID
        contract_id = row_data.get("contract_id", "")
        copy_id = QAction(f"复制合同 ID: {contract_id}", self)
        copy_id.triggered.connect(lambda: self._copy_to_clipboard(str(contract_id)))
        menu.addAction(copy_id)

        # 复制物品列表
        copy_items = QAction("复制物品列表", self)
        copy_items.triggered.connect(lambda: self._copy_contract_items(row_data))
        menu.addAction(copy_items)

        menu.addSeparator()

        # 在新窗口查看
        view_detail = QAction("在新窗口查看", self)
        view_detail.triggered.connect(lambda: ContractDetailDialog(row_data, self).exec())
        menu.addAction(view_detail)

        menu.addSeparator()

        # 加入关注列表
        add_watch = QAction("⭐ 加入关注列表", self)
        add_watch.triggered.connect(lambda: self._add_contract_to_watchlist(row_data))
        menu.addAction(add_watch)

        # 查看物品详情
        view_items = QAction("📋 查看物品详情", self)
        view_items.triggered.connect(lambda: self._show_contract_item_detail(row_data))
        menu.addAction(view_items)

        menu.exec(self._contract_table.viewport().mapToGlobal(pos))

    def _copy_to_clipboard(self, text: str):
        QApplication.clipboard().setText(text)
        self._count_label.setText(f"已复制: {text}")

    def _copy_contract_items(self, contract: dict):
        """复制合同的所有物品到剪贴板"""
        # 从 item model 获取已加载的物品
        items = self._item_model._rows
        if not items:
            self._count_label.setText("请先点击合同加载物品列表")
            return
        lines = []
        for item in items:
            zh = item.get("zh_name", "") or ""
            en = item.get("en_name", "") or ""
            qty = item.get("quantity", 0)
            lines.append(f"{zh or en}\tx{qty}")
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        self._count_label.setText(f"已复制 {len(items)} 个物品到剪贴板")

    def _on_filter_changed_client(self):
        """客户端实时过滤（搜索框/价格/买卖类型变化时触发）"""
        self._contract_proxy.set_search_text(self._search_input.text())
        self._contract_proxy.set_price_range(self._price_min.value(), self._price_max.value())
        self._contract_proxy.set_buy_sell(self._buy_sell_combo.currentText())
        visible = self._contract_proxy.rowCount()
        total = self._contract_model.rowCount()
        self._count_label.setText(f"合同: {visible}/{total} 条")

    def _add_contract_to_watchlist(self, contract: dict) -> None:
        """将合同的物品加入关注列表"""
        items = self._item_model._rows
        if not items:
            QMessageBox.information(self, "提示", "请先点击合同加载物品列表")
            return
        region_id = contract.get("region_id", 10000002)
        added = 0
        for item in items:
            type_id = item.get("type_id", 0)
            if type_id:
                add_to_watchlist(type_id, region_id=region_id)
                added += 1
        QMessageBox.information(self, "关注列表", f"已添加 {added} 个物品到关注列表")

    def _show_contract_item_detail(self, contract: dict) -> None:
        """显示合同物品详情"""
        items = self._item_model._rows
        if not items:
            QMessageBox.information(self, "提示", "请先点击合同加载物品列表")
            return
        lines = []
        for item in items:
            zh = item.get("zh_name", "") or ""
            en = item.get("en_name", "") or ""
            qty = item.get("quantity", 0)
            name = zh or en or f"ID:{item.get('type_id', '?')}"
            lines.append(f"• {name}  x{qty}")
        text = "\n".join(lines)
        QMessageBox.information(
            self,
            f"合同 #{contract.get('contract_id', '')} 物品详情",
            text,
        )

    def refresh_display(self):
        """刷新页面数据，更新状态栏"""
        self._load_contracts()
        count = self._contract_model.rowCount()
        if hasattr(self._main, "statusBar"):
            self._main.statusBar().showMessage(
                f"合同市场: {count} 条合同 | "
                f"区域: {self._region_combo.currentText()} | "
                f"类型: {self._type_combo.currentText()}"
            )

    def save_state(self) -> dict:
        return {
            "region": self._region_combo.currentText(),
            "type": self._type_combo.currentText(),
            "search_text": self._search_input.text(),
        }

    def restore_state(self, data: dict) -> None:
        if not data:
            return
        for combo, key in [(self._region_combo, "region"), (self._type_combo, "type")]:
            val = data.get(key)
            if val:
                idx = combo.findText(val)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        if data.get("search_text"):
            self._search_input.setText(data["search_text"])
