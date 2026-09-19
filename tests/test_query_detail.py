"""物品查询页「有结果态」详情桥的契约测试（第 2 步）。

分两层：
  - **纯函数层**（`fast`）：`query_detail_model` 的几何/文案规则 —— 柱长归一化、
    帝国映射、买/卖双价、精炼产出扁平化。
  - **桥层**（`ui`）：`QueryDetailBridge` 的属性默认值、状态重算与订单渲染
    （桥构造本身不起线程，故这里也不触发任何真实取数；DB/ESI 一律 patch 掉）。
"""

from __future__ import annotations

import pytest

from tests.clipboard_wait import wait_for_clipboard
from ui_qml.models.query_detail_model import (
    hub_bar_rows,
    material_rows,
    refine_rows,
    refine_total_rows,
)

_HUBS = ["Jita", "Amarr", "Dodixie", "Rens", "Hek"]


def _snap(buy: float, sell: float) -> dict:
    return {"buy": buy, "sell": sell, "buy_volume": 1, "sell_volume": 1}


# ════════════════════════════════════════════════════════════════
#  hub_bar_rows
# ════════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_hub_bar_rows_five_hubs_order_and_flags():
    """5 个中心齐全：顺序按 hubs、买最高/卖最低各自标最优、柱长归一化到 1.0。"""
    snapshots = {
        "Jita": _snap(100.0, 120.0),
        "Amarr": _snap(80.0, 110.0),
        "Dodixie": _snap(60.0, 130.0),
        "Rens": _snap(40.0, 140.0),
        "Hek": _snap(20.0, 150.0),
    }
    rows = hub_bar_rows(snapshots, _HUBS)
    assert [r["hub"] for r in rows] == _HUBS

    # Jita 买价最高、Amarr 卖价最低
    assert [r["hub"] for r in rows if r["bestBuy"]] == ["Jita"]
    assert [r["hub"] for r in rows if r["bestSell"]] == ["Amarr"]

    # 柱长按 5 个中心一起归一化：最大买/卖各为 1.0
    assert max(r["buyPos"] for r in rows) == pytest.approx(1.0)
    assert max(r["sellPos"] for r in rows) == pytest.approx(1.0)
    assert rows[0]["buyPos"] == pytest.approx(1.0)  # Jita 买价最大
    assert rows[1]["sellPos"] == pytest.approx(110.0 / 150.0)  # Amarr 卖价 → 几何按最大卖归一化

    assert rows[0]["buyText"] == "100.00"
    assert rows[0]["buyVal"] == pytest.approx(100.0)
    assert rows[0]["sellVal"] == pytest.approx(120.0)


@pytest.mark.fast
def test_hub_bar_rows_missing_hub_is_dash_and_not_best():
    """某中心整个缺数据：文案 `—`、柱长 0、不参与最优。"""
    snapshots = {
        "Jita": _snap(100.0, 120.0),
        "Amarr": _snap(80.0, 110.0),
        # Dodixie / Rens / Hek 缺失
    }
    rows = hub_bar_rows(snapshots, _HUBS)
    dodixie = next(r for r in rows if r["hub"] == "Dodixie")
    assert dodixie["buyText"] == "—"
    assert dodixie["sellText"] == "—"
    assert dodixie["buyPos"] == 0.0
    assert dodixie["sellPos"] == 0.0
    assert dodixie["bestBuy"] is False
    assert dodixie["bestSell"] is False
    # 缺失中心不影响有数据中心的归一化（最大仍是 Jita）
    assert max(r["buyPos"] for r in rows) == pytest.approx(1.0)


@pytest.mark.fast
def test_hub_bar_rows_all_zero():
    """全为 0：所有柱长 0.0、都显 `—`、没人被标最优。"""
    snapshots = {h: _snap(0.0, 0.0) for h in _HUBS}
    rows = hub_bar_rows(snapshots, _HUBS)
    assert all(r["buyPos"] == 0.0 and r["sellPos"] == 0.0 for r in rows)
    assert all(r["buyText"] == "—" and r["sellText"] == "—" for r in rows)
    assert not any(r["bestBuy"] or r["bestSell"] for r in rows)


@pytest.mark.fast
def test_hub_bar_rows_tie_marks_first_only():
    """并列最优时只标第一个。"""
    snapshots = {
        "Jita": _snap(100.0, 120.0),
        "Amarr": _snap(100.0, 110.0),  # 买价与 Jita 并列最高，卖价最低
        "Dodixie": _snap(50.0, 110.0),  # 卖价与 Amarr 并列最低
        "Rens": _snap(10.0, 200.0),
        "Hek": _snap(5.0, 300.0),
    }
    rows = hub_bar_rows(snapshots, _HUBS)
    assert [r["hub"] for r in rows if r["bestBuy"]] == ["Jita"]
    assert [r["hub"] for r in rows if r["bestSell"]] == ["Amarr"]


@pytest.mark.fast
def test_hub_bar_rows_zero_is_not_treated_as_best_sell():
    """0 价（缺失）不该被当成「最低卖价」。"""
    snapshots = {
        "Jita": _snap(100.0, 0.0),
        "Amarr": _snap(80.0, 110.0),
        "Dodixie": _snap(60.0, 130.0),
        "Rens": _snap(40.0, 0.0),
        "Hek": _snap(20.0, 0.0),
    }
    rows = hub_bar_rows(snapshots, _HUBS)
    assert [r["hub"] for r in rows if r["bestSell"]] == ["Amarr"]


@pytest.mark.fast
def test_hub_bar_rows_empire_mapping():
    """每个中心带所在帝国的中文名与主题 token 名（不是色值）。"""
    snapshots = {h: _snap(1.0, 2.0) for h in _HUBS}
    rows = hub_bar_rows(snapshots, _HUBS)
    by_hub = {r["hub"]: r for r in rows}

    assert by_hub["Jita"]["empire"] == "加达里"
    assert by_hub["Jita"]["empireColor"] == "ACCENT_CYAN"
    assert by_hub["Amarr"]["empire"] == "艾玛"
    assert by_hub["Amarr"]["empireColor"] == "ACCENT_YELLOW"
    assert by_hub["Dodixie"]["empire"] == "盖伦特"
    assert by_hub["Dodixie"]["empireColor"] == "ACCENT_GREEN"
    assert by_hub["Rens"]["empire"] == "米玛塔尔"
    assert by_hub["Rens"]["empireColor"] == "ACCENT_RED"
    assert by_hub["Hek"]["empire"] == "米玛塔尔"
    assert by_hub["Hek"]["empireColor"] == "ACCENT_RED"


@pytest.mark.fast
def test_hub_bar_rows_empty_hubs():
    assert hub_bar_rows({}, []) == []


@pytest.mark.fast
def test_empire_tokens_are_valid_theme_tokens():
    """帝国色 token 名必须都能在主题里解析到色值（否则会静默退回 TEXT_SECONDARY）。"""
    from ui_qml.models.query_detail_model import _EMPIRE_TOKEN
    from ui_qml.theme import registry as theme

    assert set(_EMPIRE_TOKEN.values()) == {"ACCENT_YELLOW", "ACCENT_CYAN", "ACCENT_GREEN", "ACCENT_RED"}
    for token in _EMPIRE_TOKEN.values():
        assert isinstance(getattr(theme, token, None), str)


# ════════════════════════════════════════════════════════════════
#  material_rows
# ════════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_material_rows_empty():
    assert material_rows([]) == []
    assert material_rows([], []) == []


@pytest.mark.fast
def test_material_rows_buy_and_sell_prices():
    """材料行同时给出买/卖单价与买/卖合计。"""
    sell = [
        {"type_id": 34, "name": "三钛合金", "total_qty": 1000, "unit_price": 5.0, "subtotal": 5000.0},
        {"type_id": 35, "name": "类晶体胶矿", "total_qty": 20, "unit_price": 9.0, "subtotal": 180.0},
    ]
    buy = [
        {"type_id": 34, "name": "三钛合金", "total_qty": 1000, "unit_price": 4.0, "subtotal": 4000.0},
        {"type_id": 35, "name": "类晶体胶矿", "total_qty": 20, "unit_price": 8.0, "subtotal": 160.0},
    ]
    rows = material_rows(sell, buy)
    assert [r["name"] for r in rows] == ["三钛合金", "类晶体胶矿"]
    assert rows[0] == {
        "name": "三钛合金",
        "qtyText": "1,000",
        "buyText": "4.00",
        "sellText": "5.00",
        "totalBuyText": "4,000.00",
        "totalSellText": "5,000.00",
    }
    assert rows[1]["qtyText"] == "20"


@pytest.mark.fast
def test_material_rows_missing_buy_side():
    """没给买价那份时买价列退化为 0.00（不崩）。"""
    sell = [{"type_id": 34, "name": "三钛合金", "total_qty": 10, "unit_price": 5.0, "subtotal": 50.0}]
    rows = material_rows(sell)
    assert rows[0]["buyText"] == "0.00"
    assert rows[0]["sellText"] == "5.00"


# ════════════════════════════════════════════════════════════════
#  refine_rows / refine_total_rows
# ════════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_refine_rows_multiple_outputs():
    """一个投入项产出多个材料 → 每个产出一行；利润按投入项级共享。"""
    result = {
        "items": [
            {
                "input_name": "凡晶石",
                "input_qty": 100,
                "yield_rate": 0.5,
                "output": [
                    {"type_id": 34, "name": "三钛合金", "qty": 415.0, "price": 5.0, "total": 2075.0},
                    {"type_id": 35, "name": "类晶体胶矿", "qty": 13.0, "price": 9.0, "total": 117.0},
                ],
                "input_value": 1000.0,
                "output_value": 2192.0,
                "profit": 1192.0,
                "margin_pct": 119.2,
            }
        ],
        "total_input_value": 1000.0,
        "total_output_value": 2192.0,
        "total_profit": 1192.0,
        "item_count": 1,
        "errors": [],
    }
    rows = refine_rows(result)
    assert len(rows) == 2
    assert rows[0]["name"] == "三钛合金"
    assert rows[0]["sourceName"] == "凡晶石"
    assert rows[0]["qtyText"] == "415.00"
    assert rows[0]["valueText"] == "2,075.00"
    assert rows[0]["yieldText"] == "50.0%"
    assert rows[0]["profitText"] == "+1,192.00"
    assert rows[0]["profitPos"] is True
    assert rows[1]["name"] == "类晶体胶矿"


@pytest.mark.fast
def test_refine_rows_negative_profit_sign():
    result = {
        "items": [
            {
                "input_name": "X",
                "input_qty": 1,
                "yield_rate": 0.4,
                "output": [{"type_id": 1, "name": "Y", "qty": 1.0, "price": 1.0, "total": 1.0}],
                "input_value": 100.0,
                "output_value": 1.0,
                "profit": -99.0,
                "margin_pct": -99.0,
            }
        ]
    }
    rows = refine_rows(result)
    assert rows[0]["profitText"] == "-99.00"
    assert rows[0]["profitPos"] is False


@pytest.mark.fast
def test_refine_rows_empty():
    assert refine_rows({}) == []
    assert refine_rows({"items": []}) == []


@pytest.mark.fast
def test_refine_total_rows():
    result = {
        "items": [{"input_name": "X"}],
        "total_output_value": 2192.0,
        "total_input_value": 1000.0,
        "total_profit": 1192.0,
    }
    rows = refine_total_rows(result)
    assert [r["label"] for r in rows] == ["产出", "利润"]
    assert rows[0]["valueText"] == "2,192.00"
    assert rows[1]["valueText"] == "+1,192.00"
    assert rows[1]["token"] == "ACCENT_GREEN"

    loss = refine_total_rows({"items": [{"input_name": "X"}], "total_profit": -5.0, "total_output_value": 1.0})
    assert loss[1]["token"] == "ACCENT_RED"
    assert loss[1]["valueText"] == "-5.00"

    assert refine_total_rows({}) == []
    assert refine_total_rows({"items": []}) == []


# ════════════════════════════════════════════════════════════════
#  QueryDetailBridge（ui：QObject，桥构造本身不起线程）
# ════════════════════════════════════════════════════════════════


def _make_bridge(monkeypatch):
    """构造一个把所有取数替换成记录桩的桥（不起任何线程 / 不碰 DB）。"""
    from ui_qml.bridge.query_detail_bridge import QueryDetailBridge

    bridge = QueryDetailBridge()
    calls: list[str] = []
    monkeypatch.setattr(bridge, "_load_hub_prices", lambda: calls.append("hub"))
    monkeypatch.setattr(bridge, "_load_materials", lambda: calls.append("materials"))
    monkeypatch.setattr(bridge, "_load_refine", lambda: calls.append("refine"))
    monkeypatch.setattr(bridge, "_load_orders", lambda **kw: calls.append("orders"))
    return bridge, calls


@pytest.mark.ui
def test_bridge_defaults(qapp):
    from ui_qml.bridge.query_detail_bridge import QueryDetailBridge

    bridge = QueryDetailBridge()
    assert bridge.typeId == 0
    assert bridge.itemName == ""
    assert bridge.busy is False
    assert bridge.hubRows == []
    assert bridge.orderRows == []
    assert bridge.refineRows == []
    assert bridge.refineTotalRows == []
    assert bridge.materialRows == []
    assert bridge.priceHubIndex == 0
    assert bridge.materialHubIndex == 0
    assert bridge.materialQty == 1
    assert bridge.orderHeads == ["#", "价格 (ISK)", "数量", "空间站"]
    assert bridge.hubNames == ["Jita", "Amarr", "Dodixie", "Rens", "Hek"]
    assert bridge.bestBuyText == "—"
    assert bridge.bestSellText == "—"


@pytest.mark.ui
def test_bridge_set_item_triggers_all_loaders(qapp, monkeypatch):
    bridge, calls = _make_bridge(monkeypatch)
    bridge.setItem(34, "三钛合金")
    assert bridge.typeId == 34
    assert bridge.itemName == "三钛合金"
    assert calls == ["hub", "materials", "refine", "orders"]


@pytest.mark.ui
def test_bridge_price_hub_change_recomputes_refine_and_materials(qapp, monkeypatch):
    bridge, calls = _make_bridge(monkeypatch)
    bridge.setItem(34, "三钛合金")
    calls.clear()

    bridge.setPriceHubIndex(2)  # 未手动改过材料中心 → 跟随
    assert bridge.priceHubIndex == 2
    assert bridge.materialHubIndex == 2
    assert "refine" in calls
    assert "materials" in calls


@pytest.mark.ui
def test_bridge_material_hub_decoupled_from_price_hub(qapp, monkeypatch):
    bridge, calls = _make_bridge(monkeypatch)
    bridge.setItem(34, "三钛合金")
    bridge.setMaterialHubIndex(4)  # 用户显式选择 → 解耦
    calls.clear()

    bridge.setPriceHubIndex(1)
    assert bridge.priceHubIndex == 1
    assert bridge.materialHubIndex == 4  # 不跟随
    assert "refine" in calls
    assert "materials" not in calls  # 材料中心没变 → 不重算


@pytest.mark.ui
def test_bridge_set_material_qty_recomputes(qapp, monkeypatch):
    bridge, calls = _make_bridge(monkeypatch)
    bridge.setItem(34, "三钛合金")
    calls.clear()

    bridge.setMaterialQty(10)
    assert bridge.materialQty == 10
    assert "materials" in calls

    calls.clear()
    bridge.setMaterialQty(0)  # 下限 1，且与现值不同才重算
    assert bridge.materialQty == 1
    assert "materials" in calls


@pytest.mark.ui
def test_bridge_render_orders_split_tables_and_best_prices(qapp):
    from ui_qml.bridge.query_detail_bridge import QueryDetailBridge

    bridge = QueryDetailBridge()
    bridge._render_orders(
        [{"price": 100.0, "volume_remain": 5, "location_id": 60003760}],
        [{"price": 90.0, "volume_remain": 3, "location_id": 60003760}],
    )
    assert bridge.buyOrderCount == 1
    assert bridge.sellOrderCount == 1
    # 两张分表各自从 #1 起
    assert bridge.buyOrderRows[0]["cells"][0]["text"] == "#1"
    assert bridge.sellOrderRows[0]["cells"][0]["text"] == "#1"
    # orderRows 是两张表的顺序拼接（买在前）
    assert bridge.orderRows == bridge.buyOrderRows + bridge.sellOrderRows
    assert bridge.bestBuyText == "100.00"
    assert bridge.bestSellText == "90.00"

    # 清空后回到占位符
    bridge._render_orders([], [])
    assert bridge.buyOrderCount == 0 and bridge.sellOrderCount == 0
    assert bridge.orderRows == []
    assert bridge.bestBuyText == "—"
    assert bridge.bestSellText == "—"


@pytest.mark.ui
def test_bridge_clear_resets_state(qapp, monkeypatch):
    bridge, _calls = _make_bridge(monkeypatch)
    bridge.setItem(34, "三钛合金")
    bridge._render_orders([{"price": 1.0, "volume_remain": 1, "location_id": 1}], [])

    bridge.clear()
    assert bridge.typeId == 0
    assert bridge.itemName == ""
    assert bridge.hubRows == []
    assert bridge.buyOrderRows == [] and bridge.sellOrderRows == []
    assert bridge.orderRows == []
    assert bridge.refineRows == []
    assert bridge.refineTotalRows == []
    assert bridge.materialRows == []
    assert bridge.bestBuyText == "—"
    assert bridge.bestSellText == "—"


@pytest.mark.ui
def test_bridge_refine_total_rows_shape(qapp):
    """refineTotalRows 每项恰好 {label, valueText, color}（QML 按这三个键渲染）。"""
    from ui_qml.bridge.query_detail_bridge import QueryDetailBridge

    bridge = QueryDetailBridge()
    bridge._on_refine_done(
        {
            "items": [
                {
                    "input_name": "X",
                    "input_qty": 1,
                    "yield_rate": 0.5,
                    "output": [{"type_id": 1, "name": "Y", "qty": 1.0, "price": 1.0, "total": 1.0}],
                    "input_value": 1000.0,
                    "output_value": 2192.0,
                    "profit": 1192.0,
                    "margin_pct": 119.2,
                }
            ],
            "total_output_value": 2192.0,
            "total_input_value": 1000.0,
            "total_profit": 1192.0,
        }
    )
    rows = bridge.refineTotalRows
    assert [set(r.keys()) for r in rows] == [{"label", "valueText", "color"}] * 2
    assert rows[1]["label"] == "利润"
    assert rows[1]["color"].startswith("#")
    assert bridge.refineSummary == "总计：产出 2,192.00 ISK / 投入 1,000.00 ISK / 利润 1,192.00 ISK"


@pytest.mark.ui
def test_bridge_resolves_empire_color(qapp):
    """token 名 → 实际色值（过对比度），未知 token 退回 TEXT_SECONDARY。"""
    from ui_qml.bridge.query_detail_bridge import _resolve_color

    color = _resolve_color("ACCENT_CYAN")
    assert color.startswith("#") and len(color) == 7
    assert _resolve_color("") == ""
    assert _resolve_color("NO_SUCH_TOKEN").startswith("#")


@pytest.mark.ui
def test_bridge_copy_price(qapp):

    from ui_qml.bridge.query_detail_bridge import QueryDetailBridge

    bridge = QueryDetailBridge()
    assert bridge.copyPrice(0) == ""  # 无订单不写剪贴板

    bridge._render_orders([{"price": 1234.5, "volume_remain": 1, "location_id": 1}], [])
    assert bridge.copyPrice(0) == "1234.50"
    assert wait_for_clipboard("1234.50") == "1234.50"
    assert bridge.copyPrice(1) == ""  # 无卖单


# ════════════════════════════════════════════════════════════════
#  shutdown（页面销毁时停线程 —— 这条曾经以「进程退出码 127」的形式炸过）
# ════════════════════════════════════════════════════════════════


class _FakeWorker:
    """只记录被怎么对待的假线程。真线程要起 ESI，测试不该为「有没有停它」付这个代价。"""

    def __init__(self, *, running: bool, stops: bool = True) -> None:
        self.running = running
        self.stops = stops
        self.interrupted = False
        self.waited = 0
        self.parent_cleared = False

    def isRunning(self) -> bool:
        return self.running

    def requestInterruption(self) -> None:
        self.interrupted = True

    def wait(self, ms: int) -> bool:
        self.waited = ms
        if self.stops:
            self.running = False
        return self.stops

    def setParent(self, parent) -> None:
        self.parent_cleared = parent is None


def _bare_bridge():
    """建一个**不替换任何取数**的详情桥（QObject 需要 QApplication，故走 ui 档）。

    与上面的 `_make_bridge(monkeypatch)` 区分开：那个把四路取数都换成了记录桩，
    这里要的是真桥，好验证 `shutdown()` 对真实线程属性的处理。
    """
    from ui_qml.bridge.query_detail_bridge import QueryDetailBridge

    return QueryDetailBridge(None)


@pytest.mark.ui
def test_shutdown_stops_a_running_worker():
    b = _bare_bridge()
    w = _FakeWorker(running=True, stops=True)
    b._order_worker = w

    b.shutdown()

    assert w.interrupted is True
    assert w.waited > 0
    assert b._order_worker is None


@pytest.mark.ui
def test_shutdown_orphans_a_worker_that_will_not_stop():
    """join 不掉的线程**解除父子关系并保活**，绝不让 Qt 去析构一个还在跑的 QThread。"""
    from ui_qml.bridge import query_detail_bridge as mod

    b = _bare_bridge()
    w = _FakeWorker(running=True, stops=False)
    b._order_worker = w

    b.shutdown()

    assert w.parent_cleared is True
    assert w in mod._ORPHANED_WORKERS, "必须保活，否则进程退出时崩"
    b._order_worker = None
    mod._ORPHANED_WORKERS.clear()


@pytest.mark.ui
def test_shutdown_ignores_idle_and_absent_workers():
    b = _bare_bridge()
    b._order_worker = _FakeWorker(running=False)
    b._refine_worker = None
    b.shutdown()  # 不起线程、不抛异常


# ════════════════════════════════════════════════════════════════
#  精炼面板的输入：人物 / 数量 / 站点
# ════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_refine_characters_default_to_the_current_one(monkeypatch):
    """人物列表读 `char_config.json`，默认选中其中的 `current`；找不到就用第 0 个。

    产率完全由**所选人物**的提炼技能决定，选错人等于算错产率，所以默认值要跟主程序一致。
    """
    import services.char_config_resolver as ccr

    monkeypatch.setattr(ccr, "get_character_list", lambda: ["甲", "乙"])
    monkeypatch.setattr(ccr, "load_all_data", lambda: {"current": "乙", "characters": {}})
    bridge = _bare_bridge()
    bridge._ensure_chars()
    assert bridge.charNames == ["甲", "乙"]
    assert bridge.refineCharIndex == 1, "应落在配置里的 current 上"

    # current 指向一个不存在的人物 → 退回第 0 个，不能是 -1（QML 侧会拿到空模型）
    monkeypatch.setattr(ccr, "load_all_data", lambda: {"current": "查无此人", "characters": {}})
    other = _bare_bridge()
    other._ensure_chars()
    assert other.refineCharIndex == 0


@pytest.mark.ui
def test_refine_skills_follow_the_selected_character(monkeypatch):
    """`_refine_skills()` 取的是**当前选中人物**的技能（换人物要跟着换）。"""
    import services.char_config_resolver as ccr

    monkeypatch.setattr(ccr, "get_character_list", lambda: ["甲", "乙"])
    monkeypatch.setattr(ccr, "load_all_data", lambda: {"current": "甲", "characters": {}})
    monkeypatch.setattr(
        ccr,
        "resolve_char_config",
        lambda char_name=None, **_kw: {"skills": {"提炼学概论": 5 if char_name == "甲" else 0}},
    )

    bridge = _bare_bridge()
    bridge._ensure_chars()
    assert bridge._refine_skills()["提炼学概论"] == 5

    bridge._refine_char_index = 1
    assert bridge._refine_skills()["提炼学概论"] == 0, "换人物要换技能"

    bridge._char_names = []
    bridge._refine_char_index = -1
    assert bridge._refine_skills() == {}, "没选人物时给空字典（公式按 0 级算）"


@pytest.mark.ui
def test_refine_inputs_recompute_but_only_on_change(monkeypatch):
    """人物 / 数量 / 站点任一改变都要重算精炼；值没变则不重算。

    与材料面板的「制造数量 / 价格中心」同一条约定：改桥 → 由桥重算，
    本组件（及 QML）只负责把值交上去。
    """
    bridge, calls = _make_bridge(monkeypatch)
    bridge._type_id = 34  # 有选中物品才会触发重算
    bridge._char_names = ["甲", "乙"]
    bridge._refine_char_index = 0

    bridge.setRefineCharIndex(1)
    bridge.setRefineQty(10)
    bridge.setRefineFacility(True)
    assert calls == ["refine", "refine", "refine"]

    bridge.setRefineCharIndex(1)  # 同一个人
    bridge.setRefineQty(10)  # 同一个数量
    bridge.setRefineFacility(True)  # 同一个站点
    assert calls == ["refine"] * 3, "值没变不该重算"

    bridge.setRefineCharIndex(99)  # 越界忽略
    assert bridge.refineCharIndex == 1
    assert calls == ["refine"] * 3
