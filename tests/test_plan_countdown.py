"""倒计时与蓝图列渲染测试 — ui_pyside6/models/industry_models.py

覆盖：PlanTableModel.tick 到期转 ready、时长列倒计时渲染、蓝图列有图/绑定标记。
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from PySide6.QtCore import Qt

from ui_pyside6.models.industry_models import PlanTableModel

_COL_TIME = 10
_COL_BLUEPRINT = 9


def _plan(**overrides) -> dict:
    data = {
        "id": 1,
        "product_type_id": 2001,
        "product_name": "渡鸦级",
        "status": "pending",
        "runs": 1,
        "parallels": 1,
        "me_level": 0,
        "te_level": 0,
        "calculated_time": 7200,
        "started_at": None,
        "has_image": False,
        "assigned_blueprint_id": None,
    }
    data.update(overrides)
    return data


def _started(seconds_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%d %H:%M:%S")


class TestTimeColumn:
    def test_pending_shows_total_duration(self):
        m = PlanTableModel([_plan(status="pending", calculated_time=7200)])
        assert m.data(m.index(0, _COL_TIME), Qt.ItemDataRole.DisplayRole) == "2h0m"

    def test_in_progress_shows_countdown(self, qapp):
        m = PlanTableModel([_plan(status="in_progress", started_at=_started(3600), calculated_time=7200)])
        text = m.data(m.index(0, _COL_TIME), Qt.ItemDataRole.DisplayRole)
        assert text.startswith("剩余 ")

    def test_in_progress_overdue_shows_expired(self, qapp):
        m = PlanTableModel([_plan(status="in_progress", started_at=_started(10000), calculated_time=7200)])
        assert m.data(m.index(0, _COL_TIME), Qt.ItemDataRole.DisplayRole) == "已超时"

    def test_ready_shows_offline(self):
        m = PlanTableModel([_plan(status="ready")])
        assert m.data(m.index(0, _COL_TIME), Qt.ItemDataRole.DisplayRole) == "待下线"

    def test_completed_shows_done(self):
        m = PlanTableModel([_plan(status="completed")])
        assert m.data(m.index(0, _COL_TIME), Qt.ItemDataRole.DisplayRole) == "已完成"


class TestBlueprintColumn:
    def test_shows_has_image(self):
        m = PlanTableModel([_plan(has_image=True)])
        assert m.data(m.index(0, _COL_BLUEPRINT), Qt.ItemDataRole.DisplayRole).endswith("[有图]")

    def test_shows_no_image(self):
        m = PlanTableModel([_plan(has_image=False)])
        assert m.data(m.index(0, _COL_BLUEPRINT), Qt.ItemDataRole.DisplayRole).endswith("[没图]")

    def test_bound_blueprint_marker(self):
        m = PlanTableModel([_plan(has_image=True, assigned_blueprint_id=5)])
        assert m.data(m.index(0, _COL_BLUEPRINT), Qt.ItemDataRole.DisplayRole).endswith("[有图] *")


class TestTick:
    def test_tick_flips_expired_to_ready(self, qapp):
        p = _plan(id=7, status="in_progress", started_at=_started(10000), calculated_time=7200)
        m = PlanTableModel([p])
        assert m.tick() == [7]
        assert p["status"] == "ready"

    def test_tick_keeps_not_expired(self, qapp):
        p = _plan(id=8, status="in_progress", started_at=_started(-3600), calculated_time=7200)
        m = PlanTableModel([p])
        assert m.tick() == []
        assert p["status"] == "in_progress"

    def test_tick_ignores_pending(self, qapp):
        p = _plan(id=9, status="pending")
        m = PlanTableModel([p])
        assert m.tick() == []
        assert p["status"] == "pending"

    def test_tick_emits_data_changed(self, qapp):
        p = _plan(id=10, status="in_progress", started_at=_started(-3600), calculated_time=7200)
        m = PlanTableModel([p])
        spy = Mock()
        m.dataChanged.connect(spy)
        m.tick()
        assert spy.called
