"""贸易页 bridge —— QML 与 worker 之间的唯一通道。

页面只做一件事：**A 贸易中心 → B 贸易中心的全品类价差排行**。
「开始计算」**只读本地 `market.db`**，不发起任何 ESI 请求：

  `analyze()` → `CrossRegionRankWorker` → 出表

要更新价格走顶栏「更新价格」（`ShellWindow.request_price_update`，自带单写者排队、
进度条与缓存失效）—— 贸易页不再挂钩它，否则点一次「开始计算」会顺带触发一次全量拉取。

状态栏那行价格时间（`fetch_hub_fetch_time`）是**只读**的：它显示本地快照有多旧，
不负责刷新。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from core.constants import TRADE_HUB_IDS
from core.logger import log
from ui_qml.bridge.all_items_bridge import market_tree_rows, subtree_ids, visible_tree_rows
from ui_qml.models.trade_rank_model import COLUMNS, TradeRankQmlModel

__all__ = ["TradeBridge"]

_HUBS = list(TRADE_HUB_IDS.keys())
#: 价格类型下拉（顺序即 index）：从 A 默认「卖单」（买入要付卖单价）、到 B 默认「买单」
_SIDES = ("sell", "buy")
_SIDE_LABELS = ("卖单", "买单")

_ALL_CATEGORY = {"id": 0, "name": "全部品类"}
#: 挂单变化的观察窗口（天）
_CHANGE_DAYS = 7

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


def _category_id(cat: dict) -> int:
    """分类项里的 id（非整数一律当 0 = 全部品类）。"""
    raw = cat.get("id")
    return raw if isinstance(raw, int) else 0


class TradeBridge(QObject):
    """贸易页的 QML 后端。"""

    stateChanged = Signal()  # 工具栏 / 状态栏 / 计算中标志
    rowsChanged = Signal()  # 结果表整体换了
    treeChanged = Signal()  # 左树（可见行 / 选中节点）

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell

        self._from_index = _HUBS.index("Jita")
        self._to_index = _HUBS.index("Amarr")
        self._from_side = 0  # 卖单
        self._to_side = 1  # 买单
        self._category_index = 0
        #: 市场分类节点：下拉与左树**共用这一次查询**（见 `_load_market_nodes`）
        _nodes = self._load_market_nodes()
        self._categories = self._categories_from(_nodes)
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

        # ── 左树：市场分类（与「可制造物品」窗口同一份市场树）────────────────
        # 节点来自上面那一次 `fetch_market_tree()`（本地静态表，与分类下拉同源同次）；
        # 选中节点后按**整棵子树**筛，能精确到子分类 —— 下拉只支持单个一级分组。
        self._tree_all: list[dict] = market_tree_rows(_nodes) if _nodes else []
        self._tree_visible: list[dict] = []
        self._expanded: set[Any] = set()
        self._selected_tree_id = -1
        self._selected_tree_name = ""
        #: 选中节点子树里的物品 type_id（选中时算一次；映射是静态的）
        self._selected_items: set[int] = set()
        #: 分组 → 物品 type_id（ref 库一次查完，按窗口缓存）
        self._items_by_group: dict[int, set[int]] = {}

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

        # 树先落一次可见行（折叠到根、还不置灰 —— 这时候一条结果都还没有）。
        # 少了这一步 QML 打开时树是空的，直到第一次改筛选才冒出来。
        self._refresh_tree()

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

    # ── 左树：市场分类 ──────────────────────────────────────
    treeRows = Property(list, lambda self: self._tree_visible, notify=treeChanged)
    selectedTreeId = Property(int, lambda self: self._selected_tree_id, notify=treeChanged)
    selectedTreeName = Property(str, lambda self: self._selected_tree_name, notify=treeChanged)

    @Slot(int)
    def toggleTreeNode(self, index: int) -> None:
        if not 0 <= index < len(self._tree_visible):
            return
        row = self._tree_visible[index]
        if not row["hasChildren"]:
            return
        node_id = row["id"]
        if node_id in self._expanded:
            self._expanded.discard(node_id)
        else:
            self._expanded.add(node_id)
        self._refresh_tree()

    @Slot(int)
    def selectTreeNode(self, index: int) -> None:
        """点分类节点：按**整棵子树**筛。

        下拉那个分类只支持单个一级分组（`market_group_id IN (一个 id)`，子分类里的物品
        全都看不到），树能精确到子分类 —— 这也是加树的主要原因。
        """
        if not 0 <= index < len(self._tree_visible):
            return
        row = self._tree_visible[index]
        self._selected_tree_id = int(row["id"])
        self._selected_tree_name = str(row["name"])
        self._selected_items = self._node_items(self._selected_tree_id)
        self._category_index = 0  # 与下拉互斥：树生效时下拉回到「全部品类」
        self._apply_filters()
        self.stateChanged.emit()

    @Slot()
    def clearTreeSelection(self) -> None:
        """「全部」：清掉树的筛选（下拉不动）。"""
        if self._selected_tree_id < 0:
            return
        self._clear_tree_selection()
        self._apply_filters()
        self.stateChanged.emit()

    def _clear_tree_selection(self) -> None:
        self._selected_tree_id = -1
        self._selected_tree_name = ""
        self._selected_items = set()

    def _refresh_tree(self) -> None:
        """重算可见行 + 「这个分类下当前结果里有没有物品」的置灰标记。"""
        present = {r.get("id") for r in self._rows}
        # 还没有结果时**不置灰**（全是灰的会让人以为分类是空的）
        hit = self._tree_has_rows(present) if present else {}
        rows: list[dict] = []
        for row in visible_tree_rows(self._tree_all, self._expanded):
            item = dict(row)
            item["empty"] = bool(present) and not hit.get(row["id"], False)
            rows.append(item)
        self._tree_visible = rows
        self.treeChanged.emit()

    def _tree_has_rows(self, present: set[Any]) -> dict[Any, bool]:
        """每个节点子树里有没有「当前结果」里的物品。

        自底向上一次算完（每个节点只跟**自己那一个分组**的物品求交集，再往上累积），
        避免逐节点 `subtree_ids` + 求并集那套 O(节点 × 子树) 的做法。
        """
        mapping = self._items_by_group_map()
        hit = {row["id"]: bool(mapping.get(int(row["id"]), set()) & present) for row in self._tree_all}
        for row in reversed(self._tree_all):
            parent = row.get("parent")
            if parent is not None and hit.get(row["id"]):
                hit[parent] = True  # type: ignore[index]
        return hit

    def _node_items(self, node_id: int) -> set[int]:
        """节点子树里的物品 type_id（选中时算一次，映射是静态的）。"""
        mapping = self._items_by_group_map()
        out: set[int] = set()
        for gid in subtree_ids(self._tree_all, node_id):
            out |= mapping.get(int(gid), set())
        return out

    def _items_by_group_map(self) -> dict[int, set[int]]:
        """分组 id → 该分组下的物品 type_id（ref 库一次查完、**按窗口缓存**）。

        `item` 表 5 万行量级，懒查一次即可；失败就退化成空映射（树只看得到结构，
        过滤不出东西），不拦着用户算排行。
        """
        if self._items_by_group:
            return self._items_by_group
        from core.container import get_container

        try:
            with get_container().db.connect("ref") as conn:
                for gid, tid in conn.execute(
                    "SELECT market_group_id, type_id FROM item WHERE market_group_id IS NOT NULL"
                ):
                    self._items_by_group.setdefault(int(gid), set()).add(int(tid))
        except Exception:
            log.exception("读取「市场分组 → 物品」映射失败，左树过滤会退化成空")
        return self._items_by_group

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
        # 左树选中的分类：按**整棵子树**里的物品筛
        if self._selected_tree_id >= 0:
            rows = [r for r in rows if r.get("id") in self._selected_items]
        self._visible = rows
        self._model.set_rows(rows)
        self._status = self._status_text()
        if self._rows and not rows:
            self._empty_hint = (
                f"「{self._selected_tree_name}」下没有符合条件的物品 — 换分类或放宽「筛选项」"
                if self._selected_tree_id >= 0
                else "当前筛选下没有符合条件的物品 — 放宽「筛选项」，或点「开始计算」重算"
            )
        else:
            self._empty_hint = "还没有数据 — 选好两个贸易中心，点「开始计算」"
        self.rowsChanged.emit()
        self.stateChanged.emit()
        self._refresh_tree()

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
        """选一级分类下拉：与左树**互斥**（两个都是分类筛选，选了这个那个就作废）。"""
        if 0 <= index < len(self._categories) and index != self._category_index:
            self._category_index = index
            if self._selected_tree_id >= 0:
                self._clear_tree_selection()
                self.treeChanged.emit()
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
        """「开始计算」：只读本地价格，直接算排行。"""
        if self._busy:
            return
        self._gen += 1
        gen = self._gen
        self._busy = True
        self._hint = ""
        self._start_rank(gen)

    def _start_rank(self, gen: int) -> None:
        from ui_qml.workers.trade_workers import CrossRegionRankWorker

        self._status = "正在计算排行..."
        self.stateChanged.emit()

        group_ids = self._selected_group_ids()
        from ui_qml.workers.trade_workers import spawn

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
        failed_signal = getattr(worker, "failed_signal", None)
        if failed_signal is not None:
            failed_signal.connect(lambda message: self._on_rank_failed(gen, message))
        spawn(worker)

    def _on_rank(self, gen: int, rows: list) -> None:
        if gen != self._gen:
            return  # 过期结果：参数已经变过了
        self._busy = False
        self._rows = list(rows or [])
        self._apply_filters()

    def _on_rank_failed(self, gen: int, message: str) -> None:
        if gen != self._gen:
            return
        self._busy = False
        self._status = f"排行失败: {message}"
        self._hint = "请稍后重试；若正在更新价格，请等待更新完成"
        self.stateChanged.emit()

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
        # 只报「本地这份快照是什么时候拉的」—— 本页不刷新，不做任何新鲜度判断
        return f"{count}  ·  {hub_a} {_age_text(age_a)} / {hub_b} {_age_text(age_b)}"

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
        """选中的市场分组：**左树的子树优先**，其次下拉里的单个一级分类；「全部」= 不筛。"""
        if self._selected_tree_id >= 0:
            groups = sorted(int(g) for g in subtree_ids(self._tree_all, self._selected_tree_id))
            return groups or None
        cat = self._categories[self._category_index] if self._categories else _ALL_CATEGORY
        gid = _category_id(cat)
        return [gid] if gid else None

    @staticmethod
    def _load_market_nodes() -> list[dict]:
        """市场分类原始节点（`reference.db.market_tree`，一次 2000 行左右）。

        分类下拉与左树共用这一次查询。读本地静态表、进门查一次，与合同页进门补物品同类；
        失败就只剩「全部品类」+ 空树，不拦着用户算排行。
        """
        from services.market_browser_service import fetch_market_tree

        try:
            return list(fetch_market_tree())
        except Exception:
            log.exception("读取市场分类失败，分类下拉只保留「全部品类」、左树为空")
            return []

    @staticmethod
    def _categories_from(nodes: list[dict]) -> list[dict]:
        """分类下拉 = 「全部品类」+ 市场分类的**顶层**（子分类交给左树）。"""
        cats = [dict(_ALL_CATEGORY)]
        for node in nodes:
            if not node.get("p"):
                cats.append({"id": int(node["id"]), "name": str(node.get("n") or node["id"])})
        return cats
