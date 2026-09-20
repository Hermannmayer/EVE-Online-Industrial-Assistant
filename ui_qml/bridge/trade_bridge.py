"""贸易页 bridge —— QML 与 worker 之间的唯一通道。

页面只做一件事：**A 贸易中心 → B 贸易中心的全品类价差排行**。
「开始计算」的时序是「先刷新两个中心的价格、再算排行」——

  `analyze()` → `shell.request_price_update([A, B], on_done)` → `_on_price_refreshed`
             → `CrossRegionRankWorker` → 出表

刷新走外壳那套（`ShellWindow.request_price_update`），复用它的单写者排队、进度条与
缓存失效；**不自己起 `PriceUpdateWorker`**，否则两处同时写 `market.db` 会撞锁。

⚠️ `PriceUpdateWorker.finished_signal` 里的 `success` **不可信**：
`services.importers.getprices.run_price_update` 在拉取失败时不抛异常（失败的 region
被跳过、旧价保留），照常返回。所以「这次刷新到底生没生效」只能**回头查价格时间**
（`fetch_hub_fetch_time`），不能信那个布尔值。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from core.constants import TRADE_HUB_IDS
from ui_qml.models.trade_rank_model import COLUMNS, TradeRankQmlModel

__all__ = ["TradeBridge"]

_HUBS = list(TRADE_HUB_IDS.keys())
#: 价格类型下拉（顺序即 index）：从 A 默认「卖单」（买入要付卖单价）、到 B 默认「买单」
_SIDES = ("sell", "buy")
_SIDE_LABELS = ("卖单", "买单")

_ALL_CATEGORY = {"id": 0, "name": "全部品类"}
#: 挂单变化的观察窗口（天）
_CHANGE_DAYS = 7
#: 超过这个分钟数就认为「刚点的刷新没生效」
_STALE_MINUTES = 60

#: 「只看有对手盘的」下限档位（件）。**0 = 不限**。
#: 第 1 档（≥1）就能滤掉 `save_prices` 混进来的 ESI 基准价兜底行 ——
#: 那种行两侧价格看着都很高，对手盘挂单量却是 0，根本成交不了。
_LIQUIDITY_THRESHOLDS = (0, 1, 10, 100)
_LIQUIDITY_LABELS = ("不限", "两侧 ≥ 1", "两侧 ≥ 10", "两侧 ≥ 100")
_LIQUIDITY_DEFAULT = 1


def _age_text(ts: str | None) -> str:
    """`fetch_time` → 「刚刚 / 35 分钟前 / 3 天前」。解析不了就原样回显。"""
    if not ts:
        return "无价格"
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(ts)
    minutes = (datetime.now(UTC).replace(tzinfo=None) - dt).total_seconds() / 60
    if minutes < 2:
        return "刚刚"
    if minutes < 120:
        return f"{minutes:.0f} 分钟前"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.0f} 小时前"
    return f"{hours / 24:.0f} 天前"


def _age_minutes(ts: str | None) -> float:
    if not ts:
        return float("inf")
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return float("inf")
    return (datetime.now(UTC).replace(tzinfo=None) - dt).total_seconds() / 60


def _category_id(cat: dict) -> int:
    """分类项里的 id（非整数一律当 0 = 全部品类）。"""
    raw = cat.get("id")
    return raw if isinstance(raw, int) else 0


class TradeBridge(QObject):
    """贸易页的 QML 后端。"""

    stateChanged = Signal()  # 工具栏 / 状态栏 / 计算中标志
    rowsChanged = Signal()  # 结果表整体换了

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell

        self._from_index = _HUBS.index("Jita")
        self._to_index = _HUBS.index("Amarr")
        self._from_side = 0  # 卖单
        self._to_side = 1  # 买单
        self._category_index = 0
        self._categories = self._load_categories()
        #: 「只看赚钱的」——价差 ≤ 0 的倒卖没有意义
        self._hide_unprofitable = True
        #: 「只看有对手盘的」档位下标（见 `_LIQUIDITY_THRESHOLDS`）
        self._liquidity_index = _LIQUIDITY_DEFAULT

        self._model = TradeRankQmlModel()
        #: 全量结果（未筛选）。筛选在内存里做 —— 切筛选项不必重算 SQL
        self._rows: list[dict] = []
        #: 筛选后真正进表的那批
        self._visible: list[dict] = []
        self._empty_hint = "还没有数据 — 选好两个贸易中心，点「开始计算」"
        self._status = "选好两个贸易中心，点「开始计算」"
        self._hint = ""
        self._busy = False
        #: 计算代次 —— 参数中途被改时，回来的旧结果靠它丢弃
        self._gen = 0
        self._worker: QObject | None = None

        #: `TradeCartController`（外壳的懒建单例）—— 用 `Any` 是因为桥不该反向依赖 views，
        #: 而它只在 `cartSummary` / `addToCart` / `openCart` 三处被鸭子类型调用。
        self._cart: Any = None
        cart = getattr(shell, "trade_cart", None)
        if callable(cart):
            try:
                self._cart = cart()
                self._cart.changed.connect(self._on_cart_changed)
            except Exception:
                # 购物车建不起来（QML 缺失等）不该拖垮整页
                self._cart = None

    # ═══════════════════════════════════════════════════════════
    #  工具栏
    # ═══════════════════════════════════════════════════════════

    hubs = Property(list, lambda self: list(_HUBS), constant=True)
    sideLabels = Property(list, lambda self: list(_SIDE_LABELS), constant=True)
    categories = Property(list, lambda self: list(self._categories), constant=True)
    columns = Property(
        list,
        lambda self: [{"title": t, "width": w} for t, w, _ in COLUMNS],
        constant=True,
    )
    actionColumn = Property(int, lambda self: len(COLUMNS) - 1, constant=True)

    fromIndex = Property(int, lambda self: self._from_index, notify=stateChanged)
    toIndex = Property(int, lambda self: self._to_index, notify=stateChanged)
    fromSideIndex = Property(int, lambda self: self._from_side, notify=stateChanged)
    toSideIndex = Property(int, lambda self: self._to_side, notify=stateChanged)
    categoryIndex = Property(int, lambda self: self._category_index, notify=stateChanged)
    busy = Property(bool, lambda self: self._busy, notify=stateChanged)
    statusText = Property(str, lambda self: self._status, notify=stateChanged)
    hintText = Property(str, lambda self: self._hint, notify=stateChanged)
    emptyHint = Property(str, lambda self: self._empty_hint, notify=rowsChanged)
    #: 结果表是否为空（按**筛选后**算）—— QML 靠它决定要不要盖那条提示。
    #: 必须走 Property 而不是 QML 里调 `model.rowCount()`：函数调用不被绑定依赖追踪，
    #: 出结果后提示不会消失（不报错，只是不动）。
    isEmpty = Property(bool, lambda self: not self._visible, notify=rowsChanged)

    # ── 筛选项 ──────────────────────────────────────────────

    hideUnprofitable = Property(bool, lambda self: self._hide_unprofitable, notify=stateChanged)
    liquidityOptions = Property(list, lambda self: list(_LIQUIDITY_LABELS), constant=True)
    liquidityIndex = Property(int, lambda self: self._liquidity_index, notify=stateChanged)

    @Slot(bool)
    def setHideUnprofitable(self, checked: bool) -> None:
        if bool(checked) != self._hide_unprofitable:
            self._hide_unprofitable = bool(checked)
            self._apply_filters()

    @Slot(int)
    def setLiquidityIndex(self, index: int) -> None:
        if 0 <= index < len(_LIQUIDITY_THRESHOLDS) and index != self._liquidity_index:
            self._liquidity_index = index
            self._apply_filters()

    def _apply_filters(self) -> None:
        """按筛选项从全量结果里挑出可见行（内存里做，不重算 SQL）。"""
        rows = self._rows
        if self._hide_unprofitable:
            rows = [r for r in rows if float(r.get("spread") or 0) > 0]
        threshold = _LIQUIDITY_THRESHOLDS[self._liquidity_index]
        if threshold:
            # 两侧都要有对手盘：A 侧买得到、B 侧卖得掉，缺一边这单就成不了
            rows = [r for r in rows if min(int(r.get("va") or 0), int(r.get("vb") or 0)) >= threshold]
        self._visible = rows
        self._model.set_rows(rows)
        self._status = self._status_text()
        self._empty_hint = (
            "当前筛选下没有符合条件的物品 — 放宽「筛选项」，或点「开始计算」重算"
            if self._rows and not rows
            else "还没有数据 — 选好两个贸易中心，点「开始计算」"
        )
        self.rowsChanged.emit()
        self.stateChanged.emit()

    @Slot(int)
    def setFromIndex(self, index: int) -> None:
        if 0 <= index < len(_HUBS) and index != self._from_index:
            self._from_index = index
            self._invalidate()
            self.stateChanged.emit()

    @Slot(int)
    def setToIndex(self, index: int) -> None:
        if 0 <= index < len(_HUBS) and index != self._to_index:
            self._to_index = index
            self._invalidate()
            self.stateChanged.emit()

    @Slot(int)
    def setFromSideIndex(self, index: int) -> None:
        if 0 <= index < len(_SIDES) and index != self._from_side:
            self._from_side = index
            self._invalidate()
            self.stateChanged.emit()

    @Slot(int)
    def setToSideIndex(self, index: int) -> None:
        if 0 <= index < len(_SIDES) and index != self._to_side:
            self._to_side = index
            self._invalidate()
            self.stateChanged.emit()

    @Slot(int)
    def setCategoryIndex(self, index: int) -> None:
        if 0 <= index < len(self._categories) and index != self._category_index:
            self._category_index = index
            self.stateChanged.emit()

    @Slot()
    def swapDirection(self) -> None:
        """切换方向：两个中心与各自的价格类型一起对调。"""
        self._from_index, self._to_index = self._to_index, self._from_index
        self._from_side, self._to_side = self._to_side, self._from_side
        self._invalidate()
        self.stateChanged.emit()

    # ═══════════════════════════════════════════════════════════
    #  计算
    # ═══════════════════════════════════════════════════════════

    model = Property(QObject, lambda self: self._model, constant=True)

    @Slot()
    def analyze(self) -> None:
        """「开始计算」：先刷新两个中心的价格，回来后算排行。"""
        if self._busy:
            return
        self._gen += 1
        gen = self._gen
        self._busy = True
        self._hint = ""
        self._status = f"正在刷新 {self._hub(self._from_index)} / {self._hub(self._to_index)} 的价格..."
        self.stateChanged.emit()

        request = getattr(self._shell, "request_price_update", None)
        if not callable(request):
            # 没有外壳（测试 / 独立使用）：直接算，不刷新
            self._start_rank(gen)
            return
        request([self._hub(self._from_index), self._hub(self._to_index)], self._on_price_refreshed_gen(gen))

    def _on_price_refreshed_gen(self, gen: int):
        def _cb(regions: object, message: object) -> None:
            self._on_price_refreshed(gen)

        return _cb

    def _on_price_refreshed(self, gen: int) -> None:
        if gen != self._gen or self._busy is False:
            return  # 用户中途改了参数，这一轮作废
        self._start_rank(gen)

    def _start_rank(self, gen: int) -> None:
        from ui_qml.workers.trade_workers import CrossRegionRankWorker

        self._status = "正在计算排行..."
        self.stateChanged.emit()

        group_ids = self._selected_group_ids()
        worker = CrossRegionRankWorker(
            region_a=TRADE_HUB_IDS[self._hub(self._from_index)],
            region_b=TRADE_HUB_IDS[self._hub(self._to_index)],
            side_a=_SIDES[self._from_side],
            side_b=_SIDES[self._to_side],
            group_ids=group_ids,
            change_days=_CHANGE_DAYS,
        )
        self._worker = worker
        worker.finished_signal.connect(lambda rows: self._on_rank(gen, rows))
        worker.start()

    def _on_rank(self, gen: int, rows: list) -> None:
        if gen != self._gen:
            return  # 过期结果：参数已经变过了
        self._busy = False
        self._rows = list(rows or [])
        self._apply_filters()

    def _status_text(self) -> str:
        hub_a = self._hub(self._from_index)
        hub_b = self._hub(self._to_index)
        if not self._rows:
            return "选好两个贸易中心，点「开始计算」"
        # 筛掉多少要看得见 —— 否则「只有 200 行」会被当成数据缺失
        count = (
            f"{len(self._visible)} / {len(self._rows)} 行（已筛选）"
            if len(self._visible) != len(self._rows)
            else f"{len(self._rows)} 行"
        )
        times = self._fetch_times()
        age_a = times.get(TRADE_HUB_IDS[hub_a])
        age_b = times.get(TRADE_HUB_IDS[hub_b])
        stale = max(_age_minutes(age_a), _age_minutes(age_b)) >= _STALE_MINUTES
        # 「刷新没生效」只能这样看出来 —— worker 的 success 标志对失败不敏感
        tail = "  ·  价格未更新，用的是本地缓存" if stale else ""
        return f"{count}  ·  {hub_a} {_age_text(age_a)} / {hub_b} {_age_text(age_b)}{tail}"

    def _fetch_times(self) -> dict:
        from services.market_browser_service import fetch_hub_fetch_time

        try:
            return fetch_hub_fetch_time(
                [TRADE_HUB_IDS[self._hub(self._from_index)], TRADE_HUB_IDS[self._hub(self._to_index)]]
            )
        except Exception:
            from core.logger import log

            log.exception("读取各中心价格时间失败")
            return {}

    # ═══════════════════════════════════════════════════════════
    #  排序
    # ═══════════════════════════════════════════════════════════

    sortColumn = Property(int, lambda self: self._model.sortColumn(), notify=rowsChanged)
    sortAscending = Property(bool, lambda self: not self._model.sortDescending(), notify=rowsChanged)

    @Slot(int)
    def sortBy(self, column: int) -> None:
        from PySide6.QtCore import Qt

        if column == self._model.sortColumn():
            ascending = self._model.sortDescending()  # 再点一次反向
        else:
            ascending = column in (1, 2)  # 名称列默认升序，数值列默认降序
        self._model.sort(
            column,
            Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder,
        )
        self.rowsChanged.emit()

    # ═══════════════════════════════════════════════════════════
    #  购物车
    # ═══════════════════════════════════════════════════════════

    @Property(str, notify=stateChanged)
    def cartSummary(self) -> str:
        if self._cart is None:
            return ""
        t = self._cart.totals()  # type: ignore[attr-defined]
        if not t["count"]:
            return "购物车为空"
        return f"购物车 {t['count']} 项 · 金额 {t['amount']:,.0f} · 体积 {t['volume']:,.2f} m³"

    @Slot(int)
    def addToCart(self, row: int) -> None:
        if self._cart is None:
            self._hint = "购物车不可用"
            self.stateChanged.emit()
            return
        try:
            data = self._model.row_at(row)
        except IndexError:
            return
        payload = {
            **data,
            "from_hub": self._hub(self._from_index),
            "from_mode": _SIDES[self._from_side],
            "to_hub": self._hub(self._to_index),
            "to_mode": _SIDES[self._to_side],
        }
        self._hint = str(self._cart.add(payload))  # type: ignore[attr-defined]
        self.stateChanged.emit()

    @Slot()
    def openCart(self) -> None:
        if self._cart is None:
            return
        self._cart.show()  # type: ignore[attr-defined]

    def _on_cart_changed(self) -> None:
        self.stateChanged.emit()

    # ═══════════════════════════════════════════════════════════
    #  收尾
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def shutdown(self) -> None:
        """页面销毁前让在跑的 worker 收尾（线程还在跑时宿主被销毁 → Qt abort）。"""
        worker = self._worker
        if worker is not None and worker.isRunning():  # type: ignore[attr-defined]
            worker.wait(3000)  # type: ignore[attr-defined]

    # ═══════════════════════════════════════════════════════════
    #  内部
    # ═══════════════════════════════════════════════════════════

    def _invalidate(self) -> None:
        """参数变了：作废在途结果，并清掉上一次的排行（旧方向的数字留着会误导）。"""
        self._gen += 1
        self._busy = False
        if self._rows:
            self._rows = []
            self._visible = []
            self._model.set_rows([])
            self.rowsChanged.emit()
        self._status = "参数已改，点「开始计算」重新算"
        self._empty_hint = "参数已改 — 点「开始计算」重新算"

    @staticmethod
    def _hub(index: int) -> str:
        return _HUBS[index] if 0 <= index < len(_HUBS) else _HUBS[0]

    def _selected_group_ids(self) -> list[int] | None:
        """选中的分类 id 列表；「全部品类」（id 0）表示不筛。"""
        cat = self._categories[self._category_index] if self._categories else _ALL_CATEGORY
        gid = _category_id(cat)
        return [gid] if gid else None

    @staticmethod
    def _load_categories() -> list[dict]:
        """市场分类的顶层（`reference.db.market_tree` 一级节点）+ 开头的「全部品类」。

        读本地静态表、一次 2000 行左右，与合同页进门查库同类；失败就只剩「全部品类」，
        不拦着用户算排行。
        """
        from core.logger import log
        from services.market_browser_service import fetch_market_tree

        cats = [dict(_ALL_CATEGORY)]
        try:
            for node in fetch_market_tree():
                if not node.get("p"):
                    cats.append({"id": int(node["id"]), "name": str(node.get("n") or node["id"])})
        except Exception:
            log.exception("读取市场分类失败，筛选下拉只保留「全部品类」")
        return cats
