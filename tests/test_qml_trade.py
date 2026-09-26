"""贸易页的契约测试（重构后：A → B 全品类价差排行）。

分三层（与 `tests/test_qml_query.py` 同构）：
  - **纯函数层**（`fast`）：`TradeRankQmlModel` 的命名角色、展示与排序；
  - **桥层**（`ui`）：`TradeBridge` 的参数状态机与加购物车；
  - **页面层**（`ui`）：`TradePage.qml` 能加载、无 QML 告警。
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt

from tests.qml_page_load import assert_page_loads_quietly, page_host
from ui_qml.models.trade_rank_model import (
    COLUMNS,
    ROLE_NAMES,
    TradeRankQmlModel,
    format_order_change,
)

_BASE = Qt.ItemDataRole.UserRole
_TEXT = _BASE + 1
_FG = _BASE + 2
_ICON_URL = _BASE + 3
_ALIGN_RIGHT = _BASE + 4
_TYPE_ID = _BASE + 5
_IS_ACTION = _BASE + 6

_PM3_COL = 7
_CHG_COL = 8
_ACTION_COL = len(COLUMNS) - 1
_NAME_COL = 1


def _row(
    tid: int = 34,
    spread: float = 5.0,
    pm3: float | None = 500.0,
    chg: float | None = 12.0,
    va: int = 1000,
    vb: int = 1000,
):
    return {
        "id": tid,
        "z": "三钛合金",
        "e": "Tritanium",
        "v": 0.01,
        "pa": 4.0,
        "pb": 4.0 + spread,
        "spread": spread,
        "pm3": pm3,
        "chg": chg,
        "va": va,
        "vb": vb,
    }


def _cell(model: TradeRankQmlModel, row: int, col: int, role: int):
    return model.data(model.index(row, col), role)


# ════════════════════════════════════════════════════════════
#  模型
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_role_names_are_unique_and_contiguous():
    keys = sorted(ROLE_NAMES)
    assert keys[0] == Qt.ItemDataRole.UserRole + 1
    assert keys == list(range(keys[0], keys[0] + len(ROLE_NAMES)))
    assert len(set(ROLE_NAMES.values())) == len(ROLE_NAMES)


@pytest.mark.fast
def test_every_role_is_readable_on_every_cell():
    model = TradeRankQmlModel()
    model.set_rows([_row()])
    for col in range(model.columnCount()):
        for role in ROLE_NAMES:
            model.data(model.index(0, col), role)


@pytest.mark.fast
def test_column_headers_and_count_match_the_bridge():
    model = TradeRankQmlModel()
    model.set_rows([_row()])

    assert model.columnCount() == len(COLUMNS)
    titles = [model.headerData(c, Qt.Orientation.Horizontal) for c in range(model.columnCount())]
    assert "中文名称" in titles
    assert "每方利润" in titles
    assert "B侧挂单变化" in titles


@pytest.mark.fast
def test_text_matches_the_column_meaning():
    model = TradeRankQmlModel()
    model.set_rows([_row(tid=34, spread=5.0, pm3=500.0, chg=12.0)])

    assert _cell(model, 0, 1, _TEXT) == "三钛合金"
    assert _cell(model, 0, 2, _TEXT) == "Tritanium"
    assert _cell(model, 0, 3, _TEXT) == "4.00"
    assert _cell(model, 0, 4, _TEXT) == "9.00"
    assert _cell(model, 0, 5, _TEXT) == "5.00"
    assert _cell(model, 0, 6, _TEXT) == "0.01"
    assert _cell(model, 0, _PM3_COL, _TEXT) == "500.00"


@pytest.mark.fast
def test_missing_numbers_show_a_dash_instead_of_zero():
    """无值不能显示成 0 —— 那会被读成「真的等于零」。"""
    model = TradeRankQmlModel()
    model.set_rows([_row(pm3=None, chg=None) | {"v": 0}])

    assert _cell(model, 0, _PM3_COL, _TEXT) == "—"
    assert _cell(model, 0, _CHG_COL, _TEXT) == "—"
    assert _cell(model, 0, 6, _TEXT) == "—"


@pytest.mark.fast
def test_name_columns_are_left_aligned_the_rest_right():
    model = TradeRankQmlModel()
    model.set_rows([_row()])

    assert _cell(model, 0, _NAME_COL, _ALIGN_RIGHT) is False
    for col in (3, 5, _PM3_COL, _CHG_COL):
        assert _cell(model, 0, col, _ALIGN_RIGHT) is True


@pytest.mark.fast
def test_profit_and_change_are_coloured_by_sign():
    model = TradeRankQmlModel()
    model.set_rows([_row(pm3=10.0, chg=5.0), _row(pm3=-10.0, chg=-5.0)])

    assert _cell(model, 0, _PM3_COL, _FG)
    assert _cell(model, 1, _PM3_COL, _FG)
    assert _cell(model, 0, _PM3_COL, _FG) != _cell(model, 1, _PM3_COL, _FG)
    assert _cell(model, 0, _CHG_COL, _FG) != _cell(model, 1, _CHG_COL, _FG)
    # 价差列只是差值，不染色
    assert _cell(model, 0, 5, _FG) == ""


@pytest.mark.fast
def test_action_column_is_flagged_and_carries_no_text():
    model = TradeRankQmlModel()
    model.set_rows([_row()])

    assert _cell(model, 0, _ACTION_COL, _IS_ACTION) is True
    assert _cell(model, 0, _NAME_COL, _IS_ACTION) is False
    assert _cell(model, 0, _ACTION_COL, _TEXT) == ""


@pytest.mark.fast
def test_type_id_role_feeds_the_cart():
    model = TradeRankQmlModel()
    model.set_rows([_row(tid=4242)])

    assert _cell(model, 0, _NAME_COL, _TYPE_ID) == 4242


@pytest.mark.fast
def test_only_the_icon_column_carries_an_icon():
    model = TradeRankQmlModel()
    model.set_rows([_row()])

    assert _cell(model, 0, _NAME_COL, _ICON_URL) == ""


@pytest.mark.fast
def test_sort_uses_raw_numbers_not_formatted_text():
    """按「每方利润」排的是原始数值：'9,999' 必须排在 10000 前面（字符串排会反过来）。"""
    model = TradeRankQmlModel()
    model.set_rows(
        [
            _row(tid=1, pm3=9999.0),
            _row(tid=2, pm3=10000.0),
            _row(tid=3, pm3=None),
        ]
    )

    model.sort(_PM3_COL, Qt.SortOrder.DescendingOrder)
    assert [model.row_at(i)["id"] for i in range(3)] == [2, 1, 3]

    model.sort(_PM3_COL, Qt.SortOrder.AscendingOrder)
    assert [model.row_at(i)["id"] for i in range(3)] == [3, 1, 2]


@pytest.mark.fast
def test_none_sorts_last_regardless_of_direction():
    model = TradeRankQmlModel()
    model.set_rows([_row(tid=1, chg=None), _row(tid=2, chg=-3.0), _row(tid=3, chg=8.0)])

    model.sort(_CHG_COL, Qt.SortOrder.DescendingOrder)
    assert [model.row_at(i)["id"] for i in range(3)] == [3, 2, 1]


@pytest.mark.fast
def test_set_rows_reapplies_the_current_sort():
    model = TradeRankQmlModel()
    model.set_rows([_row(tid=1, pm3=1.0)])
    model.sort(_NAME_COL, Qt.SortOrder.AscendingOrder)

    model.set_rows([_row(tid=2, pm3=1.0), _row(tid=3, pm3=9.0)])

    assert model.rowCount() == 2
    assert model.sortColumn() == _NAME_COL


@pytest.mark.fast
def test_icon_and_action_columns_are_not_sortable():
    model = TradeRankQmlModel()
    model.set_rows([_row()])
    model.sort(_NAME_COL, Qt.SortOrder.AscendingOrder)

    model.sort(0, Qt.SortOrder.AscendingOrder)
    assert model.sortColumn() == _NAME_COL

    model.sort(_ACTION_COL, Qt.SortOrder.AscendingOrder)
    assert model.sortColumn() == _NAME_COL


@pytest.mark.fast
def test_empty_model_is_safe():
    model = TradeRankQmlModel()
    assert model.rowCount() == 0
    model.set_rows([])
    model.refresh_colors()  # 空表补发颜色不该炸


# ════════════════════════════════════════════════════════════
#  挂单变化的文案（纯函数）
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
@pytest.mark.parametrize(
    ("per_day", "expected"),
    [
        (None, "—"),
        (0.0, "0/天"),
        (450.0, "↓450/天"),  # 正数 = 挂单在减少 = 有人在吃单
        (-120.0, "↑120/天"),  # 负数 = 挂单在堆积
        (12345.6, "↓12,346/天"),
    ],
)
def test_format_order_change(per_day, expected):
    assert format_order_change(per_day) == expected


# ════════════════════════════════════════════════════════════
#  桥
# ════════════════════════════════════════════════════════════


class _FakeShell:
    """只提供购物车的最小外壳替身（桥不去碰外壳的其它部分）。"""

    def __init__(self, cart):
        self._cart = cart
        #: 「开始计算」不该碰它（只读本地价）—— 留给 `assert_not_called`
        self.request_price_update = Mock()

    def trade_cart(self):
        return self._cart


@pytest.fixture
def bridge(qapp, tmp_path, monkeypatch):
    from ui_qml.bridge.trade_bridge import TradeBridge
    from ui_qml.views import trade_cart_window as tcw

    monkeypatch.setattr(tcw, "trade_cart_file", lambda: str(tmp_path / "cart.json"))
    return TradeBridge(_FakeShell(tcw.TradeCartController()))


@pytest.mark.ui
def test_defaults_are_buy_at_a_sell_at_b(bridge):
    """从 Jita 的卖单买入、卖到 Amarr 的买单 —— 这才是「买入价 / 卖出价」。"""
    from core.constants import TRADE_HUB_IDS

    assert bridge.hubs == list(TRADE_HUB_IDS.keys())
    assert bridge.hubs[bridge.fromIndex] == "Jita"
    assert bridge.hubs[bridge.toIndex] == "Amarr"
    assert bridge.sideLabels[bridge.fromSideIndex] == "卖单"
    assert bridge.sideLabels[bridge.toSideIndex] == "买单"
    assert bridge.busy is False
    assert bridge.isEmpty is True
    assert "开始计算" in bridge.statusText


@pytest.mark.ui
def test_category_list_starts_with_all(bridge, monkeypatch):
    """分类下拉第一项永远是「全部品类」，其余是市场分类的顶层。"""
    import services.market_browser_service as mbs

    monkeypatch.setattr(
        mbs,
        "fetch_market_tree",
        lambda: [{"id": 4, "p": None, "n": "舰船"}, {"id": 100, "p": 4, "n": "护卫舰"}],
    )
    from ui_qml.bridge.trade_bridge import TradeBridge

    cats = TradeBridge(None).categories

    assert cats[0]["name"] == "全部品类"
    assert [c["name"] for c in cats[1:]] == ["舰船"]  # 子节点不进下拉


@pytest.mark.ui
def test_swap_direction_flips_hubs_and_sides(bridge):
    bridge.swapDirection()

    assert bridge.hubs[bridge.fromIndex] == "Amarr"
    assert bridge.hubs[bridge.toIndex] == "Jita"
    assert bridge.sideLabels[bridge.fromSideIndex] == "买单"
    assert bridge.sideLabels[bridge.toSideIndex] == "卖单"


@pytest.mark.ui
def test_changing_a_parameter_drops_the_stale_table(bridge):
    """参数改了就把旧方向的排行清掉 —— 留着旧数字会误导。"""
    bridge._rows = [_row()]
    bridge._model.set_rows(bridge._rows)

    bridge.setToIndex(bridge.toIndex + 1)

    assert bridge.isEmpty is True
    assert bridge.model.rowCount() == 0
    assert "参数已改" in bridge.statusText


@pytest.mark.ui
def test_selecting_the_same_parameter_keeps_the_table(bridge):
    before = bridge.statusText
    bridge.setFromIndex(bridge.fromIndex)

    assert bridge.statusText == before


@pytest.mark.ui
def test_sort_by_toggles_direction_on_repeat(bridge):
    bridge._rows = [_row(spread=1.0), _row(spread=2.0)]
    bridge._model.set_rows(bridge._rows)

    bridge.sortBy(_NAME_COL)
    assert bridge.sortColumn == _NAME_COL
    assert bridge.sortAscending is True

    bridge.sortBy(_NAME_COL)
    assert bridge.sortAscending is False


@pytest.mark.ui
def test_add_to_cart_carries_the_current_direction(bridge):
    bridge._rows = [_row(tid=34)]
    bridge._model.set_rows(bridge._rows)

    bridge.addToCart(0)

    group = bridge._cart.groups()[0]
    assert group["label"] == "Jita(卖单) → Amarr(买单)"
    assert group["rows"][0]["typeId"] == 34
    assert "购物车 1 项" in bridge.cartSummary


@pytest.mark.ui
def test_add_to_cart_out_of_range_is_ignored(bridge):
    bridge._rows = []
    bridge._model.set_rows([])

    bridge.addToCart(5)

    assert bridge._cart.count() == 0


# ── 筛选项 ──────────────────────────────────────────────────


def _feed(bridge, rows):
    bridge._rows = list(rows)
    bridge._apply_filters()


@pytest.mark.ui
def test_filters_are_on_by_default(bridge):
    """默认就把「不赚钱的」和「没对手盘的」挡在外面 —— 否则榜首全是空挂单的垃圾。"""
    assert bridge.hideUnprofitable is True
    assert bridge.liquidityOptions[bridge.liquidityIndex] == "两侧 ≥ 1"


@pytest.mark.ui
def test_unprofitable_rows_are_hidden(bridge):
    _feed(bridge, [_row(tid=1, spread=5.0), _row(tid=2, spread=-5.0), _row(tid=3, spread=0.0)])

    assert [r["id"] for r in bridge._visible] == [1]


@pytest.mark.ui
def test_rows_without_a_counterparty_are_hidden(bridge):
    """任一侧对手盘为 0（= 那侧没有真实报价，价是 ESI 基准价兜底填的）就成不了单。"""
    _feed(
        bridge,
        [
            _row(tid=1, va=10, vb=10),
            _row(tid=2, va=0, vb=50),
            _row(tid=3, va=50, vb=0),
            _row(tid=4, va=0, vb=0),
        ],
    )

    assert [r["id"] for r in bridge._visible] == [1]


@pytest.mark.ui
def test_raising_the_liquidity_bar_is_stricter(bridge):
    rows = [_row(tid=1, va=5, vb=5), _row(tid=2, va=20, vb=20), _row(tid=3, va=500, vb=500)]
    _feed(bridge, rows)
    assert len(bridge._visible) == 3

    bridge.setLiquidityIndex(2)  # 两侧 ≥ 10
    assert [r["id"] for r in bridge._visible] == [2, 3]

    bridge.setLiquidityIndex(3)  # 两侧 ≥ 100
    assert [r["id"] for r in bridge._visible] == [3]

    bridge.setLiquidityIndex(0)  # 不限
    assert len(bridge._visible) == 3


@pytest.mark.ui
def test_status_reports_how_many_were_filtered_out(bridge):
    """筛掉多少必须看得见，否则「只有 200 行」会被当成数据缺失。"""
    _feed(bridge, [_row(tid=1), _row(tid=2, va=0)])

    assert "1 / 2 行" in bridge.statusText

    bridge.setLiquidityIndex(0)
    assert bridge.statusText.startswith("2 行")


@pytest.mark.ui
def test_filters_do_not_refetch(bridge):
    """切筛选项只在内存里挑，全量结果一份都不动（也不重算 SQL）。"""
    _feed(bridge, [_row(tid=1), _row(tid=2, va=0)])

    bridge.setLiquidityIndex(0)

    assert len(bridge._rows) == 2


@pytest.mark.ui
def test_empty_hint_distinguishes_filtered_from_no_data(bridge):
    """全被筛掉 ≠ 没算过 —— 两种空表的提示文案不能一样。"""
    assert "还没有数据" in bridge.emptyHint

    _feed(bridge, [_row(tid=1, va=0)])
    assert bridge.isEmpty is True
    assert "筛选" in bridge.emptyHint


@pytest.mark.ui
def test_changing_parameters_clears_the_filtered_view_too(bridge):
    _feed(bridge, [_row(tid=1)])
    bridge.setToIndex(bridge.toIndex + 1)

    assert bridge.isEmpty is True
    assert bridge._visible == []


@pytest.mark.ui
def test_bridge_without_a_shell_still_works():
    """测试/独立使用时不带外壳：默认参数照旧，只是没有购物车。"""
    from ui_qml.bridge.trade_bridge import TradeBridge

    b = TradeBridge(None)

    assert b.cartSummary == ""
    b.addToCart(0)  # 不该抛
    assert "购物车不可用" in b.hintText


@pytest.mark.ui
def test_failed_rank_clears_busy_and_explains(bridge):
    """排行线程抛异常后「开始计算」必须恢复可用，并如实说明原因。

    回归用例：`run()` 里没有 try/except，`finished_signal` 永不发射 → `_busy` 卡在 True
    → 按钮由 `enabled: !busy` 永久禁用，只能重开页面；同时逃逸异常会走 `sys.excepthook`
    弹「程序遇到了意外错误，请重启应用」—— 一次可恢复的 `database is locked` 被报成崩溃。
    """
    bridge._busy = True
    bridge._on_rank_failed(bridge._gen, "database is locked")

    assert bridge.busy is False
    assert "database is locked" in bridge.statusText

    # 过期代次的失败不得复位当前这一轮（否则旧线程能把新计算的忙碌状态清掉）
    bridge._busy = True
    bridge._on_rank_failed(bridge._gen - 1, "陈旧失败")
    assert bridge.busy is True


@pytest.mark.ui
def test_analyze_reads_local_prices_only(bridge, monkeypatch):
    """「开始计算」只读本地价：不触发 ESI 拉取，但排行 worker 必须真的起来。

    捕获的缺陷：`request_price_update` 那一跳没删干净（点一次计算顺带全量拉取），
    或者删过头把排行也一起删了（按钮变成空转）。两侧都要守。
    """
    import ui_qml.workers.trade_workers as tw

    started: list[dict] = []

    class _FakeWorker:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.finished_signal = Mock()
            self.failed_signal = Mock()
            #: 真实 QThread 必有 `finished`；桥的 `spawn()` 会连它做保活自摘
            self.finished = Mock()

        def start(self):
            started.append(self.kwargs)

        def isRunning(self):
            return False

    monkeypatch.setattr(tw, "CrossRegionRankWorker", _FakeWorker)

    bridge.analyze()

    bridge._shell.request_price_update.assert_not_called()
    assert len(started) == 1


# ════════════════════════════════════════════════════════════
#  页面层
# ════════════════════════════════════════════════════════════


@pytest.fixture
def trade_page(qapp):
    from ui_qml.bridge.trade_bridge import TradeBridge

    with page_host("pages/TradePage.qml", TradeBridge(None)) as pair:
        yield pair


@pytest.mark.ui
def test_page_loads_and_is_quiet(trade_page):
    """能加载 + 桥到位 + 不给 Qt 刷告警（共用实现见 `tests/qml_page_load.py`）。"""
    host, bridge = trade_page
    assert_page_loads_quietly(host, bridge, key="trade", size=(1280, 720))


@pytest.mark.ui
def test_page_has_no_removed_sections(trade_page):
    """重构删掉的区块不能再冒出来：搜索框 / 贸易评分 / 最优路线 / 运输 Tab。"""
    from PySide6.QtCore import QObject

    host, _ = trade_page
    names = {o.objectName() for o in host.rootObject().findChildren(QObject)}

    assert "tradeToolbar" in names
    assert "analyzeButton" in names
    assert "cartButton" in names
    assert "suggestPopup" not in names
    assert "transportInput" not in names
    assert "searchInput" not in names
