"""合同市场页（阶段 3）的契约测试。

分三层（与其余阶段 3 的页面测试同构）：
  - **纯函数层**（`fast`）：两张表的命名角色与展示规则；
  - **桥层**（`ui`）：客户端过滤（经 `ContractFilterProxy`）、代理行号→源行号映射、
    右键菜单动作（worker / 对话框都不触发）；
  - **页面层**（`ui`）：`ContractPage.qml` 能加载、无 QML 告警。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QtMsgType, qInstallMessageHandler

from tests.clipboard_wait import wait_for_clipboard
from tests.qml_click import press_move_release
from tests.qml_click import spin as _spin
from ui_qml.models.contract_qml_models import (
    CONTRACT_ROLE_NAMES,
    ContractItemQmlModel,
    ContractQmlModel,
)

_BASE = Qt.ItemDataRole.UserRole
_C_TEXT = _BASE + 1
_C_FG = _BASE + 2
_C_BG = _BASE + 3
_C_ALIGN = _BASE + 4
_C_MONO = _BASE + 5
_C_ID = _BASE + 7
_I_TEXT = _BASE + 1
_I_ALIGN = _BASE + 2


def _contract(
    cid: int = 1,
    ctype: str = "item_exchange",
    title: str = "三钛合金 100万",
    price: float = 1_000_000.0,
    collateral: float = 0.0,
    status: str = "outstanding",
) -> dict:
    return {
        "contract_id": cid,
        "type": ctype,
        "title": title,
        "price": price,
        "collateral": collateral,
        "volume": 100.0,
        "days_completed": 3,
        "status": status,
        "date_issued": "2026-01-01",
        "date_expired": "2026-02-01",
        "region_id": 10000002,
    }


def _c_cell(model: ContractQmlModel, row: int, col: int, role: int):
    return model.data(model.index(row, col), role)


# ════════════════════════════════════════════════════════════
#  模型
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_contract_role_names_are_unique_and_contiguous():
    keys = sorted(CONTRACT_ROLE_NAMES)
    assert keys[0] == Qt.ItemDataRole.UserRole + 1
    assert keys == list(range(keys[0], keys[0] + len(CONTRACT_ROLE_NAMES)))
    assert len(set(CONTRACT_ROLE_NAMES.values())) == len(CONTRACT_ROLE_NAMES)


@pytest.mark.fast
def test_contract_text_matches_the_widgets_columns():
    model = ContractQmlModel()
    model.set_rows([_contract()])
    assert _c_cell(model, 0, 0, _C_TEXT) == "1"
    assert _c_cell(model, 0, 1, _C_TEXT) == "物品交换"  # 类型走中文映射
    assert _c_cell(model, 0, 2, _C_TEXT) == "三钛合金 100万"
    assert _c_cell(model, 0, 3, _C_TEXT) == "1,000,000.00"
    assert _c_cell(model, 0, 5, _C_TEXT) == "100.0"
    assert _c_cell(model, 0, 6, _C_TEXT) == "3"
    assert _c_cell(model, 0, 7, _C_TEXT) == "进行中"  # 状态走中文映射


@pytest.mark.fast
def test_contract_price_and_status_colours():
    model = ContractQmlModel()
    model.set_rows([_contract(collateral=5.0)])
    assert _c_cell(model, 0, 3, _C_FG)  # 价格 → 绿
    assert _c_cell(model, 0, 4, _C_FG)  # 抵押 → 橙
    assert _c_cell(model, 0, 7, _C_FG)  # outstanding → 绿

    dead = ContractQmlModel()
    dead.set_rows([_contract(status="expired")])
    assert _c_cell(dead, 0, 7, _C_FG) != _c_cell(model, 0, 7, _C_FG)


@pytest.mark.fast
def test_contract_alignment_mono_and_background():
    model = ContractQmlModel()
    model.set_rows([_contract(), _contract(cid=2)])
    for col in range(model.columnCount()):
        expected = col in (0, 3, 4, 5, 6)
        assert _c_cell(model, 0, col, _C_ALIGN) is expected
        assert _c_cell(model, 0, col, _C_MONO) is expected
    assert _c_cell(model, 0, 1, _C_BG) != _c_cell(model, 1, 1, _C_BG)
    assert _c_cell(model, 0, 0, _C_ID) == 1


@pytest.mark.fast
def test_item_model_roles():
    model = ContractItemQmlModel()
    model.set_rows(
        [
            {
                "type_id": 34,
                "zh_name": "三钛合金",
                "en_name": "Tritanium",
                "quantity": 100,
                "is_blueprint_copy": False,
                "is_included": True,
                "material_efficiency": 10,
                "time_efficiency": 20,
            }
        ]
    )
    assert model.columnCount() == 8
    assert model.data(model.index(0, 0), _I_TEXT) == "34"
    assert model.data(model.index(0, 1), _I_TEXT) == "三钛合金"
    assert model.data(model.index(0, 3), _I_TEXT) == "100"
    assert model.data(model.index(0, 4), _I_TEXT) == "否"
    assert model.data(model.index(0, 6), _I_TEXT) == "10"
    # 物品 ID / 数量 / ME / PE 右对齐
    for col in range(model.columnCount()):
        assert model.data(model.index(0, col), _I_ALIGN) is (col in (0, 3, 6, 7))

    empty = ContractItemQmlModel()
    empty.set_rows([])
    assert empty.columnCount() == 8


# ════════════════════════════════════════════════════════════
#  桥
# ════════════════════════════════════════════════════════════


@pytest.fixture
def bridge(qapp):
    from ui_qml.bridge.contract_bridge import ContractBridge

    return ContractBridge(None)


@pytest.mark.ui
def test_defaults_and_option_sources(bridge):
    from core.constants import TRADE_HUBS
    from ui_qml.models.contract_models import _CONTRACT_COLUMNS, _ITEM_COLUMNS

    assert bridge.regions == list(TRADE_HUBS)
    assert bridge.types == ["全部", "物品交换", "拍卖", "运输"]
    assert bridge.buySellOptions == ["全部", "我要买", "我要卖"]
    assert [c["title"] for c in bridge.contractColumns] == [t for t, _ in _CONTRACT_COLUMNS]
    assert [c["title"] for c in bridge.itemColumns] == [t for t, _ in _ITEM_COLUMNS]


@pytest.mark.ui
def test_client_filters_go_through_the_proxy(bridge):
    """搜索/价格/买卖三个过滤条件都交给 `ContractFilterProxy`，桥只转发。"""
    bridge._on_contracts_loaded(
        [
            _contract(cid=1, title="三钛合金", price=1_000.0),
            _contract(cid=2, title="渡鸦级", price=5_000_000.0, ctype="auction"),
            _contract(cid=3, title="三钛合金 大包", price=9_000_000.0),
        ]
    )
    assert bridge.model.rowCount() == 3

    # 标题搜索
    bridge.setSearchText("三钛")
    assert bridge.model.rowCount() == 2
    assert bridge.countText == "合同: 2/3 条"

    # 价格下限
    bridge.setSearchText("")
    bridge.setPriceMin(5_000_000.0)
    assert bridge.model.rowCount() == 2

    # 买卖类型：我要买 = item_exchange + auction
    bridge.setPriceMin(0.0)
    bridge.setBuySellIndex(2)  # 我要卖
    assert bridge.model.rowCount() == 2  # 两条 item_exchange

    bridge.setBuySellIndex(0)
    assert bridge.model.rowCount() == 3


@pytest.mark.ui
def test_proxy_row_maps_to_source_row(bridge):
    """过滤后代理行号 ≠ 源行号，取值必须经 mapToSource。"""
    bridge._on_contracts_loaded(
        [
            _contract(cid=1, title="A", price=1_000.0),
            _contract(cid=2, title="B", price=5_000_000.0),
            _contract(cid=3, title="C", price=9_000_000.0),
        ]
    )
    bridge.setPriceMin(5_000_000.0)  # 只剩 cid=2、cid=3
    assert bridge.model.rowCount() == 2
    assert bridge.menuState(0)["contractId"] == 2
    assert bridge.menuState(1)["contractId"] == 3


@pytest.mark.ui
def test_menu_state_reports_validity(bridge):
    bridge._on_contracts_loaded([_contract(cid=7)])
    state = bridge.menuState(0)
    assert state["valid"] is True
    assert state["contractId"] == 7
    assert state["hasItems"] is False
    assert bridge.menuState(9)["valid"] is False


@pytest.mark.ui
def test_copy_contract_id(bridge, qapp):

    bridge._on_contracts_loaded([_contract(cid=42)])
    bridge.copyContractId(0)
    assert wait_for_clipboard("42") == "42"


@pytest.mark.ui
def test_item_actions_need_loaded_items(bridge):
    """没点过合同（物品表为空）时只给提示，不做任何复制。"""
    bridge._on_contracts_loaded([_contract()])
    assert bridge.hasItems() is False
    assert bridge.itemSummary() == ""
    bridge.copyItems()
    assert "请先点击合同加载物品列表" in bridge.countText
    bridge.addItemsToWatchlist()
    assert "请先点击合同加载物品列表" in bridge.countText


@pytest.mark.ui
def test_item_summary_lists_loaded_items(bridge):
    bridge._item_model.set_rows(
        [
            {"type_id": 34, "zh_name": "三钛合金", "en_name": "Tritanium", "quantity": 100},
            {"type_id": 35, "zh_name": "", "en_name": "Pyerite", "quantity": 5},
        ]
    )
    assert bridge.hasItems() is True
    summary = bridge.itemSummary()
    assert "三钛合金  x100" in summary
    assert "Pyerite  x5" in summary


# ════════════════════════════════════════════════════════════
#  页面层
# ════════════════════════════════════════════════════════════


@pytest.fixture
def contract_page(qapp):
    from ui_qml.bridge.contract_bridge import ContractBridge
    from ui_qml.host import PageHost

    b = ContractBridge(None)
    host = PageHost("pages/ContractPage.qml", context={"bridge": b})
    yield host, b
    host.deleteLater()
    _spin(60)


@pytest.mark.ui
def test_page_loads_and_exposes_the_bridge(contract_page):
    host, bridge = contract_page
    assert host.ok(), "; ".join(str(e) for e in host.errors())
    root = host.rootObject()
    assert root is not None
    assert root.property("contract") is bridge
    assert root.property("currentRow") == -1


@pytest.mark.ui
def test_page_loads_without_qml_warnings(contract_page):
    """加载 + 布局不给 Qt 刷告警（textRole / 位置绑定两类坑都真实出现过）。"""
    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            else None
        )
    )
    try:
        host, _bridge = contract_page
        root = host.rootObject()
        root.setProperty("width", 1280)
        root.setProperty("height", 720)
        _spin(300)
    finally:
        qInstallMessageHandler(previous)

    assert not caught, "QML 产生了告警：\n" + "\n".join(dict.fromkeys(caught))


@pytest.mark.ui
def test_row_click_survives_content_move(contract_page):
    """行点击命中固定在按下那一刻（见 `FTableClickArea` 的说明）。

    回归背景：delegate 里的 `TapHandler` 配 `ReleaseWithinBounds` 在**释放**时判定
    命中，内容一移动（甩动/惯性沉降）就整次丢掉点击 —— 界面表现是
    「单击不到所对应的行上」。
    """
    host, bridge = contract_page
    bridge._on_contracts_loaded([_contract(cid=i + 1, title=f"合同{i}") for i in range(50)])
    _spin(150)
    root = host.rootObject()
    press_move_release(
        host, root, area_name="contractClickArea", row=3, read_current=lambda: root.property("currentRow"), delta=1
    )
