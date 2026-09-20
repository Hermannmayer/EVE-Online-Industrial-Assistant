"""EstimateBridge 契约测试 —— QML 页面后端的行为对齐。

对照 `ui_pyside6/views/estimate_view.py`：bridge 只做转发与整形，
但**转发得对不对**必须锁住，否则 QML 版的数字会和 Widgets 版对不上。
"""

from __future__ import annotations

import pytest

from tests.qml_click import press_move_release
from ui_qml.bridge.estimate_bridge import EstimateBridge

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _no_real_refining(monkeypatch):
    """精炼服务默认换成「什么都精炼不出来」的替身。

    折扣 / 数量一改桥就会重算「精炼价值」列，本文件测的是**桥的整形**，
    不该顺带去读真 SDE 与真行情（那会把用例变成集成测试）。要验真算的用例
    自己在用例里再 patch 一次 `get_container`。
    """
    import ui_qml.bridge.estimate_bridge as eb

    class _Nothing:
        def ore_skill_info(self, type_id):
            return False, ""

        def calc_value(self, type_id, quantity=1, **kwargs):
            return {"output": [], "total_value": 0.0}

    monkeypatch.setattr(eb, "get_container", lambda: type("C", (), {"refining_service": _Nothing()})())


def _bridge_with_rows() -> EstimateBridge:
    b = EstimateBridge()
    b._model.set_rows(
        [
            {
                "type_id": 34,
                "name": "Tritanium",
                "qty": 100,
                "sell_price": 5.0,
                "buy_price": 4.0,
                "unit_price": 0,
                "sell_total": 0,
                "buy_total": 0,
                "volume": 0,
                "_volume": 0.01,
                "bp_me": 0,
                "bp_te": 0,
            },
            {
                "type_id": 35,
                "name": "Pyerite",
                "qty": 200,
                "sell_price": 2.0,
                "buy_price": 1.0,
                "unit_price": 0,
                "sell_total": 0,
                "buy_total": 0,
                "volume": 0,
                "_volume": 0.02,
                "bp_me": 0,
                "bp_te": 0,
            },
        ]
    )
    b._rebuild_unit_prices()
    return b


def test_constants_match_widgets_version(qapp):
    """精炼场地的选项必须与用户看到的词一致（值语义仍是「是不是玩家设施」）。"""
    b = EstimateBridge()
    assert b.refineModes == ["空间站", "玩家设施"]
    assert b.refineMode == "空间站"


def test_hub_options_cover_all_trade_hubs(qapp, monkeypatch):
    """贸易中心下拉：五个中心全覆盖，且 `value` 是取价用的英文键、`label` 走术语表中英对照。

    回归：这里早先是「卖价 / 买价 / 均价」的价格类型下拉，与底部两个「…到剪贴板」
    按钮重复；改成中心下拉后买/卖由底部按钮承担。
    """
    import ui_qml.bridge.estimate_bridge as eb
    from core.constants import TRADE_HUB_IDS

    monkeypatch.setattr(eb, "resolve_system_display_names_batch", lambda ids: {30000142: "吉他 (Jita)"})
    options = EstimateBridge().hubOptions()

    assert [o["value"] for o in options] == list(TRADE_HUB_IDS)
    assert options[0] == {"label": "吉他 (Jita)", "value": "Jita"}
    # 术语表里没有的中心退回英文键，不能给空串（空串会让下拉显示成空白项）
    assert all(o["label"] for o in options)


def test_character_defaults_to_config_current(qapp, monkeypatch):
    """人物下拉读真实 `char_config.json`；技能也按真人取，**没有全5兜底**。

    回归：早先「当前人物」读的是 `shell._current_char`（全库无人赋值），永远退化成
    硬编码的技能全5 —— 人物下拉形同虚设。
    """
    import ui_qml.bridge.estimate_bridge as eb

    monkeypatch.setattr(
        eb, "load_all_data", lambda: {"current": "乙", "characters": {"甲": {"skills": {}}, "乙": {"skills": {}}}}
    )
    monkeypatch.setattr(eb, "resolve_char_config", lambda **kw: {"skills": {"提炼效率理论": 3}})

    b = EstimateBridge()
    assert b.characters == ["甲", "乙"]
    assert b.character == "乙"
    assert b._current_skills() == {"提炼效率理论": 3}


def test_refine_value_column_marks_unrefinable(qapp, monkeypatch):
    """「精炼价值」列：可精炼行 = 服务给的产物总值 × 折扣；不可精炼行留 `None`（渲染「—」）。"""
    import ui_qml.bridge.estimate_bridge as eb

    class _FakeRefining:
        def ore_skill_info(self, type_id):
            return (True, "凡晶石处理技术") if type_id == 34 else (False, "")

        def calc_value(self, type_id, quantity=1, **kwargs):
            if type_id != 34:
                return {"output": [], "total_value": 0.0}
            assert kwargs["ore_skill"] == 4, "矿石专精等级必须从人物技能表里取"
            return {"output": [{"name": "三钛合金"}], "total_value": 123.0 * quantity}

    monkeypatch.setattr(eb, "get_container", lambda: type("C", (), {"refining_service": _FakeRefining()})())
    monkeypatch.setattr(eb, "resolve_char_config", lambda **kw: {"skills": {"凡晶石处理技术": 4}})

    b = _bridge_with_rows()
    b._rebuild_refine_values()

    assert b._model._rows[0]["refine_value"] == pytest.approx(123.0 * 100)
    assert b._model._rows[1]["refine_value"] is None
    assert b._model.data(b._model.index(0, 7)) == "12,300.00"
    assert b._model.data(b._model.index(1, 7)) == "—"


def test_summary_matches_widgets_formulas(qapp):
    """总体积/卖价/买价/均价与 Widgets 版 `_refresh_summary` 同公式。"""
    b = _bridge_with_rows()
    # 体积 = 100*0.01 + 200*0.02 = 1 + 4 = 5
    # 卖价 = 100*5 + 200*2 = 900 ；买价 = 100*4 + 200*1 = 600 ；均价 = 750
    assert b.summary["volume"] == "5.0 m³"
    assert b.summary["sell"] == "900 ISK"
    assert b.summary["buy"] == "600 ISK"
    assert b.summary["avg"] == "750 ISK"
    assert b.summary["rowCount"] == 2


def test_unit_price_follows_sell_price(qapp):
    """单价固定取卖价（买/卖的选择由底部两个「…到剪贴板」按钮承担）。"""
    b = _bridge_with_rows()
    assert b._model._rows[0]["unit_price"] == pytest.approx(5.0)
    b.discount = 2.0
    assert b._model._rows[0]["unit_price"] == pytest.approx(10.0)


def test_discount_applies_to_totals(qapp):
    b = _bridge_with_rows()
    b.discount = 0.5
    assert b._model._rows[0]["sell_total"] == pytest.approx(250.0)
    assert b.summary["sell"] == "450 ISK"


def test_set_and_multiply_qty(qapp):
    b = _bridge_with_rows()
    b.setQty(0, 10)
    assert b._model._rows[0]["qty"] == 10
    assert b._model._rows[0]["sell_total"] == pytest.approx(50.0)

    b.multiplyQty(0, 3)
    assert b._model._rows[0]["qty"] == 30

    b.setQty(0, 0)  # 非法数量应被忽略
    assert b._model._rows[0]["qty"] == 30


def test_remove_and_clear(qapp):
    b = _bridge_with_rows()
    b.removeRow(0)
    assert b.summary["rowCount"] == 1
    assert b._model._rows[0]["name"] == "Pyerite"

    b.clearAll()
    assert b.summary["rowCount"] == 0
    assert b.summary["avg"] == "0 ISK"


def test_row_at_and_blueprint_roundtrip(qapp):
    b = _bridge_with_rows()
    info = b.rowAt(0)
    assert info["name"] == "Tritanium"
    assert info["typeId"] == 34

    b.setBlueprint(0, 8, 12)
    bp = b.blueprintOf(0)
    assert (bp["me"], bp["te"]) == (8, 12)
    assert bp["name"] == "Tritanium"


def test_row_at_out_of_range_is_empty(qapp):
    b = _bridge_with_rows()
    assert b.rowAt(99) == {}
    assert b.blueprintOf(-1) == {"me": 0, "te": 0, "name": ""}


def test_summary_changes_emit_signal(qapp):
    b = _bridge_with_rows()
    fired: list[int] = []
    b.summaryChanged.connect(lambda: fired.append(1))
    b.setQty(0, 7)
    assert fired, "改数量未触发 summaryChanged，QML 底部汇总不会更新"


def test_busy_property_toggles(qapp):
    b = EstimateBridge()
    seen: list[bool] = []
    b.busyChanged.connect(lambda: seen.append(b.busy))
    b._set_busy(True)
    b._set_busy(False)
    assert seen == [True, False]


# ════════════════════════════════════════════════════════════
#  页面层：行点击命中固定在按下那一刻
# ════════════════════════════════════════════════════════════


@pytest.fixture
def estimate_page(qapp):
    from ui_qml.bridge.estimate_bridge import EstimateBridge
    from ui_qml.host import PageHost

    bridge = EstimateBridge()
    bridge._model.set_rows(
        [
            {
                "type_id": 34 + i,
                "name": f"物品{i}",
                "qty": 100 + i,
                "unit_price": 5.0,
                "sell_total": 600.0,
                "buy_total": 550.0,
                "volume": 0.01,
            }
            for i in range(50)
        ]
    )
    host = PageHost("pages/EstimatePage.qml", context={"bridge": bridge})
    yield host, bridge
    host.deleteLater()


@pytest.mark.ui
def test_row_click_survives_content_move(estimate_page):
    """行点击命中固定在按下那一刻（见 `FTableClickArea` 的说明）。

    回归背景：delegate 里的 `TapHandler` 在**释放**时判定命中，内容一移动
    （甩动/惯性沉降）就整次丢掉点击 —— 界面表现是「单击不到所对应的行上」。
    """
    host, _bridge = estimate_page
    root = host.rootObject()
    press_move_release(
        host, root, area_name="estimateClickArea", row=3, read_current=lambda: root.property("selectedRow"), delta=1
    )
