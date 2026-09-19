"""物品查询页 bridge —— QML 与既有服务/worker 之间的唯一通道。

职责边界与 `EstimateBridge` 一致：**业务逻辑仍在 workers / services 里**，
本类只做三件事：把请求转发给既有实现、把结果整理成 QML 好用的形状、
把状态回传给外壳状态栏。不复制任何搜索/格式化逻辑。

对照的 Widgets 版是 `ui_pyside6/views/query/query_page.py`，行为逐项对齐。

**订单详情弹窗已移除**：双击结果行原本弹一个订单窗口，但它展示的正是下方详情面板
已经在实时显示的那份买单/卖单（同缓存、同格式化函数），属于重复。右键菜单里的
「查看实时订单」与它同源，一并去掉。订单行格式的纯函数 `order_popup_bridge.order_rows`
仍被 `QueryDetailBridge` 使用，故那个模块保留。
"""

from __future__ import annotations

import weakref

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from core.constants import TRADE_HUB_IDS, TRADE_HUBS
from core.logger import log
from ui_qml.models.query_qml_model import QueryQmlModel
from ui_qml.theme import registry as theme

__all__ = ["QueryBridge"]

#: 搜索框防抖（对齐 Widgets 版的 200ms）
_DEBOUNCE_MS = 200

_DEFAULT_STATUS = "输入物品名称或 ID 后搜索，点选一行查看下方详情"


class QueryBridge(QObject):
    """物品查询页的 QML 后端。"""

    statusChanged = Signal()
    resultsChanged = Signal()
    suggestionsChanged = Signal()
    regionChanged = Signal()
    sortChanged = Signal()
    #: 当前行变化（结果表选中 → 详情面板换物品）
    selectionChanged = Signal()

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell
        self._model = QueryQmlModel()
        self._current_query = ""
        self._region_id = 10000002  # Jita，与 DEFAULT_REGION_ID 一致
        self._suggestions: list[dict] = []
        self._history: list[str] = []
        self._busy = False
        self._count_text = ""
        self._status_text = _DEFAULT_STATUS
        self._current_row = -1
        self._search_worker: QObject | None = None
        self._suggest_worker: QObject | None = None
        # 两个子桥**懒建**：`query_detail_bridge` 会拉进 workers/services，
        # 模块级/构造期建它等于每次造桥都加载整条业务链。
        self._detail_bridge: QObject | None = None
        self._dash_bridge: QObject | None = None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._fetch_suggestions)

        # 模型被重置就让 `hasResults` 重新求值 —— 它是两态切换（仪表盘 ↔ 结果区）的**唯一**
        # 判据，漏发一次的后果是「已经搜出结果，界面还停在空闲态仪表盘」，不报任何错。
        # 接在模型上而不是只在 `_on_search_done` 里发，是为了让「谁写的模型」都不影响切态。
        #
        # ⚠️ **必须用弱引用闭包，不能直接接 `self.resultsChanged.emit`**：那样模型会持有
        # 一个绑定到本桥的可调用对象，而本桥又持有模型 → 跨 Qt 所有权的引用环，
        # 进程**退出时**崩（实测：单跑 `tests/test_qml_query.py` 27 条全过、退出码却是 127）。
        # 本仓 `theme.add_theme_listener` 对绑定方法用弱引用是同一个理由。
        bridge_ref = weakref.ref(self)

        def _notify_results_changed() -> None:
            bridge = bridge_ref()
            if bridge is not None:
                bridge.resultsChanged.emit()

        self._model.modelReset.connect(_notify_results_changed)
        # 表格里的前景/底色是 data() 算出来的**字符串**，QML 绑定不会随主题自己重算，
        # 必须由这里补发 dataChanged（add_theme_listener 对绑定方法用弱引用，不会泄漏）
        self._remove_theme_listener = theme.add_theme_listener(self.refreshColors)

    # ── 模型 ──────────────────────────────────────────────────

    def _get_model(self) -> QueryQmlModel:
        return self._model

    model = Property(QObject, _get_model, constant=True)

    # ── 两态切换与子桥 ────────────────────────────────────────

    def _get_has_results(self) -> bool:
        """有没有查询结果。**只说实话**，不含「正在查」。

        页面那边也**刻意不把 `busy` 掺进判据**（`QueryPage.qml` 的 `workArea.idle`）：
        掺进去会让「搜索但没搜到」来回翻两次 —— 查询中切到结果区、查出 0 条又切回仪表盘，
        用户看到的是「两个界面来回抢显示」。只认有无结果，空手而归就原地不动。
        """
        return int(self._model.rowCount()) > 0

    hasResults = Property(bool, _get_has_results, notify=resultsChanged)

    def _get_detail(self) -> QObject | None:
        """结果态的详情子桥（5 个贸易中心价格 / 订单 / 精炼产物 / 制造材料）。

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

    def _get_current_type_id(self) -> int:
        data = self._row(self._current_row)
        return int(data["type_id"]) if data else 0

    currentTypeId = Property(int, _get_current_type_id, notify=selectionChanged)

    def _get_current_name(self) -> str:
        data = self._row(self._current_row)
        if not data:
            return ""
        return str(data.get("zh") or data.get("en") or "")

    currentName = Property(str, _get_current_name, notify=selectionChanged)

    def _sync_detail_hub(self) -> None:
        """把查询页的区域同步给详情桥，作为精炼/材料的价格中心。"""
        if self._detail_bridge is None:
            return
        setter = getattr(self._detail_bridge, "setPriceHubIndex", None)
        if not callable(setter):
            return
        for i, hub in enumerate(TRADE_HUBS):
            if TRADE_HUB_IDS.get(hub) == self._region_id:
                setter(i)
                return

    def _push_selection(self) -> None:
        """把当前行推给详情桥（桥不可用时静默跳过）。"""
        if self._detail_bridge is None:
            return
        data = self._row(self._current_row)
        if data:
            setter = getattr(self._detail_bridge, "setItem", None)
            if callable(setter):
                setter(int(data["type_id"]), self._get_current_name())
        else:
            self._clear_detail()

    def _clear_detail(self) -> None:
        clearer = getattr(self._detail_bridge, "clear", None)
        if callable(clearer):
            clearer()

    @Slot(int)
    def selectRow(self, row: int) -> None:
        """当前行变化 —— QML 的 `currentRow` 只是高亮，这里是**取数**的驱动。

        分成两件事是刻意的：高亮每帧都可能变，取数（5 次取价 + 精炼 + BOM）不能在
        拖动/滚动时反复触发。QML 只在点击/右键时调本槽。
        """
        if row == self._current_row:
            return
        self._current_row = int(row)
        self.selectionChanged.emit()
        self._push_selection()

    def _clear_selection(self) -> None:
        self._current_row = -1
        self.selectionChanged.emit()
        self._clear_detail()

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

    @Property(list, constant=True)
    def columns(self) -> list[dict]:
        """列定义（标题 + 初始宽度）—— 单一来源在 `query_models.COLUMNS`。"""
        from ui_qml.models.query_models import COLUMNS

        return [{"title": title, "width": width} for title, width in COLUMNS]

    def _get_region_index(self) -> int:
        hubs = list(TRADE_HUBS)
        for i, hub in enumerate(hubs):
            if TRADE_HUB_IDS.get(hub) == self._region_id:
                return i
        return 0

    regionIndex = Property(int, _get_region_index, notify=regionChanged)

    @Slot(int)
    def setRegionIndex(self, index: int) -> None:
        hubs = list(TRADE_HUBS)
        if not 0 <= index < len(hubs):
            return
        region_id = TRADE_HUB_IDS.get(hubs[index], 10000002)
        if region_id == self._region_id:
            return
        self._region_id = region_id
        self.regionChanged.emit()
        self._sync_detail_hub()
        if self._current_query:
            self.search()

    # ── 状态 ──────────────────────────────────────────────────

    def _get_busy(self) -> bool:
        return self._busy

    busy = Property(bool, _get_busy, notify=statusChanged)
    countText = Property(str, lambda self: self._count_text, notify=statusChanged)
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
        # Worker 给的是 (type_id, display, zh_name) 三元组
        #
        # `query` 是**可搜的查询串**，与 `text`（展示串）分开存 —— 即使两者现在同值
        # （展示串就是物品名）也不合并：展示串以后怎么改都不该影响拿去 `LIKE` 匹配的那串，
        # 见 `pickSuggestion`。中文名优先，没有就退回展示串。
        self._suggestions = [
            {"id": int(tid), "text": str(display), "query": str(zh or display)} for tid, display, zh in items
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
        """候选/历史被点中：立刻搜索它。

        展示串与可搜的查询串**分开取**（`text` vs `query`），不是同义反复：两者现在
        恰好同值（展示串就是物品名），但历史上展示串曾形如 `[17715] 毒蜥级 (Gila)`
        ——拿整串去 `LIKE` 匹配名字必然 0 条，用户实测「点候选之后永远显示未找到物品」。
        保留这条分离，展示串以后怎么改都不会再犯同一个错。
        历史项本来就是用户搜过的串，原样使用（`picked` 为 None 时走 `text`）。
        """
        text = str(text)
        picked = next((item for item in self._suggestions if str(item.get("text")) == text), None)
        self._current_query = str(picked.get("query") or text) if picked else text
        self._suggestions = []
        self.suggestionsChanged.emit()
        self.search()

    @Slot()
    def showHistory(self) -> None:
        """空输入框被聚焦时由 QML 调：把历史读出来填进候选弹窗。

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

    # ── 搜索 ──────────────────────────────────────────────────

    @Slot()
    def search(self) -> None:
        from core.search_history import add_search_history
        from ui_qml.workers.query_workers import SearchWorker

        query = self._current_query.strip()
        self._suggestions = []
        self.suggestionsChanged.emit()
        # 停掉输入防抖：不停的话，敲完字 200ms 后候选弹窗还会浮起来，
        # 正好盖在刚出来的结果上（点「搜索」后立刻回车同理会闪一下候选）
        self._debounce.stop()
        if not query:
            self.set_status("请输入物品名称或 ID")
            return

        self._current_query = query
        add_search_history(query)
        self._busy = True
        self.statusChanged.emit()

        worker = SearchWorker(query, self._region_id, self)
        self._search_worker = worker
        worker.finished_signal.connect(self._on_search_done)
        worker.error_signal.connect(self._on_search_error)
        worker.start()

    def _on_search_done(self, rows: list, is_fallback: bool) -> None:
        from ui_qml.models.query_models import format_search_rows

        self._busy = False
        if not rows:
            self._count_text = ""
            self._model.set_rows([])
            self._clear_selection()
            self.set_status(f"未找到包含「{self._current_query}」的物品")
            self.resultsChanged.emit()
            return

        self._model.set_rows(format_search_rows(rows, is_fallback))
        self._clear_selection()
        self._count_text = f"共 {len(rows)} 条结果" + (" (仅基本信息)" if is_fallback else "")
        self._status_text = "就绪 — 右键行可查看操作菜单，点选一行看下方详情"
        self.statusChanged.emit()
        self.resultsChanged.emit()

    def _on_search_error(self, error: str) -> None:
        self._busy = False
        self.set_status(f"查询出错: {error}")

    @Slot()
    def clear(self) -> None:
        self._current_query = ""
        self._suggestions = []
        self._model.set_rows([])
        self._count_text = ""
        self._clear_selection()
        self.set_status("已清空")
        self.resultsChanged.emit()
        self.suggestionsChanged.emit()

    # ── 排序 / 行交互 ──────────────────────────────────────────

    @Slot(int, bool)
    def sortBy(self, column: int, ascending: bool) -> None:
        from PySide6.QtCore import Qt

        order = Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder
        self._model.sort(column, order)
        self.sortChanged.emit()
        self.resultsChanged.emit()

    # 排序状态暴露成属性而不是 Slot 调用：QML 的绑定**不追踪 Slot 内部的属性读取**，
    # 写成 `bridge.sortIndicator(col)` 表头箭头不会跟着刷新（与 Theme.fs 同一类坑）。
    sortColumn = Property(int, lambda self: self._model.sort_column, notify=sortChanged)
    sortAscending = Property(bool, lambda self: self._model.sort_ascending, notify=sortChanged)

    def _row(self, row: int) -> dict | None:
        return self._model.get_row(int(row))

    @Slot(int)
    def viewManufacturing(self, type_id: int) -> None:
        """切到工业页看该物品的制造配方（外壳仍是 Widgets，走 ShellBridge 的导航）。"""
        navigate = getattr(self._shell, "navigate_to", None)
        if callable(navigate) and navigate("industry"):
            self.set_status(f"已切换到工业页查看 Type ID: {type_id}")
        else:
            self.set_status(f"无法跳转，Type ID: {type_id}")

    @Slot(int)
    def copyName(self, row: int) -> None:
        data = self._row(row)
        if data:
            self._copy(data.get("zh") or data.get("en") or str(data.get("type_id", "")))

    @Slot(int)
    def copyTypeId(self, row: int) -> None:
        data = self._row(row)
        if data:
            self._copy(str(data.get("type_id", "")))

    @Slot(int)
    def copyBuy(self, row: int) -> None:
        data = self._row(row)
        if data:
            self._copy(str(data.get("buy_str", "—")).split(" (")[0])

    @Slot(int)
    def copySell(self, row: int) -> None:
        data = self._row(row)
        if data:
            self._copy(str(data.get("sell_str", "—")).split(" (")[0])

    @Slot(int)
    def copyRowTsv(self, row: int) -> None:
        data = self._row(row)
        if not data:
            return
        parts = [
            str(data.get("type_id", "")),
            str(data.get("zh", "")),
            str(data.get("en", "")),
            str(data.get("group", "")),
            str(data.get("buy_str", "—")),
            str(data.get("sell_str", "—")),
            str(data.get("avg_price_str", "—")),
            str(data.get("vol_str", "—")),
        ]
        self._copy("\t".join(parts), note="已复制整行数据 (TSV 格式)")

    def _copy(self, text: str, note: str = "") -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self.set_status(note or f"已复制: {text}")

    @Slot(int, result=dict)
    def menuState(self, row: int) -> dict:
        """右键菜单要的状态：决定哪几项可用（对齐 Widgets 版按值决定加不加那一项）。"""
        data = self._row(row) or {}
        return {
            "valid": bool(data),
            "hasBuy": data.get("buy_str") not in (None, "", "—"),
            "hasSell": data.get("sell_str") not in (None, "", "—"),
            "typeId": data.get("type_id"),
        }

    # ── 子窗口（仍是 Widgets，阶段 4 迁移）────────────────────

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
        self._model.refresh_colors()
        # 两个子桥的颜色也是 data() 算出来的字符串，主题切换要一起补发，
        # 否则它们在浅色主题下留着深色底的前景色（与模型同一类坑）
        for sub in (self._detail_bridge, self._dash_bridge):
            if sub is not None:
                notify = getattr(sub, "changed", None)
                if notify is not None:
                    notify.emit()
        self.statusChanged.emit()
        self.resultsChanged.emit()
