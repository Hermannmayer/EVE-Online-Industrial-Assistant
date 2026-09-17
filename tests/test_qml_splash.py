"""QML 启动画面的运行时护栏（阶段 7 批次 7.2）。

启动画面是**全应用第一个 QML 面**，它坏掉等于启动时什么都不显示（比对话框坏掉严重得多，
且那一刻还没装 `qInstallMessageHandler`，日志未必落地）。所以除了照 `test_qml_dialogs.py`
的范式守「加载成功 + 不给 Qt 刷 QML 告警」，这里还多守两条本批特有的：

  - **兜底真的会生效**：QML 找不到时必须退回最小窗口、而不是抛异常或一片空白；
  - **收尾链**：进度走满 → 淡出 → 回调（原 `test_splash_screen.py` 的行为契约，
    它测的是 QWidget 内部字段，随旧实现一起删掉了，行为在这里重新落一次）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtQuick import QQuickWindow

from tests.qml_click import spin as _spin
from ui_qml.splash_window import SplashScreen

pytestmark = pytest.mark.ui


def _find(root, object_name: str):
    """在 QML 对象树里按 objectName 找子项（窗口的子树挂在 contentItem 上）。"""
    stack = [root.contentItem() if isinstance(root, QQuickWindow) else root]
    while stack:
        item = stack.pop()
        if item is None:
            continue
        if item.objectName() == object_name:
            return item
        stack.extend(item.childItems())
    raise AssertionError(f"没找到 objectName={object_name!r} 的 QML 子项")


def _is_qt_internal(ctx_file: str) -> bool:
    """告警是否出自 **Qt 自带**的 QML（`qrc:/qt-project.org/...`）。

    判据与 `test_qml_dialogs.py` 的同名过滤逐字一致：FluentWinUI3 的控件文件在
    多引擎进程里会偶发地报内部告警，那测的是 Qt 的引擎生命周期，不是我们的 QML。
    """
    return ctx_file.startswith("qrc:/qt-project.org/")


def _assert_loads_and_quiet(make_splash, label: str) -> None:
    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            and not _is_qt_internal(str(ctx.file))
            else None
        )
    )
    try:
        splash = make_splash()
        try:
            # 「没退回兜底窗口」= QML 真的加载起来了。少了这条断言，QML 坏掉时
            # 兜底窗口照样能让测试通过，护栏就成了摆设。
            assert splash._fallback is None, f"{label} 退回了兜底窗口，说明 QML 没加载起来"
            assert isinstance(splash._window, QQuickWindow), f"{label} 没拿到 QQuickWindow：{splash._window!r}"
            splash.show()
            _spin(250)
        finally:
            splash.close()
            _spin(80)
    finally:
        qInstallMessageHandler(previous)

    assert not caught, f"{label} 产生了 QML 告警：\n" + "\n".join(dict.fromkeys(caught))


def test_splash_loads_without_warnings(qapp):
    _assert_loads_and_quiet(SplashScreen, "启动画面")


def test_splash_window_semantics(qapp):
    """窗口属性逐项对齐旧 QWidget 版（无边框 / 置顶 / 透明 / 固定 360x470）。"""
    from PySide6.QtCore import Qt

    splash = SplashScreen()
    try:
        window = splash._window
        assert window.flags() & Qt.WindowType.FramelessWindowHint
        assert window.flags() & Qt.WindowType.WindowStaysOnTopHint
        assert (window.width(), window.height()) == (360, 470)
        assert window.minimumWidth() == window.maximumWidth() == 360
        assert window.minimumHeight() == window.maximumHeight() == 470
        # 半透明：圆角之外要能透出去（旧版是 WA_TranslucentBackground）
        assert window.color().alpha() == 0
    finally:
        splash.close()


def test_set_stage_and_component_reach_the_bridge(qapp):
    splash = SplashScreen()
    try:
        splash.show()  # 步骤表在首帧之后才加载（见 SplashBridge.load_steps）
        for _ in range(20):
            _spin(100)
            if splash._bridge.steps:
                break
        assert len(splash._bridge.steps) == 10

        splash.set_stage("检查数据")
        assert splash._bridge.stage == "检查数据"

        splash.set_component("items", "物品数据", True)
        states = {s["key"]: s["state"] for s in splash._bridge.steps}
        assert states["items"] == "ready"
        assert "就绪" in splash._bridge.message

        splash.set_component("icons", "物品图标", False)
        states = {s["key"]: s["state"] for s in splash._bridge.steps}
        assert states["icons"] == "missing"
        assert "未就绪" in splash._bridge.message

        # 未知 key 忽略（旧版是 `_icon_rows.get(key)` 拿到 None 就跳过）
        splash.set_component("not_a_step", "未知", True)
        assert all(s["key"] != "not_a_step" for s in splash._bridge.steps)
    finally:
        splash.close()


def test_step_grid_follows_the_bridge(qapp):
    """步骤表是 show() 之后补进来的 —— QML 必须跟着重建（走 `stepsChanged`）。

    这条守的是「延时加载」这个改动本身：步骤表若没接上，界面就是一块空网格，
    而启动画面的空网格**没人会报错**，只表现为「看着像没检查」。
    """
    splash = SplashScreen()
    try:
        assert _find(splash._window, "splashStepRepeater").property("count") == 0, "show() 之前不该有步骤行"
        splash.show()
        # 首帧之后才拉步骤表（~250ms 起），轮询等它到
        for _ in range(20):
            _spin(100)
            if _find(splash._window, "splashStepRepeater").property("count") == 10:
                break
        assert _find(splash._window, "splashStepRepeater").property("count") == 10
    finally:
        splash.close()
        _spin(80)


def test_rotation_timer_runs_only_while_visible(qapp):
    """旋转弧：30ms 一拍、每拍 +5°（数值与原 QWidget 定时器逐个对齐），且只在可见时转。

    可见性那一半是必须的：首启缺数据那条路（splash → InitWizard）**不会**调 `close()`，
    窗口会一直藏着 —— 定时器不停就是空转到进程结束。
    """
    splash = SplashScreen()
    try:
        root = splash._window
        assert root.property("angle") == 0, "没显示就不该转"
        splash.show()
        _spin(150)
        first = root.property("angle")
        _spin(150)
        second = root.property("angle")
        assert first != 0, "显示之后旋转该开始"
        assert second != first, f"旋转没在走：{first} → {second}"
        assert second % 5 == 0, "每拍该正好 +5°"
    finally:
        splash.close()


def test_complete_fills_progress_then_fades_and_calls_back(qapp):
    """检查完成后：进度匀速走满 100% → 淡出 → 回调，且窗口已不可见。"""
    splash = SplashScreen(min_ms=0)
    try:
        splash.show()
        splash._shown_at = 0.0
        done: list = []
        splash.complete(lambda: done.append(1))

        for _ in range(120):  # 最多 12s（负载下固定 qWait 不够，旧用例同款轮询）
            _spin(100)
            if done:
                break

        assert splash._progress == 100
        assert done == [1]
        assert not splash._window.isVisible()
    finally:
        splash.close()


def test_broken_qml_falls_back_instead_of_showing_nothing(qapp, monkeypatch):
    """QML 坏掉时**必须**退回一个看得见的窗口，而不是抛异常或一片空白。

    这条路径只在启动最早的那一刻生效，平时怎么点都碰不到 —— 所以单独守一次。
    """
    import ui_qml.splash_window as sw

    monkeypatch.setattr(sw, "_SPLASH_QML", "shell/绝对不存在的启动画面.qml")

    splash = sw.SplashScreen()
    try:
        assert splash._fallback is not None, "QML 加载失败却没有兜底窗口"
        assert splash._bridge is None
        assert splash._window is splash._fallback

        # 兜底路径也要能走完同一条状态链（Main.py 不管拿到哪种 splash 都照常连信号）
        splash.set_stage("检查数据")
        splash.set_component("items", "物品数据", True)
        assert splash._fallback._stage == "检查数据"
        assert "就绪" in splash._fallback._message
    finally:
        splash.close()
