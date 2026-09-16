"""消息对话框 —— `QMessageBox` 的 QML 替代（批次 7.1）。

原先桥层里散着 20+ 处 `QMessageBox.information/warning/question`：它们弹的是
**原生 Qt 窗口**，样式完全不跟主题，而且是「从 QML 页面里冒出一个 Widgets 窗口」
里最扎眼的一类。本模块把它收敛成一套自绘的 QML 对话框。

静态方法刻意**照抄 `QMessageBox` 的签名与返回值形状**，所以调用方只需要把
`QMessageBox.information(parent, title, text)` 换成
`FMessageDialog.information(parent, title, text)`，其余一行不改：

    QMessageBox.information(p, "提示", "已加入制造列表")   → FMessageDialog.information(p, ...)
    QMessageBox.warning(p, "提示", "读取失败")             → FMessageDialog.warning(p, ...)
    QMessageBox.about(p, "关于", text)                     → FMessageDialog.about(p, ...)
    reply = QMessageBox.question(p, "确认", text, Yes|No)  → if FMessageDialog.question(p, ...)

`question` 是唯一形状有变的：原版返回 `StandardButton`、调用方普遍写成
`if reply != QMessageBox.StandardButton.Yes: return`，这里直接返回 `bool`，
调用方塌成一行 `if not FMessageDialog.question(...): return`。**语义不变**：
取消（Esc / 关闭按钮 /「否」）一律是 `False`。

⚠️ 三处**故意不换**：
- `Main.py` 的崩溃兜底弹窗 —— 它在 `sys.excepthook` 里，此刻 QML 引擎完全可能
  就是坏掉的那一个，把最后的用户可见兜底面换成 QML 等于让崩溃路径依赖崩溃源；
- `ui_qml/file_dialogs.py` 的原生保存框 —— 那是平台惯例且保持同步语义；
- `ui_pyside6/` 里那些 `(self, …)` 的调用点（含 `complete_guard`）—— 它们的 `self`
  在批次 7.4 之后不再是 QWidget，先改会白改两遍，归 7.3/7.4。
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["KIND_INFO", "KIND_QUESTION", "KIND_WARN", "FMessageDialog", "MessageBridge"]

_QML_FILE = "components/FMessageDialog.qml"

KIND_INFO = "info"
KIND_WARN = "warn"
KIND_QUESTION = "question"


class MessageBridge(DialogBridge):
    """一条消息对话框的后端：正文 + 种类（决定徽标颜色）+ 要不要「取消」按钮。"""

    textChanged = Signal()

    def __init__(self, title: str, text: str, kind: str, *, show_cancel: bool, default_reject: bool = False) -> None:
        super().__init__()
        self.set_title(title)
        self._text = str(text)
        self._kind = kind
        self._show_cancel = bool(show_cancel)
        self._default_reject = bool(default_reject)
        #: 只有点肯定按钮才置 True；取消 / Esc / 关闭一律保持 False
        self._answer = False

    # ── QML 读的属性 ──────────────────────────────────────────

    @Property(str, notify=textChanged)
    def text(self) -> str:
        return self._text

    @Property(str, constant=True)
    def kind(self) -> str:
        return self._kind

    @Property(bool, constant=True)
    def showCancel(self) -> bool:
        return self._show_cancel

    @Property(bool, constant=True)
    def defaultReject(self) -> bool:
        """危险确认的默认项：置真时焦点落在「取消」，回车不会误触发破坏性动作。"""
        return self._default_reject

    @Slot()
    def accept(self) -> None:
        """点「确定」/「是」。**先定格再 emit** —— 宿主收到 `accepted` 就 `exec()` 返回，
        读取方立刻取值，晚一步就是 False。"""
        self._answer = True
        self.accepted.emit()

    # ── 给 Python 调用方取值 ──────────────────────────────────

    def answer(self) -> bool:
        """是否点了肯定按钮（取消 / 关闭 / Esc 一律 False）。"""
        return self._answer


class FMessageDialog(QmlDialog):
    """QML 版消息框。静态方法对齐 `QMessageBox` 的签名。

    每个静态方法都**把对话框留在局部变量里直到读完桥**：桥是对话框的子对象
    （`QmlDialog.__init__` 里的 `bridge.setParent(self)`），对话框先一步被回收会连带
    销毁桥的 C++ 对象，读它就是一个悬空包装器 —— 见 `DialogBridge.host_widget` 里
    记的那次 `Fatal Python error: Aborted`。
    """

    def __init__(self, bridge: MessageBridge, parent: Any = None, size: tuple[int, int] = (440, 210)) -> None:
        super().__init__(_QML_FILE, bridge, parent=parent, size=size)

    @staticmethod
    def _open(bridge: MessageBridge, parent: Any, size: tuple[int, int]) -> QmlDialog:
        dlg = FMessageDialog(bridge, parent=parent, size=size)
        dlg.exec()
        return dlg

    @staticmethod
    def information(parent: Any, title: str, text: str) -> None:
        """对齐 `QMessageBox.information(parent, title, text)`。"""
        FMessageDialog._open(MessageBridge(title, text, KIND_INFO, show_cancel=False), parent, (440, 190))

    @staticmethod
    def warning(parent: Any, title: str, text: str) -> None:
        """对齐 `QMessageBox.warning(parent, title, text)`。"""
        FMessageDialog._open(MessageBridge(title, text, KIND_WARN, show_cancel=False), parent, (440, 190))

    @staticmethod
    def about(parent: Any, title: str, text: str) -> None:
        """对齐 `QMessageBox.about(parent, title, text)`（只有「确定」）。"""
        FMessageDialog._open(MessageBridge(title, text, KIND_INFO, show_cancel=False), parent, (460, 320))

    @staticmethod
    def question(parent: Any, title: str, text: str, *, default_yes: bool = True) -> bool:
        """对齐 `QMessageBox.question(parent, title, text, Yes | No)`，但返回 `bool`。

        `True` = 点了「是」；「否」/ Esc / 关闭按钮一律 `False`。

        `default_yes=False` 对应原版构造里的 `defaultButton=No`：**危险确认必须传它**。
        不传时「是」会拿到初始焦点，回车即放行 —— 而原版那种「默认落在否」的写法
        正是为了挡住「手快回车把不该放行的放行了」。调用方原来写
        `QMessageBox.question(..., Yes | No, QMessageBox.StandardButton.No)` 的，一律
        改成 `default_yes=False`。
        """
        dlg = FMessageDialog._open(
            MessageBridge(title, text, KIND_QUESTION, show_cancel=True, default_reject=not default_yes),
            parent,
            (440, 210),
        )
        return cast(MessageBridge, dlg.bridge).answer()
