"""下线功能测试 — StatusBar「全部下线」按钮 + CompletePlansDialog"""

from unittest.mock import MagicMock, patch

import pytest

from ui_pyside6.views.industry.complete_plans_dialog import CompletePlansDialog
from ui_pyside6.views.industry.status_bar import StatusBar


@pytest.fixture
def production_wizard_mock_db():
    """给 ProductionWizard 注入 mock 容器/DB，避免访问真实库。

    ProductionWizard.__init__ 经 `_load_blueprint_names`（查 ref 库 item）与
    `char_capacity.active_lines_per_character`（查 user 库 production_plans）
    访问真实库；worktree / CI 无初始化 schema，必须 patch 这两条 get_container 路径。
    """
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_conn.execute.return_value.fetchone.return_value = None
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_conn
    mock_cm.__exit__.return_value = False
    mock_mgr = MagicMock()
    mock_mgr.connect.return_value = mock_cm
    mock_cont = MagicMock()
    mock_cont.db = mock_mgr
    with (
        patch("ui_pyside6.dialogs.production_wizard.get_container", return_value=mock_cont),
        patch("services.char_capacity.get_container", return_value=mock_cont),
    ):
        yield


class TestStatusBarCompleteAll:
    """底部状态栏「全部下线」按钮显示/隐藏与信号"""

    def test_hidden_without_ready(self, qapp):
        bar = StatusBar()
        bar.update_stats([{"status": "pending"}, {"status": "running"}])
        assert bar._btn_complete_all.isHidden()

    def test_shown_with_ready_count(self, qapp):
        bar = StatusBar()
        bar.update_stats(
            [
                {"status": "pending"},
                {"status": "ready"},
                {"status": "ready"},
                {"status": "running"},
            ]
        )
        assert not bar._btn_complete_all.isHidden()
        assert bar._btn_complete_all.text() == "全部下线 (2)"

    def test_emit_complete_all_requested(self, qapp):
        bar = StatusBar()
        bar.update_stats([{"status": "ready"}])
        got = []
        bar.complete_all_requested.connect(lambda: got.append(True))
        bar._btn_complete_all.click()
        assert got == [True]


class TestCompletePlansDialog:
    """下线确认对话框 — 计划清单 / 机库默认值"""

    def test_default_hangar_from_settings(self, qapp, monkeypatch):
        monkeypatch.setattr("services.plan_execution.output_per_run", lambda *a: 1)
        plans = [
            {
                "id": 1,
                "product_name": "渡鸦级",
                "product_type_id": 2001,
                "runs": 2,
                "parallels": 3,
                "deposit_hangar_id": 5,
            }
        ]
        hangars = [{"id": 1, "name": "矿仓"}, {"id": 2, "name": "组件仓"}]
        dlg = CompletePlansDialog(plans, hangars, 2)  # 默认 = 设置的默认产出机库
        assert dlg.selected_hangar_id() == 2
        assert dlg._table.rowCount() == 1
        assert dlg._table.item(0, 0).text() == "渡鸦级"
        assert dlg._table.item(0, 1).text() == "3X2"
        assert dlg._table.item(0, 2).text() == "6"  # 产出量

    def test_default_fallback_first_hangar(self, qapp, monkeypatch):
        monkeypatch.setattr("services.plan_execution.output_per_run", lambda *a: 1)
        plans = [{"id": 1, "product_name": "渡鸦级", "runs": 1, "parallels": 1, "deposit_hangar_id": None}]
        hangars = [{"id": 1, "name": "矿仓"}, {"id": 2, "name": "组件仓"}]
        dlg = CompletePlansDialog(plans, hangars, None)
        assert dlg.selected_hangar_id() == 1  # 无默认时选第一个机库

    def test_no_hangar_keeps_no_auto_deposit(self, qapp, monkeypatch):
        monkeypatch.setattr("services.plan_execution.output_per_run", lambda *a: 1)
        plans = [{"id": 1, "product_name": "渡鸦级", "runs": 1, "parallels": 1}]
        dlg = CompletePlansDialog(plans, [], -1)
        assert dlg.selected_hangar_id() == -1  # 无机库时保持「不自动入库」


class TestReadyButtonDelegate:
    """状态列「待下线」按钮渲染 delegate"""

    def _ready_model(self):
        from ui_pyside6.models.industry_models import PlanTableModel

        return PlanTableModel([{"product_name": "渡鸦级", "status": "ready", "product_type_id": 2001}])

    def test_ready_cell_button_size_hint(self, qapp):
        from PySide6.QtWidgets import QStyleOptionViewItem

        from ui_pyside6.views.industry.plan_table_constants import COL_STATUS
        from ui_pyside6.views.industry.plan_table_delegate import ReadyButtonDelegate

        delegate = ReadyButtonDelegate()
        model = self._ready_model()  # 保持模型存活，避免 QModelIndex 悬空
        index = model.index(0, COL_STATUS)
        hint = delegate.sizeHint(QStyleOptionViewItem(), index)
        assert hint.width() >= 60
        assert hint.height() >= 20

    def test_non_ready_default_size_hint(self, qapp):
        from PySide6.QtWidgets import QStyleOptionViewItem

        from ui_pyside6.models.industry_models import PlanTableModel
        from ui_pyside6.views.industry.plan_table_constants import COL_STATUS
        from ui_pyside6.views.industry.plan_table_delegate import ReadyButtonDelegate

        delegate = ReadyButtonDelegate()
        model = PlanTableModel([{"product_name": "渡鸦级", "status": "in_progress", "product_type_id": 2001}])
        index = model.index(0, COL_STATUS)
        hint = delegate.sizeHint(QStyleOptionViewItem(), index)
        assert hint.width() < 60  # 非 ready 不渲染按钮，走默认

    def test_paint_ready_does_not_crash(self, qapp):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtWidgets import QStyleOptionViewItem

        from ui_pyside6.views.industry.plan_table_constants import COL_STATUS
        from ui_pyside6.views.industry.plan_table_delegate import ReadyButtonDelegate

        delegate = ReadyButtonDelegate()
        model = self._ready_model()
        index = model.index(0, COL_STATUS)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 80, 26)
        pix = QPixmap(100, 30)
        pix.fill()
        painter = QPainter(pix)
        delegate.paint(painter, option, index)
        painter.end()
        assert not pix.isNull()


class TestLaunchWizard:
    """产线启动小助手：一级菜单按钮 + 两列 + 复制蓝图名 + 启动按钮显隐"""

    def test_launch_wizard_button_emits(self, qapp):
        from ui_pyside6.views.industry.action_buttons import ActionButtons

        ab = ActionButtons()
        got = []
        ab.launch_wizard_requested.connect(lambda: got.append(True))
        ab._btn_launch_wizard.click()
        assert got == [True]

    def test_orders_by_child_level_desc(self, qapp, production_wizard_mock_db):
        from ui_pyside6.dialogs.production_wizard import ProductionWizard

        plans = [
            {"product_name": "子项2", "child_level": 2, "status": "pending"},
            {"product_name": "母项", "child_level": 0, "status": "pending"},
            {"product_name": "子项1", "child_level": 1, "status": "pending"},
        ]
        wizard = ProductionWizard(plans, mat_hangar_id=None)
        names = [p["product_name"] for p in wizard._plans]
        assert names == ["子项2", "子项1", "母项"]  # 子级高的先做

    def test_copy_blueprint_name(self, qapp, production_wizard_mock_db):
        from PySide6.QtWidgets import QApplication

        from ui_pyside6.dialogs.production_wizard import ProductionWizard

        plans = [
            {
                "id": 1,
                "product_name": "渡鸦级",
                "product_type_id": 2001,
                "blueprint_type_id": 32877,
                "status": "pending",
                "runs": 1,
                "parallels": 1,
            }
        ]
        wizard = ProductionWizard(plans, mat_hangar_id=None)
        wizard._copy_blueprint("渡鸦级蓝图")
        assert QApplication.clipboard().text() == "渡鸦级蓝图"

    def test_pending_shows_start_button(self, qapp, production_wizard_mock_db):
        from ui_pyside6.dialogs.production_wizard import ProductionWizard

        plans = [
            {
                "id": 1,
                "product_name": "渡鸦级",
                "product_type_id": 2001,
                "blueprint_type_id": 32877,
                "status": "pending",
                "runs": 1,
                "parallels": 1,
            }
        ]
        wizard = ProductionWizard(plans, mat_hangar_id=None)  # 无材料机库 → 视为备料充足
        assert wizard._table.rowCount() == 1
        assert not wizard._start_btn.isHidden()  # 备料足 → 显示启动按钮

    def test_flat_plans_unchanged(self, qapp, production_wizard_mock_db):
        from ui_pyside6.dialogs.production_wizard import ProductionWizard

        plans = [{"product_name": "A", "child_level": 0, "status": "pending"}]
        wizard = ProductionWizard(plans, mat_hangar_id=None)
        assert wizard._table.rowCount() == 1
