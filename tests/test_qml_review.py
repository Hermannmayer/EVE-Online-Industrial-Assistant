"""剪贴板导入审阅链路的业务契约（阶段 4b-3）。

只放**业务**断言：行增减与着色、未匹配行、勾选与统计、右键菜单状态、批量改价、
删除 / 过滤、导入数据与全量目标、变动汇总文案、桥的属性与槽。

「QML 能不能加载、有没有 Qt 告警」那条护栏不放这里 —— 统一由主流程加进
`tests/test_qml_dialogs.py`（与其它对话框同一处）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.ui

#: 目标机库现有物品（`get_items` 的桩）
_TARGET_ITEMS: list[dict] = [{"type_id": 34, "quantity": 1000, "cost_price": 5.0, "zh_name": "三钛合金"}]
#: 另一个机库的物品（「来自其他机库」的来源）
_SOURCE_ITEMS: list[dict] = [{"type_id": 35, "quantity": 20, "cost_price": 11.0, "zh_name": "类晶体胶矿"}]
#: 解析后的剪贴板行：一行已匹配 + 一行未匹配
_PARSED: list[dict] = [
    {"type_id": 34, "zh_name": "三钛合金", "en_name": "Tritanium", "qty": 500, "status": "matched"},
    {"type_id": None, "raw_name": "神秘物品", "zh_name": "", "en_name": "", "qty": 3, "status": "unmatched"},
]
_SELL = {34: 5.5, 35: 12.0}


class _MarketRepo:
    """`market_repo` 的最小替身：卖单价表 + 按区域取价，调用都留痕。"""

    def __init__(self) -> None:
        self.sell_calls: list[tuple[list[int], int]] = []
        self.region_calls: list[tuple[int, str, int]] = []
        #: (type_id, price_type) → 价格；缺省视为「无数据」
        self.prices: dict[tuple[int, str], float] = {}

    def get_sell_prices(self, type_ids: list[int], region_id: int) -> dict[int, float]:
        self.sell_calls.append((list(type_ids), region_id))
        return {t: _SELL[t] for t in type_ids if t in _SELL}

    def get_price_by_region(self, type_id: int, price_type: str, region_id: int) -> float | None:
        self.region_calls.append((type_id, price_type, region_id))
        return self.prices.get((type_id, price_type))


class _BoxRecorder:
    """`QMessageBox` 替身：这几处刻意保留 QMessageBox（批量迁移是另一个批次），只记录调用。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def warning(self, _parent: Any, _title: str, text: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("warning", text))

    def information(self, _parent: Any, _title: str, text: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("information", text))


class _Harness:
    """桥 + 它的桩（市价库 / 倍率写入 / 消息框记录）。"""

    def __init__(self, bridge: Any, repo: _MarketRepo, mult_writes: list[float], box: _BoxRecorder) -> None:
        self.bridge = bridge
        self.repo = repo
        self.mult_writes = mult_writes
        self.box = box

    def cells(self, row: int) -> dict:
        return dict(self.bridge.rows[row])


@pytest.fixture
def harness(qapp, monkeypatch) -> _Harness:
    """造一个「目标机库 7 / 另一机库 8」的审阅桥，`get_items` 按机库返回不同清单。"""
    import ui_qml.bridge.review_bridge as mod

    repo = _MarketRepo()
    mult_writes: list[float] = []
    box = _BoxRecorder()

    monkeypatch.setattr(mod, "get_items", lambda hangar_id: list({7: _TARGET_ITEMS, 8: _SOURCE_ITEMS}[hangar_id]))
    monkeypatch.setattr(mod, "get_container", lambda: SimpleNamespace(market_repo=repo))
    monkeypatch.setattr(mod, "get_hangars", lambda: [{"id": 7, "name": "矿仓"}, {"id": 8, "name": "组件仓"}])
    monkeypatch.setattr(mod, "set_material_price_mult", mult_writes.append)
    monkeypatch.setattr(mod, "QMessageBox", box)
    monkeypatch.setattr(mod, "get_material_price_mult", lambda: 0.9)

    bridge = mod.ImportReviewBridge(_PARSED, "矿仓", 7, default_mode="full", filtered_note=2)
    return _Harness(bridge, repo, mult_writes, box)


def _pick_factory(picked: list[tuple[int, int]], accepted: bool = True) -> Any:
    """`HangarPickQmlDialog` 的替身（「来自其他机库」的第二级弹出）。"""

    class _FakePick:
        def __init__(self, source_items: list[dict], parent: Any = None) -> None:
            self.source_items = source_items

        def exec(self) -> int:
            return 1 if accepted else 0

        def selected_items(self) -> list[tuple[int, int]]:
            return list(picked)

    return _FakePick


# ════════════════════════════════════════════════════════════════
#  行装配（纯函数）
# ════════════════════════════════════════════════════════════════


def test_review_row_full_mode_uses_target_quantity():
    """全量同步：final = 剪贴板数量，增减 = 目标数量 − 现有。"""
    from ui_qml.bridge.review_bridge import review_row

    row = review_row(_PARSED[0], current=1000, sell_price=5.5, mode="full", source_hangar_id=None)
    assert row["final"] == 500
    assert row["delta"] == -500
    assert row["deltaText"] == "-500"
    assert row["deltaToken"] == "ACCENT_RED"
    assert row["currentText"] == "1,000"
    assert row["checked"] is True and row["checkable"] is True and row["unmatched"] is False
    assert row["price"] == 5.5


def test_review_row_incremental_mode_accumulates():
    """增量累加：final = 现有 + 剪贴板数量，增减为正 → 绿。"""
    from ui_qml.bridge.review_bridge import review_row

    row = review_row(_PARSED[0], current=1000, sell_price=5.5, mode="incremental", source_hangar_id=None)
    assert row["final"] == 1500
    assert row["delta"] == 500
    assert row["deltaText"] == "+500"
    assert row["deltaToken"] == "ACCENT_GREEN"


def test_review_row_zero_delta_has_no_colour():
    """增减为 0 时不给颜色（对齐原版不设 ForegroundRole）。"""
    from ui_qml.bridge.review_bridge import review_row

    row = review_row(_PARSED[0], current=500, sell_price=0.0, mode="full", source_hangar_id=None)
    assert row["delta"] == 0 and row["deltaToken"] == ""


def test_review_row_unmatched_is_greyed_and_uncheckable():
    """未匹配行：名称带「（未匹配）」、勾选禁用、数值 0、次要色。"""
    from ui_qml.bridge.review_bridge import review_row

    row = review_row(_PARSED[1], current=0, sell_price=0.0, mode="full", source_hangar_id=None)
    assert row["typeId"] is None
    assert row["name"] == "神秘物品（未匹配）"
    assert row["checked"] is False and row["checkable"] is False and row["unmatched"] is True
    assert (row["current"], row["delta"], row["final"]) == (0, 0, 0)
    assert row["deltaToken"] == "TEXT_SECONDARY" and row["iconUrl"] == ""


# ════════════════════════════════════════════════════════════════
#  桥：初始状态
# ════════════════════════════════════════════════════════════════


def test_review_bridge_loads_rows_and_summary(harness: _Harness):
    b = harness.bridge
    assert b.mode() == "full"
    assert b.modeIndex == 1
    assert [h["label"] for h in b.hubs][0] == "Jita (吉他)"
    assert b.discount == 0.9
    assert len(b.rows) == 2
    assert b.rows[0]["name"] == "三钛合金"
    assert b.summaryText == "[已过滤 2 行蓝图] 已勾选 1 项 / 总计 2 项 / 总增减 -500 / 预估成本 -2,750 ISK"
    # 未匹配行不计入勾选统计
    assert "已勾选 1 项" in b.summaryText


def test_review_bridge_mode_switch_recomputes(harness: _Harness):
    b = harness.bridge
    b.setModeIndex(0)  # 增量累加
    assert b.mode() == "incremental"
    assert b.rows[0]["final"] == 1500 and b.rows[0]["delta"] == 500
    b.setModeIndex(1)
    assert b.rows[0]["final"] == 500 and b.rows[0]["delta"] == -500


def test_review_bridge_hub_switch_refetches_prices(harness: _Harness):
    b = harness.bridge
    harness.repo.sell_calls.clear()
    b.setHubIndex(1)  # Amarr
    assert b.hubIndex == 1
    assert harness.repo.sell_calls == [([34], 10000043)]
    assert b.rows[0]["price"] == 5.5  # 只会取到桩里有的那一个价


def test_review_bridge_final_edit_recomputes_delta(harness: _Harness):
    b = harness.bridge
    b.setFinal(0, 1200)
    assert b.rows[0]["final"] == 1200
    assert b.rows[0]["delta"] == 200
    assert b.rows[0]["deltaText"] == "+200" and b.rows[0]["deltaToken"] == "ACCENT_GREEN"
    b.setFinal(0, 1000)
    assert b.rows[0]["delta"] == 0
    assert b.rows[0]["deltaToken"] == "TEXT_SECONDARY", "原版手改后归零用次要色"


def test_review_bridge_unmatched_row_cannot_be_edited_or_checked(harness: _Harness):
    b = harness.bridge
    b.setFinal(1, 999)
    assert b.rows[1]["final"] == 0, "未匹配行没有可编辑的数量"
    b.setChecked(1, True)
    assert b.rows[1]["checked"] is False


def test_review_bridge_select_all_skips_unmatched(harness: _Harness):
    b = harness.bridge
    b.setAllChecked(False)
    assert [r["checked"] for r in b.rows] == [False, False]
    assert "已勾选 0 项" in b.summaryText
    b.setAllChecked(True)
    assert [r["checked"] for r in b.rows] == [True, False]
    assert "已勾选 1 项" in b.summaryText


def test_review_bridge_import_data_and_sync_targets(harness: _Harness):
    b = harness.bridge
    assert b.get_import_data() == [(34, -500, 5.5, None)]
    assert b.get_sync_targets() == {34: 500}
    b.setChecked(0, False)
    assert b.get_import_data() == []
    assert b.get_sync_targets() == {}


def test_review_bridge_delete_rows(harness: _Harness):
    b = harness.bridge
    b.openMenu([0])
    b.deleteRows()
    assert len(b.rows) == 1
    assert b.rows[0]["unmatched"] is True
    assert b.get_import_data() == []


def test_review_bridge_filter_no_change_keeps_the_original_count(harness: _Harness):
    """过滤无变化项：未匹配行无增量也算进「已过滤 N 项」（原版口径，照搬不修）。"""
    b = harness.bridge
    b.setModeIndex(0)
    b.setFinal(0, 1000)  # delta 归零
    b.filterNoChange()
    assert b.rows[0]["checked"] is False
    assert b.summaryText.endswith("[已过滤 2 项无变化]"), b.summaryText


# ════════════════════════════════════════════════════════════════
#  桥：右键菜单
# ════════════════════════════════════════════════════════════════


def test_review_menu_state_excludes_the_target_hangar(harness: _Harness):
    b = harness.bridge
    state = b.menuState([0])
    assert [h["id"] for h in state["hangars"]] == [8]
    assert state["single"] is True and state["count"] == 1
    assert state["canSearchMatch"] is False, "已匹配行不给「搜索匹配」"
    assert state["discountText"] == "90%"

    unmatched = b.menuState([1])
    assert unmatched["canSearchMatch"] is True

    multi = b.menuState([0, 1])
    assert multi["single"] is False and multi["canSearchMatch"] is False


def test_review_menu_discount_text_follows_the_multiplier(harness: _Harness):
    b = harness.bridge
    b.setDiscount(0.85)
    assert b.menuState([])["discountText"] == "85%"


def test_review_set_price_from_market_and_discount(harness: _Harness):
    b = harness.bridge
    harness.repo.prices[(34, "buy")] = 4.0
    b.openMenu([0])
    b.setPriceFromMarket("buy")
    assert b.rows[0]["price"] == 4.0
    assert harness.repo.region_calls == [(34, "buy", 10000002)]

    b.applyDiscount("buy")
    assert b.rows[0]["price"] == 3.6  # 4.0 × 0.9，四舍五入到两位


def test_review_set_price_from_market_without_data_warns(harness: _Harness):
    """取不到价就逐行提示（原版走 QMessageBox.information，这里保留 QMessageBox）。"""
    b = harness.bridge
    b.openMenu([0])
    b.setPriceFromMarket("sell")
    assert harness.box.calls == [("information", "未找到该物品在所选区域的价格数据")]
    assert b.rows[0]["price"] == 5.5, "取不到价不动原值"


# ════════════════════════════════════════════════════════════════
#  桥：跨机库移入
# ════════════════════════════════════════════════════════════════


def test_review_add_from_hangar_keeps_move_semantics(harness: _Harness, monkeypatch):
    """移入的行恒按增量语义，且不参与全量 set（`get_sync_targets` 要跳过它）。"""
    import ui_qml.bridge.review_bridge as mod

    monkeypatch.setattr(mod, "HangarPickQmlDialog", _pick_factory([(35, 20)]))
    b = harness.bridge
    b.addFromHangar(8)

    assert len(b.rows) == 3
    moved = b.rows[2]
    assert moved["typeId"] == 35 and moved["delta"] == 20 and moved["final"] == 20
    assert moved["deltaToken"] == "ACCENT_GREEN"
    assert moved["price"] == 12.0
    assert b.get_import_data()[-1] == (35, 20, 12.0, 8)
    assert 35 not in b.get_sync_targets()
    assert 34 in b.get_sync_targets()


def test_review_add_from_hangar_cancel_changes_nothing(harness: _Harness, monkeypatch):
    import ui_qml.bridge.review_bridge as mod

    monkeypatch.setattr(mod, "HangarPickQmlDialog", _pick_factory([(35, 20)], accepted=False))
    b = harness.bridge
    b.addFromHangar(8)
    assert len(b.rows) == 2


def test_review_add_from_hangar_without_items_warns(harness: _Harness, monkeypatch):
    import ui_qml.bridge.review_bridge as mod

    monkeypatch.setattr(mod, "get_items", lambda hangar_id: [])
    harness.bridge.addFromHangar(8)
    assert harness.box.calls == [("information", "该机库中无物品")]


# ════════════════════════════════════════════════════════════════
#  桥：确认
# ════════════════════════════════════════════════════════════════


def test_review_accept_refuses_without_checked_rows(harness: _Harness):
    b = harness.bridge
    accepted: list[bool] = []
    b.accepted.connect(lambda: accepted.append(True))
    b.setAllChecked(False)
    b.accept()
    assert accepted == []
    assert harness.box.calls == [("warning", "没有勾选的物品，无法导入")]
    assert harness.mult_writes == [], "没勾选就不该写回倍率"


def test_review_accept_warns_about_unmatched_but_proceeds(harness: _Harness):
    """未匹配行只提示、不拦截（原版提示完继续 accept）。"""
    b = harness.bridge
    accepted: list[bool] = []
    b.accepted.connect(lambda: accepted.append(True))
    b._rows[1]["checked"] = True  # 强行勾上未匹配行（正常路径进不来）
    b.setDiscount(0.8)
    b.accept()
    assert harness.box.calls == [("information", "1 行未匹配物品未指定 type_id，导入时将跳过（可右键搜索匹配）")]
    assert accepted == [True]
    assert harness.mult_writes == [0.8], "倍率写回共享设置"


def test_review_search_match_replaces_the_unmatched_row(harness: _Harness, monkeypatch):
    """搜索匹配：把那行接到选中物品上，然后重取库存/市价并整表重填。"""
    import ui_qml.bridge.item_search_bridge as search_mod

    class _FakeSearch:
        def __init__(self, parent: Any = None, title: str = "") -> None: ...

        def exec(self) -> int:
            return 1

        def selected_item(self) -> dict:
            return {"type_id": 35, "zh_name": "类晶体胶矿", "en_name": "Pyerite"}

    monkeypatch.setattr(search_mod, "ItemSearchQmlDialog", _FakeSearch)
    b = harness.bridge
    b.openMenu([1])
    b.searchMatch()
    assert b.rows[1]["typeId"] == 35
    assert b.rows[1]["name"] == "类晶体胶矿"
    assert b.rows[1]["price"] == 12.0
    assert b.rows[1]["checkable"] is True


# ════════════════════════════════════════════════════════════════
#  选择要移动的物品 / 变动汇总
# ════════════════════════════════════════════════════════════════


def test_hangar_pick_defaults_to_all_checked(qapp):
    from ui_qml.bridge.review_bridge import HangarPickBridge

    bridge = HangarPickBridge(_SOURCE_ITEMS)
    assert bridge.title_text() == "选择要移动的物品"
    row = bridge.rows[0]
    assert (row["typeId"], row["name"], row["qtyText"], row["checked"]) == (35, "类晶体胶矿", "20", True)
    bridge.setChecked(0, False)
    assert bridge.selected_items() == []
    bridge.setChecked(0, True)
    assert bridge.selected_items() == [(35, 20)]


def test_change_summary_matches_the_original_wording():
    from ui_qml.bridge.review_bridge import change_summary

    assert change_summary([], 3, 0) == "成功导入 3 条，数量/成本均无变化"
    changes = [{"qty_delta": 5}, {"qty_delta": -2}]
    assert change_summary(changes, 2, 1) == "共 2 项变化，增加 1，减少 1，成功导入 2 条，跨机库移动 1 条"
    assert change_summary(changes, 0, 0) == "共 2 项变化，增加 1，减少 1"


def test_change_rows_colour_by_direction():
    from ui_qml.bridge.review_bridge import change_rows

    rows = change_rows(
        [
            {
                "type_id": 34,
                "name": "三钛合金",
                "qty_before": 1000,
                "qty_after": 500,
                "cost_before": 5.0,
                "cost_after": 5.5,
                "qty_delta": -500,
                "cost_delta": 0.5,
            }
        ]
    )
    cells = rows[0]["cells"]
    assert cells[0]["text"] == "三钛合金"
    assert cells[1]["text"] == "1,000 → 500"
    assert cells[1]["color"] != "", "减量该标红"
    assert cells[2]["text"] == "5.00 → 5.50"
    assert cells[2]["color"] == "", "成本列不染色"


def test_import_change_bridge_puts_the_summary_in_the_header(qapp):
    from ui_qml.bridge.review_bridge import ImportChangeBridge

    bridge = ImportChangeBridge(
        [
            {
                "type_id": 34,
                "name": "三钛合金",
                "qty_before": 1000,
                "qty_after": 1500,
                "cost_before": 0.0,
                "cost_after": 0.0,
                "qty_delta": 500,
                "cost_delta": 0.0,
            }
        ],
        added=1,
        moved=0,
        hangar_name="矿仓",
    )
    bridge.reload()
    assert bridge.title_text() == "导入完成 — 矿仓"
    assert bridge.headerText == "共 1 项变化，增加 1，成功导入 1 条"
    assert bridge.statusText == ""
    assert bridge.rowCount == 1
    assert bridge.rows[0]["cells"][1]["color"] != ""


def test_import_change_bridge_empty_state(qapp):
    from ui_qml.bridge.review_bridge import ImportChangeBridge

    bridge = ImportChangeBridge([], added=2, moved=0, hangar_name="矿仓")
    bridge.reload()
    assert bridge.rowCount == 0
    assert bridge.headerText == "成功导入 2 条，数量/成本均无变化"
    assert bridge.emptyText == "数量/成本均无变化"
