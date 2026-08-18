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

from PySide6.QtCore import QTimer
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
from services.init_service import STEPS, InitStep, StepStatus, get_missing_steps
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


def _btn_style(
    bg: str,
    fg: str = "",
    hover: str | None = None,
    disabled: str = "",
) -> str:
    fg = fg or theme.TEXT_ON_PRIMARY
    disabled = disabled or theme.TEXT_SECONDARY
    return _BTN_STYLE.format(bg=bg, fg=fg, hover=hover or bg, disabled=disabled)
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

    def __init__(self, parent=None, on_done=None, auto_mode: bool = False, prechecked_missing: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("数据初始化")
        self.setMinimumSize(620, 520)
        self.setStyleSheet(f"background-color: {theme.BG_DARK};")

        self._auto_mode = auto_mode
        self._prechecked_missing = prechecked_missing
        self._on_done_callback = on_done
        self._start_time: float | None = None
        self._elapsed_timer: QTimer | None = None
        self._worker: InitServiceWorker | None = None
        self._step_widgets: dict[str, _StepRow] = {}
        # 运行态：worker 下载进行中为 True。true 时禁止关闭/重入，保证不静默放弃。
        self._run_active = False
        # 是否已跑过初始化：之后重新开始/继续时忽略启动预检，实时重算缺失步骤。
        self._has_run = False
        # UI 侧步骤状态映射（替代 icon 的 emoji 字符串判断，脆弱且不可测）
        self._step_status: dict[str, StepStatus] = {s.key: StepStatus.PENDING for s in STEPS}

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

        self._continue_btn = QPushButton("继续（重试未完成）")
        self._continue_btn.setStyleSheet(_btn_style(theme.ACCENT_ORANGE))
        self._continue_btn.clicked.connect(self._on_continue)
        self._continue_btn.hide()
        btn_row.addWidget(self._continue_btn)

        btn_row.addStretch()

        # auto_mode（启动场景）下提供「跳过 → 直接进主界面」逃生口
        self._skip_enter_btn = QPushButton("跳过，进入主界面")
        self._skip_enter_btn.setStyleSheet(_btn_style(theme.TEXT_SECONDARY))
        self._skip_enter_btn.setVisible(self._auto_mode)
        self._skip_enter_btn.clicked.connect(self._on_skip_enter)
        btn_row.addWidget(self._skip_enter_btn)

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
            QPushButton:disabled {{ background-color: {theme.TEXT_SECONDARY}; color: {theme.TEXT_SECONDARY}; }}
        """)
        self._start_btn.clicked.connect(self._start_init)
        btn_row.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setStyleSheet(_btn_style(theme.ACCENT_RED))
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.hide()
        btn_row.addWidget(self._cancel_btn)

        # 取消/失败后的明确关闭出口（auto 关闭=返回 exec()，Main 随后显示主窗口）
        self._close_btn = QPushButton("关闭")
        self._close_btn.setStyleSheet(_btn_style(theme.TEXT_SECONDARY))
        self._close_btn.clicked.connect(self._request_close)
        self._close_btn.hide()
        btn_row.addWidget(self._close_btn)

        self._bg_btn = QPushButton("后台运行" if self._auto_mode else "最小化")
        self._bg_btn.setStyleSheet(_btn_style(theme.BG_SURFACE, theme.TEXT_PRIMARY, theme.BG_HOVER))
        self._bg_btn.clicked.connect(self._hide_wizard)
        btn_row.addWidget(self._bg_btn)

        layout.addLayout(btn_row)

        # ETA 定时器
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_eta)

    def _init_steps_from_check(self):
        """根据 init_check 初始化步骤状态（一次 check_all，避免 N 次全库扫描）"""
        if self._prechecked_missing is not None:
            missing_keys = set(self._prechecked_missing)
        else:
            missing_keys = {s.key for s in get_missing_steps()}
        done_count = 0
        for step in STEPS:
            if step.key not in missing_keys:
                self._set_step(step.key, StepStatus.COMPLETED, "数据已就绪")
                done_count += 1
            else:
                self._set_step(step.key, StepStatus.PENDING)
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

        # auto_mode（启动场景）：全部就绪 → 自动关闭；有缺失 → 自动开始下载。
        # __init__ 与 showEvent 都会调用本方法，用 _auto_handled 保证只调度一次。
        if self._auto_mode and not getattr(self, "_auto_handled", False):
            self._auto_handled = True
            if done_count == len(STEPS):
                QTimer.singleShot(300, self.accept)
            else:
                QTimer.singleShot(0, self._start_init)

    # ── 生命周期 ──

    def showEvent(self, ev):
        """显示时更新主题和初始状态"""
        super().showEvent(ev)
        self.setStyleSheet(f"background-color: {theme.BG_DARK};")
        self._init_steps_from_check()

    def closeEvent(self, event: QCloseEvent):
        """关闭行为：运行中不开窗（防静默放弃），空闲态走真实关闭。

        真实关闭即结束 modal 循环（返回 exec()）。auto 模式时 Main.py 随后显示主窗口，
        等价于「跳过进主界面」；手动模式则彻底关闭向导。
        """
        if self._run_active:
            event.ignore()
            return
        event.accept()

    def reject(self):
        """ESC：运行中忽略（不锁死），空闲态结束 modal 循环（真实关闭）。

        必须调 super().reject() 让 exec() 返回，否则 auto 模式整个 app 卡住无主窗口。
        """
        if self._run_active:
            return
        super().reject()

    def _request_close(self):
        """「关闭」按钮：空闲态显式请求真实关闭。"""
        self.close()

    def _hide_wizard(self):
        """隐藏窗口但不停止后台（后台继续运行）"""
        self.hide()

    # ── 初始化流程 ──

    def _current_missing(self) -> list[str]:
        """计算当前仍缺失的步骤。

        首次（尚未跑过）复用启动时的预检结果，避免二次全库扫描；跑过之后忽略预检
        （可能已过期），改用 check_all 实时重算，保证「继续」只补仍未就绪的步骤，
        已完成的不重跑。
        """
        if not self._has_run and self._prechecked_missing is not None:
            return [k for k in self._prechecked_missing if k in self._step_widgets]
        return [s.key for s in get_missing_steps() if s.key in self._step_widgets]

    def _start_init(self):
        """开始（或继续）初始化"""
        # 防双 Worker：上一个线程仍在跑时不新建，避免并发写库。
        if self._worker is not None and self._worker.isRunning():
            return

        self._run_active = True
        self._has_run = True
        self._start_btn.setEnabled(False)
        self._start_btn.hide()
        self._cancel_btn.show()
        self._close_btn.hide()
        self._continue_btn.hide()
        self._bg_btn.setEnabled(False)
        self._start_time = time.time()

        if self._elapsed_timer:
            self._elapsed_timer.start(1000)  # 每秒更新

        missing = self._current_missing()
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
        self._worker = InitServiceWorker(step_keys=missing, parent=self)
        self._worker.step_started.connect(self._on_step_started)
        self._worker.step_progress.connect(self._on_step_progress)
        self._worker.step_completed.connect(self._on_step_completed)
        self._worker.all_completed.connect(self._on_all_done)
        self._worker.network_status.connect(self._on_network_status)
        self._worker.start()

    def _set_step(self, key: str, status: StepStatus, message: str = "", percent: int = 0):
        """统一更新某个步骤的行 UI 与内部状态映射。"""
        self._step_status[key] = status
        row = self._step_widgets.get(key)
        if row:
            row.set_state(status, message, percent)

    def _done_count(self) -> int:
        """已完成（不止重跑）步骤数：COMPLETED / SKIPPED。"""
        return sum(1 for s in self._step_status.values() if s in (StepStatus.COMPLETED, StepStatus.SKIPPED))

    def _on_network_status(self, ok: bool, message: str):
        """网络连通性状态"""
        if not ok:
            self._net_label.setText(f"🌐 网络不可用: {message}")
            self._net_label.setStyleSheet(f"color: {theme.ACCENT_RED}; font-size: 11px;")
        else:
            self._net_label.setText("🌐 ESI 已连接")
            self._net_label.setStyleSheet(f"color: {theme.ACCENT_GREEN}; font-size: 11px;")

    def _refresh_total(self):
        """总进度条 = 已完成步骤数（分进度在各自行内显示）。"""
        done = self._done_count()
        total = len(STEPS)
        self._total_bar.setMaximum(total)
        self._total_bar.setValue(done)
        self._total_bar.setFormat(f"{done}/{total}")

    def _on_step_started(self, key: str, name: str):
        """步骤开始"""
        self._set_step(key, StepStatus.RUNNING, "正在下载...")

    def _on_step_progress(self, key: str, percent: int, message: str):
        """步骤进度更新"""
        self._set_step(key, StepStatus.RUNNING, message, percent)
        self._refresh_total()

    def _on_step_completed(self, key: str, success: bool, message: str):
        """步骤完成"""
        status = StepStatus.COMPLETED if success else StepStatus.FAILED
        self._set_step(key, status, message)
        self._refresh_total()
        if not success:
            self._continue_btn.show()

    def _on_all_done(self, success: bool, summary: str):
        """全部完成"""
        self._run_active = False
        if self._elapsed_timer:
            self._elapsed_timer.stop()

        self._cancel_btn.hide()
        self._bg_btn.setEnabled(True)
        self._total_bar.setValue(len(STEPS))
        self._total_bar.setFormat(summary)

        if success:
            self._eta_label.setText(f"✅ {summary}  🕐 已用 {self._elapsed_now()}")
            # 自动模式（启动场景）：等待 worker 线程完全退出（含 clear_yaml_cache 收尾）
            # 再触发回调并关闭；on_done 可能为空（Main.py 不传），也需 accept。
            if self._auto_mode:
                if self._worker:
                    self._worker.wait()
                if self._on_done_callback:
                    self._on_done_callback()
                self.accept()
        else:
            self._eta_label.setText(f"❌ {summary}  🕐 已用 {self._elapsed_now()}")
            self._start_btn.setText("重试失败步骤")
            self._start_btn.show()
            self._start_btn.setEnabled(True)
            self._continue_btn.show()
            if self._auto_mode:
                pass  # 保持窗口开放，用户可以重试

    # ── 操作 ──

    def _on_retry(self, key: str):
        """重试单个步骤"""
        # worker 运行中不允许跨线程直接调 service.retry（内部会再开事件循环并发同状态）。
        # 空闲态才允许：直接用单步 worker 重跑该步骤。
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_step(key, StepStatus.PENDING)
        self._run_active = True
        self._start_btn.hide()
        self._cancel_btn.show()
        self._close_btn.hide()
        self._continue_btn.hide()
        self._bg_btn.setEnabled(False)
        self._worker = InitServiceWorker(step_keys=[key], parent=self)
        self._worker.step_started.connect(self._on_step_started)
        self._worker.step_progress.connect(self._on_step_progress)
        self._worker.step_completed.connect(self._on_step_completed)
        self._worker.all_completed.connect(self._on_all_done)
        self._worker.network_status.connect(self._on_network_status)
        self._worker.start()

    def _on_skip(self, key: str):
        """跳过步骤（只允许空闲态，避免运行中跨线程调用）"""
        if self._worker is not None and self._worker.isRunning():
            return
        if self._worker:
            self._worker.skip(key)
        self._set_step(key, StepStatus.SKIPPED, "已跳过")
        self._refresh_total()

    def _on_continue(self):
        """继续（重试未完成）：只补仍未就绪的步骤，已完成的不重跑。"""
        self._continue_btn.hide()
        self._close_btn.hide()
        self._start_init()

    def _on_cancel(self):
        """取消初始化"""
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
        self._run_active = False
        self._cancel_btn.hide()
        self._bg_btn.setEnabled(True)
        self._close_btn.show()
        self._continue_btn.show()
        if self._elapsed_timer:
            self._elapsed_timer.stop()
        self._eta_label.setText(f"🚫 已取消  🕐 已用 {self._elapsed_now()}")
        self._start_btn.setText("重新开始")
        self._start_btn.show()
        self._start_btn.setEnabled(True)

    def _on_skip_enter(self):
        """跳过 → 直接进入主界面（auto_mode 启动场景）"""
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        self._run_active = False
        self.accept()

    # ── ETA ──

    def _update_eta(self):
        """更新已用时间"""
        if self._start_time:
            elapsed = time.time() - self._start_time
            completed = self._done_count()
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
    def _elapsed_str(seconds: float) -> str:
        """格式化时间字符串"""
        m, s = divmod(int(seconds), 60)
        if m > 0:
            return f"{m}m{s}s"
        return f"{s}s"

    def _elapsed_now(self) -> str:
        """从开始计时到现在经过的时长"""
        if self._start_time:
            return self._elapsed_str(time.time() - self._start_time)
        return "0s"
