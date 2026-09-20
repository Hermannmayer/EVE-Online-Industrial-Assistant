"""合同页 bridge —— QML 与 service / worker 之间的唯一通道。

页面按类型分三个页签（拍卖 / 物品交换 / 运输），各自一张表、一套列。
判定（价差、每跳 ISK、制造利润）全在 `services/contract_service` + `domain/contract_analysis`
里算好，这里只做转发与状态管理。

**两类写库任务互斥**：拉列表与补物品都写 market.db（SQLite 单写者），
`_busy_worker` 保证同一时刻只跑一个。

**进页面只读库，绝不自动拉 ESI** —— 用户明确要求「只有点了拉取才拉」。
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from core.constants import TRADE_HUB_IDS, TRADE_HUBS
from core.logger import log
from ui_qml.models.contract_models import (
    AUCTION_VIEW,
    COURIER_VIEW,
    EXCHANGE_VIEW,
    ITEM_COLUMNS,
    ContractItemTableModel,
    ContractTableModel,
)
from ui_qml.workers.contract_workers import spawn

__all__ = ["ContractBridge"]

_TABS = ["拍卖", "物品交换", "运输"]
_TAB_KEYS = ("auction", "exchange", "courier")

#: 跳数口径。第一项是「先不算」—— 用户要求选了才算（本地 BFS 虽快，但没必要替他做主）。
_JUMP_MODES = ["不计算", "最短路线", "避开低安", "自定义安全下限"]
_JUMP_KEYS = ("none", "shortest", "highsec", "custom")

_PRICE_TYPES = ["卖单最低价", "买单最高价"]
_PRICE_KEYS = ("sell", "buy")


class ContractBridge(QObject):
    rowsChanged = Signal()  # 行数 / 状态文案 / 进度
    itemsChanged = Signal()  # 下方物品表
    filtersChanged = Signal()
    regionChanged = Signal()
    suggestChanged = Signal()

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell
        self._tab_index = 0
        self._status = "尚未拉取合同"
        self._busy_worker: QObject | None = None
        self._fill_worker: QObject | None = None
        self._items_worker: QObject | None = None
        self._selected_contract: dict | None = None

        #: 星域：默认 Jita（The Forge），也可以由用户按名字挑
        self._region_id = TRADE_HUB_IDS["Jita"]
        self._region_label = ""
        self._region_query = ""
        self._suggestions: list[dict] = []

        self._price_type_index = 0
        self._jump_mode_index = 0
        self._min_security = 0.45

        self._price_min = 0.0
        self._price_max = 0.0
        self._blueprint_only = False
        self._min_hours_left = 0

        self._models = {
            "auction": ContractTableModel(AUCTION_VIEW),
            "exchange": ContractTableModel(EXCHANGE_VIEW),
            "courier": ContractTableModel(COURIER_VIEW),
        }
        self._item_model = ContractItemTableModel()

    # ═══════════════════════════════════════════════════════════
    #  页签
    # ═══════════════════════════════════════════════════════════

    tabs = Property(list, lambda self: list(_TABS), constant=True)
    tabIndex = Property(int, lambda self: self._tab_index, notify=filtersChanged)

    @Slot(int)
    def setTabIndex(self, index: int) -> None:
        if 0 <= index < len(_TABS) and index != self._tab_index:
            self._tab_index = index
            self.filtersChanged.emit()
            self.loadTab()

    @property
    def _tab_key(self) -> str:
        return _TAB_KEYS[self._tab_index]

    # ── 三个模型与列定义 ──

    auctionModel = Property(QObject, lambda self: self._models["auction"], constant=True)
    exchangeModel = Property(QObject, lambda self: self._models["exchange"], constant=True)
    courierModel = Property(QObject, lambda self: self._models["courier"], constant=True)

    @staticmethod
    def _cols(view) -> list[dict]:
        return [{"title": t, "width": w} for t, w in view.columns]

    @Property(list, constant=True)
    def auctionColumns(self) -> list[dict]:
        return self._cols(AUCTION_VIEW)

    @Property(list, constant=True)
    def exchangeColumns(self) -> list[dict]:
        return self._cols(EXCHANGE_VIEW)

    @Property(list, constant=True)
    def courierColumns(self) -> list[dict]:
        return self._cols(COURIER_VIEW)

    @Property(list, constant=True)
    def itemColumns(self) -> list[dict]:
        return [{"title": t, "width": w} for t, w in ITEM_COLUMNS]

    itemModel = Property(QObject, lambda self: self._item_model, constant=True)

    # ═══════════════════════════════════════════════════════════
    #  星域（按名字挑，不让用户记 id）
    # ═══════════════════════════════════════════════════════════

    regionOptions = Property(list, lambda self: list(TRADE_HUBS), constant=True)
    regionLabel = Property(str, lambda self: self._region_label, notify=regionChanged)
    regionQuery = Property(str, lambda self: self._region_query, notify=suggestChanged)
    suggestions = Property(list, lambda self: list(self._suggestions), notify=suggestChanged)

    @Slot(int)
    def setHubIndex(self, index: int) -> None:
        """从常用贸易中心里点一个。"""
        if 0 <= index < len(TRADE_HUBS):
            self._pick_region(TRADE_HUB_IDS[TRADE_HUBS[index]], TRADE_HUBS[index])

    @Slot(str)
    def setRegionQuery(self, text: str) -> None:
        self._region_query = str(text)
        from services.contract_service import list_regions

        try:
            self._suggestions = list_regions(self._region_query, limit=30)
        except Exception:  # 星域表缺失不该让输入框卡住
            self._suggestions = []
        self.suggestChanged.emit()

    @Slot(int)
    def pickRegion(self, index: int) -> None:
        if 0 <= index < len(self._suggestions):
            picked = self._suggestions[index]
            self._pick_region(int(picked["region_id"]), str(picked["name"]))
            self._suggestions = []
            self.suggestChanged.emit()

    def _pick_region(self, region_id: int, label: str) -> None:
        self._region_id = region_id
        self._region_label = label
        self._region_query = ""
        self.regionChanged.emit()
        self.loadTab()

    @Slot()
    def refreshRegionLabel(self) -> None:
        from services.contract_service import region_name

        self._region_label = region_name(self._region_id)
        self.regionChanged.emit()

    # ═══════════════════════════════════════════════════════════
    #  口径与筛选
    # ═══════════════════════════════════════════════════════════

    priceTypes = Property(list, lambda self: list(_PRICE_TYPES), constant=True)
    jumpModes = Property(list, lambda self: list(_JUMP_MODES), constant=True)

    priceTypeIndex = Property(int, lambda self: self._price_type_index, notify=filtersChanged)
    jumpModeIndex = Property(int, lambda self: self._jump_mode_index, notify=filtersChanged)
    minSecurity = Property(float, lambda self: self._min_security, notify=filtersChanged)
    priceMin = Property(float, lambda self: self._price_min, notify=filtersChanged)
    priceMax = Property(float, lambda self: self._price_max, notify=filtersChanged)
    blueprintOnly = Property(bool, lambda self: self._blueprint_only, notify=filtersChanged)
    minHoursLeft = Property(int, lambda self: self._min_hours_left, notify=filtersChanged)

    @Slot(int)
    def setPriceTypeIndex(self, index: int) -> None:
        if 0 <= index < len(_PRICE_TYPES) and index != self._price_type_index:
            self._price_type_index = index
            self.filtersChanged.emit()
            self.loadTab()

    @Slot(int)
    def setJumpModeIndex(self, index: int) -> None:
        """选了口径才算跳数 —— 这是用户明确要求的行为。"""
        if 0 <= index < len(_JUMP_MODES) and index != self._jump_mode_index:
            self._jump_mode_index = index
            self.filtersChanged.emit()
            self.loadTab()

    @Slot(float)
    def setMinSecurity(self, value: float) -> None:
        self._min_security = float(value)
        if self._jump_mode_index == 3:  # 自定义
            self.loadTab()

    @Slot(float)
    def setPriceMin(self, value: float) -> None:
        self._price_min = float(value)
        self.filtersChanged.emit()

    @Slot(float)
    def setPriceMax(self, value: float) -> None:
        self._price_max = float(value)
        self.filtersChanged.emit()

    @Slot(bool)
    def setBlueprintOnly(self, value: bool) -> None:
        self._blueprint_only = bool(value)
        self.filtersChanged.emit()

    @Slot(int)
    def setMinHoursLeft(self, value: int) -> None:
        self._min_hours_left = int(value)
        self.filtersChanged.emit()

    @Slot()
    def applyFilters(self) -> None:
        """筛选下推到 SQL —— 改完筛选要重新查库，不是本地过滤。"""
        self.loadTab()

    def _filter_params(self) -> dict:
        return {
            "price_min": self._price_min or None,
            "price_max": self._price_max or None,
            "blueprint_only": self._blueprint_only,
            "min_hours_left": self._min_hours_left or None,
        }

    # ═══════════════════════════════════════════════════════════
    #  加载（只读库）
    # ═══════════════════════════════════════════════════════════

    statusText = Property(str, lambda self: self._status, notify=rowsChanged)
    busy = Property(bool, lambda self: self._busy_worker is not None, notify=rowsChanged)

    @Slot()
    def loadTab(self) -> None:
        """按当前页签查库。进页面时也走这条 —— 修掉「首次进入不显示任何合同」。

        **同步，刻意不开线程**：实测最重的一档（物品交换 3000 行）本机 **49 ms**，
        其余 1~4 ms。而本页是唯一「进门就加载」的页面 —— 异步结果回来时视图可能正在销毁，
        实测会让 ui 档后续用例 `access violation`（原始代码跑同一档干净）。
        本地查询这么快，线程只换来一类崩溃风险，不值。
        ESI 那两件事（拉列表 / 补物品）才真需要线程，见 `refresh` / `startFill`。
        """
        from services.contract_service import (
            load_auction_contracts,
            load_courier_contracts,
            load_exchange_contracts,
        )

        tab = self._tab_key
        filters = self._filter_params()
        price_type = _PRICE_KEYS[self._price_type_index]
        try:
            if tab == "courier":
                rows = load_courier_contracts(
                    self._region_id, _JUMP_KEYS[self._jump_mode_index], self._min_security, filters
                )
            elif tab == "auction":
                rows = load_auction_contracts(self._region_id, price_type, filters)
            else:
                rows = load_exchange_contracts(self._region_id, price_type, filters)
        except Exception as ex:
            # 表不存在 / 库被占用都是这一类 —— **不吞**，文案要能看出是库的问题
            log.exception("合同查询失败, tab=%s", tab)
            self._status = f"数据库查询失败: {ex}"
            self.rowsChanged.emit()
            return

        self._on_loaded(tab, rows, "")

    def _on_loaded(self, tab_key: str, rows: list, error: str) -> None:
        if tab_key != self._tab_key:
            return  # 期间用户换了页签，丢弃过期结果
        self._models[tab_key].set_rows(rows)
        self._item_model.set_rows([])
        self._selected_contract = None
        self._status = error or f"{_TABS[self._tab_index]}: {len(rows):,} 条"
        self.itemsChanged.emit()
        self.rowsChanged.emit()

    # ── 拉取（唯一的 ESI 入口）──

    @Slot()
    def refresh(self) -> None:
        """从 ESI 拉合同**列表**（不含物品）。"""
        if self._busy_worker is not None:
            self._status = "已有拉取任务在跑，请先等待或停止"
            self.rowsChanged.emit()
            return

        from ui_qml.workers.contract_workers import ContractFetchWorker

        self._status = "正在拉取合同列表…（列表只拉一次，很快）"
        self.rowsChanged.emit()

        worker = ContractFetchWorker([self._region_id])
        self._busy_worker = worker
        worker.finished_signal.connect(self._on_fetch_done)
        spawn(worker)

    def _on_fetch_done(self, ok: bool, message: str) -> None:
        self._busy_worker = None
        self._status = message if ok else f"拉取失败: {message}"
        self.rowsChanged.emit()
        if ok:
            self.loadTab()

    # ── 补齐物品（价差的前提，可停）──

    @Slot()
    def startFill(self) -> None:
        """后台补齐物品详情。**只在用户点过之后才跑** —— 不会自动发起。"""
        if self._busy_worker is not None:
            self._status = "已有任务在跑，请先等待或停止"
            self.rowsChanged.emit()
            return
        if self._tab_key == "courier":
            self._status = "运输合同没有物品详情，不需要补齐"
            self.rowsChanged.emit()
            return

        from ui_qml.workers.contract_workers import ContractFillWorker

        self._status = "正在补齐物品详情…"
        self.rowsChanged.emit()

        worker = ContractFillWorker(self._region_id, self._tab_key)
        self._busy_worker = worker
        self._fill_worker = worker
        worker.progress.connect(self._on_fill_progress)
        worker.finished_signal.connect(self._on_fill_done)
        spawn(worker)

    def _on_fill_progress(self, done: int, total: int) -> None:
        self._status = f"物品补齐中… {done:,} / {total:,}"
        self.rowsChanged.emit()
        if done and done % 500 == 0:
            self.loadTab()  # 边补边刷新，价差列逐行填上

    def _on_fill_done(self, written: int, message: str) -> None:
        self._busy_worker = None
        self._fill_worker = None
        self._status = f"{message}（写入 {written:,} 条物品）"
        self.rowsChanged.emit()
        self.loadTab()

    @Slot()
    def stopFill(self) -> None:
        if self._fill_worker is not None:
            self._fill_worker.stop()  # type: ignore[attr-defined]
            self._status = "正在停止…"
            self.rowsChanged.emit()

    # ═══════════════════════════════════════════════════════════
    #  行交互
    # ═══════════════════════════════════════════════════════════

    def _row_data(self, row: int) -> dict | None:
        return self._models[self._tab_key].get_row(row)

    @Slot(int)
    def selectContract(self, row: int) -> None:
        """单击合同行 → 加载该合同的物品明细（含市价）。"""
        data = self._row_data(row)
        if not data:
            return
        self._selected_contract = data

        from ui_qml.workers.contract_workers import ContractItemsLoadWorker

        worker = ContractItemsLoadWorker(
            int(data.get("contract_id") or 0), self._region_id, _PRICE_KEYS[self._price_type_index]
        )
        self._items_worker = worker
        worker.finished_signal.connect(self._on_items_loaded)
        spawn(worker)

    def _on_items_loaded(self, items: list) -> None:
        self._item_model.set_rows(items)
        self.itemsChanged.emit()

    @Slot(int)
    def showDetail(self, row: int) -> None:
        data = self._row_data(row)
        if not data:
            return
        from ui_qml.bridge.contract_detail_bridge import ContractDetailQmlDialog

        ContractDetailQmlDialog(data, None).show()

    @Slot(result=str)
    def itemSummary(self) -> str:
        items = self._item_model._rows
        if not items:
            return ""
        lines = []
        for it in items:
            name = it.get("zh_name") or it.get("en_name") or f"ID:{it.get('type_id', '?')}"
            price = it.get("unit_price")
            suffix = f"  @ {price:,.0f}" if price else ""
            lines.append(f"• {name}  x{it.get('quantity', 0)}{suffix}")
        return "\n".join(lines)

    @Slot(result=bool)
    def hasItems(self) -> bool:
        return bool(self._item_model._rows)

    @Slot()
    def shutdown(self) -> None:
        """页面销毁前，等在跑的 worker 收尾。

        **合同页是唯一在 `Component.onCompleted` 里起 QThread 的页面**（其余页面进门都是
        同步取数）。QThread 是桥的子对象，线程还在跑时若宿主先销毁，Qt 会连带析构它并
        abort —— 实测表现为 ui 档里后续用例的 `access violation`（原始代码跑同一档干净，
        加上「进门即加载」后必现）。所以页面在 `Component.onDestruction` 里调本方法。

        取数都是本地查询，几毫秒到几百毫秒，等一下是安全的。
        """
        for worker in (self._busy_worker, self._items_worker):
            if worker is None:
                continue
            stop = getattr(worker, "stop", None)
            if callable(stop) and worker is self._busy_worker:
                stop()  # 补齐任务要主动请求中断，否则它会一直跑下去
            if worker.isRunning():  # type: ignore[attr-defined]
                worker.wait(3000)  # type: ignore[attr-defined]

    # ── 右键菜单动作 ──────────────────────────────────────────

    @Slot(int)
    def copyContractId(self, row: int) -> None:
        data = self._row_data(row)
        if data:
            self._copy(str(data.get("contract_id", "")))

    @Slot()
    def copyItems(self) -> None:
        """把当前合同的物品列表（已加载的那份）复制到剪贴板。"""
        items = self._item_model._rows
        if not items:
            self._status = "请先点击合同加载物品列表"
            self.rowsChanged.emit()
            return
        lines = []
        for it in items:
            name = it.get("zh_name") or it.get("en_name") or f"ID:{it.get('type_id', '?')}"
            price = it.get("unit_price")
            lines.append(f"{name}\tx{it.get('quantity', 0)}" + (f"\t{price:,.0f}" if price else ""))
        self._copy("\n".join(lines), note=f"已复制 {len(items)} 个物品到剪贴板")

    @Slot()
    def addItemsToWatchlist(self) -> None:
        """把当前合同的物品加入关注列表。"""
        from services.watchlist_manager import add_to_watchlist

        items = self._item_model._rows
        if not items:
            self._status = "请先点击合同加载物品列表"
            self.rowsChanged.emit()
            return
        added = 0
        for item in items:
            type_id = item.get("type_id", 0)
            if type_id:
                add_to_watchlist(int(type_id), region_id=self._region_id)
                added += 1
        self._status = f"已添加 {added} 个物品到关注列表"
        self.rowsChanged.emit()

    def _copy(self, text: str, note: str = "") -> None:
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self._status = note or f"已复制: {text}"
        self.rowsChanged.emit()
