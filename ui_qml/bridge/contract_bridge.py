"""合同页 bridge —— QML 与 service / worker 之间的唯一通道。

页面按类型分三个页签（拍卖 / 物品交换 / 运输），各自一张表、一套列。
判定（价差、每跳 ISK、制造利润）全在 `services/contract_service` + `domain/contract_analysis`
里算好，这里只做转发与状态管理。

**两类写库任务互斥**：拉列表与补物品都写 market.db（SQLite 单写者），
`_busy_worker` 保证同一时刻只跑一个。

**联网有三处，都是显式动作**：拉列表（点「拉取合同」）、补齐整个星域（点「补齐全部」）、
补齐**当前列表**（打开合同页后自动跑一次，范围就是眼前这几千行 —— 价差列和图标列没有
物品数据就永远是空的，而一个星域 3.4 万份合同逐个拉没人等得起）。落在页面的
`on_shown` 钩子上而不是创建时：外壳启动会把 7 个页面全部建好，挂在创建上等于用户还没
点开合同页就开始拉。结果落库，所以下次打开不会重复拉；随时可点「停止」。
"""

from __future__ import annotations

import time

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot

from core.constants import TRADE_HUB_IDS, TRADE_HUBS
from core.logger import log
from ui_qml.models.contract_models import (
    AUCTION_VIEW,
    COURIER_VIEW,
    EXCHANGE_VIEW,
    ITEM_COLUMNS,
    ITEM_ICON_COLUMN,
    ContractItemTableModel,
    ContractTableModel,
)
from ui_qml.workers.contract_workers import spawn

__all__ = ["ContractBridge"]

_TABS = ["拍卖", "物品交换", "运输"]
_TAB_KEYS = ("auction", "exchange", "courier")

#: 页签 key → 库里的合同类型（页签条数徽标按它统计）。
_TAB_TYPES = {"auction": "auction", "exchange": "item_exchange", "courier": "courier"}

#: 跳数口径。第一项是「先不算」—— 用户要求选了才算（本地 BFS 虽快，但没必要替他做主）。
_JUMP_MODES = ["不计算", "最短路线", "避开低安", "自定义安全下限"]
_JUMP_KEYS = ("none", "shortest", "highsec", "custom")

_PRICE_TYPES = ["卖单最低价", "买单最高价"]
_PRICE_KEYS = ("sell", "buy")


def _next_sort_order(model: object, column: int, numeric: frozenset[int]) -> Qt.SortOrder:
    """点同一列就反向；换一列时金额/数量列给**降序**（先看大的），文本列给升序。"""
    if model.sort_column == column:  # type: ignore[attr-defined]
        return Qt.SortOrder.AscendingOrder if model.sort_descending else Qt.SortOrder.DescendingOrder  # type: ignore[attr-defined]
    return Qt.SortOrder.DescendingOrder if column in numeric else Qt.SortOrder.AscendingOrder


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
        self._last_fill_reload_at = 0.0
        #: 当前页签已查出来的行（`on_shown` 时据此决定补什么）
        self._loaded_rows: list[dict] = []
        #: 页面是否被打开过 —— 自动补齐的门槛，见 `on_shown`
        self._page_shown = False

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
        self._issuer_query = ""
        self._tab_counts: list[int] = [0, 0, 0]

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
        """列定义给 QML —— `icons` 标记该列画图标而不是文字（见 `ContractView.icon_column`）。"""
        return [
            {"title": title, "width": width, "icons": index == view.icon_column}
            for index, (title, width) in enumerate(view.columns)
        ]

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
        return [
            {"title": title, "width": width, "icons": index == ITEM_ICON_COLUMN}
            for index, (title, width) in enumerate(ITEM_COLUMNS)
        ]

    itemModel = Property(QObject, lambda self: self._item_model, constant=True)

    # ── 表头排序（总表与物品表各一套；点同一列反向）──

    @Property(int, notify=itemsChanged)
    def itemSortColumn(self) -> int:
        return self._item_model.sort_column

    @Property(bool, notify=itemsChanged)
    def itemSortAscending(self) -> bool:
        return not self._item_model.sort_descending

    @Slot(int)
    def itemSortBy(self, column: int) -> None:
        """物品表表头点击 → 排序（可排的列见 `contract_models._ITEM_SORT_KEYS`）。"""
        model = self._item_model
        model.sort(column, _next_sort_order(model, column, model.numeric_columns))
        self.itemsChanged.emit()

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

    @Slot(str)
    def setIssuerQuery(self, text: str) -> None:
        """按发布者名字反查他的合同（三个页签共用）。

        只记下输入，不立刻查库 —— 每敲一个字就重查一次会把输入框拖住
        （最重的一档查询 49 ms）。生效时机与价格/剩余时间一致：点「应用筛选」或回车。
        """
        self._issuer_query = str(text)
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
            "issuer": self._issuer_query.strip() or None,
        }

    # ═══════════════════════════════════════════════════════════
    #  加载（只读库）
    # ═══════════════════════════════════════════════════════════

    statusText = Property(str, lambda self: self._status, notify=rowsChanged)
    busy = Property(bool, lambda self: self._busy_worker is not None, notify=rowsChanged)
    tabCounts = Property(list, lambda self: list(self._tab_counts), notify=rowsChanged)

    # ── 表头排序（点一次排，再点一次反向）──

    @Property(int, notify=rowsChanged)
    def sortColumn(self) -> int:
        return self._models[self._tab_key].sort_column

    @Property(bool, notify=rowsChanged)
    def sortAscending(self) -> bool:
        return not self._models[self._tab_key].sort_descending

    @Slot(int)
    def sortBy(self, column: int) -> None:
        """总表表头点击 → 排序。

        首次点某列：金额/数量列给**降序**（看合同先看贵的、赚得多的），文本列给升序；
        再点同一列就反向。**排的是已经查出来的那批行**（SQL 那边按价格降序 LIMIT 3000），
        所以「按价差排」是在这 3000 条里排 —— 列表原本的取值范围不变。
        """
        model = self._models[self._tab_key]
        model.sort(column, _next_sort_order(model, column, model.view.numeric))
        self.rowsChanged.emit()

    @Slot()
    def loadTab(self) -> None:
        """切页签 / 改筛选 / 进页面都走这条：查库 + 刷新页签条数 + 起后台补齐。"""
        self._refresh_tab_counts()
        self._reload_rows(auto_backfill=True)

    def on_shown(self) -> None:
        """页面被切到前台（`shell_window.navigate_to` 的 `on_shown` 钩子）。

        自动补齐**挂在这里而不是 `Component.onCompleted`**：外壳启动时会把 7 个页面
        一次性全部建好，挂在创建上等于用户还没点开合同页，就已经在拉几万份合同的物品。
        """
        self._page_shown = True
        self._start_backfill(self._loaded_rows)

    def _reload_rows(self, auto_backfill: bool = False) -> None:
        """按当前页签查库。

        **同步，刻意不开线程**：实测最重的一档（物品交换 3000 行）本机 **49 ms**，
        其余 1~4 ms。而本页是唯一「进门就加载」的页面 —— 异步结果回来时视图可能正在销毁，
        实测会让 ui 档后续用例 `access violation`（原始代码跑同一档干净）。
        本地查询这么快，线程只换来一类崩溃风险，不值。
        ESI 那两件事（拉列表 / 补物品）才真需要线程，见 `refresh` / `_start_backfill`。

        `auto_backfill` 只由**用户动作**那条路径开（切页签/改筛选/切星域），且要在页面
        已经被打开过之后：补齐过程每 500 条会回灌一次列表，若那条路径也允许自动补齐，
        就会出现「补完 → 立刻又起一轮」——已过期、ESI 已 404 的合同永远补不上，环会一直转。
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
        if auto_backfill and self._page_shown:
            self._start_backfill(rows)

    def _refresh_tab_counts(self) -> None:
        """三个页签各有多少条（段控件上的徽标）。

        口径与列表一致（同一套 `_build_where`）。蓝图筛选只对物品交换生效 —— 它的判据是
        「体积 ≤ 0.05」，套到拍卖/运输上会把正常合同误筛掉。
        """
        from services.contract_service import count_tab

        base = self._filter_params()
        counts: list[int] = []
        for key in _TAB_KEYS:
            filters = {**base, "blueprint_only": self._blueprint_only if key == "exchange" else False}
            try:
                counts.append(count_tab(self._region_id, _TAB_TYPES[key], filters))
            except Exception:  # 库缺表/被占用 —— 徽标是装饰，不该让整页查询失败
                log.exception("页签条数统计失败, tab=%s", key)
                counts.append(0)
        self._tab_counts = counts

    def _on_loaded(self, tab_key: str, rows: list, error: str) -> None:
        if tab_key != self._tab_key:
            return  # 期间用户换了页签，丢弃过期结果
        self._models[tab_key].set_rows(rows)
        self._loaded_rows = rows
        self._status = error or f"{_TABS[self._tab_index]}: {len(rows):,} 条"
        self._restore_selection(rows)
        self.rowsChanged.emit()

    def _restore_selection(self, rows: list[dict]) -> None:
        """列表刷新后把下方物品面板接回来。

        补齐过程每 500 条就重播一次列表 —— 每次都清空面板的话，用户正在看的那份合同的
        物品会反复消失（旧实现无条件清空，那是只有手动补齐、重启一次的年代）。
        """
        selected = self._selected_contract
        kept = None
        if selected is not None:
            wanted = int(selected.get("contract_id") or 0)
            kept = next((r for r in rows if int(r.get("contract_id") or 0) == wanted), None)
        self._selected_contract = kept
        self._item_model.set_contract(kept)
        if kept is None:
            self._item_model.set_rows([])
            self.itemsChanged.emit()
        else:
            self._load_items(int(kept["contract_id"]), kept.get("region_id"))

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

    # ── 补齐物品 / 发布者名字（价差与图标的前提）──

    @staticmethod
    def _preload_importers() -> None:
        """起补齐线程**之前**，在主线程里把 `services.importers` 整包导完。

        QThread 里现导它会与启动期的其他导入抢同一把模块锁 —— 实测直接
        `_DeadlockError: deadlock detected by _ModuleLock('services.importers.getindustry')`
        （合同页进场即自动补齐时必现：那一刻外壳正在装载其余页面）。手动补齐是启动之后
        才点的，所以从前没暴露。导入只在第一次真正发生，之后是 `sys.modules` 命中。
        """
        import services.importers  # noqa: F401

    def _start_backfill(self, rows: list[dict]) -> None:
        """进页签后自动补齐**当前列表**缺的东西：发布者名字 + 合同物品。

        范围就是当前列表，不是整个星域 —— 一个星域 3.4 万份合同、一份一个请求，
        逐个拉没人等得起；而列表按价格降序，先补上的正好是最该看的那几行。
        结果落库（`items_fetched_at` / `contract_issuers`），所以下次进同一个页签
        无事可做，不会重复拉。已有任务在跑（拉取 / 手动补齐）时不排队，直接跳过。
        """
        if self._busy_worker is not None:
            return
        # 运输合同没有物品（items 端点实测 HTTP 400），但发布者名字照样要补
        wants_items = self._tab_key != "courier"
        issuer_ids = sorted({int(r["issuer_id"]) for r in rows if r.get("issuer_id") and not r.get("issuer_name")})
        contract_ids = [int(r["contract_id"]) for r in rows if r.get("items_fetched_at") is None] if wants_items else []
        if not issuer_ids and not contract_ids:
            return

        from ui_qml.workers.contract_workers import ContractFillWorker

        self._preload_importers()
        self._last_fill_reload_at = 0.0
        worker = ContractFillWorker(self._region_id, self._tab_key, issuer_ids=issuer_ids, contract_ids=contract_ids)
        self._busy_worker = worker
        self._fill_worker = worker
        worker.progress.connect(self._on_fill_progress)
        worker.finished_signal.connect(self._on_fill_done)
        self._status = f"后台补齐中… {len(contract_ids):,} 份合同（可点「停止」）"
        self.rowsChanged.emit()
        spawn(worker)

    @Slot()
    def startFill(self) -> None:
        """补齐**整个星域**的物品与发布者名字。手动按钮走这条，不自动发起。"""
        if self._busy_worker is not None:
            self._status = "已有任务在跑，请先等待或停止"
            self.rowsChanged.emit()
            return
        if self._tab_key == "courier":
            self._status = "运输合同没有物品详情，不需要补齐"
            self.rowsChanged.emit()
            return

        from ui_qml.workers.contract_workers import ContractFillWorker

        self._preload_importers()
        self._last_fill_reload_at = 0.0
        self._status = "正在补齐本星域全部物品…"
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
        if done and done % 500 == 0 and time.monotonic() - self._last_fill_reload_at >= 1.0:
            self._last_fill_reload_at = time.monotonic()
            self._reload_rows()  # 边补边刷新，价差/图标逐行填上（**不再触发自动补齐**）

    def _on_fill_done(self, written: int, message: str) -> None:
        self._busy_worker = None
        self._fill_worker = None
        self._status = message
        self.rowsChanged.emit()
        self._reload_rows()

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
        # 物品表末尾三列（合同价/内容物市价/价差）取自这份合同
        self._item_model.set_contract(data)
        self._item_model.set_rows([])
        self.itemsChanged.emit()
        self._load_items(int(data.get("contract_id") or 0), data.get("region_id"))

    def _load_items(self, contract_id: int, region_id: int | None = None) -> None:
        from ui_qml.workers.contract_workers import ContractItemsLoadWorker

        worker = ContractItemsLoadWorker(
            contract_id,
            int(region_id or self._region_id),
            _PRICE_KEYS[self._price_type_index],
        )
        self._items_worker = worker
        worker.finished_signal.connect(
            lambda items, cid=contract_id, source=worker: self._on_items_loaded(cid, source, items)
        )
        spawn(worker)

    def _on_items_loaded(self, contract_id: int, worker: QObject, items: list) -> None:
        """只接受当前选中合同、且仍是当前明细 worker 的结果。"""
        selected = self._selected_contract
        if worker is not self._items_worker or selected is None:
            return
        if int(selected.get("contract_id") or 0) != contract_id:
            return
        self._item_model.set_rows(items)
        self.itemsChanged.emit()

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
    def copyIssuer(self, row: int) -> None:
        """复制发布者名字 —— 游戏内搜合同只能按发布者搜，合同 ID 搜不到。

        名字是异步补上的：还没解析出来时给出原因，不静默复制空串。
        """
        data = self._row_data(row)
        if not data:
            return
        name = str(data.get("issuer_name") or "")
        if not name:
            self._status = "发布者名字还没解析出来，稍后再试（正在后台补齐）"
            self.rowsChanged.emit()
            return
        self._copy(name, note=f"已复制发布者: {name}")

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
