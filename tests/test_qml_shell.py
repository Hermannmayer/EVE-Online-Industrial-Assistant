"""QML 外壳（阶段 5 / 批次 6.1）的护栏。

这一批把主窗口从 `QMainWindow` 换成 `QQuickView`，**页面宿主必须跟着从
`QQuickWidget` 变成 `QQuickItem`** —— `QQuickWidget` 是 QWidget，Qt 明确不支持
嵌进 `QQuickWindow`。这条不变量的失败方式很隐蔽：QML 照旧能加载、页面照旧能建，
只是**永远不显示**（或整块空白）。所以单列一条断言钉死「页面不是 QWidget」。

其余几条护栏对着外壳对页面承诺的接口：切页只显示一个、状态栏/进度条能到 QML、
状态存取能把当前页带过去。
"""

from __future__ import annotations

import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QWidget

from ui_qml.constants import NAV_TREE
from ui_qml.shell_window import ShellWindow

pytestmark = pytest.mark.ui

#: 导航树里的真页面 key（分组标题不算）
_KEYS = [k for k, _label, _icon in NAV_TREE if k != "__section__"]


@pytest.fixture(autouse=True)
def _no_price_network(monkeypatch):
    """掐掉启动即发的价格检查：它是真 QThread + 真 ESI，测试里不该跑。"""
    monkeypatch.setattr(ShellWindow, "_init_price_check", lambda self: None)


@pytest.fixture
def shell(app, mock_db, monkeypatch):
    """造一个 QML 外壳。

    `mock_db` 之外还要给仓库管理补一层 mock：`InventoryBridge` 构造时会把
    Widgets 版仓库页也拉起来（它调 `init_db()`），没有这层就整页建不出来
    —— 与 `conftest.inventory_page` 同一个理由。
    """
    from unittest.mock import MagicMock

    cursor = MagicMock()
    cursor.fetchone.return_value = (0,)
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.execute.return_value = cursor
    conn.executescript = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    mgr = MagicMock()
    mgr.connect.return_value = cm
    monkeypatch.setattr("services.inventory_manager._default_db", mgr)

    win = ShellWindow()
    yield win
    win.close()
    win.deleteLater()


# ── 1. 页面宿主形态（本批次的核心不变量）────────────────────


def test_every_page_is_a_qml_item_not_a_widget(shell):
    """页面必须是 `QQuickItem` —— 是 `QWidget` 就装不进 `QQuickWindow`。"""
    assert sorted(shell._pages) == sorted(_KEYS), "有页面没装载"
    for key, page in shell._pages.items():
        assert isinstance(page.item, QQuickItem), f"{key} 的页面不是 QQuickItem"
        assert not isinstance(page.item, QWidget), f"{key} 的页面是 QWidget，装不进 QQuickWindow"
        assert page.item.parentItem() is shell._content_area, f"{key} 的页面没挂进内容区"


def test_content_area_fills_the_shell_beside_the_nav(shell, app):
    """内容区在 QML 根项里占满「除导航（160）以外」的宽度。

    基准取**根项**而不是 QWindow：`resize()` 改的是 QWindow，根项的跟随要等一次
    真正的 resize 事件（offscreen 下没 show 过就等不到）。这里要验的是 QML 布局
    本身对不对，拿根项当基准就够了。
    """
    root = shell.rootObject()
    app.processEvents()
    assert shell._content_area.width() == pytest.approx(root.width() - 160, abs=2)
    assert shell._content_area.height() > 0
    assert shell._content_area.x() == pytest.approx(160, abs=1)


# ── 2. 切页 ────────────────────────────────────────────────


def test_exactly_one_page_is_visible_and_navigation_switches_it(shell):
    visible = [k for k, p in shell._pages.items() if p.item.isVisible()]
    assert len(visible) == 1, f"可见页面应当恰好 1 个，实际 {visible}"

    target = next(k for k in _KEYS if k != shell.current_page_key())
    assert shell.navigate_to(target) is True
    assert shell.current_page_key() == target
    visible = [k for k, p in shell._pages.items() if p.item.isVisible()]
    assert visible == [target], f"切页后可见的应该是 {target}，实际 {visible}"


def test_navigating_to_an_unknown_key_is_a_noop(shell):
    before = shell.current_page_key()
    assert shell.navigate_to("不存在的页") is False
    assert shell.current_page_key() == before


# ── 3. 外壳给页面的接口（ShellBridge 按鸭子类型调）──────────


def test_status_and_progress_reach_the_bridge(shell):
    bridge = shell._bridge

    shell.set_status("正在读取")
    assert bridge.statusText == "正在读取"

    shell.show_progress("处理中", 20)
    assert bridge.progressVisible is True
    assert bridge.progressMaximum == 20

    shell.update_progress(7, "第七个")
    assert (bridge.progressValue, bridge.statusText) == (7, "第七个")

    shell.hide_progress("就绪")
    assert bridge.progressVisible is False
    assert bridge.statusText == "就绪"


def test_status_label_shim_keeps_the_settings_bridges_working(shell):
    """设置族桥按 Widgets 版的形状调 `mw._status_label.setText(...)`。

    外壳没有 QLabel，靠一个薄壳转发 —— 少了它，保存设置后状态栏不会有反馈
    （而且是静默的：`getattr(..., None)` 拿不到就跳过）。
    """
    shell._status_label.setText("设置已保存")
    assert shell._bridge.statusText == "设置已保存"


def test_region_and_auto_update_text_follow_the_state(shell):
    bridge = shell._bridge
    shell._update_regions = ["Jita", "Amarr"]
    assert bridge.regionText == "区域: Jita, Amarr"

    shell._update_regions = ["Jita", "Amarr", "Rens", "Dodixie"]
    assert bridge.regionText == "区域: Jita, Amarr +2"

    shell._auto_update_enabled = True
    shell._update_interval_minutes = 45
    assert bridge.autoUpdateText == "每 45 分钟"
    shell._auto_update_enabled = False
    assert bridge.autoUpdateText == "自动更新: 关"


# ── 4. 状态存取 ────────────────────────────────────────────


def test_save_and_restore_state_round_trips_the_current_page(shell):
    keys = list(_KEYS)
    shell.navigate_to(keys[-1])
    state = shell.save_state()
    assert state["current_page"] == keys[-1]

    shell.navigate_to(keys[0])
    shell.restore_state(state)
    assert shell.current_page_key() == keys[-1]


# ── 5. QML 必须干净加载 ────────────────────────────────────


def test_shell_qml_loads_without_warnings(app, mock_db, monkeypatch):
    """外壳 QML 不许有加载告警（缺 import / 绑错属性这类问题只在运行时吐一条）。"""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    monkeypatch.setattr(ShellWindow, "_init_price_check", lambda self: None)
    messages: list[str] = []

    def _handler(msg_type, context, message):
        if msg_type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            messages.append(message)

    previous = qInstallMessageHandler(_handler)
    try:
        win = ShellWindow()
        win.close()
        win.deleteLater()
    finally:
        qInstallMessageHandler(previous)

    qml_issues = [m for m in messages if ".qml" in m or "QML" in m]
    assert not qml_issues, "外壳 QML 加载有告警：\n" + "\n".join(qml_issues)


# ── 6. 回退开关 ────────────────────────────────────────────


def test_widgets_shell_remains_available_as_a_rollback(monkeypatch):
    """`EVE_WIDGETS_SHELL=1` 必须还能造出 Widgets 外壳 —— 这是过渡期的安全带。"""
    import Main

    sentinel_new = object()
    sentinel_old = object()
    monkeypatch.setattr("ui_qml.shell_window.ShellWindow", lambda **kw: sentinel_new)
    monkeypatch.setattr("ui_pyside6.main_window.MainWindow", lambda **kw: sentinel_old)

    monkeypatch.delenv("EVE_WIDGETS_SHELL", raising=False)
    assert Main._make_shell(False) is sentinel_new

    monkeypatch.setenv("EVE_WIDGETS_SHELL", "1")
    assert Main._make_shell(False) is sentinel_old
