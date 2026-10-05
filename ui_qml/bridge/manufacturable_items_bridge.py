"""可制造物品浏览器的桥。

工具栏（刷新计算 + 内联的「中心 / 人物 / 设施税」+ 最右「置顶」）→ 筛选行（搜索 +
类别 + 库存 + 日销量 + 利润率下限 + 状态）→ 3px 进度条 → 左树右表。

**取数与评分一行都不在这里实现**：分类树走 `MfgTreeW`，物品/搜索走
`ui_qml/workers/all_items_workers`，评分走 `ui_qml/workers/score_worker.ScoreW`，
表格展示与排序仍走 `ui_qml/models/all_items_models` 的 `AModel` / `Proxy`。
本桥只做状态搬运与筛选。

与本仓其它窗口对齐的三处「统一逻辑」（用户要求）：

1. **置顶是 `FCheckBox`、靠在最右**（同 `AllItemsDialog.qml` / `ProcurementWindow.qml`），
   并且走全仓共享的 `ui_qml/pin_utils.apply_window_pin`（Win32 `SetWindowPos`，
   不重建窗口、不闪）—— 不再抄第二份 `setWindowFlags` 版本。
2. **设置项内联在窗口里**（中心 / 人物 / 设施税，同贸易页把「从/到中心 + 买卖价类型」
   直接铺在工具栏），没有二级「设置」对话框。内联控件的回写必须用
   `onActivated / onValueModified` 主动调 slot，**不能写成 `currentIndex:
   model.indexOf(...)` 那种属性绑定**（用户的选择会被绑定立刻冲回去，见
   `FPriceSourceRow.qml` 的说明）。
3. **列宽按内容实测**（`QFontMetrics`，先例 `plan_table_bridge.autofitWidths`），
   末列不再吃满剩余宽度 —— 这个窗口是覆盖在游戏上的，越窄越好。

新增的两列「日订单量 / 日成交量」取自 `market.db.price_history` 的近 7 日聚合
（`services.price_history.get_history_summary`）：**本窗口零 ESI 请求**，数据由主界面
右上角的「更新价格」统一拉取（见 `docs/dev/flows.md`）。

三处需要留意的接线：

1. **后台线程必须在关窗前收尾**（`stop()` → `drop_worker`）。
2. **分类树点击有 200ms 防抖**：`selectTreeNode` 只记下标并起表，真正的加载在
   `_on_tree_delayed()`。展开箭头即时生效，不走防抖。
3. **换 ItemsW 前先断开旧 worker 的 `done`**，否则很快地点两棵树时先发出的结果会
   覆盖后一次的数据。
"""

from __future__ import annotations

import json
import os
from typing import Any

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication
from PySide6.QtWidgets import QDialog

from core.cache import TtlLRUCache
from core.constants import TRADE_HUBS
from core.container import get_container
from core.logger import log
from core.paths import data_dir
from services import char_config_resolver
from services.inventory_manager import (
    STATE_BPC_INVENTABLE,
    STATE_BPO,
    STATE_IN_PLAN,
    STATE_NO_BLUEPRINT,
    get_production_state_flags,
    get_stock_and_order_flags,
)
from services.price_history import get_history_summary
from ui_qml.bridge.all_items_bridge import (
    drop_worker,
    insert_plan_from_score,
    market_tree_rows,
    subtree_ids,
    visible_tree_rows,
)
from ui_qml.bridge.message_dialog import FMessageDialog
from ui_qml.constants import MFG_CATEGORIES
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.models.all_items_models import Proxy, display_text
from ui_qml.models.all_items_qml_model import AllItemsQmlModel
from ui_qml.pin_utils import apply_window_pin
from ui_qml.theme import registry as theme
from ui_qml.workers.all_items_workers import JITA_RID, ItemsW, SearchItemsW
from ui_qml.workers.mfg_tree_worker import MfgTreeW
from ui_qml.workers.score_worker import ScoreW

__all__ = [
    "ManufacturableItemsBridge",
    "ManufacturableItemsQmlDialog",
    "breakdown_text",
    "subtree_category_counts",
]

_QML_FILE = "dialogs/ManufacturableItemsDialog.qml"

#: 搜索 / 树节点点击的防抖（原版两个 `QTimer` 都是 200ms）
_DEBOUNCE_MS = 200

#: 本窗口自己的基础列（**不用 `all_items_models.BCOLS`**：那份被「全物品查询」窗口共用，
#: 这里要删「均价 / 体积」）。宽度只是**首帧兜底**，真正常用的是 `_autofit_widths()`。
_MFG_BCOLS = [
    ("图标", 36, "i"),
    ("中文名", 130, "z"),
    ("English", 150, "e"),
    ("买价", 90, "bp"),
    ("卖价", 90, "sp"),
]

#: 本窗口自己的制造列：删掉「日利润 / 收益」（用户要求），加「日订单量 / 日成交量」。
#:
#: 后两列的标题**带上区域名**：窗口的「中心」可以切到 Amarr，而市场历史只按 Jita 聚合
#: （写入端 `services/importers/getprices.HISTORY_REGION_ID`，读端 `JITA_RID`）——
#: 不写清楚会把「Amarr 的买价」和「Jita 的销量」看成同一个市场。
_MFG_MCOLS = [
    ("成本", 100, "mc"),
    ("利润/件", 100, "mr"),
    ("产能/天", 62, "mh"),
    ("日订单量(Jita)", 96, "oc"),
    ("日成交量(Jita)", 96, "ocv"),
    ("状态", 90, "ms"),
    ("利润率%", 62, "mm"),
]

#: 类别下拉项 ↔ 产物 id 集合的键（顺序必须与 `MFG_CATEGORIES` 一致）
_CAT_KEYS = ("all", "t1", "t2", "faction", "reaction")

#: 「库存 / 状态」筛选。前四档是库存挂单（语义与仓库页状态列一致：`inventory_items.quantity>0`
#: 全机库合计；`open_orders.volume_remain>0` 买卖单都算），**后四档按用户要求并进同一个下拉**
#: （原来想单开一个「状态」下拉，用户否了：不加新筛选，并到这一栏里）：
#: 无蓝图 / 有原图待拷贝 / 有拷贝待发明 / 正在制造（有库存 = 上面的「库中有」）。
_STOCK_FILTERS = [
    "全部",
    "库中有",
    "有挂单",
    "库中有且有挂单",
    "无蓝图",
    "有原图待拷贝",
    "有拷贝待发明",
    "正在制造",
]

#: `_STOCK_FILTERS` 后四档对应的状态标记（前四档为 `None` —— 它们查的是库存/挂单两个布尔）
_STOCK_STATE_KEYS: tuple[str | None, ...] = (
    None,
    None,
    None,
    None,
    STATE_NO_BLUEPRINT,
    STATE_BPO,
    STATE_BPC_INVENTABLE,
    STATE_IN_PLAN,
)

#: 「日销量」筛选（按「日成交量」列 = 近 7 日平均成交量）
_SALES_FILTERS = ["全部", "≥1", "≥10", "≥100", "≥1000"]
_SALES_THRESHOLDS = [0.0, 1.0, 10.0, 100.0, 1000.0]

#: 表头 / 数据格文字两侧留白（列宽实测用，口径同 `plan_table_bridge`）：
#: 表头 delegate 左右各 6，排序列还占「6 + 2 + 10(箭头) + 6」；数据格 6 + 6。
_HEADER_TEXT_MARGIN = 24
_BODY_TEXT_MARGIN = 16

#: 内容列的宽度上限（**紧凑优先**）：名称类不封顶会把窗口撑到屏幕外；
#: 数值类封顶是防脏数据把某一列拉爆。缺省 = 不封顶。
_MAX_WIDTHS = {"z": 150, "e": 160, "ms": 110, "mc": 110, "mr": 110}

#: 图标列固定宽（对齐 QML delegate 的 18px 图标 + 左右留白）
_ICON_COL_WIDTH = 36


def _header_font() -> QFont:
    """表头字体（11px）—— 与 QML 表头 delegate 的 `page.fntSmall` 同源。"""
    font = QFont(theme.FONT_FAMILY)
    font.setPixelSize(theme.fs(11))
    return font


def breakdown_text(r: dict) -> str:
    """制造核算明细的正文 —— 逐字照搬 Widgets 版 `ManufacturableItemsDialog._ds`。

    与 `all_items_bridge.breakdown_text(r, True)` 不是同一份文案：这个窗口只做制造，
    写的是「评分 / 每小时利润 / 运行成本」那一组，状态码也少了 `no_depth`。
    两边各自忠于各自的实现，不强行合并。
    """
    b = r.get("breakdown", {})
    st = r.get("status", "")
    if st:
        tips = {"no_blueprint": "此物品没有制造蓝图", "no_price": "查不到价格数据", "no_mats": "蓝图无材料数据"}
        return f"状态: {tips.get(st, st)}"
    lines = [
        f"评分: {r.get('score', 0):.0f}",
        f"单批利润: {r.get('profit_per_run', 0):,.0f} ISK",
        f"利润率: {r.get('margin_pct', 0):.1f}%",
        f"每小时利润: {r.get('isk_per_hour', 0):,.0f} ISK",
        f"材料成本: {b.get('material_cost', 0):,.0f} ISK",
    ]
    run_cost = b.get("run_cost", 0)
    if run_cost:
        lines.append(f"运行成本: {run_cost:,.0f} ISK")
    install = b.get("install_fee", 0)
    if install:
        lines.append(f"安装费: {install:,.0f} ISK")
    broker = b.get("broker_fee", 0)
    if broker:
        lines.append(f"经纪人费: {broker:,.0f} ISK")
    sales_tax = b.get("sales_tax", 0)
    if sales_tax:
        lines.append(f"销售税: {sales_tax:,.0f} ISK")
    return "\n".join(lines)


def subtree_category_counts(
    rows: list[dict],
    product_groups: dict[int, int],
    category_sets: dict[str, set[int]],
) -> dict[Any, dict[str, int]]:
    """每个树节点在**各类别**下的产物个数（含整棵子树）—— 纯函数。

    `rows` 是 `market_tree_rows()` 交出来的深度优先平表，`product_groups` 是
    `{产物 type_id: 市场分类 id}`。先按「直接挂在该分类下」计数，再**倒序**滚上去
    （深度优先序保证子节点永远排在父节点之后，所以倒着累加一次就够）。

    用途：判断某节点在**当前类别**下有没有物品 —— 没有就置灰（而不是从树里删掉：
    用户要的是「结构稳定 + 置灰 + 点击给提示」，见 goal 记录）。
    """
    counts: dict[Any, dict[str, int]] = {row["id"]: {} for row in rows}
    for tid, gid in product_groups.items():
        bucket = counts.get(gid)
        if bucket is None:
            continue
        for cat, ids in category_sets.items():
            if tid in ids:
                bucket[cat] = bucket.get(cat, 0) + 1
    for row in reversed(rows):
        parent = row.get("parent")
        if parent in counts:
            parent_bucket = counts[parent]
            for cat, n in counts[row["id"]].items():
                parent_bucket[cat] = parent_bucket.get(cat, 0) + n
    return counts


def _copy_row(cols: list[tuple], row: dict) -> str:
    """一行的制表符文本：图标列写 type_id，其余列走 `display_text`（与表格显示一致）。"""
    parts = []
    for _title, _width, key in cols:
        parts.append(str(row.get("id", "")) if key == "i" else display_text(row, key))
    return "\t".join(parts)


def _character_names() -> list[str]:
    """人物下拉的条目。取不到人物时退化成 `["main"]`（同 `score_dialogs_bridge`）。"""
    names = list(char_config_resolver.get_character_list())
    return names if names else ["main"]


def _combo_index(values: list[str], wanted: str) -> int:
    """按值找下拉下标；找不到给 0（非可编辑下拉框不会因为设了不存在的文本而清空）。"""
    try:
        return values.index(wanted)
    except ValueError:
        return 0


class ManufacturableItemsBridge(DialogBridge):
    """可制造物品浏览器的 QML 后端。"""

    #: 状态行 / 进度 / 列 / 分类下标 / 选中行 / 钉住
    stateChanged = Signal()
    treeChanged = Signal()
    searchChanged = Signal()
    sortChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.set_title("可制造物品")

        self._categories: list[str] = list(MFG_CATEGORIES)
        self._cat_index = 0
        self._data: list[dict] = []
        self._filt: list[dict] = []
        self._view: list[dict] = []
        self._mfg: dict[str, Any] = {"hub": "Jita", "char": "main", "tax": 0}
        #: 筛选器：类别 + 库存/挂单 + 日销量 + 利润率下限（空 = 不筛）。
        #: **要在 `_load_settings()` 之前给默认值** —— 落盘里存着上次的选择（用户要求
        #: 「筛选项能保存，不要每次都去设置」）。
        self._stock_index = 0
        self._sales_index = 0
        self._min_margin_text = ""
        self._min_margin: float | None = None
        self._load_settings()

        self._characters: list[str] = _character_names()
        self._hub_index = _combo_index(list(TRADE_HUBS), str(self._mfg.get("hub", "Jita")))
        self._char_index = _combo_index(self._characters, str(self._mfg.get("char", "main")))
        #: 落盘值以「下拉里真实存在的项」为准（配置里的区域/人物被改名后要退回首项）
        self._mfg["hub"] = list(TRADE_HUBS)[self._hub_index]
        self._mfg["char"] = self._characters[self._char_index]

        self._col_specs: list[tuple] = list(_MFG_BCOLS)
        self._status = "请选择分类或搜索物品"
        self._progress_visible = False
        self._progress_value = 0
        self._progress_max = 0
        self._search_text = ""
        self._selected_row = -1
        self._selected_tree_id = -1
        self._selected_tree_name = ""
        self._pinned = False
        self._sort_column = -1
        self._sort_ascending = True

        #: 当前这批行**整批**都没有市场历史（状态行据此提示去更新价格）
        self._history_missing = False
        #: 有历史但**整批都过期**（最新记录早于近 7 天窗口）→ 同样提示去更新价格
        self._history_stale = False

        self._tree_all: list[dict] = []
        self._tree_visible: list[dict] = []
        self._expanded: set[Any] = set()
        self._pending_tree_index = -1
        #: {节点 id: {类别键: 个数}}（树数据到了才算一次；切类别只读它）
        self._cat_counts: dict[Any, dict[str, int]] = {}
        #: 类别键 → 产物 id 集合。**按窗口缓存**：五个查询里有一条是跨库 LIKE 扫描，
        #: 而它在一个窗口的生命周期内不会变（蓝图库重导入要重开窗口才刷新）。
        self._cat_sets: dict[str, set[int]] | None = None

        #: 与 Widgets 版同参的评分缓存。**两边都只读不写**，保留是为了让
        #: 「命中缓存才显示核算明细」这条判断逐字不变。
        self._cache = TtlLRUCache(max_size=5000, ttl_seconds=1800)

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
        self._tree_debounce = QTimer(self)
        self._tree_debounce.setSingleShot(True)
        self._tree_debounce.timeout.connect(self._on_tree_delayed)

    # ── 启动 ─────────────────────────────────────────────────

    def start(self) -> None:
        """开窗时加载可制造分类树（数据源 = 制造 ∪ 反应产物，见 `MfgTreeW`）。"""
        self._tw = MfgTreeW(self)
        self._tw.done.connect(self._on_tree_data)
        self._tw.start()

    # ── 给 QML 读 ────────────────────────────────────────────

    model = Property(QObject, lambda self: self._proxy, constant=True)
    columns = Property(
        list, lambda self: [{"title": t, "width": w} for t, w, _k in self._col_specs], notify=stateChanged
    )
    categories = Property(list, lambda self: list(self._categories), constant=True)
    statusText = Property(str, lambda self: self._status, notify=stateChanged)
    categoryIndex = Property(int, lambda self: self._cat_index, notify=stateChanged)
    selectedRow = Property(int, lambda self: self._selected_row, notify=stateChanged)
    selectedTreeId = Property(int, lambda self: self._selected_tree_id, notify=stateChanged)
    searchText = Property(str, lambda self: self._search_text, notify=searchChanged)
    progressVisible = Property(bool, lambda self: self._progress_visible, notify=stateChanged)
    progressValue = Property(int, lambda self: self._progress_value, notify=stateChanged)
    progressMax = Property(int, lambda self: self._progress_max, notify=stateChanged)
    rowCount = Property(int, lambda self: self._proxy.rowCount(), notify=stateChanged)
    treeRows = Property(list, lambda self: list(self._tree_visible), notify=treeChanged)
    pinned = Property(bool, lambda self: self._pinned, notify=stateChanged)
    sortColumn = Property(int, lambda self: self._sort_column, notify=sortChanged)
    sortAscending = Property(bool, lambda self: self._sort_ascending, notify=sortChanged)
    #: 表格空态文案：除了「没有数据」，点中「当前类别下没东西」的节点时给出原因
    emptyText = Property(str, lambda self: self._empty_text, notify=stateChanged)

    #: 内联评分设置（原先在「设置」二级对话框里）
    hubs = Property(list, lambda self: list(TRADE_HUBS), constant=True)
    characters = Property(list, lambda self: self._characters, constant=True)
    hubIndex = Property(int, lambda self: self._hub_index, notify=stateChanged)
    charIndex = Property(int, lambda self: self._char_index, notify=stateChanged)
    tax = Property(float, lambda self: float(self._mfg.get("tax", 0) or 0), notify=stateChanged)

    #: 筛选器
    stockFilters = Property(list, lambda self: list(_STOCK_FILTERS), constant=True)
    stockFilterIndex = Property(int, lambda self: self._stock_index, notify=stateChanged)
    salesFilters = Property(list, lambda self: list(_SALES_FILTERS), constant=True)
    salesFilterIndex = Property(int, lambda self: self._sales_index, notify=stateChanged)
    minMarginText = Property(str, lambda self: self._min_margin_text, notify=stateChanged)

    # ── 顶栏 / 筛选 ──────────────────────────────────────────

    @Slot(str)
    def setSearchText(self, text: str) -> None:
        self._search_text = str(text)
        self._debounce.start(_DEBOUNCE_MS)

    @Slot(int)
    def setCategoryIndex(self, index: int) -> None:
        """换类别：重刷树的置灰标记 + 用同一批物品重筛（**不重新取数**）。"""
        if 0 <= index < len(self._categories) and index != self._cat_index:
            self._cat_index = index
            self._save_settings()
            self._refresh_tree()
            self._apply()

    @Slot(int)
    def setStockFilterIndex(self, index: int) -> None:
        if 0 <= index < len(_STOCK_FILTERS) and index != self._stock_index:
            self._stock_index = index
            self._save_settings()
            self._apply()

    @Slot(int)
    def setSalesFilterIndex(self, index: int) -> None:
        if 0 <= index < len(_SALES_FILTERS) and index != self._sales_index:
            self._sales_index = index
            self._save_settings()
            self._apply_view()

    @Slot(str)
    def setMinMarginText(self, text: str) -> None:
        """「利润率 ≥ x%」：空 / 非法输入 = 不筛（**不能拿 0 当默认**，否则默认滤掉亏损行）。"""
        self._min_margin_text = str(text)
        self._min_margin = self._parse_margin(self._min_margin_text)
        self._save_settings()
        self._apply_view()

    @staticmethod
    def _parse_margin(text: str) -> float | None:
        raw = text.strip().replace("%", "").replace(",", "")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    @Slot(int)
    def setHubIndex(self, index: int) -> None:
        """换中心：列标题与取价区域都变 → 重下列并重算。"""
        hubs = list(TRADE_HUBS)
        if not 0 <= index < len(hubs) or hubs[index] == self._mfg.get("hub"):
            return
        self._hub_index = index
        self._mfg["hub"] = hubs[index]
        self._save_settings()
        self._cache.invalidate()
        self._upd()

    @Slot(int)
    def setCharIndex(self, index: int) -> None:
        """换人物：只落盘 + 提示重算（换个人物就自动重跑上千行评分太贵）。"""
        if not 0 <= index < len(self._characters) or self._characters[index] == self._mfg.get("char"):
            return
        self._char_index = index
        self._mfg["char"] = self._characters[index]
        self._save_settings()
        self._set_status("已切换人物；点「刷新计算」用新技能重算")

    @Slot(float)
    def setTax(self, value: float) -> None:
        tax = min(100.0, max(0.0, float(value)))
        if tax == float(self._mfg.get("tax", 0) or 0):
            return
        self._mfg["tax"] = tax
        self._save_settings()
        self._set_status("已更新设施税；点「刷新计算」用新税率重算")

    @Slot()
    def refreshScores(self) -> None:
        """「刷新计算」：重读本地历史/库存标记 → 清缓存 → 用最新价格重算。"""
        if not self._filt:
            return
        # 单条 SQL 确认 market_prices 是否有数据，避免 N 次 get_price 调用
        if get_container().market_repo.has_any_prices():
            self._cache.invalidate()
            self._set_status("重新计算中...")
            self._apply()
        else:
            self._set_status("暂无价格数据，请先在主界面更新价格")

    # ── 分类树 ───────────────────────────────────────────────

    def _on_tree_data(self, items: list[dict], groups: dict | None = None) -> None:
        self._tree_all = market_tree_rows(items)
        self._cat_counts = subtree_category_counts(self._tree_all, dict(groups or {}), self._category_sets())
        self._expanded.clear()
        self._refresh_tree()

    def _category_sets(self) -> dict[str, set[int]]:
        """五个类别各自的产物 id 集合（**按窗口缓存**，窗口生命周期内不变）。"""
        if self._cat_sets is None:
            repo = get_container().blueprint_repo
            self._cat_sets = {
                "all": set(repo.get_all_product_ids("manufacturing")),
                "t1": set(repo.get_t1_manufacturable_product_ids()),
                "t2": set(repo.get_t2_manufacturable_product_ids()),
                "faction": set(repo.get_faction_manufacturable_product_ids()),
                "reaction": set(repo.get_all_product_ids("reaction")),
            }
        return self._cat_sets

    @property
    def _cat_key(self) -> str:
        return _CAT_KEYS[min(self._cat_index, len(_CAT_KEYS) - 1)]

    @property
    def _empty_text(self) -> str:
        """表格空态文案：能说清原因就说清（「点了空节点」不是「没数据」）。"""
        if self._filt:
            return "没有数据"
        if self._selected_tree_name:
            return f"当前类别「{self._categories[self._cat_index]}」下「{self._selected_tree_name}」没有可制造物品"
        return "没有数据"

    def _refresh_tree(self) -> None:
        cat = self._cat_key
        rows: list[dict] = []
        for row in visible_tree_rows(self._tree_all, self._expanded):
            item = dict(row)
            # 置灰 = 该节点子树里没有当前类别的物品（仍可点，点了给提示）
            item["empty"] = self._cat_counts.get(row["id"], {}).get(cat, 0) == 0
            rows.append(item)
        self._tree_visible = rows
        self.treeChanged.emit()

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
        """点分类：只记下标 + 起防抖表（原 `_on_tree` → `_on_tree_delayed`）。"""
        if not 0 <= index < len(self._tree_visible):
            return
        self._pending_tree_index = index
        self._tree_debounce.start(_DEBOUNCE_MS)

    def _on_tree_delayed(self) -> None:
        index = self._pending_tree_index
        if not 0 <= index < len(self._tree_visible):
            return
        row = self._tree_visible[index]
        node_id = row["id"]
        ids = subtree_ids(self._tree_all, node_id)
        if not ids:
            return

        self._selected_tree_id = int(node_id)
        self._selected_tree_name = str(row["name"])
        # 原版 `self._search_input.clear()`
        self._search_text = ""
        self.searchChanged.emit()
        self._data = []
        self._reload_items(sorted(ids))
        self.stateChanged.emit()

    def _reload_items(self, ids: list[Any] | None) -> None:
        # 断开旧 worker 的 `done` 再换新：否则先发出的那次结果会覆盖后一次的数据
        old = self._iw
        if old is not None:
            try:
                old.done.disconnect()
            except (TypeError, RuntimeError):
                pass
            drop_worker(old)

        # 只取「有制造/反应蓝图产物」的物品：不下推这个条件的话，`fetch_items` 的
        # `LIMIT 2000` 会先截断再过滤（实测「舰船装备」真实 1265 个可制造物品只出 792 个）
        worker = ItemsW(ids, rid=JITA_RID, parent=self, manufacturable_only=True)
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
        self._selected_tree_name = ""
        self._data = rows
        self._apply()

    # ── 筛选与列 ─────────────────────────────────────────────

    def _apply(self) -> None:
        """类别 → 库存/挂单 → 日订单量/成交量（本地读）→ 落表并起评分。"""
        data = self._data
        ids = self._category_sets()[self._cat_key]
        rows = [r for r in data if r["id"] in ids] if data else []
        self._attach_stock_flags(rows)
        rows = [r for r in rows if self._stock_ok(r)]
        self._attach_history(rows)
        self._filt = rows
        self._upd()

    def _attach_stock_flags(self, rows: list[dict]) -> None:
        """一次批量查「库中有 / 有挂单」（本机两张表分别 158 / 8 行，微秒级）+ 状态标记。

        状态标记（无蓝图 / 有原图 / 有拷贝可发明 / 在跑的计划）见
        `services.inventory_manager.get_production_state_flags`：同样是批量、本地库，零 ESI。
        两者一起挂，是因为它们喂的是**同一个下拉**（用户要求并进「库存」那一栏）。
        """
        if not rows:
            return
        ids = [r["id"] for r in rows]
        flags = get_stock_and_order_flags(ids, db=get_container().db)
        states = get_production_state_flags(ids, db=get_container().db)
        for row in rows:
            stocked, listed = flags.get(row["id"], (False, False))
            row["_stock"] = stocked
            row["_orders"] = listed
            row["_state"] = states.get(row["id"], frozenset())

    def _stock_ok(self, row: dict) -> bool:
        if self._stock_index == 0:
            return True
        stocked = bool(row.get("_stock"))
        listed = bool(row.get("_orders"))
        if self._stock_index == 1:
            return stocked
        if self._stock_index == 2:
            return listed
        if self._stock_index == 3:
            return stocked and listed
        key = _STOCK_STATE_KEYS[self._stock_index]
        return key in (row.get("_state") or ())

    def _attach_history(self, rows: list[dict]) -> None:
        """近 7 个**日历天**平均订单量 / 成交量 —— **本地缓存一次 SQL，零 ESI 请求**。

        数据由「更新价格」统一拉取（见 `docs/dev/flows.md`）。查不到 → `None`（表格显示 `—`），
        **不用 0 冒充**：0 是「这些天确实没成交」，`—` 是「不知道」。

        ⚠️ 窗口是日历天（`get_history_summary` 的说明）：ESI 历史只返回有成交的日子，
        按「最近 7 条记录」会变成「上次活跃那几天」——实测 `屹立白蚁 II` 已经两个多月
        没成交，却算出 21.6/天。
        """
        if not rows:
            self._history_missing = False
            self._history_stale = False
            return
        summary = get_history_summary([r["id"] for r in rows], region_id=JITA_RID, _db=get_container().db)
        for row in rows:
            item = summary.get(row["id"])
            row["oc"] = item["oc"] if item else None
            row["ocv"] = item["vol"] if item else None
        # 整批都没有历史 → 状态行提示去「更新价格」（在**取数**这一步判定，
        # 不在 `_view_status` 里按当前行猜 —— 评分后的行是另一批 dict）
        self._history_missing = all(r.get("ocv") is None for r in rows)
        # 有历史、但**整批都过期**（最新记录早于 7 天窗口）→ 状态行说清「数据太旧」，
        # 否则满屏 `—` 会让人以为是物品的问题
        self._history_stale = (
            bool(summary) and not self._history_missing and all(item.get("stale") for item in summary.values())
        )

    def _set_columns(self, cols: list[tuple]) -> None:
        self._col_specs = list(cols)
        self._model.set_cols(list(cols))
        self._reapply_sort()
        self.stateChanged.emit()

    def _set_rows(self, rows: list[dict]) -> None:
        # 每次换行都重量列宽：评分前后同一列从「—」变成「1,432,815.20」，
        # 只量一次会让数字列被裁。长名称列量到封顶就 break，代价可控。
        self._autofit_widths(rows)
        self._model.set_rows(rows)
        self._reapply_sort()
        self.stateChanged.emit()

    def _upd(self) -> None:
        """始终显示 自己的基础列 + 制造列，数据先落表再异步算分。"""
        cols = list(_MFG_BCOLS)
        hub = self._mfg["hub"]
        cols[3] = (f"买价（{hub}）", cols[3][1], "bp")
        cols[4] = (f"卖价（{hub}）", cols[4][1], "sp")
        cols.extend(_MFG_MCOLS)
        self._set_columns(cols)
        if self._filt:
            self._set_rows(self._filt)
            self._set_status(f"共 {len(self._filt)} 条 | 计算评分中...")
            self._calc()
        else:
            self._view = []
            self._set_rows([])
            self._set_status(self._empty_status())

    def _empty_status(self) -> str:
        """表格空态的状态行文案：能说清原因就说清（与 `emptyText` 同一口径）。"""
        if self._selected_tree_name:
            return f"「{self._selected_tree_name}」在当前类别下没有可制造物品"
        return "无数据"

    # ── 评分 ─────────────────────────────────────────────────

    def _calc(self) -> None:
        # 原版这里要断旧 worker 的 progress/done 再换新（否则旧回调会覆盖新结果）；
        # `drop_worker` 一并把线程收尾 —— 正在跑的 QThread 被连带析构会中止进程
        drop_worker(self._wp)
        self._progress_visible = True
        self._progress_max = len(self._filt)
        self._progress_value = 0
        self._set_status("计算评分中...")

        worker = ScoreW(list(self._filt), True, self._mfg, self)
        worker.progress.connect(self._on_score_progress)
        worker.done.connect(self._on_scored)
        worker.start()
        self._wp = worker

    def _on_score_progress(self, current: int, _total: int) -> None:
        self._progress_value = current
        self.stateChanged.emit()

    def _on_scored(self, rows: list[dict]) -> None:
        self._filt = rows
        self._progress_visible = False
        # 「利润/件」= 卖价 − 成本（用户要求：这一列不该是把卖价再抄一份）。
        # 评分线程每次都重写 `mr`（= `revenue_per_unit`），所以这里改是幂等的；
        # 原始字段 `revenue_per_unit` 不动，核算明细/右键仍按原口径取。
        for row in rows:
            cost = row.get("mc")
            revenue = row.get("mr")
            row["mr"] = (revenue - cost) if isinstance(revenue, int | float) and isinstance(cost, int | float) else None
        self._apply_view()

    # ── 视图筛选（利润率 / 日销量）───────────────────────────

    def _apply_view(self) -> None:
        """在**已算好的行**上套「利润率 ≥ x%」「日销量 ≥ N」——不重算、不查库。"""
        self._view = [r for r in self._filt if self._sales_ok(r) and self._margin_ok(r)]
        self._set_rows(self._view)
        self._set_status(self._view_status())

    def _sales_ok(self, row: dict) -> bool:
        threshold = _SALES_THRESHOLDS[self._sales_index]
        if threshold <= 0:
            return True
        vol = row.get("ocv")
        # 「不知道卖不卖得动」不算通过 —— 筛选是有意义的业务判断，不是兜底
        return vol is not None and float(vol) >= threshold

    def _margin_ok(self, row: dict) -> bool:
        if self._min_margin is None:
            return True
        margin = row.get("mm")
        return margin is not None and float(margin) >= self._min_margin

    def _view_status(self) -> str:
        total = len(self._filt)
        shown = len(self._view)
        head = f"共 {total} 条" if shown == total else f"共 {total} 条，筛选后 {shown} 条"
        tail = " | 评分已计算"
        if self._history_missing:
            tail += " | 市场历史为空：请点右上角「更新价格」"
        elif self._history_stale:
            tail += " | 本地历史已过期（近 7 天无记录）：请点右上角「更新价格」"
        return head + tail

    # ── 列宽实测（紧凑优先）──────────────────────────────────

    def _autofit_widths(self, rows: list[dict]) -> None:
        """按表头 + 实际内容实测每列宽度（`QFontMetrics`，先例 `plan_table_bridge`）。

        为什么不用固定宽度：这个窗口是**覆盖在游戏上的**，列宽拍死就会遮住后面的游戏
        数据（用户要求「自适应 + 尽量紧凑」）。为什么不在 QML 里量：QML 侧要对上千行 ×
        十几列做 `TextMetrics` 太慢，而 Python 的 `QFontMetrics` 是同一份度量
        （`plan_table_bridge.autofitWidths` 已注明实测与 QML `implicitWidth` 一致）。

        封顶见 `_MAX_WIDTHS`；长名称列一旦量过封顶值就 break，不必为必然被裁的文本
        把上千行都量一遍。
        """
        body_font = QFont(theme.FONT_FAMILY)
        body_font.setPixelSize(theme.fs(12))
        body = QFontMetrics(body_font)
        header = QFontMetrics(_header_font())

        out: list[tuple] = []
        for title, _width, key in self._col_specs:
            if key == "i":
                out.append((title, _ICON_COL_WIDTH, key))
                continue
            cap = _MAX_WIDTHS.get(key, 0)
            min_width = header.horizontalAdvance(title) + _HEADER_TEXT_MARGIN
            widest = 0
            for row in rows:
                text = display_text(row, key)
                if not text:
                    continue
                widest = max(widest, body.horizontalAdvance(text))
                if cap and widest >= cap:
                    break
            width = max(min_width, widest + _BODY_TEXT_MARGIN)
            out.append((title, min(width, cap) if cap else width, key))
        self._col_specs = out

    # ── 表头排序 ─────────────────────────────────────────────

    @Slot(int)
    def sortByColumn(self, column: int) -> None:
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
        if 0 <= self._sort_column < len(self._col_specs):
            order = Qt.SortOrder.AscendingOrder if self._sort_ascending else Qt.SortOrder.DescendingOrder
            self._proxy.sort(self._sort_column, order)

    # ── 表格行操作 ───────────────────────────────────────────

    def _row_at(self, row: int) -> dict | None:
        if not 0 <= row < self._proxy.rowCount():
            return None
        data = self._proxy.data(self._proxy.index(row, 0), Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _mfg_key(self, type_id: int) -> str:
        return f"{type_id}|mfg|{self._mfg['hub']}|{self._mfg['char']}"

    @Slot(int, result=dict)
    def rowInfo(self, row: int) -> dict:
        empty = {"valid": False, "typeId": 0, "name": "", "blueprintName": "", "hasMfgDetail": False}
        data = self._row_at(row)
        if not data or not data.get("id"):
            return empty
        type_id = int(data["id"])
        return {
            "valid": True,
            "typeId": type_id,
            "name": data.get("z", "") or data.get("e", "") or str(type_id),
            "blueprintName": self._blueprint_name(type_id) or "",
            "hasMfgDetail": bool(self._cache.get(self._mfg_key(type_id))),
        }

    @staticmethod
    def _blueprint_name(type_id: int) -> str | None:
        """产物对应制造蓝图的**名称**（右键菜单「复制蓝图名称」用；无蓝图 → None）。"""
        name = get_container().blueprint_repo.get_manufacturing_blueprint_name(type_id)
        return str(name) if name else None

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
        value = display_text(data, self._col_specs[column][2])
        if not value.strip() or value == "—":
            return
        QGuiApplication.clipboard().setText(str(value))

    @Slot()
    def copySelection(self) -> None:
        """Ctrl+C：复制当前行（原 `_copy_selection`）。"""
        data = self._row_at(self._selected_row)
        if data is None:
            self._set_status("没有选中行")
            return
        QGuiApplication.clipboard().setText(_copy_row(self._col_specs, data))
        self._set_status("已复制 1 行")

    @Slot(int)
    def copyAll(self) -> None:
        """Ctrl+A：整表复制（原版是「全选 + 复制」；QML 表只有单行选中，
        直接复制整表是同一件事的超集）。"""
        rows = [self._row_at(i) for i in range(self._proxy.rowCount())]
        lines = [_copy_row(self._col_specs, r) for r in rows if r]
        if not lines:
            self._set_status("没有选中行")
            return
        QGuiApplication.clipboard().setText("\n".join(lines))
        self._set_status(f"已复制 {len(lines)} 行")

    @Slot(int)
    def copyRow(self, row: int) -> None:
        """右键「复制整行」：与 Ctrl+C（`copySelection`）同一份文本，右键也能拿到。"""
        data = self._row_at(row)
        if data is None:
            return
        QGuiApplication.clipboard().setText(_copy_row(self._col_specs, data))
        self._set_status("已复制 1 行")

    @Slot(int)
    def openMaterials(self, row: int) -> None:
        """双击物品行 → 制造材料明细（原 `_dbl` → `MatDlg`）。"""
        from ui_qml.bridge.all_items_bridge import MatQmlDialog

        data = self._row_at(row)
        if not data or not data.get("id"):
            return
        MatQmlDialog(int(data["id"]), self.host_widget()).show()

    @Slot(int)
    def showBreakdown(self, row: int) -> None:
        """制造核算明细弹窗（原 `_ctx` 里的 `QMessageBox.information`）。"""
        data = self._row_at(row)
        if not data or not data.get("id"):
            return
        cached = self._cache.get(self._mfg_key(int(data["id"])))
        if cached:
            FMessageDialog.information(self.host_widget(), "制造核算明细", breakdown_text(cached))

    @Slot(int)
    def showMarketAdvice(self, row: int) -> None:
        """右键「挂单建议」：弹只读建议框（本地行情，零 ESI 请求）。

        与同一座桥的 `openMaterials`（双击行的「制造材料」）**同一条宿主链路**：
        `host_widget()` 当 parent、`QmlDialog(modeless=True)` + `show()` —— 只读查看器
        没有返回值要给调用方，也不该把父窗锁住。**不是** `showBreakdown` 那种
        `FMessageDialog` 模态消息框（那是纯文本消息，装不下这一屏数字与依据）。

        用 `rowInfo` 而不是直接读行数据：它已经处理了「这一行还有没有效」，
        并且给出的就是菜单里显示的那个物品名。
        """
        info = self.rowInfo(row)
        if not info["valid"]:
            return
        from ui_qml.bridge.market_advice_bridge import MarketAdviceQmlDialog

        MarketAdviceQmlDialog(int(info["typeId"]), str(info["name"]), self.host_widget()).show()

    @Slot(int)
    def addToPlan(self, row: int) -> None:
        """「加入制造列表」（原 `_ctx._do_add_plan`）。"""
        info = self.rowInfo(row)
        if not info["valid"]:
            return
        type_id = int(info["typeId"])
        name = str(info["name"])
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

    @Slot(int)
    def copyName(self, row: int) -> None:
        """复制**物品名**（右键菜单第一项）。"""
        data = self._row_at(row)
        if not data or not data.get("id"):
            return
        name = str(data.get("z", "") or data.get("e", "") or data["id"])
        QGuiApplication.clipboard().setText(name)
        self._set_status(f"已复制名称: {name}")

    @Slot(int)
    def copyBlueprintName(self, row: int) -> None:
        """复制**制造蓝图名称**（右键菜单第二项；无蓝图时给出提示，不写空串进剪贴板）。"""
        data = self._row_at(row)
        if not data or not data.get("id"):
            return
        name = self._blueprint_name(int(data["id"]))
        if not name:
            self._set_status("该物品没有制造蓝图")
            return
        QGuiApplication.clipboard().setText(name)
        self._set_status(f"已复制蓝图名称: {name}")

    @Slot(int, str)
    def addResearch(self, row: int, kind: str) -> None:
        """「加入拷贝 / 发明 / 效率研究规划」—— 直接复用全物品窗口那份实现。

        该窗口只建了制造缓存、没有贸易模式，所以菜单里不放「贸易核算明细」。
        """
        info = self.rowInfo(row)
        if not info["valid"]:
            return
        from ui_qml.bridge.all_items_bridge import _add_research_plan

        _add_research_plan(self.host_widget(), int(info["typeId"]), str(info["name"]), kind)

    # ── 置顶 ─────────────────────────────────────────────────

    @Slot(bool)
    def setPinned(self, pinned: bool) -> None:
        """「置顶」复选框 —— 走全仓共享实现（`pin_utils`，Win32 SetWindowPos，不重建窗口）。"""
        self._pinned = bool(pinned)
        host = self.host_widget()
        if host is not None:
            apply_window_pin(host, self._pinned)
        self.stateChanged.emit()

    # ── 设置 ─────────────────────────────────────────────────

    def _settings_path(self) -> str:
        return os.path.join(data_dir(), "mfg_browser_settings.json")

    def _load_settings(self) -> None:
        """读上次的设置：评分参数（中心/人物/设施税）+ **筛选器**。

        筛选器也落盘（用户要求「不希望每次都去设置」）：类别 / 库存 / 日销量 /
        利润率下限。窗口下次打开时按落盘值还原；越界或已下线的选项退回默认（0 / 空）。
        """
        path = self._settings_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self._mfg.update(saved.get("mfg", {}))
            filters = saved.get("filters", {})
            if isinstance(filters, dict):
                cat = self._clamp_index(filters.get("category"), len(self._categories))
                if cat is not None:
                    self._cat_index = cat
                stock = self._clamp_index(filters.get("stock"), len(_STOCK_FILTERS))
                if stock is not None:
                    self._stock_index = stock
                sales = self._clamp_index(filters.get("sales"), len(_SALES_FILTERS))
                if sales is not None:
                    self._sales_index = sales
                margin = filters.get("min_margin")
                if isinstance(margin, str):
                    self._min_margin_text = margin
                    self._min_margin = self._parse_margin(margin)
        except Exception:
            # 原版这里是一段裸 `except: pass`；本仓禁止，改为记日志后按默认值继续
            log.exception("读取可制造物品设置失败 path=%s", path)

    @staticmethod
    def _clamp_index(value: Any, size: int) -> int | None:
        """落盘的下标 → 合法下标；不是整数或越界 → `None`（保持默认）。"""
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        return value if 0 <= value < size else None

    def _save_settings(self) -> None:
        """落盘：评分参数 + 当前筛选器（用户要求筛选项能保存）。"""
        path = self._settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "mfg": self._mfg,
            "filters": {
                "category": self._cat_index,
                "stock": self._stock_index,
                "sales": self._sales_index,
                "min_margin": self._min_margin_text,
            },
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            log.exception("保存可制造物品设置失败 path=%s", path)

    # ── 关窗收尾 ─────────────────────────────────────────────

    def stop(self) -> None:
        self._debounce.stop()
        self._tree_debounce.stop()
        for worker in (self._tw, self._iw, self._sw, self._wp):
            drop_worker(worker)

    def _set_status(self, text: str) -> None:
        self._status = str(text)
        self.stateChanged.emit()


class ManufacturableItemsQmlDialog(QmlDialog):
    """QML 版「可制造物品」。

    调用方把类名换成它即可 —— 构造签名逐字一致（parent 照吃但会被忽略：
    查看类 → **非模态独立窗**，调用方用 `show()`）。

    调用方要保活请用 `dialog_host.find_modeless(...)`，**不要自己缓存实例** ——
    独立窗关掉即销毁（`WA_DeleteOnClose`），缓存的 Python 包装器会失效。
    """

    def __init__(self, parent: Any = None) -> None:
        bridge = ManufacturableItemsBridge()
        # 工具栏是**一行**（用户要求把筛选与设置并到一行），所以默认开宽一点；
        # 列宽本身仍按内容实测（末列不铺满），窗口再窄也不会把列拉宽。
        super().__init__(_QML_FILE, bridge, parent=parent, size=(1420, 640), modeless=True)
        self._mfg_bridge = bridge
        self.setMinimumSize(1000, 420)
        bridge.start()
