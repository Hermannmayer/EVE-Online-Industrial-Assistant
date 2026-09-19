"""物品查询页 · 有结果态详情桥（第 2 步）。

组合式桥：由 `QueryBridge` 持有一个实例（`Property(QObject, constant=True)`），
QML 侧读 `query.detail.*`，不需要新的 context property，`registry`/`_spec_for` 一行不改。

取数全部复用既有实现，本模块不复制业务逻辑：
  - 5 个贸易中心价格：`market_repo.get_batch_market_snapshot`（每个 hub 各查一次）
  - 订单：`OrderFetchWorker` + `order_cache` + `_station_name_cache` + `order_rows`
  - 精炼：`RefineWorker`
  - 制造材料：`bom_expander.get_flat_materials`（买/卖各展开一次）
几何与文案算法在 `ui_qml/models/query_detail_model.py` 的纯函数里，QML 不做计算。
颜色一律走主题 token（`getattr(theme, token)` + `ensure_contrast`），不写字面量。

**`__init__` 里绝不起线程**：本仓硬约束（构造期起 QThread 会让短命桥在 pytest 退出时
卡住 —— 见 `ui_qml/bridge/query_bridge.py:221-237` 的既有注释）。所有取数在
`setItem` / `reload` 里懒启动。
"""

from __future__ import annotations

import time as _time
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWidgets import QApplication

from core.constants import TRADE_HUB_IDS, TRADE_HUBS
from core.logger import log
from domain.theme_contrast import ensure_contrast
from ui_qml.models.query_detail_model import (
    hub_bar_rows,
    material_rows,
    refine_rows,
    refine_total_rows,
)
from ui_qml.theme import registry as theme

__all__ = ["QueryDetailBridge"]

#: 订单表头（订单弹窗删除后，这里是唯一一份）。
_ORDER_HEADS = ["#", "价格 (ISK)", "数量", "空间站"]

#: 订单缓存有效期：5 分钟内重选同一行不重新打 ESI。
_ORDER_CACHE_TTL = 300

_DEFAULT_HUB_INDEX = 0
_DEFAULT_MATERIAL_QTY = 1
#: `shutdown()` 等线程收尾的上限（毫秒）。订单是两次 HTTP，取不到就等到这里为止。
_SHUTDOWN_WAIT_MS = 1500
#: 收尾不掉的在途线程**保活**在这里：绝不能让 Qt 在进程退出时析构一个还在跑的 QThread
#: （那会直接崩）。它们已经没有任何引用方，进程退出时由操作系统回收。
_ORPHANED_WORKERS: list = []


def _resolve_color(token: str) -> str:
    """主题 token 名 → 当前主题色值（过对比度兜底）。

    与 `ShellWindowBridge.navIconColor` 同一手法：浅色主题的强调色对浅底常常
    低于 WCAG 1.4.11 的 3:1，图形直接用会糊。token 无效时退回 `TEXT_SECONDARY`。
    """
    if not token:
        return ""
    color = getattr(theme, token, None)
    if not isinstance(color, str):
        log.warning("查询详情配色 token 不存在：%s", token)
        return theme.TEXT_SECONDARY
    return ensure_contrast(color, theme.BG_SURFACE)


class QueryDetailBridge(QObject):
    """物品查询页「有结果态」详情面板的 QML 后端。"""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._type_id = 0
        self._name = ""
        self._busy = False
        self._pending = 0

        self._hub_rows: list[dict] = []
        self._hub_summary = ""
        self._buy_order_rows: list[dict] = []
        self._sell_order_rows: list[dict] = []
        self._order_status = ""
        self._best_buy = 0.0
        self._best_sell = 0.0
        self._refine_rows: list[dict] = []
        self._refine_summary = ""
        self._refine_total_rows: list[dict] = []
        self._material_rows: list[dict] = []
        self._material_summary = ""

        self._price_hub_index = _DEFAULT_HUB_INDEX
        self._material_hub_index = _DEFAULT_HUB_INDEX
        self._material_hub_touched = False
        self._material_qty = _DEFAULT_MATERIAL_QTY

        # 精炼面板的三个输入（人物 / 数量 / 站点）——与材料面板的「制造数量 / 价格中心」同理，
        # 都由桥持有、改动后重算。人物列表懒读（见 `_ensure_chars`）。
        self._char_names: list[str] = []
        self._refine_char_index = -1  # -1 = 尚未落到 `char_config.json` 的 current 上
        self._refine_qty = _DEFAULT_MATERIAL_QTY
        self._refine_facility = False

        self._order_worker: Any = None
        self._refine_worker: Any = None

    # ── 标识 / 状态 ───────────────────────────────────────────

    def _get_type_id(self) -> int:
        return self._type_id

    typeId = Property(int, _get_type_id, notify=changed)

    itemName = Property(str, lambda self: self._name, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)

    # ── ① 5 个贸易中心价格 ────────────────────────────────────

    hubRows = Property(list, lambda self: list(self._hub_rows), notify=changed)
    hubSummary = Property(str, lambda self: self._hub_summary, notify=changed)
    #: 贸易中心名列表（顺序同 `core.constants.TRADE_HUBS`）—— 价格中心下拉框的 model。
    hubNames = Property(list, lambda self: list(TRADE_HUBS), constant=True)

    # ── ② 订单列表 ────────────────────────────────────────────

    #: 买单 + 卖单的顺序拼接（「复制整表」之类用法）；两张分表见下。
    orderRows = Property(list, lambda self: list(self._buy_order_rows) + list(self._sell_order_rows), notify=changed)
    #: 买单/卖单分两列显示（各表 `#` 从 1 起）
    buyOrderRows = Property(list, lambda self: list(self._buy_order_rows), notify=changed)
    sellOrderRows = Property(list, lambda self: list(self._sell_order_rows), notify=changed)
    buyOrderCount = Property(int, lambda self: len(self._buy_order_rows), notify=changed)
    sellOrderCount = Property(int, lambda self: len(self._sell_order_rows), notify=changed)
    orderHeads = Property(list, lambda self: list(_ORDER_HEADS), constant=True)
    orderStatus = Property(str, lambda self: self._order_status, notify=changed)
    bestBuyText = Property(str, lambda self: self._price_text(self._best_buy), notify=changed)
    bestSellText = Property(str, lambda self: self._price_text(self._best_sell), notify=changed)

    # ── ③ 精炼产物 ────────────────────────────────────────────

    refineRows = Property(list, lambda self: list(self._refine_rows), notify=changed)
    refineSummary = Property(str, lambda self: self._refine_summary, notify=changed)
    refineTotalRows = Property(list, lambda self: list(self._refine_total_rows), notify=changed)

    #: 精炼的三个输入：人物 / 数量 / 站点。
    #: 产率由**该人物的技能**决定（`core/eve_formulas.calc_refining_yield`：
    #: 基础 ×(1+3%×提炼学概论) ×(1+2%×提炼效率理论)，再按 NPC 站 / 玩家结构取上限），
    #: 所以这三个都是「改了要重算」的输入，与材料面板的「制造数量 / 价格中心」同理。
    charNames = Property(list, lambda self: list(self._char_names), notify=changed)
    refineQty = Property(int, lambda self: self._refine_qty, notify=changed)
    refineFacility = Property(bool, lambda self: self._refine_facility, notify=changed)

    def _get_refine_char_index(self) -> int:
        return self._refine_char_index

    refineCharIndex = Property(int, _get_refine_char_index, notify=changed)

    # ── ④ 制造材料 ────────────────────────────────────────────

    materialRows = Property(list, lambda self: list(self._material_rows), notify=changed)
    materialSummary = Property(str, lambda self: self._material_summary, notify=changed)

    def _get_material_qty(self) -> int:
        return self._material_qty

    materialQty = Property(int, _get_material_qty, notify=changed)

    def _get_material_hub_index(self) -> int:
        return self._material_hub_index

    materialHubIndex = Property(int, _get_material_hub_index, notify=changed)

    # ── 价格中心（精炼 / 订单区域）─────────────────────────────

    def _get_price_hub_index(self) -> int:
        return self._price_hub_index

    priceHubIndex = Property(int, _get_price_hub_index, notify=changed)

    # ── 懒起任务：busy 计数器 ─────────────────────────────────

    def _start_task(self) -> None:
        self._pending += 1
        self._busy = True

    def _finish_task(self) -> None:
        self._pending = max(0, self._pending - 1)
        self._busy = self._pending > 0

    # ── 入口 ──────────────────────────────────────────────────

    @Slot(int, str)
    def setItem(self, type_id: int, name: str) -> None:
        """选中行变化时由 `QueryBridge` 调用（在 `setPriceHubIndex` 之后）。"""
        self._type_id = int(type_id or 0)
        self._name = str(name or "")

        # 材料价格中心默认跟随查询区域；用户手动选过就不再覆盖（解耦但默认合理）。
        if not self._material_hub_touched:
            self._material_hub_index = self._price_hub_index

        self._hub_rows = []
        self._hub_summary = ""
        self._buy_order_rows = []
        self._sell_order_rows = []
        self._order_status = ""
        self._best_buy = 0.0
        self._best_sell = 0.0
        self._refine_rows = []
        self._refine_summary = ""
        self._refine_total_rows = []
        self._material_rows = []
        self._material_summary = ""
        self.changed.emit()

        self.reload()

    @Slot()
    def clear(self) -> None:
        """清空当前物品（搜索结果变化/清空时由 `QueryBridge` 调用）。

        只重置展示状态，不动价格中心/数量这类用户选择；`typeId=0` 让在途 worker
        的回调认出「已切换」而丢弃结果。
        """
        self._type_id = 0
        self._name = ""
        self._hub_rows = []
        self._hub_summary = ""
        self._buy_order_rows = []
        self._sell_order_rows = []
        self._order_status = ""
        self._best_buy = 0.0
        self._best_sell = 0.0
        self._refine_rows = []
        self._refine_summary = ""
        self._refine_total_rows = []
        self._material_rows = []
        self._material_summary = ""
        self.changed.emit()

    @Slot()
    def reload(self) -> None:
        """重新拉取四块面板（价格中心 / 数量取当前值）。"""
        if not self._type_id:
            return
        self._load_hub_prices()
        self._load_materials()
        self._load_refine()
        self._load_orders(force=False)

    @Slot()
    def shutdown(self) -> None:
        """停掉在途取数线程。**页面销毁（切页 / 关窗 / 退出）时必须调**。

        为什么必须：订单走 ESI，`OrderFetchWorker` 正常几百毫秒、**超时 30 秒**，
        而它是 `parent=self` 的 QThread。页面一销毁，Qt 就会去析构一个**还在跑**的线程
        —— 那是直接崩，不是异常：实测「选中一行后进程退出」会以退出码 127 结束，
        且**输出里连一行 traceback 都没有**（所以极难从现象反推）。

        join 不掉时**解除父子关系并保活到进程退出**，而不是硬销毁：`terminate()` 会在
        线程持有 GIL 时把主线程一起锁死（Windows 的 `TerminateThread` 语义），比泄漏更糟。
        进程退出时操作系统会回收，泄漏一个已无引用的线程对象是可以接受的代价。
        """
        for attr in ("_order_worker", "_refine_worker"):
            worker = getattr(self, attr, None)
            setattr(self, attr, None)
            if worker is None or not worker.isRunning():
                continue
            worker.requestInterruption()
            if worker.wait(_SHUTDOWN_WAIT_MS):
                continue
            log.warning("取数线程 %s 未能在 %dms 内收尾，解除父子关系并保活到进程退出", attr, _SHUTDOWN_WAIT_MS)
            worker.setParent(None)
            _ORPHANED_WORKERS.append(worker)

    @Slot()
    def reloadOrders(self) -> None:
        """强制刷订单（忽略缓存）。"""
        if not self._type_id:
            return
        self._load_orders(force=True)

    @Slot(int)
    def setPriceHubIndex(self, index: int) -> None:
        """精炼（及订单区域）的价格中心。变化后重算精炼与材料。"""
        if not 0 <= index < len(TRADE_HUBS):
            return
        if index == self._price_hub_index:
            return
        self._price_hub_index = index
        if not self._material_hub_touched:
            self._material_hub_index = index
        self.changed.emit()
        if self._type_id:
            self._load_refine()
            if not self._material_hub_touched:
                self._load_materials()

    @Slot(int)
    def setMaterialQty(self, qty: int) -> None:
        """制造材料的数量（默认 1）。变化后重算材料。"""
        qty = max(1, int(qty or 1))
        if qty == self._material_qty:
            return
        self._material_qty = qty
        self.changed.emit()
        if self._type_id:
            self._load_materials()

    @Slot(int)
    def setMaterialHubIndex(self, index: int) -> None:
        """制造材料用的价格中心（与精炼的 `priceHubIndex` 解耦）。"""
        if not 0 <= index < len(TRADE_HUBS):
            return
        self._material_hub_touched = True
        if index == self._material_hub_index:
            return
        self._material_hub_index = index
        self.changed.emit()
        if self._type_id:
            self._load_materials()

    # ── 精炼的输入（人物 / 数量 / 站点）────────────────────────

    @Slot(int)
    def setRefineCharIndex(self, index: int) -> None:
        """精炼用哪个人物 —— 决定读谁的提炼学概论 / 提炼效率理论等级。"""
        if not 0 <= index < len(self._char_names) or index == self._refine_char_index:
            return
        self._refine_char_index = index
        self.changed.emit()
        if self._type_id:
            self._load_refine()

    @Slot(int)
    def setRefineQty(self, qty: int) -> None:
        """精炼的数量（默认 1，与查询页「选中行 = 1 件」一致）。"""
        qty = max(1, int(qty or 1))
        if qty == self._refine_qty:
            return
        self._refine_qty = qty
        self.changed.emit()
        if self._type_id:
            self._load_refine()

    @Slot(bool)
    def setRefineFacility(self, facility: bool) -> None:
        """在玩家设施（Upwell 结构）精炼 —— 基础率与上限都高于 NPC 空间站。"""
        facility = bool(facility)
        if facility == self._refine_facility:
            return
        self._refine_facility = facility
        self.changed.emit()
        if self._type_id:
            self._load_refine()

    @Slot(int, result=str)
    def copyPrice(self, kind: int) -> str:
        """复制订单列表里最优的买价（kind=0）/ 卖价（kind=1），返回复制到的文本。

        无订单时返回空串（不写剪贴板）；价格按可粘贴的裸数字格式（无千分位）。
        """
        value = self._best_sell if kind else self._best_buy
        if not value:
            return ""
        text = f"{value:.2f}"
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.clipboard().setText(text)
        return text

    # ── ① 5 个贸易中心价格 ────────────────────────────────────

    def _load_hub_prices(self) -> None:
        from core.container import get_container

        self._start_task()
        try:
            snapshots: dict[str, dict] = {}
            repo = get_container().market_repo
            for hub in TRADE_HUBS:
                region_id = TRADE_HUB_IDS[hub]
                batch = repo.get_batch_market_snapshot([self._type_id], region_id)
                entry = batch.get(self._type_id) or {}
                snapshots[hub] = {
                    "buy": entry.get("bp"),
                    "sell": entry.get("sp"),
                    "buy_volume": entry.get("bv") or 0,
                    "sell_volume": entry.get("sv") or 0,
                }
        except Exception:
            log.exception("查询详情：获取 5 个贸易中心价格失败 type_id=%s", self._type_id)
            snapshots = {}
        finally:
            self._finish_task()

        rows = hub_bar_rows(snapshots, list(TRADE_HUBS))
        for row in rows:  # 帝国色 token 名 → 实际色值（过对比度兜底）
            row["empireColor"] = _resolve_color(row.get("empireColor", ""))
        self._hub_rows = rows
        self._hub_summary = self._build_hub_summary(rows)
        self.changed.emit()

    def _build_hub_summary(self, rows: list[dict]) -> str:
        if not self._type_id or not rows:
            return ""
        best_buy = next((r for r in rows if r.get("bestBuy")), None)
        best_sell = next((r for r in rows if r.get("bestSell")), None)
        parts = []
        if best_buy:
            parts.append(f"买价最高：{best_buy['hub']} {best_buy['buyText']}")
        if best_sell:
            parts.append(f"卖价最低：{best_sell['hub']} {best_sell['sellText']}")
        return " · ".join(parts) if parts else "该物品在 5 个贸易中心均无价格数据"

    # ── ② 订单列表 ────────────────────────────────────────────

    def _load_orders(self, *, force: bool) -> None:
        from ui_qml.workers.order_workers import OrderFetchWorker, order_cache

        region_id = TRADE_HUB_IDS.get(self._price_hub(), TRADE_HUB_IDS[TRADE_HUBS[0]])

        if not force:
            cached = order_cache.get(self._type_id)
            if cached:
                buy_orders, sell_orders, fetch_time = cached
                if _time.time() - fetch_time < _ORDER_CACHE_TTL:
                    self._render_orders(buy_orders, sell_orders)
                    self._order_status = "订单数据已加载（缓存）"
                    self.changed.emit()
                    return

        self._buy_order_rows = []
        self._sell_order_rows = []
        self._best_buy = 0.0
        self._best_sell = 0.0
        self._order_status = "正在从 ESI 获取实时订单…"
        self.changed.emit()

        self._start_task()
        worker = OrderFetchWorker(self._type_id, region_id, self)
        self._order_worker = worker
        worker.finished_signal.connect(self._on_orders_fetched)
        worker.error_signal.connect(self._on_orders_error)
        worker.start()

    def _render_orders(self, buy_orders: list, sell_orders: list) -> None:
        """填入买单/卖单两张分表（买绿、卖红），各自 `#` 从 1 起。"""
        from ui_qml.bridge.order_popup_bridge import order_rows
        from ui_qml.workers.order_workers import _station_name_cache

        self._buy_order_rows = order_rows(list(buy_orders or []), "GREEN", _station_name_cache)
        self._sell_order_rows = order_rows(list(sell_orders or []), "RED", _station_name_cache)
        self._best_buy = max((float(o.get("price") or 0) for o in buy_orders or []), default=0.0)
        self._best_sell = min(
            (float(o.get("price") or 0) for o in sell_orders or [] if float(o.get("price") or 0) > 0),
            default=0.0,
        )

    def _on_orders_fetched(self, type_id: int, buy_orders: list, sell_orders: list) -> None:
        self._finish_task()
        if type_id != self._type_id:
            return
        #: 写回共享缓存。原先这一笔是订单弹窗那条路径写的，弹窗删除后必须由这里接手 ——
        #: 否则 `_load_orders` 里的缓存分支永远落空（每选一次行就打一次 ESI），
        #: `_ORDER_CACHE_TTL` 也成了死常量。
        from ui_qml.workers.order_workers import order_cache

        order_cache[self._type_id] = (buy_orders, sell_orders, _time.time())
        self._render_orders(buy_orders, sell_orders)
        has_orders = bool(self._buy_order_rows or self._sell_order_rows)
        self._order_status = "实时订单数据已加载" if has_orders else "该物品当前无挂单"
        self.changed.emit()

    def _on_orders_error(self, type_id: int, error: str) -> None:
        self._finish_task()
        if type_id != self._type_id:
            return
        self._buy_order_rows = []
        self._sell_order_rows = []
        self._best_buy = 0.0
        self._best_sell = 0.0
        self._order_status = f"获取订单失败：{error}"
        self.changed.emit()

    def _price_text(self, value: float) -> str:
        return f"{value:,.2f}" if value else "—"

    # ── ③ 精炼产物 ────────────────────────────────────────────

    def _load_refine(self) -> None:
        from ui_qml.workers.refine_worker import RefineWorker

        self._ensure_chars()
        self._refine_rows = []
        self._refine_total_rows = []
        self._refine_summary = "正在计算精炼产物…"
        self.changed.emit()

        self._start_task()
        worker = RefineWorker(
            items=[{"type_id": self._type_id, "qty": self._refine_qty, "name": self._name}],
            skills=self._refine_skills(),
            is_player_facility=self._refine_facility,
            price_hub=self._price_hub(),
            parent=self,
        )
        self._refine_worker = worker
        worker.result_signal.connect(self._on_refine_done)
        worker.start()

    def _ensure_chars(self) -> None:
        """首次需要时读一次人物列表，并落到 `char_config.json` 里记录的当前人物。

        **必须缓存到字段**：`charNames` 是 `Property`，QML 每次读它都会走 getter，
        把 `load_all_data()`（一次 JSON 读盘）写在 getter 里等于每次重绘都读盘。
        """
        if self._char_names:
            return
        from services.char_config_resolver import get_character_list, load_all_data

        self._char_names = list(get_character_list() or [])
        if not self._char_names:
            self._refine_char_index = -1
            return
        current = str((load_all_data() or {}).get("current") or "")
        self._refine_char_index = self._char_names.index(current) if current in self._char_names else 0

    def _refine_char(self) -> str:
        if 0 <= self._refine_char_index < len(self._char_names):
            return self._char_names[self._refine_char_index]
        return ""

    def _refine_skills(self) -> dict:
        """当前人物的技能表。

        `calc_refining_yield` 只认里面的「提炼学概论」「提炼效率理论」两个键（见
        `core/char_settings_common.SKILL_CATEGORIES` 的「精炼」分类）。
        没选人物、或人物没填过这两项时返回空字典 —— 公式按 0 级算，与「没写就是没有」一致。
        """
        from services.char_config_resolver import resolve_char_config

        name = self._refine_char()
        if not name:
            return {}
        return dict((resolve_char_config(char_name=name) or {}).get("skills") or {})

    def _on_refine_done(self, result: dict) -> None:
        self._finish_task()
        rows = refine_rows(result or {})
        self._refine_rows = rows
        self._refine_total_rows = [
            {"label": row["label"], "valueText": row["valueText"], "color": _resolve_color(row.get("token", ""))}
            for row in refine_total_rows(result or {})
        ]
        if not rows:
            self._refine_summary = "该物品不可精炼"
        else:
            out = float((result or {}).get("total_output_value") or 0)
            inp = float((result or {}).get("total_input_value") or 0)
            profit = float((result or {}).get("total_profit") or 0)
            self._refine_summary = f"总计：产出 {out:,.2f} ISK / 投入 {inp:,.2f} ISK / 利润 {profit:,.2f} ISK"
        self.changed.emit()

    # ── ④ 制造材料 ────────────────────────────────────────────

    def _load_materials(self) -> None:
        from services.bom_expander import get_flat_materials

        hub = self._material_hub()
        qty = self._material_qty
        try:
            sell_mats = get_flat_materials(self._type_id, quantity=qty, bp_me=0, price_hub=hub, price_type="sell")
            buy_mats = get_flat_materials(self._type_id, quantity=qty, bp_me=0, price_hub=hub, price_type="buy")
        except Exception:
            log.exception("查询详情：制造材料 BOM 展开失败 type_id=%s", self._type_id)
            self._material_rows = []
            self._material_summary = "该物品没有制造配方"
            self.changed.emit()
            return

        rows = material_rows(sell_mats, buy_mats)
        # `get_flat_materials` 对「没有蓝图」的物品会**把它自己当成唯一材料**返回（基础矿物、
        # 打捞件等都是这样）。直接渲染出来就是「三钛 ← 需要 1 个三钛」，读着像配方，
        # 实际是「无配方」的兜底。按 type_id 判掉，换成明确的文案。
        if rows and all(int(m.get("type_id") or 0) == self._type_id for m in sell_mats):
            rows = []
        self._material_rows = rows
        if not rows:
            self._material_summary = "该物品没有制造配方（基础材料 / 无蓝图）"
        else:
            sell_total = sum(float(m.get("subtotal") or 0) for m in sell_mats)
            buy_total = sum(float(m.get("subtotal") or 0) for m in buy_mats)
            self._material_summary = (
                f"共 {len(rows)} 种材料 · 合计（卖价）{sell_total:,.2f} ISK / 合计（买价）{buy_total:,.2f} ISK"
            )
        self.changed.emit()

    # ── 价格中心辅助 ──────────────────────────────────────────

    def _price_hub(self) -> str:
        hubs = list(TRADE_HUBS)
        if 0 <= self._price_hub_index < len(hubs):
            return hubs[self._price_hub_index]
        return hubs[0]

    def _material_hub(self) -> str:
        hubs = list(TRADE_HUBS)
        if 0 <= self._material_hub_index < len(hubs):
            return hubs[self._material_hub_index]
        return hubs[0]
