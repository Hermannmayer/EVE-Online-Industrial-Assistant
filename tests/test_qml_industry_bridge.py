"""`IndustryBridge` 契约测试 —— 阶段 2b 页面骨架的桥。

接替已删除的 `TopToolbar` / `StatusBar` / `ActionButtons` / `GanttView` 那批断言：
统计文案、「全部下线」显隐、采购汇总文案、视图切换、价格设置、蓝图搜索防抖。
桥本身只是转发，故 `_page` 用 MagicMock 即可验证「有没有转到位」。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ui_qml.bridge.industry_bridge import FILTERS, PRICE_TYPES, IndustryBridge


@pytest.fixture
def bridge() -> IndustryBridge:
    return IndustryBridge(MagicMock())


# ════════════════════════════════════════════════════════════
#  状态栏统计（原 StatusBar.update_stats）
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_complete_all_hidden_without_ready(bridge):
    bridge.update_stats([{"status": "pending"}, {"status": "running"}])
    assert bridge.completeAllVisible is False


@pytest.mark.fast
def test_complete_all_shows_ready_count(bridge):
    bridge.update_stats(
        [
            {"status": "pending"},
            {"status": "ready"},
            {"status": "ready"},
            {"status": "running"},
        ]
    )
    assert bridge.completeAllVisible is True
    assert bridge.completeAllText == "全部下线 (2)"


@pytest.mark.fast
def test_stats_text_counts_each_bucket(bridge):
    bridge.update_stats(
        [
            {"status": "pending", "parallels": 2, "materials_ready": 1},
            {"status": "in_progress", "parallels": 3, "materials_ready": 1},
            {"status": "running", "parallels": 1, "materials_ready": 0},
            {"status": "ready", "parallels": 1, "materials_ready": 1},
        ]
    )
    # 产线(备料) 只累加已勾选备料的并行数：2 + 3 + 1 = 6（running 那条未勾选，不计）
    assert bridge.statusText == "计划总数: 4 | 运行中: 2 | 待排: 1 | 产线(备料): 6"
    assert bridge.planCountText == "共 4 条计划"


@pytest.mark.fast
def test_material_summary_text(bridge):
    bridge.update_material(1234567.0, 890.5)
    assert bridge.materialText == "备料中采购: 1,234,567 ISK | 体积: 890.5 m3"


@pytest.mark.fast
def test_message_overrides_stats_and_can_be_cleared(bridge):
    bridge.update_stats([{"status": "pending"}])
    bridge.show_message("正在获取价格...")
    assert bridge.statusText == "正在获取价格..."
    bridge.clear_message()
    assert bridge.statusText.startswith("计划总数:")


# ════════════════════════════════════════════════════════════
#  筛选 / 视图
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_filter_defaults_to_all_and_reloads_on_change(bridge):
    assert bridge.current_filter() == FILTERS[0] == "全部"
    bridge.setFilterIndex(2)
    assert bridge.current_filter() == FILTERS[2]
    bridge._page.load_plans.assert_called_once_with()


@pytest.mark.fast
def test_filter_index_is_clamped(bridge):
    bridge.setFilterIndex(999)
    assert bridge.filterIndex == len(FILTERS) - 1
    bridge.setFilterIndex(-5)
    assert bridge.filterIndex == 0


@pytest.mark.fast
def test_gantt_mode_hides_status_and_actions(bridge):
    assert bridge.viewMode == "data"
    assert bridge.statusVisible is True

    bridge.setViewMode("gantt")
    assert bridge.viewMode == "gantt"
    assert bridge.statusVisible is False
    bridge._page.refresh_gantt.assert_called_once_with()


@pytest.mark.fast
def test_unknown_view_mode_falls_back_to_data(bridge):
    bridge.setViewMode("nonsense")
    assert bridge.viewMode == "data"


# ════════════════════════════════════════════════════════════
#  价格设置
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_set_price_setting_persists_and_reloads(bridge, monkeypatch):
    saved: list[dict] = []
    monkeypatch.setattr("ui_qml.bridge.industry_bridge.get_price_settings", lambda: {"mat_hub": "Jita"})
    monkeypatch.setattr("ui_qml.bridge.industry_bridge.save_settings", lambda d: saved.append(d), raising=False)

    bridge.setPriceSetting("mat_hub", "Amarr")
    assert saved and saved[0]["price_settings"]["mat_hub"] == "Amarr"
    bridge._page.load_plans.assert_called_once_with()


@pytest.mark.fast
def test_set_price_setting_ignores_noop(bridge, monkeypatch):
    saved: list[dict] = []
    monkeypatch.setattr("ui_qml.bridge.industry_bridge.get_price_settings", lambda: {"mat_hub": "Jita"})
    monkeypatch.setattr("ui_qml.bridge.industry_bridge.save_settings", lambda d: saved.append(d), raising=False)

    bridge.setPriceSetting("mat_hub", "Jita")
    assert saved == [], "值没变不应写盘"


@pytest.mark.fast
def test_price_type_options_carry_value_and_label(bridge):
    assert {p["value"] for p in bridge.priceTypes} == {v for v, _ in PRICE_TYPES}


# ════════════════════════════════════════════════════════════
#  蓝图导入
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_short_query_clears_suggestions_without_searching(bridge, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr("ui_qml.workers.compare_chart.search_items", lambda t: calls.append(t) or [])

    bridge.requestSuggestions("钢")
    assert bridge.suggestions == []
    assert calls == [], "少于 2 个字不应触发搜索"


@pytest.mark.fast
def test_add_plan_ignores_blank(bridge):
    bridge.addPlan("   ")
    bridge._page.add_plan.assert_not_called()


@pytest.mark.fast
def test_add_plan_forwards_trimmed_text(bridge):
    bridge.addPlan("  狂怒级  ")
    bridge._page.add_plan.assert_called_once_with("狂怒级")


# ════════════════════════════════════════════════════════════
#  转发到位
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_action_buttons_forward_to_page(bridge):
    bridge.launchWizard()
    bridge.openProcurement()
    bridge.openBlueprintList()
    bridge.openMaterialsSummary()
    bridge.openOutputSummary()
    bridge.openCharUsage()
    bridge.refreshPrices()
    bridge.savePrices()
    bridge.completeAll()

    page = bridge._page
    page.open_launcher.assert_called_once_with(None)
    page.open_procurement.assert_called_once_with()
    page.open_blueprint_list.assert_called_once_with()
    page.open_materials_summary.assert_called_once_with()
    page.open_output_summary.assert_called_once_with()
    page.open_char_usage.assert_called_once_with()
    page.refresh_prices.assert_called_once_with()
    page.save_prices.assert_called_once_with()
    page.complete_all.assert_called_once_with()


@pytest.mark.fast
def test_gantt_rows_built_from_plans(bridge):
    bridge.set_gantt_plans(
        [{"id": 1, "product_name": "独立", "product_type_id": 2001, "calculated_time": 7200, "runs": 1}]
    )
    assert [r["name"] for r in bridge.ganttRows] == ["独立"]
    assert bridge.ganttMaxHours % 12 == 0


@pytest.mark.fast
def test_gantt_rows_empty_when_no_plans(bridge):
    bridge.set_gantt_plans([])
    assert bridge.ganttRows == []
