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
from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.qml_click import spin as _spin
from tests.qml_page_load import assert_page_loads_quietly, page_host
from ui_qml.models.inventory_helpers import BlueprintTableModel, InvTableModel
from ui_qml.models.inventory_qml_models import (
    BP_ROLE_NAMES,
    INV_ROLE_NAMES,
    BlueprintQmlModel,
    InvQmlModel,
)
from ui_qml.theme.registry import token

_BASE = Qt.ItemDataRole.UserRole
_I_TEXT = _BASE + 1
_I_ICON = _BASE + 2
_I_ALIGN = _BASE + 3
_I_TIP = _BASE + 4
_I_ID = _BASE + 6
_I_FG = _BASE + 8
_B_TEXT = _BASE + 1
_B_FG = _BASE + 2
_B_ALIGN = _BASE + 4
_B_NAME = _BASE + 7

pytestmark = pytest.mark.ui


def _item(iid: int = 1, tid: int = 34, qty: int = 100, cost: float = 5.0) -> dict:
    return {
        "id": iid,
        "type_id": tid,
        "quantity": qty,
        "cost_price": cost,
        "plan_usage": 10,
        "plan_remain": 90,
        "sell_price": 6.0,
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
    assert model.data(model.index(0, 6), _I_TEXT) == "-"  # 规划占用 10 < 库存 100 → 无缺口
    assert model.data(model.index(0, 7), _I_TEXT) == "500"  # 占用资金 = 5.0 × 100
    assert model.data(model.index(0, 8), _I_TEXT) == "600"  # 100 × 6.0
    assert model.data(model.index(0, 0), _I_ID) == 1
    assert model.data(model.index(0, 4), _I_TIP) == "待启动计划预留"
    assert model.data(model.index(0, 3), _I_TIP) == ""
    # 数量列起右对齐，名称列左对齐
    assert model.data(model.index(0, 1), _I_ALIGN) is False
    assert model.data(model.index(0, 2), _I_ALIGN) is True
    # 图标列给的是 URL 或空串（缓存缺失时为空）
    assert model.data(model.index(0, 1), _I_ICON) == ""
    # 缺口 > 0 才下发红色 token（无缺口给空串 = 不覆盖主题色）
    assert model.data(model.index(0, 6), _I_FG) == ""
    short = InvQmlModel()
    short.set_rows([{**_item(qty=40), "plan_usage": 100}])
    assert short.data(short.index(0, 6), _I_TEXT) == "缺 60"
    assert short.data(short.index(0, 6), _I_FG) == token("ACCENT_RED")


@pytest.mark.fast
def test_inv_model_handles_missing_prices():
    model = InvQmlModel()
    model.set_rows([{**_item(), "cost_price": 0, "sell_price": None, "plan_usage": 0, "plan_remain": None}])
    assert model.data(model.index(0, 3), _I_TEXT) == "-"
    assert model.data(model.index(0, 7), _I_TEXT) == "-"  # 成本价 0 → 占用资金占位
    assert model.data(model.index(0, 8), _I_TEXT) == "-"
    assert model.data(model.index(0, 4), _I_TEXT) == "0"
    assert model.data(model.index(0, 5), _I_TEXT) == "100"  # 无剩余时回落库存数量
    assert model.data(model.index(0, 6), _I_TEXT) == "-"  # 规划占用 0 → 无缺口


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
    assert model.data(model.index(0, 9), _B_TEXT) == "1,200 ISK"
    assert model.data(model.index(0, 10), _B_TEXT) == "200 ISK"  # 1,200 − 1,000（每流程）
    assert model.data(model.index(0, 11), _B_TEXT) == "+12.5%"
    assert model.data(model.index(0, 0), _B_NAME) == "三钛合金蓝图"
    assert model.data(model.index(0, 2), _B_FG) == ""  # 未占用不染色
    assert model.data(model.index(0, 10), _B_FG) == token("ACCENT_GREEN")  # 正利润绿
    assert model.data(model.index(0, 11), _B_FG) == token("ACCENT_GREEN")

    negative = BlueprintQmlModel()
    negative.set_rows([{**_bp(margin=-3.0), "revenue": 900.0}])
    assert negative.data(negative.index(0, 10), _B_FG) == token("ACCENT_RED")  # 亏损红
    assert negative.data(negative.index(0, 10), _B_TEXT) == "-100 ISK"
    assert negative.data(negative.index(0, 11), _B_FG) != model.data(model.index(0, 11), _B_FG)


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
    model.set_rows([{**_bp(), "status": "库中有成品 · 正在制造"}, _bp(bpid=2)])
    assert model.data(model.index(0, 1), _B_ALIGN) is False
    assert model.data(model.index(0, 2), _B_ALIGN) is True
    assert model.data(model.index(0, 11), _B_ALIGN) is True  # 利润率仍是数值列
    assert model.data(model.index(0, 12), _B_TEXT) == "库中有成品 · 正在制造"  # 末尾的「状态」列
    assert model.data(model.index(1, 12), _B_TEXT) == "-"  # 一个状态都没命中
    assert model.data(model.index(0, 12), _B_ALIGN) is False  # 文字列 → 左对齐
    model.set_rows([])
    assert model.rowCount() == 0


@pytest.mark.fast
@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (set(), "-"),
        ({"有挂单"}, "有挂单"),
        ({"正在制造", "库中有成品", "正在发明"}, "库中有成品 · 正在发明 · 正在制造"),
    ],
)
def test_format_blueprint_status_orders_and_joins(statuses, expected):
    """状态 → 显示串：固定顺序 + ` · ` 连接，全未命中给 `-`（显示串同时是排序键）。"""
    from services.inventory_manager import format_blueprint_status

    assert format_blueprint_status(statuses) == expected


@pytest.mark.fast
def test_blueprint_status_map_hits_stock_orders_and_running_plans(tmp_path, monkeypatch):
    """批量查询一次判出全部状态（临时 sqlite，不碰真库）。

    回归背景：计划 → 蓝图必须走 `plan_blueprint_bindings`（`assigned_blueprint_id` 兜底）——
    按 `production_plans.blueprint_type_id` 关联会恒空，那一列 `insert_plan` 从不写、
    真实库里全为 NULL（2026-10 实测）。同时守着两条口径：`pending` 不算「正在」、
    挂单要 `volume_remain > 0`（买单也算）。
    """
    import contextlib
    import sqlite3

    import services.inventory_manager as im

    db = tmp_path / "user.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE inventory_items (type_id INTEGER, quantity INTEGER);
        CREATE TABLE open_orders (type_id INTEGER, volume_remain INTEGER, is_buy INTEGER);
        CREATE TABLE production_plans (id INTEGER, status TEXT, activity TEXT, assigned_blueprint_id INTEGER);
        CREATE TABLE plan_blueprint_bindings (plan_id INTEGER, blueprint_id INTEGER);
        INSERT INTO inventory_items VALUES (34, 500), (37, 0);
        INSERT INTO open_orders VALUES (35, 10, 1), (37, 0, 0);
        INSERT INTO production_plans VALUES (9, 'in_progress', 'manufacturing', 1), (10, 'pending', 'manufacturing', 3);
        INSERT INTO plan_blueprint_bindings VALUES (9, 1), (10, 3);
        """
    )
    conn.commit()
    conn.close()

    @contextlib.contextmanager
    def _connect(*_aliases):
        c = sqlite3.connect(db)
        try:
            yield c
        finally:
            c.close()

    monkeypatch.setattr(im, "_default_db", lambda: SimpleNamespace(connect=_connect))

    rows = [
        {"id": 1, "blueprint_type_id": 1000, "product_type_id": 34},
        {"id": 2, "blueprint_type_id": 2000, "product_type_id": 35},
        {"id": 3, "blueprint_type_id": 3000, "product_type_id": 36},
        {"id": 4, "blueprint_type_id": 4000, "product_type_id": 37},
    ]
    assert im.get_blueprint_status_map(rows) == {
        1: "库中有成品 · 正在制造",  # 库存有 34；在跑计划 9 绑的正是这一行
        2: "有挂单",  # 买单也算
        3: "-",  # 计划 10 是 pending → 不算「正在」
        4: "-",  # 库存 0、挂单剩余 0
    }


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
    # 列定义与模型表头一一配对（zip(strict=True) → 项数不一致会当场 ValueError），
    # 且表头对齐读的是元数据里的 alignRight（QML 侧不再按列号区间特判）
    assert [c["title"] for c in bridge.itemColumns] == InvTableModel._HEADERS
    assert bridge.itemColumns[1]["alignRight"] is False
    assert bridge.itemColumns[6]["alignRight"] is True  # 「缺口」数值列右对齐


@pytest.mark.ui
def test_on_shown_picks_up_hangars_created_after_load(bridge, monkeypatch):
    """回归：新建的机库必须在仓库管理页里出现（页面重新可见时重取一次列表）。

    原先本页只在构造时读一次 `hangars`、也没有 `on_shown` 钩子 —— 用户在「机库设置」里
    建完机库回到仓库管理，看不到它（2026-10-06 报）。
    """
    import services.inventory_manager as im

    assert bridge.hangarNames == ["A 库", "B 库"]
    monkeypatch.setattr(
        im,
        "get_hangars",
        lambda: [{"id": 1, "name": "A 库"}, {"id": 2, "name": "B 库"}, {"id": 9, "name": "研发"}],
    )

    bridge.on_shown()

    assert bridge.hangarNames == ["A 库", "B 库", "研发"]


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


@pytest.mark.ui
def test_blueprint_status_column_is_batched(bridge, monkeypatch):
    """「状态」列：桥把**整批行**交给一次批量查询，再按蓝图行 id 回填。

    蓝图表 1300+ 行，逐行查会卡死 —— 所以这里断言的是「传了什么参数」（一次拿到整批行、
    按行 id 回填），而不是查询被调用几次。
    """
    import services.inventory_manager as im

    seen: dict[int, int | None] = {}

    def fake_status_map(rows: list[dict]) -> dict[int, str]:
        seen.update({r["id"]: r.get("product_type_id") for r in rows})
        return {7: "库中有成品 · 正在制造"}

    monkeypatch.setattr(im, "get_blueprints", lambda hid=None: [{**_bp(bpid=7, bp_type_id=1000), "occupied": False}])
    monkeypatch.setattr(
        im,
        "get_blueprint_product_info_batch",
        lambda ids: {
            1000: {"product_type_id": 34, "product_name": "三钛合金", "product_quantity": 100, "base_time": 60}
        },
    )
    monkeypatch.setattr(im, "get_blueprint_status_map", fake_status_map)
    bridge.loadBlueprints()

    assert seen == {7: 34}
    model = bridge.blueprintModel
    assert model.rowCount() == 1
    assert model.data(model.index(0, 12), _B_TEXT) == "库中有成品 · 正在制造"
    # 列定义与模型表头一一配对；表头对齐读元数据
    assert [c["title"] for c in bridge.blueprintColumns] == BlueprintTableModel._HEADERS
    assert bridge.blueprintColumns[10]["title"] == "每流程利润"
    assert bridge.blueprintColumns[10]["alignRight"] is True
    assert bridge.blueprintColumns[12]["title"] == "状态"
    assert bridge.blueprintColumns[12]["alignRight"] is False


# ════════════════════════════════════════════════════════════
#  剪贴板全量同步的预览（回归：库里有、剪贴板没有 → 待清零项）
# ════════════════════════════════════════════════════════════


class _ReviewMarketRepo:
    """审阅桥的最小市价替身（本组用例不关心价格）。"""

    def get_sell_prices(self, type_ids: list, region_id: int) -> dict[int, float]:
        return {}


@pytest.fixture
def _review_bridge(qapp, monkeypatch):
    """目标机库 7 = {34: 1000, 41484: 6}；剪贴板只复制了 34。

    `41484 旗舰级电容器电池 I` 就是用户报的那 6 个残留电池：它必须在预览里
    以 `final=0`、默认勾选的形式出现，否则「全量同步」就是静默留档。
    """
    import ui_qml.bridge.review_bridge as mod

    hangar = [
        {"type_id": 34, "quantity": 1000, "cost_price": 5.0, "zh_name": "三钛合金"},
        {"type_id": 41484, "quantity": 6, "cost_price": 2460055.19, "zh_name": "旗舰级电容器电池 I"},
    ]
    parsed = [{"type_id": 34, "zh_name": "三钛合金", "en_name": "Tritanium", "qty": 1000, "status": "matched"}]
    monkeypatch.setattr(mod, "get_items", lambda hangar_id, **_kw: list(hangar) if hangar_id == 7 else [])
    monkeypatch.setattr(mod, "get_container", lambda: SimpleNamespace(market_repo=_ReviewMarketRepo()))
    monkeypatch.setattr(mod, "get_hangars", lambda: [{"id": 7, "name": "通用仓库"}])
    monkeypatch.setattr(mod, "get_material_price_mult", lambda: 1.0)
    return mod.ImportReviewBridge(parsed, "通用仓库", 7, default_mode="full")


def test_full_sync_preview_lists_rows_missing_from_clipboard(_review_bridge):
    """回归：全量同步原先只对剪贴板里出现过的物品做 set，「库里有、剪贴板没有」整类不动。

    现在这类物品必须在预览里可见（名称 + 现有数量 + 目标 0）、默认勾选、可取消，
    并在 `get_clear_missing()` 里作为待清零项报给落库层。默认「只看有变更的行」时
    剪贴板那行（34：1000 = 库内 1000，无变化）被隐藏，待清零行仍在。
    """
    b = _review_bridge
    assert [r["typeId"] for r in b.rows] == [41484], "待清零项必须可见（不能静默留档）"
    zero = b.rows[0]
    assert zero["missing"] is True
    assert (zero["typeId"], zero["name"], zero["current"], zero["final"], zero["delta"]) == (
        41484,
        "旗舰级电容器电池 I",
        6,
        0,
        -6,
    )
    assert zero["checked"] is True, "默认勾选（用户可取消）"
    assert zero["checkable"] is True
    assert b.get_clear_missing() == {41484: 6}, "待清零项的值 = 该行现有数量"
    assert "旗舰级电容器电池 I" in b.clear_missing_text()
    assert "现有 6" in b.clear_missing_text()
    assert "1 项" in b.summaryText and "清零" in b.summaryText

    # 关掉「只看有变更的行」→ 无变化的那行也要能核对；过滤不改清零清单
    b.setOnlyChanged(False)
    assert [r["typeId"] for r in b.rows] == [34, 41484]
    assert b.get_clear_missing() == {41484: 6}


def test_full_sync_clear_targets_respect_uncheck_and_manual_target(_review_bridge):
    """取消勾选 → 不清零；把「变化」列改成 3 → 走全量 set（设为 3）而不是删。"""
    b = _review_bridge
    b.setOnlyChanged(False)  # 本用例按行号操作 → 先让全部行可见
    assert [r["typeId"] for r in b.rows] == [34, 41484]
    b.setChecked(1, False)
    assert b.get_clear_missing() == {}
    assert b.clear_missing_text() == ""
    assert 41484 not in b.get_sync_targets(), "取消勾选的行不许参与全量 set（否则仍会被清零）"

    b.setChecked(1, True)
    b.setFinal(1, 3)
    assert b.get_clear_missing() == {}, "用户显式改成 3 → 不再算待清零项"
    assert b.get_sync_targets() == {34: 1000, 41484: 3}


def test_same_item_multiple_stacks_are_summed_not_overwritten(qapp, monkeypatch):
    """回归（用户报障）：剪贴板里同一种物品有**多堆**时必须相加。

    EVE 的「物品」列表里同一种东西可以有多堆，复制出来就是多行同名物品；而 full 模式的
    落库是 `set_item_quantity(type_id, 最终数量)` —— **覆盖写**。不合并的话后一行会把前一行
    覆盖掉，只剩最后一堆。实测：莫尔石 2999 + 184 + 176 只写进了 176，于是待采购报
    「需求 3175 − 176 = 2999」，用户看到的是「我库里明明有 2999，却让我买 2999」。
    """
    import ui_qml.bridge.review_bridge as mod

    hangar = [{"type_id": 11399, "quantity": 10, "cost_price": 17980.0, "zh_name": "莫尔石"}]
    parsed = [
        {"type_id": 11399, "zh_name": "莫尔石", "en_name": "Morphite", "qty": 2999, "status": "matched"},
        {"type_id": 11399, "zh_name": "莫尔石", "en_name": "Morphite", "qty": 184, "status": "matched"},
        {"type_id": 11399, "zh_name": "莫尔石", "en_name": "Morphite", "qty": 176, "status": "matched"},
    ]
    monkeypatch.setattr(mod, "get_items", lambda hangar_id, **_kw: list(hangar) if hangar_id == 7 else [])
    monkeypatch.setattr(mod, "get_container", lambda: SimpleNamespace(market_repo=_ReviewMarketRepo()))
    monkeypatch.setattr(mod, "get_hangars", lambda: [{"id": 7, "name": "通用仓库"}])
    monkeypatch.setattr(mod, "get_material_price_mult", lambda: 1.0)

    b = mod.ImportReviewBridge(parsed, "通用仓库", 7, default_mode="full")
    b.setOnlyChanged(False)

    assert [r["typeId"] for r in b.rows] == [11399], "三堆要合成一行，不能变成三行"
    row = b.rows[0]
    assert row["final"] == 3359, "full 模式的目标数量 = 三堆之和（旧实现只留最后一堆 176）"
    assert b.get_sync_targets() == {11399: 3359}
    assert "2,999" in row["mergedText"] and "3,359" in row["mergedText"], "要看得见每一堆各是多少"


def test_incremental_mode_has_no_clear_targets(qapp, monkeypatch):
    """incremental 只增不减：预览里根本不出现待清零行。"""
    import ui_qml.bridge.review_bridge as mod

    monkeypatch.setattr(
        mod,
        "get_items",
        lambda hangar_id, **_kw: [{"type_id": 41484, "quantity": 6, "cost_price": 1.0, "zh_name": "电池"}],
    )
    monkeypatch.setattr(mod, "get_container", lambda: SimpleNamespace(market_repo=_ReviewMarketRepo()))
    monkeypatch.setattr(mod, "get_material_price_mult", lambda: 1.0)
    bridge = mod.ImportReviewBridge(
        [{"type_id": 34, "zh_name": "三钛合金", "qty": 5, "status": "matched"}],
        "通用仓库",
        7,
        default_mode="incremental",
    )
    assert [r for r in bridge.rows if r.get("missing")] == []
    assert bridge.get_clear_missing() == {}


# ════════════════════════════════════════════════════════════
#  「只看有变更的行」（回归：几百行里看不出哪几行真的会变）
# ════════════════════════════════════════════════════════════


@pytest.fixture
def _review_bridge_mixed(qapp, monkeypatch):
    """3 行：34 有变化（库 1000 → 剪贴板 700）、35 无变化（库 20 → 剪贴板 20）、1 行未匹配。"""
    import ui_qml.bridge.review_bridge as mod

    hangar = [
        {"type_id": 34, "quantity": 1000, "cost_price": 5.0, "zh_name": "三钛合金"},
        {"type_id": 35, "quantity": 20, "cost_price": 11.0, "zh_name": "类晶体胶矿"},
    ]
    parsed = [
        {"type_id": 34, "zh_name": "三钛合金", "en_name": "Tritanium", "qty": 700, "status": "matched"},
        {"type_id": 35, "zh_name": "类晶体胶矿", "en_name": "Pyerite", "qty": 20, "status": "matched"},
        {"type_id": None, "raw_name": "神秘物品", "zh_name": "", "en_name": "", "qty": 3, "status": "unmatched"},
    ]
    prices = {34: 5.5, 35: 12.0}
    monkeypatch.setattr(mod, "get_items", lambda hangar_id, **_kw: list(hangar) if hangar_id == 7 else [])
    monkeypatch.setattr(
        mod,
        "get_container",
        lambda: SimpleNamespace(
            market_repo=SimpleNamespace(get_sell_prices=lambda ids, region: {t: prices[t] for t in ids if t in prices})
        ),
    )
    monkeypatch.setattr(mod, "get_material_price_mult", lambda: 1.0)
    return mod.ImportReviewBridge(parsed, "通用仓库", 7, default_mode="full")


def test_preview_defaults_to_rows_that_change_something(_review_bridge_mixed):
    """默认「只看有变更的行」：无变化那行隐藏；未匹配行必须照样可见。

    回归背景（用户原话）：「导入预览应该只显示有变更的，而不是全部显示。这样根本看不出来
    哪些是变更的。」整仓粘贴几百行时，一屏几百行里找不出真正会动的那几行。
    """
    b = _review_bridge_mixed
    assert [r["typeId"] for r in b.rows] == [34, None], "默认视图 = 变化行(34) + 未匹配行"
    assert len(b._all_rows) == 3, "提交真源仍是全部 3 行"
    assert "已隐藏 1 行无变化" in b.summaryText

    # 汇总口径不变：总增减 = **全部行**之和（过滤不能让数字变小）
    all_delta = sum(int(r["delta"]) for r in b._all_rows)
    assert all_delta == -300, "34: 700-1000=-300；35 与未匹配行都是 0"
    assert f"总增减 {all_delta:,}" in b.summaryText
    assert "总计 3 项" in b.summaryText

    # 提交内容不变：仍是全部行的勾选结果（未匹配行没有 type_id，本就不参与提交）
    assert b.get_import_data() == [(34, -300, 5.5, None), (35, 0, 12.0, None)]
    assert b.get_sync_targets() == {34: 700, 35: 20}

    # 关掉开关 → 全部 3 行都在（用户要能核对）
    b.setOnlyChanged(False)
    assert len(b.rows) == 3
    assert "已隐藏" not in b.summaryText
    assert b.get_import_data() == [(34, -300, 5.5, None), (35, 0, 12.0, None)], "切开关不改提交内容"

    # 增量模式：判据是「增量 ≠ 0」；未匹配行仍恒显示
    b.setModeIndex(0)  # _MODES[0] = incremental
    assert [r["typeId"] for r in b.rows] == [34, 35, None]


# ════════════════════════════════════════════════════════════
#  库存修正的编排（回归：解析/落库必须离开主线程 + 清零确认门）
# ════════════════════════════════════════════════════════════


def _stub_import_threads(monkeypatch):
    """打桩「剪贴板 → 解析 → 落库」三段，记录各自跑在哪个线程。

    返回 (记录表, 预览替身类, 汇总替身类)。三个桩都**不**碰真库：
    `run_clipboard_import` 只该在 worker 线程里调它们（用户报的「卡死」就是它们在主线程跑）。
    """
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QDialog

    import ui_qml.bridge.review_bridge as mod
    import ui_qml.workers.inventory_import_worker as worker_mod

    seen: dict = {"apply_calls": []}
    calls = {"n": 0}

    def _parse(raw: str):
        seen["parse_thread"] = QThread.currentThread()
        return [{"type_id": 34, "zh_name": "三钛合金", "en_name": "Tritanium", "qty": 1000, "status": "matched"}], 0

    def _get_items(hangar_id, **_kw):
        seen.setdefault("get_items_thread", QThread.currentThread())
        calls["n"] += 1
        # 第 1 次 = 导入前快照 1000；之后 = 导入后 1010（模拟落库加了 10）
        return [
            {"type_id": 34, "quantity": 1000 + (10 if calls["n"] > 1 else 0), "cost_price": 5.0, "zh_name": "三钛合金"}
        ]

    def _apply(hangar_id, data, mode, targets, clear_missing=None):
        seen["apply_thread"] = QThread.currentThread()
        seen["apply_calls"].append((hangar_id, data, mode, targets, clear_missing))
        return 1, 0

    monkeypatch.setattr(worker_mod, "parse_clipboard", _parse)
    monkeypatch.setattr(worker_mod, "get_items", _get_items)
    monkeypatch.setattr(worker_mod, "apply_inventory_import", _apply)
    monkeypatch.setattr(
        worker_mod,
        "get_container",
        lambda: SimpleNamespace(market_repo=SimpleNamespace(get_sell_prices=lambda ids, region: {34: 5.5})),
    )

    class _Clipboard:
        def text(self) -> str:
            return "三钛合金\t1000\n"

    monkeypatch.setattr(
        mod,
        "QApplication",
        SimpleNamespace(
            clipboard=lambda: _Clipboard(),
            setOverrideCursor=lambda *_: None,
            restoreOverrideCursor=lambda: None,
        ),
    )

    class _Preview:
        last: dict = {}
        reenter_hook = None
        seen_exec = False

        def __init__(self, items, hangar_name, target_hangar_id, parent=None, **kw):
            _Preview.last = {"items": items, "prefetched": kw.get("prefetched")}

        def exec(self) -> int:
            if not _Preview.seen_exec and _Preview.reenter_hook is not None:
                _Preview.seen_exec = True
                _Preview.reenter_hook()  # 模拟「等待期间又被触发一次导入」
            return QDialog.DialogCode.Accepted

        def get_import_data(self):
            return [(34, 0, 5.0, None)]

        def mode(self) -> str:
            return "full"

        def get_sync_targets(self):
            return {34: 1000}

        def get_clear_missing(self):
            return {}

        def clear_missing_text(self) -> str:
            return ""

    class _Change:
        last: dict = {}

        def __init__(self, changes, added, moved, hangar_name, parent=None):
            _Change.last = {"changes": changes, "added": added, "moved": moved}

        def exec(self) -> int:
            return 0

    class _Box:
        calls: list = []
        answer = True

        @staticmethod
        def warning(_parent, _title, text, *a, **kw):
            _Box.calls.append(("warning", text))

        @staticmethod
        def information(_parent, _title, text, *a, **kw):
            _Box.calls.append(("information", text))

        @staticmethod
        def question(_parent, _title, text, *a, **kw):
            _Box.calls.append(("question", text, kw.get("default_yes")))
            return _Box.answer

    monkeypatch.setattr(mod, "ImportReviewQmlDialog", _Preview)
    monkeypatch.setattr(mod, "ImportChangeQmlDialog", _Change)
    monkeypatch.setattr(mod, "FMessageDialog", _Box)
    return seen, _Preview, _Change, _Box


def test_run_clipboard_import_keeps_blocking_work_off_the_main_thread(qapp, monkeypatch):
    """端到端：解析/取数/落库都在 worker 线程，主线程只弹预览与汇总。

    回归背景：用户报「库存修正会导致整个软件卡死并进行计算」—— 原先
    `parse_clipboard`（整仓名字匹配，秒级）/ `get_items` / `apply_inventory_import`
    全在主线程同步跑。这里用桩记录 `QThread.currentThread()` 做断言（不逐信号断言）。
    """
    from PySide6.QtCore import QThread

    import ui_qml.bridge.review_bridge as mod

    seen, preview, change, box = _stub_import_threads(monkeypatch)
    main_thread = QThread.currentThread()

    # 重入守卫：预览 exec() 里再触发一次导入（模拟「嵌套事件循环期间又被点一次」）
    preview.reenter_hook = lambda: mod.run_clipboard_import(7, "通用仓库", None, mode="full")

    mod.run_clipboard_import(7, "通用仓库", None, mode="full")

    assert seen.get("parse_thread") is not None, "没走到解析"
    assert seen["parse_thread"] is not main_thread, "解析仍在主线程（会卡界面）"
    assert seen["get_items_thread"] is not main_thread, "取库存仍在主线程"
    assert seen.get("apply_thread") is not None, "没走到落库"
    assert seen["apply_thread"] is not main_thread, "落库仍在主线程"
    # 主线程只负责弹窗：预览拿到 worker 预取的整库快照（不再自己查库）+ 汇总收到结果
    assert preview.last["prefetched"]["existing_qty"] == {34: 1000}
    assert [c[0] for c in seen["apply_calls"]] == [7], "重入的第二次调用不许产生第二轮落库"
    assert any("正在导入" in text for _kind, text in box.calls), "重入必须给用户可见提示"
    assert change.last["added"] == 1 and change.last["moved"] == 0
    assert change.last["changes"], "导入后的变动汇总必须有行"


def test_run_clipboard_import_clear_confirm_declined_writes_nothing(qapp, monkeypatch):
    """清零确认门：点「否」→ 一行都不写；点「是」→ 带着 clear_missing 落库。"""
    import ui_qml.bridge.review_bridge as mod

    seen, _preview, _change, box = _stub_import_threads(monkeypatch)

    class _PreviewWithClear:
        """预览替身：报出一个待清零项（库里有 41484=6、剪贴板没有）。"""

        def __init__(self, items, hangar_name, target_hangar_id, parent=None, **kw):
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def get_import_data(self):
            return [(34, 0, 5.0, None)]

        def mode(self):
            return "full"

        def get_sync_targets(self):
            return {34: 1000}

        def get_clear_missing(self):
            return {41484: 6}

        def clear_missing_text(self):
            return "以下 1 项在你的机库里、但不在本次剪贴板中"

    monkeypatch.setattr(mod, "ImportReviewQmlDialog", _PreviewWithClear)

    box.answer = False
    mod.run_clipboard_import(7, "通用仓库", None, mode="full")
    assert seen["apply_calls"] == [], "确认点「否」时不许写库"
    assert box.calls[-1][0] == "question"
    assert box.calls[-1][2] is False, "破坏性操作的确认框必须 default_yes=False"

    box.answer = True
    mod.run_clipboard_import(7, "通用仓库", None, mode="full")
    assert len(seen["apply_calls"]) == 1, "确认点「是」才落库"
    assert seen["apply_calls"][0][4] == {41484: 6}, "待清零项必须原样传给 service"


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

    with page_host("pages/StoragePage.qml", InventoryBridge(None)) as pair:
        yield pair


@pytest.mark.ui
def test_page_loads_and_is_quiet(storage_page):
    """能加载 + 桥到位 + 不给 Qt 刷告警（共用实现见 `tests/qml_page_load.py`）。"""
    host, bridge = storage_page
    assert_page_loads_quietly(host, bridge, key="inv", size=(1400, 800))


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

    model.sort(11, Qt.SortOrder.DescendingOrder)  # 利润率降序
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
