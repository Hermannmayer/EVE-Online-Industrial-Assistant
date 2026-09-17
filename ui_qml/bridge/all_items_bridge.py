"""全物品浏览器 + 制造材料明细的桥（阶段 4b）。

对照两个 Widgets 版：
- `ui_pyside6/views/all_items_view.py::AllItemsDialog`（含左树 + 表格 + 评分模式切换 + 导出）
- 同文件 `MatDlg`（双击物品行弹出的「制造材料」明细）

**取数、筛选、评分、排序、导出格式一行都没搬过来**：
分类树走 `ui_qml.workers.all_items_workers.TreeW`，物品/搜索走同文件的 `ItemsW` /
`SearchItemsW`，评分走 `ui_pyside6.views.score_dialogs.ScoreW`（`BaseBatchScoreWorker`
的后台线程，零 UI，继续用原类），类别筛选仍是 `blueprint_repo` 的那几个 product_ids 查询，
表格展示与排序仍是 `ui_pyside6/models/all_items_models.py` 的 `AModel` / `Proxy`
（经 `ui_qml/models/all_items_qml_model.py` 补命名角色）。桥只做「界面状态 ↔ 属性/槽」。

四处需要留意的接线：

1. **后台线程必须在关窗前收尾**。`QmlDialog._stop_bridge` 会调 `stop()`。
   不收尾的后果是硬崩：线程是桥的子对象，桥随对话框销毁时 `QThread` 若仍在运行，
   Qt 直接 `qFatal` 中止进程（本仓实测：退出码 127、一行日志都没有）。
   注意三个 worker 的 `run()` **不检查中断标志**，`wait()` 可能超时 ——
   所以这里用 `drop_worker()` 统一兜底（超时就把线程摘出对话树保活）。
2. **二级弹窗的 parent 一律走 `DialogBridge.host_widget()`**，不自己存宿主引用
   （环引用会先没掉 C++ 窗口，详见 `ui_qml/dialog_host.py`）。
3. **`_show_m` / `_show_t` 换列**：切模式会换一整套列（基础列 + 制造列 / 贸易列），
   列定义仍是那三个常量，只是买价/卖价两列的标题带上区域名。
4. **表格没有 Qt 的选中模型**：QML `TableView` 用的是 `FTableClickArea` 派发的行号，
   所以「当前行」由桥自己记（`_selected_row`）—— 原版靠 `selectionModel().selectedRows()`
   的地方（批量对比）改读它。
"""

from __future__ import annotations

import json
import os
from typing import Any

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog

from core.cache import TtlLRUCache
from core.container import get_container
from core.logger import log
from core.paths import data_dir
from ui_qml.bridge.message_dialog import FMessageDialog
from ui_qml.constants import CATEGORIES, MFG_CATEGORIES
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.models.all_items_models import BCOLS, DASH, MCOLS, TCOLS, Proxy
from ui_qml.models.all_items_qml_model import AllItemsQmlModel, icon_url
from ui_qml.workers.all_items_workers import JITA_RID, ItemsW, SearchItemsW, TreeW
from ui_qml.workers.lifecycle import drop_worker
from ui_qml.workers.score_worker import ScoreW

__all__ = [
    "AllItemsBridge",
    "AllItemsQmlDialog",
    "MatBridge",
    "MatQmlDialog",
    "breakdown_text",
    "insert_plan_from_score",
    "market_tree_rows",
    "subtree_ids",
    "visible_tree_rows",
]

_ALL_QML = "dialogs/AllItemsDialog.qml"
_MAT_QML = "dialogs/MaterialsDialog.qml"

#: 搜索防抖（原版 `QTimer` 的 200ms）
_SEARCH_DEBOUNCE_MS = 200

_EXPORT_DEFAULT = "物品数据.csv"
_EXPORT_FILTER = "CSV 文件 (*.csv);;Excel 文件 (*.xlsx)"


# ══════════════════════════════════════════════════════════════
#  纯函数：分类树 / 导出 / 明细文案（便于单测，不碰 Qt）
# ══════════════════════════════════════════════════════════════


def market_tree_rows(items: list[dict]) -> list[dict]:
    """市场分类字典列表（`[{id, p, n}]`）→ 深度优先的扁平行。

    原版用 `QTreeWidget`；QML 没有树控件，这里把树压成「带缩进的平表」，
    每行带 `depth` / `parent` / `hasChildren`，展开状态由调用方按 `id` 记。
    子节点顺序 = 输入顺序（与原版 `addChild` 的追加顺序一致）。
    """
    by_id = {d["id"]: d for d in items}
    children: dict[Any, list[dict]] = {}
    roots: list[dict] = []
    for d in items:
        parent = d.get("p")
        if parent is not None and parent in by_id:
            children.setdefault(parent, []).append(d)
        else:
            roots.append(d)

    out: list[dict] = []

    def walk(node: dict, depth: int, parent: Any) -> None:
        kids = children.get(node["id"], [])
        out.append({"id": node["id"], "name": node["n"], "depth": depth, "parent": parent, "hasChildren": bool(kids)})
        for kid in kids:
            walk(kid, depth + 1, node["id"])

    for root in roots:
        walk(root, 0, None)
    return out


def visible_tree_rows(rows: list[dict], expanded: set[Any]) -> list[dict]:
    """折叠状态下的可见行 —— 被折叠节点的整棵子树都隐藏，并给每行补 `expanded`。

    依赖 `market_tree_rows()` 给的是深度优先序：一旦遇到一个「祖先被折叠」的行，
    后续所有 `depth` 更大的行都属于那棵子树。

    补 `expanded` 是给 QML 画箭头方向用的（▸ / ▾）；返回的是副本，
    不改 `market_tree_rows()` 交出来的原始行。
    """
    out: list[dict] = []
    collapsed_at: int | None = None
    for row in rows:
        if collapsed_at is not None and row["depth"] > collapsed_at:
            continue
        collapsed_at = None
        visible = dict(row)
        visible["expanded"] = row["id"] in expanded
        out.append(visible)
        if row["hasChildren"] and row["id"] not in expanded:
            collapsed_at = row["depth"]
    return out


def subtree_ids(rows: list[dict], node_id: Any) -> set[Any]:
    """节点自身 + 全部后代（原版是递归遍历 `QTreeWidgetItem` 的子树）。

    同样依赖深度优先序：从该行往下，凡是 `depth` 更大的都属于它这棵子树。
    """
    start = next((i for i, r in enumerate(rows) if r["id"] == node_id), None)
    if start is None:
        return set()
    depth = rows[start]["depth"]
    out = {node_id}
    for row in rows[start + 1 :]:
        if row["depth"] <= depth:
            break
        out.add(row["id"])
    return out


def breakdown_text(r: dict, is_mfg: bool) -> str:
    """评分明细弹窗的正文 —— 逐字照搬 `AllItemsDialog._ds`。"""
    if is_mfg:
        b = r.get("breakdown", {})
        st = r.get("status", "")
        if st:
            tips = {
                "no_blueprint": "此物品没有制造蓝图",
                "no_price": "查不到价格数据，请在主界面更新价格",
                "no_materials": "蓝图无材料数据",
                "no_depth": "市场没有买单",
            }
            return f"{tips.get(st, st)}"
        c = r.get("cost_per_unit", 0) or 0
        rev = r.get("revenue_per_unit", 0) or 0
        prof = r.get("profit_per_run", 0) or 0
        hr = r.get("hours_per_run", 0) or 1
        mats = r.get("materials", []) or []
        mat_lines = "\n".join(
            f"  {m['name']} x{m['qty']:,} @ {m['unit_price']:,.2f} = {m['subtotal']:,.0f}" for m in mats
        )
        broker_relist_fee = b.get("broker_rate", 0) * rev / 100 * (1 - b.get("relist_discount", 50) / 100)
        return (
            f"每批利润核算\n"
            f"{'─' * 24}\n"
            f"材料明细:\n{mat_lines}\n"
            f"材料合计: {sum(m['subtotal'] for m in mats):,.0f} ISK\n\n"
            f"成本/个: {c:,.2f} ISK\n"
            f"收入/个: {rev:,.2f} ISK\n"
            f"单批利润: {prof:,.2f} ISK\n"
            f"利润率: {r.get('margin_pct', 0):.2f}%\n"
            f"制造时间: {hr:.2f}h\n"
            f"产能: {24 / hr:.2f}批/天\n\n"
            f"费用明细\n"
            f"经纪人(挂单): {b.get('broker_rate', 0) * rev / 100:.0f} ISK  ← {b.get('broker_rate', 0):.3f}%\n"
            f"经纪人(改单): {broker_relist_fee:.0f} ISK"
            f"  ← 改单折扣{b.get('relist_discount', 50):.0f}%\n"
            f"销售税: {b.get('sales_tax_rate', 0) * rev / 100:.0f} ISK  ← {b.get('sales_tax_rate', 0):.2f}%\n"
            f"{'─' * 24}\n"
            f"收益等级: {r.get('_tag', '?')}\n"
            f"日利润: {r.get('mdp', 0):,.0f} ISK/天"
        )
    st = r.get("status", "")
    if st:
        return f"状态: {st}"
    tag = r.get("_tag", "?") or "?"
    bc = r.get("buy_cost", 0) or 0
    sr = r.get("sell_revenue", 0) or 0
    gp = r.get("gross_profit", 0) or 0
    mp = r.get("margin_pct", 0) or 0
    pm = r.get("profit_per_m3", 0) or 0
    return (
        f"单件贸易核算\n"
        f"{'─' * 24}\n"
        f"买入: {bc:,.2f} ISK\n"
        f"  (含挂单经纪人费 + 改单费)\n"
        f"卖出: {sr:,.2f} ISK\n"
        f"  (扣挂单经纪人费 + 改单费 + 销售税)\n"
        f"毛利: {gp:,.2f} ISK\n"
        f"利润率: {mp:.2f}%\n"
        f"每方利率: {pm:.2f} ISK/m³\n"
        f"{'─' * 24}\n"
        f"收益等级: {tag}\n"
        f"日利润: 查看收益列(×市场深度)"
    )


def insert_plan_from_score(type_id: int, name: str, score: dict, data: dict, mfg_cfg: dict) -> None:
    """「加入制造列表」：评分结果 + 对话框参数 → 一条生产计划。

    逐行照搬 Widgets 版 `AllItemsDialog._ctx` 里的 `_do_add_plan` ——
    它是 `_ctx` 内的闭包，从外面拿不到函数对象，只能搬这一份；
    落库仍是唯一的 `services.plan_service.insert_plan`。
    """
    from services import inventory_manager, user_settings
    from services.plan_service import insert_plan

    mat_hangar_id, solar_system_id = inventory_manager.get_default_mat_hangar_and_system()
    iskph = score.get("isk_per_hour", 0) or score.get("breakdown", {}).get("isk_per_hour", 0)
    mat_cost = score.get("breakdown", {}).get("material_cost", 0)
    metrics = {
        "profit": score.get("profit_per_run", 0) or 0,
        "margin": score.get("margin_pct", 0) or 0,
        "score": score.get("score", 0) or 0,
        "iskph": iskph,
        "material_cost": mat_cost,
        "calculated_time": (score.get("hours_per_run", 0) or 0) * 3600,
        "daily_output": 0,
    }
    insert_plan(
        type_id,
        name,
        data,
        mat_hub=mfg_cfg.get("hub", "Jita"),
        sell_hub=mfg_cfg.get("hub", "Jita"),
        facility=data.get("fac", ""),
        solar_system_id=solar_system_id,
        mat_hangar_id=mat_hangar_id,
        deposit_hangar_id=user_settings.get_default_hangar_id("default_deposit_hangar_id"),
        metrics=metrics,
    )


def _col_dicts(cols: list[tuple]) -> list[dict]:
    """列定义 `(标题, 宽度, key)` → QML 用的 `[{title, width}]`。"""
    return [{"title": title, "width": width} for title, width, _key in cols]


def _export_table(cols: list[tuple], rows: list[dict]) -> tuple[list[str], list[list[str]]]:
    """导出用的表头与二维表（取值口径与 `AllItemsDialog._export_data` 逐字一致）。"""
    headers = [c[0] for c in cols if c[2] != "i"]
    out: list[list[str]] = []
    for row in rows:
        line: list[str] = []
        for _title, _width, key in cols:
            if key == "i":
                continue
            value = row.get(key)
            if value is None:
                line.append("")
            elif isinstance(value, int | float):
                line.append(f"{value:,.2f}")
            else:
                line.append(str(value))
        out.append(line)
    return headers, out


# ══════════════════════════════════════════════════════════════
#  桥
# ══════════════════════════════════════════════════════════════


class AllItemsBridge(DialogBridge):
    """全物品浏览器的 QML 后端。"""

    #: 状态行 / 进度 / 列定义 / 分类下标 / 选中行
    stateChanged = Signal()
    #: 分类树可见行
    treeChanged = Signal()
    #: 搜索框回写（只 QML ← 桥：点树节点时原版会 `clear()` 搜索框）
    searchChanged = Signal()
    #: 表头排序指示
    sortChanged = Signal()

    def __init__(self, manufacturable_only: bool = False) -> None:
        super().__init__()
        self._manufacturable_only = bool(manufacturable_only)
        self.set_title("可制造物品 - 添加至生产计划" if self._manufacturable_only else "全物品查询")

        self._categories: list[str] = list(MFG_CATEGORIES if self._manufacturable_only else CATEGORIES)
        self._cat_index = 0
        self._data: list[dict] = []
        self._filt: list[dict] = []
        self._mfg: dict[str, Any] = {"hub": "Jita", "char": "main", "tax": 0}
        self._trade: dict[str, Any] = {"bh": "Amarr", "sh": "Jita", "bs": "sell", "ss": "sell", "char": "main"}
        self._load_settings()

        self._show_m = False
        self._show_t = False
        self._col_specs: list[tuple] = list(BCOLS)
        self._status = "就绪"
        self._progress_visible = False
        self._progress_value = 0
        self._progress_max = 0
        self._search_text = ""
        self._selected_row = -1
        self._selected_tree_id = -1
        self._pinned = False
        self._sort_column = -1
        self._sort_ascending = True

        self._tree_all: list[dict] = []
        self._tree_visible: list[dict] = []
        self._expanded: set[Any] = set()

        #: 与 Widgets 版同参的评分缓存。**两边都只读不写**（全仓没有任何 `.set`），
        #: 保留是为了让「命中缓存才显示核算明细」这条判断逐字不变。
        self._cache = TtlLRUCache(max_size=500, ttl_seconds=1800)

        self._model = AllItemsQmlModel()
        self._proxy = Proxy(self)
        self._proxy.setSourceModel(self._model)

        self._tw: Any = None
        self._iw: Any = None
        self._sw: Any = None
        self._wp: Any = None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._do_search)

    # ── 启动 ─────────────────────────────────────────────────

    def start(self) -> None:
        """开窗时拉起首次加载（原版在 `__init__` 末尾做同样两件事）。"""
        self._tw = TreeW(self)
        self._tw.done.connect(self._on_tree_data)
        self._tw.start()
        self._reload_items(None)

    # ── 给 QML 读 ────────────────────────────────────────────

    model = Property(QObject, lambda self: self._proxy, constant=True)
    categories = Property(list, lambda self: list(self._categories), constant=True)
    manufacturableOnly = Property(bool, lambda self: self._manufacturable_only, constant=True)
    columns = Property(list, lambda self: [dict(c) for c in _col_dicts(self._col_specs)], notify=stateChanged)
    statusText = Property(str, lambda self: self._status, notify=stateChanged)
    categoryIndex = Property(int, lambda self: self._cat_index, notify=stateChanged)
    selectedRow = Property(int, lambda self: self._selected_row, notify=stateChanged)
    selectedTreeId = Property(int, lambda self: self._selected_tree_id, notify=stateChanged)
    pinned = Property(bool, lambda self: self._pinned, notify=stateChanged)
    searchText = Property(str, lambda self: self._search_text, notify=searchChanged)
    progressVisible = Property(bool, lambda self: self._progress_visible, notify=stateChanged)
    progressValue = Property(int, lambda self: self._progress_value, notify=stateChanged)
    progressMax = Property(int, lambda self: self._progress_max, notify=stateChanged)
    rowCount = Property(int, lambda self: self._proxy.rowCount(), notify=stateChanged)
    treeRows = Property(list, lambda self: list(self._tree_visible), notify=treeChanged)
    showManufacturing = Property(bool, lambda self: self._show_m, notify=stateChanged)
    showTrade = Property(bool, lambda self: self._show_t, notify=stateChanged)
    sortColumn = Property(int, lambda self: self._sort_column, notify=sortChanged)
    sortAscending = Property(bool, lambda self: self._sort_ascending, notify=sortChanged)

    # ── 顶栏 / 筛选 ──────────────────────────────────────────

    @Slot(str)
    def setSearchText(self, text: str) -> None:
        """搜索框输入 —— 防抖 200ms 后查库（对齐原版 `_on_search_text`）。"""
        self._search_text = str(text)
        self._debounce.start(_SEARCH_DEBOUNCE_MS)

    @Slot(int)
    def setCategoryIndex(self, index: int) -> None:
        if 0 <= index < len(self._categories) and index != self._cat_index:
            self._cat_index = index
            self._apply()

    @Slot()
    def showMfgMode(self) -> None:
        self._show_m = True
        self._show_t = False
        self._upd()

    @Slot()
    def showTradeMode(self) -> None:
        self._show_t = True
        self._show_m = False
        self._upd()

    @Slot()
    def openMfgSettings(self) -> None:
        from ui_qml.bridge.score_dialogs_bridge import MfgQmlDialog

        dlg = MfgQmlDialog(self._mfg, self.host_widget())
        if dlg.exec():
            self._mfg = dlg.get()
        self._save_settings()
        if self._show_m:
            self._upd()

    @Slot()
    def openTradeSettings(self) -> None:
        from ui_qml.bridge.score_dialogs_bridge import TradeQmlDialog

        dlg = TradeQmlDialog(self._trade, self.host_widget())
        if dlg.exec():
            self._trade = dlg.get()
        self._save_settings()
        if self._show_t:
            self._upd()

    @Slot()
    def openCompare(self) -> None:
        """批量对比 —— 只带**当前选中行**（原版取 `selectionModel().selectedRows()`）。"""
        from ui_qml.bridge.compare_bridge import CompareQmlDialog

        items: list[dict] = []
        row = self._row_at(self._selected_row)
        if row and row.get("id"):
            items.append({"type_id": row["id"], "name": row.get("z", "")})
        dlg = CompareQmlDialog(initial_items=items, parent=self.host_widget())
        dlg.show()

    @Slot()
    def exportData(self) -> None:
        """导出当前表格数据（原 `_export_data`，父窗口走 `host_widget()`）。"""
        from core.export_helper import export_to_csv, export_to_excel
        from ui_qml.file_dialogs import get_save_filename

        if self._proxy.rowCount() == 0:
            self._set_status("没有数据可导出")
            return
        path = get_save_filename(self.host_widget(), _EXPORT_DEFAULT, _EXPORT_FILTER)
        if not path:
            return
        headers, rows = _export_table(self._col_specs, self._filt)
        try:
            if path.endswith(".xlsx"):
                export_to_excel(headers, rows, path)
            else:
                export_to_csv(headers, rows, path)
            self._set_status(f"已导出 {len(rows)} 行")
        except Exception as e:  # 磁盘满 / 权限 / 占用 —— 只把原因写进状态行，不打断对话框
            log.exception("导出全物品数据失败")
            self._set_status(f"导出失败: {e}")

    # ── 分类树 ───────────────────────────────────────────────

    def _on_tree_data(self, items: list[dict]) -> None:
        self._tree_all = market_tree_rows(items)
        self._expanded.clear()
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        self._tree_visible = visible_tree_rows(self._tree_all, self._expanded)
        self.treeChanged.emit()

    @Slot(int)
    def toggleTreeNode(self, index: int) -> None:
        """点箭头：展开 / 折叠（原版是 `QTreeWidget` 自带的箭头）。"""
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
        """点名字：加载该分类（含全部子分类）下的物品（原 `_on_tree`）。"""
        if not 0 <= index < len(self._tree_visible):
            return
        node_id = self._tree_visible[index]["id"]
        ids = subtree_ids(self._tree_all, node_id)
        if not ids:
            return
        self._selected_tree_id = int(node_id)
        # 原版 `self._search_input.clear()`：清空搜索框且不改动正在加载的数据集
        self._search_text = ""
        self.searchChanged.emit()
        self._data = []
        self._reload_items(sorted(ids))
        self.stateChanged.emit()

    def _reload_items(self, ids: list[Any] | None) -> None:
        drop_worker(self._iw)
        worker = ItemsW(ids, rid=JITA_RID, parent=self)
        worker.done.connect(self._on_items)
        worker.start()
        self._iw = worker

    def _on_items(self, rows: list[dict]) -> None:
        self._data = rows
        has_price = any(r.get("bp") or r.get("sp") for r in rows[:100])
        self._set_status(f"共 {len(rows)} 条" if has_price else "暂无价格，请先在主界面更新")
        self._apply()

    # ── 搜索 ─────────────────────────────────────────────────

    def _do_search(self) -> None:
        query = self._search_text.strip()
        if not query:
            return
        drop_worker(self._sw)
        self._set_status("搜索中...")
        worker = SearchItemsW(query, JITA_RID, self)
        worker.done.connect(self._on_search_done)
        worker.start()
        self._sw = worker

    def _on_search_done(self, rows: list[dict]) -> None:
        self._data = rows
        self._apply()

    # ── 筛选与列 ─────────────────────────────────────────────

    def _apply(self) -> None:
        """按当前类别过滤（原 `_apply`：两类模式各一套 product_ids 查询）。"""
        data = self._data
        cat = self._cat_index
        if self._manufacturable_only:
            if data:
                repo = get_container().blueprint_repo
                bp_ids: set[int]
                if cat == 0:
                    bp_ids = set(repo.get_all_product_ids("manufacturing"))
                elif cat == 1:
                    bp_ids = repo.get_t1_manufacturable_product_ids()
                elif cat == 2:
                    bp_ids = repo.get_t2_manufacturable_product_ids()
                elif cat == 3:
                    bp_ids = repo.get_faction_manufacturable_product_ids()
                else:
                    bp_ids = set(repo.get_all_product_ids("reaction"))
                data = [r for r in data if r["id"] in bp_ids]
            self._filt = data
            self._upd()
            return

        if data and cat > 0:
            repo = get_container().blueprint_repo
            if cat == 1:  # 无法制造获得 — 没有任何蓝图
                ids = repo.get_all_blueprint_product_ids()
                data = [r for r in data if r["id"] not in ids]
            elif cat == 2:  # 蓝图制造 T1
                ids = repo.get_t1_manufacturable_product_ids()
                data = [r for r in data if r["id"] in ids]
            elif cat == 3:  # 发明制造 T2
                ids = repo.get_t2_manufacturable_product_ids()
                data = [r for r in data if r["id"] in ids]
            elif cat == 4:  # 势力蓝图制造
                ids = repo.get_faction_manufacturable_product_ids()
                data = [r for r in data if r["id"] in ids]
            elif cat == 5:  # 反应
                ids = set(repo.get_all_product_ids("reaction"))
                data = [r for r in data if r["id"] in ids]
            elif cat == 6:  # 行星开发
                pi_ids = get_container().item_repo.get_planetary_product_ids()
                data = [r for r in data if r["id"] in pi_ids]
        self._filt = data
        self._upd()

    def _set_columns(self, cols: list[tuple]) -> None:
        self._col_specs = list(cols)
        self._model.set_cols(list(cols))
        self._reapply_sort()
        self.stateChanged.emit()

    def _set_rows(self, rows: list[dict]) -> None:
        self._model.set_rows(rows)
        self._reapply_sort()
        self.stateChanged.emit()

    def _upd(self) -> None:
        """按显示模式换列；有数据就异步算分（原 `_upd`）。"""
        if self._show_m:
            cols = list(BCOLS)
            cols[3] = (f"买价（{self._mfg['hub']}）", 100, "bp")
            cols[4] = (f"卖价（{self._mfg['hub']}）", 100, "sp")
            cols.extend(MCOLS)
            self._set_columns(cols)
            if self._filt:
                self._calc(True)
            else:
                self._set_status("无数据")
        elif self._show_t:
            cols = list(BCOLS)
            ptn = {"buy": "买单", "sell": "卖单"}
            cols[3] = (f"买价（{self._trade['bh']}{ptn.get(self._trade['bs'], '')}）", 100, "bp")
            cols[4] = (f"卖价（{self._trade['sh']}{ptn.get(self._trade['ss'], '')}）", 100, "sp")
            cols.extend(TCOLS)
            self._set_columns(cols)
            if self._filt:
                self._calc(False)
            else:
                self._set_status("无数据")
        else:
            self._set_columns(list(BCOLS))
            self._set_rows(self._filt)
            self._set_status(f"共 {len(self._filt)} 条")

    # ── 评分 ─────────────────────────────────────────────────

    def _calc(self, is_mfg: bool) -> None:
        # 原版直接覆盖 `self._wp`（旧线程继续跑、`done` 仍连着本桥，会拿过期数据回调）。
        # 这里先收尾旧线程：既是防「点两次评分弹两次结果」，也避免它在关窗时被连带析构。
        drop_worker(self._wp)
        self._progress_visible = True
        self._progress_max = len(self._filt)
        self._progress_value = 0
        self._set_status("计算评分中...")

        cfg = self._mfg if is_mfg else self._trade
        worker = ScoreW(list(self._filt), is_mfg, cfg, self)
        worker.progress.connect(self._on_score_progress)
        worker.done.connect(self._on_scored)
        worker.start()
        self._wp = worker

    def _on_score_progress(self, current: int, _total: int) -> None:
        self._progress_value = current
        self.stateChanged.emit()

    def _on_scored(self, rows: list[dict]) -> None:
        self._progress_visible = False
        self._filt = rows
        self._set_rows(self._filt)
        self._set_status(f"共 {len(self._filt)} 条 | 评分已计算")

    # ── 表头排序 ─────────────────────────────────────────────

    @Slot(int)
    def sortByColumn(self, column: int) -> None:
        """点表头排序 —— 排序规则仍是 `Proxy.lessThan`（原 `setSortingEnabled(True)`）。"""
        if not 0 <= column < len(self._col_specs):
            return
        if self._sort_column == column:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_column = column
            self._sort_ascending = True
        self._reapply_sort()
        self.sortChanged.emit()

    def _reapply_sort(self) -> None:
        """换列 / 换数据之后必须重下排序 —— 源模型的 `beginResetModel` 会清掉代理的排序态。"""
        if 0 <= self._sort_column < len(self._col_specs):
            order = Qt.SortOrder.AscendingOrder if self._sort_ascending else Qt.SortOrder.DescendingOrder
            self._proxy.sort(self._sort_column, order)

    # ── 表格行操作 ───────────────────────────────────────────

    def _row_at(self, row: int) -> dict | None:
        """代理行号 → 行数据（角色查询会转发到源模型的 `UserRole`）。"""
        if not 0 <= row < self._proxy.rowCount():
            return None
        data = self._proxy.data(self._proxy.index(row, 0), Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _mfg_key(self, type_id: int) -> str:
        return f"{type_id}|mfg|{self._mfg['hub']}|{self._mfg['char']}"

    def _trade_key(self, type_id: int) -> str:
        return f"{type_id}|trade|{self._trade['bh'] + self._trade['sh']}|{self._trade['char']}"

    @Slot(int, result=dict)
    def rowInfo(self, row: int) -> dict:
        """一行的关键信息，供右键菜单决定显示哪些条目。"""
        empty = {"valid": False, "typeId": 0, "name": "", "hasMfgDetail": False, "hasTradeDetail": False}
        data = self._row_at(row)
        if not data or not data.get("id"):
            return empty
        type_id = int(data["id"])
        return {
            "valid": True,
            "typeId": type_id,
            "name": data.get("z", "") or data.get("e", "") or str(type_id),
            "hasMfgDetail": bool(self._show_m and self._cache.get(self._mfg_key(type_id))),
            "hasTradeDetail": bool(self._show_t and self._cache.get(self._trade_key(type_id))),
        }

    @Slot(int, int)
    def clickCell(self, row: int, column: int) -> None:
        """单击单元格：选中该行并把这格文本复制到剪贴板（原 `_clk`）。"""
        if not 0 <= row < self._proxy.rowCount():
            return
        self._selected_row = row
        self.stateChanged.emit()
        data = self._row_at(row)
        if not data or not 0 <= column < len(self._col_specs):
            return
        value = data.get(self._col_specs[column][2])
        if value is None or str(value) == DASH or not str(value).strip():
            return
        QGuiApplication.clipboard().setText(str(value))

    @Slot(int)
    def openMaterials(self, row: int) -> None:
        """双击物品行 → 制造材料明细（原 `_dbl` → `MatDlg`）。"""
        data = self._row_at(row)
        if not data or not data.get("id"):
            return
        MatQmlDialog(int(data["id"]), self.host_widget()).exec()

    @Slot(int)
    def copyName(self, row: int) -> None:
        data = self._row_at(row)
        if data:
            QGuiApplication.clipboard().setText(str(data.get("z", "")))

    @Slot(int)
    def copyId(self, row: int) -> None:
        data = self._row_at(row)
        if data and data.get("id"):
            QGuiApplication.clipboard().setText(str(data["id"]))

    @Slot(int)
    def showBreakdown(self, row: int) -> None:
        """核算明细弹窗（原 `_ctx` 里的 `QMessageBox.information`）。"""
        data = self._row_at(row)
        if not data or not data.get("id"):
            return
        type_id = int(data["id"])
        if self._show_m:
            cached = self._cache.get(self._mfg_key(type_id))
            if cached:
                FMessageDialog.information(self.host_widget(), "制造核算明细", breakdown_text(cached, True))
                return
        if self._show_t:
            cached = self._cache.get(self._trade_key(type_id))
            if cached:
                FMessageDialog.information(self.host_widget(), "贸易核算明细", breakdown_text(cached, False))

    @Slot(int)
    def addToPlan(self, row: int) -> None:
        """「加入制造列表」（原 `_ctx._do_add_plan`）。"""
        info = self.rowInfo(row)
        if not info["valid"]:
            return
        type_id = int(info["typeId"])
        name = str(info["name"])
        score: dict = {}
        if self._show_m:
            score = self._cache.get(self._mfg_key(type_id)) or {}

        from ui_qml.bridge.industry_dialogs_bridge import AddPlanDialogQmlDialog

        dlg = AddPlanDialogQmlDialog(name, score, self.host_widget())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data:
            return
        insert_plan_from_score(type_id, name, score, data, self._mfg)
        FMessageDialog.information(self.host_widget(), "提示", f"已加入制造列表: {name}")

    @Slot(int, str)
    def addResearch(self, row: int, kind: str) -> None:
        """「加入拷贝 / 发明 / 效率研究规划」。

        原实现（`AllItemsDialog._add_research_plan`）里写死了 **Widgets 版**的三个研究
        计划对话框，直接复用会把 Widgets 窗口弹进 QML 页面；这里改用已迁好的 QML 版
        （构造签名与 `result_data()` 逐字兼容），蓝图查询那一段逐行照搬。
        """
        info = self.rowInfo(row)
        if not info["valid"]:
            return
        _add_research_plan(self.host_widget(), int(info["typeId"]), str(info["name"]), kind)

    # ── 置顶 ─────────────────────────────────────────────────

    @Slot(bool)
    def setPinned(self, pinned: bool) -> None:
        """「置顶」勾选框（原 `_on_pin_toggled`）。

        原版在 Windows 上专门走 `ctypes.SetWindowPos`（为的是避开
        `setWindowFlags` 引起的窗口重建），其他平台才改 flags + 重新 show。
        QML 版只有一份实现：改 flags 再 `show()`（即原版的非 Windows 分支）——
        窗口会闪一下，但跨平台一致且不引 ctypes。
        """
        self._pinned = bool(pinned)
        host = self.host_widget()
        if host is not None:
            flags = host.windowFlags()
            if self._pinned:
                host.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
            else:
                host.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
            host.show()
        self.stateChanged.emit()

    # ── 设置 ─────────────────────────────────────────────────

    def _settings_path(self) -> str:
        return os.path.join(data_dir(), "score_settings.json")

    def _load_settings(self) -> None:
        path = self._settings_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self._mfg.update(saved.get("mfg", {}))
            self._trade.update(saved.get("trade", {}))
        except Exception:
            # 原版这里是一段裸 `except: pass`；本仓禁止，改为记日志后按默认值继续
            log.exception("读取评分设置失败 path=%s", path)

    def _save_settings(self) -> None:
        path = self._settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"mfg": self._mfg, "trade": self._trade}, f, ensure_ascii=False, indent=2)
        except Exception:
            log.exception("保存评分设置失败 path=%s", path)

    # ── 关窗收尾 ─────────────────────────────────────────────

    def stop(self) -> None:
        """`QmlDialog._stop_bridge` 关窗时调它 —— 见模块 docstring 第 1 条。"""
        self._debounce.stop()
        for worker in (self._tw, self._iw, self._sw, self._wp):
            drop_worker(worker)

    def _set_status(self, text: str) -> None:
        self._status = str(text)
        self.stateChanged.emit()


class AllItemsQmlDialog(QmlDialog):
    """QML 版「全物品查询」。

    `AllItemsDialog(parent, manufacturable_only)` 的调用方把类名换掉即可 ——
    构造签名逐字一致，且和原版一样**不吃 parent**（独立顶层窗口 + 任务栏入口）。
    """

    def __init__(self, parent: Any = None, manufacturable_only: bool = False) -> None:
        bridge = AllItemsBridge(manufacturable_only)
        # 原版 `super().__init__()` 就没有 parent（注释：无 parent，完全独立窗口），
        # 这里同样不挂父窗口，只把 parent 收下以保持签名一致
        super().__init__(_ALL_QML, bridge, parent=None, size=(1100, 680))
        self._all_bridge = bridge
        self.setMinimumSize(800, 400)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        bridge.start()


def _add_research_plan(parent: Any, type_id: int, name: str, kind: str) -> None:
    """从全物品页直接建科研计划 —— 逐行照搬 `AllItemsDialog._add_research_plan`。

    物品 → 蓝图：制造蓝图查 `blueprint_products`；蓝图物品本身就是蓝图 type_id。
    其余情况给出提示（不是所有物品都能拷贝 / 发明 / 研究）。
    与 Widgets 版的**唯一差别**是三个计划对话框换成已迁好的 QML 版。
    """
    from services.research_plans import (
        create_research_plan,
        invention_base_runs,
        resolve_invention_source,
    )
    from ui_qml.bridge.research_plan_bridge import (
        CopyPlanDialogQmlDialog,
        InventionPlanDialogQmlDialog,
        ResearchPlanDialogQmlDialog,
    )

    db = get_container().db
    bp_id = int(type_id)
    try:
        with db.connect("bp", "ref") as conn:
            is_bp_item = bool(
                conn.execute(
                    "SELECT 1 FROM blueprint_activities WHERE blueprint_type_id = ? LIMIT 1", (bp_id,)
                ).fetchone()
            )
            if not is_bp_item:
                row = conn.execute(
                    "SELECT blueprint_type_id FROM blueprint_products WHERE product_type_id = ? LIMIT 1",
                    (bp_id,),
                ).fetchone()
                if not row:
                    FMessageDialog.information(parent, "提示", f"「{name}」没有蓝图，无法加入科研规划")
                    return
                bp_id = int(row[0])
            src = resolve_invention_source(conn, bp_id) if kind == "invention" else None
            copy_row = conn.execute(
                "SELECT max_production_limit FROM blueprint_activities "
                "WHERE blueprint_type_id = ? AND activity = 'copying' LIMIT 1",
                (bp_id,),
            ).fetchone()
            base_runs = (
                {
                    int(oc["blueprint_type_id"]): invention_base_runs(
                        conn, int(oc["blueprint_type_id"]), int(src["t1_blueprint_type_id"])
                    )
                    for oc in src["outcomes"]
                }
                if src
                else {}
            )
    except Exception:
        log.exception("读取蓝图信息失败 type_id=%s", type_id)
        FMessageDialog.warning(parent, "提示", "读取蓝图信息失败，见日志")
        return

    if kind == "invention":
        if src is None:
            FMessageDialog.information(parent, "提示", f"「{name}」不是 T2/T3 蓝图，无法发明")
            return
        dlg = InventionPlanDialogQmlDialog(
            src["t1_name"],
            outcomes=src["outcomes"],
            base_runs_by_outcome=base_runs,
            default_probability={int(o["blueprint_type_id"]): float(o["base_probability"]) for o in src["outcomes"]},
            parent=parent,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data() or {}
        product = int(data.get("product_blueprint_type_id") or 0)
        if not product:
            FMessageDialog.information(parent, "提示", "未选择发明产物")
            return
        create_research_plan(
            product,
            activity="invention",
            blueprint_name=data.get("product_name") or str(product),
            runs=int(data.get("attempts") or 1),
            mat_hangar_id=data.get("mat_hangar_id"),
            deposit_hangar_id=data.get("deposit_hangar_id"),
            solar_system_id=data.get("solar_system_id"),
            char_name=data.get("char_name") or "",
            facility=data.get("facility") or "",
            decryptor_type_id=data.get("decryptor_type_id"),
            success_rate=data.get("success_rate"),
        )
        FMessageDialog.information(parent, "完成", "已加入发明规划")
        return

    if kind == "copying":
        if not copy_row:
            FMessageDialog.information(parent, "提示", f"「{name}」没有拷贝活动")
            return
        copy_dlg = CopyPlanDialogQmlDialog(name, max_production_limit=int(copy_row[0] or 1), parent=parent)
        if copy_dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = copy_dlg.result_data() or {}
        create_research_plan(
            bp_id,
            activity="copying",
            blueprint_name=name,
            runs=int(data.get("runs_per_copy") or 1),
            parallels=int(data.get("copies") or 1),
            mat_hangar_id=data.get("mat_hangar_id"),
            deposit_hangar_id=data.get("deposit_hangar_id"),
            solar_system_id=data.get("solar_system_id"),
            char_name=data.get("char_name") or "",
            facility=data.get("facility") or "",
        )
        FMessageDialog.information(parent, "完成", "已加入拷贝规划")
        return

    research_dlg = ResearchPlanDialogQmlDialog(name, parent=parent)
    if research_dlg.exec() != QDialog.DialogCode.Accepted:
        return
    data = research_dlg.result_data() or {}
    create_research_plan(
        bp_id,
        activity=str(data.get("activity") or "researching_material_efficiency"),
        blueprint_name=name,
        runs=int(data.get("target_level") or 1),
        mat_hangar_id=data.get("mat_hangar_id"),
        deposit_hangar_id=data.get("deposit_hangar_id"),
        solar_system_id=data.get("solar_system_id"),
        char_name=data.get("char_name") or "",
        facility=data.get("facility") or "",
        research_target_level=int(data.get("target_level") or 1),
    )
    FMessageDialog.information(parent, "完成", "已加入效率研究规划")


# ══════════════════════════════════════════════════════════════
#  制造材料明细（原 `MatDlg`）
# ══════════════════════════════════════════════════════════════


def material_rows(type_id: int) -> tuple[str, bool, list[dict], str]:
    """制造材料明细 → `(物品名, 有无蓝图, 行, 合计文案)`。

    逐字对齐 `MatDlg.__init__`：名称取 `item_repo.get_name`，材料取
    `blueprint_repo.get_manufacturing_materials`，单价为空按 0 计。
    """
    container = get_container()
    name = str(container.item_repo.get_name(type_id))
    materials = container.blueprint_repo.get_manufacturing_materials(type_id)
    if materials is None:
        return name, False, [], ""
    _bp_id, mats = materials
    rows: list[dict] = []
    total = 0.0
    for mid, qty, zh, en, sp in mats:
        label = zh or en or str(mid)
        price = sp or 0
        subtotal = price * qty
        total += subtotal
        rows.append(
            {
                "iconUrl": icon_url(mid),
                "text": f"  {label} x{qty:,} @ {price:,.2f} = {subtotal:,.2f}",
            }
        )
    return name, True, rows, f"总成本: {total:,.2f} ISK"


class MatBridge(DialogBridge):
    """「制造材料」明细的 QML 后端（原 `MatDlg`）。"""

    def __init__(self, type_id: int) -> None:
        super().__init__()
        self.set_title("制造材料")
        self._name, self._found, self._rows, self._total = material_rows(int(type_id))
        self._title_text = f"制造材料: {self._name}"

    #: 标题行（原版那条加粗的 `QLabel`）
    itemTitle = Property(str, lambda self: self._title_text, constant=True)
    #: 有没有制造蓝图 —— 没有时只显示一行红字
    found = Property(bool, lambda self: self._found, constant=True)
    rows = Property(list, lambda self: [dict(r) for r in self._rows], constant=True)
    totalText = Property(str, lambda self: self._total, constant=True)


class MatQmlDialog(QmlDialog):
    """QML 版「制造材料」。`MatDlg(tid, parent)` 的调用方原样可用。"""

    def __init__(self, tid: int, parent: Any = None) -> None:
        bridge = MatBridge(tid)
        super().__init__(_MAT_QML, bridge, parent=parent, size=(460, 280))
        self._mat_bridge = bridge
