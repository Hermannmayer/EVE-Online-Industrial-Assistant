"""QML 对话框宿主 —— 把 QML 页面当 `QDialog` 用。

阶段 4 要把 44 个对话框逐步迁到 QML，但**调用方全是既有 Python**，形态是：

    dlg = XxxDialog(self, data)
    if dlg.exec():
        result = dlg.get_xxx()

所以不能只写一个 QML `Dialog`（那只在 QML 树里有效）。这里用
`QDialog` 包一层 `PageHost`：窗口行为（模态、居中、焦点、Esc 关闭）交给 QDialog，
内容交给 QML。调用方的 `exec()` / `result()` 一行都不用改。

QML 侧通过桥发 `accepted` / `rejected` 信号（见 `DialogBridge`），宿主把它们接到
`QDialog.accept/reject` 上 —— 迁移期的统一契约。

**属主窗口（transient parent）**：外壳与工具窗是 `QWindow`（`QQuickWindow`），
`QDialog` 的 parent 参数只收 `QWidget`，于是这里过去一律降级成 `None` —— 对话框就成了
**无主**窗口。后果是「父窗置顶时，无主对话框排在普通层被它盖住，而对话框是应用级
模态、父窗又点不了」——互相锁死。现在统一把属主挂到 `windowHandle().setTransientParent()`：
有 QWidget 父就用它，没有就退到「当前活动窗口」这个 `QWindow`（外壳/工具窗都在其中）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from ui_qml.host import PageHost

__all__ = ["DialogBridge", "QmlDialog"]


class DialogBridge(QObject):
    """对话框桥的公共部分：标题 + 接受/取消。

    各对话框自己的桥继承它，再加自己的字段与校验。
    """

    accepted = Signal()
    rejected = Signal()
    # 带上标题本身，宿主才能直接接到 setWindowTitle 上
    titleChanged = Signal(str)
    errorChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._title = ""
        self._error_text = ""

    title = Property(str, lambda self: self._title, notify=titleChanged)
    #: 给 QML 显示的校验提示（空串 = 不显示）
    error = Property(str, lambda self: self._error_text, notify=errorChanged)

    def title_text(self) -> str:
        """给 Python 侧读标题的普通方法。

        直接读 `self.title` 在 mypy 眼里是 `Property` 描述符而不是 str
        （PySide6 的桩没把描述符协议建模出来），故另给一个直取字段的入口。
        """
        return self._title

    def set_title(self, text: str) -> None:
        self._title = str(text)
        self.titleChanged.emit(self._title)

    def set_error(self, text: str) -> None:
        self._error_text = str(text)
        self.errorChanged.emit()

    @Slot()
    def accept(self) -> None:
        """QML 侧「确定」。需要校验时在子类里覆写 —— 校验不过就别 emit。"""
        self.accepted.emit()

    @Slot()
    def reject(self) -> None:
        self.rejected.emit()

    def host_widget(self) -> QWidget | None:
        """宿主对话框 —— 给 `QMessageBox` / 二级弹窗当 parent 用。

        靠 Qt 的父子关系拿（见 `QmlDialog.__init__` 里的 `setParent`），**不自己存引用**：
        自己存会形成「对话框 → 桥 → 对话框」的环，GC 收环的时机不受控，
        可能先没掉 C++ 窗口、留下一个悬空包装器 —— 拿去当 `QMessageBox` 的 parent
        就是一次崩溃（实测整轮 UI 测试跑到中途偶发 `Fatal Python error: Aborted`）。

        返回 `None` 是**合法且安全**的：两个调用点都接受 None（只是失去居中）。
        """
        parent = self.parent()
        return parent if isinstance(parent, QWidget) else None


class QmlDialog(QDialog):
    """承载单个 QML 对话框页面的 QDialog。"""

    def __init__(
        self,
        qml_file: str,
        bridge: DialogBridge,
        *,
        parent: QWidget | None = None,
        size: tuple[int, int] | None = None,
    ) -> None:
        #: 只认 QWidget 父：`QDialog` 的 parent 参数收不下裸 `QObject`/`QWindow`
        #: （本仓 6.1 踩过一次 —— `QMenu(self)` / `QMessageBox.about(self, ...)` 把
        #: `QQuickView` 当 QWidget 父，运行时直接抛类型错）。批次 7.4 起工业页那串
        #: 控制器的基类变成 `QObject`，`self` 传进来不再是 QWidget，所以在这里统一
        #: 收敛成 `None`。
        #
        #: 但**收敛成 None 会丢掉属主**：外壳/工具窗是 QWindow，对话框于是成了无主窗口
        #: （父窗置顶时被盖住 + 应用级模态锁死父窗 = 互相锁死）。所以下面再补一次
        #: `setTransientParent`，把属主挂到 QWidget 父窗或「当前活动 QWindow」上。
        widget_parent = parent if isinstance(parent, QWidget) else None
        super().__init__(widget_parent)
        self._bridge = bridge
        #: 桥挂到宿主对话框名下：桥的寿命不超过对话框，且桥里 `self.parent()` 就是那个窗口。
        #: 见 `DialogBridge.host_widget` 里对「自己存引用会悬空」的说明。
        bridge.setParent(self)
        self._bridge.accepted.connect(self.accept)
        self._bridge.rejected.connect(self.reject)
        self._bridge.titleChanged.connect(self.setWindowTitle)
        if bridge.title_text():
            self.setWindowTitle(bridge.title_text())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._host = PageHost(qml_file, context={"bridge": bridge}, parent=self)
        layout.addWidget(self._host)

        self._bind_transient_parent(widget_parent)

        # 销毁也要收尾：调用方（测试里尤其常见）会直接 `dlg.deleteLater()`，那条路径
        # 既不经过 `done()` 也不经过 `closeEvent`，桥的后台线程就没人停 —— 而 `QThread`
        # 在运行中被析构时 Qt 直接中止进程，或者把队列信号投给已销毁的 QML 对象
        # （access violation：表现成「另一个无关测试的 fixture 拆除处突然段错误」，
        # `-m ui` 全量档偶发崩在 storage 页拆除，根子其实在这里）。
        #
        # 两个坑，都实测过：
        # 1. 必须等 `destroyed` —— Qt 在 `~QObject` 里**先**发它、**后**删子对象，
        #    所以这一刻桥还活着、停得掉；等桥被删就晚了。
        # 2. 必须用 **lambda / 独立函数**连接：PySide6 里连到**自己** `destroyed` 上的
        #    绑定方法**不会被调用**（同一个对象正在被销毁）。
        # 只对真的实现了 `stop()` 的桥接（页面桥没有，也无需）。
        _stop = getattr(bridge, "stop", None)
        if callable(_stop):
            self.destroyed.connect(lambda *_: _stop())

        if size is not None:
            self.setMinimumSize(*size)
            self.resize(*size)

    @property
    def bridge(self) -> Any:
        return self._bridge

    # ── 属主窗口（层级） ─────────────────────────────────────

    def _bind_transient_parent(self, widget_parent: QWidget | None) -> None:
        """把本对话框挂到属主窗口下，让它在父窗之上、并阻止父窗抢前置。

        没有这一步时对话框是**无主**窗口：父窗（外壳 / 两个工具窗）一旦置顶，
        无主对话框排在普通层会被它盖住，而对话框是应用级模态 —— 父窗也点不了，
        两个窗口互相锁死。

        取属主的顺序：QWidget 父窗的 `QWindow` → 当前聚焦窗口（外壳与两个工具窗
        都是 `QWindow`，且在 `QGuiApplication.focusWindow()` 里）。都没有就不挂，
        退回原行为（如无父窗的测试场景）。

        注意不能改用 `QApplication.activeWindow()` —— 它返回 `QWidget`，而本仓的
        外壳/工具窗都是 `QWindow`，拿不到。
        """
        own_handle = self.windowHandle()
        if own_handle is None:
            return
        owner: QWindow | None = widget_parent.windowHandle() if widget_parent is not None else None
        if owner is None:
            owner = QGuiApplication.focusWindow()
        if owner is None or owner is own_handle:
            return
        #: 留引用防 Python 包装器先析构：`setTransientParent` 只记 HWND，Qt 不接管所有权，
        #: 父窗是 Python 侧临时对象时（工具窗的 QWindow 由控制器持有，但别赌）丢了引用
        #: 就是悬空指针。
        self._transient_parent_window = owner
        own_handle.setTransientParent(owner)
        #: 父窗置顶（TOPMOST）时，属主关系**不会**自动把子窗抬到同层 —— 子窗仍会排在
        #: 普通层、被置顶父窗盖住。显式跟随一次，子窗才与父窗同层。
        self._match_owner_always_on_top(owner)

    def _match_owner_always_on_top(self, owner: QWindow) -> None:
        """父窗是 TOPMOST 时给对话框也加 `WindowStaysOnTopHint`，保证子窗排在父窗之上。

        只在「父窗用 flags 置顶」时走到（外壳/工具窗在 Windows 上走 `SetWindowPos
        HWND_TOPMOST`，flags 里没有这个 hint），故不覆盖 Win32 主路径 —— 那条路由
        `setTransientParent` 的属主关系 + 对话框自身 `exec()` 的置前负责。
        """
        if not (owner.flags() & Qt.WindowType.WindowStaysOnTopHint):
            return
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def ok(self) -> bool:
        """QML 是否加载成功（调用方据此决定要不要回退到 Widgets 版）。"""
        return self._host.ok()

    # ── 关窗收尾 ─────────────────────────────────────────────

    def _stop_bridge(self) -> None:
        """关窗前给桥一个收尾机会（桥没实现 `stop()` 就什么也不做）。

        桥里若有还在跑的后台线程，**必须**在这里停掉并等它结束：
        `QThread` 在运行中被析构时 Qt 直接 `abort()` —— 实测进程静默死掉、
        退出码 127、连一行日志都没有（`ui_snapshot.py --dialog contract_detail`
        就是这么挂的，当时物品加载线程还没跑完）。

        放在基类而不是各对话框各写一遍：`done()` 覆盖确定/取消/Esc，
        `closeEvent` 覆盖点窗口 X，两个入口都得走。
        """
        stop = getattr(self._bridge, "stop", None)
        if callable(stop):
            stop()

    def done(self, result: int) -> None:
        self._stop_bridge()
        super().done(result)

    def closeEvent(self, event: Any) -> None:
        self._stop_bridge()
        super().closeEvent(event)
