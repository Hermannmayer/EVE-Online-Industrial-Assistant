"""表头排序保持工具测试 — 锁住两个 Qt 行为与 SortPreservingTableView 的补偿。

1. `setModel()` 换模型不会重排新模型（箭头还在、行序回退）；
2. `setSortIndicator()` 同值时不发信号，故不能用来「重放」排序。
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QTableView

from ui_pyside6.table_sort import SortPreservingTableView, init_sorting

pytestmark = pytest.mark.ui


def _model(values: list[int]) -> QStandardItemModel:
    m = QStandardItemModel(0, 2)
    for v in values:
        m.appendRow([QStandardItem(str(v)), QStandardItem("x")])
    return m


def _order(model: QStandardItemModel) -> list[str]:
    return [model.item(r, 0).text() for r in range(model.rowCount())]


def test_init_sorting_clears_fake_indicator(qapp):
    """setSortingEnabled 会留下 (第 0 列, 降序) 的假排序箭头，init_sorting 必须清掉。"""
    table = QTableView()
    table.setSortingEnabled(True)
    assert table.horizontalHeader().sortIndicatorSection() == 0  # Qt 默认值（数据并未排序）
    init_sorting(table)
    assert table.isSortingEnabled()
    assert table.horizontalHeader().sortIndicatorSection() == -1


def test_plain_table_loses_sort_on_set_model(qapp):
    """记录 Qt 行为本身：换模型后行序回退（子类就是为堵它而存在）。"""
    table = QTableView()
    init_sorting(table)
    table.setModel(_model([3, 1, 2]))
    table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    assert _order(table.model()) == ["1", "2", "3"]

    table.setModel(_model([9, 7, 8]))
    assert _order(table.model()) == ["9", "7", "8"], "setModel 不会对新模型调 sort()"
    assert table.horizontalHeader().sortIndicatorSection() == 0, "箭头却还留在原列"


def test_sort_preserving_view_replays_on_set_model(qapp):
    """用户排过序 → 重建模型后自动重放同一列/方向。"""
    table = SortPreservingTableView()
    first = _model([3, 1, 2])
    table.setModel(first)
    table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    assert _order(first) == ["1", "2", "3"]

    second = _model([9, 7, 8])
    table.setModel(second)
    assert _order(second) == ["7", "8", "9"]
    assert table.horizontalHeader().sortIndicatorSection() == 0


def test_no_replay_when_never_sorted(qapp):
    """没点过表头（指示器 -1）→ 重建后保持模型原始顺序，不擅自排序。"""
    table = SortPreservingTableView()
    table.setModel(_model([3, 1, 2]))
    second = _model([9, 7, 8])
    table.setModel(second)
    assert _order(second) == ["9", "7", "8"]


def test_set_model_none_is_safe_and_keeps_indicator(qapp):
    """空结果分支 setModel(None) 不得崩，且不得丢掉排序状态（下次重建要能重放）。"""
    table = SortPreservingTableView()
    table.setModel(_model([1, 2]))
    table.sortByColumn(0, Qt.SortOrder.DescendingOrder)

    table.setModel(None)
    assert table.model() is None
    assert table.horizontalHeader().sortIndicatorSection() == 0

    second = _model([9, 7, 8])
    table.setModel(second)
    assert _order(second) == ["9", "8", "7"]
