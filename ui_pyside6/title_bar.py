"""无边框窗口标题栏 + 边缘缩放事件过滤器。

标题栏是独立顶部行（QToolBar）：应用标题（醒目）→ 拉伸 → 置顶 → 最小化/最大化/关闭。
整个标题行空区可拖动（startSystemMove），双击最大化。窗口控制按钮小巧精致（hover 微反馈，
关闭钮 hover 红色），置顶按钮有 checked 视觉态。
"""

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QLabel,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)

import ui_pyside6.icons as icons
import ui_pyside6.theme as theme

_ICON_SIZE = 14


class TitleBar(QToolBar):
    """无边框窗口顶部标题行"""

    def __init__(self, title: str, parent=None):
        super().__init__("标题栏", parent)
        self.setObjectName("title_bar")
        self.setMovable(False)
        self.setFloatable(False)
        self.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self._maximized = False
        self._drag_offset = None

        # 应用标题（醒目，左侧）
        self._title_label = QLabel(title)
        self._title_label.setObjectName("title_label")
        self.addWidget(self._title_label)

        # 拉伸占位：把窗口控制推到最右上角
        spacer = QWidget()
        spacer.setObjectName("title_spacer")
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)

        # 置顶（可勾选，checked 态由 QSS 提供）
        self._pin_btn = QToolButton()
        self._pin_btn.setObjectName("title_btn")
        self._pin_btn.setCheckable(True)
        self._pin_btn.setToolTip("窗口置顶（点击切换开/关）")
        icons.set_button_icon(self._pin_btn, "pin", theme.TEXT_PRIMARY, size=_ICON_SIZE)
        self.addWidget(self._pin_btn)

        # 窗口控制（右上角，小号精致按钮）
        self._min_btn = QToolButton()
        self._min_btn.setObjectName("title_btn")
        self._min_btn.setToolTip("最小化")
        icons.set_button_icon(self._min_btn, "minus", theme.TEXT_PRIMARY, size=_ICON_SIZE)
        self._min_btn.clicked.connect(self._on_minimize)
        self.addWidget(self._min_btn)

        self._max_btn = QToolButton()
        self._max_btn.setObjectName("title_btn")
        self._max_btn.setToolTip("最大化")
        icons.set_button_icon(self._max_btn, "maximize", theme.TEXT_PRIMARY, size=_ICON_SIZE)
        self._max_btn.clicked.connect(self._on_maximize)
        self.addWidget(self._max_btn)

        self._close_btn = QToolButton()
        self._close_btn.setObjectName("title_close_btn")
        self._close_btn.setToolTip("关闭")
        icons.set_button_icon(self._close_btn, "close", theme.TEXT_PRIMARY, size=_ICON_SIZE)
        self._close_btn.clicked.connect(self._on_close)
        self.addWidget(self._close_btn)

    # ── 窗口操作 ──

    def _window(self) -> QWidget | None:
        return self.window()

    def _on_minimize(self):
        w = self._window()
        if w is not None:
            w.showMinimized()

    def _on_maximize(self):
        w = self._window()
        if w is None:
            return
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()

    def _on_close(self):
        w = self._window()
        if w is not None:
            w.close()

    def set_maximized(self, maximized: bool):
        """随窗口最大化状态切换「最大化/还原」图标"""
        self._maximized = maximized
        self._refresh_icon(self._max_btn, "restore" if maximized else "maximize")
        self._max_btn.setToolTip("还原" if maximized else "最大化")

    def refresh_icons(self):
        """主题切换后重刷按钮图标色（TEXT_PRIMARY 保证各主题下可见）"""
        pin_color = theme.TEXT_ON_PRIMARY if self._pin_btn.isChecked() else theme.TEXT_PRIMARY
        self._refresh_icon(self._pin_btn, "pin", pin_color)
        self._refresh_icon(self._min_btn, "minus")
        self._refresh_icon(self._max_btn, "restore" if getattr(self, "_maximized", False) else "maximize")
        self._refresh_icon(self._close_btn, "close")

    def _refresh_icon(self, btn, key, color=None):
        icons.set_button_icon(btn, key, color or theme.TEXT_PRIMARY, size=_ICON_SIZE)

    # ── 拖拽（标题行空区；startSystemMove 失败则手动拖动兜底） ──

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            # 兜底：手动拖动（记录按下偏移）
            win = self.window()
            self._drag_offset = event.globalPosition().toPoint() - win.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        offset = getattr(self, "_drag_offset", None)
        if offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.window().move(event.globalPosition().toPoint() - offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_maximize()
            return
        super().mouseDoubleClickEvent(event)


class FramelessResizeFilter(QObject):
    """无边框窗口边缘缩放：监听全局鼠标，靠近边缘显示缩放光标，按下时 startSystemResize。

    交互控件（按钮/输入框）优先于边缘缩放——标题栏右上角按钮仍可点击。
    """

    EDGE = 6

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._enable_tracking(window)

    @staticmethod
    def _enable_tracking(widget: QWidget):
        widget.setMouseTracking(True)
        for child in widget.findChildren(QWidget):
            child.setMouseTracking(True)

    def _edge_at(self, event) -> Qt.Edge | None:
        win = self._window
        if win.isMaximized() or win.isFullScreen():
            return None
        pt = win.mapFromGlobal(event.globalPosition().toPoint())
        w, h = win.width(), win.height()
        m = self.EDGE
        value = 0
        if pt.y() <= m:
            value |= Qt.Edge.TopEdge.value
        if pt.y() >= h - m:
            value |= Qt.Edge.BottomEdge.value
        if pt.x() <= m:
            value |= Qt.Edge.LeftEdge.value
        if pt.x() >= w - m:
            value |= Qt.Edge.RightEdge.value
        # 角 = 边组合（PySide6 Qt.Edge 无独立角成员）
        return Qt.Edge(value) if value else None

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.MouseMove:
            self._update_cursor(event)
        elif et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            # 交互控件（按钮/输入框）优先：边缘缩放在空白处生效
            if isinstance(obj, QAbstractButton):
                return False
            edge = self._edge_at(event)
            if edge is not None:
                handle = self._window.windowHandle()
                if handle is not None and handle.startSystemResize(edge):
                    return True
        return False

    def _update_cursor(self, event):
        edge = self._edge_at(event)
        if edge is None:
            self._window.unsetCursor()
            return
        tl = Qt.Edge.TopEdge | Qt.Edge.LeftEdge
        br = Qt.Edge.BottomEdge | Qt.Edge.RightEdge
        tr = Qt.Edge.TopEdge | Qt.Edge.RightEdge
        bl = Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
        if edge in (tl, br):
            shape = Qt.CursorShape.SizeFDiagCursor
        elif edge in (tr, bl):
            shape = Qt.CursorShape.SizeBDiagCursor
        elif edge == Qt.Edge.LeftEdge or edge == Qt.Edge.RightEdge:
            shape = Qt.CursorShape.SizeHorCursor
        elif edge == Qt.Edge.TopEdge or edge == Qt.Edge.BottomEdge:
            shape = Qt.CursorShape.SizeVerCursor
        else:
            shape = None
        if shape is not None:
            if self._window.cursor().shape() != shape:
                self._window.setCursor(shape)
        else:
            self._window.unsetCursor()
