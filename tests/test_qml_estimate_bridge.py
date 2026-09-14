"""EstimateBridge 契约测试 —— QML 页面后端的行为对齐。

对照 `ui_pyside6/views/estimate_view.py`：bridge 只做转发与整形，
但**转发得对不对**必须锁住，否则 QML 版的数字会和 Widgets 版对不上。
"""

from __future__ import annotations

import pytest

from tests.qml_click import press_move_release
from ui_qml.bridge.estimate_bridge import EstimateBridge

pytestmark = pytest.mark.ui


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
    """下拉选项与 Widgets 版硬编码的中文必须一致，否则用户会看到两套词。"""
    b = EstimateBridge()
    assert b.priceTypes == ["卖价", "买价", "均价"]
    assert b.refineModes == ["人物", "设施"]
    assert b.skillPresets == ["技能全5", "当前人物", "技能全0"]
    assert "Jita" in b.hubs


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


def test_price_type_switches_unit_price(qapp):
    b = _bridge_with_rows()

    b.priceType = "buy"
    assert b.priceType == "buy"
    assert b._model._rows[0]["unit_price"] == pytest.approx(4.0)

    b.priceType = "avg"
    assert b._model._rows[0]["unit_price"] == pytest.approx(4.5)

    b.priceType = "sell"
    assert b._model._rows[0]["unit_price"] == pytest.approx(5.0)


def test_price_type_rejects_unknown_value(qapp):
    """非法值必须被忽略，否则 QML 传错字符串会让单价算成 0。"""
    b = _bridge_with_rows()
    b.priceType = "nonsense"
    assert b.priceType == "sell"


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
