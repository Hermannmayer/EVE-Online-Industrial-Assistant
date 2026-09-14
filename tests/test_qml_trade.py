"""贸易页（阶段 3）的契约测试。

分三层（与 `tests/test_qml_query.py` 同构）：
  - **纯函数层**（`fast`）：`TradeHubQmlModel` 的命名角色与展示规则；
  - **桥层**（`ui`）：`TradeBridge` 的状态机与结果整形（用合成 payload 直接喂
    `_on_*` 处理器，不依赖 DB / 网络）；
  - **页面层**（`ui`）：`TradePage.qml` 能加载、无 QML 告警。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer, QtMsgType, qInstallMessageHandler

from ui_qml.models.trade_qml_model import ROLE_NAMES, TradeHubQmlModel

_BASE = Qt.ItemDataRole.UserRole
_TEXT = _BASE + 1
_FG = _BASE + 2
_ICON_URL = _BASE + 3
_ALIGN_RIGHT = _BASE + 4
_HUB = _BASE + 6


def _hub_row(
    hub: str = "Jita",
    buy: float = 100.0,
    sell: float = 130.0,
    spread_pct: float = 30.0,
    tid: int = 34,
) -> dict:
    return {
        "hub": hub,
        "type_id": tid,
        "buy_price": buy,
        "sell_price": sell,
        "spread": sell - buy,
        "spread_pct": spread_pct,
        "volume": 1000,
    }


def _cell(model: TradeHubQmlModel, row: int, col: int, role: int):
    return model.data(model.index(row, col), role)


def _spin(ms: int = 150) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


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
    model = TradeHubQmlModel([_hub_row()])
    for col in range(model.columnCount()):
        for role in ROLE_NAMES:
            model.data(model.index(0, col), role)


@pytest.mark.fast
def test_text_matches_the_widgets_columns():
    model = TradeHubQmlModel([_hub_row()])
    assert _cell(model, 0, 0, _TEXT) == "Jita"
    assert _cell(model, 0, 1, _TEXT) == "100.00"
    assert _cell(model, 0, 2, _TEXT) == "130.00"
    assert _cell(model, 0, 3, _TEXT) == "30.00"
    assert _cell(model, 0, 4, _TEXT) == "30.0%"
    assert _cell(model, 0, 5, _TEXT) == "1,000"


@pytest.mark.fast
def test_hub_column_is_left_aligned_the_rest_right():
    model = TradeHubQmlModel([_hub_row()])
    assert _cell(model, 0, 0, _ALIGN_RIGHT) is False
    for col in range(1, model.columnCount()):
        assert _cell(model, 0, col, _ALIGN_RIGHT) is True


@pytest.mark.fast
def test_spread_pct_is_coloured_by_sign():
    positive = TradeHubQmlModel([_hub_row(spread_pct=12.0)])
    negative = TradeHubQmlModel([_hub_row(spread_pct=-3.0)])
    flat = TradeHubQmlModel([_hub_row(spread_pct=0.0)])

    assert _cell(positive, 0, 4, _FG)
    assert _cell(negative, 0, 4, _FG)
    assert _cell(positive, 0, 4, _FG) != _cell(negative, 0, 4, _FG)
    assert _cell(flat, 0, 4, _FG) == ""
    # 只有价差% 列染色
    assert _cell(positive, 0, 1, _FG) == ""


@pytest.mark.fast
def test_hub_role_and_icon_column():
    model = TradeHubQmlModel([_hub_row(hub="Amarr")])
    assert _cell(model, 0, 0, _HUB) == "Amarr"
    assert _cell(model, 0, 0, _ICON_URL) == "" or _cell(model, 0, 0, _ICON_URL).startswith("file:")
    assert _cell(model, 0, 3, _ICON_URL) == ""  # 非首列不给图标


@pytest.mark.fast
def test_set_rows_replaces_content():
    model = TradeHubQmlModel([_hub_row(hub="Jita")])
    model.set_rows([_hub_row(hub="Rens"), _hub_row(hub="Hek")])
    assert model.rowCount() == 2
    assert _cell(model, 0, 0, _TEXT) == "Rens"
    model.set_rows([])
    assert model.rowCount() == 0


# ════════════════════════════════════════════════════════════
#  桥：Tab 1（跨区域价差 / 评分）
# ════════════════════════════════════════════════════════════


@pytest.fixture
def bridge(qapp):
    from ui_qml.bridge.trade_bridge import TradeBridge

    return TradeBridge(None)


@pytest.mark.ui
def test_hubs_and_modes_come_from_shared_sources(bridge):
    from core.constants import TRADE_HUB_IDS

    assert bridge.hubs == list(TRADE_HUB_IDS.keys())
    assert bridge.modes == ["公开货运", "自有运输"]
    assert len(bridge.hubColumns) == 6
    assert [c["title"] for c in bridge.hubColumns][0] == "贸易中心"


@pytest.mark.ui
def test_defaults_match_the_widgets_version(bridge):
    """初始买卖区域 Jita→Amarr、数量 1、评分卡片隐藏（对齐 trade_view）。"""
    assert bridge.hubs[bridge.buyHubIndex] == "Jita"
    assert bridge.hubs[bridge.sellHubIndex] == "Amarr"
    assert bridge.quantity == 1
    assert bridge.scoreVisible is False
    assert bridge.pairVisible is False
    assert bridge.transportQuantity == 100
    assert bridge.transportModeIndex == 0


@pytest.mark.ui
def test_cross_region_result_fills_table_and_switches_to_best_pair(bridge):
    """跨区域结果：填表、算出最大价差、把买卖区域切到最优对、显示评分卡片。"""
    bridge._selected_tid = 34
    bridge._selected_name = "三钛合金"
    rows = [
        _hub_row("Jita", buy=100.0, sell=110.0),
        _hub_row("Amarr", buy=90.0, sell=200.0),
        _hub_row("Rens", buy=95.0, sell=120.0),
        _hub_row("Hek", buy=80.0, sell=85.0),
    ]

    bridge._on_cross_region_result(rows)

    assert bridge.hubModel.rowCount() == 4
    assert "4/4" in bridge.hubStatus
    assert bridge.scoreVisible is True
    # 最优对：Hek 买(80) → Amarr 卖(200)，差 120（比 Rens 95→200 的 105 大）
    assert bridge.hubs[bridge.buyHubIndex] == "Hek"
    assert bridge.hubs[bridge.sellHubIndex] == "Amarr"


@pytest.mark.ui
def test_empty_cross_region_result_clears_the_table(bridge):
    bridge._selected_tid = 34
    bridge._selected_name = "三钛合金"
    bridge._on_cross_region_result([])
    assert bridge.hubModel.rowCount() == 0
    assert "无价格数据" in bridge.previewText


@pytest.mark.ui
def test_score_result_builds_the_field_list(bridge):
    """评分卡片：6 项、分值与利润按阈值取色、负数利润标红。"""
    bridge._selected_tid = 34
    bridge._selected_name = "三钛合金"
    bridge._on_score_result(
        {
            "score": 72,
            "buy_cost": 1_000_000,
            "sell_revenue": 1_500_000,
            "gross_profit": 500_000,
            "margin_pct": 50.0,
            "profit_per_m3": 12_345,
        }
    )

    labels = [f["label"] for f in bridge.scoreFields]
    assert labels[0] == "贸易评分:"
    assert len(bridge.scoreFields) == 6
    assert bridge.scoreFields[0]["value"] == "72/100"
    assert bridge.scoreFields[0]["strong"] is True
    assert "500,000" in bridge.scoreFields[3]["value"]
    assert "评分: 72" in bridge.previewText

    bridge._on_score_result({"score": 10, "gross_profit": -1, "margin_pct": -1})
    assert bridge.scoreFields[3]["color"] == bridge.scoreFields[4]["color"]


@pytest.mark.ui
def test_score_result_with_status_keeps_the_card_untouched(bridge):
    bridge._selected_tid = 34
    bridge._selected_name = "三钛合金"
    bridge._on_score_result({"status": "无价格数据"})
    assert bridge.scoreFields == []
    assert "无价格数据" in bridge.previewText


@pytest.mark.ui
def test_trade_pair_prefers_the_widest_spread_and_scales_by_quantity(bridge):
    bridge._selected_tid = 34
    bridge._selected_name = "三钛合金"
    bridge._hub_rows = [
        _hub_row("Jita", buy=100.0, sell=110.0),
        _hub_row("Amarr", buy=90.0, sell=200.0),
    ]
    bridge.setQuantity(10)
    bridge._update_trade_pair()

    assert bridge.pairVisible is True
    assert "Amarr" in bridge.pairText and "Jita" in bridge.pairText
    assert "1,000" in bridge.pairText  # (200 − 100) × 10 件


@pytest.mark.ui
def test_quantity_is_clamped(bridge):
    bridge.setQuantity(0)
    assert bridge.quantity == 1
    bridge.setQuantity(10_000_000)
    assert bridge.quantity == 1_000_000


# ════════════════════════════════════════════════════════════
#  桥：Tab 2（运输）
# ════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_transport_jumps_are_auto_filled_on_hub_change(bridge, monkeypatch):
    """切买卖区域 → 自动查跳跃数并标「自动」；手动改过就不再标。"""
    monkeypatch.setattr("services.logistics.get_distance_jumps", lambda src, dst: 12)
    bridge.setTransportBuyHubIndex(bridge.hubs.index("Rens"))
    assert bridge.transportJumps == 12
    assert bridge.transportJumpsAuto is True

    bridge.setTransportJumps(7)
    assert bridge.transportJumps == 7
    assert bridge.transportJumpsAuto is False


@pytest.mark.ui
def test_transport_jumps_fall_back_when_no_route_is_known(bridge, monkeypatch):
    """查不到跳跃数时保留原值，并去掉「自动」标记（不静默改用户看到的数）。"""
    monkeypatch.setattr("services.logistics.get_distance_jumps", lambda src, dst: None)
    before = bridge.transportJumps
    bridge.setTransportBuyHubIndex(bridge.hubs.index("Hek"))
    assert bridge.transportJumps == before
    assert bridge.transportJumpsAuto is False


@pytest.mark.ui
def test_transport_result_builds_the_field_list(bridge):
    bridge._t_selected_tid = 34
    bridge._t_selected_name = "三钛合金"
    bridge._on_transport_result(
        {
            "buy_cost": 1_000_000,
            "sell_revenue": 2_000_000,
            "freight_cost": 100_000,
            "broker_cost": 30_000,
            "sales_tax": 20_000,
            "net_profit": 850_000,
            "margin_pct": 42.5,
            "isk_per_m3": 5_000,
            "freight_mode": "public_freight",
        }
    )

    assert bridge.transportResultVisible is True
    labels = [f["label"] for f in bridge.transportFields]
    assert labels == ["买入成本:", "卖出收入:", "运费:", "经纪人费:", "销售税:", "净利润:", "利润率:", "每m³利润:"]
    assert "公开货运" in bridge.transportPreview
    assert "42.5%" in bridge.transportPreview


@pytest.mark.ui
def test_transport_analyze_without_selection_only_updates_preview(bridge):
    bridge.analyzeTransport()
    assert "请先搜索并选择一个物品" in bridge.transportPreview
    assert bridge.transportResultVisible is False


# ════════════════════════════════════════════════════════════
#  页面层
# ════════════════════════════════════════════════════════════


@pytest.fixture
def trade_page(qapp):
    from ui_qml.bridge.trade_bridge import TradeBridge
    from ui_qml.host import PageHost

    b = TradeBridge(None)
    host = PageHost("pages/TradePage.qml", context={"bridge": b})
    yield host, b
    host.deleteLater()
    _spin(60)


@pytest.mark.ui
def test_page_loads_and_exposes_the_bridge(trade_page):
    host, bridge = trade_page
    assert host.ok(), "; ".join(str(e) for e in host.errors())
    root = host.rootObject()
    assert root is not None
    assert root.property("trade") is bridge


@pytest.mark.ui
def test_page_loads_without_qml_warnings(trade_page):
    """加载 + 布局不给 Qt 刷告警（textRole 指向不存在的角色 / 位置绑定用 mapToItem
    这两类都真实出现过，且运行期只表现为「界面不对」）。"""
    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            else None
        )
    )
    try:
        host, _bridge = trade_page
        root = host.rootObject()
        root.setProperty("width", 1280)
        root.setProperty("height", 720)
        _spin(300)
    finally:
        qInstallMessageHandler(previous)

    assert not caught, "QML 产生了告警：\n" + "\n".join(dict.fromkeys(caught))
