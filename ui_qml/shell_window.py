"""QML 外壳窗口（阶段 5 批次 6.1）—— 顶替 `ui_pyside6/main_window.MainWindow`。

**为什么必须是 `QQuickWindow`（这里是它的子类 `QQuickView`）**：外壳一旦由 QML 绘制，
页面就不能再是 `QQuickWidget`（它是 QWidget，Qt 明确不支持嵌进 `QQuickWindow`），
所以页面改成 `Item`（见 `ui_qml/registry.build_qml_page`）——这一步是**连带的**，
不是可选的。

`QQuickView` 而不是裸 `QQuickWindow`：要 `setSource()` 加载 `shell/Main.qml`。
`nativeEvent` 是 `QWindow` 的虚函数，子类照样能重写，无边框窗口那套（`WM_NCCALCSIZE` /
`WM_NCHITTEST` / `WM_GETMINMAXINFO`）逐行照搬原实现，行为不变。

**启动链路的约束（见 `Main.py`）一条都不能破**：单实例锁、`QQuickStyle` 先于任何 QML、
splash → 主窗时序、`aboutToQuit` 的两条清理、以及「用 QObject 绑定槽接收 QThread 信号」
（普通函数会被 DirectConnection 投到工作线程，在那里造窗口会死锁）。
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from PySide6.QtCore import Property, QObject, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core.constants import TRADE_HUBS
from core.container import get_container
from core.logger import log
from core.paths import ensure_dirs_exist, window_geometry_file
from ui_qml.bridge import CONTEXT_NAME, theme_singleton
from ui_qml.constants import NAV_TREE
from ui_qml.host import QML_ROOT
from ui_qml.icon_provider import PROVIDER_ID, PhosphorIconProvider
from ui_qml.icons import ICON_MAP
from ui_qml.registry import QmlPage, build_qml_page, register_migrated_pages
from ui_qml.theme import registry as theme

__all__ = ["ShellWindow", "ShellWindowBridge"]

_SHELL_QML = "shell/Main.qml"

#: 页面钩子里「切页时外壳会顺手调」的那几个（与 `SpecPageHost` 转发的是同一组）
_HOOK_REFRESH = "refresh_display"
_HOOK_STATUS = "update_status_bar"


class _StatusLabelShim:
    """`mw._status_label.setText(...)` 的替身。

    设置对话框那族桥按 Widgets 版的形状取状态栏文案
    （`getattr(mw, "_status_label", None)` 后 `.setText(...)`），
    QML 外壳没有 QLabel，用这个薄壳转发到状态栏 —— 免得为一行文案去改所有桥。
    """

    def __init__(self, window: ShellWindow) -> None:
        self._window = window

    def setText(self, text: str) -> None:
        self._window.set_status(text)


class ShellWindowBridge(QObject):
    """外壳自己的桥：导航 / 窗口控制 / 状态栏 / 价格信息，全部面向 `shell/Main.qml`。

    这里的属性都是**外壳的真实状态**（如 `pinned` / `maximized` / `autoUpdate`），
    QML 只读它、点击回传 —— 不让 QML 自己存一份，避免「按钮亮了但外壳没真置顶」。
    """

    stateChanged = Signal()

    def __init__(self, window: ShellWindow) -> None:
        super().__init__(window)
        self._window = window

    # ── QML 读 ────────────────────────────────────────────────

    appTitle = Property(str, lambda self: "EVE 商人助手", constant=True)

    @Property(list, notify=stateChanged)
    def navItems(self) -> list[dict]:
        # `icon` 一律发**文件名**（不是 NAV_TREE 里的语义键），见 `iconFile`
        return [
            {
                "key": key,
                "label": label,
                "icon": self.iconFile(icon),
                "section": key == "__section__",
            }
            for key, label, icon in NAV_TREE
        ]

    @Slot(str, result=str)
    def iconFile(self, key: str) -> str:
        """语义键 → Phosphor **文件名**（唯一来源是 `ui_qml.icons.ICON_MAP`）。

        QML 拼的是 `image://phosphor/<文件名>`，而导航树与图标键给的是**语义键**
        （`search` / `close` / `hangar`…），两者不是一回事：直接把语义键当文件名拼，
        取不到图时 provider 返回空白图，**不报错，图标整片消失** ——
        实测只有 `user` / `gear-six` / `coins` 这类「键恰好等于文件名」的能显示出来。
        """
        return ICON_MAP.get(key, key)

    @Property(str, notify=stateChanged)
    def currentKey(self) -> str:
        return self._window.current_page_key()

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._window._status_text

    @Property(bool, notify=stateChanged)
    def progressVisible(self) -> bool:
        return self._window._progress_visible

    @Property(int, notify=stateChanged)
    def progressValue(self) -> int:
        return self._window._progress_value

    @Property(int, notify=stateChanged)
    def progressMaximum(self) -> int:
        return self._window._progress_maximum

    @Property(str, notify=stateChanged)
    def priceAgeText(self) -> str:
        return self._window._price_age_text

    @Property(QColor, notify=stateChanged)
    def priceAgeColor(self) -> QColor:
        return self._window._price_age_color

    @Property(str, notify=stateChanged)
    def regionText(self) -> str:
        return self._window.region_text()

    @Property(list, notify=stateChanged)
    def regions(self) -> list[dict]:
        return [{"name": name, "checked": name in self._window._update_regions} for name in TRADE_HUBS]

    @Property(bool, notify=stateChanged)
    def autoUpdate(self) -> bool:
        return self._window._auto_update_enabled

    @Property(str, notify=stateChanged)
    def autoUpdateText(self) -> str:
        return self._window.auto_update_text()

    @Property(bool, notify=stateChanged)
    def pinned(self) -> bool:
        return self._window.is_pinned()

    @Property(bool, notify=stateChanged)
    def maximized(self) -> bool:
        return self._window.windowState() == Qt.WindowState.WindowMaximized

    # ── QML 写 ────────────────────────────────────────────────

    @Slot(str)
    def navigate(self, key: str) -> None:
        self._window.navigate_to(key)

    @Slot()
    def refreshPrice(self) -> None:
        self._window.trigger_price_update()

    @Slot(bool)
    def setAutoUpdate(self, enabled: bool) -> None:
        self._window.set_auto_update(enabled)

    @Slot(str, bool)
    def setRegion(self, name: str, checked: bool) -> None:
        self._window.set_update_region(name, checked)

    @Slot()
    def openSysSettings(self) -> None:
        self._window.show_sys_settings()

    @Slot()
    def openCharSettings(self) -> None:
        self._window.show_char_settings()

    @Slot()
    def openHangarSettings(self) -> None:
        self._window.show_hangar_settings()

    @Slot()
    def togglePin(self) -> None:
        self._window.set_pinned(not self._window.is_pinned())

    @Slot()
    def minimize(self) -> None:
        self._window.showMinimized()

    @Slot()
    def maximizeOrRestore(self) -> None:
        if self.maximized:
            self._window.showNormal()
        else:
            self._window.showMaximized()

    @Slot()
    def closeWindow(self) -> None:
        """关闭主窗口 —— **必须延迟一拍**。

        本槽是从 QML 的 `onClicked` 里调进来的，而关闭会同步拆掉 QML 场景
        （页面 Item + 根对象）。在信号处理器还没返回时就销毁它自己所属的对象，
        Qt 会直接报 CRITICAL：

            Object 0x… destroyed while one of its QML signal handlers is in progress.
            … ShellTitleBar.qml:63: function() { [native code] }

        排到下一个事件循环，处理器先返回，再关。（与「二级菜单弹出延迟一拍」同因。）
        """
        QTimer.singleShot(0, self._window.close)

    @Slot()
    def startMove(self) -> None:
        # ShellWindow 自己就是 QWindow（QQuickView 是 QWindow 子类），拖动/缩放直接调；
        # 不是 QWidget 那种「去问 windowHandle() 要句柄」的形态。
        self._window.startSystemMove()

    @Slot(int)
    def startResize(self, edges: int) -> None:
        self._window.startSystemResize(Qt.Edge(edges))

    def notify(self) -> None:
        """外壳状态变了 → 让 QML 重新取一遍（绑定靠这个信号）。

        **退出期直接不发**：那一刻 QML 上下文正在被拆，让场景重算只会在
        `Theme` / `shell` 已经取不到的时候求值，成片抛
        「Cannot read property 'xxx' of null」（实测退出时能刷出两百多行）。
        """
        from core.qt_noise import shutting_down

        if shutting_down():
            return
        self.stateChanged.emit()


class ShellWindow(QQuickView):
    """QML 外壳窗口。对页面的公开接口与 `MainWindow` 一致（鸭子类型，见 `ShellBridge`）。"""

    def __init__(self, hot_reload: bool = False) -> None:
        super().__init__()

        theme.set_geometry_file(window_geometry_file())
        ensure_dirs_exist()

        self.setTitle("EVE 商人助手")
        # 无边框：标题行/边缘缩放全在 QML + nativeEvent 里处理
        self.setFlags(self.flags() | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(QSize(1200, 700))
        self.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)

        # ── 主题 ──
        theme.apply_theme(theme.load_theme_preference())
        theme.add_theme_listener(self._on_theme_changed)
        self._sync_window_color()

        # ── 状态（QML 只读，见 ShellWindowBridge）──
        self._status_text = "就绪"
        self._progress_visible = False
        self._progress_value = 0
        self._progress_maximum = 0
        self._price_age_text = "价格: —"
        self._price_age_color = QColor(theme.TEXT_SECONDARY)
        self._update_regions: list[str] = self._load_update_regions()
        self._update_interval_minutes = self._load_interval()
        self._auto_update_enabled = self._load_auto_update()
        self._pinned = self._load_window_pin()
        self._price_timer: QTimer | None = None
        self._price_worker: Any = None
        self._check_worker: Any = None
        self._tray_icon: QSystemTrayIcon | None = None
        self._pages: dict[str, QmlPage] = {}
        self._current_key = ""
        self._status_label = _StatusLabelShim(self)
        self._closing = False

        # ── QML ──
        self._bridge = ShellWindowBridge(self)
        self.rootContext().setContextProperty(CONTEXT_NAME, theme_singleton())
        self.rootContext().setContextProperty("shell", self._bridge)

        # Phosphor 图标：外壳的引擎上注册一次（页面共用同一个引擎，不再是每页一个）
        self._icon_provider = PhosphorIconProvider()
        engine = self.engine()
        if engine is not None:
            engine.addImageProvider(PROVIDER_ID, self._icon_provider)

        self.setSource(QUrl.fromLocalFile(str(QML_ROOT / _SHELL_QML)))
        if self.status() == QQuickView.Status.Error:
            errors = "; ".join(err.toString() for err in self.errors())
            log.error("外壳 QML 加载失败 %s: %s", _SHELL_QML, errors)
            raise RuntimeError(f"外壳 QML 加载失败：{errors}")

        root = self.rootObject()
        content_area = root.property("contentArea") if root is not None else None
        if not isinstance(content_area, QQuickItem):
            raise RuntimeError("shell/Main.qml 没有给出 contentArea（页面无处安放）")
        self._content_area: QQuickItem = content_area
        self._content_area.widthChanged.connect(self._resize_pages)
        self._content_area.heightChanged.connect(self._resize_pages)

        # ── 页面 ──
        self._register_pages()

        # ── 窗口状态 ──
        self.windowStateChanged.connect(lambda _state: self._bridge.notify())
        theme.restore_window_geometry(self)

        # ── 价格 ──
        self._price_age_timer = QTimer(self)
        self._price_age_timer.timeout.connect(self.refresh_price_time)
        self._price_age_timer.start(60 * 1000)
        self._init_price_check()
        if self._auto_update_enabled and self._update_interval_minutes > 0:
            self._start_price_timer()

        # ── 热重载 / 首次启动 / 托盘 ──
        self._hot_reload_enabled = hot_reload
        if hot_reload:
            self._hot_reload_timer = QTimer(self)
            self._hot_reload_timer.timeout.connect(self._check_hot_reload)
            self._hot_reload_timer.start(500)
            from core import hot_reload as _hr

            state = _hr.read_state()
            if state:
                self.restore_state(state)
                _hr.clear_state()

        QTimer.singleShot(500, self._check_first_run)
        QTimer.singleShot(100, self._init_tray_icon)

        # 退出时必须**两条路都**等线程收尾：关窗走 closeEvent，而托盘菜单的「退出」
        # 直接调 `QApplication.quit()` —— 它只退出事件循环，**不会关窗**，
        # `closeEvent` 根本不被调用。少了这条，仍在跑的 QThread 会随 QApplication
        # 析构被删，Qt 直接报 `QThread: Destroyed while thread is still running`
        # （本仓反复踩过的硬崩形态）。实测：托盘退出正是走的这条路。
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop_running_threads)

        # 默认页（与 Widgets 版一致：第一个非分组项）
        first = next((k for k, _l, _i in NAV_TREE if k != "__section__"), "")
        if first:
            self.navigate_to(first)

    # ══════════════════════════════════════════════════════════
    #  窗口级
    # ══════════════════════════════════════════════════════════

    def _sync_window_color(self) -> None:
        """窗口底色：solid 材质用主题底色，其余设为透明好让 DWM 毛玻璃透出来。

        QML 根节点不画不透明底（见 `shell/Main.qml`），所以这一步决定「透不透」。
        """
        if theme.theme_material() == "solid":
            self.setColor(QColor(theme.BG_DARK))
        else:
            self.setColor(Qt.GlobalColor.transparent)

    def _on_theme_changed(self) -> None:
        self._sync_window_color()
        self._apply_window_backdrop()
        self._bridge.notify()

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)  # type: ignore[arg-type]
        self._apply_window_backdrop()
        if self._pinned:
            self._apply_pin(True)

    def _apply_window_backdrop(self) -> None:
        """恢复原生缩放/吸附样式 + 应用 DWM 毛玻璃/暗色（失败自动降级）。"""
        try:
            hwnd = int(self.winId())
            from ui_qml.dwm import apply_dwm_backdrop, enable_native_resize

            enable_native_resize(hwnd)
            spec = theme.current_theme_spec()
            dark = bool(spec and spec["mode"] == "dark")
            apply_dwm_backdrop(hwnd, theme.theme_material(), dark)
        except Exception:
            log.exception("应用 DWM 毛玻璃失败（降级 solid）")

    def nativeEvent(self, eventType: Any, message: Any) -> Any:
        """Windows 无边框窗口消息：逐行照搬 `MainWindow.nativeEvent`（行为不能变）。"""
        if sys.platform == "win32":
            try:
                import ctypes
                import ctypes.wintypes

                msg = ctypes.wintypes.MSG.from_address(int(message))
                WM_NCCALCSIZE, WM_NCHITTEST, WM_NCACTIVATE, WM_GETMINMAXINFO = 0x0083, 0x0084, 0x0086, 0x0024
                if msg.message == WM_NCCALCSIZE:
                    return True, 0  # 隐藏原生非客户区（保持无边框外观）
                if msg.message == WM_NCACTIVATE:
                    return True, 1  # 阻止激活/失活时绘制原生边框
                if msg.message == WM_NCHITTEST:
                    return True, self._nchittest(msg.lParam)
                if msg.message == WM_GETMINMAXINFO:
                    return True, self._minmax_info(msg.lParam)
            except Exception:
                log.exception("nativeEvent 处理失败")
        return super().nativeEvent(eventType, message)

    @staticmethod
    def _minmax_info(lParam: int) -> int:
        """WM_GETMINMAXINFO：把最大化尺寸/位置钳制到工作区。"""
        import ctypes
        import ctypes.wintypes

        SPI_GETWORKAREA = 0x0030
        work = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0):
            return 0

        class MINMAXINFO(ctypes.Structure):
            _fields_ = [
                ("ptReserved", ctypes.wintypes.POINT),
                ("ptMaxSize", ctypes.wintypes.POINT),
                ("ptMaxPosition", ctypes.wintypes.POINT),
                ("ptMinTrackSize", ctypes.wintypes.POINT),
                ("ptMaxTrackSize", ctypes.wintypes.POINT),
            ]

        info = MINMAXINFO.from_address(int(lParam))
        info.ptMaxSize.x = work.right - work.left
        info.ptMaxSize.y = work.bottom - work.top
        info.ptMaxPosition.x = work.left
        info.ptMaxPosition.y = work.top
        return 0

    def _nchittest(self, lParam: int) -> int:
        """WM_NCHITTEST 命中码：边缘缩放；标题栏一律 HTCLIENT 交给 QML 拖动。

        与原实现同因：拖动统一走 `startSystemMove`（一次性 SC_MOVE），
        逐帧重判命中码会让拖动抖动。
        """
        HTCLIENT = 1
        HTLEFT, HTRIGHT, HTTOP = 10, 11, 12
        HTTOPLEFT, HTTOPRIGHT = 13, 14
        HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17

        if self.windowState() in (Qt.WindowState.WindowMaximized, Qt.WindowState.WindowFullScreen):
            return HTCLIENT
        from PySide6.QtGui import QCursor

        pt = self.mapFromGlobal(QCursor.pos())
        margin = 6
        w, h = self.width(), self.height()
        if pt.y() <= margin:
            if pt.x() <= margin:
                return HTTOPLEFT
            if pt.x() >= w - margin:
                return HTTOPRIGHT
            return HTTOP
        if pt.y() >= h - margin:
            if pt.x() <= margin:
                return HTBOTTOMLEFT
            if pt.x() >= w - margin:
                return HTBOTTOMRIGHT
            return HTBOTTOM
        if pt.x() <= margin:
            return HTLEFT
        if pt.x() >= w - margin:
            return HTRIGHT
        return HTCLIENT

    def closeEvent(self, event: Any) -> None:
        from core import hot_reload as _hr
        from core.qt_noise import begin_shutdown

        begin_shutdown()
        _hr.clear_trigger()
        self._closing = True
        self._teardown_qml()  # 先拆场景，再谈别的（见该方法说明）
        theme.remove_theme_listener(self._on_theme_changed)
        theme.save_window_geometry(self)
        for w in QApplication.topLevelWidgets():
            if w is not self and w.isVisible():
                w.close()
        self._stop_running_threads()
        if self._tray_icon:
            self._tray_icon.hide()
        super().closeEvent(event)  # type: ignore[arg-type]

    def _teardown_qml(self) -> None:
        """先把 QML 场景拆干净，再让引擎/窗口析构。

        顺序很要紧：反过来（引擎先走、场景还在）时，任何一次绑定重算都会撞上
        已经被拆掉的上下文，抛 `Cannot read property 'xxx' of null`。
        页面 Item 与根对象都在引擎**还活着**的时候显式删掉，绑定就不会有机会
        对着死上下文求值。

        与 `closeEvent` 一样不做幂等保护：重复调用时 `setSource(QUrl())` 是空操作。
        """
        for page in self._pages.values():
            if page.item is not None:
                page.item.deleteLater()
        self._pages.clear()
        if self.rootObject() is not None:
            self.setSource(QUrl())  # 丢掉根对象（QQuickView 的公开做法）

    def _stop_running_threads(self) -> None:
        """等所有后台线程退出（可重入：closeEvent 与 aboutToQuit 都会调）。

        页面内的 QThread 在**仍运行时被销毁**，Qt 会直接报
        `QThread: Destroyed while thread is still running` —— 那是硬崩前的最后一次警告，
        所以两条退出路径都要走到这里。
        """
        from PySide6.QtCore import QThread

        from core.qt_noise import begin_shutdown

        # 托盘「退出」走 app.quit()，不经过 closeEvent —— 这里补上同一个标记
        begin_shutdown()
        for worker in self.findChildren(QThread):
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(3000)

    # ══════════════════════════════════════════════════════════
    #  外壳公开 API（页面的桥按鸭子类型调，与 MainWindow 同形）
    # ══════════════════════════════════════════════════════════

    def set_status(self, text: str) -> None:
        self._status_text = str(text)
        self._bridge.notify()

    def show_progress(self, text: str = "", maximum: int = 0) -> None:
        self._status_text = text or "处理中..."
        self._progress_visible = True
        self._progress_maximum = max(0, int(maximum))
        self._progress_value = 0
        self._bridge.notify()

    def update_progress(self, value: int, text: str = "") -> None:
        self._progress_value = int(value)
        if text:
            self._status_text = text
        self._bridge.notify()

    def hide_progress(self, text: str = "就绪") -> None:
        self._progress_visible = False
        self._progress_maximum = 0
        self._status_text = text
        self._bridge.notify()

    def navigate_to(self, key: str) -> bool:
        """切到某个导航页（找不到返回 False）。"""
        if key not in self._pages:
            return False
        self._current_key = key
        for pkey, page in self._pages.items():
            page.item.setVisible(pkey == key)
        hooks = self._pages[key].hooks
        target = getattr(hooks, _HOOK_STATUS, None)
        if callable(target):
            target()
        if key == "watchlist":
            trigger = getattr(hooks, "trigger_price_check", None)
            if callable(trigger):
                trigger()
        self._bridge.notify()
        return True

    def current_page_key(self) -> str:
        return self._current_key

    # ══════════════════════════════════════════════════════════
    #  页面
    # ══════════════════════════════════════════════════════════

    def _register_pages(self) -> None:
        register_migrated_pages()
        engine = self.engine()
        if engine is None:
            raise RuntimeError("外壳没有 QQmlEngine，无法建页面")
        for key, _label, _icon in NAV_TREE:
            if key == "__section__":
                continue
            page = build_qml_page(key, self, engine, self._content_area)
            if page is None:
                log.warning("页面 %s 未迁移到 QML 或加载失败，本页暂缺", key)
                continue
            page.item.setVisible(False)
            self._pages[key] = page
        self._resize_pages()
        log.info(
            "QML 外壳已装载 %d/%d 个页面", len(self._pages), sum(1 for k, _l, _i in NAV_TREE if k != "__section__")
        )

    def _resize_pages(self) -> None:
        """页面尺寸跟随内容区（Item 之间的尺寸同步得显式做，QML 里写锚点也行，
        但页面是 Python 造的，拿不到那段 QML，所以在这里连信号）。"""
        from core.qt_noise import shutting_down

        if shutting_down() or not self._pages:
            return
        w = self._content_area.width()
        h = self._content_area.height()
        for page in self._pages.values():
            page.item.setWidth(w)
            page.item.setHeight(h)

    # ══════════════════════════════════════════════════════════
    #  状态保存 / 恢复（热重载与退出用）
    # ══════════════════════════════════════════════════════════

    def save_state(self) -> dict:
        pages: dict[str, Any] = {}
        state = {"version": 1, "current_page": self._current_key, "pages": pages}
        for key, page in self._pages.items():
            save = getattr(page.hooks, "save_state", None)
            if callable(save):
                try:
                    pages[key] = save()
                except Exception:
                    log.exception("保存页面状态失败: %s", key)
        return state

    def restore_state(self, data: dict | None) -> None:
        if not data:
            return
        key = data.get("current_page")
        if key:
            self.navigate_to(key)
        for pkey, pdata in data.get("pages", {}).items():
            page = self._pages.get(pkey)
            restore = getattr(page.hooks, "restore_state", None) if page else None
            if callable(restore):
                try:
                    restore(pdata)
                except Exception:
                    log.exception("恢复页面状态失败: %s", pkey)

    # ══════════════════════════════════════════════════════════
    #  价格
    # ══════════════════════════════════════════════════════════

    def _init_price_check(self) -> None:
        from ui_qml.workers.main_window_workers import PriceCheckWorker

        self._check_worker = PriceCheckWorker(self._update_interval_minutes, self)
        self._check_worker.result.connect(self._on_price_check_done)
        self._check_worker.start()

    def _on_price_check_done(self, needs_update: bool, status_text: str) -> None:
        self.set_status(status_text)
        self._refresh_price_age()
        if not needs_update:
            return
        if self._auto_update_enabled:
            self.set_status("正在自动更新价格...")
            QTimer.singleShot(1000, self.trigger_price_update)
        else:
            self.set_status("价格数据需要更新（自动更新已关闭）")

    def trigger_price_update(self) -> None:
        if self._price_worker is not None and self._price_worker.isRunning():
            self.set_status("价格更新已在运行中")
            return

        regions = None if set(self._update_regions) == set(TRADE_HUBS) else self._update_regions
        if regions is not None and not regions:
            self.set_status("请先在区域菜单勾选至少一个贸易中心")
            return
        self.set_status(f"正在更新 {', '.join(regions)}..." if regions else "正在从 ESI 获取市场价格...")
        self.show_progress(self._status_text, 0)

        from ui_qml.workers.main_window_workers import PriceUpdateWorker

        self._price_worker = PriceUpdateWorker(regions, self)
        self._price_worker.finished_signal.connect(self._on_price_update_done)
        self._price_worker.start()

    def _on_price_update_done(self, success: bool, message: str) -> None:
        self.hide_progress("价格更新完成" if success else f"价格更新失败: {message}")
        if not success:
            return
        try:
            from services.scoring_service import invalidate_cache

            invalidate_cache()
            get_container().scoring_service().invalidate_cache()
        except Exception:
            log.exception("价格更新后清缓存失败")
        self._refresh_price_age()
        page = self._pages.get("query")
        refresh = getattr(page.hooks, _HOOK_REFRESH, None) if page else None
        if callable(refresh):
            refresh()
        self._check_and_notify_price_changes()

    def _check_and_notify_price_changes(self) -> None:
        try:
            from services.watchlist_manager import check_price_changes

            changes = check_price_changes()
            if not changes:
                return
            parts = []
            for c in changes[:3]:
                name = c["name"]
                if c["old_buy"] and c["new_buy"] and abs(c["new_buy"] - c["old_buy"]) > 0.01:
                    parts.append(f"{name}: 买 {c['old_buy']:.2f}→{c['new_buy']:.2f}")
                elif c["old_sell"] and c["new_sell"] and abs(c["new_sell"] - c["old_sell"]) > 0.01:
                    parts.append(f"{name}: 卖 {c['old_sell']:.2f}→{c['new_sell']:.2f}")
            details = "; ".join(parts)
            count = len(changes)
            if count > 3:
                details += f" …等 {count} 个"
            msg = f"{count} 个物品价格发生变化"
            self.set_status(f"🔔 {msg}")
            if self._tray_icon is not None and self._tray_icon.isVisible():
                self._tray_icon.showMessage(
                    "EVE 商人助手 - 价格变化",
                    details or msg,
                    QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
        except Exception as ex:
            self.set_status(f"价格变化检测失败: {ex}")

    def refresh_price_time(self) -> None:
        self._refresh_price_age()

    def _set_price_age(self, text: str, color: str) -> None:
        self._price_age_text = text
        self._price_age_color = QColor(color)
        self._bridge.notify()

    def _refresh_price_age(self) -> None:
        try:
            latest = get_container().market_repo.get_latest_fetch_time()
            if not latest:
                self._set_price_age("价格: 暂无数据", theme.TEXT_SECONDARY)
                return
            try:
                dt = datetime.strptime(latest, "%Y-%m-%d %H:%M:%S")
                now_utc = datetime.now(UTC).replace(tzinfo=None)
                diff_min = int((now_utc - dt).total_seconds() / 60)
                if diff_min < 10:
                    color = theme.GREEN
                elif diff_min < 30:
                    color = theme.ACCENT_YELLOW
                else:
                    color = theme.ACCENT_RED
                bj_str = (dt.replace(tzinfo=UTC) + timedelta(hours=8)).strftime("%H:%M")
                self._set_price_age(f"价格: {diff_min} 分钟前 ({bj_str})", color)
            except Exception:
                self._set_price_age("价格: 解析异常", theme.TEXT_SECONDARY)
        except Exception:
            self._set_price_age("价格: 数据库未就绪", theme.TEXT_SECONDARY)

    # ── 自动更新 / 区域 ────────────────────────────────────────

    def auto_update_text(self) -> str:
        if self._auto_update_enabled and self._update_interval_minutes > 0:
            return f"每 {self._update_interval_minutes} 分钟"
        return "自动更新: 关"

    def region_text(self) -> str:
        regions = self._update_regions
        if set(regions) == set(TRADE_HUBS):
            return "区域: 全部"
        if not regions:
            return "区域: 无"
        if len(regions) <= 2:
            return f"区域: {', '.join(regions)}"
        return f"区域: {', '.join(regions[:2])} +{len(regions) - 2}"

    def set_update_region(self, name: str, checked: bool) -> None:
        if name not in TRADE_HUBS:
            return
        if checked and name not in self._update_regions:
            self._update_regions.append(name)
        elif not checked and name in self._update_regions:
            self._update_regions.remove(name)
        self._save_settings()
        self._bridge.notify()

    def set_auto_update(self, enabled: bool) -> None:
        self._auto_update_enabled = bool(enabled)
        self._save_settings()
        if enabled and self._update_interval_minutes > 0:
            self._start_price_timer()
            self.set_status(f"已开启自动更新（每 {self._update_interval_minutes} 分钟）")
        else:
            self._stop_price_timer()
            self.set_status("已关闭自动更新")
        self._bridge.notify()

    def _start_price_timer(self) -> None:
        if self._price_timer is not None:
            self._price_timer.stop()
        if self._update_interval_minutes <= 0:
            return
        self._price_timer = QTimer(self)
        self._price_timer.timeout.connect(self._init_price_check)
        self._price_timer.start(self._update_interval_minutes * 60 * 1000)

    def _stop_price_timer(self) -> None:
        if self._price_timer is not None:
            self._price_timer.stop()
            self._price_timer = None

    # ── 设置读写（与 Widgets 版同一套键，来回切外壳不会丢设置）──

    def _load_interval(self) -> int:
        from services.user_settings import load_settings

        try:
            return max(0, min(1440, int(load_settings().get("update_interval", 30))))
        except (TypeError, ValueError):
            return 30

    def _load_auto_update(self) -> bool:
        from services.user_settings import load_settings

        return bool(load_settings().get("auto_update_enabled", True))

    def _load_update_regions(self) -> list[str]:
        from services.user_settings import load_settings

        regions = load_settings().get("update_regions", [])
        if isinstance(regions, list):
            valid = [r for r in regions if r in TRADE_HUBS]
            if valid:
                return valid
        return ["Jita"]

    def _load_window_pin(self) -> bool:
        from services.user_settings import load_settings

        return bool(load_settings().get("window_pin", False))

    def _save_settings(self) -> None:
        from services.user_settings import save_settings

        try:
            save_settings(
                {
                    "update_interval": self._update_interval_minutes,
                    "auto_update_enabled": self._auto_update_enabled,
                    "update_regions": list(self._update_regions),
                    "window_pin": self._pinned,
                }
            )
        except Exception as e:
            self.set_status(f"保存设置失败: {e}")

    # ── 置顶 ──────────────────────────────────────────────────

    def is_pinned(self) -> bool:
        return self._pinned

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = bool(pinned)
        self._apply_pin(self._pinned)
        self._save_settings()
        self._bridge.notify()

    def _apply_pin(self, checked: bool) -> None:
        from ui_qml.pin_utils import apply_window_pin

        try:
            apply_window_pin(self, checked)
        except Exception:
            log.exception("应用窗口置顶失败")
        self._apply_window_backdrop()

    # ══════════════════════════════════════════════════════════
    #  设置对话框 / 首次启动 / 托盘 / 热重载
    # ══════════════════════════════════════════════════════════

    def show_char_settings(self) -> None:
        from ui_qml.bridge.char_settings_bridge import CharSettingsQmlDialog

        CharSettingsQmlDialog(self).exec()

    def show_sys_settings(self) -> None:
        from ui_qml.bridge.settings_bridge import SettingsQmlDialog

        SettingsQmlDialog(self, self).exec()

    def show_hangar_settings(self) -> None:
        from ui_qml.bridge.hangar_settings_bridge import HangarSettingsQmlDialog

        HangarSettingsQmlDialog(self).exec()
        page = self._pages.get("industry")
        load_plans = getattr(page.hooks, "load_plans", None) if page else None
        if callable(load_plans):
            load_plans()

    def _show_init_wizard(self, auto_mode: bool = False) -> None:
        from ui_qml.bridge.init_wizard_bridge import InitWizardQmlDialog

        InitWizardQmlDialog(auto_mode=auto_mode).exec()

    def _show_about(self) -> None:
        """「关于」—— 沿用原版的 `QMessageBox.about`（系统关于框，不是页面里的自绘窗）。"""
        from PySide6.QtWidgets import QMessageBox

        from core.version import __version__

        # 父窗口传 None：`QMessageBox` 要 QWidget 父，传 QQuickView 会在运行时炸
        QMessageBox.about(
            None,
            "关于 EVE 商人助手",
            f"EVE 商人助手 v{__version__}\n\n"
            "基于 PySide6 重构\n"
            "为 EVE Online 玩家提供工业制造、市场贸易辅助工具。\n\n"
            "数据来源: EVE Swagger Interface (ESI)\n"
            "© 2026",
        )

    def _check_first_run(self) -> None:
        from services.init_check import check_all

        status = check_all()
        has_items = status.get("items", False)
        missing = sum(1 for v in status.values() if not v)
        if missing == 0 and has_items:
            self.set_status("就绪")
        else:
            failed = [k for k, v in status.items() if not v]
            msg = "⚠️ 1 项未初始化" if len(failed) == 1 else f"⚠️ {missing} 项未初始化"
            self.set_status(f"{msg} ({', '.join(failed)})")

    def _check_hot_reload(self) -> None:
        from core import hot_reload as _hr

        if not _hr.is_triggered():
            return
        state = self.save_state()
        _hr.write_state(state)
        _hr.clear_trigger()
        QApplication.quit()

    def _init_tray_icon(self) -> None:
        import os

        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon = None
            return

        from core.paths import ICON_DIR

        icon: QIcon | None = None
        if os.path.isdir(ICON_DIR):
            for fname in sorted(os.listdir(ICON_DIR)):
                fpath = os.path.join(ICON_DIR, fname)
                if os.path.isfile(fpath) and fname.lower().endswith((".png", ".ico", ".svg", ".xpm")):
                    icon = QIcon(fpath)
                    if not icon.isNull():
                        break
        if icon is None or icon.isNull():
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.PRIMARY))
            painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
            painter.setBrush(QColor(theme.TEXT_ON_PRIMARY))
            font = painter.font()
            font.setPointSize(28)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "E")
            painter.end()
            icon = QIcon(pixmap)

        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setIcon(icon)
        self._tray_icon.setToolTip("EVE 商人助手")

        # 菜单**不能**把 QQuickView 当父对象：`QMenu` 的父必须是 QWidget，
        # 传 QWindow 会抛 "QMenu.__init__ called with wrong argument types"。
        # 无父的菜单要自己留引用，否则被 GC 回收后托盘右键就没有菜单了。
        menu = QMenu()
        self._tray_menu = menu
        menu.setObjectName("sys_menu")
        show_action = QAction("打开主窗口", self)
        show_action.triggered.connect(self._tray_show_window)
        menu.addAction(show_action)
        menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(QApplication.quit)
        menu.addAction(exit_action)
        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _tray_show_window(self) -> None:
        self.show()
        self.raise_()
        self.requestActivate()

    def _on_tray_activated(self, reason: Any) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show_window()
