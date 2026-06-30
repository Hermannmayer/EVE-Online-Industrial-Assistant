"""评分弹窗测试 — 依赖 qapp + mock"""

from unittest.mock import MagicMock, patch

import pytest

import ui_pyside6.theme as theme
from ui_pyside6.theme import apply_theme
from ui_pyside6.views.score_dialogs import MfgDlg, ScoreW, TradeDlg, _fmt_tag

# ═══════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════


@pytest.fixture(autouse=True)
def reset_theme():
    yield
    apply_theme("dark")


@pytest.fixture
def mock_char_settings():
    with (
        patch("ui_pyside6.views.score_dialogs.get_character_list", return_value=["main", "alt"]),
        patch("ui_pyside6.views.score_dialogs.get_character", return_value={"skills": {"工业理论": 5}}),
    ):
        yield


@pytest.fixture
def mock_container():
    """Mock get_container for DB access"""
    cur = MagicMock()
    cur.fetchone.return_value = None  # _icon_label 和 DB 查询
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value = cur
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    db = MagicMock()
    db.connect.return_value = cm
    cont = MagicMock()
    cont.db = db
    with patch("ui_pyside6.views.score_dialogs.get_container", return_value=cont):
        yield


# ═══════════════════════════════════════════
#  MfgDlg
# ═══════════════════════════════════════════


def test_mfg_dlg_constructor(qapp, mock_char_settings, mock_container):
    """MfgDlg 基本构造不崩溃"""
    dlg = MfgDlg(parent=None)
    assert dlg.windowTitle() == "制造评分设置"
    assert hasattr(dlg, "get")
    dlg.close()


def test_mfg_dlg_with_type_id(qapp, mock_char_settings, mock_container):
    """带 type_id 的构造不崩溃（_icon_label + DB 查询）"""
    dlg = MfgDlg(type_id=2001, parent=None)
    assert dlg.windowTitle() != ""  # 标题至少不为空
    dlg.close()


def test_mfg_dlg_with_current(qapp, mock_char_settings, mock_container):
    """带 current 配置的构造正确初始化控件"""
    cfg = {"hub": "Amarr", "char": "alt", "tax": 2.5}
    dlg = MfgDlg(current=cfg, parent=None)
    # 验证下拉框选项（即使无法完全验证 setCurrentText，至少不崩溃）
    assert dlg.h.currentText() == "Amarr"
    assert dlg.t.value() == 2.5
    dlg.close()


def test_mfg_dlg_get(qapp, mock_char_settings, mock_container):
    """MfgDlg.get() 返回正确结构"""
    dlg = MfgDlg(parent=None)
    result = dlg.get()
    assert "hub" in result
    assert "char" in result
    assert "tax" in result
    assert isinstance(result["hub"], str)
    assert isinstance(result["tax"], (int, float))
    dlg.close()


# ═══════════════════════════════════════════
#  TradeDlg
# ═══════════════════════════════════════════


def test_trade_dlg_constructor(qapp, mock_char_settings, mock_container):
    """TradeDlg 基本构造不崩溃"""
    dlg = TradeDlg(parent=None)
    assert dlg.windowTitle() == "贸易评分设置"
    assert hasattr(dlg, "get")
    dlg.close()


def test_trade_dlg_with_type_id(qapp, mock_char_settings, mock_container):
    """带 type_id 的构造不崩溃"""
    dlg = TradeDlg(type_id=2001, parent=None)
    assert dlg.windowTitle() != ""
    dlg.close()


def test_trade_dlg_with_current(qapp, mock_char_settings, mock_container):
    """带 current 配置的构造正确初始化控件"""
    cfg = {"bh": "Amarr", "sh": "Dodixie", "bs": "buy", "ss": "sell", "char": "alt"}
    dlg = TradeDlg(current=cfg, parent=None)
    assert dlg.bh.currentText() == "Amarr"
    assert dlg.sh.currentText() == "Dodixie"
    dlg.close()


def test_trade_dlg_get(qapp, mock_char_settings, mock_container):
    """TradeDlg.get() 返回正确结构"""
    dlg = TradeDlg(parent=None)
    result = dlg.get()
    assert "bh" in result
    assert "sh" in result
    assert "bs" in result
    assert "ss" in result
    assert "char" in result
    assert result["bs"] in ("sell", "buy")
    dlg.close()


# ═══════════════════════════════════════════
#  ScoreW
# ═══════════════════════════════════════════


def test_scorew_constructor(qapp):
    """ScoreW 基本构造"""
    w = ScoreW(items=[], is_mfg=True, cfg={"hub": "Jita", "char": "main", "tax": 0})
    assert w._mfg is True
    assert w._cfg["hub"] == "Jita"
    # 不调用 run() 避免真实 DB 访问


def test_scorew_trade_mode(qapp):
    """ScoreW 贸易模式构造"""
    w = ScoreW(
        items=[],
        is_mfg=False,
        cfg={"bh": "Jita", "sh": "Jita", "bs": "sell", "ss": "sell", "char": "main"},
    )
    assert w._mfg is False
    assert w._cfg["bh"] == "Jita"


# ═══════════════════════════════════════════
#  主题 / 样式表
# ═══════════════════════════════════════════


def test_mfg_dlg_uses_theme_variables(qapp, mock_char_settings, mock_container):
    """MfgDlg 构造时使用 theme 变量而非硬编码颜色"""
    dlg = MfgDlg(parent=None)
    ss = dlg.styleSheet()
    assert theme.BG_DARK in ss
    assert theme.TEXT_PRIMARY in ss
    dlg.close()


def test_trade_dlg_uses_theme_variables(qapp, mock_char_settings, mock_container):
    """TradeDlg 构造时使用 theme 变量"""
    dlg = TradeDlg(parent=None)
    ss = dlg.styleSheet()
    assert theme.BG_DARK in ss
    assert theme.TEXT_PRIMARY in ss
    dlg.close()


# ═══════════════════════════════════════════
#  _fmt_tag  Helper
# ═══════════════════════════════════════════


def test_fmt_tag_s_rank():
    assert _fmt_tag(50_000_000) == "0.5亿 S"


def test_fmt_tag_a_rank():
    assert _fmt_tag(10_000_000) == "1000万 A"


def test_fmt_tag_veto():
    assert _fmt_tag(100_000_000, veto="no_depth") == "✗"
