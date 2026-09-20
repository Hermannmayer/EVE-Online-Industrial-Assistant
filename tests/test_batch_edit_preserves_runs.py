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


class TestInventionExpectation:
    """发明「预期生产结果」面板的数字口径（`plan_edit_bridge` 的 `expect*` 属性）。

    口径是**期望值**：预期张数 = 总尝试 × 成功率 × 每次成功 1 张。它与表格「输出」列
    的「全成功上限」（`plan_metrics` 的 `expected_runs = 尝试 × 每张流程`）**不是同一个数**，
    面板文案一律带「预期」二字就是为了区分。

    数字都手算过：base_probability 0.30 + 科学技能 4/4 + 加密 4 → 技能系数
    `1 + (4+4)/30 + 4/40 = 1.366667`；解码器修正查 `domain/research.DECRYPTORS`。
    """

    _BD = {
        "base_runs": 7,
        "base_probability": 0.30,
        "science_skill_1": 4,
        "science_skill_2": 4,
        "encryption_skill": 4,
        "runs_per_bpc": 7,
    }

    def _dlg(self, monkeypatch, **extra):
        plan = {
            "activity": "invention",
            "product_name": "T2 产物",
            "runs": 10,  # 每线尝试次数
            "parallels": 4,  # → 总尝试 40
            "breakdown": dict(self._BD),
            **extra,
        }
        return _make_dialog(monkeypatch, plan, batch_mode=False)

    @pytest.mark.parametrize(
        ("decryptor_id", "runs_text", "me_te", "rate", "bpc", "total_text"),
        [
            # 不用解码器：流程 = base_runs，等级 = 基准 ME2 / TE4
            (None, "7 流程", "ME2 / TE4", 0.41, 16, "合计约 112 流程"),
            # 加速装置解码器（×1.2，流程 +1，ME +2，TE +10）
            (34201, "8 流程", "ME4 / TE14", 0.492, 20, "合计约 160 流程"),
            # 放大装置解码器（×0.6，流程 +9，ME -2，TE +2）→ ME 被下限钳到 0
            (34203, "16 流程", "ME0 / TE6", 0.246, 10, "合计约 160 流程"),
        ],
    )
    def test_expected_outcome(self, qapp, monkeypatch, decryptor_id, runs_text, me_te, rate, bpc, total_text):
        dlg = self._dlg(monkeypatch, decryptor_type_id=decryptor_id)
        assert dlg.expectVisible is True
        assert dlg.expectRunsPerBpcText == runs_text
        assert dlg.expectMeTeText == me_te
        assert dlg.expectRate == pytest.approx(rate, abs=1e-6)
        assert dlg.expectBpcCount == bpc
        assert dlg.expectTotalRunsText == total_text

    def test_manual_rate_override_is_not_scaled_by_decryptor(self, qapp, monkeypatch):
        """手填过成功率 → 解码器只改流程与等级，不再乘概率倍率（与 plan_metrics 同口径）。"""
        dlg = self._dlg(monkeypatch, success_rate=0.25, decryptor_type_id=34207)  # 优化的获取装置，×1.9
        assert dlg.expectRate == pytest.approx(0.25)  # 没有乘 1.9
        assert dlg.expectBpcCount == 10  # 40 × 0.25
        assert dlg.expectRunsPerBpcText == "9 流程"  # 7 + 2，解码器照常生效
        assert dlg.expectMeTeText == "ME3 / TE2"  # 基准 (2,4) + (1,-2)

    def test_hidden_without_scoring_breakdown(self, qapp, monkeypatch):
        """没跑到评分（breakdown 缺 base_runs）→ 面板不显示，不拿兜底值糊弄用户。"""
        dlg = _make_dialog(
            monkeypatch,
            {"activity": "invention", "product_name": "T2", "runs": 10, "parallels": 4},
            batch_mode=False,
        )
        assert dlg.expectVisible is False

    def test_hidden_for_manufacturing(self, qapp, monkeypatch):
        """制造行不显示预期面板（它的产出不是概率作业）。"""
        dlg = _make_dialog(
            monkeypatch,
            {
                "activity": "manufacturing",
                "product_name": "T1",
                "runs": 10,
                "parallels": 4,
                "breakdown": dict(self._BD),
            },
            batch_mode=False,
        )
        assert dlg.expectVisible is False
