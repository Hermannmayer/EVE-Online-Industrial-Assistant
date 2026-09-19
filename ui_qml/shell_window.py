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
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QRect, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core.constants import TRADE_HUBS
from core.container import get_container
from core.logger import log
from core.paths import ensure_dirs_exist, window_geometry_file
from domain.theme_contrast import ensure_contrast
from ui_qml.app_icon import ASSETS_DIR
from ui_qml.bridge import CONTEXT_NAME, theme_singleton
from ui_qml.constants import NAV_TREE
from ui_qml.host import QML_ROOT
from ui_qml.icon_provider import PROVIDER_ID, PhosphorIconProvider
from ui_qml.icons import ICON_MAP
from ui_qml.registry import QmlPage, build_qml_page, register_migrated_pages
from ui_qml.theme import registry as theme

__all__ = ["ShellWindow", "ShellWindowBridge"]

_SHELL_QML = "shell/Main.qml"

#: 「按下 vs 拖动」的判定阈值（px）。优先用系统 SM_CXDRAG/SM_CYDRAG，取不到才用这个兜底。
_DRAG_THRESHOLD = 4


def _drag_threshold() -> int:
    """系统拖动阈值（SM_CXDRAG/SM_CYDRAG 取较大者）。非 Win32 或取不到 → 兜底 4px。

    取系统值是必要的：Windows 上鼠标的「手抖」幅度是可调的，写死会出现
    「我明明只是点了一下，窗口却还原了」。
    """
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            SM_CXDRAG, SM_CYDRAG = 68, 69
            return max(int(user32.GetSystemMetrics(SM_CXDRAG)), int(user32.GetSystemMetrics(SM_CYDRAG)))
        except Exception:
            log.debug("读系统拖动阈值失败，回落 %dpx", _DRAG_THRESHOLD)
    return _DRAG_THRESHOLD


#: 页面钩子里「切页时外壳会顺手调」的那几个。
#: 批次 7.4 之前这组由 `SpecPageHost` 转发（那条路已随 Widgets 回退脚手架删除），现在这里是唯一定义处。
_HOOK_REFRESH = "refresh_display"
_HOOK_STATUS = "update_status_bar"
#: 页面**被切到前台**时同步一次（工业页用它重读价格设置）。
#: 批次 7.4 起工业页控制器是 `QObject`、没有 `showEvent` 可依赖，这条分发是**唯一**唤醒路径 ——
#: 钩子名改了或这里删了都是静默失效：从仓库页改完材料倍率切回工业页，工具栏旋钮停在旧值且不报错。
_HOOK_SHOWN = "on_shown"


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
                "color": self.navIconColor(color_token),
            }
            for key, label, icon, color_token in NAV_TREE
        ]

    @Slot(str, result=str)
    def navIconColor(self, token: str) -> str:
        """导航条目配色的 token 名 → 当前主题的实际色值（已做对比度兜底）。

        `NAV_TREE` 里存的是 `"ACCENT_YELLOW"` 这类**名字**，不是色值 —— 那样这份
        常量表就不必依赖 Qt/主题。到这里才解析成颜色，并且**必须过一遍
        `ensure_contrast`**：浅色主题的琥珀 `#ffb300` 对白底只有 1.79:1，
        远低于 WCAG 1.4.11 对图形要求的 3:1，直接画会糊成一片。

        对照底色取 `BG_SURFACE`（侧栏自身底色）。实际渲染用的是它 90% 不透明叠在
        `BG_DARK` 上（`Main.qml` 的 `chromeColor`），与本值只差几个色阶，
        对比度影响 <2%，不值得为它把那个 0.9 再复制一份过来。
        """
        color = getattr(theme, token, None)
        if not isinstance(color, str):
            log.warning("导航配色 token 不存在：%s", token)
            return theme.TEXT_SECONDARY
        return ensure_contrast(color, theme.BG_SURFACE)

    @Property(str, notify=stateChanged)
    def logoSource(self) -> str:
        """侧栏 logo 的 `file://` URL —— 按深/浅主题二选一。

        和 `iconFile` 是同一条约定：**文件系统的事归桥管，QML 不拼路径**。
        侧栏 QML 在 `ui_qml/qml/shell/` 下，`Qt.resolvedUrl("../assets/…")` 会解析到
        `ui_qml/qml/assets/`（不存在），资产实际在 `ui_qml/assets/` —— 拼相对路径会静默空白。

        两张图由 `scripts/make_app_icon.py` 生成（透明底，笔画色分深/浅，品牌红点保留）。
        文件缺失时返回 `""`：`Image` 空 source 只是不画，不报错。
        """
        name = "logo_dark.png" if theme.is_dark_mode() else "logo_light.png"
        path = Path(ASSETS_DIR) / name
        return QUrl.fromLocalFile(str(path)).toString() if path.exists() else ""

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

    @Slot(float, float, float, float, result=bool)
    def beginMove(self, press_x: float, press_y: float, x: float, y: float) -> bool:
        """标题栏拖动：超过系统拖动阈值再起拖；最大化时先还原再跟手。见 `ShellWindow.begin_move`。"""
        return self._window.begin_move(press_x, press_y, x, y)

    @Slot()
    def endMove(self) -> None:
        """标题栏拖动结束（抬起 / 取消 / 新的一次按下）。见 `ShellWindow.end_move`。"""
        self._window.end_move()

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
        #: 「最大化前的尺寸」——`showMaximized()` 不改 geometry()，所以这里读到的就是
        #: 还原后该回的尺寸；`QWindow` 没有 `normalGeometry()`（实测），只能自己记。
        self._normal_rect = QRect(self.geometry())
        #: 本次按下是否已交棒给系统拖动循环 —— 详见 `begin_move`
        self._drag_handed_off = False

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

        # 默认页 = 导航首项（`NAV_TREE` 的顺序即显示顺序）
        first = NAV_TREE[0][0]
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
        """主题切换时同步窗口。**必须容忍「自己已经被销毁」**。

        `closeEvent` 会注销这条监听器，但那条路只覆盖「正常关闭」。**没走 `closeEvent`
        就被销毁**的情况拦不住 —— 测试与截图工具里大量存在（建窗后直接 `deleteLater()`，
        从不 `close()`）。那种情况下监听器还活着、窗口的 C++ 对象已经没了，而下一次
        `apply_theme` 就会在 `setColor` 上撞 `RuntimeError: Internal C++ object already
        deleted`，日志成片刷「主题监听器回调失败」。

        所以这里接住它并**顺手注销**：一条已经没救的监听器，不该每次切主题都重撞一遍。
        用 debug 而不是 warning 记一笔 —— 这是已知且无害的收尾路径，不是需要用户注意的故障。
        """
        try:
            self._sync_window_color()
            self._apply_window_backdrop()
            self._bridge.notify()
        except RuntimeError:
            # 这三个调用里唯一会抛 RuntimeError 的情形就是「底层 C++ 对象已被销毁」，
            # 而 PySide 的包装器还活着（弱引用因此尚未失效，剪除逻辑够不到它）。
            log.debug("窗口已销毁，注销主题监听器")
            theme.remove_theme_listener(self._on_theme_changed)

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
        # 工业那两个工具窗（产线小助手 / 采购）在批次 7.4 之后是 **QWindow**，
        # 而 `topLevelWidgets()` **不含 QWindow**（实测）—— 少了这一段，关主窗后
        # 它们仍然可见，`quitOnLastWindowClosed` 永不触发，表现为「点了关闭但进程不退」。
        for win in QGuiApplication.topLevelWindows():
            if win is not self and win.isVisible():
                win.close()
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
        # 页面控制器里那些**不是外壳子对象**的线程要单独关：工业页的 worker 挂在
        # `IndustryPage` 之下，而它没有 QObject 父（`main_window` 是位置参数、不是 parent），
        # 所以下面那句 `findChildren(QThread)` 根本找不到它们 —— 漏掉的后果是
        # 「QThread 运行中被析构 → Qt 直接 abort()」，静默死进程且不留日志。
        for page in getattr(self, "_pages", {}).values():
            shutdown = getattr(page.hooks, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    log.exception("页面关机钩子失败")
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
        # 「页面被切到前台」的同步。放在状态栏之后：钩子实现里可能改状态文案，
        # 让状态栏先落地再让页面同步。
        shown = getattr(hooks, _HOOK_SHOWN, None)
        if callable(shown):
            shown()
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
        for key, _label, _icon, _color in NAV_TREE:
            page = build_qml_page(key, self, engine, self._content_area)
            if page is None:
                log.warning("页面 %s 未迁移到 QML 或加载失败，本页暂缺", key)
                continue
            page.item.setVisible(False)
            self._pages[key] = page
        self._resize_pages()
        log.info("QML 外壳已装载 %d/%d 个页面", len(self._pages), len(NAV_TREE))

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

    # ── 标题栏拖动（最大化即还原并跟手）───────────────────────

    def moveEvent(self, event: Any) -> None:
        """记录「最大化前的尺寸」—— 只有常规态才记（详见 `_normal_rect`）。"""
        super().moveEvent(event)  # type: ignore[arg-type]
        self._remember_normal_rect()

    def resizeEvent(self, event: Any) -> None:
        """同上。`QWindow` 没有 `normalGeometry()`，这个字段就是我们的「normal」。"""
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._remember_normal_rect()

    def _remember_normal_rect(self) -> None:
        """常规态下把当前几何存成「最大化前的尺寸」。

        必须**持续**记录而不是构造时记一次：用户先调整窗口大小、再最大化、再拖标题栏时，
        要还原到「最大化前那一刻的尺寸」，不是启动时的尺寸。
        最大化/最小化/全屏期间不记 —— 那些状态下的 `geometry()` 是屏幕尺寸，记进去
        会让下次还原直接铺满屏幕。
        """
        if self.windowState() != Qt.WindowState.WindowNoState:
            return
        if self.geometry().isValid():
            self._normal_rect = QRect(self.geometry())

    def begin_move(self, press_x: float, press_y: float, x: float, y: float) -> bool:
        """标题栏拖动：越过阈值才起拖；最大化时先还原再跟手。

        为什么不在按下时直接 `startSystemMove()`：那样最大化窗口会被整体拖走。原生标题
        栏的「拖动即还原成最大化前的尺寸、并把窗口压到光标下」是**系统拖动循环**
        （`WM_NCLBUTTONDOWN` + `HTCAPTION`）的附带行为；`startSystemMove` 内部只走
        `SC_MOVE`，**不带还原**，所以这一步得自己补。

        坐标是窗口内坐标；阈值取系统 `SM_CXDRAG/SM_CYDRAG` —— 单纯单击（未越阈值）
        不会还原，与 Windows 判定「点击 vs 拖动」的标准一致。

        Returns:
            是否已交棒给系统拖动循环（True 时 QML 侧不必再处理后续移动事件）。
        """
        threshold = _drag_threshold()
        if abs(x - press_x) < threshold and abs(y - press_y) < threshold:
            return False
        # 同一次按下只起拖一次。`startSystemMove()` 内部先 `ReleaseCapture()` 再投递
        # `WM_SYSCOMMAND/SC_DRAGMOVE`：系统拖动循环已经跑起来之后再调一次，那次
        # `ReleaseCapture()` 会把正在进行的循环掐断（窗口刚跟手就停，看起来像拖不动）。
        # QML 侧每次移动都会调进来，所以守卫必须落在这里。
        if self._drag_handed_off:
            return True
        self._drag_handed_off = True
        if self.windowState() == Qt.WindowState.WindowMaximized:
            ratio = (x / self.width()) if self.width() else 0.5
            self._restore_before_move(ratio)
        self.startSystemMove()
        return True

    def end_move(self) -> None:
        """本次按下结束（抬起 / 取消 / 新的一次按下）—— 复位交棒标记。

        不复位的话，同一次拖动结束后再按标题栏就永远起不了拖了。
        """
        self._drag_handed_off = False

    def _restore_before_move(self, ratio: float) -> None:
        """还原为最大化前的尺寸，并把窗口摆到光标下（照 Windows 标题栏拖动的做法）。

        `QWindow` 没有 `normalGeometry()`（实测，那是 `QWidget` 的），所以「最大化前的
        尺寸」只能自己记：构造时读一次持久化几何 —— `showMaximized()` 不改 `geometry()`，
        因此那里记下的就是该还原到的尺寸。

        ratio: 光标在最大化窗口内的横向比例（0~1），用来决定还原后光标停在窗口的哪一处，
        这样拖动跟手时窗口不会「跳」到光标右边。
        """
        from PySide6.QtGui import QCursor

        rect = self._normal_rect
        width = max(int(rect.width()), self.minimumWidth())
        height = max(int(rect.height()), self.minimumHeight())
        self.showNormal()
        self.resize(width, height)
        cur = QCursor.pos()
        left = cur.x() - int(width * min(max(ratio, 0.0), 1.0))
        # 纵向让光标落在标题行上（标题行高 32，取其中点附近），与原生观感一致
        self.setPosition(left, cur.y() - 16)

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
        """「关于」—— 走 `FMessageDialog.about`（自绘 QML，批次 7.1）。"""
        from core.version import __version__
        from ui_qml.bridge.message_dialog import FMessageDialog

        # 父窗口传 None：`QmlDialog`（QDialog）要 QWidget 父，传 QQuickView 会在运行时炸
        FMessageDialog.about(
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
