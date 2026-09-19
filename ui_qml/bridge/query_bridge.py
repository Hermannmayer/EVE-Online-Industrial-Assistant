"""物品查询页 bridge —— QML 与既有服务/worker 之间的唯一通道。

职责边界与 `EstimateBridge` 一致：**业务逻辑仍在 workers / services 里**，
本类只做三件事：把请求转发给既有实现、把结果整理成 QML 好用的形状、
把状态回传给外壳状态栏。不复制任何搜索/格式化逻辑。

**页面形态（用户明确要求）**：候选弹窗**就是**匹配清单 —— 输入即出全部前缀匹配，
点一条直接把它推给详情桥，**没有结果表格**。所以本模块不再有模型、列定义、排序、
右键菜单与复制那一套；`ui_qml/models/query_model(s).py` 也随之删除。

历史项与候选项的处理不同（历史项是**裸查询词**、没有 type_id）：点历史 = 把词填回
输入框并重新拉候选，由用户从候选里选具体物品。

**订单详情弹窗已移除**：它展示的正是详情面板已在实时显示的那份买单/卖单，
订单行格式的纯函数 `order_popup_bridge.order_rows` 仍被 `QueryDetailBridge` 使用。
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core.constants import TRADE_HUB_IDS, TRADE_HUBS
from core.logger import log
from ui_qml.theme import registry as theme

__all__ = ["QueryBridge"]

#: 搜索框防抖（对齐 Widgets 版的 200ms）
_DEBOUNCE_MS = 200

_DEFAULT_STATUS = "输入物品名称或 ID，从候选里选一件查看详情"


class QueryBridge(QObject):
    """物品查询页的 QML 后端。"""

    statusChanged = Signal()
    suggestionsChanged = Signal()
    regionChanged = Signal()

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell
        self._current_query = ""
        self._region_id = 10000002  # Jita，与 DEFAULT_REGION_ID 一致
        self._suggestions: list[dict] = []
        self._history: list[str] = []
        self._busy = False
        self._status_text = _DEFAULT_STATUS
        self._suggest_worker: QObject | None = None
        # 两个子桥**懒建**：`query_detail_bridge` 会拉进 workers/services，
        # 模块级/构造期建它等于每次造桥都加载整条业务链。
        self._detail_bridge: QObject | None = None
        self._dash_bridge: QObject | None = None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._fetch_suggestions)

        # 子桥里的前景/底色是 data() 算出来的**字符串**，QML 绑定不会随主题自己重算，
        # 必须由这里补发（`add_theme_listener` 对绑定方法用弱引用，不会泄漏）
        self._remove_theme_listener = theme.add_theme_listener(self.refreshColors)

    # ── 两态切换与子桥 ────────────────────────────────────────

    def _get_detail(self) -> QObject | None:
        """详情子桥（5 个贸易中心价格 / 订单 / 精炼产物 / 制造材料）。

        页面用 `detail.typeId > 0` 当「已选中一件物品」的判据 —— 它同时也是
        「显示仪表盘还是详情面板」的**唯一**依据，故这里不另设 `hasSelection`。

        导入失败返回 None 而不是抛出去：这个属性是 QML 绑定在求值的，抛异常会让
        **整页**加载失败（外壳只把本页记为暂缺），而少一个面板不该毁掉整页 ——
        QML 侧已按 `detail === null` 写了占位文案。
        """
        if self._detail_bridge is None:
            try:
                from ui_qml.bridge.query_detail_bridge import QueryDetailBridge
            except ImportError:
                log.exception("详情面板桥加载失败，该面板将不可用")
                return None
            self._detail_bridge = QueryDetailBridge(self)
            self._sync_detail_hub()
        return self._detail_bridge

    detail = Property(QObject, _get_detail, constant=True)

    def _get_dashboard(self) -> QObject | None:
        """空闲态的仪表盘子桥（产线详情 / 资产折线图 / 挂单列表）。同 `_get_detail`。"""
        if self._dash_bridge is None:
            try:
                from ui_qml.bridge.query_dashboard_bridge import QueryDashboardBridge
            except ImportError:
                log.exception("空闲态仪表盘桥加载失败，该面板将不可用")
                return None
            self._dash_bridge = QueryDashboardBridge(self)
        return self._dash_bridge

    dashboard = Property(QObject, _get_dashboard, constant=True)

    def _sync_detail_hub(self) -> None:
        """把查询页的区域同步给详情桥，作为精炼 / 材料的价格中心。"""
        if self._detail_bridge is None:
            return
        setter = getattr(self._detail_bridge, "setPriceHubIndex", None)
        if not callable(setter):
            return
        for i, hub in enumerate(TRADE_HUBS):
            if TRADE_HUB_IDS.get(hub) == self._region_id:
                setter(i)
                return

    def _show_detail(self, type_id: int, name: str) -> None:
        """把选中的物品推给详情桥（桥不可用时静默跳过）。"""
        bridge = self._get_detail()
        if bridge is None:
            return
        setter = getattr(bridge, "setItem", None)
        if callable(setter):
            setter(int(type_id), str(name))

    def _clear_detail(self) -> None:
        clearer = getattr(self._detail_bridge, "clear", None)
        if callable(clearer):
            clearer()

    @Slot()
    def shutdown(self) -> None:
        """停掉两个子桥的在途取数线程。**页面被销毁时必须调**（见 `QueryDetailBridge.shutdown`）。

        只处理**已经建出来**的子桥 —— 这里绝不能读 `self.detail` / `self.dashboard`
        （那两个 getter 会把没用到过的子桥无谓地创建出来，连带 import 整条业务链）。
        """
        for sub in (self._detail_bridge, self._dash_bridge):
            if sub is None:
                continue
            stop = getattr(sub, "shutdown", None)
            if callable(stop):
                stop()

    # ── 选项 ──────────────────────────────────────────────────

    regions = Property(list, lambda self: list(TRADE_HUBS), constant=True)

    def _get_region_index(self) -> int:
        hubs = list(TRADE_HUBS)
        for i, hub in enumerate(hubs):
            if TRADE_HUB_IDS.get(hub) == self._region_id:
                return i
        return 0

    regionIndex = Property(int, _get_region_index, notify=regionChanged)

    @Slot(int)
    def setRegionIndex(self, index: int) -> None:
        """换查询区域：详情桥的价格中心跟着走，订单按新区域重取。

        精炼与制造材料由 `setPriceHubIndex` 自己重算（见 `QueryDetailBridge`），
        这里只需再补一次订单 —— 它的 region 是从价格中心推出来的。
        """
        hubs = list(TRADE_HUBS)
        if not 0 <= index < len(hubs):
            return
        region_id = TRADE_HUB_IDS.get(hubs[index], 10000002)
        if region_id == self._region_id:
            return
        self._region_id = region_id
        self.regionChanged.emit()
        self._sync_detail_hub()
        reload_orders = getattr(self._detail_bridge, "reloadOrders", None)
        if callable(reload_orders):
            reload_orders()

    # ── 状态 ──────────────────────────────────────────────────

    def _get_busy(self) -> bool:
        return self._busy

    busy = Property(bool, _get_busy, notify=statusChanged)
    statusText = Property(str, lambda self: self._status_text, notify=statusChanged)

    def set_status(self, text: str) -> None:
        self._status_text = str(text)
        self.statusChanged.emit()
        self._push_shell_status(text)

    def _push_shell_status(self, text: str) -> None:
        setter = getattr(self._shell, "set_status", None)
        if callable(setter):
            setter(text)

    # ── 输入 / 候选 ────────────────────────────────────────────

    searchText = Property(str, lambda self: self._current_query, notify=statusChanged)

    @Slot(str)
    def onTextChanged(self, text: str) -> None:
        """输入框每次改动：够长就防抖查候选，清空则回落到搜索历史。"""
        self._current_query = str(text)
        if len(text) >= 1:
            self._debounce.start(_DEBOUNCE_MS)
        else:
            self._suggestions = []
            self.suggestionsChanged.emit()
            self._show_history()

    suggestions = Property(list, lambda self: self._suggestions, notify=suggestionsChanged)
    history = Property(list, lambda self: self._history, notify=suggestionsChanged)

    @Slot()
    def _fetch_suggestions(self) -> None:
        from ui_qml.workers.query_workers import SuggestionWorker

        query = self._current_query.strip()
        if not query:
            return
        worker = SuggestionWorker(query, self)
        self._suggest_worker = worker
        worker.finished_signal.connect(self._on_suggestions)
        worker.start()

    def _on_suggestions(self, items: list) -> None:
        from ui_qml.icon_cache import icon_url

        # Worker 给的是 (type_id, display, zh_name) 三元组
        #
        # `query` 是**可搜的查询串**，与 `text`（展示串）分开存 —— 即使两者现在同值
        # （展示串就是物品名）也不合并：展示串以后怎么改都不该影响拿去 `LIKE` 匹配的那串。
        # 中文名优先，没有就退回展示串。
        #
        # `icon` 是物品图标的 `file://` URL；图标 PNG 还没下载到本地时是空串，
        # QML 侧按空串就不显示（`Image` 拿到空串不刷警告，见 `icon_cache.icon_url`）。
        self._suggestions = [
            {"id": int(tid), "text": str(display), "query": str(zh or display), "icon": icon_url(int(tid))}
            for tid, display, zh in items
        ]
        self.suggestionsChanged.emit()

    def _show_history(self) -> None:
        from core.search_history import load_search_history

        #: 历史文件里存的是 `{"query": ..., "time": ...}` **字典**，要取 `query` 字段。
        #: 原先是 `[str(h) for h in ...]` —— 等于把整条 dict 连时间戳一起渲染成历史项，
        #: 用户看到的就是 `{'query': '毒蜥级', 'time': 1758...}`。字典还要过一道类型检查：
        #: 历史文件是用户可改的纯文本，读到脏数据不该让整个候选弹窗炸掉。
        self._history = [
            str(h.get("query") or "") for h in load_search_history() if isinstance(h, dict) and h.get("query")
        ]
        self.suggestionsChanged.emit()

    @Slot(str)
    def pickSuggestion(self, text: str) -> None:
        """候选/历史被点中。

        两种来源处理不同：
          - **候选项**带 type_id → 直接推给详情桥（页面不经过任何搜索/表格）；
          - **历史项**是用户以前搜过的**裸查询词**，没有 type_id → 填回输入框并重新拉候选，
            由用户从候选里挑具体物品（历史里存的词可能对应多件物品，替用户猜一件不如让他选）。
        """
        from core.search_history import add_search_history

        text = str(text)
        picked = next((item for item in self._suggestions if str(item.get("text")) == text), None)
        if picked is None:
            self._current_query = text
            self.statusChanged.emit()
            self._suggestions = []
            self.suggestionsChanged.emit()
            self._fetch_suggestions()
            return

        type_id = int(picked.get("id") or 0)
        name = str(picked.get("query") or text)
        if not type_id:
            return
        self._current_query = name
        self._suggestions = []
        self.suggestionsChanged.emit()
        self._debounce.stop()  # 别让候选在详情出来后 200ms 又浮起来盖住它
        add_search_history(name)
        self._show_detail(type_id, name)
        self.set_status(f"已选中 {name}")

    @Slot()
    def showHistory(self) -> None:
        """空输入框被按下时由 QML 调：把历史读出来填进候选弹窗。

        为什么需要这个入口：`_show_history` 原先**只**在「文本变成空」时被 `onTextChanged`
        调到。可刚进页面时输入框本来就是空的，压根没有文本变化 —— `_history` 一直是 `[]`，
        点输入框什么也不显示；反倒点「清空」会把 `text` 置空、触发一次 `onTextChanged`，
        历史才冒出来。这里补上「空着但没变过」的那条路。
        """
        self._suggestions = []
        self._show_history()

    @Slot()
    def clearHistory(self) -> None:
        from core.search_history import clear_search_history

        clear_search_history()
        self._suggestions = []
        self._history = []
        self.suggestionsChanged.emit()

    # ── 清空 ──────────────────────────────────────────────────

    @Slot()
    def clear(self) -> None:
        """清空输入与当前选中物品 —— 详情面板随之让位给空闲态仪表盘。"""
        self._current_query = ""
        self._suggestions = []
        self._clear_detail()
        self.set_status("已清空")
        self.suggestionsChanged.emit()

    # ── 子窗口 ────────────────────────────────────────────────

    @Slot()
    def openAllItems(self) -> None:
        """打开全物品浏览器（非模态独立窗，单实例复用）。

        复用靠 `dialog_host.find_modeless` 查保活表，**不用实例属性缓存** ——
        独立窗关掉即销毁（`WA_DeleteOnClose`），缓存下来的 Python 包装器会变成
        悬空对象，下次 `show()` 直接抛「Internal C++ object already deleted」。
        """
        from ui_qml.bridge.all_items_bridge import AllItemsQmlDialog as AllItemsDialog
        from ui_qml.dialog_host import find_modeless

        dialog = find_modeless(AllItemsDialog)
        if dialog is None:
            dialog = AllItemsDialog()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    @Slot()
    def openBatchPrice(self) -> None:
        from ui_qml.bridge.batch_price_bridge import BatchPriceQmlDialog as BatchPriceDialog

        parent = None
        BatchPriceDialog(parent).exec()

    # ── 主题 ──────────────────────────────────────────────────

    @Slot()
    def refreshColors(self) -> None:
        for sub in (self._detail_bridge, self._dash_bridge):
            if sub is not None:
                notify = getattr(sub, "changed", None)
                if notify is not None:
                    notify.emit()
        self.statusChanged.emit()
