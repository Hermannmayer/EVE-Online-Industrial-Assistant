"""价格监控页（阶段 3）的契约测试。

分三层（与 `test_qml_query.py` / `test_qml_trade.py` 同构）：
  - **纯函数层**（`fast`）：`WatchlistQmlModel` 的角色与三层行底色规则；
  - **桥层**（`ui`）：`WatchlistBridge` 的增删改与状态栏文案（DB 调用全部打桩）；
  - **页面层**（`ui`）：`WatchlistPage.qml` 能加载、无 QML 告警。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer, QtMsgType, qInstallMessageHandler

from tests.qml_click import press_move_release
from ui_qml.models.watchlist_qml_model import ROLE_NAMES, WatchlistQmlModel

_BASE = Qt.ItemDataRole.UserRole
_TEXT = _BASE + 1
_FG = _BASE + 2
_BG = _BASE + 3
_ALIGN_RIGHT = _BASE + 5
_MONO = _BASE + 6
_WATCH_ID = _BASE + 8
_ITEM_NAME = _BASE + 9


def _row(
    wid: int = 1,
    tid: int = 34,
    zh: str = "三钛合金",
    buy: float | None = 5.0,
    sell: float | None = 6.0,
    buy_threshold: float | None = None,
    sell_threshold: float | None = None,
    note: str = "",
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
    }


def _cell(model: WatchlistQmlModel, row: int, col: int, role: int):
    return model.data(model.index(row, col), role)


def _spin(ms: int = 120) -> None:
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
#  桥
# ════════════════════════════════════════════════════════════


@pytest.fixture
def bridge(qapp, monkeypatch):
    """桥会真的读关注列表与建表，这里把 DB 层全部打桩。"""
    import services.watchlist_manager as wm

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
    from ui_qml.bridge.watchlist_bridge import WatchlistBridge
    from ui_qml.host import PageHost

    monkeypatch.setattr(wm, "init_db", lambda: None)
    monkeypatch.setattr(wm, "get_watchlist", lambda: [])

    b = WatchlistBridge(None)
    host = PageHost("pages/WatchlistPage.qml", context={"bridge": b})
    yield host, b
    host.deleteLater()
    _spin(60)


@pytest.mark.ui
def test_page_loads_and_exposes_the_bridge(watch_page):
    host, bridge = watch_page
    assert host.ok(), "; ".join(str(e) for e in host.errors())
    root = host.rootObject()
    assert root is not None
    assert root.property("watch") is bridge
    assert root.property("currentRow") == -1


@pytest.mark.ui
def test_page_loads_without_qml_warnings(watch_page):
    """加载 + 布局不给 Qt 刷告警。

    这页真实踩过：`MultiEffect` 忘了 `import QtQuick.Effects` → QML 加载失败 →
    静默回退 Widgets 版（外观与主题全不对，但应用照常起得来）。
    """
    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            else None
        )
    )
    try:
        host, _bridge = watch_page
        root = host.rootObject()
        root.setProperty("width", 1280)
        root.setProperty("height", 720)
        _spin(300)
    finally:
        qInstallMessageHandler(previous)

    assert not caught, "QML 产生了告警：\n" + "\n".join(dict.fromkeys(caught))


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
