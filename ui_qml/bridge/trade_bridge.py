"""贸易页 bridge —— QML 与既有 worker 之间的唯一通道。

对照的 Widgets 版是 `ui_pyside6/views/trade_view.py`（两个 Tab：跨区域价差/评分、运输利润）。

**计算全在既有 worker 里**（`CrossRegionPriceWorker` / `TradeScoreWorker` /
`TransportWorker`），本类只做三件事：转发请求、把结果整理成 QML 好渲染的形状、
维护选中与预览文案。

结果卡片以「字段列表」的形式给出（`scoreFields` / `transportFields`），
QML 用 Repeater 画 —— 比在 QML 里写十几个具名属性更好维护，
也便于把「哪一项标红加粗」这类规则留在 Python 侧（与 Widgets 版逐项对齐）。
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from core.container import get_container
from ui_qml.models.trade_qml_model import TradeHubQmlModel

__all__ = ["TradeBridge"]

_HUBS = list(TRADE_HUB_IDS.keys())
_MODES = ("公开货运", "自有运输")

#: 结果卡片里「值」的颜色语义
_GREEN = "ACCENT_GREEN"
_RED = "ACCENT_RED"
_PRIMARY = "PRIMARY"
_TEXT = "TEXT_PRIMARY"


def _token(name: str) -> str:
    return str(getattr(theme, name, "") or "")


def _field(label: str, value: str, token: str = _TEXT, strong: bool = False) -> dict:
    return {"label": label, "value": value, "color": _token(token), "strong": strong}


class TradeBridge(QObject):
    """贸易页的 QML 后端。"""

    searchChanged = Signal()  # 候选 / 选中 / 预览（Tab 1）
    hubChanged = Signal()  # 跨区域表 / 评分卡片 / 贸易对
    transportChanged = Signal()  # Tab 2 的全部状态

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell

        # ── Tab 1 ──
        self._search_text = ""
        self._results: list[dict] = []
        self._selected_tid: int | None = None
        self._selected_name = ""
        self._preview = "搜索物品 → 查看四大贸易中心价差 → 计算贸易评分"
        self._preview_token = _TEXT
        self._hub_model = TradeHubQmlModel()
        self._hub_rows: list[dict] = []
        self._hub_status = ""
        self._buy_hub_index = _HUBS.index("Jita")
        self._sell_hub_index = _HUBS.index("Amarr")
        self._quantity = 1
        self._score_visible = False
        self._score_fields: list[dict] = []
        self._pair_text = ""
        self._pair_visible = False

        # ── Tab 2 ──
        self._t_search_text = ""
        self._t_results: list[dict] = []
        self._t_selected_tid: int | None = None
        self._t_selected_name = ""
        self._t_preview = "搜索物品 → 选择贸易中心 → 计算运输利润"
        self._t_preview_token = _TEXT
        self._t_buy_hub_index = _HUBS.index("Jita")
        self._t_sell_hub_index = _HUBS.index("Amarr")
        self._t_quantity = 100
        self._t_mode_index = 0
        self._t_jumps = 72
        self._t_jumps_auto = False
        self._t_result_visible = False
        self._t_fields: list[dict] = []

        self._search_worker: QObject | None = None
        self._t_search_worker: QObject | None = None
        self._hub_worker: QObject | None = None
        self._score_worker: QObject | None = None
        self._transport_worker: QObject | None = None

        self._remove_theme_listener = theme.add_theme_listener(self._on_theme_changed)

    # ═══════════════════════════════════════════════════════════
    #  公共选项
    # ═══════════════════════════════════════════════════════════

    hubs = Property(list, lambda self: list(_HUBS), constant=True)
    modes = Property(list, lambda self: list(_MODES), constant=True)

    # ═══════════════════════════════════════════════════════════
    #  Tab 1：搜索与选中
    # ═══════════════════════════════════════════════════════════

    searchText = Property(str, lambda self: self._search_text, notify=searchChanged)
    results = Property(list, lambda self: self._results, notify=searchChanged)
    previewText = Property(str, lambda self: self._preview, notify=searchChanged)
    previewColor = Property(str, lambda self: _token(self._preview_token), notify=searchChanged)

    @Slot(str)
    def onSearchChanged(self, text: str) -> None:
        self._search_text = str(text)
        if not text.strip():
            self._results = []
            self.searchChanged.emit()
            return
        from ui_pyside6.workers.industry_workers import SearchWorker

        worker = SearchWorker(text.strip(), get_container().db, self)
        self._search_worker = worker
        worker.finished_signal.connect(self._on_search_result)
        worker.start()

    def _on_search_result(self, results: list) -> None:
        self._results = [
            {
                "typeId": int(r["type_id"]),
                "text": f"[{r['type_id']}] {r.get('zh_name') or r.get('en_name') or ''}",
                "name": r.get("zh_name") or r.get("en_name") or str(r["type_id"]),
            }
            for r in (results or [])
        ]
        self.searchChanged.emit()

    @Slot(int)
    def pickResult(self, index: int) -> None:
        """选中候选项：填回输入框、清掉上一次的评分与贸易对，并**自动触发**跨区域分析。"""
        if not 0 <= index < len(self._results):
            return
        item = self._results[index]
        self._selected_tid = int(item["typeId"])
        self._selected_name = str(item["name"])
        self._search_text = self._selected_name
        self._results = []
        self._preview = f"已选: {self._selected_name} — 点「分析」查看跨区域价格"
        self._preview_token = _TEXT
        self._score_visible = False
        self._pair_visible = False
        self.searchChanged.emit()
        self.hubChanged.emit()
        self.analyze()

    # ═══════════════════════════════════════════════════════════
    #  Tab 1：跨区域价格
    # ═══════════════════════════════════════════════════════════

    hubModel = Property(QObject, lambda self: self._hub_model, constant=True)
    hubStatus = Property(str, lambda self: self._hub_status, notify=hubChanged)

    hubColumns = Property(
        list,
        lambda self: [
            {"title": title, "width": width}
            for title, width in zip(self._hub_model._HEADERS, (120, 110, 110, 110, 80, 100), strict=True)
        ],
        constant=True,
    )

    @Slot()
    def analyze(self) -> None:
        if self._selected_tid is None:
            self._set_preview("请先选一个物品", _TEXT)
            return
        self._set_preview(f"正在获取 {self._selected_name} 跨区域价格...", _TEXT)

        from ui_pyside6.workers.trade_workers import CrossRegionPriceWorker

        worker = CrossRegionPriceWorker(self._selected_tid, get_container().db, self)
        self._hub_worker = worker
        worker.finished_signal.connect(self._on_cross_region_result)
        worker.start()

    def _on_cross_region_result(self, rows: list) -> None:
        if not rows:
            self._hub_model.set_rows([])
            self._hub_rows = []
            self._hub_status = ""
            self._set_preview(f"{self._selected_name}: 无价格数据", _TEXT)
            self.hubChanged.emit()
            return

        self._hub_model.set_rows(rows)
        self._hub_rows = rows

        n_with_data = sum(1 for r in rows if r.get("sell_price", 0) > 0)
        max_spread, max_pair = self._best_spread(rows)
        spread_info = f"  |  最大价差: {max_pair}" if max_spread > 0 else ""
        self._hub_status = f"已获取 {n_with_data}/4 个贸易中心的价格数据"
        self._set_preview(f"{self._selected_name} | {n_with_data} 个区域有数据{spread_info}", _TEXT)

        # 自动把买卖区域切到最优对（与 Widgets 版一致）
        best = self._best_pair(rows)
        if best is not None:
            self._buy_hub_index = _HUBS.index(best[0]) if best[0] in _HUBS else self._buy_hub_index
            self._sell_hub_index = _HUBS.index(best[1]) if best[1] in _HUBS else self._sell_hub_index

        self._score_visible = True
        self.hubChanged.emit()
        self.computeScore()

    @staticmethod
    def _best_pair(rows: list[dict]) -> tuple[str, str] | None:
        best_profit = 0
        best: tuple[str, str] | None = None
        for buy_row in rows:
            for sell_row in rows:
                if buy_row.get("hub") == sell_row.get("hub"):
                    continue
                if buy_row.get("buy_price", 0) <= 0 or sell_row.get("sell_price", 0) <= 0:
                    continue
                diff = sell_row["sell_price"] - buy_row["buy_price"]
                if diff > best_profit:
                    best_profit = diff
                    best = (str(buy_row["hub"]), str(sell_row["hub"]))
        return best

    @staticmethod
    def _best_spread(rows: list[dict]) -> tuple[float, str]:
        max_spread = 0.0
        max_pair = ""
        for buy_row in rows:
            for sell_row in rows:
                if buy_row.get("hub") == sell_row.get("hub"):
                    continue
                buy_price = buy_row.get("buy_price", 0)
                if buy_price <= 0 or sell_row.get("sell_price", 0) <= 0:
                    continue
                spread = sell_row["sell_price"] - buy_price
                if spread > max_spread:
                    max_spread = spread
                    pct = spread / buy_price * 100
                    max_pair = f"{buy_row['hub']} 买 → {sell_row['hub']} 卖 ({pct:.1f}%)"
        return max_spread, max_pair

    # ═══════════════════════════════════════════════════════════
    #  Tab 1：贸易评分
    # ═══════════════════════════════════════════════════════════

    buyHubIndex = Property(int, lambda self: self._buy_hub_index, notify=hubChanged)
    sellHubIndex = Property(int, lambda self: self._sell_hub_index, notify=hubChanged)
    quantity = Property(int, lambda self: self._quantity, notify=hubChanged)
    scoreVisible = Property(bool, lambda self: self._score_visible, notify=hubChanged)
    scoreFields = Property(list, lambda self: self._score_fields, notify=hubChanged)
    pairText = Property(str, lambda self: self._pair_text, notify=hubChanged)
    pairVisible = Property(bool, lambda self: self._pair_visible, notify=hubChanged)

    @Slot(int)
    def setBuyHubIndex(self, index: int) -> None:
        if 0 <= index < len(_HUBS) and index != self._buy_hub_index:
            self._buy_hub_index = index
            self.hubChanged.emit()

    @Slot(int)
    def setSellHubIndex(self, index: int) -> None:
        if 0 <= index < len(_HUBS) and index != self._sell_hub_index:
            self._sell_hub_index = index
            self.hubChanged.emit()

    @Slot(int)
    def setQuantity(self, value: int) -> None:
        value = max(1, min(1_000_000, int(value)))
        if value != self._quantity:
            self._quantity = value
            self.hubChanged.emit()

    @Slot()
    def computeScore(self) -> None:
        if self._selected_tid is None:
            return
        self._set_preview(f"正在计算 {self._selected_name} 贸易评分...", _TEXT)

        from ui_pyside6.workers.trade_workers import TradeScoreWorker

        worker = TradeScoreWorker(
            self._selected_tid,
            _HUBS[self._buy_hub_index],
            _HUBS[self._sell_hub_index],
            "buy",
            "sell",
            self._quantity,
            self,
        )
        self._score_worker = worker
        worker.finished_signal.connect(self._on_score_result)
        worker.start()

    def _on_score_result(self, result: dict) -> None:
        status = result.get("status", "")
        if status:
            self._set_preview(f"{self._selected_name}: {status}", _TEXT)
            return

        score = result.get("score", 0)
        buy_cost = result.get("buy_cost", 0)
        sell_revenue = result.get("sell_revenue", 0)
        gross_profit = result.get("gross_profit", 0)
        margin_pct = result.get("margin_pct", 0)
        profit_m3 = result.get("profit_per_m3", 0)
        profit_token = _GREEN if gross_profit > 0 else _RED

        self._score_fields = [
            _field("贸易评分:", f"{score:.0f}/100", _PRIMARY if score >= 50 else profit_token, strong=True),
            _field("买入成本:", f"{buy_cost:,.0f} ISK"),
            _field("卖出收入:", f"{sell_revenue:,.0f} ISK"),
            _field("毛利润:", f"{gross_profit:,.0f} ISK", profit_token, strong=True),
            _field("利润率:", f"{margin_pct:.1f}%", profit_token),
            _field("每m³利润:", f"{profit_m3:,.0f} ISK/m³"),
        ]
        self._set_preview(
            f"{self._selected_name} | 评分: {score:.0f} | 利润: {gross_profit:,.0f} ISK | 利润率: {margin_pct:.1f}%",
            profit_token,
        )
        self._update_trade_pair()
        self.hubChanged.emit()

    def _update_trade_pair(self) -> None:
        rows = self._hub_rows
        if not rows:
            self._pair_visible = False
            self.hubChanged.emit()
            return

        best_profit = 0.0
        best_buy = best_sell = ""
        buy_price_val = sell_price_val = 0.0
        for buy_row in rows:
            for sell_row in rows:
                if buy_row.get("hub") == sell_row.get("hub"):
                    continue
                if buy_row.get("buy_price", 0) <= 0 or sell_row.get("sell_price", 0) <= 0:
                    continue
                diff = sell_row["sell_price"] - buy_row["buy_price"]
                if diff > best_profit:
                    best_profit = diff
                    best_buy = str(buy_row["hub"])
                    best_sell = str(sell_row["hub"])
                    buy_price_val = buy_row["buy_price"]
                    sell_price_val = sell_row["sell_price"]

        if best_profit > 0:
            pct = best_profit / buy_price_val * 100 if buy_price_val > 0 else 0
            total = best_profit * self._quantity
            self._pair_text = (
                f"最优路线: {best_buy} 买入 ({buy_price_val:,.0f} ISK) → "
                f"{best_sell} 卖出 ({sell_price_val:,.0f} ISK)\n"
                f"单件利润: {best_profit:,.0f} ISK ({pct:.1f}%) | "
                f"{self._quantity} 件总利润: {total:,.0f} ISK"
            )
            self._pair_visible = True
        else:
            self._pair_visible = False

    # ═══════════════════════════════════════════════════════════
    #  Tab 2：运输
    # ═══════════════════════════════════════════════════════════

    transportSearchText = Property(str, lambda self: self._t_search_text, notify=transportChanged)
    transportResults = Property(list, lambda self: self._t_results, notify=transportChanged)
    transportPreview = Property(str, lambda self: self._t_preview, notify=transportChanged)
    transportPreviewColor = Property(str, lambda self: _token(self._t_preview_token), notify=transportChanged)
    transportBuyHubIndex = Property(int, lambda self: self._t_buy_hub_index, notify=transportChanged)
    transportSellHubIndex = Property(int, lambda self: self._t_sell_hub_index, notify=transportChanged)
    transportQuantity = Property(int, lambda self: self._t_quantity, notify=transportChanged)
    transportModeIndex = Property(int, lambda self: self._t_mode_index, notify=transportChanged)
    transportJumps = Property(int, lambda self: self._t_jumps, notify=transportChanged)
    transportJumpsAuto = Property(bool, lambda self: self._t_jumps_auto, notify=transportChanged)
    transportResultVisible = Property(bool, lambda self: self._t_result_visible, notify=transportChanged)
    transportFields = Property(list, lambda self: self._t_fields, notify=transportChanged)

    @Slot(str)
    def onTransportSearchChanged(self, text: str) -> None:
        self._t_search_text = str(text)
        if not text.strip():
            self._t_results = []
            self.transportChanged.emit()
            return
        from ui_pyside6.workers.industry_workers import SearchWorker

        worker = SearchWorker(text.strip(), get_container().db, self)
        self._t_search_worker = worker
        worker.finished_signal.connect(self._on_transport_search_result)
        worker.start()

    def _on_transport_search_result(self, results: list) -> None:
        self._t_results = [
            {
                "typeId": int(r["type_id"]),
                "text": f"[{r['type_id']}] {r.get('zh_name') or r.get('en_name') or ''}",
                "name": r.get("zh_name") or r.get("en_name") or str(r["type_id"]),
            }
            for r in (results or [])
        ]
        self.transportChanged.emit()

    @Slot(int)
    def pickTransportResult(self, index: int) -> None:
        if not 0 <= index < len(self._t_results):
            return
        item = self._t_results[index]
        self._t_selected_tid = int(item["typeId"])
        self._t_selected_name = str(item["name"])
        self._t_search_text = self._t_selected_name
        self._t_results = []
        self._t_preview = f"已选: {self._t_selected_name} — 点「分析运输」计算运费后利润"
        self._t_preview_token = _TEXT
        self._t_result_visible = False
        self.transportChanged.emit()

    @Slot(int)
    def setTransportBuyHubIndex(self, index: int) -> None:
        if 0 <= index < len(_HUBS) and index != self._t_buy_hub_index:
            self._t_buy_hub_index = index
            self._auto_update_jumps()

    @Slot(int)
    def setTransportSellHubIndex(self, index: int) -> None:
        if 0 <= index < len(_HUBS) and index != self._t_sell_hub_index:
            self._t_sell_hub_index = index
            self._auto_update_jumps()

    @Slot(int)
    def setTransportQuantity(self, value: int) -> None:
        value = max(1, min(1_000_000, int(value)))
        if value != self._t_quantity:
            self._t_quantity = value
            self.transportChanged.emit()

    @Slot(int)
    def setTransportModeIndex(self, index: int) -> None:
        if 0 <= index < len(_MODES) and index != self._t_mode_index:
            self._t_mode_index = index
            self.transportChanged.emit()

    @Slot(int)
    def setTransportJumps(self, value: int) -> None:
        value = max(1, min(500, int(value)))
        if value != self._t_jumps:
            self._t_jumps = value
            self._t_jumps_auto = False  # 手动改过就不再标「自动」
            self.transportChanged.emit()

    def _auto_update_jumps(self) -> None:
        """按买卖区域自动填跳跃数（查不到就保留用户值，只把「自动」标记去掉）。"""
        from services.logistics import get_distance_jumps

        jumps = get_distance_jumps(_HUBS[self._t_buy_hub_index], _HUBS[self._t_sell_hub_index])
        if jumps is not None:
            self._t_jumps = int(jumps)
            self._t_jumps_auto = True
        else:
            self._t_jumps_auto = False
        self.transportChanged.emit()

    @Slot()
    def analyzeTransport(self) -> None:
        if self._t_selected_tid is None:
            self._set_transport_preview("请先搜索并选择一个物品", _TEXT)
            return

        self._set_transport_preview(f"正在计算 {self._t_selected_name} 运输利润...", _TEXT)
        from ui_pyside6.workers.trade_workers import TransportWorker

        worker = TransportWorker(
            type_id=self._t_selected_tid,
            buy_hub=_HUBS[self._t_buy_hub_index],
            sell_hub=_HUBS[self._t_sell_hub_index],
            buy_price_type="buy",
            sell_price_type="sell",
            quantity=self._t_quantity,
            distance_jumps=self._t_jumps,
            use_public_freight=self._t_mode_index == 0,
            parent=self,
        )
        self._transport_worker = worker
        worker.finished_signal.connect(self._on_transport_result)
        worker.start()

    def _on_transport_result(self, result: dict) -> None:
        status = result.get("status", "")
        if status:
            self._set_transport_preview(f"{self._t_selected_name}: {status}", _TEXT)
            return

        freight = result["freight_cost"]
        net = result["net_profit"]
        margin = result["margin_pct"]
        profit_token = _GREEN if net > 0 else _RED

        self._t_fields = [
            _field("买入成本:", f"{result['buy_cost']:,.0f} ISK"),
            _field("卖出收入:", f"{result['sell_revenue']:,.0f} ISK"),
            _field("运费:", f"{freight:,.0f} ISK", _RED),
            _field("经纪人费:", f"{result['broker_cost']:,.0f} ISK"),
            _field("销售税:", f"{result['sales_tax']:,.0f} ISK"),
            _field("净利润:", f"{net:,.0f} ISK", profit_token, strong=True),
            _field("利润率:", f"{margin:.1f}%", profit_token),
            _field("每m³利润:", f"{result['isk_per_m3']:,.0f} ISK/m³"),
        ]
        mode_text = "公开货运" if result.get("freight_mode") == "public_freight" else "自有运输"
        self._set_transport_preview(
            f"{self._t_selected_name} | {mode_text} | 运费: {freight:,.0f} ISK | "
            f"净利润: {net:,.0f} ISK | 利润率: {margin:.1f}%",
            profit_token,
        )
        self._t_result_visible = True
        self.transportChanged.emit()

    # ═══════════════════════════════════════════════════════════
    #  内部
    # ═══════════════════════════════════════════════════════════

    def _set_preview(self, text: str, token: str) -> None:
        self._preview = text
        self._preview_token = token
        self.searchChanged.emit()

    def _set_transport_preview(self, text: str, token: str) -> None:
        self._t_preview = text
        self._t_preview_token = token
        self.transportChanged.emit()

    def _on_theme_changed(self) -> None:
        """主题切换：卡片颜色是算出来的字符串，重算一次并让表格重绘。"""
        self._hub_model.refresh_colors()
        if self._score_fields:
            self._score_fields = list(self._score_fields)
        if self._t_fields:
            self._t_fields = list(self._t_fields)
        self.searchChanged.emit()
        self.hubChanged.emit()
        self.transportChanged.emit()
