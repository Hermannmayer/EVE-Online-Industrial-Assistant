"""工业制造 Worker 线程单元测试"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QThread

from ui_pyside6.workers.industry_workers import RankWorker, ScoreWorker, SearchWorker

pytestmark = pytest.mark.ui


class TestSearchWorker:
    def test_worker_is_qthread(self):
        """SearchWorker 是 QThread 子类"""
        db = MagicMock()
        w = SearchWorker(query="rav", db=db)
        assert isinstance(w, QThread)
        assert w._query == "rav"

    def test_run_emits_finished(self, qapp):
        """run() 执行 SQL 后通过 finished 信号返回结果"""
        db = MagicMock()
        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = [(2001, "渡鸦级", "Raven")]
        fake_conn = MagicMock()
        fake_conn.cursor.return_value = fake_cursor
        fake_cm = MagicMock()
        fake_cm.__enter__ = MagicMock(return_value=fake_conn)
        fake_cm.__exit__ = MagicMock(return_value=False)
        db.connect.return_value = fake_cm

        received = []

        def collect(data):
            received.append(data)

        w = SearchWorker(query="rav", db=db)
        w.finished.connect(collect)
        w.run()

        assert len(received) == 1
        rows = received[0]
        assert len(rows) == 1
        assert rows[0]["type_id"] == 2001
        assert rows[0]["zh_name"] == "渡鸦级"
        assert rows[0]["en_name"] == "Raven"
        # 验证 SQL 参数含 % 通配符
        call_sql = fake_cursor.execute.call_args[0][0]
        assert "LIKE ?" in call_sql
        assert "LIMIT 30" in call_sql


class TestScoreWorker:
    @patch("ui_pyside6.workers.industry_workers.get_container")
    def test_run_emits_finished(self, mock_get_container, qapp):
        """run() 调用 scoring_service().calc_manufacturing_score 并通过 finished 返回结果"""
        expected = {
            "status": "",
            "score": 123.45,
            "profit_per_run": 1000000.0,
            "margin_pct": 15.0,
            "breakdown": {},
            "materials": [],
        }
        mock_svc = MagicMock()
        mock_svc.calc_manufacturing_score.return_value = expected
        mock_get_container.return_value.scoring_service.return_value = mock_svc

        received = []

        def collect(data):
            received.append(data)

        w = ScoreWorker(type_id=2001, bp_me=10, bp_te=20, mat_hub="Jita", sell_hub="Jita", tax=0.015)
        w.finished.connect(collect)
        w.run()

        mock_svc.calc_manufacturing_score.assert_called_once_with(
            type_id=2001,
            char_config={"skills": {"工业理论": 5, "高级工业理论": 5}, "market": {}},
            bp_me=10,
            bp_te=20,
            mat_source_hub="Jita",
            sell_hub="Jita",
            facility_tax_pct=0.015,
            price_type_mat="sell",
            price_type_prod="sell",
            system_id=None,
        )
        assert len(received) == 1
        assert received[0]["status"] == ""
        assert received[0]["score"] == 123.45


class TestRankWorker:
    @patch("ui_pyside6.workers.industry_workers.get_container")
    def test_run_with_no_products(self, mock_get_container, qapp):
        """无可制造物品时 result 信号发出空列表"""
        mock_svc = MagicMock()
        mock_get_container.return_value.scoring_service.return_value = mock_svc

        db = MagicMock()
        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = []
        fake_conn = MagicMock()
        fake_conn.cursor.return_value = fake_cursor
        fake_cm = MagicMock()
        fake_cm.__enter__ = MagicMock(return_value=fake_conn)
        fake_cm.__exit__ = MagicMock(return_value=False)
        db.connect.return_value = fake_cm

        results = []
        done = []

        w = RankWorker(mat_hub="Jita", sell_hub="Jita", mat_price_type="sell", bp_me=10, bp_te=20, tax=0.015, db=db)
        w.result.connect(lambda r: results.append(r))
        w.done.connect(lambda t: done.append(t))
        w.run()

        assert len(results) == 1
        assert results[0] == []
        assert len(done) == 1
        mock_svc.calc_manufacturing_score.assert_not_called()
