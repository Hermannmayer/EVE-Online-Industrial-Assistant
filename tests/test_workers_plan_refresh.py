"""PlanPriceRefreshWorker 单元测试"""

from unittest.mock import patch

from PySide6.QtCore import QThread

from ui_pyside6.views.industry_view import PlanPriceRefreshWorker


class TestPlanPriceRefreshWorker:
    def test_worker_is_qthread(self):
        """验证 PlanPriceRefreshWorker 是 QThread 子类"""
        w = PlanPriceRefreshWorker(type_ids={1, 2, 3})
        assert isinstance(w, QThread)

    def test_worker_construction(self):
        """构造时正确保存 type_ids"""
        w = PlanPriceRefreshWorker(type_ids={24680, 13579})
        assert w._type_ids == {24680, 13579}

    @patch("ui_pyside6.views.industry_view.PlanPriceRefreshWorker._fetch_and_save")
    def test_run_emits_finished_on_success(self, mock_fetch, qapp):
        """run() 成功拉取后通过 finished 信号返回成功消息"""
        mock_fetch.return_value = 5

        received: list[tuple[bool, str]] = []

        def collect(success, message):
            received.append((success, message))

        w = PlanPriceRefreshWorker(type_ids={1, 2, 3, 4, 5})
        w.finished.connect(collect)
        w.run()

        assert len(received) == 1
        assert received[0][0] is True  # success
        assert "5" in received[0][1]

    @patch("ui_pyside6.views.industry_view.PlanPriceRefreshWorker._fetch_and_save")
    def test_run_emits_finished_on_failure(self, mock_fetch, qapp):
        """run() 遇到异常时通过 finished 信号返回失败消息"""
        mock_fetch.side_effect = RuntimeError("ESI 连接超时")

        received: list[tuple[bool, str]] = []

        def collect(success, message):
            received.append((success, message))

        w = PlanPriceRefreshWorker(type_ids={1})
        w.finished.connect(collect)
        w.run()

        assert len(received) == 1
        assert received[0][0] is False
        assert "ESI 连接超时" in received[0][1]
