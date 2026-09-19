"""订单行构造（`order_popup_bridge.order_rows`）的契约测试。

这个纯函数原先服务「双击结果行弹出的订单弹窗」，**弹窗已删除** —— 现在它服务物品查询页
详情面板的「订单列表」（`QueryDetailBridge._render_orders`）。本文件守着它的逐格文案与配色；
表头在 `query_detail_bridge._ORDER_HEADS` 那一份。

「QML 是否加载成功 / 有无告警」由 `tests/test_qml_dialogs.py` 统一管。
"""

from __future__ import annotations

import pytest

import ui_qml.theme.registry as theme
from ui_qml.bridge.order_popup_bridge import order_rows

pytestmark = pytest.mark.ui

_STATION = 60003760


def _order(price: float = 5.25, volume: int = 1234, location: int = _STATION) -> dict:
    return {"price": price, "volume_remain": volume, "location_id": location}


def _texts(row: dict) -> list[str]:
    return [str(c["text"]) for c in row["cells"]]


class TestOrderRows:
    def test_formats_price_volume_and_station(self):
        """空间站列显示**站名**，不再跟一个多余的 ` [id]`。"""
        rows = order_rows([_order()], "GREEN", {_STATION: "Jita IV - Moon 4"})
        assert _texts(rows[0]) == ["#1", "5.25", "1,234", "Jita IV - Moon 4"]

    def test_buy_rows_are_green_and_sell_rows_red(self):
        buy = order_rows([_order()], "GREEN", {})[0]
        sell = order_rows([_order()], "RED", {})[0]
        assert {c["color"] for c in buy["cells"]} == {theme.ACCENT_GREEN}
        assert {c["color"] for c in sell["cells"]} == {theme.ACCENT_RED}

    def test_falls_back_to_location_id_without_a_station_name(self):
        # 站名解析不到（玩家建筑等）就退回 location_id，不显示空白
        rows = order_rows([_order(location=60099999)], "GREEN", None)
        assert _texts(rows[0])[3] == "60099999"

    def test_blank_cached_name_also_falls_back(self):
        # 缓存里存了空串也不该渲染成空白格
        rows = order_rows([_order()], "GREEN", {_STATION: ""})
        assert _texts(rows[0])[3] == "60003760"

    def test_numbering_starts_at_one(self):
        rows = order_rows([_order(), _order(), _order()], "GREEN", {})
        assert [_texts(r)[0] for r in rows] == ["#1", "#2", "#3"]

    def test_large_numbers_use_thousands_separator(self):
        rows = order_rows([_order(price=1234567.891, volume=9876543)], "GREEN", {})
        assert _texts(rows[0])[1:3] == ["1,234,567.89", "9,876,543"]

    def test_empty_input(self):
        assert order_rows([], "GREEN", {}) == []
