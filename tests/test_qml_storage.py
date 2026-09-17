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
from PySide6.QtCore import QObject, QPoint, Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.qml_click import spin as _spin
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


def _stub_inventory(monkeypatch, items: list[dict]) -> None:
    """把仓库页要的后端全部打桩（机库 / 物品 / 蓝图 / 容器）。"""
    import services.inventory_manager as im
    import services.name_resolver as nr
    from core import container as container_mod

    monkeypatch.setattr(im, "init_db", lambda: None)
    monkeypatch.setattr(im, "get_hangars", lambda: [{"id": 1, "name": "A 库"}])
    monkeypatch.setattr(im, "get_items", lambda hid=None: list(items))
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


@pytest.fixture
def storage_page(qapp, monkeypatch):
    _stub_inventory(monkeypatch, [])

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


# ════════════════════════════════════════════════════════════
#  表格点击命中（FTableClickArea）
#
#  回归背景：delegate 内的 TapHandler 配 `ReleaseWithinBounds` 是在**释放**时判定
#  命中的，而 TableView 是 Flickable，甩动/沉降期间内容会移动——按下时那个 delegate
#  已经移开，于是整次点击被丢掉。实测「按下 → 内容移动 1 行 → 释放」选中集为空，
#  也就是用户说的「单击不到所对应的行上」。
#  现在命中在**按下那一刻**算好并按它派发。
# ════════════════════════════════════════════════════════════


@pytest.fixture
def storage_table(qapp, monkeypatch):
    """有 300 行数据的仓库页 + 物品表/点击区句柄。"""
    _stub_inventory(monkeypatch, [_item(iid=i) for i in range(1, 301)])

    from ui_qml.bridge.inventory_bridge import InventoryBridge
    from ui_qml.host import PageHost

    b = InventoryBridge(None)
    host = PageHost("pages/StoragePage.qml", context={"bridge": b})
    host.resize(1500, 850)
    host.show()
    _spin(500)

    root = host.rootObject()
    table = None

    def _walk(item):
        nonlocal table
        for ch in item.childItems():
            if "TableView" in ch.metaObject().className() and table is None:
                table = ch
            _walk(ch)

    _walk(root)
    area = root.findChild(QObject, "itemClickArea")
    if table is None or area is None:
        host.deleteLater()
        _spin(60)
        pytest.skip("表格/点击区没找到（QML 结构变了）")

    yield host, root, b, table, area
    host.deleteLater()
    _spin(60)


def _delegate_selected(table, row: int):
    """该行 delegate 的 `selectedRow`（= 画面上的高亮），找不到返回 None。"""
    for ch in table.property("contentItem").childItems():
        try:
            if ch.property("row") == row and ch.property("column") == 1:
                return ch.property("selectedRow")
        except Exception:
            continue
    return None


def _press_point(root, table, row: int, content_y: float, row_h: int) -> QPoint:
    """「内容位移 content_y 时，视觉第 row 行中心」对应的 host 坐标。

    **断言该行确实落在视口内**：点空时选中集为空，断言会以「应选中第 N 行」的
    面目出现，把「用例数据挑得不对」伪装成产品故障（实测踩过：单跑通过、整模块
    跑时窗口矮一点就点空）。
    """
    ty = row * row_h - content_y + row_h / 2
    assert 0 < ty < table.height(), (
        f"用例自身有误：第 {row} 行在 contentY={content_y} 下不可见（表高 {table.height()}）"
    )
    origin = table.mapToItem(root, 0.0, 0.0)
    host_origin = root.mapToItem(None, origin.x(), origin.y())
    return QPoint(int(host_origin.x()) + 200, int(host_origin.y()) + int(ty))


@pytest.mark.ui
def test_click_selects_the_row_under_the_cursor(storage_table):
    host, root, bridge, table, _area = storage_table
    row_h = root.property("rowH")
    for content_y, row in ((0.0, 2), (0.0, 7), (140.0, 9), (4000.0, 160)):
        table.setProperty("contentY", content_y)
        _spin(180)
        bridge.clearItemSelection()
        _spin(60)
        QTest.mouseClick(host, Qt.LeftButton, Qt.NoModifier, _press_point(root, table, row, content_y, row_h))
        _spin(120)
        assert sorted(bridge._item_selection) == [row], f"contentY={content_y} 应选中第 {row} 行"


@pytest.mark.ui
def test_click_keeps_the_pressed_row_when_content_moves(storage_table):
    """回归：按下与释放之间内容移动（甩动/惯性沉降），仍应选中**按下那一刻**的行。"""
    host, root, bridge, table, _area = storage_table
    row_h = root.property("rowH")

    # 注意：行号必须落在该 contentY 下**可见**的范围内，否则点的是视口外（测试自身的坑）
    for content_y, row, delta in ((0.0, 5, 1), (0.0, 5, 3), (200.0, 12, -2), (4000.0, 150, 2)):
        table.setProperty("contentY", content_y)
        _spin(180)
        bridge.clearItemSelection()
        _spin(60)
        pt = _press_point(root, table, row, content_y, row_h)
        QTest.mousePress(host, Qt.LeftButton, Qt.NoModifier, pt)
        QApplication.processEvents()  # 让「按下」在内容移动之前落地
        table.setProperty("contentY", content_y + delta * row_h)
        _spin(60)
        QTest.mouseRelease(host, Qt.LeftButton, Qt.NoModifier, pt)
        _spin(120)
        assert sorted(bridge._item_selection) == [row], (
            f"contentY={content_y} 内容移动 {delta} 行后应仍选中按下的第 {row} 行"
        )


@pytest.mark.ui
def test_drag_to_scroll_does_not_select(storage_table):
    """拖动是滚动，不是选中 —— 修好「点击」不能把「拖动」搞成误选。"""
    host, root, bridge, table, _area = storage_table
    row_h = root.property("rowH")
    table.setProperty("contentY", 0.0)
    _spin(150)
    bridge.clearItemSelection()
    _spin(60)

    start = _press_point(root, table, 6, 0.0, row_h)
    QTest.mousePress(host, Qt.LeftButton, Qt.NoModifier, start)
    for i in range(1, 9):
        QTest.mouseMove(host, QPoint(start.x(), start.y() - i * 12))
        QApplication.processEvents()
    QTest.mouseRelease(host, Qt.LeftButton, Qt.NoModifier, QPoint(start.x(), start.y() - 96))
    _spin(200)

    assert table.property("contentY") > 0, "拖动应滚动内容"
    assert sorted(bridge._item_selection) == [], "拖动不该产生选中"


@pytest.mark.ui
def test_right_click_menu_targets_the_pressed_row(storage_table):
    host, root, bridge, table, _area = storage_table
    row_h = root.property("rowH")
    menu = root.findChild(QObject, "itemMenu")
    assert menu is not None

    table.setProperty("contentY", 0.0)
    _spin(150)
    QTest.mouseClick(host, Qt.RightButton, Qt.NoModifier, _press_point(root, table, 6, 0.0, row_h))
    _spin(200)
    assert menu.property("visible") is True, "右键应弹出菜单"
    assert menu.property("row") == 6, "菜单作用于右键按下的那一行"
    menu.setProperty("visible", False)
    _spin(60)


@pytest.mark.ui
def test_click_updates_the_row_highlight(storage_table):
    """回归：点击后**画面上的高亮**必须跟着动。

    只断言桥里的选中集是不够的 —— 曾经出现过「桥里选中对了、delegate 的高亮不动」：
    当时高亮靠 QML 侧派生集合（`readonly property var` + 逐格 `indexOf`），实测那个
    派生绑定**不随选中变化重算**，界面上就是点了这行、高亮停在别处（看着像选中了
    另一行）。现在高亮走模型的 `selected` 角色（`dataChanged` 驱动），把它钉住。
    """
    host, root, bridge, table, _area = storage_table
    row_h = root.property("rowH")
    table.setProperty("contentY", 0.0)
    _spin(200)
    bridge.clearItemSelection()
    _spin(150)
    assert _delegate_selected(table, 3) is False

    QTest.mouseClick(host, Qt.LeftButton, Qt.NoModifier, _press_point(root, table, 3, 0.0, row_h))
    _spin(250)

    assert sorted(bridge._item_selection) == [3]
    assert _delegate_selected(table, 3) is True, "高亮没跟上：delegate 的 selectedRow 仍是 False"
    assert _delegate_selected(table, 4) is False, "不该顺带高亮别的行"


# ════════════════════════════════════════════════════════════
#  表头排序
#
#  回归背景：仓库页从 Widgets 迁到 QML 时**整个排序功能丢了**（用户反馈
#  「仓库界面的排序功能没了」）。模型侧一直有 `sort(column, order)`，是表头没接。
# ════════════════════════════════════════════════════════════


@pytest.fixture
def sortable_bridge(qapp, monkeypatch):
    """四行名字有明确顺序的物品，便于断言排序结果。"""
    names = ["Zeta", "Alpha", "Mike", "Bravo"]
    items = [{**_item(iid=i + 1, qty=100 * (i + 1)), "display_name": n} for i, n in enumerate(names)]
    _stub_inventory(monkeypatch, items)
    from ui_qml.bridge.inventory_bridge import InventoryBridge

    return InventoryBridge(None)


@pytest.mark.ui
def test_sort_items_toggles_direction(sortable_bridge):
    bridge = sortable_bridge

    def order() -> list[str]:
        return [r["display_name"] for r in bridge.itemModel.rows()]

    assert order() == ["Zeta", "Alpha", "Mike", "Bravo"]
    bridge.sortItems(1)  # 名称列升序
    assert order() == ["Alpha", "Bravo", "Mike", "Zeta"]
    assert bridge.itemSortColumn == 1
    assert bridge.itemSortAscending is True

    bridge.sortItems(1)  # 再点同列 → 反向
    assert order() == ["Zeta", "Mike", "Bravo", "Alpha"]
    assert bridge.itemSortAscending is False

    bridge.sortItems(2)  # 换列 → 从升序开始（对齐 QTableView）
    assert order() == ["Zeta", "Alpha", "Mike", "Bravo"]  # 数量 100/200/300/400
    assert bridge.itemSortAscending is True


@pytest.mark.ui
def test_sort_items_keeps_selection_by_id(sortable_bridge):
    """排序会重排行号 —— 选中集必须按 **id** 找回，否则会指到别的物品上。"""
    bridge = sortable_bridge
    bridge.selectItemRow(1)  # Alpha
    assert [bridge.itemModel.rows()[r]["display_name"] for r in bridge.selectedItemRows] == ["Alpha"]

    bridge.sortItems(1)  # 名称升序 → Alpha 排到第 0 行

    rows = bridge.itemModel.rows()
    assert [rows[r]["display_name"] for r in bridge.selectedItemRows] == ["Alpha"]


@pytest.mark.fast
def test_storage_page_headers_are_wired_to_sorting():
    """静态护栏：两张表的表头都要接到排序。

    「排序功能没了」不会让任何测试失败 —— 当初就是这么整段丢的（表头没接线）。
    """
    text = (Path(__file__).resolve().parent.parent / "ui_qml" / "qml" / "pages" / "StoragePage.qml").read_text(
        encoding="utf-8"
    )
    assert "page.inv.sortItems(" in text, "机库表的表头没接排序"
    assert "page.inv.sortBlueprints(" in text, "蓝图表表头没接排序"
    assert "itemSortableColumns" in text and "blueprintSortableColumns" in text, "可排序列判据没接上"


# ════════════════════════════════════════════════════════════
#  排序要活过刷新
#
#  回归背景：右键「加入制造规划」跑完会 `loadBlueprints()` → `set_rows()` 整份换行，
#  而 `set_rows` 原先只换数据、不重排 —— 表格悄悄回到原始顺序，桥那边的排序指示却
#  还亮着（它记的是自己那份 `_bp_sort_col`）。用户看到的就是
#  「点了加入制造规划之后排序失效了」。同一根因也打机库物品表（移库/刷新后同样乱）。
# ════════════════════════════════════════════════════════════


def _sortable_bp(bpid: int, runs: int, margin: float) -> dict:
    """够排序用的最小蓝图行（`is_bpo=False`：原图按流程数排序会被当成 inf）。"""
    return {
        "id": bpid,
        "blueprint_type_id": 1000 + bpid,
        "is_bpo": False,
        "runs": runs,
        "margin": margin,
        "me_level": 0,
        "te_level": 0,
        "base_time": 0,
    }


@pytest.mark.ui
def test_blueprint_sort_survives_set_rows(qapp):
    """刷新（`set_rows` 整份换行）后必须照当前排序重排，升序降序都要守住。"""
    source = [_sortable_bp(1, 50, -3.0), _sortable_bp(2, 10, 9.0), _sortable_bp(3, 30, 1.0)]
    model = BlueprintQmlModel([dict(r) for r in source])

    model.sort(7, Qt.SortOrder.AscendingOrder)  # 流程数量
    assert [r["id"] for r in model.rows()] == [2, 3, 1]

    model.set_rows([dict(r) for r in source])  # 模拟一次刷新：同一批数据、原始顺序
    assert [r["id"] for r in model.rows()] == [2, 3, 1], "刷新后被打回原始顺序 = 用户报的「排序失效」"

    model.sort(10, Qt.SortOrder.DescendingOrder)  # 利润率降序
    assert [r["id"] for r in model.rows()] == [2, 3, 1]

    model.set_rows([dict(r) for r in source])
    assert [r["id"] for r in model.rows()] == [2, 3, 1], "降序同样要活过刷新"


@pytest.mark.ui
def test_item_sort_survives_set_rows(qapp):
    """同一条回护栏，机库物品表也走一遍（移库 / 刷新同样会 `set_rows`）。"""
    source = [_item(iid=1, qty=300), _item(iid=2, qty=100), _item(iid=3, qty=200)]
    model = InvQmlModel([dict(r) for r in source])

    model.sort(2, Qt.SortOrder.AscendingOrder)  # 库存数量
    assert [r["id"] for r in model.rows()] == [2, 3, 1]

    model.set_rows([dict(r) for r in source])
    assert [r["id"] for r in model.rows()] == [2, 3, 1]


@pytest.mark.ui
def test_never_sorted_model_stays_put_on_refresh(qapp):
    """没排过序的表刷新后保持后端给的顺序（别自作主张按第 0 列乱排）。"""
    source = [_sortable_bp(1, 50, -3.0), _sortable_bp(2, 10, 9.0), _sortable_bp(3, 30, 1.0)]
    model = BlueprintQmlModel([dict(r) for r in source])

    model.set_rows([dict(r) for r in source])
    assert [r["id"] for r in model.rows()] == [1, 2, 3]
