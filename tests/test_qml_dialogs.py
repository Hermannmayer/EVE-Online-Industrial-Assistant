"""QML 对话框的运行时护栏（阶段 4）。

阶段 4 要把约 44 个对话框逐个迁到 QML，这里放**每个对话框都要过一遍**的两条：
  - `QmlDialog` 能加载（`ok()`）；
  - 加载 + 布局不给 Qt 刷告警（`textRole` / 位置绑定 / import 缺失这几类坑
    在页面迁移时都真实踩过）。

各对话框自己的业务契约仍写在各自的测试文件里（如
`tests/test_batch_edit_preserves_runs.py`），这里只管「宿主是否健康」。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer, QtMsgType, qInstallMessageHandler

pytestmark = pytest.mark.ui


def _spin(ms: int = 120) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _assert_loads_and_quiet(make_dialog, label: str) -> None:
    """共用的两条护栏。"""
    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            else None
        )
    )
    try:
        dialog = make_dialog()
        try:
            assert dialog.ok(), f"{label} 的 QML 没加载起来：" + "; ".join(str(e) for e in dialog._host.errors())
            dialog.resize(520, 460)
            _spin(250)
        finally:
            dialog.deleteLater()
            _spin(60)
    finally:
        qInstallMessageHandler(previous)

    assert not caught, f"{label} 产生了 QML 告警：\n" + "\n".join(dict.fromkeys(caught))


@pytest.fixture
def plan_edit_factory(qapp, monkeypatch):
    """「编辑生产计划」对话框的工厂（机库与角色列表都打桩）。"""
    from services import inventory_manager

    monkeypatch.setattr(inventory_manager, "get_hangars", lambda: [])
    monkeypatch.setattr("ui_pyside6.views.char_settings_view.services_get_character_list", lambda: ["甲"])

    from ui_qml.bridge.plan_edit_bridge import PlanEditQmlDialog

    def _make(plan: dict | None = None, **kwargs):
        return PlanEditQmlDialog(None, plan or {"product_name": "渡鸦级", "runs": 3, "parallels": 2}, **kwargs)

    return _make


def test_plan_edit_dialog_loads_without_warnings(plan_edit_factory):
    _assert_loads_and_quiet(plan_edit_factory, "编辑生产计划")


def test_plan_edit_dialog_batch_mode_loads(plan_edit_factory):
    _assert_loads_and_quiet(
        lambda: plan_edit_factory({"_selected_rows": [0, 1], "runs": 5, "parallels": 1}, batch_mode=True, row_count=2),
        "批量编辑生产计划",
    )


def test_plan_edit_labels_follow_the_activity_kind(plan_edit_factory):
    """科研行的 runs 语义不同：标签随活动类型走（与 Widgets 版逐条对齐）。"""
    dialog = plan_edit_factory({"product_name": "x", "activity": "invention"})
    try:
        bridge = dialog.bridge
        assert bridge.runsLabel == "尝试次数"
        assert bridge.parallelLabel == "并行数"
    finally:
        dialog.deleteLater()

    copy_dialog = plan_edit_factory({"product_name": "x", "activity": "copying"})
    try:
        assert copy_dialog.bridge.parallelLabel == "产出份数"
    finally:
        copy_dialog.deleteLater()


def test_plan_edit_dialog_title_comes_from_the_bridge(plan_edit_factory):
    dialog = plan_edit_factory({"product_name": "渡鸦级"})
    try:
        assert "渡鸦级" in dialog.windowTitle()
    finally:
        dialog.deleteLater()
