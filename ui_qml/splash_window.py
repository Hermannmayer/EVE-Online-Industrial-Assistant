"""QML 启动画面（阶段 7 批次 7.2）—— 顶替 `ui_pyside6/splash_screen.py`。

**这是全应用第一个 QML 面**，比别的 QML 面多一条硬要求：**它坏掉等于启动时什么都不显示**，
而此刻 `qInstallMessageHandler` 还没装、日志 handler 也未必已经可用。所以本模块的加载
路径自带兜底（`SplashScreen.__init__` 捕获异常 → `_FallbackSplash`，并往 stderr 打一行），
而不是像别处那样「加载失败就抛给调用方」。

窗口语义逐项对应原 QWidget（`qml/shell/Splash.qml` 里是 QML 侧那一半）：

    setFixedSize(360,470)              → Window 的 minimum*/maximum*
    FramelessWindowHint|StaysOnTopHint → Window 的 flags
    WA_TranslucentBackground + 自绘圆角 → Window 的 `color: "transparent"` + 面板 Rectangle 的 radius
                                           （QML 没有窗口圆角，圆角只能靠矩形自己画）
    windowOpacity 淡出                  → 仍由这里的 `QPropertyAnimation(window, b"opacity")` 驱动
    30ms 旋转定时器                      → QML 的 Timer（30ms / +5°，数值逐项对齐）

**为什么是 `QQmlEngine` + `QQmlComponent` 而不是 `QQuickView`**：根元素是 `Window`
（窗口语义在 QML 里声明），而 `QQuickView` 的根必须是 `Item`；`QQmlComponent`
还能直接给出 `errors()` 文本，兜底分支要靠它写日志 —— `QQmlApplicationEngine.load()`
失败时只有一句 stderr，拿不到结构化错误。
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QWidget

from core.logger import log
from ui_qml.bridge import CONTEXT_NAME, theme_singleton
from ui_qml.icon_provider import PROVIDER_ID, PhosphorIconProvider
from ui_qml.theme import registry as theme

__all__ = ["SplashBridge", "SplashScreen"]

_SPLASH_QML = "shell/Splash.qml"

# QML 文件根目录。**故意不从 `ui_qml.host` 取它的 `QML_ROOT`**：那会连带 import
# `QtQuickWidgets`（宿主控件那一套），实测在启动最早那一刻白花 ~50ms 在首帧上
# （首帧时间是本批的判据之一，见计划 7.2）。
_QML_ROOT = Path(__file__).resolve().parent / "qml"

#: 步骤状态：检查中 / 已就绪 / 未就绪（QML 侧按这三个值选图标与颜色）
_STATE_CHECKING = "checking"
_STATE_READY = "ready"
_STATE_MISSING = "missing"

#: 首帧钩子用的连接方式：**排回 GUI 线程**（`frameSwapped` 是渲染线程发的，
#: 在那边动 QML 就是跨线程违规）+ **只跑一次**（它每帧都发）。
#: PySide6 的 `ConnectionType` 不是 flag 枚举，只能这样按位或出来。
_ONCE_ON_GUI_THREAD = Qt.ConnectionType(
    Qt.ConnectionType.QueuedConnection.value | Qt.ConnectionType.SingleShotConnection.value
)


class SplashBridge(QObject):
    """QML 启动画面的桥：步骤列表 + 阶段文案 + 提示行 + 进度。

    进度由 Python 侧定时器推进（与旧实现同一套节奏），QML 只读 —— 不让 QML 自己存一份，
    否则「显示 100% 了但收尾回调还没跑」这种两套状态迟早对不上。
    """

    stepsChanged = Signal()
    stageChanged = Signal()
    messageChanged = Signal()
    progressChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # 步骤列表先空着 —— 由 `load_steps()` 在 splash 显示之后填（它是这条启动路径上
        # 最大的一笔同步开销，见该方法的说明）。空列表下 QML 只是不画步骤网格。
        self._steps: list[dict] = []
        self._stage = "正在检查数据就绪状态..."
        self._message = ""
        self._progress = 0

    # ── QML 读 ────────────────────────────────────────────────

    steps = Property(list, lambda self: self._steps, notify=stepsChanged)
    stage = Property(str, lambda self: self._stage, notify=stageChanged)
    message = Property(str, lambda self: self._message, notify=messageChanged)
    progress = Property(int, lambda self: self._progress, notify=progressChanged)

    # ── 步骤表（延迟到 splash 显示之后加载）────────────────────

    def load_steps(self) -> None:
        """拉进 `services.init_service.STEPS`（首次 import 实测约 120ms）。

        **故意不在 `__init__` 里做**：它跟首帧的渲染栈初始化（Qt Quick + RHI，
        一次性约 250ms）在抢同一个线程 —— GUI 线程多做一点，首帧就晚一点。
        由 `SplashScreen.show()` 排到首帧之后再叫这里（实测省下约 180ms）。

        步骤进来后靠 **`stepsChanged`** 让 QML 重建 Repeater：走的是常规的 notify 绑定，
        不依赖「事后补 context property 会不会重算」这种看求值时机的事。
        """
        if self._steps:
            return
        from services.init_service import STEPS

        self._steps = [{"key": s.key, "name": s.name, "state": _STATE_CHECKING} for s in STEPS]
        self.stepsChanged.emit()

    # ── QML 写（camelCase：QML 侧的命名，见 theme_bridge 的说明）──

    @Slot(str)
    def setStage(self, msg: str) -> None:
        self._stage = str(msg)
        self.stageChanged.emit()

    @Slot(str, str, bool)
    def setComponent(self, key: str, name: str, ready: bool) -> None:
        """单个数据步骤的状态（进度统一由收尾动画驱动，不在这里动）。"""
        if not self._steps:
            # 极罕见：信号抢在 `show()`（它会 load_steps）之前到。宁可在这里补一次，
            # 也不要静默丢掉一个步骤 —— 那正是一次「检查完了但界面还写着检查中」。
            self.load_steps()
        if not any(s["key"] == key for s in self._steps):
            return  # 未知 key 忽略（旧实现是 `self._icon_rows.get(key)` 拿到 None 就跳过）
        state = _STATE_READY if ready else _STATE_MISSING
        # **重建整个列表**再发信号：就地改 dict 的话 QML 拿到的还是同一个对象，
        # Repeater 的代理不会重建（改完「图标不变」这种静默失效）。
        self._steps = [{**s, "state": state} if s["key"] == key else s for s in self._steps]
        self.stepsChanged.emit()
        self.set_message(f"{name}：{'就绪' if ready else '未就绪'}")

    # ── Python 侧驱动（QML 不直接调）────────────────────────────

    def set_progress(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        if value == self._progress:
            return
        self._progress = value
        self.progressChanged.emit()

    def set_message(self, text: str) -> None:
        text = str(text)
        if text == self._message:
            return
        self._message = text
        self.messageChanged.emit()


class _FallbackSplash(QWidget):
    """QML 加载失败时的最小兜底窗口（自绘圆角面板 + 百分比 + 阶段文案）。

    存在的理由只有一个：**启动时不能什么都不显示**。它不追求还原视觉，
    只保证「进程起来了、正在检查数据」这件事看得见。
    """

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(360, 470)
        self._stage = "正在检查数据就绪状态..."
        self._message = ""
        self._progress = 0

    # 与桥同形的最小接口（SplashScreen 两条路径共用一套调用）

    def set_stage(self, text: str) -> None:
        self._stage = str(text)
        self.update()

    def set_message(self, text: str) -> None:
        self._message = str(text)
        self.update()

    def set_progress(self, value: int) -> None:
        self._progress = max(0, min(100, int(value)))
        self.update()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(theme.BG_SURFACE))
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawRoundedRect(rect, 14, 14)

        font = painter.font()
        font.setPointSize(30)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_BRIGHT))
        painter.drawText(
            self.rect().adjusted(0, 90, 0, 0),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            f"{self._progress}%",
        )

        font.setPointSize(11)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_SECONDARY))
        flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
        painter.drawText(self.rect().adjusted(24, 300, -24, 0), flags, self._stage)
        painter.drawText(self.rect().adjusted(24, 420, -24, 0), flags, self._message)


class SplashScreen(QObject):
    """启动画面：显示、状态更新、完成动画（对外接口与旧 QWidget 版逐字一致）。

    **必须是 QObject**：`Main.py` 把 `StartupCheckWorker`（QThread）的信号直接连到
    `set_stage` / `set_component` 上，而 PySide 对**普通 Python 可调用对象**一律用
    DirectConnection —— 槽会在工作线程里跑，去碰 QML 对象就是跨线程违规
    （与 `Main.py` 里那个 `_StartupHandler` 注释讲的是同一件事）。
    绑定到 QObject 的方法才会按接收者线程排队投递到 GUI 线程。
    """

    def __init__(self, min_ms: int = 600, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._min_ms = min_ms
        self._shown_at: float = 0.0
        self._on_done: Callable[[], None] = lambda: None
        self._progress = 0
        self._fill_timer: QTimer | None = None
        self._fade: QPropertyAnimation | None = None

        self._engine: QQmlEngine | None = None
        self._component: QQmlComponent | None = None
        self._icon_provider: PhosphorIconProvider | None = None
        self._bridge: SplashBridge | None = None
        self._fallback: _FallbackSplash | None = None
        self._window: QWidget | QQuickWindow | None = None

        try:
            self._build_qml()
        except Exception as exc:
            # 兜底。**必须打 stderr**：此刻 qInstallMessageHandler 还没装，日志 handler
            # 也可能还没落地，出问题时用户与开发者都得有一条能看见的线索。
            print(f"[启动画面] QML 加载失败，退回最小兜底窗口：{exc}", file=sys.stderr, flush=True)
            log.exception("QML 启动画面加载失败，退回最小兜底窗口")
            self._teardown_qml()
            self._fallback = _FallbackSplash()
            self._window = self._fallback

    # ── 构建 ─────────────────────────────────────────────────

    def _build_qml(self) -> None:
        engine = QQmlEngine()
        self._engine = engine
        self._bridge = SplashBridge()

        ctx = engine.rootContext()
        # QML 控件样式必须与生产一致（见 Main.py 的同名调用）
        ctx.setContextProperty(CONTEXT_NAME, theme_singleton())
        ctx.setContextProperty("splash", self._bridge)

        # Phosphor 图标（步骤状态图标）：引擎接管 provider 的所有权
        self._icon_provider = PhosphorIconProvider()
        engine.addImageProvider(PROVIDER_ID, self._icon_provider)

        path = _QML_ROOT / _SPLASH_QML
        component = QQmlComponent(engine)
        self._component = component
        component.setData(path.read_bytes(), QUrl.fromLocalFile(str(path)))
        if component.isError():
            raise RuntimeError("; ".join(e.toString() for e in component.errors()))

        window = component.create(ctx)
        if not isinstance(window, QQuickWindow):
            errors = "; ".join(e.toString() for e in component.errors())
            raise RuntimeError(f"{_SPLASH_QML} 没给出窗口（根元素不是 Window）：{window!r} {errors}")
        self._window = window

    def _teardown_qml(self) -> None:
        """丢掉 QML 这一侧（**只能排到下一个事件循环调**，见 `close()`）。"""
        engine = self._engine
        self._engine = None
        self._component = None
        self._icon_provider = None
        self._bridge = None
        if isinstance(self._window, QQuickWindow):
            self._window = None
        if engine is not None:
            engine.deleteLater()

    # ── 生命周期（Main.py 调用）───────────────────────────────

    def show(self) -> None:
        """显示 splash，把步骤表的加载排到**首帧之后**。

        实测（本机，同一脚本内 A/B，各 4 轮）：步骤表若在这之前加载，进程启动到
        splash 出画是 538~614ms；挪到首帧之后是 381~408ms。差额的来源是渲染线程的
        首次 sync 要等 GUI 线程回到事件循环 —— GUI 线程在 `show()` 之后接着干任何活，
        都会原样推迟首帧。所以这里**不在 show() 里同步加载**，而是等 `frameSwapped`
        （渲染线程发的，必须排回 GUI 线程再动 QML）。
        """
        window = self._window
        if window is not None:
            window.show()
        self._shown_at = time.monotonic()
        if self._bridge is None:
            return
        if isinstance(window, QQuickWindow):
            window.frameSwapped.connect(self._on_first_frame, _ONCE_ON_GUI_THREAD)
        else:
            self._bridge.load_steps()  # 兜底窗口没有渲染线程，直接加载

    def _on_first_frame(self) -> None:
        """首帧已出画 → 这时再拉步骤表（见 `show()`）。"""
        if self._bridge is not None:
            self._bridge.load_steps()

    def close(self) -> None:
        """收尾：藏窗口，然后把 QML 引擎排到下一拍拆掉。

        **不能就地拆**：`close()` 是从淡出动画的 `finished` 回调里调进来的，
        而那个动画的目标正是引擎拥有的窗口 —— 在信号处理器里销毁自己所属的对象，
        Qt 会报 CRITICAL（与外壳「关闭要延迟一拍」同因）。
        """
        if self._window is not None:
            self._window.hide()
        if self._engine is not None:
            QTimer.singleShot(0, self._teardown_qml)

    # ── 状态更新（由 StartupCheckWorker 信号驱动）───────────────

    def set_stage(self, msg: str) -> None:
        if self._bridge is not None:
            self._bridge.setStage(str(msg))
        elif self._fallback is not None:
            self._fallback.set_stage(str(msg))

    def set_component(self, key: str, name: str, ready: bool) -> None:
        if self._bridge is not None:
            self._bridge.setComponent(key, name, bool(ready))
        elif self._fallback is not None:
            self._fallback.set_message(f"{name}：{'就绪' if ready else '未就绪'}")

    def complete(self, on_done: Callable[[], None]) -> None:
        """检查完成：保证最小显示时间 → 进度 0→100 快速动画 → 短暂停留 → 淡出。

        检查阶段进度条不增长（避免被 worker 子线程 GIL 抢占拖住造成"卡住"观感），
        检查完成后统一播放收尾动画。节奏与旧 QWidget 版逐项一致。
        """
        self._on_done = on_done if callable(on_done) else (lambda: None)
        elapsed_ms = (time.monotonic() - self._shown_at) * 1000
        wait = max(0, int(self._min_ms - elapsed_ms))
        QTimer.singleShot(wait, self._start_fill)

    # ── 收尾动画 ─────────────────────────────────────────────

    def _start_fill(self) -> None:
        self._progress = 0
        self._set_progress(0)
        self._fill_timer = QTimer(self)
        self._fill_timer.timeout.connect(self._fill_step)
        self._fill_timer.start(10)

    def _fill_step(self) -> None:
        if self._progress < 100:
            self._progress += 1
            self._set_progress(self._progress)
            return
        if self._fill_timer is not None:
            self._fill_timer.stop()
            self._fill_timer = None
        self._set_message("就绪检查完成")
        QTimer.singleShot(200, self._fade_out)

    def _fade_out(self) -> None:
        window = self._window
        if window is None:
            self._finish()
            return
        anim = QPropertyAnimation(window, b"opacity", self)
        anim.setDuration(300)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self._finish)
        self._fade = anim
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _finish(self) -> None:
        self._fade = None
        if self._window is not None:
            self._window.hide()
        on_done, self._on_done = self._on_done, lambda: None
        on_done()

    # ── 内部：把进度/提示送进当前这套显示（QML 或兜底）──────────

    def _set_progress(self, value: int) -> None:
        if self._bridge is not None:
            self._bridge.set_progress(value)
        elif self._fallback is not None:
            self._fallback.set_progress(value)

    def _set_message(self, text: str) -> None:
        if self._bridge is not None:
            self._bridge.set_message(text)
        elif self._fallback is not None:
            self._fallback.set_message(text)
