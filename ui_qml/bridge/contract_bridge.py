"""合同页 bridge —— QML 与既有 worker / 模型之间的唯一通道。

对照的 Widgets 版是 `ui_pyside6/views/contract_view.py`。

**过滤仍走 `ContractFilterProxy`**：`QSortFilterProxyModel` 会把源模型的 `roleNames()`
转发下去，所以 QML 直接把**代理**当 model，搜索/价格区间/买卖类型全部照旧走它的
`filterAcceptsRow` —— 过滤逻辑一份都不用重写。

        contract detail dialog（`ContractDetailQmlDialog`）—— 阶段 4 已迁到 QML。
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWidgets import QApplication

from core.constants import TRADE_HUB_IDS, TRADE_HUBS
from ui_qml.models.contract_qml_models import ContractItemQmlModel, ContractQmlModel

__all__ = ["ContractBridge"]

_TYPE_LABELS = ["全部", "物品交换", "拍卖", "运输"]
_TYPE_KEYS = {
    "全部": "all",
    "物品交换": "item_exchange",
    "拍卖": "auction",
    "运输": "courier",
}
_BUY_SELL = ["全部", "我要买", "我要卖"]


class ContractBridge(QObject):
    """合同页的 QML 后端。"""

    rowsChanged = Signal()  # 合同列表 / 计数 / 进度
    itemsChanged = Signal()  # 下方物品表
    filtersChanged = Signal()

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        from ui_qml.models.contract_models import ContractFilterProxy

        self._shell = shell
        self._region_index = 0
        self._type_index = 0
        self._busy = False
        self._count_text = "合同: —"
        self._fetch_worker: QObject | None = None
        self._load_worker: QObject | None = None
        self._items_worker: QObject | None = None
        self._selected_contract: dict | None = None

        self._model = ContractQmlModel()
        self._proxy = ContractFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self._item_model = ContractItemQmlModel()

        # 客户端过滤条件（搜索/价格/买卖）
        self._search_text = ""
        self._price_min = 0.0
        self._price_max = 0.0
        self._buy_sell_index = 0

    # ═══════════════════════════════════════════════════════════
    #  顶部筛选（区域 / 类型）—— 变更即重新拉库
    # ═══════════════════════════════════════════════════════════

    regions = Property(list, lambda self: list(TRADE_HUBS), constant=True)
    types = Property(list, lambda self: list(_TYPE_LABELS), constant=True)
    buySellOptions = Property(list, lambda self: list(_BUY_SELL), constant=True)

    regionIndex = Property(int, lambda self: self._region_index, notify=filtersChanged)
    typeIndex = Property(int, lambda self: self._type_index, notify=filtersChanged)

    @Slot(int)
    def setRegionIndex(self, index: int) -> None:
        if 0 <= index < len(TRADE_HUBS) and index != self._region_index:
            self._region_index = index
            self.filtersChanged.emit()
            self.loadContracts()

    @Slot(int)
    def setTypeIndex(self, index: int) -> None:
        if 0 <= index < len(_TYPE_LABELS) and index != self._type_index:
            self._type_index = index
            self.filtersChanged.emit()
            self.loadContracts()

    # ═══════════════════════════════════════════════════════════
    #  列表
    # ═══════════════════════════════════════════════════════════

    model = Property(QObject, lambda self: self._proxy, constant=True)
    itemModel = Property(QObject, lambda self: self._item_model, constant=True)

    @Property(list, constant=True)
    def contractColumns(self) -> list[dict]:
        """合同表列定义（标题 + 宽度）—— 单一来源在 `contract_models._CONTRACT_COLUMNS`。"""
        from ui_qml.models.contract_models import _CONTRACT_COLUMNS

        return [{"title": title, "width": width} for title, width in _CONTRACT_COLUMNS]

    @Property(list, constant=True)
    def itemColumns(self) -> list[dict]:
        """物品表列定义 —— 单一来源在 `contract_models._ITEM_COLUMNS`。"""
        from ui_qml.models.contract_models import _ITEM_COLUMNS

        return [{"title": title, "width": width} for title, width in _ITEM_COLUMNS]

    busy = Property(bool, lambda self: self._busy, notify=rowsChanged)
    countText = Property(str, lambda self: self._count_text, notify=rowsChanged)

    @Slot()
    def refresh(self) -> None:
        """从 ESI 拉取合同数据（原版「刷新合同数据」）。"""
        if self._fetch_worker is not None and self._fetch_worker.isRunning():  # type: ignore[attr-defined]
            self._count_text = "正在更新中..."
            self.rowsChanged.emit()
            return

        from ui_qml.workers.contract_workers import ContractFetchWorker

        self._busy = True
        self._count_text = "正在从 ESI 获取合同数据..."
        self.rowsChanged.emit()

        worker = ContractFetchWorker([TRADE_HUBS[self._region_index]], self)
        self._fetch_worker = worker
        worker.finished_signal.connect(self._on_fetch_done)
        worker.start()

    def _on_fetch_done(self, success: bool, message: str) -> None:
        self._busy = False
        if success:
            self._count_text = "合同数据已更新"
            self.rowsChanged.emit()
            self.loadContracts()
        else:
            self._count_text = f"更新失败: {message}"
            self.rowsChanged.emit()

    @Slot()
    def loadContracts(self) -> None:
        """从数据库加载当前区域/类型下的合同。"""
        from ui_qml.workers.contract_workers import ContractLoadWorker

        region_id = TRADE_HUB_IDS.get(TRADE_HUBS[self._region_index], 10000002)
        worker = ContractLoadWorker(region_id, _TYPE_KEYS[_TYPE_LABELS[self._type_index]], self)
        self._load_worker = worker
        worker.finished_signal.connect(self._on_contracts_loaded)
        worker.start()

    def _on_contracts_loaded(self, contracts: list) -> None:
        self._model.set_rows(contracts)
        self._item_model.set_rows([])
        self._selected_contract = None
        self._apply_client_filters()
        self.itemsChanged.emit()

    # ═══════════════════════════════════════════════════════════
    #  客户端过滤（搜索 / 价格区间 / 买卖）
    # ═══════════════════════════════════════════════════════════

    searchText = Property(str, lambda self: self._search_text, notify=filtersChanged)
    priceMin = Property(float, lambda self: self._price_min, notify=filtersChanged)
    priceMax = Property(float, lambda self: self._price_max, notify=filtersChanged)
    buySellIndex = Property(int, lambda self: self._buy_sell_index, notify=filtersChanged)

    @Slot(str)
    def setSearchText(self, text: str) -> None:
        self._search_text = str(text)
        self._apply_client_filters()

    @Slot(float)
    def setPriceMin(self, value: float) -> None:
        self._price_min = float(value)
        self._apply_client_filters()

    @Slot(float)
    def setPriceMax(self, value: float) -> None:
        self._price_max = float(value)
        self._apply_client_filters()

    @Slot(int)
    def setBuySellIndex(self, index: int) -> None:
        if 0 <= index < len(_BUY_SELL):
            self._buy_sell_index = index
            self._apply_client_filters()

    def _apply_client_filters(self) -> None:
        self._proxy.set_search_text(self._search_text)
        self._proxy.set_price_range(self._price_min, self._price_max)
        self._proxy.set_buy_sell(_BUY_SELL[self._buy_sell_index])
        self._count_text = f"合同: {self._proxy.rowCount()}/{self._model.rowCount()} 条"
        self.rowsChanged.emit()

    # ═══════════════════════════════════════════════════════════
    #  行交互
    # ═══════════════════════════════════════════════════════════

    def _source_row(self, proxy_row: int) -> int:
        """代理行号 → 源行号（过滤后行号与源行号不一致，必须映射）。"""
        index = self._proxy.index(proxy_row, 0)
        return int(self._proxy.mapToSource(index).row()) if index.isValid() else -1

    def _row_data(self, proxy_row: int) -> dict | None:
        row = self._source_row(proxy_row)
        return self._model.get_row(row) if row >= 0 else None

    @Slot(int)
    def selectContract(self, proxy_row: int) -> None:
        """单击合同行 → 加载该合同的物品列表。"""
        data = self._row_data(proxy_row)
        if not data:
            return
        self._selected_contract = data
        self._loadItems(int(data.get("contract_id") or 0))

    def _loadItems(self, contract_id: int) -> None:
        if self._items_worker is not None and self._items_worker.isRunning():  # type: ignore[attr-defined]
            return
        from ui_qml.workers.contract_workers import ContractItemsLoadWorker

        worker = ContractItemsLoadWorker(contract_id, self)
        self._items_worker = worker
        worker.finished_signal.connect(self._on_items_loaded)
        worker.start()

    def _on_items_loaded(self, items: list) -> None:
        self._item_model.set_rows(items)
        self.itemsChanged.emit()

    @Slot(int)
    def showDetail(self, proxy_row: int) -> None:
        """双击合同行 → 详情弹窗。"""
        data = self._row_data(proxy_row)
        if not data:
            return
        from ui_qml.bridge.contract_detail_bridge import ContractDetailQmlDialog

        parent = None
        ContractDetailQmlDialog(data, parent).exec()

    # ── 右键菜单动作 ──────────────────────────────────────────

    @Slot(int)
    def copyContractId(self, proxy_row: int) -> None:
        data = self._row_data(proxy_row)
        if data:
            self._copy(str(data.get("contract_id", "")))

    @Slot()
    def copyItems(self) -> None:
        """把当前合同的物品列表（已加载的）复制到剪贴板。"""
        items = self._item_model._rows
        if not items:
            self._set_count("请先点击合同加载物品列表")
            return
        lines = [f"{(i.get('zh_name') or i.get('en_name') or '')}\tx{i.get('quantity', 0)}" for i in items]
        self._copy("\n".join(lines), note=f"已复制 {len(items)} 个物品到剪贴板")

    @Slot()
    def addItemsToWatchlist(self) -> None:
        """把当前合同的物品加入关注列表。"""
        from services.watchlist_manager import add_to_watchlist

        items = self._item_model._rows
        if not items:
            self._set_count("请先点击合同加载物品列表")
            return
        region_id = int((self._selected_contract or {}).get("region_id") or 10000002)
        added = 0
        for item in items:
            type_id = item.get("type_id", 0)
            if type_id:
                add_to_watchlist(type_id, region_id=region_id)
                added += 1
        self._set_count(f"已添加 {added} 个物品到关注列表")

    @Slot(result=str)
    def itemSummary(self) -> str:
        """当前合同物品的纯文本摘要（「查看物品详情」用它，替代 Widgets 的消息框）。"""
        items = self._item_model._rows
        if not items:
            return ""
        lines = []
        for item in items:
            name = item.get("zh_name") or item.get("en_name") or f"ID:{item.get('type_id', '?')}"
            lines.append(f"• {name}  x{item.get('quantity', 0)}")
        return "\n".join(lines)

    @Slot(result=bool)
    def hasItems(self) -> bool:
        return bool(self._item_model._rows)

    @Slot(int, result=dict)
    def menuState(self, proxy_row: int) -> dict:
        data = self._row_data(proxy_row) or {}
        return {
            "valid": bool(data),
            "contractId": data.get("contract_id", ""),
            "hasItems": self.hasItems(),
        }

    # ── 内部 ──────────────────────────────────────────────────

    def _copy(self, text: str, note: str = "") -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self._set_count(note or f"已复制: {text}")

    def _set_count(self, text: str) -> None:
        self._count_text = text
        self.rowsChanged.emit()
