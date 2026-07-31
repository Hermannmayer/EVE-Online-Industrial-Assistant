"""
启动检查对话框 — 启动时先弹紧凑小窗检查数据，需要下载时自动展开

工作流:
  1. 小窗弹出，显示进度条 + 7 个状态点
  2. 后台检查数据就绪情况
  3. 全部就绪 → 自动关闭，回调启动主窗口
  4. 有缺失 → 自动展开为完整进度界面，开始下载
  5. 用户也可点"跳过"直接进主窗口
"""

import time
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from services.init_service import STEPS, InitStep, StepStatus, get_missing_steps, is_step_satisfied
from ui_pyside6.workers.init_workers import InitServiceWorker

# ── 常量 ──

_CHECK_SIZE = (380, 220)    # 紧凑模式尺寸
_EXPAND_SIZE = (620, 500)   # 展开模式尺寸


class _StepRow(QWidget):
    """步骤行 — 携带动态控件引用，供 _update_row_state 更新"""

    def __init__(self) -> None:
        super().__init__()
        self._icon: QLabel
        self._bar: QProgressBar
        self._msg: QLabel
        self._retry_btn: QPushButton


class StartupCheckDialog(QDialog):
    """启动检查对话框 — 精致紧凑 → 按需展开"""

    def __init__(self, on_ready: Callable[[], None] | None = None):
        super().__init__()
        self.setWindowTitle("EVE 商人助手")
        self.setFixedSize(*_CHECK_SIZE)
        self.setStyleSheet(f"background-color: {theme.BG_DARK};")

        self._on_ready = on_ready           # 检查/初始化完成后回调
        self._expanded = False               # 是否已展开
        self._start_time = time.time()
        self._worker: InitServiceWorker | None = None
        self._step_status: dict[str, StepStatus] = {}
        self._step_dots: dict[str, QLabel] = {}
        self._step_rows: dict[str, _StepRow] = {}
        self._timer: QTimer | None = None

        self._build_compact_ui()
        self._start_check()

    # ═══════════════════════════════════════
    #  UI — 紧凑模式
    # ═══════════════════════════════════════

    def _build_compact_ui(self):
        """构建紧凑检查界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(8)

        # ── 标题行 ──
        title_row = QHBoxLayout()
        icon = QLabel("⚡")
        icon.setStyleSheet(f"font-size: 20px; color: {theme.PRIMARY};")
        title_row.addWidget(icon)

        title = QLabel("EVE 商人助手")
        title.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 16px; font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        layout.addSpacing(4)

        # ── 进度条 ──
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {theme.BG_SURFACE};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {theme.PRIMARY};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(self._progress)

        # ── 状态文字 ──
        self._status_label = QLabel("正在准备...")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._status_label)

        layout.addSpacing(6)

        # ── 步骤状态点 (2×4 grid) ──
        dot_grid = QGridLayout()
        dot_grid.setSpacing(4)
        row, col = 0, 0
        for _, step in enumerate(STEPS):
            dot = QLabel("○")
            dot.setStyleSheet(f"font-size: 11px; color: {theme.TEXT_SECONDARY};")
            dot.setFixedWidth(80)
            self._step_dots[step.key] = dot
            dot_grid.addWidget(dot, row, col)
            col += 1
            if col >= 4:
                col = 0
                row += 1
        layout.addLayout(dot_grid)

        # ── 跳过按钮 ──
        layout.addStretch()
        skip_row = QHBoxLayout()
        skip_row.addStretch()
        self._skip_btn = QPushButton("跳过 → 进入主页面")
        self._skip_btn.setFlat(True)
        self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip_btn.setStyleSheet(f"""
            QPushButton {{
                color: {theme.TEXT_SECONDARY};
                font-size: 11px;
                border: none;
                padding: 4px 8px;
            }}
            QPushButton:hover {{ color: {theme.PRIMARY}; }}
        """)
        self._skip_btn.clicked.connect(self._on_skip)
        skip_row.addWidget(self._skip_btn)
        layout.addLayout(skip_row)

        # ── 展开模式组件（初始隐藏） ──
        self._expanded_container = QVBoxLayout()
        self._expanded_container.setContentsMargins(0, 0, 0, 0)
        self._expanded_container.setSpacing(4)
        layout.addLayout(self._expanded_container)

        self._step_rows_container = QVBoxLayout()
        self._step_rows_container.setSpacing(4)
        self._expanded_container.addLayout(self._step_rows_container)

        # 展开后的额外控件
        self._net_label = QLabel("")
        self._net_label.setStyleSheet(f"color: {theme.ACCENT_GREEN}; font-size: 11px;")
        self._expanded_container.addWidget(self._net_label)

        self._total_bar = QProgressBar()
        self._total_bar.setRange(0, len(STEPS))
        self._total_bar.setValue(0)
        self._total_bar.setTextVisible(True)
        self._total_bar.setFixedHeight(18)
        self._total_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {theme.BG_SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: 4px;
                text-align: center;
                color: {theme.TEXT_PRIMARY};
                font-size: 11px;
            }}
            QProgressBar::chunk {{
                background-color: {theme.PRIMARY};
                border-radius: 3px;
            }}
        """)
        self._expanded_container.addWidget(self._total_bar)

        self._eta_label = QLabel("")
        self._eta_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._expanded_container.addWidget(self._eta_label)

        # 展开后的按钮
        btn_row = QHBoxLayout()
        self._retry_all_btn = QPushButton("全部重试")
        self._retry_all_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {theme.ACCENT_ORANGE}; color: #fff; border: none;
                border-radius: 4px; padding: 4px 14px; font-size: 12px; }}
            QPushButton:hover {{ background-color: {theme.BG_HOVER}; }}
        """)
        self._retry_all_btn.clicked.connect(self._on_retry_all)
        self._retry_all_btn.hide()
        btn_row.addWidget(self._retry_all_btn)

        btn_row.addStretch()

        self._bg_btn = QPushButton("后台运行")
        self._bg_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 4px 14px; font-size: 12px; }}
            QPushButton:hover {{ background-color: {theme.BG_HOVER}; }}
        """)
        self._bg_btn.clicked.connect(self._on_minimize)
        btn_row.addWidget(self._bg_btn)

        self._expanded_container.addLayout(btn_row)

        # 展开模式整体隐藏
        for i in range(self._expanded_container.count()):
            item = self._expanded_container.itemAt(i)
            if item and item.widget():
                item.widget().hide()
            elif item and item.layout():
                self._hide_layout(item.layout())

        self._expanded_container.parentWidget().layout().update()

    def _hide_layout(self, layout):
        """递归隐藏 layout 中的所有 widget"""
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                item.widget().hide()
            elif item and item.layout():
                self._hide_layout(item.layout())

    def _show_layout(self, layout):
        """递归显示 layout 中的所有 widget"""
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                item.widget().show()
            elif item and item.layout():
                self._show_layout(item.layout())

    # ═══════════════════════════════════════
    #  检查流程
    # ═══════════════════════════════════════

    def _start_check(self):
        """启动后台快速检查（仅 is_step_satisfied 轮询，不执行实际初始化）"""

        self._worker = None
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._poll_check)
        self._check_timer.start(100)  # 100ms 间隔，快速检测

    def _poll_check(self):
        """轮询检查进度更新状态点"""
        for step in STEPS:
            done = is_step_satisfied(step.key)
            if done:
                self._step_status[step.key] = StepStatus.COMPLETED
                self._update_dot(step.key, StepStatus.COMPLETED)
            else:
                self._step_status[step.key] = StepStatus.PENDING

        done = sum(1 for s in STEPS if self._step_status.get(s.key) == StepStatus.COMPLETED)
        total = len(STEPS)
        pct = int(done / total * 100)
        self._progress.setValue(pct)
        self._status_label.setText(f"检查中  {done}/{total}")

        if done == total:
            self._check_timer.stop()
            # 直接关闭（兜底：不等 worker 信号，已在 UI 线程检测到就绪）
            self._on_check_done(True, "全部就绪")

    def _on_step_check(self, key: str, success: bool, message: str):
        """检查阶段步骤完成"""
        status = StepStatus.COMPLETED if success else StepStatus.FAILED
        self._step_status[key] = status
        self._update_dot(key, status)
        # 检查失败→不阻塞，继续检查其他

    def _on_check_done(self, success: bool, summary: str):
        """所有步骤检查完成（可被 timer 和 worker 信号多次触发，幂等）"""
        if getattr(self, '_check_done_flag', False):
            return
        self._check_done_flag = True

        missing = get_missing_steps()
        if not missing:
            # ✅ 全部就绪 → 延迟 300ms 给用户看清状态 → 关闭
            self._status_label.setText("✓ 全部就绪")
            self._progress.setValue(100)
            if self._check_timer:
                self._check_timer.stop()
            QTimer.singleShot(300, self._on_ready_close)
        else:
            # ❌ 有缺失 → 展开为下载界面
            self._status_label.setText(f"需要下载 {len(missing)} 个组件")
            self._expand_and_download()

    # ═══════════════════════════════════════
    #  展开 → 下载
    # ═══════════════════════════════════════

    def _expand_and_download(self):
        """展开窗口并开始下载"""
        if self._expanded:
            return
        self._expanded = True

        # 构建展开后的步骤行
        for step in STEPS:
            row = self._build_step_row(step)
            self._step_rows[step.key] = row
            self._step_rows_container.addWidget(row)

        # 显示展开内容
        self._show_layout(self._expanded_container)

        # 改变窗口大小
        self.setFixedSize(*_EXPAND_SIZE)

        # 更新已有就绪步骤状态
        for step in STEPS:
            if self._step_status.get(step.key) == StepStatus.COMPLETED:
                self._update_row_state(step.key, StepStatus.COMPLETED, "数据已就绪")

        # 启动初始化
        self._skip_btn.hide()
        self._start_init()

    def _build_step_row(self, step: InitStep) -> _StepRow:
        """构建单个步骤行"""
        row = _StepRow()
        row.setStyleSheet(f"""
            QWidget {{
                background-color: {theme.BG_SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: 4px;
            }}
        """)
        row.setFixedHeight(36)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(8)

        icon = QLabel("○")
        icon.setStyleSheet(f"font-size: 12px; color: {theme.TEXT_SECONDARY};")
        icon.setFixedWidth(20)
        layout.addWidget(icon)
        row._icon = icon

        name = QLabel(step.name)
        name.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
        layout.addWidget(name)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedSize(100, 10)
        bar.setStyleSheet(f"""
            QProgressBar {{ background-color: {theme.BG_SURFACE_LIGHT}; border: none;
                border-radius: 3px; }}
            QProgressBar::chunk {{ background-color: {theme.PRIMARY}; border-radius: 3px; }}
        """)
        bar.hide()
        layout.addWidget(bar)
        row._bar = bar

        msg = QLabel("")
        msg.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(msg, 1)
        row._msg = msg

        retry_btn = QPushButton("重试")
        retry_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {theme.ACCENT_ORANGE}; color: #fff;
                border: none; border-radius: 3px; padding: 2px 10px; font-size: 11px; }}
        """)
        retry_btn.hide()
        retry_btn.clicked.connect(lambda checked, k=step.key: self._on_retry(k))
        layout.addWidget(retry_btn)
        row._retry_btn = retry_btn

        return row

    def _update_row_state(self, key: str, status: StepStatus, message: str = "", percent: int = 0):
        """更新步骤行状态"""
        row = self._step_rows.get(key)
        if not row:
            return

        icon_map = {
            StepStatus.PENDING: "○", StepStatus.RUNNING: "◉",
            StepStatus.COMPLETED: "●", StepStatus.FAILED: "●",
            StepStatus.SKIPPED: "–",
        }
        color_map = {
            StepStatus.PENDING: theme.TEXT_SECONDARY, StepStatus.RUNNING: theme.PRIMARY,
            StepStatus.COMPLETED: theme.ACCENT_GREEN, StepStatus.FAILED: theme.ACCENT_RED,
            StepStatus.SKIPPED: theme.TEXT_SECONDARY,
        }
        row._icon.setText(icon_map.get(status, "○"))
        row._icon.setStyleSheet(f"font-size: 12px; color: {color_map.get(status, theme.TEXT_SECONDARY)};")
        row._msg.setText(message)
        row._bar.setVisible(status == StepStatus.RUNNING)
        if status == StepStatus.RUNNING:
            row._bar.setValue(percent)
        row._retry_btn.setVisible(status == StepStatus.FAILED)

    def _update_dot(self, key: str, status: StepStatus):
        """更新状态点"""
        dot = self._step_dots.get(key)
        if not dot:
            return
        step = next((s for s in STEPS if s.key == key), None)
        if not step:
            return

        symbols = {
            StepStatus.PENDING: "○", StepStatus.COMPLETED: "●",
            StepStatus.FAILED: "●", StepStatus.RUNNING: "◉",
        }
        colors = {
            StepStatus.PENDING: theme.TEXT_SECONDARY, StepStatus.COMPLETED: theme.ACCENT_GREEN,
            StepStatus.FAILED: theme.ACCENT_RED, StepStatus.RUNNING: theme.PRIMARY,
        }
        dot.setText(f"{symbols.get(status, '○')} {step.name}")
        dot.setStyleSheet(f"font-size: 11px; color: {colors.get(status, theme.TEXT_SECONDARY)};")

    # ═══════════════════════════════════════
    #  初始化流程
    # ═══════════════════════════════════════

    def _start_init(self):
        """开始自动初始化"""
        self._start_time = time.time()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_eta)
        self._timer.start(1000)

        missing = [s.key for s in get_missing_steps()]
        if not missing:
            self._on_all_done(True, "全部就绪")
            return

        self._worker = InitServiceWorker(step_keys=missing)
        self._worker.step_progress.connect(self._on_step_progress)
        self._worker.step_completed.connect(self._on_step_completed)
        self._worker.all_completed.connect(self._on_all_done)
        self._worker.network_status.connect(self._on_network)
        self._worker.start()

    def _on_step_progress(self, key: str, percent: int, message: str):
        """步骤进度"""
        self._update_row_state(key, StepStatus.RUNNING, message, percent)
        self._update_dot(key, StepStatus.RUNNING)

    def _on_step_completed(self, key: str, success: bool, message: str):
        """步骤完成"""
        status = StepStatus.COMPLETED if success else StepStatus.FAILED
        self._update_row_state(key, status, message)
        self._update_dot(key, status)

        # 更新总进度
        completed_count = sum(
            1 for s in STEPS
            if self._step_rows.get(s.key)
            and self._step_rows[s.key]._icon.text() == "●"
        )
        self._total_bar.setValue(completed_count)
        self._total_bar.setFormat(f"{completed_count}/{len(STEPS)}")

        if not success:
            self._retry_all_btn.show()

    def _on_network(self, ok: bool, message: str):
        """网络状态"""
        if ok:
            self._net_label.setText(f"🌐 {message}")

    def _on_all_done(self, success: bool, summary: str):
        """全部完成"""
        if self._timer:
            self._timer.stop()

        self._total_bar.setValue(len(STEPS))
        self._total_bar.setFormat(summary)
        self._eta_label.setText(f"🕐 已用 {self._elapsed_str()}")

        if success:
            self._status_label.setText("🎉 全部就绪")
            # 延迟关闭启动主窗口
            QTimer.singleShot(500, self._on_ready_close)
        else:
            self._retry_all_btn.show()
            self._status_label.setText("部分步骤未完成，可在设置中重试")

    def _on_retry(self, key: str):
        """重试单个步骤"""
        if self._worker:
            row = self._step_rows.get(key)
            if row:
                self._update_row_state(key, StepStatus.PENDING)
            self._worker.retry(key)

    def _on_retry_all(self):
        """全部重试"""
        self._retry_all_btn.hide()
        self._start_init()

    def _on_skip(self):
        """跳过 → 直接进入主窗口"""
        if self._worker:
            self._worker.cancel()
        self._on_ready_close()

    def _on_minimize(self):
        """后台运行 → 隐藏到托盘"""
        self.hide()
        # 完成后仍会触发 on_ready_close

    # ═══════════════════════════════════════
    #  生命周期
    # ═══════════════════════════════════════

    def _on_ready_close(self):
        """关闭对话框，通知主窗口启动"""
        if self._timer:
            self._timer.stop()
        self.accept()

    def closeEvent(self, event: QCloseEvent):
        """阻止直接关闭（防止用户误关导致无法初始化）"""
        if self._expanded and self._worker and self._worker.isRunning():
            self.hide()  # 后台运行
            event.ignore()
        else:
            self.accept()

    def reject(self):
        """ESC = 最小化到后台"""
        if self._expanded and self._worker and self._worker.isRunning():
            self.hide()
        else:
            self.accept()

    def _update_eta(self):
        """更新 ETA"""
        elapsed = time.time() - self._start_time
        done = sum(1 for s in STEPS if self._step_status.get(s.key) == StepStatus.COMPLETED)
        total = len(STEPS)
        remaining = 0
        if done > 0 and elapsed > 5:
            rate = elapsed / done
            remaining = (total - done) * rate
        self._eta_label.setText(
            f"🕐 已用 {self._elapsed_str(elapsed)}"
            + (f"  ·  剩余约 {self._elapsed_str(remaining)}" if remaining > 0 else "")
        )

    @staticmethod
    def _elapsed_str(seconds: float | None = None) -> str:
        if seconds is None:
            seconds = 0
        m, s = divmod(int(seconds), 60)
        if m > 0:
            return f"{m}m{s}s"
        return f"{s}s"
