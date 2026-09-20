"""采购小助手测试：双分区 / 表头排序 / 双击按列复制 / 整单复制范围 / 删除与手改的保持。

阶段 4b 把渲染交给 QML 后，本文件从「断言 Widgets 控件」改成「断言控制器与桥」：
**每条断言的意图与断言值都保持原样**（分区行数、复制文本、删除后不复活、排序不丢…），
只是取值入口从 `dlg._buy_table.model()` 换成 `dlg.section_rows("buy")`。
"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtGui import QGuiApplication

from tests.qml_click import spin as _spin
from ui_qml.bridge.procurement_bridge import procure_rows, procure_table_headers
from ui_qml.views.procurement_tab import (
    ProcurementDialog,
    copy_cell_text,
    display_name,
    split_sections,
)

pytestmark = pytest.mark.ui

# to_buy>0：34/35 需采购；to_buy=0：2001 库存已备足
# `spread`（(卖价−买价) × 需采购量，金额）：34 有双边挂单、35 只有单边（None）、2001 双边同向
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
        "spread": 1.25,
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
        "spread": None,
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
        "spread": 0.1,
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
    """复制文本 = 显示文本去掉千分位（两处口径不得漂移）。

    唯一例外是**算不出**的格子（价差单边挂单，显示 `-`）：复制给空串而不是 `-`，
    否则粘进游戏输入框的是一串废字符。见 `test_copying_a_one_sided_spread_does_not_copy_a_fake_zero`。
    """
    for r in ROWS:
        shown = procure_rows([r])[0]["cells"]
        for col in range(len(shown)):
            if shown[col]["text"] == "-":
                assert copy_cell_text(r, col) == ""
                continue
            assert copy_cell_text(r, col) == shown[col]["text"].replace(",", ""), f"物品 {r['type_id']} 列 {col}"


# ═══════════════════════════════════════════════════
#  列结构（表头 / 排序字段 / 复制字段 / 单元格四处按索引对齐）
# ═══════════════════════════════════════════════════


def test_column_lists_stay_index_aligned():
    """四处列定义必须同长同序 —— 它们**按索引对齐**，插错位就是「排序按这列、复制按那列」。

    串列不报错也不崩，只是数字悄悄对不上，所以用一条显式断言钉住。
    """
    from ui_qml.bridge import procurement_bridge as pb

    assert len(pb._HEADERS) == len(pb._SORT_FIELDS) == len(pb._COPY_FIELDS) == len(pb._COLUMNS)
    assert pb._HEADERS[3] == "买卖差价"
    assert pb._SORT_FIELDS[3] == "spread", "价差列要能排序（表头点得动）"
    assert pb._COPY_FIELDS[3] == "spread"
    assert [c["title"] for c in pb._COLUMNS] == pb._HEADERS
    assert procure_table_headers() == pb._HEADERS


def test_narrowest_window_clips_nothing(qapp, make_dlg):
    """窗口拉到最小宽时：工具栏、按钮行、表格列一个都不能被裁（用户报过两次「打开显示不全」）。

    为什么非量不可：`FSummaryTable.colWidth` **不会**为了塞下而挤固定列 —— 它只把
    弹性列压到 80 下限，然后整行溢出、右边几列直接看不见（静默，不报错）。

    两层一起兜：
      - **静态**：固定列宽之和必须与 `ProcurementWindow.qml` 的 `contentMinWidth` 算式常数一致
        （列宽改宽了、窗口算式没跟着改 → 漂移即裁切）；
      - **渲染**：按最小宽真跑一遍，量工具栏、按钮行、表格列的右边缘。

    按钮行是 `Flow`（加按钮只多占一行高度）；换回单行 `RowLayout` 就会把窗口顶宽、切掉最右边的控件。
    """
    from pathlib import Path

    from ui_qml.bridge import procurement_bridge as pb

    cell_padding = 12  # 与 FSummaryTable.cellPadding 同口径（Theme 缩放为 1 时）
    raw_fixed = sum(c["width"] for c in pb._COLUMNS if c["width"] > 0)  # 固定列宽本身，不含内边距
    assert sum(1 for c in pb._COLUMNS if c["width"] <= 0) == 1, "只留名称列吃满剩余空间"

    src = (Path(__file__).resolve().parent.parent / "ui_qml/qml/pages/ProcurementWindow.qml").read_text(
        encoding="utf-8"
    )
    assert f"contentMinWidth: {raw_fixed} + " in src, (
        f"QML 最小宽算式里的固定列合计不是 {raw_fixed}（改了列宽就得同步改算式，否则右侧列被裁）"
    )
    assert "+ 80 + 16" in src, "算式里少了「名称列下限 80 + 左右边距 16」"
    assert f"Math.round({cell_padding} * Theme.fontScale) * " in src, "内边距没跟字体缩放走"

    dlg = make_dlg()
    win = dlg._window
    assert win is not None
    win.show()
    _spin(120)
    win.setWidth(win.minimumWidth())
    _spin(120)
    root = win.contentItem()

    def _right_edge(item) -> float:
        return max((c.x() + c.width() for c in item.childItems() if c.isVisible()), default=0.0)

    for name in ("toolbar", "actionBar"):
        item = _find_item(root, name)
        assert item is not None, f"{name} 不见了"
        assert _right_edge(item) <= item.width() + 0.5, f"{name} 里有控件超出右边界（会被裁）"

    for name in ("table_buy", "table_stock"):
        table = _find_item(root, name)
        assert table is not None, f"{name} 不见了"
        cols = next(
            (c for c in _walk_items(table) if len([k for k in c.childItems() if k.width() > 0]) == len(pb._COLUMNS)),
            None,
        )
        assert cols is not None, f"{name} 里没找到 {len(pb._COLUMNS)} 个列位"
        assert _right_edge(cols) <= cols.width() + 0.5, f"{name} 的列装不下（右侧列被裁）"
    win.close()


def _walk_items(item, depth: int = 0):
    """深度优先遍历 `childItems()`（限 5 层，够到表头里的列位）。"""
    yield item
    if depth >= 5:
        return
    for ch in item.childItems():
        yield from _walk_items(ch, depth + 1)


def _find_item(item, name: str):
    return next((c for c in _walk_items(item) if c.objectName() == name), None)


def test_spread_cell_renders_value_or_dash():
    """价差列：双边挂单给数值（千分位、两位小数），单边给 `-`（不是 0）。"""
    assert [r["cells"][3]["text"] for r in procure_rows(ROWS)] == ["1.25", "-", "0.10"]


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

    dlg.sort_section("buy", 2)  # 需采购升序 [100, 1000]
    assert [r["to_buy"] for r in dlg.section_rows("buy")] == [100, 1000]

    dlg.sort_section("buy", 2)  # 再点同列 → 反向
    assert [r["to_buy"] for r in dlg.section_rows("buy")] == [1000, 100]

    dlg.sort_section("buy", 0)  # 换列 → 从升序开始
    names = [display_name(r) for r in dlg.section_rows("buy")]
    assert names == sorted(names)


def test_sort_by_spread_treats_unknown_as_zero(qapp, make_dlg):
    """买卖差价列能排序；算不出的那一格（`None`）按 0 参与比较，不炸也不排到天上。

    行 34 的 spread=1.25、行 35 是 `None`（单边挂单）→ 升序应为 35、34。
    """
    dlg = make_dlg()

    dlg.sort_section("buy", 3)
    assert [r["type_id"] for r in dlg.section_rows("buy")] == [35, 34]

    dlg.sort_section("buy", 3)  # 反向
    assert [r["type_id"] for r in dlg.section_rows("buy")] == [34, 35]


def test_sort_survives_recalculate(qapp, make_dlg):
    """轮询重算不得丢排序。用升序：fixture 自然序 [1000, 100] 与排序序相反。"""
    dlg = make_dlg()
    dlg.sort_section("buy", 2)  # 需采购
    assert [r["to_buy"] for r in dlg.section_rows("buy")] == [100, 1000]

    dlg.recalculate()  # 模拟轮询 / 刷新重建分区
    assert dlg.sort_column("buy") == 2
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
    dlg.sort_section("buy", 2)
    assert dlg.sort_column("buy") == 2
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
    """双击哪列复制哪列：名称列→物品名，数量列→整数，价差/总价→两位小数（均无千分位）。
    用 setText spy 断言，规避全量跑时系统剪贴板读回被前置测试扰动的偶发。"""
    dlg = make_dlg()
    clip = QGuiApplication.clipboard()
    expected = {0: "三钛合金", 1: "1000", 2: "1000", 3: "1.25", 4: "5000.00"}
    with patch.object(clip, "setText") as m_set:
        for col, text in expected.items():
            dlg.copy_cell("buy", 0, col)
            assert m_set.call_args.args[0] == text, f"列 {col} 复制内容不符"
            assert dlg.copy_hint_text() == f"已复制: {text}"
    assert dlg._copy_hint_timer.isActive()

    with patch.object(clip, "setText") as m_set:
        dlg.copy_cell("stock", 0, 0)
        assert m_set.call_args.args[0] == "渡鸦级"


def test_copying_a_one_sided_spread_does_not_copy_a_fake_zero(qapp, make_dlg):
    """单边挂单时价差是「算不出」而不是 0：那一格不该复制出 `0.00`。

    `copy_cell_text` 对 `None` 返回空串 → `copy_cell` 直接不复制（也不弹「已复制」提示）。
    """
    dlg = make_dlg()
    clip = QGuiApplication.clipboard()
    with patch.object(clip, "setText") as m_set:
        dlg.copy_cell("buy", 1, 3)  # 第 1 行（类银超金属）的价差列为 None
        m_set.assert_not_called()
    assert dlg.copy_hint_text() == ""
    assert copy_cell_text(ROWS[1], 3) == ""
    assert "0.00" not in copy_cell_text(ROWS[1], 3)


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


class TestCompleteAllReload:
    """一键完成后必须整表重载 `_active_plans`。

    只调 `recalculate()` 的话，已完成（或被母项清理）的行会滞留在 `_active_plans` 里，
    下次点「完成所有」会把它们再算一遍、汇总文案失真。
    """

    def test_reloads_active_plans_after_complete(self, qapp, make_dlg, monkeypatch):
        from ui_qml.bridge import complete_guard

        ready = [
            {
                "id": 1,
                "status": "ready",
                "product_name": "母项",
                "product_type_id": 2001,
                "runs": 1,
                "parallels": 1,
            }
        ]
        dlg = make_dlg(plans=ready)
        dlg._active_plans = ready

        calls: list[str] = []
        monkeypatch.setattr(dlg, "_reload_plans", lambda: calls.append("reload"))
        monkeypatch.setattr(dlg, "recalculate", lambda: calls.append("calculate"))
        monkeypatch.setattr(complete_guard, "confirm_bp_shortfall", lambda *a, **k: False)
        monkeypatch.setattr(
            "services.plan_execution.complete_plan",
            lambda plan, **kw: {"ok": True, "deposited": 0, "removed": 2},
        )
        monkeypatch.setattr(dlg, "show_copy_hint", lambda *a, **k: None)

        dlg.complete_all()

        assert calls == ["reload"], "完成后必须走 _reload_plans（其内部已含 recalculate）"


# ═══════════════════════════════════════════════════
#  置顶：显示 / 前置时重申
#
#  回归背景：`_restore_pin` 只在**构造时**设过一次置顶，而那一刻窗口还没显示
#  （SetWindowPos 作用在一个随后会被 Qt 重新定位、显示的平台窗口上）；而
#  `QWindow.raise_()` 在 Windows 上是 `SetWindowPos(HWND_TOP)` —— 不带 HWND_TOPMOST
#  的插入位置。用户看到的是「勾着置顶却没置顶，再点一次才好」。
#  现在这两条路径都重申一次，幂等、一次 Win32 调用。
# ═══════════════════════════════════════════════════


def test_reassert_pin_only_touches_the_window_when_pinned(monkeypatch):
    """`reassert_pin` 是幂等的空操作：没勾置顶、或窗口还没建，都不该去动窗口。"""
    from ui_qml import pin_utils

    calls: list[bool] = []
    monkeypatch.setattr(pin_utils, "apply_window_pin", lambda window, checked: calls.append(checked))

    pin_utils.reassert_pin(object(), False)
    assert calls == [], "没勾置顶时不该白跑一次 Win32 调用"
    pin_utils.reassert_pin(None, True)
    assert calls == [], "窗口还没建时不能炸"
    pin_utils.reassert_pin(object(), True)
    assert calls == [True]


def test_show_and_raise_reassert_the_pin(qapp, make_dlg, monkeypatch):
    """窗口显示、以及置顶态下的「前置」，都必须重申置顶。"""
    dlg = make_dlg()
    calls: list[bool] = []
    monkeypatch.setattr(
        "ui_qml.views.procurement_tab.reassert_pin",
        lambda window, pinned: calls.append(bool(pinned)),
    )

    dlg._pinned = True
    dlg.window_visibility_changed(True)
    assert calls == [True], "显示时要重申置顶"

    calls.clear()
    dlg.raise_()
    assert calls == [True], "置顶态下的「前置」要带 HWND_TOPMOST 一起做，不能走裸 raise_()"

    calls.clear()
    dlg._pinned = False
    dlg.raise_()
    assert calls == [], "没置顶时前置走原生路径"


def test_recalculate_excludes_running_sublines(qapp, make_dlg, monkeypatch):
    """重算必须把「正在生产的子项产线」的产物排除掉，且这个集合按**全量**计划算。

    回归：排除集原先由 `aggregate_procurement` 从**传进来的** `plans` 现算，而本窗传的是
    筛过的「备料中」计划 —— 子线一进生产中就不在那份列表里，产物被当成没有子线、
    重复计成待采购（用户报的「电磁发生器已在生产，采购仍报缺 2504」）。
    """
    seen: dict = {}

    def _fake(conn, plans, **kw):
        seen.update({"plans": plans, **kw})
        return ([], 0.0, 0.0)

    dlg = make_dlg(
        plans=[
            {"id": 1, "product_type_id": 3955, "runs": 1, "parallels": 1, "status": "pending", "materials_ready": 1},
            # 子项产线：生产中（不会进「备料中」那一份），但它的产物必须被排除
            {"id": 2, "product_type_id": 11694, "sub_level": 1, "status": "in_progress", "materials_ready": 1},
        ]
    )
    # 补丁必须在 `make_dlg` **之后**打：夹具自己也会 patch 这个函数，先打会被它盖掉
    monkeypatch.setattr("services.plan_aggregator.aggregate_procurement", _fake)
    dlg.recalculate()

    assert seen["self_made"] == {11694}, "自制件集合没按全量计划算"
    assert [p["id"] for p in seen["plans"]] == [1], "传给聚合的仍应只有「备料中」那一份"
