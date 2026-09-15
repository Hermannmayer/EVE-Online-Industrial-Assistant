"""数据初始化向导的桥（阶段 4d）。

对照 Widgets 版 `ui_pyside6/views/init_wizard.py`：逐项检查 / 下载 SDE 与 ESI 数据，
每步一个状态图标 + 进度 + 失败重试 / 非关键步骤跳过，底部总进度 + 已用时间，
auto 模式（启动场景）全部就绪即自动关窗、有缺失即自动开跑。

**检查 / 下载逻辑一行都不重写**：直接复用 `services.init_service`（步骤表 `STEPS`、
就绪判定 `get_missing_steps`）与 `ui_qml.workers.init_workers.InitServiceWorker`
（QThread）。迁移期只保留这一份业务实现，桥只做「状态映射 + 控件态 + 线程收尾」。

三处与原版不同（都有原因，逐条见下）：
- 原版的 `_StepRow`（QWidget）不单独建文件，改成 QML 列表里的一行 delegate；每行的
  computed 字段（图标 / 颜色 / 进度条可见性 / 两个按钮的可见性）由桥的纯函数
  `step_row()` 算好，与 Widgets 版逐条对齐 —— 颜色按主题 token 解析成字符串，QML 只画。
- 原版用 emoji 字符串 **且** 另存了一份 `_step_status` 映射做判断；这里只留后者作唯一
  事实来源，emoji 由它派生，避免「图标被别处改过就和状态对不上」。
- 「后台运行 / 最小化」按钮原来是 `self.hide()`。QML 页面拿不到宿主窗口，桥改发
  `hideRequested`，由宿主 `InitWizardQmlDialog` 接到自己的 `hide()` 上。

关窗语义（原 `closeEvent` / `reject` 的「运行中不关窗」）落在宿主类里：QML 侧 Esc
走的是 `QDialog.reject`，不经过桥，所以必须在宿主拦；桥里同样拦一次（QML 的「关闭」
按钮走 `requestClose()` → `reject()`）。
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Property, QTimer, Signal, Slot

from services.init_service import STEPS, InitStep, StepStatus, get_missing_steps
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.theme import registry as theme
from ui_qml.workers.init_workers import InitServiceWorker

__all__ = [
    "InitWizardBridge",
    "InitWizardQmlDialog",
    "format_elapsed",
    "step_row",
]

_QML_FILE = "dialogs/InitWizardDialog.qml"

#: 步骤 key 全集 —— 原版用 `self._step_widgets`（dict）做成员判定，这里等价
_STEP_KEYS: frozenset[str] = frozenset(s.key for s in STEPS)

#: 状态 → 图标 / 主题 token（与原 `_StepRow.set_state` 的两张表逐字一致）
_ICONS: dict[StepStatus, str] = {
    StepStatus.PENDING: "⏸️",
    StepStatus.RUNNING: "⏳",
    StepStatus.COMPLETED: "✅",
    StepStatus.FAILED: "❌",
    StepStatus.SKIPPED: "⏭️",
    StepStatus.CANCELLED: "🚫",
}
_TOKENS: dict[StepStatus, str] = {
    StepStatus.PENDING: "TEXT_SECONDARY",
    StepStatus.RUNNING: "PRIMARY",
    StepStatus.COMPLETED: "ACCENT_GREEN",
    StepStatus.FAILED: "ACCENT_RED",
    StepStatus.SKIPPED: "TEXT_SECONDARY",
    StepStatus.CANCELLED: "TEXT_SECONDARY",
}

#: 关窗时还没跑完、被摘出对话树的线程（同 `batch_price_bridge` 的强引用保活做法）
_DETACHED: set[Any] = set()


# ══════════════════════════════════════════════════════════════
#  纯函数：行装配与计时文案（便于单测，不碰 Qt）
# ══════════════════════════════════════════════════════════════


def _token_color(token: str) -> str:
    """主题 token 名 → 颜色字符串（QML 的 `color:` 直接吃字符串，见 `summary_dialog.cell`）。"""
    return str(getattr(theme, token, "") or "")


def step_row(step: InitStep, status: StepStatus, message: str = "", percent: int = 0) -> dict:
    """一个步骤 → QML 列表行的全部字段。

    原 `_StepRow.set_state` 里散着的四条规则收在这里：图标随状态、颜色随状态、
    重试按钮只在 FAILED、跳过按钮只在 PENDING/FAILED **且非关键**步骤。
    """
    return {
        "key": step.key,
        "name": step.name,
        "critical": bool(step.critical),
        "icon": _ICONS.get(status, "⏸️"),
        "color": _token_color(_TOKENS.get(status, "TEXT_SECONDARY")),
        "message": message,
        "percent": int(percent),
        #: 步骤级进度条只在 RUNNING 时出现（原 `progress_bar.setVisible(status == RUNNING)`）
        "running": status == StepStatus.RUNNING,
        "retryVisible": status == StepStatus.FAILED,
        "skipVisible": status in (StepStatus.PENDING, StepStatus.FAILED) and not step.critical,
    }


def format_elapsed(seconds: float) -> str:
    """秒 → `1m30s` / `45s`（原 `InitWizard._elapsed_str` 逐字一致）。"""
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}m{s}s"
    return f"{s}s"


# ══════════════════════════════════════════════════════════════
#  桥
# ══════════════════════════════════════════════════════════════


class InitWizardBridge(DialogBridge):
    """数据初始化向导的 QML 后端。"""

    #: 单一状态信号：10 行的小列表，每次重建代价可以忽略（不像批量查价的输入框
    #: 会逐字触发），不值得为它再拆一个信号出来。
    stateChanged = Signal()
    #: 「后台运行 / 最小化」：宿主窗口由 QML 页面拿不到，交给宿主接 `hide()`
    hideRequested = Signal()

    def __init__(
        self,
        on_done: Any = None,
        auto_mode: bool = False,
        prechecked_missing: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.set_title("数据初始化")

        self._auto_mode = bool(auto_mode)
        self._prechecked_missing = list(prechecked_missing) if prechecked_missing is not None else None
        self._on_done_callback = on_done

        self._start_time: float | None = None
        self._worker: InitServiceWorker | None = None
        #: worker 下载进行中为 True。true 时禁止关闭/重入，保证不静默放弃。
        self._run_active = False
        #: 是否已跑过初始化：之后重新开始/继续时忽略启动预检，实时重算缺失步骤。
        self._has_run = False
        #: auto 模式的自动关窗/自动开跑只调度一次（`__init__` 与 show 各会刷一次状态）
        self._auto_handled = False

        #: UI 侧步骤状态（唯一事实来源；图标与按钮可见性都由它派生）
        self._step_status: dict[str, StepStatus] = {s.key: StepStatus.PENDING for s in STEPS}
        self._step_message: dict[str, str] = {s.key: ("等待中" if s.critical else "可选") for s in STEPS}
        self._step_percent: dict[str, int] = {s.key: 0 for s in STEPS}

        self._net_text = "🌐 检测中..."
        self._net_color = _token_color("TEXT_SECONDARY")

        self._total_current = 0
        self._total_maximum = len(STEPS)
        self._total_text = ""

        self._eta_text = ""

        # 底部按钮态。默认值照抄原版 `_build_ui` 出来的初始可见性
        self._start_visible = True
        self._start_enabled = True
        self._start_text = "开始下载" if self._auto_mode else "开始初始化"
        self._cancel_visible = False
        self._close_visible = False
        self._continue_visible = False
        self._bg_enabled = True
        self._bg_text = "后台运行" if self._auto_mode else "最小化"

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_eta)

        self.refresh_steps()

    # ── 给 QML 读 ────────────────────────────────────────────

    @Property(list, notify=stateChanged)
    def steps(self) -> list[dict]:
        return [
            step_row(s, self._step_status[s.key], self._step_message.get(s.key, ""), self._step_percent.get(s.key, 0))
            for s in STEPS
        ]

    @Property(str, notify=stateChanged)
    def netText(self) -> str:
        return self._net_text

    @Property(str, notify=stateChanged)
    def netColor(self) -> str:
        return self._net_color

    @Property(int, notify=stateChanged)
    def totalCurrent(self) -> int:
        return self._total_current

    @Property(int, notify=stateChanged)
    def totalMaximum(self) -> int:
        return self._total_maximum

    @Property(str, notify=stateChanged)
    def totalText(self) -> str:
        return self._total_text

    @Property(str, notify=stateChanged)
    def etaText(self) -> str:
        return self._eta_text

    @Property(bool, notify=stateChanged)
    def startVisible(self) -> bool:
        return self._start_visible

    @Property(bool, notify=stateChanged)
    def startEnabled(self) -> bool:
        return self._start_enabled

    @Property(str, notify=stateChanged)
    def startText(self) -> str:
        return self._start_text

    @Property(bool, notify=stateChanged)
    def cancelVisible(self) -> bool:
        return self._cancel_visible

    @Property(bool, notify=stateChanged)
    def closeVisible(self) -> bool:
        return self._close_visible

    @Property(bool, notify=stateChanged)
    def continueVisible(self) -> bool:
        return self._continue_visible

    @Property(bool, notify=stateChanged)
    def bgEnabled(self) -> bool:
        return self._bg_enabled

    @Property(str, notify=stateChanged)
    def bgText(self) -> str:
        return self._bg_text

    @Property(bool, notify=stateChanged)
    def runActive(self) -> bool:
        """运行态 —— 宿主据此拦「运行中关窗」。"""
        return self._run_active

    #: auto 模式（启动场景）才给「跳过，进入主界面」逃生口
    autoMode = Property(bool, lambda self: self._auto_mode, constant=True)

    # ── 给 QML 调 ────────────────────────────────────────────

    @Slot()
    def refresh_steps(self) -> None:
        """按就绪检测刷新各步骤状态（原 `_init_steps_from_check`）。

        一次 `check_all`（经 `get_missing_steps`）定全部步骤，避免 N 次全库扫描；
        有启动预检结果时直接复用（`Main.py` 的 splash 已经查过一遍）。
        """
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
                # 消息留空：原版这里也是 `_set_step(key, PENDING)`（不带 msg），
                # 会把 `_StepRow` 构造时的「等待中/可选」冲掉
                self._set_step(step.key, StepStatus.PENDING)

        total = len(STEPS)
        self._total_maximum = total
        self._total_current = done_count
        self._total_text = f"{done_count}/{total} 就绪"
        # 全部就绪时藏掉开始按钮（原 `_start_btn.hide()`），否则保持可见
        self._start_visible = done_count != total
        if done_count == total:
            self._total_text = "全部就绪"

        remaining = total - done_count
        if remaining > 0:
            self._eta_text = f"剩余 {remaining}/{total} 个步骤"
            self._start_text = f"开始初始化（{remaining} 步）"

        # auto 模式（启动场景）：全部就绪 → 自动关闭；有缺失 → 自动开跑。
        # `__init__` 与 show 都会调本方法，用 `_auto_handled` 保证只调度一次。
        if self._auto_mode and not self._auto_handled:
            self._auto_handled = True
            if done_count == total:
                QTimer.singleShot(300, self.accept)
            else:
                QTimer.singleShot(0, self._start_init)

        self._notify()

    @Slot()
    def startInit(self) -> None:
        self._start_init()

    @Slot()
    def continueInit(self) -> None:
        """继续（重试未完成）：只补仍未就绪的步骤，已完成的不重跑。"""
        self._continue_visible = False
        self._close_visible = False
        self._start_init()

    @Slot(str)
    def retryStep(self, key: str) -> None:
        self._on_retry(key)

    @Slot(str)
    def skipStep(self, key: str) -> None:
        self._on_skip(key)

    @Slot()
    def cancelInit(self) -> None:
        self._on_cancel()

    @Slot()
    def skipEnter(self) -> None:
        """ "跳过 → 直接进入主界面"（auto_mode 启动场景）。"""
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        self._run_active = False
        self.accept()

    @Slot()
    def hideWizard(self) -> None:
        """隐藏窗口但不停止后台（后台继续运行）。"""
        self.hideRequested.emit()

    @Slot()
    def requestClose(self) -> None:
        """「关闭」按钮（原 `_request_close` → `self.close()`）。

        关闭等价于 `reject`：它结束 modal 循环、返回 `exec()`，auto 模式时
        `Main.py` 随后显示主窗口。运行中由 `reject` 的重载拦住。
        """
        self.reject()

    # ── 初始化流程 ───────────────────────────────────────────

    def _current_missing(self) -> list[str]:
        """当前仍缺失的步骤（原 `InitWizard._current_missing`）。

        首次（尚未跑过）复用启动预检，免二次全库扫描；跑过之后忽略预检（可能已过期），
        改用 `get_missing_steps` 实时重算，保证「继续」只补仍未就绪的步骤。
        """
        if not self._has_run and self._prechecked_missing is not None:
            return [k for k in self._prechecked_missing if k in _STEP_KEYS]
        return [s.key for s in get_missing_steps() if s.key in _STEP_KEYS]

    def _start_init(self) -> None:
        """开始（或继续）初始化。"""
        # 防双 Worker：上一个线程仍在跑时不新建，避免并发写库
        if self._worker is not None and self._worker.isRunning():
            return

        self._run_active = True
        self._has_run = True
        self._start_enabled = False
        self._start_visible = False
        self._cancel_visible = True
        self._close_visible = False
        self._continue_visible = False
        self._bg_enabled = False
        self._start_time = time.time()
        self._elapsed_timer.start(1000)  # 每秒更新

        missing = self._current_missing()
        if not missing:
            self._on_all_done(True, "全部就绪")
            return

        for k in missing:
            self._set_step(k, StepStatus.PENDING)

        self._total_maximum = len(STEPS)
        self._total_current = len(STEPS) - len(missing)
        self._total_text = "准备中..."
        self._eta_text = f"正在初始化 {len(missing)} 个步骤..."

        self._spawn_worker(missing)
        self._notify()

    def _spawn_worker(self, keys: list[str]) -> None:
        """起一个 InitServiceWorker（原版在 `_start_init` / `_on_retry` 各写了一遍）。"""
        worker = InitServiceWorker(step_keys=keys, parent=self)
        self._worker = worker
        worker.step_started.connect(self._on_step_started)
        worker.step_progress.connect(self._on_step_progress)
        worker.step_completed.connect(self._on_step_completed)
        worker.all_completed.connect(self._on_all_done)
        worker.network_status.connect(self._on_network_status)
        worker.start()

    def _set_step(self, key: str, status: StepStatus, message: str = "", percent: int = 0) -> None:
        """更新某个步骤的内部状态（不单独发信号，由调用方统一 `_notify`）。"""
        self._step_status[key] = status
        self._step_message[key] = message
        self._step_percent[key] = percent

    def _done_count(self) -> int:
        """已完成（不止重跑）步骤数：COMPLETED / SKIPPED。"""
        return sum(1 for s in self._step_status.values() if s in (StepStatus.COMPLETED, StepStatus.SKIPPED))

    def _refresh_total(self) -> None:
        """总进度条 = 已完成步骤数（分进度在各自行内显示）。"""
        done = self._done_count()
        self._total_maximum = len(STEPS)
        self._total_current = done
        self._total_text = f"{done}/{len(STEPS)}"

    def _notify(self) -> None:
        self.stateChanged.emit()

    # ── 线程回调 ─────────────────────────────────────────────

    def _on_network_status(self, ok: bool, message: str) -> None:
        if not ok:
            self._net_text = f"🌐 网络不可用: {message}"
            self._net_color = _token_color("ACCENT_RED")
        else:
            self._net_text = "🌐 ESI 已连接"
            self._net_color = _token_color("ACCENT_GREEN")
        self._notify()

    def _on_step_started(self, key: str, name: str) -> None:
        self._set_step(key, StepStatus.RUNNING, "正在下载...")
        self._notify()

    def _on_step_progress(self, key: str, percent: int, message: str) -> None:
        self._set_step(key, StepStatus.RUNNING, message, percent)
        self._refresh_total()
        self._notify()

    def _on_step_completed(self, key: str, success: bool, message: str) -> None:
        status = StepStatus.COMPLETED if success else StepStatus.FAILED
        self._set_step(key, status, message)
        self._refresh_total()
        if not success:
            self._continue_visible = True
        self._notify()

    def _on_all_done(self, success: bool, summary: str) -> None:
        self._run_active = False
        self._elapsed_timer.stop()
        self._cancel_visible = False
        self._bg_enabled = True
        self._total_current = len(STEPS)
        self._total_text = summary

        if success:
            self._eta_text = f"✅ {summary}  🕐 已用 {self._elapsed_now()}"
            # 自动模式（启动场景）：等 worker 线程完全退出（含 clear_yaml_cache 收尾）
            # 再触发回调并关窗；on_done 可能为空（Main.py 不传），也需 accept。
            if self._auto_mode:
                if self._worker:
                    self._worker.wait()
                if self._on_done_callback:
                    self._on_done_callback()
                self.accept()
        else:
            self._eta_text = f"❌ {summary}  🕐 已用 {self._elapsed_now()}"
            self._start_text = "重试失败步骤"
            self._start_visible = True
            self._start_enabled = True
            self._continue_visible = True
            # auto 模式下保持窗口开放，用户可以重试（原版这里是个空 pass）
        self._notify()

    # ── 单步操作 ─────────────────────────────────────────────

    def _on_retry(self, key: str) -> None:
        """重试单个步骤（只用单步 worker，空闲态才允许）。

        worker 运行中不允许跨线程直接调 `service.retry`（内部会再开事件循环并发同状态）。
        """
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_step(key, StepStatus.PENDING)
        self._run_active = True
        self._start_visible = False
        self._cancel_visible = True
        self._close_visible = False
        self._continue_visible = False
        self._bg_enabled = False
        self._spawn_worker([key])
        self._notify()

    def _on_skip(self, key: str) -> None:
        """跳过步骤（只允许空闲态，避免运行中跨线程调用）。"""
        if self._worker is not None and self._worker.isRunning():
            return
        if self._worker:
            self._worker.skip(key)
        self._set_step(key, StepStatus.SKIPPED, "已跳过")
        self._refresh_total()
        self._notify()

    def _on_cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
        self._run_active = False
        self._cancel_visible = False
        self._bg_enabled = True
        self._close_visible = True
        self._continue_visible = True
        self._elapsed_timer.stop()
        self._eta_text = f"🚫 已取消  🕐 已用 {self._elapsed_now()}"
        self._start_text = "重新开始"
        self._start_visible = True
        self._start_enabled = True
        self._notify()

    # ── ETA ──────────────────────────────────────────────────

    def _update_eta(self) -> None:
        """更新已用时间 / 剩余估算（由 `_elapsed_timer` 每秒触发）。"""
        if not self._start_time:
            return
        elapsed = time.time() - self._start_time
        completed = self._done_count()
        total = len(STEPS)
        if completed > 0 and elapsed > 5:
            rate = elapsed / completed
            remaining = (total - completed) * rate
            self._eta_text = f"🕐 已用 {format_elapsed(elapsed)}  · 剩余约 {format_elapsed(remaining)}"
        else:
            self._eta_text = f"🕐 已用 {format_elapsed(elapsed)}"
        self._notify()

    def _elapsed_now(self) -> str:
        """从开始计时到现在经过的时长。"""
        if self._start_time:
            return format_elapsed(time.time() - self._start_time)
        return "0s"

    # ── 关窗收尾 ─────────────────────────────────────────────

    def reject(self) -> None:
        """运行中忽略关窗（不锁死），空闲态正常 reject（结束 `exec()`）。

        原版 `InitWizard.reject` 同款：auto 模式下必须让 `exec()` 返回，
        否则整个 app 卡在没有主窗口的状态。
        """
        if self._run_active:
            return
        super().reject()

    def stop(self) -> None:
        """关窗收尾：`QThread` 在运行中被析构时 Qt 直接 `abort()`（本仓真实崩过）。

        先 `cancel()` 再等 2 秒；真没等到就把它从桥的子对象里摘出来、挂到模块级集合上
        等它自己结束（同 `batch_price_bridge.stop` 的强引用保活做法）—— 父对象已随对话框
        销毁，留着反而是崩溃源。
        """
        worker = self._worker
        if worker is None or not worker.isRunning():
            return
        worker.cancel()
        worker.requestInterruption()
        if worker.wait(2000):
            return
        _DETACHED.add(worker)
        worker.setParent(None)
        worker.finished.connect(lambda: _DETACHED.discard(worker))


class InitWizardQmlDialog(QmlDialog):
    """QML 版「数据初始化」。`InitWizard(parent, on_done, auto_mode, prechecked_missing)` 原样可用。"""

    def __init__(
        self,
        parent: Any = None,
        on_done: Any = None,
        auto_mode: bool = False,
        prechecked_missing: list[str] | None = None,
    ) -> None:
        bridge = InitWizardBridge(on_done=on_done, auto_mode=auto_mode, prechecked_missing=prechecked_missing)
        # 原类 `setMinimumSize(620, 520)` 且不 resize：默认尺寸即 620×520
        super().__init__(_QML_FILE, bridge, parent=parent, size=(620, 520))
        bridge.hideRequested.connect(self.hide)

    def refresh_steps(self) -> None:
        """给 Python 侧/测试用的直通入口（等价原 `_init_steps_from_check`）。"""
        # 走 `self.bridge`（`QmlDialog` 的 `Any` 属性）而不是 `self._bridge`：
        # 后者的静态类型是 `DialogBridge`，子类才有的 `refresh_steps` 过不了 mypy。
        self.bridge.refresh_steps()

    # ── 关窗语义（原 `closeEvent` / `reject`）─────────────────

    def showEvent(self, event: Any) -> None:
        """显示时重新刷一次步骤状态（原 `showEvent` 里调 `_init_steps_from_check`）。"""
        super().showEvent(event)
        self.bridge.refresh_steps()

    def reject(self) -> None:
        """ESC / 关窗：运行中忽略，空闲态真实关闭。

        ESC 走的是 `QDialog.reject`，**不经过桥**，所以这道拦截必须落在宿主上；
        桥里那份 `reject` 只管 QML 按钮那条路径。
        """
        if self.bridge.runActive:
            return
        super().reject()

    def closeEvent(self, event: Any) -> None:
        """点窗口 X：运行中不开窗（防静默放弃），空闲态走真实关闭。"""
        if self.bridge.runActive:
            event.ignore()
            return
        super().closeEvent(event)
