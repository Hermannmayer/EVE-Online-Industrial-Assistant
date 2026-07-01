"""
贸易页面 — 价格监控 & 运输分析
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from core.container import get_container
from ui_pyside6.models.trade_models import TradeHubTableModel
from ui_pyside6.workers.trade_workers import CrossRegionPriceWorker, TradeScoreWorker, TransportWorker


class TradePage(QWidget):
    """市场贸易页"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        self.setObjectName("trade_page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 子标签
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("QTabWidget::pane { border: none; }")

        self._tabs.addTab(self._build_monitor_tab(), "价格监控")
        self._tabs.addTab(self._build_transport_tab(), "运输分析")

        # 主题监听测试目标
        self._monitor_placeholder = self._preview

        layout.addWidget(self._tabs)

        theme.add_theme_listener(self._on_theme_changed)

    # ═══════════════════════════════════════════
    #  主题切换
    # ═══════════════════════════════════════════

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式表"""
        self._tabs.setStyleSheet("QTabWidget::pane { border: none; }")

        self._search.setStyleSheet(
            f"QLineEdit {{ background-color: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 6px 10px; font-size: 13px; }}"
        )
        self._preview.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")

        self._hub_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)

        self._score_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)

        for lbl in self._score_labels.values():
            lbl.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")

        self._hub_status.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")

        # 运输分析 tab 主题
        self._t_search.setStyleSheet(
            f"QLineEdit {{ background-color: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 6px 10px; font-size: 13px; }}"
        )
        self._t_preview.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")

        self._t_config_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)
        self._t_result_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)
        for lbl in self._t_labels.values():
            lbl.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")

        # ═══════════════════════════════════════════
        #  Tab 0: 价格监控
        # ═══════════════════════════════════════════

        def save_state(self) -> dict:
            return {"tab_index": self._tabs.currentIndex()}

        def restore_state(self, data: dict) -> None:
            if data and 0 <= data.get("tab_index", 0) < self._tabs.count():
                self._tabs.setCurrentIndex(data["tab_index"])

    def _build_monitor_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 搜索栏 ──
        bar = QHBoxLayout()

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索物品名称（如 渡鸦级）→ 查看跨区域价差 → 贸易评分")
        self._search.textChanged.connect(self._on_search)
        bar.addWidget(self._search, 1)

        self._search_list = QListWidget()
        self._search_list.setMaximumHeight(160)
        self._search_list.setVisible(False)
        self._search_list.itemClicked.connect(self._on_search_click)

        self._analyze_btn = QPushButton("分析")
        self._analyze_btn.clicked.connect(self._on_analyze)
        self._analyze_btn.setEnabled(False)
        bar.addWidget(self._analyze_btn)

        layout.addLayout(bar)

        # 预览
        self._preview = QLabel("搜索物品 → 查看四大贸易中心价差 → 计算贸易评分")
        self._preview.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._preview)

        layout.addWidget(self._search_list)

        # ── 跨区域价差表 ──
        self._hub_group = QGroupBox("跨区域价格对比")
        self._hub_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)
        hg = QVBoxLayout(self._hub_group)
        hg.setSpacing(4)

        self._hub_table = QTableView()
        self._hub_table.setAlternatingRowColors(True)
        self._hub_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._hub_table.horizontalHeader().setStretchLastSection(True)
        self._hub_table.verticalHeader().setDefaultSectionSize(24)
        self._hub_table.setMaximumHeight(150)
        hg.addWidget(self._hub_table)

        self._hub_status = QLabel("")
        self._hub_status.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        hg.addWidget(self._hub_status)

        layout.addWidget(self._hub_group)

        # ── 贸易评分 ──
        self._build_score_group(layout)

        # ── 最佳贸易对 ──
        self._build_trade_pair(layout)

        layout.addStretch()
        return w

    def _build_score_group(self, layout):
        """贸易评分结果面板"""
        self._score_group = QGroupBox("贸易评分")
        self._score_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)
        self._score_group.setVisible(False)

        sv = QVBoxLayout(self._score_group)
        sv.setSpacing(6)

        # 配置栏
        cfg = QHBoxLayout()
        cfg.addWidget(QLabel("买入区域:"))
        self._buy_hub = QComboBox()
        self._buy_hub.addItems(list(TRADE_HUB_IDS.keys()))
        self._buy_hub.setCurrentText("Jita")
        cfg.addWidget(self._buy_hub)

        cfg.addWidget(QLabel("卖出区域:"))
        self._sell_hub = QComboBox()
        self._sell_hub.addItems(list(TRADE_HUB_IDS.keys()))
        self._sell_hub.setCurrentText("Amarr")
        cfg.addWidget(self._sell_hub)

        cfg.addWidget(QLabel("数量:"))
        self._trade_qty = QSpinBox()
        self._trade_qty.setRange(1, 1000000)
        self._trade_qty.setValue(1)
        cfg.addWidget(self._trade_qty)

        self._score_btn = QPushButton("计算贸易评分")
        self._score_btn.clicked.connect(self._on_trade_score)
        cfg.addWidget(self._score_btn)

        cfg.addStretch()
        sv.addLayout(cfg)

        # 评分卡片
        self._profit_grid = QFrame()
        grid = QGridLayout(self._profit_grid)
        grid.setSpacing(4)

        label_specs = [
            ("贸易评分:", "score"),
            ("买入成本:", "buy_cost"),
            ("卖出收入:", "sell_revenue"),
            ("毛利润:", "gross_profit"),
            ("利润率:", "margin_pct"),
            ("每m³利润:", "profit_per_m3"),
        ]
        self._score_labels = {}
        for i, (label, key) in enumerate(label_specs):
            row, col_pair = i % 3, i // 3
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
            val = QLabel("—")
            val.setObjectName(f"trade_{key}")
            val.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
            grid.addWidget(lbl, row, col_pair * 2)
            grid.addWidget(val, row, col_pair * 2 + 1)
            self._score_labels[key] = val

        sv.addWidget(self._profit_grid)

        layout.addWidget(self._score_group)

    def _build_trade_pair(self, layout):
        """最佳贸易对信息"""
        self._pair_group = QGroupBox("最优贸易路线")
        self._pair_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)
        self._pair_group.setVisible(False)

        pv = QVBoxLayout(self._pair_group)
        self._pair_label = QLabel("")
        self._pair_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
        self._pair_label.setWordWrap(True)
        pv.addWidget(self._pair_label)

        layout.addWidget(self._pair_group)

    # ═══════════════════════════════════════════
    #  Tab 1: 运输分析
    # ═══════════════════════════════════════════

    def _build_transport_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 搜索栏 ──
        tbar = QHBoxLayout()
        self._t_search = QLineEdit()
        self._t_search.setPlaceholderText("搜索物品名称 → 计算运费后净利润")
        self._t_search.textChanged.connect(self._on_t_search)
        tbar.addWidget(self._t_search, 1)

        self._t_search_list = QListWidget()
        self._t_search_list.setMaximumHeight(160)
        self._t_search_list.setVisible(False)
        self._t_search_list.itemClicked.connect(self._on_t_search_click)

        self._t_analyze_btn = QPushButton("分析运输")
        self._t_analyze_btn.clicked.connect(self._on_transport_analyze)
        self._t_analyze_btn.setEnabled(False)
        tbar.addWidget(self._t_analyze_btn)
        layout.addLayout(tbar)

        # 预览
        self._t_preview = QLabel("搜索物品 → 选择贸易中心 → 计算运输利润")
        self._t_preview.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._t_preview)

        layout.addWidget(self._t_search_list)

        # ── 配置区 ──
        self._t_config_group = QGroupBox("运输配置")
        self._t_config_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)
        cfg_layout = QGridLayout(self._t_config_group)
        cfg_layout.setSpacing(6)

        cfg_layout.addWidget(QLabel("买入区域:"), 0, 0)
        self._t_buy_hub = QComboBox()
        self._t_buy_hub.addItems(list(TRADE_HUB_IDS.keys()))
        self._t_buy_hub.setCurrentText("Jita")
        cfg_layout.addWidget(self._t_buy_hub, 0, 1)

        cfg_layout.addWidget(QLabel("卖出区域:"), 0, 2)
        self._t_sell_hub = QComboBox()
        self._t_sell_hub.addItems(list(TRADE_HUB_IDS.keys()))
        self._t_sell_hub.setCurrentText("Amarr")
        cfg_layout.addWidget(self._t_sell_hub, 0, 3)

        cfg_layout.addWidget(QLabel("数量:"), 0, 4)
        self._t_qty = QSpinBox()
        self._t_qty.setRange(1, 1000000)
        self._t_qty.setValue(100)
        cfg_layout.addWidget(self._t_qty, 0, 5)

        cfg_layout.addWidget(QLabel("运输模式:"), 1, 0)
        self._t_mode = QComboBox()
        self._t_mode.addItems(["公开货运", "自有运输"])
        cfg_layout.addWidget(self._t_mode, 1, 1)

        self._t_jumps_label = QLabel("跳跃数:")
        cfg_layout.addWidget(self._t_jumps_label, 1, 2)
        self._t_jumps = QSpinBox()
        self._t_jumps.setRange(1, 500)
        self._t_jumps.setValue(72)
        cfg_layout.addWidget(self._t_jumps, 1, 3)

        # 自动填充跳跃数
        self._t_buy_hub.currentTextChanged.connect(self._auto_update_jumps)
        self._t_sell_hub.currentTextChanged.connect(self._auto_update_jumps)

        self._t_calc_btn = QPushButton("计算运输利润")
        self._t_calc_btn.clicked.connect(self._on_transport_analyze)
        cfg_layout.addWidget(self._t_calc_btn, 1, 5)

        layout.addWidget(self._t_config_group)

        # ── 结果卡片 ──
        self._t_result_group = QGroupBox("运输利润分析")
        self._t_result_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 8px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; padding: 2px 8px; color: {theme.TEXT_SECONDARY}; }}
        """)
        self._t_result_group.setVisible(False)

        rv = QVBoxLayout(self._t_result_group)
        rv.setSpacing(4)

        self._t_result_grid = QFrame()
        grid = QGridLayout(self._t_result_grid)
        grid.setSpacing(4)

        t_label_specs = [
            ("买入成本:", "t_buy_cost"),
            ("卖出收入:", "t_sell_revenue"),
            ("运费:", "t_freight_cost"),
            ("经纪人费:", "t_broker_cost"),
            ("销售税:", "t_sales_tax"),
            ("净利润:", "t_net_profit"),
            ("利润率:", "t_margin_pct"),
            ("每m³利润:", "t_isk_per_m3"),
        ]
        self._t_labels = {}
        for i, (label, key) in enumerate(t_label_specs):
            row, col_pair = i % 4, i // 4
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
            val = QLabel("—")
            val.setObjectName(key)
            val.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
            grid.addWidget(lbl, row, col_pair * 2)
            grid.addWidget(val, row, col_pair * 2 + 1)
            self._t_labels[key] = val

        rv.addWidget(self._t_result_grid)
        layout.addWidget(self._t_result_group)

        layout.addStretch()
        return w

    def _auto_update_jumps(self):
        """根据买卖区域自动填充跳跃数"""
        src = self._t_buy_hub.currentText()
        dst = self._t_sell_hub.currentText()
        from services.logistics import get_distance_jumps

        j = get_distance_jumps(src, dst)
        if j is not None:
            self._t_jumps.setValue(j)
            self._t_jumps_label.setText("跳跃数 (自动):")
        else:
            self._t_jumps_label.setText("跳跃数:")

    # ═══════════════════════════════════════════
    #  运输分析搜索
    # ═══════════════════════════════════════════

    def _on_t_search(self, text: str):
        if not text.strip():
            self._t_search_list.setVisible(False)
            return
        from ui_pyside6.workers.industry_workers import SearchWorker

        w = SearchWorker(text.strip(), get_container().db, self)
        w.finished.connect(self._on_t_search_result)
        w.start()

    def _on_t_search_result(self, results: list):
        self._t_search_list.clear()
        if not results:
            self._t_search_list.addItem("无匹配")
            self._t_search_list.setVisible(True)
            return
        for r in results:
            name = r.get("zh_name") or r.get("en_name") or f"ID:{r['type_id']}"
            item = QListWidgetItem(f"[{r['type_id']}] {name}")
            item.setData(Qt.ItemDataRole.UserRole, r)
            self._t_search_list.addItem(item)
        self._t_search_list.setVisible(True)

    def _on_t_search_click(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        self._t_search_list.setVisible(False)
        name = data.get("zh_name") or data.get("en_name") or str(data["type_id"])
        self._t_search.setText(name)
        self._t_selected_tid = data["type_id"]
        self._t_selected_name = name
        self._t_preview.setText(f"已选: {name} — 点「分析运输」计算运费后利润")
        self._t_analyze_btn.setEnabled(True)
        self._t_result_group.setVisible(False)

    # ═══════════════════════════════════════════
    #  运输利润计算
    # ═══════════════════════════════════════════

    def _on_transport_analyze(self):
        if not hasattr(self, "_t_selected_tid"):
            self._t_preview.setText("请先搜索并选择一个物品")
            return

        self._t_preview.setText(f"正在计算 {self._t_selected_name} 运输利润...")
        self._t_result_group.setEnabled(False)

        use_public = self._t_mode.currentIndex() == 0
        w = TransportWorker(
            type_id=self._t_selected_tid,
            buy_hub=self._t_buy_hub.currentText(),
            sell_hub=self._t_sell_hub.currentText(),
            buy_price_type="buy",
            sell_price_type="sell",
            quantity=self._t_qty.value(),
            distance_jumps=self._t_jumps.value(),
            use_public_freight=use_public,
            parent=self,
        )
        w.finished.connect(self._on_transport_result)
        w.start()

    def _on_transport_result(self, result: dict):
        self._t_result_group.setEnabled(True)
        status = result.get("status", "")
        if status:
            self._t_preview.setText(f"{self._t_selected_name}: {status}")
            return

        buy_cost = result["buy_cost"]
        sell_revenue = result["sell_revenue"]
        freight = result["freight_cost"]
        broker = result["broker_cost"]
        tax = result["sales_tax"]
        net = result["net_profit"]
        margin = result["margin_pct"]
        isk_m3 = result["isk_per_m3"]

        profit_color = theme.GREEN if net > 0 else theme.RED

        self._t_labels["t_buy_cost"].setText(f"{buy_cost:,.0f} ISK")
        self._t_labels["t_sell_revenue"].setText(f"{sell_revenue:,.0f} ISK")
        self._t_labels["t_freight_cost"].setText(f"{freight:,.0f} ISK")
        self._t_labels["t_freight_cost"].setStyleSheet(f"color: {theme.RED}; font-size: 12px;")
        self._t_labels["t_broker_cost"].setText(f"{broker:,.0f} ISK")
        self._t_labels["t_sales_tax"].setText(f"{tax:,.0f} ISK")
        self._t_labels["t_net_profit"].setText(f"{net:,.0f} ISK")
        self._t_labels["t_net_profit"].setStyleSheet(f"color: {profit_color}; font-size: 12px; font-weight: bold;")
        self._t_labels["t_margin_pct"].setText(f"{margin:.1f}%")
        self._t_labels["t_margin_pct"].setStyleSheet(f"color: {profit_color}; font-size: 12px;")
        self._t_labels["t_isk_per_m3"].setText(f"{isk_m3:,.0f} ISK/m³")

        mode_text = "公开货运" if result.get("freight_mode") == "public_freight" else "自有运输"
        self._t_preview.setText(
            f"{self._t_selected_name} | {mode_text} | "
            f"运费: {freight:,.0f} ISK | 净利润: {net:,.0f} ISK | 利润率: {margin:.1f}%"
        )
        self._t_preview.setStyleSheet(f"color: {profit_color}; font-size: 12px;")

        self._t_result_group.setVisible(True)

    # ═══════════════════════════════════════════
    #  搜索
    # ═══════════════════════════════════════════

    def _on_search(self, text: str):
        if not text.strip():
            self._search_list.setVisible(False)
            return
        from ui_pyside6.workers.industry_workers import SearchWorker

        w = SearchWorker(text.strip(), get_container().db, self)
        w.finished.connect(self._on_search_result)
        w.start()

    def _on_search_result(self, results: list):
        self._search_list.clear()
        if not results:
            self._search_list.addItem("无匹配")
            self._search_list.setVisible(True)
            return
        for r in results:
            name = r.get("zh_name") or r.get("en_name") or f"ID:{r['type_id']}"
            item = QListWidgetItem(f"[{r['type_id']}] {name}")
            item.setData(Qt.ItemDataRole.UserRole, r)
            self._search_list.addItem(item)
        self._search_list.setVisible(True)

    def _on_search_click(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        self._search_list.setVisible(False)
        name = data.get("zh_name") or data.get("en_name") or str(data["type_id"])
        self._search.setText(name)
        self._selected_tid = data["type_id"]
        self._selected_name = name
        self._preview.setText(f"已选: {name} — 点「分析」查看跨区域价格")
        self._analyze_btn.setEnabled(True)
        self._score_group.setVisible(False)
        self._pair_group.setVisible(False)
        # 自动触发分析
        self._on_analyze()

    # ═══════════════════════════════════════════
    #  跨区域价格分析
    # ═══════════════════════════════════════════

    def _on_analyze(self):
        if not hasattr(self, "_selected_tid"):
            self._preview.setText("请先选一个物品")
            return

        self._preview.setText(f"正在获取 {self._selected_name} 跨区域价格...")
        self._hub_group.setEnabled(False)

        w = CrossRegionPriceWorker(self._selected_tid, get_container().db, self)
        w.finished.connect(self._on_cross_region_result)
        w.start()

    def _on_cross_region_result(self, rows: list):
        self._hub_group.setEnabled(True)

        if not rows:
            self._preview.setText(f"{self._selected_name}: 无价格数据")
            self._hub_table.setModel(None)
            return

        self._hub_table.setModel(TradeHubTableModel(rows))
        self._hub_data = rows

        # 找最佳买卖对
        best_profit = 0
        best_buy_hub = ""
        best_sell_hub = ""
        for buy_row in rows:
            for sell_row in rows:
                if buy_row["hub"] == sell_row["hub"]:
                    continue
                if buy_row["buy_price"] <= 0 or sell_row["sell_price"] <= 0:
                    continue
                diff = sell_row["sell_price"] - buy_row["buy_price"]
                if diff > best_profit:
                    best_profit = diff
                    best_buy_hub = buy_row["hub"]
                    best_sell_hub = sell_row["hub"]

        n_with_data = sum(1 for r in rows if r["sell_price"] > 0)
        self._hub_status.setText(f"已获取 {n_with_data}/4 个贸易中心的价格数据")

        # 计算跨区域价差
        spread_info = ""
        max_spread = 0
        max_pair = ""
        for buy_row in rows:
            for sell_row in rows:
                if buy_row["hub"] == sell_row["hub"]:
                    continue
                if buy_row["buy_price"] <= 0 or sell_row["sell_price"] <= 0:
                    continue
                s = sell_row["sell_price"] - buy_row["buy_price"]
                sp = s / buy_row["buy_price"] * 100 if buy_row["buy_price"] > 0 else 0
                if s > max_spread:
                    max_spread = s
                    max_pair = f"{buy_row['hub']} 买 → {sell_row['hub']} 卖 ({sp:.1f}%)"

        if max_spread > 0:
            spread_info = f"  |  最大价差: {max_pair}"

        self._preview.setText(f"{self._selected_name} | {n_with_data} 个区域有数据{spread_info}")
        self._preview.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")

        # 自动填充最佳买卖区域
        if best_buy_hub:
            self._buy_hub.setCurrentText(best_buy_hub)
        if best_sell_hub:
            self._sell_hub.setCurrentText(best_sell_hub)

        # 显示贸易评分组
        self._score_group.setVisible(True)
        self._on_trade_score()

    # ═══════════════════════════════════════════
    #  贸易评分
    # ═══════════════════════════════════════════

    def _on_trade_score(self):
        if not hasattr(self, "_selected_tid"):
            return

        self._preview.setText(f"正在计算 {self._selected_name} 贸易评分...")

        w = TradeScoreWorker(
            self._selected_tid,
            self._buy_hub.currentText(),
            self._sell_hub.currentText(),
            "buy",
            "sell",
            self._trade_qty.value(),
            self,
        )
        w.finished.connect(self._on_trade_score_result)
        w.start()

    def _on_trade_score_result(self, result: dict):
        status = result.get("status", "")
        if status:
            self._preview.setText(f"{self._selected_name}: {status}")
            return

        score = result.get("score", 0)
        buy_cost = result.get("buy_cost", 0)
        sell_revenue = result.get("sell_revenue", 0)
        gross_profit = result.get("gross_profit", 0)
        margin_pct = result.get("margin_pct", 0)
        profit_m3 = result.get("profit_per_m3", 0)

        profit_color = theme.GREEN if gross_profit > 0 else theme.RED

        self._score_labels["score"].setText(f"{score:.0f}/100")
        self._score_labels["score"].setStyleSheet(
            f"color: {theme.PRIMARY if score >= 50 else profit_color}; font-size: 14px; font-weight: bold;"
        )
        self._score_labels["buy_cost"].setText(f"{buy_cost:,.0f} ISK")
        self._score_labels["sell_revenue"].setText(f"{sell_revenue:,.0f} ISK")
        self._score_labels["gross_profit"].setText(f"{gross_profit:,.0f} ISK")
        self._score_labels["gross_profit"].setStyleSheet(f"color: {profit_color}; font-size: 12px; font-weight: bold;")
        self._score_labels["margin_pct"].setText(f"{margin_pct:.1f}%")
        self._score_labels["margin_pct"].setStyleSheet(f"color: {profit_color}; font-size: 12px;")
        self._score_labels["profit_per_m3"].setText(f"{profit_m3:,.0f} ISK/m³")

        self._preview.setText(
            f"{self._selected_name} | 评分: {score:.0f} | 利润: {gross_profit:,.0f} ISK | 利润率: {margin_pct:.1f}%"
        )
        self._preview.setStyleSheet(f"color: {profit_color}; font-size: 12px;")

        # 最佳贸易对
        if hasattr(self, "_hub_data") and self._hub_data:
            self._update_trade_pair()

    def _update_trade_pair(self):
        """计算并展示最优贸易路线"""
        rows = self._hub_data
        best_profit = 0
        best_buy = ""
        best_sell = ""
        buy_price_val = 0
        sell_price_val = 0

        for buy_row in rows:
            for sell_row in rows:
                if buy_row["hub"] == sell_row["hub"]:
                    continue
                if buy_row["buy_price"] <= 0 or sell_row["sell_price"] <= 0:
                    continue
                diff = sell_row["sell_price"] - buy_row["buy_price"]
                if diff > best_profit:
                    best_profit = diff
                    best_buy = buy_row["hub"]
                    best_sell = sell_row["hub"]
                    buy_price_val = buy_row["buy_price"]
                    sell_price_val = sell_row["sell_price"]

        if best_profit > 0:
            sp = best_profit / buy_price_val * 100 if buy_price_val > 0 else 0
            qty = self._trade_qty.value()
            total_profit = best_profit * qty
            self._pair_label.setText(
                f"最优路线: {best_buy} 买入 ({buy_price_val:,.0f} ISK) → {best_sell} 卖出 ({sell_price_val:,.0f} ISK)\n"
                f"单件利润: {best_profit:,.0f} ISK ({sp:.1f}%) | {qty} 件总利润: {total_profit:,.0f} ISK"
            )
            self._pair_group.setVisible(True)
        else:
            self._pair_group.setVisible(False)

    # ═══════════════════════════════════════════
    #  刷新
    # ═══════════════════════════════════════════

    def refresh_display(self):
        """刷新页面数据，更新状态栏"""
        if hasattr(self._main, "statusBar"):
            self._main.statusBar().showMessage("贸易分析")
