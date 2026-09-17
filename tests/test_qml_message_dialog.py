"""`FMessageDialog` —— `QMessageBox` 的 QML 替代（批次 7.1）。

这批把桥层里 20+ 处 `QMessageBox` 换成自绘 QML 对话框，**调用方的形状几乎不变**
（静态方法照抄 `QMessageBox` 的签名），所以最容易出错的不是渲染，而是两条语义：

1. **`question()` 的返回值**：原版返回 `StandardButton`、调用方写
   `if reply != QMessageBox.StandardButton.Yes: return`；新版返回 `bool`，
   调用方写 `if not FMessageDialog.question(...): return`。**取消必须是 False** ——
   弄反了就是「点关闭反而执行了删除」。这里把三条路径（确定 / 取消 / 拒绝）都钉死。
2. **加载不带告警**：与其余对话框同一条护栏（缺 import / 绑错属性只在运行时吐一条）。

另外守一条本模块特有的：**桥必须在对话框存活期间读完**。桥是对话框的子对象
（`QmlDialog.__init__` 里的 `bridge.setParent(self)`），对话框先被回收会连带销毁桥的
C++ 对象，读它就是一个悬空包装器 —— `dialog_host.DialogBridge.host_widget` 里记过
那次 `Fatal Python error: Aborted`。`FMessageDialog` 的静态方法为此把对话框留在
局部变量里直到取值完成，这里用「读桥时对话框还活着」把它钉住。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QDialog

from tests.qml_click import spin as _spin
from ui_qml.bridge import message_dialog as md
from ui_qml.bridge.message_dialog import KIND_INFO, KIND_QUESTION, KIND_WARN, FMessageDialog, MessageBridge

pytestmark = pytest.mark.ui


def _is_qt_internal(ctx_file: str) -> bool:
    """Qt 自带样式的告警不算（理由见 `tests/test_qml_dialogs.py` 同名函数）。"""
    return ctx_file.startswith("qrc:/qt-project.org/")


def _loads_and_quiet(make_dialog, label: str) -> None:
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
        dialog = make_dialog()
        try:
            assert dialog.ok(), f"{label} 的 QML 没加载起来：" + "; ".join(str(e) for e in dialog._host.errors())
            dialog.resize(440, 210)
            _spin(250)
        finally:
            dialog.deleteLater()
            _spin(60)
    finally:
        qInstallMessageHandler(previous)

    assert not caught, f"{label} 产生了 QML 告警：\n" + "\n".join(dict.fromkeys(caught))


# ── 1. 三种形态都能干净加载 ──────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "show_cancel"),
    [(KIND_INFO, False), (KIND_WARN, False), (KIND_QUESTION, True)],
    ids=["info", "warn", "question"],
)
def test_each_kind_loads_without_qml_warnings(qapp, kind, show_cancel):
    _loads_and_quiet(
        lambda: FMessageDialog(MessageBridge("标题", "正文\n第二行", kind, show_cancel=show_cancel)),
        f"消息框（{kind}）",
    )


# ── 2. 桥的取值语义 ──────────────────────────────────────────


def test_answer_is_false_until_accepted():
    """初始与取消都必须是 `False` —— 这是「点关闭却执行了危险操作」的唯一防线。"""
    bridge = MessageBridge("确认删除", "确定要删除吗？", KIND_QUESTION, show_cancel=True)
    assert bridge.answer() is False

    bridge.reject()
    assert bridge.answer() is False, "取消之后仍是 False"

    bridge.accept()
    assert bridge.answer() is True


def test_bridge_exposes_what_qml_reads(qapp):
    bridge = MessageBridge("标题", "正文", KIND_WARN, show_cancel=False)
    assert bridge.kind == KIND_WARN
    assert bridge.showCancel is False
    assert bridge.text == "正文"
    assert bridge.title == "标题"


# ── 3. `question()` 的返回：三条路径都不能弄反 ─────────────────


class _AutoAnswer(FMessageDialog):
    """把 `exec()` 换成「按预设答复点一下」，其余全走真链路。

    这比打桩 `FMessageDialog.question` 有牙：`_open` 里的构造 / `exec()` / 取桥
    都是真的，只有「人点哪个按钮」被替换掉。
    """

    #: True = 点「是」，False = 点「否」
    _answer: bool = True

    def exec(self) -> int:
        (self.bridge.accept if self._answer else self.bridge.reject)()
        return int(QDialog.DialogCode.Accepted if self._answer else QDialog.DialogCode.Rejected)


def _with_auto_answer(monkeypatch, answer: bool) -> None:
    monkeypatch.setattr(md, "FMessageDialog", type("_A", (_AutoAnswer,), {"_answer": answer}))


def test_question_true_when_accepted(qapp, monkeypatch):
    _with_auto_answer(monkeypatch, True)
    assert FMessageDialog.question(None, "确认", "继续吗？") is True


def test_question_false_when_rejected(qapp, monkeypatch):
    _with_auto_answer(monkeypatch, False)
    assert FMessageDialog.question(None, "确认", "继续吗？") is False


def test_question_keeps_the_dialog_alive_while_reading_the_bridge(qapp, monkeypatch):
    """读桥时对话框必须还在 —— 桥是它的子对象，对话框先走就是悬空包装器。

    形状是这样踩出来的：第一版把 `_open` 写成「返回桥」、对话框留在 `_open` 的局部变量里，
    调用方拿到桥时对话框已经出栈。桥的 C++ 父对象一没，桥就是悬空包装器
    （`dialog_host.DialogBridge.host_widget` 记过那次 `Fatal Python error: Aborted`）。

    这里让桥在 `answer()` 里检查自己的父对象：`parent()` 为空或已销毁就直接断言失败。
    """

    class _ParentProbe(MessageBridge):
        def answer(self) -> bool:
            parent = self.parent()
            assert parent is not None, "读桥时对话框已经不在了（桥是它的子对象）"
            # C++ 对象已销毁时，任何方法调用都会抛 RuntimeError: Internal C++ object already deleted
            parent.objectName()
            return super().answer()

    monkeypatch.setattr(md, "MessageBridge", _ParentProbe)
    _with_auto_answer(monkeypatch, True)

    assert md.FMessageDialog.question(None, "确认", "继续吗？") is True


def test_parent_probe_would_actually_fire(qapp):
    """上一条用的探测器必须**真的会响** —— 否则它只是一条恒真的断言。

    对话框销毁后，桥作为它的子对象一并没了；此刻读桥的父对象会抛
    `RuntimeError: Internal C++ object already deleted`。这正是探测器要抓的形态。
    """
    bridge = MessageBridge("标题", "正文", KIND_INFO, show_cancel=False)
    dlg = FMessageDialog(bridge)
    dlg.deleteLater()
    _spin(80)

    with pytest.raises(RuntimeError):
        dlg.windowTitle()
    with pytest.raises(RuntimeError):
        _ = bridge.parent()


def test_question_can_default_to_no(qapp, monkeypatch):
    """`default_yes=False` 必须落到桥的 `defaultReject` 上。

    原版危险确认写 `QMessageBox.question(..., defaultButton=No)` —— 换成 QML 版后，
    「默认项」不再是构造参数，而是**焦点给谁**，最容易在搬迁时静默丢掉。
    桥上是 `defaultReject`，QML 用 `focus:` 消费它。
    """
    seen: list[bool] = []

    class _Capture(_AutoAnswer):
        def __init__(self, bridge, parent=None, size=(440, 210)):
            seen.append(bridge.defaultReject)
            super().__init__(bridge, parent=parent, size=size)

    monkeypatch.setattr(md, "FMessageDialog", _Capture)
    md.FMessageDialog.question(None, "确认", "继续吗？", default_yes=False)
    assert seen == [True], "危险确认必须把默认项放在「否」上"

    seen.clear()
    md.FMessageDialog.question(None, "确认", "继续吗？")
    assert seen == [False], "不带参数时维持原样（默认项在「是」）"


# ── 4. 签名与 `QMessageBox` 同形（调用点才能一行替换）──────────


@pytest.mark.parametrize("name", ["information", "warning", "about", "question"])
def test_static_methods_take_parent_title_text_positionally(name):
    """前三个位置参数必须是 `(parent, title, text)`，与 `QMessageBox` 一致。"""
    import inspect

    params = list(inspect.signature(getattr(FMessageDialog, name)).parameters)
    assert params[:3] == ["parent", "title", "text"], f"{name} 的位置参数形状与 QMessageBox 不一致"
