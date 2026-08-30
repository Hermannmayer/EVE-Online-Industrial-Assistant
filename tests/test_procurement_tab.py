"""待采购对话框改造测试：双表分区 / 表头排序 / 双击复制 / 整单复制范围"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from ui_pyside6.views.procurement_tab import ProcurementDialog, ProcureTableModel, _display_name, _split_sections

pytestmark = pytest.mark.ui

# to_buy>0：34/35 需采购；to_buy=0：2001 库存已备足
ROWS = [
    {
        "type_id": 34,
        "name": "Tritanium",
        "zh_name": "三钛合金",
        "en_name": "Tritanium",
        "need": 1000,
        "owned": 0,
        "to_buy": 1000,
        "price": 5.0,
        "total": 5000.0,
        "volume": 10.0,
    },
    {
        "type_id": 35,
        "name": "Pyerite",
        "zh_name": "类银超金属",
        "en_name": "Pyerite",
        "need": 500,
        "owned": 400,
        "to_buy": 100,
        "price": 9.0,
        "total": 900.0,
        "volume": 1.0,
    },
    {
        "type_id": 2001,
        "name": "Raven",
        "zh_name": "渡鸦级",
        "en_name": "Raven",
        "need": 2,
        "owned": 5,
        "to_buy": 0,
        "price": 55000000.0,
        "total": 0.0,
        "volume": 0.0,
    },
]


def _make_mock_db():
    """Mock DB — 支持 with connect(...) 上下文。aggregate_procurement 被 patch，不真正查库。"""
    cur = MagicMock()
    cur.fetchall.return_value = []
    cur.fetchone.return_value = None
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.execute.return_value = cur
    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    db = MagicMock()
    db.connect.return_value = cm
    return db


@pytest.fixture
def make_dlg(qapp):
    """构造 ProcurementDialog，patch get_container + aggregate_procurement 使 _calculate 返回固定 rows。

    补丁在测试期间保持生效，允许测试内再次调用 _calculate（如排序状态重放）。
    """
    created: list[tuple[ProcurementDialog, list]] = []

    def _make(rows: list[dict] | None = None, plans: list[dict] | None = None):
        db = _make_mock_db()
        cont = MagicMock()
        cont.db = db
        rows = ROWS if rows is None else rows
        patchers = [
            patch("core.container.get_container", return_value=cont),
            patch(
                "services.plan_aggregator.aggregate_procurement",
                return_value=([dict(r) for r in rows], 0.0, 0.0),
            ),
        ]
        for p in patchers:
            p.start()
        dlg = ProcurementDialog(active_plans=plans or [], default_mat_hangar_id=None, hangar_label="测试机库")
        created.append((dlg, patchers))
        return dlg

    yield _make
    for dlg, patchers in created:
        for p in patchers:
            p.stop()
        dlg.close()


# ═══════════════════════════════════════════════════
#  分区拆分（纯函数）
# ═══════════════════════════════════════════════════


def test_split_sections_partitions():
    buy, stock = _split_sections(ROWS)
    assert [r["type_id"] for r in buy] == [34, 35]
    assert [r["type_id"] for r in stock] == [2001]
    assert all(r["to_buy"] > 0 for r in buy)
    assert all(r["to_buy"] <= 0 for r in stock)
    # 分区并集 = 原集合且顺序保持
    assert buy + stock == ROWS


def test_split_sections_empty_half():
    buy, stock = _split_sections([])
    assert buy == [] and stock == []
    buy, stock = _split_sections([dict(ROWS[-1])])  # 全 to_buy=0
    assert buy == [] and len(stock) == 1


# ═══════════════════════════════════════════════════
#  模型排序
# ═══════════════════════════════════════════════════


def test_model_sort_numeric_and_name(qapp):
    m = ProcureTableModel([dict(r) for r in ROWS])
    m.sort(3, Qt.SortOrder.DescendingOrder)  # 需采购降序
    assert [r["to_buy"] for r in m._rows] == [1000, 100, 0]

    m.sort(4, Qt.SortOrder.AscendingOrder)  # 单价升序
    assert [r["price"] for r in m._rows] == [5.0, 9.0, 55000000.0]

    m.sort(0, Qt.SortOrder.AscendingOrder)  # 名称升序（按显示名）
    names = [_display_name(r) for r in m._rows]
    assert names == sorted(names)

    m.sort(0, Qt.SortOrder.DescendingOrder)
    names = [_display_name(r) for r in m._rows]
    assert names == sorted(names, reverse=True)


def test_sort_remaps_persistent_index(qapp):
    """排序后 QPersistentModelIndex 应指向同一行对象（否则右键删除会删错行）。"""
    from PySide6.QtCore import QPersistentModelIndex

    m = ProcureTableModel(
        [
            {"type_id": 100, "zh_name": "乙", "to_buy": 900, "price": 1.0},
            {"type_id": 200, "zh_name": "丙", "to_buy": 0, "price": 2.0},  # 目标行，排序后应被搬动
            {"type_id": 300, "zh_name": "甲", "to_buy": 100, "price": 3.0},
        ]
    )
    # 建一个指向目标对象（200）的持久索引
    idx_persist = QPersistentModelIndex()
    for row, r in enumerate(m._rows):
        if r["type_id"] == 200:
            idx_persist = QPersistentModelIndex(m.index(row, 0))
            break
    assert idx_persist.isValid()

    m.sort(3, Qt.SortOrder.DescendingOrder)  # 变成 [100(900), 300(100), 200(0)]
    assert [r["type_id"] for r in m._rows] == [100, 300, 200]
    assert idx_persist.row() == 2
    assert m._rows[idx_persist.row()]["type_id"] == 200


def test_sort_then_remove_row_target(qapp):
    """排序后按所见行号删除，删的是排序后对应行。"""
    m = ProcureTableModel(
        [
            {"type_id": 100, "zh_name": "乙", "to_buy": 900, "price": 1.0},
            {"type_id": 200, "zh_name": "丙", "to_buy": 0, "price": 2.0},
            {"type_id": 300, "zh_name": "甲", "to_buy": 100, "price": 3.0},
        ]
    )
    m.sort(3, Qt.SortOrder.DescendingOrder)
    m.remove_row(2)  # 删除排到最后的 to_buy=0（200）
    assert [r["type_id"] for r in m._rows] == [100, 300]


# ═══════════════════════════════════════════════════
#  对话框双表/空结果
# ═══════════════════════════════════════════════════


def test_dialog_two_sections(qapp, make_dlg):
    dlg = make_dlg()
    assert isinstance(dlg._buy_table.model(), ProcureTableModel)
    assert isinstance(dlg._stock_table.model(), ProcureTableModel)
    assert dlg._buy_table.model().rowCount() == 2
    assert dlg._stock_table.model().rowCount() == 1
    assert "需采购" in dlg._buy_label.text()
    assert "库存已备足" in dlg._stock_label.text()
    assert not dlg._buy_table.isHidden()
    assert not dlg._stock_table.isHidden()
    assert "渡鸦级" not in dlg._buy_label.text()  # 渡鸦级属于已备足分区


def test_empty_rows_hides_tables(qapp, make_dlg):
    dlg = make_dlg(rows=[])
    assert dlg._buy_table.model() is None
    assert dlg._stock_table.model() is None
    assert dlg._buy_table.isHidden()
    assert dlg._stock_table.isHidden()
    assert dlg._buy_label.isHidden()
    assert dlg._stock_label.isHidden()
    assert dlg._summary_label.text() == "无活跃计划材料需求"


# ═══════════════════════════════════════════════════
#  双击复制（两表都要生效）
# ═══════════════════════════════════════════════════


def test_double_click_copies_name(qapp, make_dlg):
    """双击行复制物品名（不含数量）。用 setText spy 断言，规避全量跑时系统剪贴板读回被前置测试扰动的偶发。"""
    dlg = make_dlg()
    buy_model = dlg._buy_table.model()
    clip = QApplication.clipboard()
    with (
        patch.object(clip, "setText") as m_set,
        patch("ui_pyside6.views.procurement_tab.QToolTip"),
    ):
        dlg._on_row_double_click(buy_model.index(0, 0))
        assert m_set.call_args.args[0] == "三钛合金"
        dlg._on_row_double_click(dlg._stock_table.model().index(0, 0))
        assert m_set.call_args.args[0] == "渡鸦级"


# ═══════════════════════════════════════════════════
#  整单复制范围（只复制需采购区）
# ═══════════════════════════════════════════════════


def test_copy_button_only_buy(qapp, make_dlg):
    dlg = make_dlg()
    clip = QApplication.clipboard()
    with (
        patch.object(clip, "setText") as m_set,
        patch("ui_pyside6.views.procurement_tab.QMessageBox"),
    ):
        dlg._on_copy_to_clipboard()
    text = m_set.call_args.args[0]
    lines = text.splitlines()
    assert len(lines) == 2, "只应复制需采购区两行"
    assert "渡鸦级" not in text
    for line in lines:
        name, _, qty = line.partition("* ")
        assert qty.isdigit(), f"格式应为「名字* 数量」: {line!r}"
    names = {line.split("* ")[0] for line in lines}
    assert names == {"三钛合金", "类银超金属"}
    # 数量精确值
    assert "三钛合金* 1000" in lines


def test_copy_button_when_no_buy_rows(qapp, make_dlg):
    """需采购为空时按钮不复制已备足行。"""
    rows = [dict(r) for r in ROWS if r["type_id"] == 2001]
    dlg = make_dlg(rows=rows)
    assert dlg._buy_table.isHidden()
    clip = QApplication.clipboard()
    with (
        patch.object(clip, "setText") as m_set,
        patch("ui_pyside6.views.procurement_tab.QMessageBox"),
    ):
        dlg._on_copy_to_clipboard()
    m_set.assert_not_called()


# ═══════════════════════════════════════════════════
#  右键菜单定位触发表
# ═══════════════════════════════════════════════════


def test_context_menu_uses_sender(qapp, make_dlg):
    """右键菜单在各表上操作触发表：patch 模块级 QMenu 名（PySide6 原生 exec 无法 patch.object），
    用 addAction.side_effect 依次返回动作、exec 返回「删除此行」后验证只删对应表。"""
    dlg = make_dlg()
    buy_model = dlg._buy_table.model()
    stock_model = dlg._stock_table.model()

    def _emit(table):
        table.selectRow(0)
        with patch("ui_pyside6.views.procurement_tab.QMenu") as MockQMenu:
            m = MockQMenu.return_value
            actions = [MagicMock() for _ in range(4)]
            m.addAction.side_effect = actions  # 删除此行/修改数量/复制数量/复制此行
            m.exec.return_value = actions[0]  # 模拟点击「删除此行」
            table.customContextMenuRequested.emit(QPoint(1, 1))

    _emit(dlg._buy_table)  # 需采购表右键删除 row0（三钛合金）
    assert buy_model.rowCount() == 1
    assert [r["type_id"] for r in buy_model._rows] == [35]

    _emit(dlg._stock_table)  # 已备足表右键删除 row0（渡鸦级）
    assert stock_model.rowCount() == 0


# ═══════════════════════════════════════════════════
#  修改数量跨分区迁移
# ═══════════════════════════════════════════════════


def test_edit_qty_crosses_section(qapp, make_dlg):
    dlg = make_dlg()
    buy_model = dlg._buy_table.model()
    dlg._buy_table.selectRow(0)  # 三钛合金 to_buy=1000
    sel = dlg._buy_table.selectionModel().selectedRows()
    with patch("ui_pyside6.views.procurement_tab.QInputDialog.getDouble", return_value=(0.0, True)):
        dlg._on_edit_qty(dlg._buy_table, sel, buy_model)

    # 跨边界 → 重建分区：需采购只剩 1 行，已备足变 2 行
    assert dlg._buy_table.model().rowCount() == 1
    assert [r["type_id"] for r in dlg._buy_table.model()._rows] == [35]
    assert dlg._stock_table.model().rowCount() == 2
    assert all(r["to_buy"] <= 0 for r in dlg._stock_table.model()._rows)


# ═══════════════════════════════════════════════════
#  排序状态重放（_calculate 重建后保持）
# ═══════════════════════════════════════════════════


def test_sort_state_replayed_after_calculate(qapp, make_dlg):
    dlg = make_dlg()
    # 模拟用户在需采购表点击表头按「需采购」降序
    dlg._buy_table.horizontalHeader().setSortIndicator(3, Qt.SortOrder.DescendingOrder)
    assert dlg._sort_state.get(id(dlg._buy_table)) == (3, Qt.SortOrder.DescendingOrder)
    assert [r["to_buy"] for r in dlg._buy_table.model()._rows] == [1000, 100]

    # 重算（刷新/换价）→ _rebuild_sections 重建后重放排序
    dlg._calculate()
    assert dlg._buy_table.horizontalHeader().sortIndicatorSection() == 3
    assert dlg._buy_table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    assert [r["to_buy"] for r in dlg._buy_table.model()._rows] == [1000, 100]
