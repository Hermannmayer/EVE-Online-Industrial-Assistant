"""待采购对话框改造测试：双表分区 / 表头排序 / 双击按列复制 / 整单复制范围 / 主题与复制提示"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

import ui_pyside6.theme as theme
from ui_pyside6.views.procurement_tab import (
    ProcurementDialog,
    ProcureTableModel,
    _copy_cell_text,
    _display_name,
    _split_sections,
)

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
            patch("services.plan_service.load_active_plans_for_procurement", return_value=list(plans or [])),
            patch("services.inventory_manager.get_default_mat_hangar_and_system", return_value=(None, None)),
        ]
        for p in patchers:
            p.start()
        dlg = ProcurementDialog()
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
    assert not dlg._buy_section.isHidden()
    assert not dlg._stock_section.isHidden()
    assert "渡鸦级" not in dlg._buy_label.text()  # 渡鸦级属于已备足分区


def test_empty_rows_hides_tables(qapp, make_dlg):
    dlg = make_dlg(rows=[])
    assert dlg._buy_table.model() is None
    assert dlg._stock_table.model() is None
    # 两栏包进 QSplitter 后，隐藏的是分区容器（子控件随之不可见）
    assert dlg._buy_section.isHidden()
    assert dlg._stock_section.isHidden()
    assert not dlg._buy_label.isVisible()
    assert not dlg._stock_label.isVisible()
    assert dlg._summary_label.fullText() == "无活跃计划材料需求"


# ═══════════════════════════════════════════════════
#  双击复制（两表都要生效，按列取内容）
# ═══════════════════════════════════════════════════


def test_double_click_copies_clicked_column(qapp, make_dlg):
    """双击哪列复制哪列：名称列→物品名，数量列→整数，价格/体积→两位小数（均无千分位）。
    用 setText spy 断言，规避全量跑时系统剪贴板读回被前置测试扰动的偶发。"""
    dlg = make_dlg()
    buy_model = dlg._buy_table.model()
    clip = QApplication.clipboard()
    expected = {0: "三钛合金", 1: "1000", 2: "0", 3: "1000", 4: "5.00", 5: "5000.00", 6: "10.00"}
    with patch.object(clip, "setText") as m_set:
        for col, text in expected.items():
            dlg._on_row_double_click(buy_model.index(0, col))
            assert m_set.call_args.args[0] == text, f"列 {col} 复制内容不符"
            assert dlg._copy_hint.fullText() == f"已复制: {text}"
    assert dlg._copy_hint_timer.isActive()

    with patch.object(clip, "setText") as m_set:
        dlg._on_row_double_click(dlg._stock_table.model().index(0, 0))
        assert m_set.call_args.args[0] == "渡鸦级"


def test_copy_text_matches_display(qapp, make_dlg):
    """复制文本 = 显示文本去掉千分位（两处口径不得漂移）。"""
    dlg = make_dlg()
    model = dlg._buy_table.model()
    for row in range(model.rowCount()):
        r = model.get_row(row)
        for col in range(model.columnCount()):
            shown = model.data(model.index(row, col), Qt.ItemDataRole.DisplayRole)
            assert _copy_cell_text(r, col) == str(shown).replace(",", ""), f"行{row} 列{col}"


def test_copy_actions_use_status_hint_not_popup(qapp, make_dlg):
    """右键「复制数量」与工具栏「复制到剪贴板」改走底部提示，不再弹模态框。"""
    dlg = make_dlg()
    clip = QApplication.clipboard()
    buy_model = dlg._buy_table.model()
    dlg._buy_table.selectRow(0)
    sel = dlg._buy_table.selectionModel().selectedRows()
    with (
        patch.object(clip, "setText") as m_set,
        patch("ui_pyside6.views.procurement_tab.QMessageBox") as m_box,
    ):
        dlg._on_copy_qty(dlg._buy_table, sel, buy_model)
        assert m_set.call_args.args[0] == "1000"
        assert dlg._copy_hint.fullText() == "已复制: 1000"

        dlg._on_copy_to_clipboard()
        assert "2 种材料" in dlg._copy_hint.fullText()
    m_box.information.assert_not_called()


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
    assert dlg._buy_section.isHidden()
    clip = QApplication.clipboard()
    with (
        patch.object(clip, "setText") as m_set,
        patch("ui_pyside6.views.procurement_tab.QMessageBox"),
    ):
        dlg._on_copy_to_clipboard()
    m_set.assert_not_called()


# ═══════════════════════════════════════════════════
#  删除行（本次打开内生效，关闭窗口后恢复）
# ═══════════════════════════════════════════════════


def test_deleted_row_not_copied_after_recalculate(qapp, make_dlg):
    """删除的行不得被轮询重算放回来，否则「复制到剪贴板」会带上已删条目。"""
    dlg = make_dlg()
    model = dlg._buy_table.model()
    dlg._buy_table.selectRow(0)
    sel = dlg._buy_table.selectionModel().selectedRows()
    dlg._on_delete_row(dlg._buy_table, sel, model)
    assert [r["type_id"] for r in dlg._buy_table.model()._rows] == [35]
    assert "已移除 1 项" in dlg._copy_hint.fullText()

    dlg._calculate()  # 模拟 10s 轮询 / 刷新计算
    assert [r["type_id"] for r in dlg._buy_table.model()._rows] == [35]

    clip = QApplication.clipboard()
    with patch.object(clip, "setText") as m_set:
        dlg._on_copy_to_clipboard()
    assert "三钛合金" not in m_set.call_args.args[0]
    assert "类银超金属" in m_set.call_args.args[0]


def test_deleted_rows_return_after_reopen(qapp, make_dlg):
    """删除只在本次打开内生效：关闭窗口再打开，被删的行要重新算回来。"""
    dlg = make_dlg()
    dlg._buy_table.selectRow(0)
    sel = dlg._buy_table.selectionModel().selectedRows()
    dlg._on_delete_row(dlg._buy_table, sel, dlg._buy_table.model())
    assert dlg._deleted_ids

    dlg.close()  # closeEvent 清空删除记录
    assert dlg._deleted_ids == set()
    dlg.show()  # showEvent → _reload_plans → _calculate
    assert [r["type_id"] for r in dlg._buy_table.model()._rows] == [34, 35]


def test_esc_close_also_resets_deletions(qapp, make_dlg):
    """Esc 关闭走 QDialog.done()（不经 closeEvent），同样要重置删除记录。"""
    dlg = make_dlg()
    dlg._buy_table.selectRow(0)
    sel = dlg._buy_table.selectionModel().selectedRows()
    dlg._on_delete_row(dlg._buy_table, sel, dlg._buy_table.model())
    assert dlg._deleted_ids

    dlg.reject()  # 等价于按 Esc
    assert dlg._deleted_ids == set()
    dlg._calculate()
    assert [r["type_id"] for r in dlg._buy_table.model()._rows] == [34, 35]


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
#  排序保持（_calculate 重建后不丢）
# ═══════════════════════════════════════════════════


def test_sort_survives_recalculate(qapp, make_dlg):
    """轮询重算不得丢排序。用升序：fixture 自然序 [1000, 100] 与排序序相反，
    修复前（setModel 不重排 + setSortIndicator 同值不发声）这里会回退成 [1000, 100]。"""
    dlg = make_dlg()
    dlg._buy_table.horizontalHeader().setSortIndicator(3, Qt.SortOrder.AscendingOrder)
    assert [r["to_buy"] for r in dlg._buy_table.model()._rows] == [100, 1000]

    dlg._calculate()  # 模拟轮询 / 刷新重建分区
    assert dlg._buy_table.horizontalHeader().sortIndicatorSection() == 3
    assert dlg._buy_table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
    assert [r["to_buy"] for r in dlg._buy_table.model()._rows] == [100, 1000]


def test_no_fake_sort_indicator_on_start(qapp, make_dlg):
    """初始不得显示 Qt 默认的 (第 0 列, 降序) 假排序箭头，行序保持原始。"""
    dlg = make_dlg()
    assert dlg._buy_table.horizontalHeader().sortIndicatorSection() == -1
    assert [r["to_buy"] for r in dlg._buy_table.model()._rows] == [1000, 100]


# ═══════════════════════════════════════════════════
#  主题（跟随全局主题）
# ═══════════════════════════════════════════════════


def test_dialog_applies_global_stylesheet(qapp, make_dlg):
    """对话框必须整套套用全局 QSS：此前只给几个 label 设了内联颜色，窗口是系统默认灰白。"""
    dlg = make_dlg()
    assert "QTableView" in dlg.styleSheet()
    try:
        theme.apply_theme("light")
        assert theme.ONE_LIGHT["BG_DARK"] in dlg.styleSheet()
    finally:
        theme.apply_theme("one-dark")


# ═══════════════════════════════════════════════════
#  两栏可拖动 + 轮询重算不丢手改
# ═══════════════════════════════════════════════════


def test_two_sections_in_splitter(qapp, make_dlg):
    """回归：两栏必须放进可拖动的 QSplitter（固定比例会把「库存充足」挤到看不见）。"""
    from PySide6.QtWidgets import QSplitter

    dlg = make_dlg()
    assert isinstance(dlg._splitter, QSplitter)
    assert dlg._splitter.orientation() == Qt.Orientation.Vertical
    assert dlg._splitter.count() == 2
    assert dlg._splitter.childrenCollapsible() is False  # 不允许拖到折叠
    assert dlg._splitter.isCollapsible(0) is False
    assert dlg._splitter.isCollapsible(1) is False
    assert dlg._splitter.widget(0) is dlg._buy_section
    assert dlg._splitter.widget(1) is dlg._stock_section


def test_manual_qty_survives_recalculate(qapp, make_dlg):
    """轮询重算不得丢弃用户手改的采购量（_manual_overrides 回放）。"""
    dlg = make_dlg()
    model = dlg._buy_table.model()
    dlg._buy_table.selectRow(0)
    sel = dlg._buy_table.selectionModel().selectedRows()
    tid = model.get_row(0)["type_id"]

    with patch("ui_pyside6.views.procurement_tab.QInputDialog.getDouble", return_value=(7.0, True)):
        dlg._on_edit_qty(dlg._buy_table, sel, model)
    assert dlg._manual_overrides[int(tid)] == 7.0

    dlg._calculate()  # 模拟轮询重算
    row = next(r for r in dlg._buy_table.model()._rows if r["type_id"] == tid)
    assert row["to_buy"] == 7.0
    assert row["total"] == 7.0 * row["price"]
