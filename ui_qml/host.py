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
            self.load_failed.emit(errors)

    # ── 公开 API ──

    @property
    def qml_file(self) -> str:
        return self._qml_file

    def ok(self) -> bool:
        """QML 是否加载成功（调用方据此决定是否回退到 Widgets 版）。"""
        return self.status() == QQuickWidget.Status.Ready
