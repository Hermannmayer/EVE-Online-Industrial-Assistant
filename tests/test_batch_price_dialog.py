"""批量查价对话框测试"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QCoreApplication

from ui_pyside6.views.batch_price_dialog import (
    BatchPriceDialog,
    BatchPriceWorker,
)

pytestmark = pytest.mark.ui

# ═══════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════


def _make_mock_db():
    """Mock DB — 支持 connect('ref'), connect('mkt')"""
    cur = MagicMock()
    cur.fetchone.return_value = None
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value = cur
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    db = MagicMock()
    db.connect.return_value = cm
    return db


@pytest.fixture
def mock_deps():
    """Mock get_container → mock db"""
    db = _make_mock_db()
    cont = MagicMock()
    cont.db = db
    with patch("ui_pyside6.views.batch_price_dialog.get_container", return_value=cont):
        yield


# ═══════════════════════════════════════════
#  1. 构造测试
# ═══════════════════════════════════════════


def test_dialog_has_theme_listener(qapp, mock_deps):
    """对话框注册了 theme listener + _on_theme_changed 存在"""
    dlg = BatchPriceDialog(parent=None)
    assert hasattr(dlg, "_on_theme_changed")
    # 调用不会崩溃
    dlg._on_theme_changed()
    dlg.close()


def test_dialog_close_with_worker(qapp, mock_deps):
    """关闭对话框（即使 worker 存在）不崩溃"""
    dlg = BatchPriceDialog(parent=None)
    # 模拟 worker 正在运行
    worker = MagicMock()
    worker.isRunning.return_value = True
    dlg._worker = worker
    dlg.close()


# ═══════════════════════════════════════════
#  2. 查询测试
# ═══════════════════════════════════════════


def test_query_flow(qapp, mock_deps):
    """点击查询 → _search_items → worker → 显示结果"""
    dlg = BatchPriceDialog(parent=None)

    # 填入输入
    dlg._input_text.setPlainText("三钛合金\n渡鸦级")

    mock_results = [
        {
            "type_id": 1001,
            "name": "三钛合金",
            "buy_str": "4.00 (10000000)",
            "sell_str": "5.00 (8000000)",
            "avg_str": "4.50",
            "spread_str": "+1.00",
            "vol_str": "18000000",
            "buy_val": 4.0,
            "sell_val": 5.0,
            "avg_val": 4.5,
            "spread_val": 1.0,
            "vol_val": 18000000,
            "not_found": False,
        },
        {
            "type_id": 2001,
            "name": "渡鸦级",
            "buy_str": "50000000.00 (1000000)",
            "sell_str": "55000000.00 (800000)",
            "avg_str": "52500000.00",
            "spread_str": "+5000000.00",
            "vol_str": "1800000",
            "buy_val": 50000000.0,
            "sell_val": 55000000.0,
            "avg_val": 52500000.0,
            "spread_val": 5000000.0,
            "vol_val": 1800000,
            "not_found": False,
        },
    ]

    # Mock _search_items → 返回已知物品
    with (
        patch("ui_pyside6.views.batch_price_dialog._search_items") as mock_search,
        patch.object(BatchPriceWorker, "start") as mock_start,
    ):
        mock_search.return_value = [
            {"type_id": 1001, "name": "三钛合金", "raw_query": "三钛合金"},
            {"type_id": 2001, "name": "渡鸦级", "raw_query": "渡鸦级"},
        ]
        # 直接触发查询
        dlg._on_query()

        # 验证 worker 被创建并启动
        assert dlg._worker is not None
        mock_start.assert_called_once()

        # 模拟 worker 完成 → 信号连接
        dlg._worker.finished_signal.connect(dlg._on_query_done)
        dlg._worker.finished_signal.emit(mock_results)
        QCoreApplication.processEvents()

    assert len(dlg._current_results) == 2
    assert dlg._current_results[0]["name"] == "三钛合金"
    assert dlg._current_results[1]["name"] == "渡鸦级"
    assert dlg._model.rowCount() == 2
    assert dlg._export_btn.isEnabled() is True
    dlg.close()


def test_query_empty_input(qapp, mock_deps):
    """空输入不应触发查询"""
    dlg = BatchPriceDialog(parent=None)
    dlg._on_query()
    assert dlg._status_label.text() == "请先输入物品名称或 ID"
    dlg.close()


def test_query_not_found(qapp, mock_deps):
    """所有物品都未找到时提示"""
    dlg = BatchPriceDialog(parent=None)
    dlg._input_text.setPlainText("不存在的物品")

    with patch("ui_pyside6.views.batch_price_dialog._search_items") as mock_search:
        mock_search.return_value = [
            {"type_id": 0, "name": "不存在的物品", "raw_query": "不存在的物品", "not_found": True},
        ]
        dlg._on_query()
        QCoreApplication.processEvents()

    assert dlg._status_label.text() == "未找到任何匹配的物品"
    assert dlg._export_btn.isEnabled() is False
    dlg.close()


# ═══════════════════════════════════════════
#  3. 导出测试
# ═══════════════════════════════════════════


def test_export_csv(qapp, mock_deps):
    """导出 CSV 调用 export_to_csv"""
    dlg = BatchPriceDialog(parent=None)
    dlg._current_results = [
        {
            "name": "三钛合金",
            "buy_str": "4.00",
            "sell_str": "5.00",
            "avg_str": "4.50",
            "spread_str": "+1.00",
            "vol_str": "18000000",
        },
        {
            "name": "渡鸦级",
            "buy_str": "50000000.00",
            "sell_str": "55000000.00",
            "avg_str": "52500000.00",
            "spread_str": "+5000000.00",
            "vol_str": "1800000",
        },
    ]

    with (
        patch("ui_pyside6.views.batch_price_dialog.get_save_filename", return_value="/tmp/test_export.csv"),
        patch("ui_pyside6.views.batch_price_dialog.export_to_csv") as mock_export,
    ):
        dlg._on_export_csv()

        mock_export.assert_called_once()
        args, _ = mock_export.call_args
        # args: (headers, rows, path)
        headers = args[0]
        rows = args[1]
        assert headers == ["物品名", "买价", "卖价", "均价", "价差", "成交量"]
        assert len(rows) == 2
        assert rows[0][0] == "三钛合金"
        assert rows[1][0] == "渡鸦级"
        assert args[2] == "/tmp/test_export.csv"


def test_export_csv_no_data(qapp, mock_deps):
    """无数据时导出按钮无效，_on_export_csv 不崩溃"""
    dlg = BatchPriceDialog(parent=None)
    dlg._current_results = []
    # 无数据时直接返回
    dlg._on_export_csv()
    assert dlg._status_label.text() != "已导出"  # 不会被标记为已导出


def test_export_csv_cancelled(qapp, mock_deps):
    """用户取消保存对话框则不导出"""
    dlg = BatchPriceDialog(parent=None)
    dlg._current_results = [
        {
            "name": "三钛合金",
            "buy_str": "4.00",
            "sell_str": "5.00",
            "avg_str": "4.50",
            "spread_str": "+1.00",
            "vol_str": "18000000",
        },
    ]

    with (
        patch("ui_pyside6.views.batch_price_dialog.get_save_filename", return_value=""),
        patch("ui_pyside6.views.batch_price_dialog.export_to_csv") as mock_export,
    ):
        dlg._on_export_csv()
        mock_export.assert_not_called()
    dlg.close()
