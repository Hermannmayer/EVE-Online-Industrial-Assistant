"""
数据初始化向导 — QThread 驱动版

特性：
- 每步进度条 + 状态图标（✅ ⏳ ❌ ⏸️）
- 失败步骤可重试，非关键步骤可跳过
- 网络连通性检查
- 已用时间 / 预计剩余时间
- 自动模式（启动时弹窗，不可关闭）

用法（用户手动）：
    wizard = InitWizard(parent)
    wizard.show()

用法（自动模式 — Main.py 启动时）：
    wizard = InitWizard(parent, auto_mode=True, on_done=callback)
    wizard.show()
"""

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
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

# ── 样式 ──

_BTN_STYLE = """
    QPushButton {{
        background-color: {bg};
        color: {fg};
        border: none;
        border-radius: 4px;
        padding: 4px 12px;
        font-size: 12px;
    }}
    QPushButton:hover {{ background-color: {hover}; }}
    QPushButton:disabled {{ background-color: {bg}; color: {disabled}; }}
"""

_STEP_ROW_STYLE = """
    QWidget#stepRow {{
        background-color: {surface};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 8px;
    }}
"""


def _btn_style(bg: str, fg: str = "#fff", hover: str | None = None, disabled: str = "#666") -> str:
    return _BTN_STYLE.format(bg=bg, fg=fg, hover=hover or bg, disabled=disabled)


class _StepRow(QWidget):
    """单个步骤行：状态图标 + 名称 + 进度 + 操作按钮"""

    retry_clicked = None  # set by parent
    skip_clicked = None

    def __init__(self, step: InitStep, parent=None):
        super().__init__(parent)
        self.setObjectName("stepRow")
        self.step = step
        self.setStyleSheet(
            _STEP_ROW_STYLE.format(
                surface=theme.BG_SURFACE,
                border=theme.BORDER,
            )
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        # 状态图标
        self.icon = QLabel("⏸️")
        self.icon.setFixedWidth(24)
        self.icon.setStyleSheet(f"font-size: 14px; color: {theme.TEXT_SECONDARY};")
        layout.addWidget(self.icon)

        # 名称 + 进度文本
        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        self.name_label = QLabel(step.name)
        self.name_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        info_col.addWidget(self.name_label)

        self.msg_label = QLabel("等待中" if step.critical else "可选")
        self.msg_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        info_col.addWidget(self.msg_label)

        layout.addLayout(info_col, 1)

        # 步骤级进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedSize(140, 16)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {theme.BG_SURFACE_LIGHT};
                border: 1px solid {theme.BORDER};
                border-radius: 3px;
                text-align: center;
                color: {theme.TEXT_SECONDARY};
                font-size: 10px;
            }}
            QProgressBar::chunk {{
                background-color: {theme.PRIMARY};
                border-radius: 2px;
            }}
        """)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # 重试按钮
        self.retry_btn = QPushButton("重试")
        self.retry_btn.setStyleSheet(_btn_style(theme.ACCENT_ORANGE))
        self.retry_btn.hide()
        layout.addWidget(self.retry_btn)

        # 跳过按钮
        self.skip_btn = QPushButton("跳过")
        self.skip_btn.setStyleSheet(_btn_style(theme.TEXT_SECONDARY))
        self.skip_btn.setVisible(not step.critical)
        layout.addWidget(self.skip_btn)

    def set_state(self, status: StepStatus, message: str = "", percent: int = 0):
        """更新步骤行状态"""
        icon_map = {
            StepStatus.PENDING: "⏸️",
            StepStatus.RUNNING: "⏳",
            StepStatus.COMPLETED: "✅",
            StepStatus.FAILED: "❌",
            StepStatus.SKIPPED: "⏭️",
            StepStatus.CANCELLED: "🚫",
        }
        color_map = {
            StepStatus.PENDING: theme.TEXT_SECONDARY,
            StepStatus.RUNNING: theme.PRIMARY,
            StepStatus.COMPLETED: theme.ACCENT_GREEN,
            StepStatus.FAILED: theme.ACCENT_RED,
            StepStatus.SKIPPED: theme.TEXT_SECONDARY,
            StepStatus.CANCELLED: theme.TEXT_SECONDARY,
        }

        self.icon.setText(icon_map.get(status, "⏸️"))
        self.icon.setStyleSheet(f"font-size: 14px; color: {color_map.get(status, theme.TEXT_SECONDARY)};")
        self.msg_label.setText(message)

        self.retry_btn.setVisible(status == StepStatus.FAILED)
        self.skip_btn.setVisible(status in (StepStatus.PENDING, StepStatus.FAILED) and not self.step.critical)
        self.progress_bar.setVisible(status == StepStatus.RUNNING)
        if status == StepStatus.RUNNING:
            self.progress_bar.setValue(percent)

    def reset(self):
        """重置为等待状态"""
        self.set_state(StepStatus.PENDING)


class InitWizard(QDialog):
    """数据初始化向导 — 重构版（QThread 驱动）"""

    def __init__(self, parent=None, on_done=None, auto_mode: bool = False):
        super().__init__(parent)
        self.setWindowTitle("数据初始化")
        self.setMinimumSize(620, 520)
        self.setStyleSheet(f"background-color: {theme.BG_DARK};")

        self._auto_mode = auto_mode
        self._on_done_callback = on_done
        self._start_time: float | None = None
        self._elapsed_timer: QTimer | None = None
        self._worker: InitServiceWorker | None = None
        self._step_widgets: dict[str, _StepRow] = {}

        self._build_ui()
        self._init_steps_from_check()

    # ── UI 构建 ──

    def _build_ui(self):
        """构建向导界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # ---- 标题区 ----
        title_row = QHBoxLayout()
        title = QLabel("数据初始化")
        title.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 18px; font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch()

        # 网络状态
        self._net_label = QLabel("🌐 检测中...")
        self._net_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        title_row.addWidget(self._net_label)
        layout.addLayout(title_row)

        desc = QLabel("正在下载游戏数据以启用全部功能。已就绪的步骤将自动跳过。")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(desc)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
        line.setFixedHeight(1)
        layout.addWidget(line)

        # ---- 步骤列表 ----
        step_container = QVBoxLayout()
        step_container.setSpacing(6)

        for step in STEPS:
            row = _StepRow(step)
            row.retry_btn.clicked.connect(lambda checked, k=step.key: self._on_retry(k))
            row.skip_btn.clicked.connect(lambda checked, k=step.key: self._on_skip(k))
            self._step_widgets[step.key] = row
            step_container.addWidget(row)

        layout.addLayout(step_container)

        # ---- 底部 ----
        layout.addStretch()

        # 分隔线
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
        line2.setFixedHeight(1)
        layout.addWidget(line2)

        # 整体进度条
        self._total_bar = QProgressBar()
        self._total_bar.setRange(0, len(STEPS))
        self._total_bar.setValue(0)
        self._total_bar.setTextVisible(True)
        self._total_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {theme.BG_SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: 4px;
                height: 22px;
                text-align: center;
                color: {theme.TEXT_PRIMARY};
                font-size: 12px;
            }}
            QProgressBar::chunk {{
                background-color: {theme.PRIMARY};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self._total_bar)

        # ETA 文字
        eta_row = QHBoxLayout()
        self._eta_label = QLabel("")
        self._eta_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        eta_row.addWidget(self._eta_label)
        eta_row.addStretch()
        layout.addLayout(eta_row)

        # 按钮行
        btn_row = QHBoxLayout()

        self._retry_all_btn = QPushButton("全部重试")
        self._retry_all_btn.setStyleSheet(_btn_style(theme.ACCENT_ORANGE))
        self._retry_all_btn.clicked.connect(self._on_retry_all)
        self._retry_all_btn.hide()
        btn_row.addWidget(self._retry_all_btn)

        btn_row.addStretch()

        self._start_btn = QPushButton("开始初始化" if not self._auto_mode else "开始下载")
        self._start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.PRIMARY};
                color: {theme.TEXT_ON_PRIMARY};
                border: none;
                border-radius: 6px;
                padding: 8px 28px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{ background-color: {theme.BG_HOVER}; }}
            QPushButton:disabled {{ background-color: {theme.TEXT_SECONDARY}; color: #888; }}
        """)
        self._start_btn.clicked.connect(self._start_init)
        btn_row.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setStyleSheet(_btn_style(theme.ACCENT_RED))
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.hide()
        btn_row.addWidget(self._cancel_btn)

        self._bg_btn = QPushButton("后台运行" if self._auto_mode else "最小化")
        self._bg_btn.setStyleSheet(_btn_style(theme.BG_SURFACE, theme.TEXT_PRIMARY, theme.BG_HOVER))
        self._bg_btn.clicked.connect(self._hide_wizard)
        btn_row.addWidget(self._bg_btn)

        layout.addLayout(btn_row)

        if self._auto_mode:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)

        # ETA 定时器
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_eta)

    def _init_steps_from_check(self):
        """根据 init_check 初始化步骤状态"""
        done_count = 0
        for step in STEPS:
            row = self._step_widgets[step.key]
            if is_step_satisfied(step.key):
                row.set_state(StepStatus.COMPLETED, "数据已就绪")
                done_count += 1
            else:
                row.set_state(StepStatus.PENDING)
        self._total_bar.setValue(done_count)
        self._total_bar.setFormat(f"{done_count}/{len(STEPS)} 就绪")

        # 全部就绪时隐藏开始按钮
        if done_count == len(STEPS):
            self._start_btn.hide()
            self._total_bar.setFormat("全部就绪")

        # 部分就绪时显示 ETA
        remaining = len(STEPS) - done_count
        if remaining > 0:
            self._eta_label.setText(f"剩余 {remaining}/{len(STEPS)} 个步骤")
            self._start_btn.setText(f"开始初始化（{remaining} 步）")

    # ── 生命周期 ──

    def showEvent(self, ev):
        """显示时更新主题和初始状态"""
        super().showEvent(ev)
        self.setStyleSheet(f"background-color: {theme.BG_DARK};")
        self._init_steps_from_check()

    def closeEvent(self, event: QCloseEvent):
        """关闭行为取决于模式"""
        if self._auto_mode:
            event.ignore()  # 自动模式不可关闭
        else:
            self._hide_wizard()
            event.ignore()

    def reject(self):
        """ESC = 隐藏"""
        self._hide_wizard()

    def _hide_wizard(self):
        """隐藏窗口但不停止后台"""
        self.hide()

    # ── 初始化流程 ──

    def _start_init(self):
        """开始初始化"""
        self._start_btn.setEnabled(False)
        self._start_btn.hide()
        self._cancel_btn.show()
        self._bg_btn.setEnabled(False)
        self._retry_all_btn.hide()
        self._start_time = time.time()

        if self._elapsed_timer:
            self._elapsed_timer.start(1000)  # 每秒更新

        # 确定需要执行的步骤
        missing = [s.key for s in get_missing_steps()]
        if not missing:
            self._on_all_done(True, "全部就绪")
            return

        for k in missing:
            self._step_widgets[k].reset()

        self._total_bar.setMaximum(len(STEPS))
        self._total_bar.setValue(len(STEPS) - len(missing))
        self._total_bar.setFormat("准备中...")

        self._eta_label.setText(f"正在初始化 {len(missing)} 个步骤...")

        # 启动 Worker
        self._worker = InitServiceWorker(step_keys=missing)
        self._worker.step_started.connect(self._on_step_started)
        self._worker.step_progress.connect(self._on_step_progress)
        self._worker.step_completed.connect(self._on_step_completed)
        self._worker.all_completed.connect(self._on_all_done)
        self._worker.start()

    def _on_step_started(self, key: str, name: str):
        """步骤开始"""
        row = self._step_widgets.get(key)
        if row:
            row.set_state(StepStatus.RUNNING, "正在下载...")

    def _on_step_progress(self, key: str, percent: int, message: str):
        """步骤进度更新"""
        row = self._step_widgets.get(key)
        if row:
            row.set_state(StepStatus.RUNNING, message, percent)
        # 更新总进度
        completed = sum(1 for k, r in self._step_widgets.items() if r.icon.text() in ("✅", "⏭️", "❌"))
        self._total_bar.setValue(completed + (percent / 100))

    def _on_step_completed(self, key: str, success: bool, message: str):
        """步骤完成"""
        row = self._step_widgets.get(key)
        if row:
            status = StepStatus.COMPLETED if success else StepStatus.FAILED
            row.set_state(status, message)
        # 更新总进度
        done = sum(1 for k, r in self._step_widgets.items() if r.icon.text() in ("✅", "⏭️"))
        total = len(STEPS)
        self._total_bar.setValue(done)
        self._total_bar.setFormat(f"{done}/{total}")
        if not success:
            self._retry_all_btn.show()

    def _on_all_done(self, success: bool, summary: str):
        """全部完成"""
        if self._elapsed_timer:
            self._elapsed_timer.stop()

        self._cancel_btn.hide()
        self._bg_btn.setEnabled(True)
        self._total_bar.setValue(len(STEPS))
        self._total_bar.setFormat(summary)

        if success:
            self._eta_label.setText(f"✅ {summary}  🕐 已用 {self._elapsed_str()}")
            # 自动模式：触发回调后关闭
            if self._auto_mode and self._on_done_callback:
                self._on_done_callback()
                self.accept()
        else:
            self._eta_label.setText(f"❌ {summary}  🕐 已用 {self._elapsed_str()}")
            self._start_btn.setText("重试失败步骤")
            self._start_btn.show()
            self._start_btn.setEnabled(True)
            self._retry_all_btn.show()
            if self._auto_mode:
                pass  # 保持窗口开放，用户可以重试

    # ── 操作 ──

    def _on_retry(self, key: str):
        """重试单个步骤"""
        row = self._step_widgets.get(key)
        if row:
            row.set_state(StepStatus.PENDING)
        if self._worker:
            self._worker.retry(key)
        else:
            # 还没启动单个重试 → 只重新这个
            self._step_widgets[key].set_state(StepStatus.PENDING)
            self._worker = InitServiceWorker(step_keys=[key])
            self._worker.step_started.connect(self._on_step_started)
            self._worker.step_progress.connect(self._on_step_progress)
            self._worker.step_completed.connect(self._on_step_completed)
            self._worker.all_completed.connect(self._on_all_done)
            self._worker.start()

    def _on_skip(self, key: str):
        """跳过步骤"""
        if self._worker:
            self._worker.skip(key)
        row = self._step_widgets.get(key)
        if row:
            row.set_state(StepStatus.SKIPPED, "已跳过")
        self._total_bar.setValue(sum(1 for k, r in self._step_widgets.items() if r.icon.text() in ("✅", "⏭️")))

    def _on_retry_all(self):
        """全部重试"""
        self._retry_all_btn.hide()
        self._start_init()

    def _on_cancel(self):
        """取消初始化"""
        if self._worker:
            self._worker.cancel()
        self._cancel_btn.hide()
        self._bg_btn.setEnabled(True)
        if self._elapsed_timer:
            self._elapsed_timer.stop()
        self._eta_label.setText(f"🚫 已取消  🕐 已用 {self._elapsed_str()}")
        self._start_btn.setText("重新开始")
        self._start_btn.show()
        self._start_btn.setEnabled(True)

    # ── ETA ──

    def _update_eta(self):
        """更新已用时间"""
        if self._start_time:
            elapsed = time.time() - self._start_time
            completed = sum(1 for k, r in self._step_widgets.items() if r.icon.text() in ("✅", "⏭️"))
            total = len(STEPS)
            if completed > 0 and elapsed > 5:
                rate = elapsed / completed
                remaining = (total - completed) * rate
                self._eta_label.setText(
                    f"🕐 已用 {self._elapsed_str(elapsed)}  · 剩余约 {self._elapsed_str(remaining)}"
                )
            else:
                self._eta_label.setText(f"🕐 已用 {self._elapsed_str(elapsed)}")

    @staticmethod
    def _elapsed_str(seconds: float | None = None) -> str:
        """格式化时间字符串"""
        if seconds is None:
            if hasattr(InitWizard._elapsed_str, "_start"):
                seconds = time.time() - InitWizard._elapsed_str._start
            else:
                return "0s"
        m, s = divmod(int(seconds), 60)
        if m > 0:
            return f"{m}m{s}s"
        return f"{s}s"
