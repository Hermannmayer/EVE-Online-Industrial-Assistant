"""Bug A 回归测试 — 批量编辑不再把 runs/parallels 重置为 1X1 或首行值"""

import pytest

from services import inventory_manager

pytestmark = pytest.mark.ui


class TestBatchEditPreservesRuns:
    def _make_dialog(self, monkeypatch, plan_data):
        monkeypatch.setattr("ui_pyside6.views.industry.plan_edit_dialog.get_character_list", lambda: [])
        monkeypatch.setattr(inventory_manager, "get_hangars", lambda: [])
        from ui_pyside6.views.industry.plan_edit_dialog import PlanEditDialog

        return PlanEditDialog(
            None, plan_data, batch_mode=True, row_count=len(plan_data.get("_selected_rows", []) or [1])
        )

    def test_batch_mode_prefills_first_row_values(self, qapp, monkeypatch):
        """批量编辑弹窗用首行真实 runs/parallels 预填，而非硬编码 1。"""
        dlg = self._make_dialog(monkeypatch, {"_selected_rows": [0, 1], "runs": 5, "parallels": 3})
        assert dlg._runs_spin.value() == 5
        assert dlg._parallel_spin.value() == 3

    def test_batch_mode_defaults_to_none_not_writing(self, qapp, monkeypatch):
        """批量模式默认不写流程/并行（同步复选未勾 → runs/parallels 为 None）。"""
        dlg = self._make_dialog(monkeypatch, {"_selected_rows": [0, 1], "runs": 5, "parallels": 3})
        data = dlg.get_updated_data()
        assert data["runs"] is None
        assert data["parallels"] is None

    def test_batch_mode_sync_checkbox_returns_values(self, qapp, monkeypatch):
        """勾选「同步流程/并行」后返回首行 spin 值（显式同步）。"""
        dlg = self._make_dialog(monkeypatch, {"_selected_rows": [0, 1], "runs": 5, "parallels": 3})
        dlg._sync_runs_cb.setChecked(True)
        data = dlg.get_updated_data()
        assert data["runs"] == 5
        assert data["parallels"] == 3

    def test_batch_mode_defaults_to_one_when_missing(self, qapp, monkeypatch):
        """旧调用方未传 runs/parallels 时兜底 1（不崩溃）。"""
        dlg = self._make_dialog(monkeypatch, {"_selected_rows": [0]})
        assert dlg._runs_spin.value() == 1
        assert dlg._parallel_spin.value() == 1

    def test_non_batch_mode_uses_plan_values(self, qapp, monkeypatch):
        """单行编辑模式仍从 plan dict 读值。"""
        monkeypatch.setattr("ui_pyside6.views.industry.plan_edit_dialog.get_character_list", lambda: [])
        monkeypatch.setattr(inventory_manager, "get_hangars", lambda: [])
        from ui_pyside6.views.industry.plan_edit_dialog import PlanEditDialog

        dlg = PlanEditDialog(None, {"product_name": "x", "runs": 19, "parallels": 11}, batch_mode=False)
        assert dlg._runs_spin.value() == 19
        assert dlg._parallel_spin.value() == 11
