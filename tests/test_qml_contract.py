"""合同页（三个页签）的桥与页面契约测试。

分两层：
  - **桥层**（`ui`）：页签切换绑到正确的模型、忙碌互斥守卫、跳数口径只在选中后才算
  - **页面层**（`ui`）：`ContractPage.qml` 能加载、无 QML 告警

`ContractPage` 的 `Component.onCompleted` 会真的发起一次查库（刻意如此 —— 旧版没有
初次加载入口，第一次打开永远是空表且不报错）。测试里把三个加载入口换成返回空的桩，
让 worker 毫秒级结束，避免后台线程拖过用例结束。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtTest import QTest

from tests.qml_click import press_move_release
from tests.qml_click import spin as _spin
from tests.qml_page_load import assert_page_loads_quietly, page_host
from ui_qml.bridge.contract_bridge import ContractBridge

pytestmark = pytest.mark.ui


@pytest.fixture
def no_db(monkeypatch):
    """三个页签的加载入口都返回空 —— 本文件测接线，SQL 有专门的文件覆盖。"""
    for name in ("load_auction_contracts", "load_exchange_contracts", "load_courier_contracts"):
        monkeypatch.setattr(f"services.contract_service.{name}", lambda *a, **kw: [])


@pytest.fixture
def contract_page(qapp, no_db):
    with page_host("pages/ContractPage.qml", ContractBridge(None)) as pair:
        yield pair


# ════════════════════════════════════════════════════════════
#  页面层
# ════════════════════════════════════════════════════════════


def test_page_loads_and_is_quiet(contract_page):
    """能加载 + 桥到位 + 不给 Qt 刷告警（共用实现见 `tests/qml_page_load.py`）。

    三个页签是 `ContractPage` 的从属组件，页面能静默加载即覆盖它们的加载路径。
    """
    host, bridge = contract_page
    assert_page_loads_quietly(host, bridge, key="contract", size=(1280, 720))


def test_three_tab_models_are_wired(contract_page):
    """三个页签各绑一个模型 —— 这是「拆成三个子页」的最小可观察事实。"""
    _host, bridge = contract_page
    models = {bridge.auctionModel, bridge.exchangeModel, bridge.courierModel}
    assert len(models) == 3
    assert bridge.auctionColumns and bridge.exchangeColumns and bridge.courierColumns


def test_row_click_survives_content_move(contract_page):
    """行点击命中固定在按下那一刻（见 `FTableClickArea` 的说明）。

    回归背景：delegate 里的 `TapHandler` 配 `ReleaseWithinBounds` 在**释放**时判定
    命中，内容一移动（甩动/惯性沉降）就整次丢掉点击 —— 界面表现是
    「单击不到所对应的行上」。
    """
    host, bridge = contract_page
    bridge.auctionModel.set_rows([{"contract_id": i + 1, "title": f"合同{i}"} for i in range(50)])
    _spin(150)

    root = host.rootObject()
    pane = root.findChild(QObject, "contractTabPane_auction")
    assert pane is not None, "找不到拍卖页签主体"

    press_move_release(
        host,
        root,
        area_name="contractClickArea_auction",
        row=3,
        read_current=lambda: pane.property("currentRow"),
        delta=1,
    )


def test_header_click_sorts_the_table(contract_page):
    """点表头按该列排序，再点一次反向。

    模型早就有 `sort()` 与 `_SORT_KEYS`，缺的一直是**表头没接上** —— 用户看到的是
    「表格不能排序」。这条用例盯的就是那根接线（含「首次点金额列给降序」的约定）。
    """
    host, bridge = contract_page
    bridge.auctionModel.set_rows(
        [
            {"contract_id": 1, "price_diff": 100.0},
            {"contract_id": 2, "price_diff": 900.0},
            {"contract_id": 3, "price_diff": 500.0},
        ]
    )
    _spin(150)

    host.resize(1200, 800)
    host.show()
    _spin(250)

    root = host.rootObject()
    header = root.findChild(QObject, "contractHeader_auction")
    assert header is not None, "找不到拍卖表头"

    # 「价差」是第 6 列（列宽取桥下发的那份，表头与表体同源）
    columns = bridge.auctionColumns
    offset = header.mapToItem(root, sum(c["width"] for c in columns[:6]) + columns[6]["width"] / 2, header.height() / 2)
    point = QPoint(int(offset.x()), int(offset.y()))

    def click_header() -> None:
        QTest.mouseClick(host, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        _spin(150)

    click_header()
    assert bridge.sortColumn == 6, "点了表头却没排到那一列"
    assert bridge.sortAscending is False, "金额列首次点击该给降序（先看赚得多的）"
    assert [r["price_diff"] for r in bridge.auctionModel._rows] == [900.0, 500.0, 100.0]

    click_header()
    assert bridge.sortAscending is True, "同一列再点一次该反向"
    assert [r["price_diff"] for r in bridge.auctionModel._rows] == [100.0, 500.0, 900.0]


# ════════════════════════════════════════════════════════════
#  桥层
# ════════════════════════════════════════════════════════════


def test_tab_switch_reloads_that_tab(no_db, monkeypatch):
    """切页签要按**该页签**的口径重新查库，不是复用上一张表的数据。"""
    bridge = ContractBridge(None)
    seen: list[dict] = []
    monkeypatch.setattr(bridge, "loadTab", lambda: seen.append({"tab": bridge._tab_key}))

    bridge.setTabIndex(2)
    assert seen == [{"tab": "courier"}]
    assert bridge.tabIndex == 2


def test_busy_guard_blocks_second_job(no_db):
    """拉取与补齐都写 market.db（SQLite 单写者）—— 同一时刻只能跑一个。"""
    bridge = ContractBridge(None)
    sentinel = object()
    bridge._busy_worker = sentinel  # type: ignore[assignment]

    import ui_qml.workers.contract_workers as cw

    started: list[str] = []
    monkeypatch_cls = cw.ContractFetchWorker

    class _Spy(monkeypatch_cls):  # type: ignore[misc,valid-type]
        def start(self):  # 不真起线程
            started.append("started")

    cw.ContractFetchWorker = _Spy  # type: ignore[misc]
    try:
        bridge.refresh()
    finally:
        cw.ContractFetchWorker = monkeypatch_cls  # type: ignore[misc]

    assert started == []
    assert "已有拉取任务在跑" in bridge.statusText


def test_jump_mode_only_computes_after_choice(monkeypatch):
    """跳数「选了口径才算」—— 默认那一档传下去的是 `none`，选了才换成对应口径。

    查库是同步的，所以直接盯 service 入口收到的实参。
    """
    captured: list[dict] = []

    def _spy(region_id, jump_mode="none", min_security=None, filters=None, limit=None):
        captured.append({"jump_mode": jump_mode, "min_security": min_security})
        return []

    monkeypatch.setattr("services.contract_service.load_courier_contracts", _spy)
    bridge = ContractBridge(None)

    bridge.setTabIndex(2)  # → 运输，触发一次 loadTab
    assert bridge.tabIndex == 2
    assert captured[-1]["jump_mode"] == "none"

    bridge.setJumpModeIndex(2)  # 避开低安
    assert captured[-1]["jump_mode"] == "highsec"

    bridge.setJumpModeIndex(1)  # 最短路线
    assert captured[-1]["jump_mode"] == "shortest"


def test_courier_tab_has_no_fill(no_db):
    """运输合同没有物品详情（items 端点实测 HTTP 400）—— 补齐按钮对它应当无效。"""
    bridge = ContractBridge(None)
    bridge._tab_index = 2
    bridge.startFill()
    assert "没有物品详情" in bridge.statusText
