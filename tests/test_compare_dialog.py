"""批量对比对话框测试 — 依赖 qapp + mock"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QCoreApplication

from ui_pyside6.theme import ONE_LIGHT, apply_theme
from ui_pyside6.views.compare_dialog import (
    COMPARE_COLS_MFG,
    CompareDialog,
    CompareTableModel,
    _fmt_tag,
    _format_isk,
)

# ═══════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════


@pytest.fixture(autouse=True)
def reset_theme():
    yield
    apply_theme("dark")


def _make_mock_db():
    """创建一个 DB mock，_item_name / _search_items 所需"""
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
    """Mock DB + char_settings_view"""
    db = _make_mock_db()
    cont = MagicMock()
    cont.db = db
    with (
        patch("ui_pyside6.views.compare_dialog.get_container", return_value=cont),
        patch("ui_pyside6.views.compare_dialog.get_character_list", return_value=["main", "alt"]),
        patch("ui_pyside6.views.compare_dialog.get_character", return_value={"skills": {}}),
    ):
        yield


# ═══════════════════════════════════════════
#  CompareDialog 构造 & 主题
# ═══════════════════════════════════════════


def test_dialog_constructor(qapp, mock_deps):
    """对话框基本构造不崩溃"""
    dlg = CompareDialog(parent=None)
    assert dlg.windowTitle() == "批量对比"
    assert dlg._selected_items == []
    dlg.close()


def test_dialog_with_initial_items(qapp, mock_deps):
    """带预选物品构造不崩溃"""
    items = [{"type_id": 2001, "name": "渡鸦级"}]
    dlg = CompareDialog(initial_items=items, parent=None)
    assert len(dlg._selected_items) >= 1
    dlg.close()


def test_dialog_has_theme_listener(qapp, mock_deps):
    """对话框有 _on_theme_changed 方法并注册了 listener"""
    dlg = CompareDialog(parent=None)
    assert hasattr(dlg, "_on_theme_changed")
    # 切换主题后样式表应包含主题色
    apply_theme("light")
    QCoreApplication.processEvents()
    light_ss = dlg.styleSheet()
    assert ONE_LIGHT["BG_DARK"] in light_ss or ONE_LIGHT["TEXT_PRIMARY"] in light_ss
    dlg.close()


def test_dialog_close_without_worker(qapp, mock_deps):
    """关闭对话框（无 worker）不崩溃"""
    dlg = CompareDialog(parent=None)
    dlg.close()
    assert True


# ═══════════════════════════════════════════
#  CompareTableModel
# ═══════════════════════════════════════════


def test_table_model_initial_state():
    """表格模型初始行列数为 0"""
    model = CompareTableModel(mode="mfg")
    assert model.rowCount() == 0
    assert model.columnCount() == len(COMPARE_COLS_MFG)


def test_table_model_set_rows():
    """set_rows 后行列数正确"""
    model = CompareTableModel(mode="mfg")
    rows = [
        {
            "name": "ItemA",
            "cost": 100.0,
            "revenue": 150.0,
            "profit": 50.0,
            "margin": 33.3,
            "score": 9.5,
            "isk_per_hour": 10000.0,
            "runs_per_day": 24,
            "status": "",
        },
    ]
    model.set_rows(rows)
    assert model.rowCount() == 1
    assert model.columnCount() == len(COMPARE_COLS_MFG)


def test_table_model_mode_switch():
    """切换模式后列数变化"""
    model = CompareTableModel(mode="mfg")
    mfg_cols = model.columnCount()
    model.set_mode("trade")
    trade_cols = model.columnCount()
    assert mfg_cols == 9  # COMPARE_COLS_MFG
    assert trade_cols == 8  # COMPARE_COLS_TRADE


# ═══════════════════════════════════════════
#  Helper 函数
# ═══════════════════════════════════════════


def test_format_isk_billions():
    assert _format_isk(2_500_000_000) == "2.50B"


def test_format_isk_millions():
    assert _format_isk(12_500_000) == "12.50M"


def test_format_isk_thousands():
    assert _format_isk(3_200) == "3.2K"


def test_format_isk_small():
    assert _format_isk(999) == "999"


def test_format_isk_negative():
    assert _format_isk(-100) == "-100"


def test_format_tag_veto():
    """有 veto 时返回 ✗"""
    assert _fmt_tag(100_000_000, veto="no_depth") == "✗"


def test_format_tag_s_rank():
    """日均利润 >= 50M 返回 S 级"""
    assert _fmt_tag(50_000_000) == "0.5亿 S"


def test_format_tag_a_rank():
    """日均利润 >= 10M 返回 A 级"""
    assert _fmt_tag(10_000_000) == "1000万 A"


def test_format_tag_b_rank():
    """日均利润 >= 1M 返回 B 级"""
    assert _fmt_tag(1_000_000) == "100万 B"


def test_format_tag_c_rank():
    """日均利润 >= 100K 返回 C 级"""
    assert _fmt_tag(100_000) == "10万 C"


def test_format_tag_d_rank():
    """日均利润 < 100K 返回 D 级"""
    assert _fmt_tag(50_000) == "5万 D"
