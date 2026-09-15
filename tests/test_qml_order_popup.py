"""订单弹窗（阶段 4b）的业务契约测试。

三层：
  - **纯函数层**：行构造与标题文案，逐字对齐 Widgets 版 `OrderPopup.set_orders`；
  - **桥层**：`set_orders` 把买单/卖单整形进两张表（空表不塞占位行）；
  - **链路层**：右上角「走势图」确实弹出价格走势图 —— 三级链
    `QueryPage.qml → query_bridge → OrderPopupQmlDialog → PriceChartQmlDialog`
    的最后一段，把价格表换回 Widgets 版就等于没迁。

「QML 是否加载成功 / 有无告警」那两条由 `tests/test_qml_dialogs.py` 统一管。
"""

from __future__ import annotations

import pytest

import ui_pyside6.theme as theme
from ui_qml.bridge.order_popup_bridge import (
    OrderPopupBridge,
    order_rows,
    popup_title,
)

pytestmark = pytest.mark.ui

_STATION = 60003760
_NAME = "三钛合金"


def _order(price: float = 5.25, volume: int = 1234, location: int = _STATION) -> dict:
    return {"price": price, "volume_remain": volume, "location_id": location}


def _texts(row: dict) -> list[str]:
    return [str(c["text"]) for c in row["cells"]]


def _fake_chart_class(sink: list) -> type:
    """走势图替身：记录构造参数，`exec()` 不阻塞（真身会开模态窗口卡住测试）。"""

    class _FakeChart:
        def __init__(self, type_id: int, name: str, parent: object = None) -> None:
            sink.append((type_id, name, parent))

        def exec(self) -> int:
            return 0

    return _FakeChart


# ════════════════════════════════════════════════════════════
#  纯函数
# ════════════════════════════════════════════════════════════


class TestOrderRows:
    def test_formats_price_volume_and_station(self):
        rows = order_rows([_order()], "GREEN", {_STATION: "Jita IV - Moon 4"})
        assert _texts(rows[0]) == ["#1", "5.25", "1,234", "Jita IV - Moon 4 [60003760]"]

    def test_buy_rows_are_green_and_sell_rows_red(self):
        buy = order_rows([_order()], "GREEN", {})[0]
        sell = order_rows([_order()], "RED", {})[0]
        assert {c["color"] for c in buy["cells"]} == {theme.ACCENT_GREEN}
        assert {c["color"] for c in sell["cells"]} == {theme.ACCENT_RED}

    def test_falls_back_to_location_id_without_cached_name(self):
        # 名字缓存没命中时原版就退回 location_id，不显示空
        rows = order_rows([_order(location=60099999)], "GREEN", None)
        assert _texts(rows[0])[3] == "60099999 [60099999]"

    def test_numbering_starts_at_one(self):
        rows = order_rows([_order(), _order(), _order()], "GREEN", {})
        assert [_texts(r)[0] for r in rows] == ["#1", "#2", "#3"]

    def test_large_numbers_use_thousands_separator(self):
        rows = order_rows([_order(price=1234567.891, volume=9876543)], "GREEN", {})
        assert _texts(rows[0])[1:3] == ["1,234,567.89", "9,876,543"]

    def test_empty_input(self):
        assert order_rows([], "GREEN", {}) == []


def test_popup_title_matches_widgets_wording():
    assert popup_title(_NAME, 34) == "三钛合金 (Type ID: 34)"


# ════════════════════════════════════════════════════════════
#  桥
# ════════════════════════════════════════════════════════════


class TestOrderPopupBridge:
    def test_set_orders_fills_both_tables(self, qapp, monkeypatch):
        # 站点名缓存随批次 6.0 搬到 ui_qml.workers.order_workers（Widgets 版订单弹窗已删）
        from ui_qml.workers import order_workers

        monkeypatch.setitem(order_workers._station_name_cache, _STATION, "Jita IV - Moon 4")
        bridge = OrderPopupBridge()
        bridge.set_orders(34, _NAME, [_order()], [_order(price=6.5, volume=99)])

        assert bridge.title_text() == "三钛合金 (Type ID: 34)"
        assert _texts(bridge.buyRows[0]) == ["#1", "5.25", "1,234", "Jita IV - Moon 4 [60003760]"]
        assert _texts(bridge.sellRows[0]) == ["#1", "6.50", "99", "Jita IV - Moon 4 [60003760]"]

    def test_empty_orders_leave_empty_tables(self, qapp):
        """该物品没人挂单是常态 —— 空表交给 QML 的 emptyText，不塞占位行。"""
        bridge = OrderPopupBridge()
        bridge.set_orders(34, _NAME, [], [])
        assert bridge.buyRows == []
        assert bridge.sellRows == []
        assert [c["title"] for c in bridge.columns] == ["#", "价格 (ISK)", "数量", "空间站"]

    def test_no_chart_without_an_item(self, qapp, monkeypatch):
        import ui_qml.bridge.price_chart_bridge as pcb

        monkeypatch.setattr(pcb, "PriceChartQmlDialog", _fake_chart_class([]))
        OrderPopupBridge().openChart()  # 没 set_orders 过：不该弹任何东西


class TestChartChain:
    def test_chart_button_opens_the_same_item(self, qapp, monkeypatch):
        import ui_qml.bridge.price_chart_bridge as pcb

        opened: list = []
        monkeypatch.setattr(pcb, "PriceChartQmlDialog", _fake_chart_class(opened))

        bridge = OrderPopupBridge()
        bridge.set_orders(34, _NAME, [_order()], [])
        bridge.openChart()

        assert opened == [(34, _NAME, None)]

    def test_chart_parent_is_the_host_window(self, qapp, monkeypatch):
        """二级弹窗的 parent 必须走 `host_widget()`（宿主 QDialog）。

        自己存 `bridge.dialog = self` 会形成 Python↔C++ 环，GC 先没掉窗口就崩
        （见 `dialog_host.DialogBridge.host_widget`）。
        """
        from PySide6.QtWidgets import QWidget

        import ui_qml.bridge.price_chart_bridge as pcb

        opened: list = []
        monkeypatch.setattr(pcb, "PriceChartQmlDialog", _fake_chart_class(opened))

        host = QWidget()
        bridge = OrderPopupBridge()
        bridge.setParent(host)  # `QmlDialog.__init__` 就是这么挂的
        bridge.set_orders(34, _NAME, [], [])
        bridge.openChart()

        assert opened and opened[0][2] is host
        host.deleteLater()

    def test_open_chart_is_repeatable(self, qapp, monkeypatch):
        """`openChart` 只做转发：不碰网络、不碰 DB（取价是走势图那边的事），可反复点。"""
        import ui_qml.bridge.price_chart_bridge as pcb

        opened: list = []
        monkeypatch.setattr(pcb, "PriceChartQmlDialog", _fake_chart_class(opened))
        bridge = OrderPopupBridge()
        bridge.set_orders(34, _NAME, [], [])
        bridge.openChart()
        bridge.openChart()
        assert len(opened) == 2
