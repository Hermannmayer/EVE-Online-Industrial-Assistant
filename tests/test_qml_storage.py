"""仓库管理页（阶段 3）的契约测试。

分三层（与其余阶段 3 的页面测试同构）：
  - **纯函数层**（`fast`）：两张表的命名角色与展示规则；
  - **桥层**（`ui`）：机库切换、**多选语义**（普通/Ctrl/Shift）、右键作用行集、
    蓝图过滤（DB 与 container 全部打桩）；
  - **页面层**（`ui`）：`StoragePage.qml` 能加载、无 QML 告警。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer, QtMsgType, qInstallMessageHandler

from ui_qml.models.inventory_qml_models import (
    BP_ROLE_NAMES,
    INV_ROLE_NAMES,
    BlueprintQmlModel,
    InvQmlModel,
)

_BASE = Qt.ItemDataRole.UserRole
_I_TEXT = _BASE + 1
_I_ICON = _BASE + 2
_I_ALIGN = _BASE + 3
_I_TIP = _BASE + 4
_I_ID = _BASE + 6
_B_TEXT = _BASE + 1
_B_FG = _BASE + 2
_B_ALIGN = _BASE + 4
_B_NAME = _BASE + 7


def _item(iid: int = 1, tid: int = 34, qty: int = 100, cost: float = 5.0) -> dict:
    return {
        "id": iid,
        "type_id": tid,
        "quantity": qty,
        "cost_price": cost,
        "plan_usage": 10,
        "plan_remain": 90,
        "sell_price": 6.0,
        "research_cost": 1000,
        "display_name": "三钛合金",
    }


def _bp(bpid: int = 1, bp_type_id: int = 1000, occupied: bool = False, margin: float = 12.5) -> dict:
    return {
        "id": bpid,
        "blueprint_type_id": bp_type_id,
        "zh_name": "三钛合金蓝图",
        "product_type_id": 34,
        "product_name": "三钛合金",
        "product_quantity": 100,
        "is_bpo": True,
        "runs": 10,
        "me_level": 10,
        "te_level": 20,
        "base_time": 3600,
        "occupied": occupied,
        "material_cost": 1000.0,
        "revenue": 1200.0,
        "margin": margin,
    }


def _spin(ms: int = 100) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# ════════════════════════════════════════════════════════════
#  模型
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_role_names_are_unique_and_contiguous():
    for roles in (INV_ROLE_NAMES, BP_ROLE_NAMES):
        keys = sorted(roles)
        assert keys[0] == Qt.ItemDataRole.UserRole + 1
        assert keys == list(range(keys[0], keys[0] + len(roles)))
        assert len(set(roles.values())) == len(roles)


@pytest.mark.fast
def test_inv_model_text_and_roles():
    model = InvQmlModel()
    model.set_rows([_item()])
    assert model.data(model.index(0, 0), _I_TEXT) == ""  # 图标列无文字
    assert model.data(model.index(0, 1), _I_TEXT) == "三钛合金"
    assert model.data(model.index(0, 2), _I_TEXT) == "100"
    assert model.data(model.index(0, 3), _I_TEXT) == "5.00"
    assert model.data(model.index(0, 4), _I_TEXT) == "10"
    assert model.data(model.index(0, 5), _I_TEXT) == "90"
    assert model.data(model.index(0, 6), _I_TEXT) == "600"  # 100 × 6.0
    assert model.data(model.index(0, 7), _I_TEXT) == "1,000"
    assert model.data(model.index(0, 0), _I_ID) == 1
    assert model.data(model.index(0, 4), _I_TIP) == "待启动计划预留"
    assert model.data(model.index(0, 3), _I_TIP) == ""
    # 数量列起右对齐，名称列左对齐
    assert model.data(model.index(0, 1), _I_ALIGN) is False
    assert model.data(model.index(0, 2), _I_ALIGN) is True
    # 图标列给的是 URL 或空串（缓存缺失时为空）
    assert isinstance(model.data(model.index(0, 0), _I_ICON), str)
    assert model.data(model.index(0, 1), _I_ICON) == ""


@pytest.mark.fast
def test_inv_model_handles_missing_prices():
    model = InvQmlModel()
    model.set_rows([{**_item(), "cost_price": 0, "sell_price": None, "plan_usage": 0, "plan_remain": None}])
    assert model.data(model.index(0, 3), _I_TEXT) == "-"
    assert model.data(model.index(0, 6), _I_TEXT) == "-"
    assert model.data(model.index(0, 4), _I_TEXT) == "0"
    assert model.data(model.index(0, 5), _I_TEXT) == "100"  # 无剩余时回落库存数量


@pytest.mark.fast
def test_blueprint_model_text_and_colours():
    model = BlueprintQmlModel()
    model.set_rows([_bp()])
    assert model.data(model.index(0, 1), _B_TEXT) == "三钛合金蓝图"
    assert model.data(model.index(0, 2), _B_TEXT) == "蓝图原图"
    assert model.data(model.index(0, 3), _B_TEXT) == "10"
    assert model.data(model.index(0, 6), _B_TEXT) == "1h 0m"
    assert model.data(model.index(0, 7), _B_TEXT) == "无限"  # BPO
    assert model.data(model.index(0, 8), _B_TEXT) == "1,000 ISK"
    assert model.data(model.index(0, 10), _B_TEXT) == "+12.5%"
    assert model.data(model.index(0, 0), _B_NAME) == "三钛合金蓝图"
    assert model.data(model.index(0, 2), _B_FG) == ""  # 未占用不染色
    assert model.data(model.index(0, 10), _B_FG)  # 利润率有正负色

    negative = BlueprintQmlModel()
    negative.set_rows([_bp(margin=-3.0)])
    assert negative.data(negative.index(0, 10), _B_FG) != model.data(model.index(0, 10), _B_FG)


@pytest.mark.fast
def test_occupied_blueprint_is_marked_orange():
    plain = BlueprintQmlModel()
    plain.set_rows([_bp(occupied=False)])
    busy = BlueprintQmlModel()
    busy.set_rows([_bp(occupied=True)])

    assert busy.data(busy.index(0, 2), _B_TEXT).endswith("（占用中）")
    assert busy.data(busy.index(0, 2), _B_FG) != plain.data(plain.index(0, 2), _B_FG)
    assert busy.data(busy.index(0, 2), _B_FG) != ""


@pytest.mark.fast
def test_blueprint_alignment_and_set_rows():
    model = BlueprintQmlModel()
    model.set_rows([_bp(), _bp(bpid=2)])
    assert model.data(model.index(0, 1), _B_ALIGN) is False
    assert model.data(model.index(0, 2), _B_ALIGN) is True
    model.set_rows([])
    assert model.rowCount() == 0


# ════════════════════════════════════════════════════════════
#  桥
# ════════════════════════════════════════════════════════════


@pytest.fixture
def bridge(qapp, monkeypatch):
    """桥在构造时会真读机库/物品/蓝图与市场分类，这里把数据层全部打桩。"""
    import services.inventory_manager as im
    import services.name_resolver as nr
    from core import container as container_mod

    hangars = [{"id": 1, "name": "A 库", "solar_system_id": None}, {"id": 2, "name": "B 库"}]
    items: dict[int, list[dict]] = {1: [_item(1), _item(2, tid=35)], 2: [_item(3, tid=36)]}
    blueprints: list[dict] = []

    monkeypatch.setattr(im, "init_db", lambda: None)
    monkeypatch.setattr(im, "get_hangars", lambda: list(hangars))
    monkeypatch.setattr(im, "get_items", lambda hid=None: list(items.get(hid, [])))
    monkeypatch.setattr(im, "get_blueprints", lambda hid=None: list(blueprints))
    monkeypatch.setattr(im, "get_blueprint_tech_levels", lambda: {})
    monkeypatch.setattr(im, "get_blueprint_reaction_ids", lambda: set())
    monkeypatch.setattr(im, "get_blueprint_product_info_batch", lambda ids: {})
    monkeypatch.setattr(im, "get_blueprint_materials_batch", lambda ids: {})
    monkeypatch.setattr(nr, "resolve_system_display_names_batch", lambda ids: {})
    monkeypatch.setattr(
        container_mod,
        "get_container",
        lambda: SimpleNamespace(
            item_repo=SimpleNamespace(get_root_market_categories=lambda: [(100, "舰船")]),
            market_repo=SimpleNamespace(get_sell_prices=lambda ids, region: {}, get_prices_by_region=lambda *a: {}),
        ),
    )

    from ui_qml.bridge.inventory_bridge import InventoryBridge

    b = InventoryBridge(None)
    b._fixture_items = items
    return b


@pytest.mark.ui
def test_hangars_and_items_load_at_construction(bridge):
    assert bridge.hangarNames == ["A 库", "B 库"]
    assert bridge.hangarIndex == 0
    assert bridge.itemModel.rowCount() == 2
    assert bridge.itemCountText == "共 2 项"
    assert "按卖单价格" in bridge.itemTotalText


@pytest.mark.ui
def test_switching_hangar_reloads_items(bridge):
    bridge.setHangarIndex(1)
    assert bridge.hangarIndex == 1
    assert bridge.itemModel.rowCount() == 1
    assert bridge.itemCountText == "共 1 项"
    bridge.setHangarIndex(99)  # 越界忽略
    assert bridge.hangarIndex == 1


@pytest.mark.ui
def test_plain_click_selects_only_that_row(bridge):
    bridge.selectItemRow(0)
    assert bridge.itemRowSelected(0) is True
    bridge.selectItemRow(1)
    assert bridge.itemRowSelected(0) is False
    assert bridge.itemRowSelected(1) is True


@pytest.mark.ui
def test_ctrl_click_toggles_and_shift_click_ranges(bridge, monkeypatch):
    mods = {"value": Qt.KeyboardModifier.NoModifier}
    # 从桥的 `_modifiers` 注入：PySide6 的 QGuiApplication 是 C++ 类型，
    # 直接 monkeypatch 它的类方法不生效（静默失败，用例会假过）
    monkeypatch.setattr(type(bridge), "_modifiers", lambda self: mods["value"])

    mods["value"] = Qt.KeyboardModifier.NoModifier
    bridge.selectItemRow(0)

    mods["value"] = Qt.KeyboardModifier.ControlModifier
    bridge.selectItemRow(1)
    assert bridge.itemRowSelected(0) and bridge.itemRowSelected(1)
    bridge.selectItemRow(1)  # 再点一次取消
    assert bridge.itemRowSelected(1) is False
    assert bridge.itemRowSelected(0) is True

    # Shift 从**上一次点中的行**（锚点）连选过来；此时锚点是刚 Ctrl 点过的 1，
    # 所以 Shift 点 0 得到 {0,1}
    mods["value"] = Qt.KeyboardModifier.ShiftModifier
    bridge.selectItemRow(0)
    assert bridge.itemRowSelected(0) and bridge.itemRowSelected(1)


@pytest.mark.ui
def test_selection_revision_bumps_so_qml_repaints(bridge):
    """`var` 集合变化不会自己通知，delegate 靠读修订号重算 —— 修订号必须每次变。"""
    before = bridge.selectionRevision
    bridge.selectItemRow(0)
    assert bridge.selectionRevision > before


@pytest.mark.ui
def test_menu_rows_fall_back_to_the_clicked_row(bridge):
    bridge.clearItemSelection()
    assert bridge.itemsForMenu(1) == [1]
    assert bridge.itemRowSelected(1) is True

    bridge.selectItemRow(0)
    assert bridge.itemsForMenu(0) == [0] or 0 in bridge.itemsForMenu(0)


@pytest.mark.ui
def test_item_menu_state_reports_move_targets(bridge):
    state = bridge.itemMenuState(0)
    assert state["valid"] is True
    assert state["single"] is True
    assert state["count"] == 1
    # 当前是 A 库(1)，可移动到 B 库(2)
    assert [t["id"] for t in state["moveTargets"]] == [2]


@pytest.mark.ui
def test_item_hint_reports_empty_clipboard(bridge, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: SimpleNamespace(text=lambda: "   ")))
    bridge.transferFromClipboard()
    assert "剪贴板为空" in bridge.itemCountText


@pytest.mark.ui
def test_blueprint_filters_and_counts(bridge):
    from ui_qml.bridge import inventory_bridge as mod

    bridge._bp_all_rows = [
        {**_bp(bpid=1, bp_type_id=1), "tech_level": 1, "is_reaction": False, "product_type_id": 34},
        {
            **_bp(bpid=2, bp_type_id=2),
            "is_bpo": False,
            "tech_level": 2,
            "is_reaction": False,
            "product_type_id": 35,
            "zh_name": "渡鸦级蓝图",
        },
        {
            **_bp(bpid=3, bp_type_id=3),
            "tech_level": 1,
            "is_reaction": True,
            "product_type_id": 36,
            "zh_name": "反应公式",
        },
    ]
    bridge.applyBlueprintFilter()
    assert bridge.blueprintModel.rowCount() == 3
    assert bridge.blueprintCountText == "共 3 个蓝图"

    bridge.setTypeFilterIndex(mod._TYPE_FILTERS.index("蓝图原图"))
    assert bridge.blueprintModel.rowCount() == 1

    bridge.setTypeFilterIndex(mod._TYPE_FILTERS.index("反应公式"))
    assert bridge.blueprintModel.rowCount() == 1

    bridge.setTypeFilterIndex(0)
    bridge.setTechFilterIndex(mod._TECH_FILTERS.index("T2"))
    assert bridge.blueprintModel.rowCount() == 1

    bridge.setTechFilterIndex(0)
    bridge.setBlueprintSearch("渡鸦")
    assert bridge.blueprintModel.rowCount() == 1


@pytest.mark.ui
def test_blueprint_menu_rows_fall_back(bridge):
    bridge.clearBlueprintSelection()
    assert bridge.blueprintsForMenu(2) == [2]
    assert bridge.blueprintRowSelected(2) is True
    assert bridge.blueprintMenuState(2)["single"] is True


# ════════════════════════════════════════════════════════════
#  页面层
# ════════════════════════════════════════════════════════════


@pytest.fixture
def storage_page(qapp, monkeypatch):
    import services.inventory_manager as im
    import services.name_resolver as nr
    from core import container as container_mod

    monkeypatch.setattr(im, "init_db", lambda: None)
    monkeypatch.setattr(im, "get_hangars", lambda: [{"id": 1, "name": "A 库"}])
    monkeypatch.setattr(im, "get_items", lambda hid=None: [])
    monkeypatch.setattr(im, "get_blueprints", lambda hid=None: [])
    monkeypatch.setattr(im, "get_blueprint_tech_levels", lambda: {})
    monkeypatch.setattr(im, "get_blueprint_reaction_ids", lambda: set())
    monkeypatch.setattr(nr, "resolve_system_display_names_batch", lambda ids: {})
    monkeypatch.setattr(
        container_mod,
        "get_container",
        lambda: SimpleNamespace(
            item_repo=SimpleNamespace(get_root_market_categories=lambda: []),
            market_repo=SimpleNamespace(get_sell_prices=lambda ids, region: {}),
        ),
    )

    from ui_qml.bridge.inventory_bridge import InventoryBridge
    from ui_qml.host import PageHost

    b = InventoryBridge(None)
    host = PageHost("pages/StoragePage.qml", context={"bridge": b})
    yield host, b
    host.deleteLater()
    _spin(60)


@pytest.mark.ui
def test_page_loads_and_exposes_the_bridge(storage_page):
    host, bridge = storage_page
    assert host.ok(), "; ".join(str(e) for e in host.errors())
    root = host.rootObject()
    assert root is not None
    assert root.property("inv") is bridge


@pytest.mark.ui
def test_page_loads_without_qml_warnings(storage_page):
    """加载 + 布局不给 Qt 刷告警（这一页有 11 列的宽表，最容易出 textRole/绑定类告警）。"""
    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            else None
        )
    )
    try:
        host, _bridge = storage_page
        root = host.rootObject()
        root.setProperty("width", 1400)
        root.setProperty("height", 800)
        _spin(300)
    finally:
        qInstallMessageHandler(previous)

    assert not caught, "QML 产生了告警：\n" + "\n".join(dict.fromkeys(caught))
