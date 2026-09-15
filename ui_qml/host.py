"""`PageHost` —— 把 QML 页面嵌进现有 Widgets 外壳的宿主控件。

迁移期（阶段 0–4）每个 QML 页面都装在一个 `QQuickWidget` 里，放进
`QStackedWidget#content_stack` 对应的位置；阶段 5 再整体换成 `QQuickWindow`。

**关键约束（H1）**：必须 `setClearColor(transparent)`。
`QQuickWidget` 默认把 QML 渲染到不透明的 FBO，会整块盖住 DWM 毛玻璃
（实测：默认 clear color 下空区 alpha=255；设为 transparent 后 alpha=0，Mica 才能透出）。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QWidget

from core.logger import log
from ui_qml.bridge import CONTEXT_NAME, theme_singleton
from ui_qml.icon_provider import PROVIDER_ID, PhosphorIconProvider

# QML 文件根目录：ui_qml/qml/
QML_ROOT = Path(__file__).resolve().parent / "qml"


class PageHost(QQuickWidget):
    """承载单个 QML 页面的宿主，加载失败时发 `load_failed` 供调用方回退。"""

    load_failed = Signal(str)

    def __init__(
        self,
        qml_file: str,
        *,
        context: dict[str, QObject] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._qml_file = qml_file
        # H1：透明清屏，否则 QML 表面会盖住窗口级 Mica/Acrylic
        self.setClearColor(Qt.GlobalColor.transparent)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Phosphor 图标供应器：QML 侧 `image://phosphor/<name>?c=<色>&s=<px>` 取染色 SVG。
        # 每个宿主一个（QQuickWidget 各自持有 QQmlEngine；addImageProvider 会转移所有权，
        # 同一个 provider 注册到两个引擎会在销毁时二次释放）。
        self._icon_provider = PhosphorIconProvider()
        engine = self.engine()
        if engine is not None:
            engine.addImageProvider(PROVIDER_ID, self._icon_provider)

        # Theme 单例对所有 QML 页面恒定可用
        self.rootContext().setContextProperty(CONTEXT_NAME, theme_singleton())
        # 注入的对象必须由宿主持有强引用：QML 的 context 不接管所有权，
        # 只传临时对象会被 GC 回收，表现为 contextProperty() 查不到（静默失效）。
        self._context_objects: dict[str, QObject] = {}
        for name, obj in (context or {}).items():
            self.rootContext().setContextProperty(name, obj)
            self._context_objects[name] = obj

        self.statusChanged.connect(self._on_status_changed)
        self.setSource(QUrl.fromLocalFile(str(self._resolve(qml_file))))

    # ── 内部 ──

    @staticmethod
    def _resolve(qml_file: str) -> Path:
        path = Path(qml_file)
        return path if path.is_absolute() else QML_ROOT / path

    def _on_status_changed(self, status: QQuickWidget.Status) -> None:
        if status == QQuickWidget.Status.Error:
            errors = "; ".join(str(err).strip() for err in self.errors())
            log.error("QML 页面加载失败 %s: %s", self._qml_file, errors)
            self._show_load_error(errors)
            self.load_failed.emit(errors)

    def _show_load_error(self, errors: str) -> None:
        """加载失败时在宿主上盖一块**看得见**的错误面。

        原先只写日志 + 发信号，而宿主本身没有回退能力：六个页面的 Widgets 回退是注册表在
        `build_page` 里做的，对话框根本没有回退，工业页那条回退路径又会加载同一份 QML。
        结果是「一块空白，什么都不说」，用户只会觉得软件坏了、也不知道去看日志。

        这里直接把它显示出来，**任何宿主都受益**（页面与对话框走的是同一个类）。
        """
        from PySide6.QtWidgets import QLabel

        from ui_qml.theme import registry as theme

        label = QLabel(f"QML 加载失败：{self._qml_file}\n\n{errors}\n\n（详见日志）", self)
        label.setObjectName("qml_load_error")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"background: {theme.BG_DARK}; color: {theme.ACCENT_RED}; padding: 16px;")
        label.setGeometry(self.rect())
        label.show()
        label.raise_()
        self._error_label = label

    def resizeEvent(self, event: object) -> None:
        """错误面跟着宿主一起缩放（它是自绘覆盖层，不参与布局）。"""
        super().resizeEvent(event)  # type: ignore[arg-type]
        label = getattr(self, "_error_label", None)
        if label is not None:
            label.setGeometry(self.rect())

    # ── 公开 API ──

    @property
    def qml_file(self) -> str:
        return self._qml_file

    def ok(self) -> bool:
        """QML 是否加载成功（调用方据此决定是否回退到 Widgets 版）。"""
        return self.status() == QQuickWidget.Status.Ready
