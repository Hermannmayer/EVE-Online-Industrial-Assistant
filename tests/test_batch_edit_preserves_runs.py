"""Bug A 回归测试 — 批量编辑不再把 runs/parallels 重置为 1X1 或首行值。

阶段 4：对话框迁到 QML 后，断言从「Widgets 内部控件」换成**桥的字段**
（`bridge.runs` / `bridge.setSyncRuns`）—— 行为契约一字未改，只是观察点变了。
"""

import pytest

from services import inventory_manager

pytestmark = pytest.mark.ui


def _make_dialog(monkeypatch, plan_data, *, batch_mode=True):
    monkeypatch.setattr("ui_qml.bridge.plan_edit_bridge.PlanEditBridge._load_chars", staticmethod(lambda: ["main"]))
    monkeypatch.setattr(inventory_manager, "get_hangars", lambda: [])
    from ui_qml.bridge.plan_edit_bridge import PlanEditBridge

    return PlanEditBridge(plan_data, batch_mode=batch_mode, row_count=len(plan_data.get("_selected_rows", []) or [1]))


class TestBatchEditPreservesRuns:
    def test_batch_mode_prefills_first_row_values(self, qapp, monkeypatch):
        """批量编辑弹窗用首行真实 runs/parallels 预填，而非硬编码 1。"""
        dlg = _make_dialog(monkeypatch, {"_selected_rows": [0, 1], "runs": 5, "parallels": 3})
        assert dlg.runs == 5
        assert dlg.parallels == 3

    def test_batch_mode_defaults_to_none_not_writing(self, qapp, monkeypatch):
        """批量模式默认不写流程/并行（同步复选未勾 → runs/parallels 为 None）。"""
        dlg = _make_dialog(monkeypatch, {"_selected_rows": [0, 1], "runs": 5, "parallels": 3})
        data = dlg.data()
        assert data["runs"] is None
        assert data["parallels"] is None

    def test_batch_mode_sync_checkbox_returns_values(self, qapp, monkeypatch):
        """勾选「同步流程/并行」后返回预填值（显式同步）。"""
        dlg = _make_dialog(monkeypatch, {"_selected_rows": [0, 1], "runs": 5, "parallels": 3})
        dlg.setSyncRuns(True)
        data = dlg.data()
        assert data["runs"] == 5
        assert data["parallels"] == 3

    def test_batch_mode_defaults_to_one_when_missing(self, qapp, monkeypatch):
        """旧调用方未传 runs/parallels 时兜底 1（不崩溃）。"""
        dlg = _make_dialog(monkeypatch, {"_selected_rows": [0]})
        assert dlg.runs == 1
        assert dlg.parallels == 1

    def test_non_batch_mode_uses_plan_values(self, qapp, monkeypatch):
        """单行编辑模式仍从 plan dict 读值。"""
        dlg = _make_dialog(monkeypatch, {"product_name": "x", "runs": 19, "parallels": 11}, batch_mode=False)
        assert dlg.runs == 19
        assert dlg.parallels == 11
        assert dlg.data()["runs"] == 19  # 单行模式默认同步

    def test_character_is_required(self, qapp, monkeypatch):
        """角色名为空时校验不通过（对齐 Widgets 版的 QMessageBox 拦截）。"""
        dlg = _make_dialog(monkeypatch, {"runs": 1, "parallels": 1}, batch_mode=False)
        seen: list[bool] = []
        dlg.accepted.connect(lambda: seen.append(True))
        dlg._chars = [""]  # 模拟空角色名
        dlg.setCharIndex(0)
        dlg.accept()
        assert seen == []
        assert "请输入角色名" in dlg.error
