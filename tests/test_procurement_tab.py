"""采购小助手测试：双分区 / 表头排序 / 双击按列复制 / 整单复制范围 / 删除与手改的保持。

阶段 4b 把渲染交给 QML 后，本文件从「断言 Widgets 控件」改成「断言控制器与桥」：
**每条断言的意图与断言值都保持原样**（分区行数、复制文本、删除后不复活、排序不丢…），
只是取值入口从 `dlg._buy_table.model()` 换成 `dlg.section_rows("buy")`。
"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtGui import QGuiApplication

from ui_pyside6.views.procurement_tab import (
    ProcurementDialog,
    copy_cell_text,
    display_name,
    split_sections,
)
from ui_qml.bridge.procurement_bridge import procure_rows

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
    """构造 ProcurementDialog，patch get_container + aggregate_procurement 使重算返回固定 rows。

    补丁在测试期间保持生效，允许测试内再次重算（如排序状态重放）。
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
    buy, stock = split_sections(ROWS)
    assert [r["type_id"] for r in buy] == [34, 35]
    assert [r["type_id"] for r in stock] == [2001]


def test_split_sections_empty_half():
    buy, stock = split_sections([])
    assert buy == [] and stock == []
    buy, stock = split_sections([dict(ROWS[-1])])  # 全 to_buy=0
    assert buy == [] and len(stock) == 1


def test_copy_text_matches_display():
    """复制文本 = 显示文本去掉千分位（两处口径不得漂移）。"""
    for r in ROWS:
        shown = procure_rows([r])[0]["cells"]
        for col in range(7):
            assert copy_cell_text(r, col) == shown[col]["text"].replace(",", ""), f"物品 {r['type_id']} 列 {col}"


def test_display_name_prefers_zh_then_en_then_id():
    assert display_name({"type_id": 34, "zh_name": "三钛合金", "en_name": "Tritanium"}) == "三钛合金"
    assert display_name({"type_id": 34, "zh_name": "", "en_name": "Tritanium"}) == "Tritanium"
    assert display_name({"type_id": None}) == ""


# ═══════════════════════════════════════════════════
#  排序（在桥/控制器里，重建后不丢）
# ═══════════════════════════════════════════════════


def test_sort_numeric_and_name(qapp, make_dlg):
    """按列排序：数值列按值、名称列按显示名（`casefold`）—— 对齐原表模型的判据。"""
    dlg = make_dlg()

    dlg.sort_section("buy", 3)  # 需采购升序 [100, 1000]
    assert [r["to_buy"] for r in dlg.section_rows("buy")] == [100, 1000]

    dlg.sort_section("buy", 3)  # 再点同列 → 反向
    assert [r["to_buy"] for r in dlg.section_rows("buy")] == [1000, 100]

    dlg.sort_section("buy", 0)  # 换列 → 从升序开始
    names = [display_name(r) for r in dlg.section_rows("buy")]
    assert names == sorted(names)


def test_sort_survives_recalculate(qapp, make_dlg):
    """轮询重算不得丢排序。用升序：fixture 自然序 [1000, 100] 与排序序相反。"""
    dlg = make_dlg()
    dlg.sort_section("buy", 3)
    assert [r["to_buy"] for r in dlg.section_rows("buy")] == [100, 1000]

    dlg.recalculate()  # 模拟轮询 / 刷新重建分区
    assert dlg.sort_column("buy") == 3
    assert dlg.sort_ascending("buy") is True
    assert [r["to_buy"] for r in dlg.section_rows("buy")] == [100, 1000]


def test_no_fake_sort_on_start(qapp, make_dlg):
    """初始不显示排序箭头（`sort_column == -1`），行序保持原始。"""
    dlg = make_dlg()
    assert dlg.sort_column("buy") == -1
    assert [r["to_buy"] for r in dlg.section_rows("buy")] == [1000, 100]


def test_two_sections_are_independently_sorted(qapp, make_dlg):
    """两个分区各排各的（原版是两个独立表格控件，共用排序状态会让一边带偏另一边）。"""
    dlg = make_dlg()
    dlg.sort_section("buy", 3)
    assert dlg.sort_column("buy") == 3
    assert dlg.sort_column("stock") == -1


# ═══════════════════════════════════════════════════
#  对话框双分区 / 空结果
# ═══════════════════════════════════════════════════


def test_dialog_two_sections(qapp, make_dlg):
    dlg = make_dlg()
    assert len(dlg.section_rows("buy")) == 2
    assert len(dlg.section_rows("stock")) == 1
    assert "需采购" in dlg.section_label("buy")
    assert "库存已备足" in dlg.section_label("stock")
    assert "渡鸦级" not in dlg.section_label("buy")  # 渡鸦级属于已备足分区


def test_empty_rows_hides_tables(qapp, make_dlg):
    dlg = make_dlg(rows=[])
    assert dlg.section_rows("buy") == []
    assert dlg.section_rows("stock") == []
    assert dlg.summary_text() == "无活跃计划材料需求"


# ═══════════════════════════════════════════════════
#  双击复制（两分区都要生效，按列取内容）
# ═══════════════════════════════════════════════════


def test_double_click_copies_clicked_column(qapp, make_dlg):
    """双击哪列复制哪列：名称列→物品名，数量列→整数，价格/体积→两位小数（均无千分位）。
    用 setText spy 断言，规避全量跑时系统剪贴板读回被前置测试扰动的偶发。"""
    dlg = make_dlg()
    clip = QGuiApplication.clipboard()
    expected = {0: "三钛合金", 1: "1000", 2: "0", 3: "1000", 4: "5.00", 5: "5000.00", 6: "10.00"}
    with patch.object(clip, "setText") as m_set:
        for col, text in expected.items():
            dlg.copy_cell("buy", 0, col)
            assert m_set.call_args.args[0] == text, f"列 {col} 复制内容不符"
            assert dlg.copy_hint_text() == f"已复制: {text}"
    assert dlg._copy_hint_timer.isActive()

    with patch.object(clip, "setText") as m_set:
        dlg.copy_cell("stock", 0, 0)
        assert m_set.call_args.args[0] == "渡鸦级"


def test_copy_actions_use_status_hint_not_popup(qapp, make_dlg):
    """右键「复制数量」与工具栏「复制到剪贴板」走底部提示，不弹模态框。"""
    dlg = make_dlg()
    clip = QGuiApplication.clipboard()
    with patch.object(clip, "setText") as m_set:
        dlg.copy_qty("buy", 0)
        assert m_set.call_args.args[0] == "1000"
        assert dlg.copy_hint_text() == "已复制: 1000"

        dlg.copy_all_to_clipboard()
        assert "2 种材料" in dlg.copy_hint_text()


# ═══════════════════════════════════════════════════
#  整单复制范围（只复制需采购区）
# ═══════════════════════════════════════════════════


def test_copy_button_only_buy(qapp, make_dlg):
    dlg = make_dlg()
    clip = QGuiApplication.clipboard()
    with patch.object(clip, "setText") as m_set:
        dlg.copy_all_to_clipboard()
    text = m_set.call_args.args[0]
    lines = text.splitlines()
    assert len(lines) == 2, "只应复制需采购区两行"
    assert "渡鸦级" not in text
    for line in lines:
        _name, _, qty = line.partition("* ")
        assert qty.isdigit(), f"格式应为「名字* 数量」: {line!r}"
    names = {line.split("* ")[0] for line in lines}
    assert names == {"三钛合金", "类银超金属"}
    # 数量精确值
    assert "三钛合金* 1000" in lines


def test_copy_button_when_no_buy_rows(qapp, make_dlg):
    """需采购为空时按钮不复制已备足行。"""
    rows = [dict(r) for r in ROWS if r["type_id"] == 2001]
    dlg = make_dlg(rows=rows)
    assert dlg.section_rows("buy") == []
    clip = QGuiApplication.clipboard()
    with patch.object(clip, "setText") as m_set:
        dlg.copy_all_to_clipboard()
    m_set.assert_not_called()


# ═══════════════════════════════════════════════════
#  删除行（本次打开内生效，关闭窗口后恢复）
# ═══════════════════════════════════════════════════


def test_deleted_row_not_copied_after_recalculate(qapp, make_dlg):
    """删除的行不得被轮询重算放回来，否则「复制到剪贴板」会带上已删条目。"""
    dlg = make_dlg()
    dlg.delete_row("buy", 0)
    assert [r["type_id"] for r in dlg.section_rows("buy")] == [35]
    assert "已移除 1 项" in dlg.copy_hint_text()

    dlg.recalculate()  # 模拟 10s 轮询 / 刷新计算
    assert [r["type_id"] for r in dlg.section_rows("buy")] == [35]

    clip = QGuiApplication.clipboard()
    with patch.object(clip, "setText") as m_set:
        dlg.copy_all_to_clipboard()
    assert "三钛合金" not in m_set.call_args.args[0]
    assert "类银超金属" in m_set.call_args.args[0]


def test_deleted_rows_return_after_reopen(qapp, make_dlg):
    """删除只在本次打开内生效：关闭窗口再打开，被删的行要重新算回来。"""
    dlg = make_dlg()
    dlg.delete_row("buy", 0)
    assert dlg._deleted_ids

    dlg.close()  # closeEvent 清空删除记录
    assert dlg._deleted_ids == set()
    dlg.show()  # showEvent → _reload_plans → recalculate
    assert [r["type_id"] for r in dlg.section_rows("buy")] == [34, 35]


def test_esc_close_also_resets_deletions(qapp, make_dlg):
    """Esc 关闭走 QDialog.done()（不经 closeEvent），同样要重置删除记录。"""
    dlg = make_dlg()
    dlg.delete_row("buy", 0)
    assert dlg._deleted_ids

    dlg.reject()  # 等价于按 Esc
    assert dlg._deleted_ids == set()
    dlg.recalculate()
    assert [r["type_id"] for r in dlg.section_rows("buy")] == [34, 35]


# ═══════════════════════════════════════════════════
#  右键菜单按分区定位
# ═══════════════════════════════════════════════════


def test_row_actions_are_section_scoped(qapp, make_dlg):
    """右键动作必须作用于「点它的那个分区」：QML 侧把 section 名传进来。"""
    dlg = make_dlg()
    dlg.delete_row("buy", 0)  # 需采购表删第一行（三钛合金）
    assert [r["type_id"] for r in dlg.section_rows("buy")] == [35]
    assert [r["type_id"] for r in dlg.section_rows("stock")] == [2001]

    dlg.delete_row("stock", 0)  # 已备足表删第一行（渡鸦级）
    assert dlg.section_rows("stock") == []


# ═══════════════════════════════════════════════════
#  修改数量跨分区迁移 + 手改保持
# ═══════════════════════════════════════════════════


def test_edit_qty_crosses_section(qapp, make_dlg):
    dlg = make_dlg()
    with patch("ui_qml.bridge.input_dialog.InputQmlDialog.get_double", return_value=(0.0, True)):
        dlg.edit_qty("buy", 0)  # 三钛合金 to_buy=1000 → 0

    # 跨边界 → 重建分区：需采购只剩 1 行，已备足变 2 行
    assert [r["type_id"] for r in dlg.section_rows("buy")] == [35]
    assert len(dlg.section_rows("stock")) == 2
    assert all(r["to_buy"] <= 0 for r in dlg.section_rows("stock"))


def test_manual_qty_survives_recalculate(qapp, make_dlg):
    """轮询重算不得丢弃用户手改的采购量（`_manual_overrides` 回放）。"""
    dlg = make_dlg()
    tid = dlg.section_rows("buy")[0]["type_id"]

    with patch("ui_qml.bridge.input_dialog.InputQmlDialog.get_double", return_value=(7.0, True)):
        dlg.edit_qty("buy", 0)
    assert dlg._manual_overrides[int(tid)] == 7.0

    dlg.recalculate()  # 模拟轮询重算
    row = next(r for r in dlg.section_rows("buy") if r["type_id"] == tid)
    assert row["to_buy"] == 7.0
    assert row["total"] == 7.0 * row["price"]


# ═══════════════════════════════════════════════════
#  QML 窗口本身
# ═══════════════════════════════════════════════════


def test_qml_window_loads(qapp, make_dlg):
    """整窗交给 QML 后，必须确认它真的加载起来了 —— 构造成功不等于 QML 没报错。

    批次 7.4 起根元素是 `Window`（不再是 `Item`），`_build_window` 会在
    `component.errors()` 非空或根不是 `Window` 时直接抛；所以这里只要窗口与它的
    contentItem 都在，就说明 QML 真的建出来了。
    """
    dlg = make_dlg()
    assert dlg._window is not None, "ProcurementWindow.qml 没建出窗口"
    assert dlg._window.contentItem() is not None, "ProcurementWindow.qml 加载失败（没有 contentItem）"


def test_two_sections_are_in_a_draggable_split():
    """回归：两栏必须是**可拖动**的分隔（原 `QSplitter`，现在是对应的 `SplitView`）。

    当初的教训是「固定比例会把『库存充足』那栏挤到看不见」，所以这条不能只靠
    肉眼看过就算 —— 加一条静态守卫，有人把它换成固定高度时立刻失败。
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "ui_qml/qml/pages/ProcurementWindow.qml").read_text(
        encoding="utf-8"
    )
    assert "SplitView" in src, "两栏必须放在可拖动的 SplitView 里，不能是固定布局"
    assert "SplitView.fillHeight" in src, "两个分区都要参与分隔高度分配"
    assert src.count("SectionPane {") >= 2, "两个分区各一个 SectionPane"
