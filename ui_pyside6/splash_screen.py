"""炫酷启动界面 — 圆形渐变 + 旋转加载弧 + 数据就绪状态。

视觉参考 Qt_CircularSplashScreen（Wanderson-Magalhaes 经典方案）：
- 上半：QRadialGradient 圆形渐变背景 + 旋转进度弧 + 中央进度百分比
- 下半：10 个数据步骤紧凑网格（✓/✗ 图标 + 中文名）
进度条反映真实检查进度，全部检查完成后平滑走满 → 短暂停留 → 淡出。
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

import ui_pyside6.icons as icons
import ui_pyside6.theme as theme

_ICON_READY = "check"
_ICON_MISSING = "close"
_ICON_CHECKING = "circle"


class _Loader(QWidget):
    """圆形渐变加载指示器：渐变圆 + 旋转弧 + 中央进度百分比。"""

    def __init__(self, size: int = 230, parent=None):
        super().__init__(parent)
        self._progress = 0
        self._angle = 0
        self.setFixedSize(size, size)

    def set_progress(self, value: int):
        self._progress = max(0, min(100, value))
        self.update()

    def tick(self):
        self._angle = (self._angle + 5) % 360
        self.update()

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        radius = min(self.width(), self.height()) / 2 - 4

        # 圆形渐变背景
        grad = QRadialGradient(center, radius)
        grad.setColorAt(0.0, QColor(theme.BG_SURFACE_LIGHT))
        grad.setColorAt(0.75, QColor(theme.BG_DARK))
        grad.setColorAt(1.0, QColor(theme.BG_SURFACE))
        painter.setBrush(grad)
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawEllipse(center, radius, radius)

        # 内圈基准环
        ring_r = radius * 0.78
        ring = QRectF(center.x() - ring_r, center.y() - ring_r, ring_r * 2, ring_r * 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(theme.BG_SURFACE_LIGHT), 2))
        painter.drawEllipse(ring)

        # 旋转进度弧（90° 高亮弧，绕中心旋转）
        painter.save()
        painter.translate(center)
        painter.rotate(self._angle)
        arc_r = radius * 0.78
        arc = QRectF(-arc_r, -arc_r, arc_r * 2, arc_r * 2)
        pen = QPen(QColor(theme.PRIMARY), 6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(arc, 0, 100 * 16)
        painter.restore()

        # 中央进度百分比
        font = QFont()
        font.setPointSize(30)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_BRIGHT))
        painter.drawText(
            QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._progress}%",
        )


class SplashScreen(QWidget):
    """无边框炫酷启动界面，由 StartupCheckWorker 信号驱动状态更新。"""

    def __init__(self, min_ms: int = 600, parent=None):
        super().__init__(parent)
        # 延迟 import：避免显示首帧前同步加载 init_service（首次 import 开销大）
        from services.init_service import STEPS

        self._steps = list(STEPS)
        self._min_ms = min_ms
        self._shown_at: float = 0.0
        self._icon_rows: dict[str, QLabel] = {}
        self._on_done = lambda: None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(360, 470)

        self._loader = _Loader()
        self._build_ui()
        self._init_steps()

        # 旋转弧动画
        self._rot_timer = QTimer(self)
        self._rot_timer.timeout.connect(self._loader.tick)
        self._rot_timer.start(30)

    # ── UI 构建 ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 12, 26, 16)
        layout.setSpacing(6)

        layout.addWidget(self._loader, 0, Qt.AlignmentFlag.AlignHCenter)

        self._stage_label = QLabel("正在检查数据就绪状态...")
        self._stage_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._stage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._stage_label)

        layout.addSpacing(6)

        # 步骤 2 列紧凑网格
        grid = QGridLayout()
        grid.setSpacing(4)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(3)
        for i, step in enumerate(self._steps):
            icon = QLabel()
            icon.setFixedWidth(14)
            icon.setFixedHeight(14)
            self._set_icon_state(icon, _ICON_CHECKING, theme.PRIMARY)
            name = QLabel(step.name)
            name.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 11px;")
            row, col = divmod(i, 2)
            grid.addWidget(icon, row, col * 2)
            grid.addWidget(name, row, col * 2 + 1)
            self._icon_rows[step.key] = icon
        layout.addLayout(grid)

        layout.addStretch()

        self._msg_label = QLabel("")
        self._msg_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 10px;")
        self._msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._msg_label)

    @staticmethod
    def _set_icon_state(label: QLabel, key: str, color: str):
        """步骤状态图标（Phosphor，随主题色）"""
        label.setPixmap(icons.themed_icon(key, 14, color).pixmap(14, 14))

    def _init_steps(self):
        for step in self._steps:
            row = self._icon_rows[step.key]
            self._set_icon_state(row, _ICON_CHECKING, theme.PRIMARY)

    # ── 窗口背景（半透明圆角） ──

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(theme.BG_SURFACE))
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawRoundedRect(rect, 14, 14)

    # ── 状态更新（由 worker 信号驱动） ──

    def set_stage(self, msg: str):
        self._stage_label.setText(msg)

    def set_component(self, key: str, name: str, ready: bool):
        """更新单个数据步骤状态（进度统一由 complete 动画驱动）。"""
        icon = self._icon_rows.get(key)
        if icon:
            if ready:
                self._set_icon_state(icon, _ICON_READY, theme.ACCENT_GREEN)
            else:
                self._set_icon_state(icon, _ICON_MISSING, theme.ACCENT_RED)
        self._msg_label.setText(f"{name}：{'就绪' if ready else '未就绪'}")

    # ── 生命周期 ──

    def showEvent(self, ev):
        super().showEvent(ev)
        self._shown_at = time.monotonic()

    def complete(self, on_done):
        """检查完成：保证最小显示时间 → 进度 0→100 快速动画 → 短暂停留 → 淡出。

        检查阶段进度条不增长（避免被 worker 子线程 GIL 抢占拖住造成"卡住"观感），
        检查完成后统一播放收尾动画。
        """
        self._on_done = on_done
        elapsed_ms = (time.monotonic() - self._shown_at) * 1000
        wait = max(0, int(self._min_ms - elapsed_ms))
        QTimer.singleShot(wait, self._start_fill)

    def _start_fill(self):
        self._loader.set_progress(0)
        self._fill_timer = QTimer(self)
        self._fill_timer.timeout.connect(self._fill_step)
        self._fill_timer.start(10)

    def _fill_step(self):
        if self._loader._progress < 100:
            self._loader.set_progress(self._loader._progress + 1)
            return
        self._fill_timer.stop()
        self._msg_label.setText("就绪检查完成")
        QTimer.singleShot(200, self._fade_out)

    def _fade_out(self):
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(300)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: (self.hide(), self._on_done()))
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
