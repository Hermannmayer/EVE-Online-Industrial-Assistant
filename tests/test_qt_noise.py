"""退出期 Qt 内建 QML 噪音抑制（`core.qt_noise`）的护栏。

回归背景：点右上角关闭按钮后，`FluentWinUI3` 样式**自己**的 qrc 文件成片报
「Value is null and could not be converted to an object」——QML 引擎拆除期样式单例
已销毁、绑定还在求值，必然拿到 null。这是 Qt 内部行为，不是我们的 QML 写错了，
但会一次刷出上百行、看起来像崩了。

抑制的**边界**必须钉死，否则就成了「把真问题也吞掉」：只在退出已开始之后、
且只对 Qt 自带 QML 生效。
"""

from __future__ import annotations

from core import qt_noise

_QT_INTERNAL = (
    "qrc:/qt-project.org/imports/QtQuick/Controls/FluentWinUI3/Button.qml:25: "
    "TypeError: Value is null and could not be converted to an object"
)
_OURS = "file:///x/ui_qml/qml/shell/Main.qml:12: TypeError: Unable to assign [undefined] to int"


def test_only_qt_internal_qml_messages_are_recognised():
    assert qt_noise.is_qt_internal_qml(_QT_INTERNAL)
    assert not qt_noise.is_qt_internal_qml(_OURS), "我们自己 QML 的告警不能被当噪音"


def test_flag_starts_off_and_is_set_by_begin_shutdown():
    """未退出时必须是关的 —— 运行期的同类告警可能是真问题，要照旧记录。"""
    original = qt_noise._shutting_down
    try:
        qt_noise._shutting_down = False
        assert qt_noise.shutting_down() is False
        qt_noise.begin_shutdown()
        assert qt_noise.shutting_down() is True
        # 可重入：closeEvent 与 aboutToQuit 两条路都会调
        qt_noise.begin_shutdown()
        assert qt_noise.shutting_down() is True
    finally:
        qt_noise._shutting_down = original


def test_the_shell_marks_shutdown_when_the_close_button_is_used(app, mock_db, monkeypatch):
    """点关闭按钮（`closeEvent`）必须把标记立起来，否则抑制根本不生效。"""
    from ui_qml.shell_window import ShellWindow

    monkeypatch.setattr(ShellWindow, "_init_price_check", lambda self: None)
    original = qt_noise._shutting_down
    try:
        qt_noise._shutting_down = False
        win = ShellWindow()
        win.show()  # 没显示过的窗口 `close()` 不派发 closeEvent（Qt 的行为）
        assert qt_noise.shutting_down() is False, "刚起来就当成在退出了"
        win._bridge.closeWindow()  # 右上角关闭按钮走的就是这条
        assert qt_noise.shutting_down() is True
        win.deleteLater()
    finally:
        qt_noise._shutting_down = original
