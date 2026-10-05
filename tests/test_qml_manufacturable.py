"""可制造物品浏览器（QML 版）的业务契约。

对照重构后的窗口：桥的属性、分类树防抖与「置灰」标记、筛选器（类别 / 库存挂单 /
日销量 / 利润率下限）、评分列（自己的列集合：删了均价·体积·日利润·收益，加了
日订单量·日成交量）、列宽实测、Ctrl+C / Ctrl+A 复制、右键菜单（复制名称与
复制蓝图名称，**没有**复制ID；外加「挂单建议」这条只读对话框入口）、内联评分设置
（中心 / 人物 / 设施税）、置顶走共享实现。

`qapp` fixture 是**必须**的：这些用例都要构造 QWidget（`QmlDialog` 是 QDialog），
漏了会挂死而不是报错（本仓踩过）。
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from tests.clipboard_wait import wait_for_clipboard, wait_for_copy
from ui_qml.bridge import manufacturable_items_bridge as mi
from ui_qml.workers.all_items_workers import JITA_RID

pytestmark = pytest.mark.ui

_ROWS = [
    {"id": 2001, "z": "渡鸦级", "e": "Raven", "bp": 100.0, "sp": 120.0, "ap": 110.0, "v": 10000.0},
    {"id": 34, "z": "三钛合金", "e": "Tritanium", "bp": 5.0, "sp": 6.0, "ap": 5.5, "v": 0.01},
]

_TREE = [
    {"id": 10, "p": None, "n": "舰船"},
    {"id": 11, "p": 10, "n": "护卫舰"},
    {"id": 20, "p": None, "n": "矿物"},
]

#: 「产物 → 分类」映射：2001 挂在 10 下、34 挂在 11 下、分类 20 下一个都没有
_GROUPS = {2001: 10, 34: 11}

#: 库存/挂单标记：2001 库中有、34 有挂单
_STOCK_FLAGS = {2001: (True, False), 34: (False, True)}

#: 蓝图/计划状态标记：2001 有原图待拷贝、34 我们没有蓝图（其余两项样例里不命中）
_STATE_FLAGS = {
    2001: frozenset({mi.STATE_BPO}),
    34: frozenset({mi.STATE_NO_BLUEPRINT}),
}

#: 近 7 日聚合的替身：2001 卖得动（50/天）、34 卖不动（3/天）
_HISTORY = {2001: {"oc": 2.0, "vol": 50.0, "days": 7, "last": "2026-01-07"}}
_HISTORY_DEFAULT = {"oc": 1.0, "vol": 3.0, "days": 7, "last": "2026-01-07"}


# ════════════════════════════════════════════════════════════
#  替身
# ════════════════════════════════════════════════════════════


class _FakeWorker(QObject):
    """`ItemsW` / `SearchItemsW` / `ScoreW` 的同步替身。"""

    done = Signal(list)
    progress = Signal(int, int)

    def __init__(self, *args, **kwargs):
        parent = kwargs.pop("parent", None)
        if args and isinstance(args[-1], QObject):
            parent = args[-1]
            args = args[:-1]
        super().__init__(parent)
        self.parent_obj = parent
        self.args = list(args)
        self.kwargs = dict(kwargs)
        self.started = False
        self.interrupted = False
        self.waited: list[int] = []

    def isRunning(self) -> bool:
        return False

    def requestInterruption(self) -> None:
        self.interrupted = True

    def wait(self, ms: int = 0) -> bool:
        self.waited.append(ms)
        return True

    def start(self) -> None:
        self.started = True


class _FakeTreeWorker(_FakeWorker):
    """`MfgTreeW` 的替身 —— 它的 `done` 是 `(items, {产物: 分类})` **两参**信号。"""

    done = Signal(list, object)  # type: ignore[assignment]  # 与基类的单参 `done` 语义不同


class _SlowWorker(_FakeWorker):
    def isRunning(self) -> bool:
        return True


class _Repo:
    """`blueprint_repo` 替身：五个类别 id 集合 + 蓝图名。"""

    def get_all_product_ids(self, activity: str) -> list[int]:
        if activity == "manufacturing":
            return [2001, 34]
        return [3001]

    def get_t1_manufacturable_product_ids(self) -> list[int]:
        return [2001]

    def get_t2_manufacturable_product_ids(self) -> list[int]:
        return [3002]

    def get_faction_manufacturable_product_ids(self) -> list[int]:
        return [3003]

    def get_manufacturing_blueprint_name(self, product_type_id: int) -> str | None:
        return {2001: "渡鸦级蓝图"}.get(int(product_type_id))


class _MarketRepo:
    def __init__(self, has_prices: bool = True) -> None:
        self.has_prices = has_prices

    def has_any_prices(self) -> bool:
        return self.has_prices


class _Container:
    blueprint_repo = _Repo()
    market_repo = _MarketRepo()
    #: 桥会把容器里的数据库句柄交给 `get_stock_and_order_flags` / `get_history_summary`
    db = None


class _ContainerWithPrices(_Container):
    def __init__(self, has_prices: bool) -> None:
        self.market_repo = _MarketRepo(has_prices)


class _Resolver:
    """`char_config_resolver` 替身（人物下拉要可预期）。"""

    @staticmethod
    def get_character_list() -> list[str]:
        return ["main", "alt"]

    @staticmethod
    def get_character(name: str):
        return {"name": name}


class _RecordingDialog:
    calls: list[dict] = []
    accept = False

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        _RecordingDialog.calls.append({"args": args, "kwargs": kwargs})

    def exec(self) -> int:
        return 1 if _RecordingDialog.accept else 0

    def show(self) -> None:
        pass

    def result_data(self) -> dict:
        return {}

    def get(self) -> dict:
        return {}


class _MsgBox:
    """`FMessageDialog` 替身：只记下调用（用例不该弹模态窗）。"""

    texts: list[str] = []

    @staticmethod
    def information(_parent, _title, text) -> None:
        _MsgBox.texts.append(str(text))

    @staticmethod
    def warning(_parent, _title, text) -> None:
        _MsgBox.texts.append(str(text))


@pytest.fixture(autouse=True)
def stub_env(monkeypatch, tmp_path):
    monkeypatch.setattr(mi, "MfgTreeW", _FakeTreeWorker)
    monkeypatch.setattr(mi, "ItemsW", _FakeWorker)
    monkeypatch.setattr(mi, "SearchItemsW", _FakeWorker)
    monkeypatch.setattr(mi, "ScoreW", _FakeWorker)
    monkeypatch.setattr(mi, "get_container", lambda: _Container())
    monkeypatch.setattr(mi, "char_config_resolver", _Resolver)
    monkeypatch.setattr(mi, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(mi, "FMessageDialog", _MsgBox)
    monkeypatch.setattr(mi, "get_stock_and_order_flags", lambda ids, db=None: dict(_STOCK_FLAGS))
    monkeypatch.setattr(
        mi,
        "get_production_state_flags",
        lambda ids, db=None: {int(i): _STATE_FLAGS[int(i)] for i in ids if int(i) in _STATE_FLAGS},
    )
    monkeypatch.setattr(mi, "get_history_summary", _fake_history)
    _RecordingDialog.calls = []
    _RecordingDialog.accept = False
    _MsgBox.texts = []
    yield


def _fake_history(ids, region_id=0, days=7, _db=None) -> dict:
    return {int(i): dict(_HISTORY.get(int(i), _HISTORY_DEFAULT)) for i in ids}


def _dialog() -> mi.ManufacturableItemsQmlDialog:
    return mi.ManufacturableItemsQmlDialog()


def _rows(dlg: mi.ManufacturableItemsQmlDialog) -> list[dict]:
    return list(dlg.bridge._model._rows)  # type: ignore[attr-defined]


def _ids(dlg: mi.ManufacturableItemsQmlDialog) -> list[int]:
    return [r["id"] for r in _rows(dlg)]


def _titles(dlg: mi.ManufacturableItemsQmlDialog) -> list[str]:
    return [c["title"] for c in dlg.bridge.columns]  # type: ignore[attr-defined]


def _widths(dlg: mi.ManufacturableItemsQmlDialog) -> dict[str, int]:
    return {c["title"]: c["width"] for c in dlg.bridge.columns}  # type: ignore[attr-defined]


def _full_titles(hub: str) -> list[str]:
    """`_upd` 之后那一整套列（本窗口自己的基础列 + 制造列，买卖价两列带区域名）。"""
    base = [c[0] for c in mi._MFG_BCOLS]
    return base[:3] + [f"买价（{hub}）", f"卖价（{hub}）"] + base[5:] + [c[0] for c in mi._MFG_MCOLS]


# ════════════════════════════════════════════════════════════
#  初始态
# ════════════════════════════════════════════════════════════


def test_defaults(qapp):
    dlg = _dialog()
    try:
        assert dlg.ok(), "QML 没加载起来"
        assert dlg.windowTitle() == "可制造物品"

        bridge = dlg.bridge
        assert bridge.statusText == "请选择分类或搜索物品"
        assert len(bridge.categories) == 5
        # 还没加载过数据 → 列还是自己的基础列（`_upd` 之后才换成整套）
        assert [c["title"] for c in bridge.columns] == [c[0] for c in mi._MFG_BCOLS]
        assert bridge.rowCount == 0
        assert bridge.progressVisible is False
        assert bridge.pinned is False
        assert bridge.treeRows == []
        assert bridge.emptyText == "没有数据"
        # 内联设置：默认值来自 `mfg_browser_settings.json` 缺失时的兜底
        assert bridge.hubs == list(mi.TRADE_HUBS)
        assert bridge.characters == ["main", "alt"]
        assert (bridge.hubIndex, bridge.charIndex, bridge.tax) == (0, 0, 0.0)
        # 筛选器默认全部不筛（库存那一栏里同时挂着蓝图/计划状态，用户要求并进同一个下拉）
        assert bridge.stockFilters == [
            "全部",
            "库中有",
            "有挂单",
            "库中有且有挂单",
            "无蓝图",
            "有原图待拷贝",
            "有拷贝待发明",
            "正在制造",
        ]
        assert bridge.stockFilterIndex == 0
        assert bridge.salesFilters == ["全部", "≥1", "≥10", "≥100", "≥1000"]
        assert bridge.salesFilterIndex == 0
        assert bridge.minMarginText == ""
    finally:
        dlg.deleteLater()


def test_start_kicks_off_the_tree_worker(qapp):
    dlg = _dialog()
    try:
        assert dlg.bridge._tw.started is True  # type: ignore[attr-defined]
        assert dlg.bridge._tw.parent_obj is dlg.bridge  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_settings_file_is_read_when_present(qapp, tmp_path):
    (tmp_path / "mfg_browser_settings.json").write_text(
        '{"mfg": {"hub": "Amarr", "char": "alt", "tax": 7.5}}', encoding="utf-8"
    )
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        assert bridge._mfg["hub"] == "Amarr"  # type: ignore[attr-defined]
        assert bridge._mfg["char"] == "alt"  # type: ignore[attr-defined]
        assert (bridge.hubIndex, bridge.charIndex) == (1, 1)
        assert bridge.tax == 7.5
    finally:
        dlg.deleteLater()


def test_broken_settings_file_falls_back_to_defaults(qapp, tmp_path):
    """坏 JSON 不该把窗口带崩（原版是一段裸 `except: pass`）。"""
    (tmp_path / "mfg_browser_settings.json").write_text("{ 不是 JSON", encoding="utf-8")
    dlg = _dialog()
    try:
        assert dlg.bridge._mfg["hub"] == "Jita"  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_settings_file_with_unknown_values_falls_back_to_first_entry(qapp, tmp_path):
    """配置里的区域/人物被改名 → 退回首项（非可编辑下拉框的行为）。"""
    (tmp_path / "mfg_browser_settings.json").write_text(
        '{"mfg": {"hub": "不存在的星域", "char": "查无此人"}}', encoding="utf-8"
    )
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        assert (bridge.hubIndex, bridge.charIndex) == (0, 0)
        assert bridge._mfg["hub"] == "Jita"  # type: ignore[attr-defined]
        assert bridge._mfg["char"] == "main"  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  分类树（防抖 + 置灰）
# ════════════════════════════════════════════════════════════


def test_select_tree_node_is_debounced(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_tree_data(_TREE, _GROUPS)  # type: ignore[attr-defined]
        assert [r["id"] for r in bridge.treeRows] == [10, 20], "默认全折叠"

        bridge.selectTreeNode(0)
        assert bridge._iw is None, "防抖没到点之前不加载"  # type: ignore[attr-defined]

        bridge._on_tree_delayed()  # type: ignore[attr-defined]
        worker = bridge._iw  # type: ignore[attr-defined]
        assert worker.args == [[10, 11]], "要加载整棵子树（含子分类）"
        assert bridge.selectedTreeId == 10
        assert worker.started is True
    finally:
        dlg.deleteLater()


def test_toggle_tree_node_is_immediate(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_tree_data(_TREE, _GROUPS)  # type: ignore[attr-defined]
        bridge.toggleTreeNode(0)
        assert [r["id"] for r in bridge.treeRows] == [10, 11, 20]
        assert bridge._pending_tree_index == -1, "展开箭头不该顺手触发加载"  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_reload_disconnects_the_previous_item_worker(qapp):
    """换 ItemsW 前必须断开旧的 `done`：否则先发出的结果会覆盖后一次的数据。"""
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._reload_items([10])  # type: ignore[attr-defined]
        first = bridge._iw  # type: ignore[attr-defined]

        bridge._reload_items([7])  # type: ignore[attr-defined]
        assert bridge._iw is not first  # type: ignore[attr-defined]

        first.done.emit([{"id": 999, "z": "陈旧"}])
        assert bridge._data == [], "旧 worker 的结果不该再进来"  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_reload_asks_only_for_manufacturable_items(qapp):
    """取数必须带 `manufacturable_only=True`：不下推这个条件会被 LIMIT 2000 先截断
    （实测「舰船装备」真实 1265 个可制造物品只出 792 个）。"""
    dlg = _dialog()
    try:
        dlg.bridge._reload_items([10])  # type: ignore[attr-defined]
        assert dlg.bridge._iw.kwargs.get("manufacturable_only") is True  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize(
    ("category_index", "grey_ids"),
    [
        (0, [20]),  # 所有可制造：2001 在 10 下、34 在 11 下，只有 20 是空的
        (1, [11, 20]),  # T1 只有 2001 → 11（挂 34）也变空
        (2, [10, 11, 20]),  # T2 只有 3002，树里没有
    ],
)
def test_tree_rows_are_greyed_when_the_category_has_nothing(qapp, category_index, grey_ids):
    """置灰 = 该节点子树里没有**当前类别**的物品（结构不删，点了给提示）。"""
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_tree_data(_TREE, _GROUPS)  # type: ignore[attr-defined]
        # 展开根节点：否则子节点（11）在折叠态下根本不在 treeRows 里，断言会漏掉它
        bridge.toggleTreeNode(0)
        assert [r["id"] for r in bridge.treeRows] == [10, 11, 20]

        bridge.setCategoryIndex(category_index)
        grey = [r["id"] for r in bridge.treeRows if r["empty"]]
        assert grey == grey_ids

        bridge.setCategoryIndex(0)  # 切回来也要恢复（置灰是随类别算的，不是一次性打标）
        assert [r["id"] for r in bridge.treeRows if r["empty"]] == [20]
    finally:
        dlg.deleteLater()


def test_empty_node_explains_itself_instead_of_showing_nothing(qapp):
    """点中「当前类别下没东西」的节点：空态要说清原因，不能只说「没有数据」。"""
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_tree_data(_TREE, _GROUPS)  # type: ignore[attr-defined]
        bridge.selectTreeNode(1)  # 矿物（20）
        bridge._on_tree_delayed()  # type: ignore[attr-defined]
        assert bridge.selectedTreeId == 20
        bridge._on_items([])  # type: ignore[attr-defined]

        assert bridge.rowCount == 0
        assert "矿物" in bridge.emptyText
        assert "没有可制造物品" in bridge.emptyText
        assert bridge.statusText == "「矿物」在当前类别下没有可制造物品"
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  筛选与列
# ════════════════════════════════════════════════════════════


def test_items_land_in_the_table_then_score(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]

        assert _ids(dlg) == [2001, 34], "先落表再异步算分"
        assert bridge.statusText == "计算评分中...", "`_upd` 那句「共 N 条 |」随即被 `_calc` 覆盖（与原版一致）"
        scorer = bridge._wp  # type: ignore[attr-defined]
        assert scorer.args[1] is True, "这个窗口恒为制造评分"
        assert scorer.args[2] == bridge._mfg  # type: ignore[attr-defined]

        bridge._on_scored([{"id": 2001, "z": "渡鸦级", "mm": 3.0}])  # type: ignore[attr-defined]
        assert bridge.progressVisible is False
        assert bridge.statusText == "共 1 条 | 评分已计算"
    finally:
        dlg.deleteLater()


def test_column_set_is_the_windows_own(qapp):
    """本窗口的列：删了均价·体积·日利润·收益·收入，加了日订单量·日成交量·利润/件。"""
    dlg = _dialog()
    try:
        dlg.bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        titles = _titles(dlg)
        assert titles == _full_titles("Jita")
        for gone in ("均价", "体积", "日利润", "收益", "收入"):
            assert gone not in titles
        assert "利润/件" in titles, "这一列是卖价−成本，不再是把卖价抄一份"
        # 历史只按 Jita 聚合 → 两列标题必须写明区域（中心可以切到 Amarr）
        assert "日订单量(Jita)" in titles
        assert "日成交量(Jita)" in titles
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize(
    ("cost", "revenue", "expected"),
    [(100.0, 150.0, 50.0), (100.0, 40.0, -60.0), (None, 150.0, None)],
)
def test_profit_per_unit_is_revenue_minus_cost(qapp, cost, revenue, expected):
    """「利润/件」= 卖价 − 成本；任一侧取不到就给 None（列里显示 `—`，不是 0）。"""
    dlg = _dialog()
    try:
        row: dict = {"id": 2001, "z": "渡鸦级"}
        if cost is not None:
            row["mc"] = cost
        if revenue is not None:
            row["mr"] = revenue
        dlg.bridge._on_scored([row])  # type: ignore[attr-defined]
        assert dlg.bridge._view[0]["mr"] == expected  # type: ignore[attr-defined]
        assert dlg.bridge._view[0]["mr"] != 150.0 or revenue != 150.0, "别再把卖价原样抄过来"
    finally:
        dlg.deleteLater()


def test_filters_are_remembered(qapp):
    """筛选项落盘：下次打开窗口还是上次的选择（用户要求不要每次重设）。"""
    first = mi.ManufacturableItemsBridge()
    first.setCategoryIndex(2)
    first.setStockFilterIndex(1)
    first.setSalesFilterIndex(2)
    first.setMinMarginText("15")

    second = mi.ManufacturableItemsBridge()
    assert second.categoryIndex == 2
    assert second.stockFilterIndex == 1
    assert second.salesFilterIndex == 2
    assert second.minMarginText == "15"
    assert second._min_margin == 15.0  # type: ignore[attr-defined]  # 阈值也要还原（不只是输入框文本）


def test_hub_change_relabels_the_price_columns(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge.setHubIndex(1)  # Amarr
        assert "买价（Amarr）" in _titles(dlg)
        assert bridge._mfg["hub"] == "Amarr"  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_category_filter_uses_blueprint_repo(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS + [{"id": 3002, "z": "T2产物"}])  # type: ignore[attr-defined]

        bridge.setCategoryIndex(1)  # 蓝图制造 T1
        assert _ids(dlg) == [2001]

        bridge.setCategoryIndex(2)  # 发明制造 T2
        assert _ids(dlg) == [3002]

        bridge.setCategoryIndex(4)  # 反应
        assert _ids(dlg) == [], "反应产物不在样例数据里"

        bridge.setCategoryIndex(0)  # 全部可制造 —— 这一档也是**过滤**，不是不过滤
        assert _ids(dlg) == [2001, 34]
        assert bridge.statusText == "计算评分中..."
    finally:
        dlg.deleteLater()


def test_category_id_sets_are_cached_per_window(qapp, monkeypatch):
    """五个类别 id 集合只算一次（其中势力那条是跨库 LIKE 扫描，每次都算太亏）。"""
    calls: list[str] = []

    class _CountingRepo(_Repo):
        def get_faction_manufacturable_product_ids(self) -> list[int]:
            calls.append("faction")
            return super().get_faction_manufacturable_product_ids()

        def get_t1_manufacturable_product_ids(self) -> list[int]:
            calls.append("t1")
            return super().get_t1_manufacturable_product_ids()

    class _CountingContainer(_Container):
        blueprint_repo = _CountingRepo()

    monkeypatch.setattr(mi, "get_container", lambda: _CountingContainer())

    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge.setCategoryIndex(1)  # type: ignore[attr-defined]
        bridge.setCategoryIndex(2)  # type: ignore[attr-defined]
        bridge.setCategoryIndex(0)  # type: ignore[attr-defined]
        assert calls.count("t1") == 1
        assert calls.count("faction") == 1, "切类别不该重算类别 id 集合"
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (0, [2001, 34]),  # 全部
        (1, [2001]),  # 库中有
        (2, [34]),  # 有挂单
        (3, []),  # 库中有且有挂单
        (4, [34]),  # 无蓝图 —— 见 `_STATE_FLAGS`
        (5, [2001]),  # 有原图待拷贝
        (6, []),  # 有拷贝待发明
        (7, []),  # 正在制造
    ],
)
def test_stock_filter_uses_the_batch_flags(qapp, index, expected):
    """同一个下拉里既有库存/挂单，也有蓝图与计划状态（用户要求并进一栏）。"""
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge.setStockFilterIndex(index)
        assert _ids(dlg) == expected
        assert bridge.stockFilterIndex == index
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (0, [2001, 34]),  # 不筛
        (1, [2001, 34]),  # ≥1：两条都有成交量
        (2, [2001]),  # ≥10：只有 2001（50/天）
        (3, []),  # ≥100
    ],
)
def test_sales_filter_reads_the_daily_volume_column(qapp, index, expected):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge._on_scored([{**r} for r in _ROWS])  # type: ignore[attr-defined]
        bridge.setSalesFilterIndex(index)
        assert _ids(dlg) == expected
    finally:
        dlg.deleteLater()


def test_sales_filter_hides_rows_without_history(qapp, monkeypatch):
    """「不知道卖不卖得动」不算通过——查不到历史时筛选必须把它滤掉（`None` ≠ 0）。"""
    monkeypatch.setattr(mi, "get_history_summary", lambda ids, region_id=0, days=7, _db=None: {})
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge._on_scored([{**r} for r in _ROWS])  # type: ignore[attr-defined]
        assert _ids(dlg) == [2001, 34]
        assert "市场历史为空" in bridge.statusText

        bridge.setSalesFilterIndex(1)  # ≥1
        assert _ids(dlg) == []
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize("text", ["", "   ", "abc", "%"])
def test_margin_filter_is_off_for_blank_or_invalid_input(qapp, text):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge._on_scored([{**r} for r in _ROWS])  # type: ignore[attr-defined]
        bridge.setMinMarginText(text)
        assert _ids(dlg) == [2001, 34], "空/非法输入 = 不筛（**不能**拿 0 当默认）"
    finally:
        dlg.deleteLater()


def test_margin_filter_drops_rows_below_the_threshold(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge._on_scored([{"id": 2001, "z": "赚", "mm": 12.0}, {"id": 34, "z": "亏", "mm": -3.0}])  # type: ignore[attr-defined]

        bridge.setMinMarginText("5")
        assert _ids(dlg) == [2001]
        assert "筛选后 1 条" in bridge.statusText

        bridge.setMinMarginText("-10")  # 阈值可为负（把亏损但不至于 -10% 的留下）
        assert _ids(dlg) == [2001, 34]
    finally:
        dlg.deleteLater()


def test_empty_filter_says_no_data(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items([])  # type: ignore[attr-defined]
        assert bridge.statusText == "无数据"
        assert bridge.progressVisible is False
    finally:
        dlg.deleteLater()


def test_column_widths_follow_content_and_are_capped(qapp, monkeypatch):
    """列宽按内容实测（覆盖在游戏上的浮窗，越窄越好）：短内容更窄、长内容封顶。

    **离屏平台一个字体都没有**（`QFontDatabase` 为空，`QFontMetrics` 全量出 0），
    所以这里把 `QFontMetrics` 换成确定性的替身 —— 测的是「按内容撑开 + 封顶 + 表头下限」
    这套自己的逻辑，而不是 Qt 的字体度量本身（那是框架行为）。
    """

    class _Metrics:
        def __init__(self, _font) -> None:
            pass

        @staticmethod
        def horizontalAdvance(text: str) -> int:
            return len(str(text)) * 7

    monkeypatch.setattr(mi, "QFontMetrics", _Metrics)

    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items([{"id": 2001, "z": "渡鸦级", "e": "Raven", "bp": 1.0, "sp": 2.0}])  # type: ignore[attr-defined]
        narrow = _widths(dlg)

        bridge._on_items(  # type: ignore[attr-defined]
            [{"id": 2001, "z": "很长的中文名" * 20, "e": "Very Long English Name " * 5, "bp": 1.0, "sp": 2.0}]
        )
        wide = _widths(dlg)

        assert narrow["图标"] == wide["图标"] == 36, "图标列固定宽"
        assert narrow["中文名"] < wide["中文名"], "名字长了列就该变宽"
        assert wide["中文名"] == mi._MAX_WIDTHS["z"], "长名字封顶，不能把窗口撑爆"
        assert wide["English"] == mi._MAX_WIDTHS["e"]
        # 表头下限：窄内容也不能窄到装不下表头（"中文名" 3 字 × 7 + 24）
        assert narrow["中文名"] >= 3 * 7 + 24
        assert all(isinstance(w, int) and w > 0 for w in wide.values())
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  刷新计算
# ════════════════════════════════════════════════════════════


def test_refresh_without_data_does_nothing(qapp):
    dlg = _dialog()
    try:
        dlg.bridge.refreshScores()
        assert dlg.bridge.statusText == "请选择分类或搜索物品"
    finally:
        dlg.deleteLater()


def test_refresh_without_prices_keeps_the_status(qapp, monkeypatch):
    monkeypatch.setattr(mi, "get_container", lambda: _ContainerWithPrices(False))
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge.refreshScores()
        assert bridge.statusText == "暂无价格数据，请先在主界面更新价格"
    finally:
        dlg.deleteLater()


def test_refresh_with_prices_recomputes(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge._on_scored([{**r} for r in _ROWS])  # type: ignore[attr-defined]
        assert bridge.statusText == "共 2 条 | 评分已计算"

        bridge.refreshScores()
        assert bridge.statusText == "计算评分中...", "刷新会立刻回到算分态"
        assert bridge.progressVisible is True
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  搜索 / 排序 / 行操作 / 右键菜单
# ════════════════════════════════════════════════════════════


def test_search_is_debounced_then_runs(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge.setSearchText("渡鸦")
        assert bridge._sw is None  # type: ignore[attr-defined]
        bridge._do_search()  # type: ignore[attr-defined]
        assert bridge.statusText == "搜索中..."
        assert bridge._sw.args == ["渡鸦", JITA_RID]  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_sort_toggles_direction_on_the_same_column(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge.sortByColumn(1)
        assert (bridge.sortColumn, bridge.sortAscending) == (1, True)
        bridge.sortByColumn(1)
        assert (bridge.sortColumn, bridge.sortAscending) == (1, False)
        bridge.sortByColumn(0)
        assert (bridge.sortColumn, bridge.sortAscending) == (0, True)
    finally:
        dlg.deleteLater()


def test_click_cell_selects_and_copies(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]

        bridge.clickCell(0, 1)  # 中文名列
        assert bridge.selectedRow == 0
        assert wait_for_copy(lambda: bridge.clickCell(0, 1), "渡鸦级") == "渡鸦级"

        QGuiApplication.clipboard().setText("未改动")
        bridge.clickCell(0, 0)  # 图标列没有值
        assert wait_for_clipboard("未改动") == "未改动"
    finally:
        dlg.deleteLater()


def test_copy_selection_and_copy_all(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]

        bridge.copySelection()
        assert bridge.statusText == "没有选中行", "还没点过任何行"

        bridge.clickCell(0, 1)
        line = wait_for_copy(bridge.copySelection, "2001\t渡鸦级\tRaven\t")
        assert line.startswith("2001\t渡鸦级\tRaven\t"), "图标列换成 type_id"

        # 等**末行**出现，才说明两行都写全了（只等首行可能在第二行落地前就读走）
        text = wait_for_copy(bridge.copyAll, "2001\t渡鸦级\tRaven\t\n34\t三钛合金\t")
        lines = text.splitlines()
        assert len(lines) == 2
        assert lines[1].startswith("34\t三钛合金\t")
        assert bridge.statusText == "已复制 2 行"

        # 右键「复制整行」：与 Ctrl+C 同一份文本（图标列写 type_id，其余走显示格式）
        QGuiApplication.clipboard().setText("未改动")
        line = wait_for_copy(lambda: bridge.copyRow(1), "34\t三钛合金\tTritanium\t")
        assert line.startswith("34\t三钛合金\tTritanium\t")
        assert bridge.statusText == "已复制 1 行"
    finally:
        dlg.deleteLater()


def test_copy_name_and_blueprint_name(qapp):
    """右键菜单的两个复制项：物品名 / 制造蓝图名（**没有**「复制ID」了）。"""
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]

        info = bridge.rowInfo(0)
        assert info["name"] == "渡鸦级"
        assert info["blueprintName"] == "渡鸦级蓝图"

        assert wait_for_copy(lambda: bridge.copyName(0), "渡鸦级") == "渡鸦级"
        assert bridge.statusText == "已复制名称: 渡鸦级"

        assert wait_for_copy(lambda: bridge.copyBlueprintName(0), "渡鸦级蓝图") == "渡鸦级蓝图"
        assert bridge.statusText == "已复制蓝图名称: 渡鸦级蓝图"
    finally:
        dlg.deleteLater()


def test_copy_blueprint_name_without_a_blueprint_hints(qapp):
    """没有制造蓝图的行：给提示，**不**把空串写进剪贴板。"""
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        QGuiApplication.clipboard().setText("未改动")

        bridge.copyBlueprintName(1)  # 34 没有蓝图名
        assert bridge.statusText == "该物品没有制造蓝图"
        assert wait_for_clipboard("未改动") == "未改动"
    finally:
        dlg.deleteLater()


def test_open_materials_uses_the_qml_material_dialog(qapp, monkeypatch):
    from ui_qml.bridge import all_items_bridge

    monkeypatch.setattr(all_items_bridge, "MatQmlDialog", _RecordingDialog)
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge.openMaterials(0)
        assert _RecordingDialog.calls[0]["args"][0] == 2001

        bridge.openMaterials(9)  # 越界：不弹
        assert len(_RecordingDialog.calls) == 1
    finally:
        dlg.deleteLater()


class _AdviceStub:
    """`services.market_advice_service` 的替身：换 `payload` 就换一档判定。"""

    JITA_RID = 10000002

    #: 两侧挂单：数字都是真值
    two_sided = {
        "typeId": 2001,
        "name": "渡鸦级",
        "spreadPct": 12.3456,
        "roundTripFeePct": 3.6,
        "dayVolume": 1234.5,
        "orderVolume": 2705.0,
        "turnDays": 2.19,
        "verdict": "two_sided",
        "buyAdvice": "挂买单：买价 × 1.01 = 100.00 ISK",
        "sellAdvice": "挂卖单：卖价 × 0.99 = 120.00 ISK",
        "reasons": ["价差 12.35% > 来回费用的 2 倍", "近 7 个日历天日均成交 1,234.50 件"],
        "caliber": "买卖价=挂单价；成交量=成交历史（近 7 个日历天）",
    }

    #: 没有报价：价差 / 日均成交 / 卖单队列都是 `None`（**不是** 0）
    no_data = {
        "typeId": 2001,
        "name": "渡鸦级",
        "spreadPct": None,
        "roundTripFeePct": 3.6,
        "dayVolume": None,
        "orderVolume": None,
        "turnDays": None,
        "verdict": "no_data",
        "buyAdvice": "先跑一次「更新价格」（本页数据来自本地缓存）",
        "sellAdvice": "先跑一次「更新价格」（本页数据来自本地缓存）",
        "reasons": ["取不到买价和卖价：本地 market_prices 里没有该物品挂单行"],
        "caliber": "买卖价=挂单价；成交量=成交历史（近 7 个日历天）",
    }

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self.payload: dict = dict(self.two_sided)

    def get_trade_advice(self, type_id: int, region_id: int = JITA_RID, **_kwargs: object) -> dict:
        self.calls.append((int(type_id), int(region_id)))
        return dict(self.payload)


def test_market_advice_entry_shows_the_assembled_panel(qapp, monkeypatch):
    """右键「挂单建议」：入口按行的 type_id/名开窗，面板字段按服务返回值装配。

    覆盖两件事（同一层：挂单建议的桥）：

    1. **入口**：`showMarketAdvice(row)` 用行的 type_id + 物品名构造只读对话框，
       走 `show()`（不是 `exec()`）——与同桥的「制造材料」同一条宿主链路；越界行不弹。
    2. **装配**：verdict 标题 / 买 / 卖建议 / 依据 / 关键数字都来自服务返回；
       `no_data` 那档的三个空数字必须是 `—` —— 本仓口径里 0 是**真值**，不能冒充没数据。
    """
    from ui_qml.bridge import market_advice_bridge as mab

    stub = _AdviceStub()
    monkeypatch.setattr(mab, "MarketAdviceQmlDialog", _RecordingDialog)
    monkeypatch.setattr(mab, "_advice_service", lambda: stub)

    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]

        bridge.showMarketAdvice(0)
        assert _RecordingDialog.calls[-1]["args"][:2] == (2001, "渡鸦级")
        bridge.showMarketAdvice(9)  # 越界：不弹
        assert len(_RecordingDialog.calls) == 1

        panel = mab.MarketAdviceBridge(2001, "渡鸦级")
        assert stub.calls == [(2001, 10000002)], "区域取服务自己的 JITA_RID"
        assert panel.headerText == "渡鸦级 (Type ID: 2001)"
        assert (panel.verdict, panel.title, panel.token) == ("two_sided", "两侧挂单划算", "ACCENT_GREEN")
        assert panel.buyAdvice.startswith("挂买单") and panel.sellAdvice.startswith("挂卖单")
        assert panel.reasons[0].startswith("价差")
        assert [row["value"] for row in panel.metrics] == ["12.35%", "3.60%", "1,234.50", "2,705 件 ≈ 2.2 天"]

        stub.payload = dict(_AdviceStub.no_data)
        empty = mab.MarketAdviceBridge(2001, "渡鸦级")
        values = [row["value"] for row in empty.metrics]
        assert (empty.verdict, empty.title) == ("no_data", "本地没有这只物品的挂单/成交数据")
        assert (values[0], values[2], values[3]) == ("—", "—", "—"), "缺值一律 —，不拿 0 冒充"
        assert values[1] == "3.60%", "算得出来的那一项照常给数字"
    finally:
        dlg.deleteLater()


def test_add_to_plan_wiring(qapp, monkeypatch):
    from ui_qml.bridge import industry_dialogs_bridge

    class _PlanDialog(_RecordingDialog):
        def result_data(self) -> dict:
            return {"fac": "空间站", "runs": 1}

    landed: list = []
    monkeypatch.setattr(industry_dialogs_bridge, "AddPlanDialogQmlDialog", _PlanDialog)
    monkeypatch.setattr(mi, "insert_plan_from_score", lambda *a: landed.append(a))

    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]

        _RecordingDialog.accept = False
        bridge.addToPlan(0)
        assert landed == []

        _RecordingDialog.accept = True
        bridge.addToPlan(0)
        assert len(landed) == 1
        type_id, name, _score, _data, cfg = landed[0]
        assert (type_id, name) == (2001, "渡鸦级")
        assert cfg == bridge._mfg  # type: ignore[attr-defined]
        assert _MsgBox.texts[-1] == "已加入制造列表: 渡鸦级"
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  内联设置（原「设置」二级对话框的三个字段）
# ════════════════════════════════════════════════════════════


def test_inline_char_change_saves_and_hints_a_recalc(qapp, tmp_path):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge._on_scored([{**r} for r in _ROWS])  # type: ignore[attr-defined]

        bridge.setCharIndex(1)  # alt
        assert bridge._mfg["char"] == "alt"  # type: ignore[attr-defined]
        assert bridge.charIndex == 1
        assert "刷新计算" in bridge.statusText, "换人物不自动重算，但要提示"
        saved = json.loads((tmp_path / "mfg_browser_settings.json").read_text(encoding="utf-8"))
        assert saved["mfg"]["char"] == "alt"

        bridge.setCharIndex(1)  # 同值：不重复落盘、不改状态
    finally:
        dlg.deleteLater()


def test_inline_tax_is_clamped_and_saved(qapp, tmp_path):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge.setTax(250.0)
        assert bridge.tax == 100.0
        bridge.setTax(-5.0)
        assert bridge.tax == 0.0
        bridge.setTax(12.5)
        assert bridge.tax == 12.5
        saved = json.loads((tmp_path / "mfg_browser_settings.json").read_text(encoding="utf-8"))
        assert saved["mfg"]["tax"] == 12.5
    finally:
        dlg.deleteLater()


def test_inline_hub_change_reloads_and_saves(qapp, tmp_path):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge._on_scored([{**r} for r in _ROWS])  # type: ignore[attr-defined]

        bridge.setHubIndex(0)  # 同值：不重算
        assert bridge.statusText == "共 2 条 | 评分已计算"

        bridge.setHubIndex(1)  # Amarr → 换列并重算
        assert "买价（Amarr）" in _titles(dlg)
        assert bridge.statusText == "计算评分中..."
        saved = json.loads((tmp_path / "mfg_browser_settings.json").read_text(encoding="utf-8"))
        assert saved["mfg"]["hub"] == "Amarr"
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  置顶
# ════════════════════════════════════════════════════════════


def test_pin_goes_through_the_shared_window_pin(qapp, monkeypatch):
    """置顶必须走 `pin_utils.apply_window_pin`（别再抄一份 setWindowFlags）。"""
    calls: list[bool] = []
    monkeypatch.setattr(mi, "apply_window_pin", lambda window, checked: calls.append(checked))

    dlg = _dialog()
    try:
        assert dlg.bridge.pinned is False
        dlg.bridge.setPinned(True)
        assert dlg.bridge.pinned is True
        dlg.bridge.setPinned(False)
        assert dlg.bridge.pinned is False
        assert calls == [True, False]
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  关闭收尾
# ════════════════════════════════════════════════════════════


def test_stop_finishes_every_running_worker(qapp, monkeypatch):
    monkeypatch.setattr(mi, "MfgTreeW", _SlowWorker)
    monkeypatch.setattr(mi, "ItemsW", _SlowWorker)
    monkeypatch.setattr(mi, "SearchItemsW", _SlowWorker)
    monkeypatch.setattr(mi, "ScoreW", _SlowWorker)

    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge._reload_items([10])  # type: ignore[attr-defined]
        bridge.setSearchText("渡鸦")
        bridge._do_search()  # type: ignore[attr-defined]

        workers = [bridge._tw, bridge._iw, bridge._wp, bridge._sw]  # type: ignore[attr-defined]
        dlg.done(0)
        for worker in workers:
            assert worker.interrupted is True
            assert worker.waited, "每个在跑的线程都要被 wait 收尾"
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  纯函数
# ════════════════════════════════════════════════════════════


def test_subtree_category_counts_rolls_up_to_every_ancestor():
    """树节点计数：直接把产物挂在分类上 → 自底向上滚到每个祖先。"""
    rows = [
        {"id": 1, "name": "根", "depth": 0, "parent": None},
        {"id": 2, "name": "子", "depth": 1, "parent": 1},
        {"id": 3, "name": "另一个根", "depth": 0, "parent": None},
    ]
    cats = {"all": {101, 102}, "t1": {101}}
    counts = mi.subtree_category_counts(rows, {101: 2, 102: 2, 999: 3}, cats)

    assert counts[2] == {"all": 2, "t1": 1}, "直接挂在这一层的产物"
    assert counts[1] == {"all": 2, "t1": 1}, "滚到父节点"
    assert counts[3] == {}, "999 不属于任何类别 → 不计"
    assert set(counts) == {1, 2, 3}, "每个节点都有计数桶（空桶也要在）"


def test_breakdown_text_status_uses_this_dialogs_own_wording():
    """这个窗口的状态码文案与全物品窗口不同（少了 `no_depth`，`no_materials` 写成 `no_mats`）。"""
    assert mi.breakdown_text({"status": "no_mats"}) == "状态: 蓝图无材料数据"
    assert mi.breakdown_text({"status": "no_depth"}) == "状态: no_depth", "没登记的状态码原样回显"
    assert mi.breakdown_text({"status": "no_price"}) == "状态: 查不到价格数据"


def test_breakdown_text_lines_and_optional_fees():
    text = mi.breakdown_text(
        {
            "score": 88.2,
            "profit_per_run": 1234.0,
            "margin_pct": 5.5,
            "isk_per_hour": 999.0,
            "breakdown": {"material_cost": 100.0, "run_cost": 1.0, "install_fee": 2.0},
        }
    )
    lines = text.splitlines()
    assert lines[0] == "评分: 88"
    assert lines[1] == "单批利润: 1,234 ISK"
    assert lines[3] == "每小时利润: 999 ISK"
    assert lines[4] == "材料成本: 100 ISK"
    assert lines[5] == "运行成本: 1 ISK"
    assert lines[6] == "安装费: 2 ISK"
    assert len(lines) == 7, "没有的费用项不占行"
