"""备料中采购汇总 worker 测试 — ProcurementSummaryWorker（需求2）"""

from types import SimpleNamespace

import pytest

import ui_pyside6.workers.industry_workers as iw
from services.plan_aggregator import aggregate_procurement


class TestProcurementSummaryWorker:
    def test_emits_totals(self, temp_db, monkeypatch):
        """run() 直调 → finished 发出与手工 aggregate_procurement 一致的 (cost, vol)。"""
        monkeypatch.setattr(iw, "get_container", lambda: SimpleNamespace(db=temp_db))
        with temp_db.connect("user") as conn:
            conn.execute(
                "CREATE TABLE inventory_items (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "hangar_id INTEGER, type_id INTEGER, quantity INTEGER, cost_price REAL)"
            )
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0, "mat_hangar_id": 5}
        captured = []
        worker = iw.ProcurementSummaryWorker([plan], default_mat_hangar_id=5, region_id=10000002, price_type="sell")
        worker.finished.connect(lambda c, v: captured.append((c, v)))
        worker.run()

        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            _rows, cost, vol = aggregate_procurement(conn, [plan], default_hangar_id=5, price_type="sell")
        assert len(captured) == 1
        assert captured[0][0] == pytest.approx(cost)
        assert captured[0][1] == pytest.approx(vol)

    def test_no_plans_emits_zero(self, temp_db, monkeypatch):
        monkeypatch.setattr(iw, "get_container", lambda: SimpleNamespace(db=temp_db))
        captured = []
        worker = iw.ProcurementSummaryWorker([], default_mat_hangar_id=5)
        worker.finished.connect(lambda c, v: captured.append((c, v)))
        worker.run()
        assert captured == [(0.0, 0.0)]

    def test_exception_emits_zero(self, temp_db, monkeypatch):
        """计划为 None → aggregate 抛异常 → worker 兜底发 (0.0, 0.0) 不崩溃。"""
        monkeypatch.setattr(iw, "get_container", lambda: SimpleNamespace(db=temp_db))
        captured = []
        worker = iw.ProcurementSummaryWorker([None])  # type: ignore[list-item]
        worker.finished.connect(lambda c, v: captured.append((c, v)))
        worker.run()
        assert captured == [(0.0, 0.0)]
