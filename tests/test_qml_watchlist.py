"""价格监控 / 关注页（阶段 3 建的页，WP5 重构成左列表 + 右详情）的契约测试。

分三层（与 `test_qml_query.py` / `test_qml_trade.py` 同构）：
  - **纯函数层**（`fast`）：`WatchlistQmlModel` 的角色与三层行底色规则；
    以及右详情的纯计算（排序 / 对比表 / 加入以来涨幅 / BOM 节点合并）；
  - **桥层**（`ui`）：`WatchlistBridge` 的增删改、状态栏文案、右详情装配（DB 调用全部打桩）；
  - **页面层**（`ui`）：`WatchlistPage.qml` 能加载、无 QML 告警、行点击与折线归一化。
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt

from tests.qml_click import press_move_release
from tests.qml_click import spin as _spin
from tests.qml_page_load import assert_page_loads_quietly, page_host
from ui_qml.bridge.watchlist_bridge import (
    bom_nodes,
    comparison_rows,
    rise_pct,
    sort_rows,
)
from ui_qml.models.watchlist_qml_model import ROLE_NAMES, WatchlistQmlModel

_BASE = Qt.ItemDataRole.UserRole
_TEXT = _BASE + 1
_FG = _BASE + 2
_BG = _BASE + 3
_ALIGN_RIGHT = _BASE + 5
_MONO = _BASE + 6
_WATCH_ID = _BASE + 8
_ITEM_NAME = _BASE + 9
_RISE_TEXT = _BASE + 13

pytestmark = pytest.mark.ui


def _row(
    wid: int = 1,
    tid: int = 34,
    zh: str = "三钛合金",
    buy: float | None = 5.0,
    sell: float | None = 6.0,
    buy_threshold: float | None = None,
    sell_threshold: float | None = None,
    note: str = "",
    added_price: float | None = None,
) -> dict:
    return {
        "id": wid,
        "type_id": tid,
        "zh_name": zh,
        "en_name": "Tritanium",
        "region_id": 10000002,
        "buy_price": buy,
        "sell_price": sell,
        "buy_threshold": buy_threshold,
        "sell_threshold": sell_threshold,
        "note": note,
        "added_price": added_price,
    }


def _cell(model: WatchlistQmlModel, row: int, col: int, role: int):
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
    model = WatchlistQmlModel()
    model.set_rows([_row()])
    for col in range(model.columnCount()):
        for role in ROLE_NAMES:
            model.data(model.index(0, col), role)


@pytest.mark.fast
def test_text_matches_the_widgets_columns():
    model = WatchlistQmlModel()
    model.set_rows([_row()])
    assert _cell(model, 0, 0, _TEXT) == ""  # 图标列无文字
    assert _cell(model, 0, 1, _TEXT) == "三钛合金"
    assert _cell(model, 0, 2, _TEXT) == "Tritanium"
    assert _cell(model, 0, 3, _TEXT) == "Jita"
    assert _cell(model, 0, 4, _TEXT) == "5.00"
    assert _cell(model, 0, 5, _TEXT) == "6.00"
    assert _cell(model, 0, 6, _TEXT) == "+20.0%"
    assert _cell(model, 0, 7, _TEXT) == "—"  # 未设阈值
    assert _cell(model, 0, 9, _TEXT) == ""


@pytest.mark.fast
def test_id_and_name_roles():
    model = WatchlistQmlModel()
    model.set_rows([_row(wid=7)])
    assert _cell(model, 0, 0, _WATCH_ID) == 7
    assert _cell(model, 0, 0, _ITEM_NAME) == "三钛合金"
    # 左侧窄列表（`ListView`）用的**行级**角色：与列无关，列 0 上取也一样
    assert _cell(model, 0, 0, _BASE + 10) == "三钛合金"  # rowName
    assert _cell(model, 0, 0, _BASE + 11) == "5.00"  # buyText
    assert _cell(model, 0, 0, _BASE + 12) == "6.00"  # sellText
    assert _cell(model, 0, 0, _RISE_TEXT) == "—"  # 桥没注入 rise_text（无 added_price）→ 不冒充 0
    assert _cell(model, 0, 0, _BASE + 14) == ""  # note

    # 左列表的行卡片载荷走的是同一个 data()（展示规则不漂移）
    card = model.list_rows()[0]
    assert (card["row"], card["name"], card["buyText"], card["sellText"], card["riseText"]) == (
        0,
        "三钛合金",
        "5.00",
        "6.00",
        "—",
    )
    assert card["bg"], "行底色必须由模型给（价格变化/阈值触发都在这条链上）"


@pytest.mark.fast
def test_alignment_and_mono_only_on_number_columns():
    model = WatchlistQmlModel()
    model.set_rows([_row()])
    for col in range(model.columnCount()):
        expected = col in (4, 5, 6, 7, 8)
        assert _cell(model, 0, col, _ALIGN_RIGHT) is expected
        assert _cell(model, 0, col, _MONO) is expected


@pytest.mark.fast
def test_price_columns_coloured_by_side():
    model = WatchlistQmlModel()
    model.set_rows([_row()])
    assert _cell(model, 0, 4, _FG)  # 买价 → 绿
    assert _cell(model, 0, 5, _FG)  # 卖价 → 红
    assert _cell(model, 0, 6, _FG)  # 差价% → 橙

    bare = WatchlistQmlModel()
    bare.set_rows([_row(buy=None, sell=None)])
    assert _cell(bare, 0, 4, _TEXT) == "—"
    assert _cell(bare, 0, 6, _FG)  # 无价时回落次要色（不能是空串）


@pytest.mark.fast
def test_row_background_prefers_price_change_over_threshold():
    """三层优先级：价格变化 > 阈值触发 > 隔行。"""
    plain = WatchlistQmlModel()
    plain.set_rows([_row()])
    plain_bg = _cell(plain, 0, 1, _BG)

    # 阈值触发：买价 5 ≤ 阈值 99
    model = WatchlistQmlModel()
    model.set_rows([_row(buy_threshold=99.0)])
    threshold_bg = _cell(model, 0, 1, _BG)
    assert threshold_bg and threshold_bg != plain_bg

    # 价格变化压过阈值
    model.set_price_changes({34: {"old_buy": 5.0, "new_buy": 6.0, "old_sell": 6.0, "new_sell": 6.0}})
    changed_bg = _cell(model, 0, 1, _BG)
    assert changed_bg and changed_bg != threshold_bg
    # 带 alpha 的叠加色（#aarrggbb 形式）——写成 #rrggbb 会丢掉透明度、把整行糊成实心色
    assert len(changed_bg) == 9 and changed_bg.startswith("#")


@pytest.mark.fast
def test_background_alternates_without_triggers():
    model = WatchlistQmlModel()
    model.set_rows([_row(), _row(wid=2)])
    first, second = _cell(model, 0, 1, _BG), _cell(model, 1, 1, _BG)
    assert first and second and first != second


# ════════════════════════════════════════════════════════════
#  右详情（WP5）：纯计算
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"sell_price": 120.0, "added_price": 100.0}, 20.0),
        ({"sell_price": 100.0, "added_price": 100.0}, 0.0),
        # 缺任一侧 → None（显示 `—`）：**不拿 0 冒充**
        ({"sell_price": 120.0}, None),  # WP1 迁移前的库：行里没有 added_price 键
        ({"sell_price": 120.0, "added_price": None}, None),  # 加入时库里没价
        ({"sell_price": 120.0, "added_price": 0.0}, None),  # 挂单价 0 = 没有挂单，不是「卖 0 ISK」
        ({"sell_price": None, "added_price": 100.0}, None),
    ],
)
def test_rise_pct_needs_both_sides(row, expected):
    assert rise_pct(row) == expected


@pytest.mark.fast
def test_sort_modes_put_missing_keys_last():
    rows = [
        {**_row(wid=1, tid=10), "created_at": "2026-01-01"},
        {**_row(wid=2, tid=20), "created_at": "2026-03-01", "buy_threshold": 99.0},
        {**_row(wid=3, tid=30), "created_at": "2026-04-01"},
    ]
    # 添加时间：新 → 旧
    assert [r["id"] for r in sort_rows(rows, 0)] == [3, 2, 1]
    # 涨幅：高 → 低，算不出的（None）排最后
    assert [r["id"] for r in sort_rows(rows, 1, {10: 5.0, 20: None, 30: 9.0})] == [3, 1, 2]
    # 阈值触发：触发的在前，组内仍按添加时间新 → 旧
    assert [r["id"] for r in sort_rows(rows, 2)] == [2, 3, 1]


@pytest.mark.fast
def test_comparison_rows_show_dash_instead_of_zero_for_missing_data():
    """对比表 5 行：当前 / 加入时 / 30 / 90 / 180 天前，涨跌以**当前**为基准。"""
    rows = comparison_rows(100.0, None, {30: 80.0, 90: None, 180: 60.0})
    assert [r["label"] for r in rows] == ["当前", "加入时", "30 天前", "90 天前", "180 天前"]
    assert [r["caliber"] for r in rows] == ["挂单价", "挂单价", "成交均价", "成交均价", "成交均价"]
    by_label = {r["label"]: r for r in rows}

    # 缺数据的单元格一律 `—`（**不用 0 冒充**，也不留空串）
    for label in ("加入时", "90 天前"):
        assert by_label[label]["text"] == "—"
        assert by_label[label]["deltaText"] == "—"
        assert by_label[label]["pctText"] == "—"
        assert by_label[label]["price"] is None
    # 「当前」行不跟自己比
    assert by_label["当前"]["deltaText"] == "—"
    assert by_label["当前"]["pctText"] == "—"

    # 有数据的档位：涨跌 = 当前 − 该档位（绝对值 + 百分比两栏）
    assert by_label["30 天前"]["text"] == "80.00"
    assert by_label["30 天前"]["deltaText"] == "+20.00"
    assert by_label["30 天前"]["pctText"] == "+25.0%"
    assert by_label["180 天前"]["deltaText"] == "+40.00"

    # 当前价也没有时：各档位照常显示自己的价，涨跌一律 `—`
    no_cur = {r["label"]: r for r in comparison_rows(None, 50.0, {30: 80.0})}
    assert no_cur["加入时"]["text"] == "50.00"
    assert no_cur["加入时"]["pctText"] == "—"
    assert no_cur["30 天前"]["text"] == "80.00"
    assert no_cur["30 天前"]["deltaText"] == "—"


@pytest.mark.fast
def test_bom_nodes_merge_duplicates_and_keep_the_shallowest_level():
    """BOM 是 DAG：同一物品在多处出现要**按 typeId 合并**（层级取最浅、数量求和）。"""
    leaf_deep = SimpleNamespace(type_id=34, name="三钛合金", quantity=100.0, depth=2, children=[])
    leaf_shallow = SimpleNamespace(type_id=34, name="三钛合金", quantity=50.0, depth=1, children=[])
    mid = SimpleNamespace(type_id=35, name="类晶胶", quantity=10.0, depth=1, children=[leaf_deep])
    root = SimpleNamespace(type_id=587, name="裂谷级", quantity=1.0, depth=0, children=[mid, leaf_shallow])

    nodes = bom_nodes(root, 2)
    assert [(n["typeId"], n["level"], n["qty"]) for n in nodes] == [
        (587, 0, 1.0),
        (35, 1, 10.0),
        (34, 1, 150.0),
    ]


# ════════════════════════════════════════════════════════════
#  桥
# ════════════════════════════════════════════════════════════


@pytest.fixture
def bridge(qapp, monkeypatch):
    """桥会真的读关注列表与建表，这里把 DB 层全部打桩。"""
    import services.watchlist_manager as wm
    from ui_qml.bridge import watchlist_bridge as wb

    rows: list[dict] = []
    calls: list[tuple] = []

    def _add(**kw):
        rows.append(_row(wid=99, note=kw.get("note", "")))
        return 99

    monkeypatch.setattr(wm, "init_db", lambda: None)
    monkeypatch.setattr(wm, "get_watchlist", lambda: list(rows))
    monkeypatch.setattr(wm, "add_to_watchlist", _add)
    monkeypatch.setattr(wm, "remove_from_watchlist", lambda wid: rows.clear())
    monkeypatch.setattr(wm, "update_watchlist_item", lambda wid, **kw: calls.append((wid, kw)))
    monkeypatch.setattr(wm, "check_price_changes", lambda: [])
    # 右详情的价格历史也读库：默认给「没有历史」，需要历史的用例自己再打一次
    monkeypatch.setattr(wb, "read_history", lambda *a, **kw: [])

    from ui_qml.bridge.watchlist_bridge import WatchlistBridge

    b = WatchlistBridge(None)
    b._calls = calls  # 供用例断言
    b._rows_ref = rows  # 桩里的「库」——refresh() 会重新读它
    return b


@pytest.mark.ui
def test_columns_and_regions_come_from_shared_sources(bridge):
    from core.constants import TRADE_HUB_IDS
    from ui_qml.models.watchlist_models import COLUMNS

    assert bridge.regions == list(TRADE_HUB_IDS.keys())
    assert [c["title"] for c in bridge.columns] == [t for t, _ in COLUMNS]


@pytest.mark.ui
def test_empty_watchlist_reports_zero(bridge):
    assert bridge.model.rowCount() == 0
    assert bridge.countText == "共 0 项"


@pytest.mark.ui
def test_add_without_selection_fails(bridge):
    """没选物品时返回 False，由 QML 提示（对应 Widgets 版的 QMessageBox.warning）。"""
    assert bridge.add() is False
    assert bridge.model.rowCount() == 0


@pytest.mark.ui
def test_add_resets_the_editor_on_success(bridge):
    bridge.pickSuggestion(-1)  # 越界：不动
    bridge._suggestions = [{"typeId": 34, "text": "[34] 三钛合金"}]
    bridge.pickSuggestion(0)
    bridge.setNote("盯一下")
    assert bridge.selectedName == "[34] 三钛合金"

    assert bridge.add() is True
    assert bridge.searchText == ""
    assert bridge.selectedName == ""
    assert bridge.note == ""
    assert bridge.model.rowCount() == 1


@pytest.mark.ui
def test_threshold_is_cleared_when_value_is_not_positive(bridge):
    # `setThreshold` 末尾会 refresh()，所以要把行放进桩的「库」里而不是只塞模型
    bridge._rows_ref.append(_row(wid=5))
    bridge.refresh()
    assert bridge.model.rowCount() == 1

    bridge.setThreshold(0, "buy", 0.0)
    assert bridge._calls == [(5, {"buy_threshold": None})]

    bridge.setThreshold(0, "sell", 12.5)
    assert bridge._calls[-1] == (5, {"sell_threshold": 12.5})


@pytest.mark.ui
def test_threshold_on_out_of_range_row_is_a_noop(bridge):
    bridge.setThreshold(9, "buy", 1.0)
    assert bridge._calls == []


@pytest.mark.ui
def test_row_info_exposes_thresholds(bridge):
    bridge._model.set_rows([_row(wid=5, buy_threshold=3.0, sell_threshold=None)])
    info = bridge.rowInfo(0)
    assert info["valid"] is True
    assert info["name"] == "三钛合金"
    assert info["buyThreshold"] == 3.0
    assert info["sellThreshold"] == 0.0

    assert bridge.rowInfo(9)["valid"] is False


@pytest.mark.ui
def test_price_check_pushes_status_to_shell(bridge, monkeypatch):
    """状态栏文案：条数 + 触发数 + 价格变化数。"""
    seen: list[str] = []
    bridge._shell = type("S", (), {"set_status": staticmethod(lambda t: seen.append(t))})()
    bridge._rows_ref.extend([_row(buy_threshold=99.0), _row(wid=2)])
    bridge._price_changes = {34: {"old_buy": 1, "new_buy": 2}}
    bridge.refresh()

    assert seen, "刷新后应推一条状态"
    assert "2 项" in seen[-1]
    assert "触发提醒" in seen[-1]
    assert "价格变化" in seen[-1]


# ════════════════════════════════════════════════════════════
#  页面层
# ════════════════════════════════════════════════════════════


@pytest.fixture
def watch_page(qapp, monkeypatch):
    import services.watchlist_manager as wm
    from ui_qml.bridge import watchlist_bridge as wb
    from ui_qml.bridge.watchlist_bridge import WatchlistBridge

    monkeypatch.setattr(wm, "init_db", lambda: None)
    monkeypatch.setattr(wm, "get_watchlist", lambda: [])
    monkeypatch.setattr(wb, "read_history", lambda *a, **kw: [])

    with page_host("pages/WatchlistPage.qml", WatchlistBridge(None)) as pair:
        yield pair


@pytest.mark.ui
def test_page_loads_and_is_quiet(watch_page):
    """能加载 + 桥到位 + 不给 Qt 刷告警（共用实现见 `tests/qml_page_load.py`）。"""
    host, bridge = watch_page
    root = assert_page_loads_quietly(host, bridge, key="watch", size=(1200, 700))
    assert root.property("currentRow") == -1


@pytest.mark.ui
def test_row_click_survives_content_move(watch_page):
    """行点击命中固定在按下那一刻（见 `FTableClickArea` 的说明）。

    回归背景：delegate 里的 `TapHandler` 配 `ReleaseWithinBounds` 在**释放**时判定
    命中，内容一移动（甩动/惯性沉降）就整次丢掉点击 —— 界面表现是
    「单击不到所对应的行上」。
    """
    host, bridge = watch_page
    bridge._model.set_rows([_row(wid=i + 1) for i in range(50)])
    _spin(150)
    root = host.rootObject()
    press_move_release(
        host, root, area_name="watchClickArea", row=3, read_current=lambda: root.property("currentRow"), delta=1
    )


@pytest.mark.ui
def test_detail_shows_added_price_when_present_and_dash_when_absent(bridge, monkeypatch):
    """`added_price` 两种情形：有 → 显示「加入时」价与加入以来涨幅；无 → `—`（不是 0）。"""
    from ui_qml.bridge import watchlist_bridge as wb

    today = date.today()
    history = [
        ((today - timedelta(days=179)).isoformat(), 60.0, 10),
        ((today - timedelta(days=90)).isoformat(), 70.0, 20),
        ((today - timedelta(days=30)).isoformat(), 80.0, 30),
        (today.isoformat(), 100.0, 40),
    ]
    monkeypatch.setattr(wb, "read_history", lambda *a, **kw: list(history))

    bridge._model.set_rows([_row(wid=1, sell=120.0, added_price=100.0), _row(wid=2, sell=120.0)])
    bridge.selectRow(0)

    assert bridge.detail["valid"] is True
    assert bridge.detail["name"] == "三钛合金"
    rows = {r["label"]: r for r in bridge.detail["rows"]}
    assert rows["加入时"]["text"] == "100.00"
    assert rows["加入时"]["pctText"] == "+20.0%"  # 120 / 100 − 1
    assert rows["30 天前"]["text"] == "80.00"
    assert rows["30 天前"]["pctText"] == "+50.0%"  # (120 − 80) / 80

    # 折线：成交均价 + 成交量同轴同日（窗口 180 天，最早那条 179 天前刚好在内）
    assert bridge.chartLabels == [day for day, _avg, _vol in history]
    assert bridge.priceSeries[0]["points"][-1]["y"] == 100.0
    assert bridge.volumeSeries[0]["points"][-1]["y"] == 40

    # 没有 added_price（迁移前的库，行里压根没这个键）→ `—`，**不是 0.00**
    bridge._model.set_rows([_row(wid=2, sell=120.0)])
    bridge.selectRow(0)
    rows = {r["label"]: r for r in bridge.detail["rows"]}
    assert rows["加入时"]["text"] == "—"
    assert rows["加入时"]["pctText"] == "—"


@pytest.mark.ui
def test_material_series_are_absolute_in_bridge_and_normalised_by_the_chart(watch_page, monkeypatch):
    """勾选「显示制造材料」：桥给**绝对值**，`FLineChart` 按各自首点归一到 100。

    捕获的缺陷：归一化写反成「绝对值叠加」—— 材料价格差 3~4 个数量级时会压成一条直线，
    且图例里的「基期=100」说明与实际画法不符。
    """
    from ui_qml.bridge import watchlist_bridge as wb

    payload = {
        "rows": [
            {
                "name": "裂谷级",
                "typeId": 587,
                "level": 0,
                "indent": 0,
                "qtyText": "1",
                "priceText": "5.00",
                "agoText": "4.00",
                "pctText": "+25.0%",
                "pct": 25.0,
                "caliber": "挂单价",
            },
        ],
        "series": [
            {
                "label": "裂谷级",
                "color": "#123456",
                "points": [{"x": 0, "y": 5.0}, {"x": 1, "y": 6.0}, {"x": 2, "y": 7.5}],
            },
            {"label": "三钛合金", "color": "#654321", "points": [{"x": 0, "y": 100.0}, {"x": 1, "y": 200.0}]},
        ],
        "hint": "口径：挂单价",
    }
    monkeypatch.setattr(wb, "load_materials", lambda *a, **kw: payload)

    host, bridge = watch_page
    bridge._model.set_rows([_row(wid=1, added_price=100.0)])
    bridge.selectRow(0)
    bridge.setShowMaterials(True)
    _spin(150)

    root = host.rootObject()
    chart = root.findChild(QObject, "materialChart")
    assert chart is not None, "详情面板里应有材料折线（objectName: materialChart）"
    assert chart.property("normalize") is True
    # 桥给的是绝对值（归一化是组件的事；桥里归一化会让图例与表里的绝对值对不上）
    assert bridge.materialSeries[0]["points"][0]["y"] == 5.0

    rng = chart.property("_range")
    values = rng if isinstance(rng, dict) else rng.toVariant()
    # 两条线都单调不降 → 归一化后全图最小值就是各线首点（= 100），最大值来自第二条线
    assert values["lo"] == 100.0
    assert values["hi"] == 200.0
