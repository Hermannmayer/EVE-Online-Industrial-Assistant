"""QML 版「数据初始化向导」的业务契约（阶段 4d）。

只测行为：步骤行装配 → 就绪预检 → 开始 / 继续 / 重试 / 跳过 / 取消 → 总进度与计时 →
auto 模式的自动开跑与自动关窗 → 关窗收尾（运行中不关、空闲关、线程收尾）。
「QML 加载无告警」那条通用护栏在 `tests/test_qml_dialogs.py` 里统一跑，这里不重复。

检查 / 下载一律换成同步替身（`_StubWorker`），不碰库、不联网；真线程只用于
「关窗要等它收尾」那一条（`_SlowWorker`）。

每个用 Qt 的用例都带 `qapp`（fixture 里带）：漏了会在没有 `QApplication` 时
构造 QWidget / 加载 QML，表现为**挂死**而不是报错（实测过）。
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtGui import QCloseEvent

import ui_qml.bridge.init_wizard_bridge as iwb
import ui_qml.theme.registry as theme
from services.init_service import STEPS, InitStep, StepStatus
from ui_qml.bridge.init_wizard_bridge import InitWizardQmlDialog, format_elapsed, step_row

# ════════════════════════════════════════════════════════════════
#  替身：初始化线程
# ════════════════════════════════════════════════════════════════


class _StubWorker(QObject):
    """`InitServiceWorker` 的同步替身：信号与签名照抄（少一个，桥 connect 时就 AttributeError）。

    `start()` 只记下参数、不真跑；各步的信号由用例手动 `emit_*` 推进，
    这样「步骤走到哪一步」完全可控。
    """

    step_started = Signal(str, str)
    step_progress = Signal(str, int, str)
    step_completed = Signal(str, bool, str)
    all_completed = Signal(bool, str)
    network_status = Signal(bool, str)
    #: `QThread.finished`（桥的「摘出去保活」分支要连它）
    finished = Signal()

    #: 按构造顺序存所有实例，用例取 `[-1]` 拿最新那个
    instances: ClassVar[list[_StubWorker]] = []

    def __init__(self, step_keys: list[str] | None = None, parent: Any = None) -> None:
        super().__init__(parent)
        self.step_keys = list(step_keys or [])
        self.started = False
        self.cancelled = False
        self.interrupted = False
        self.waited = 0
        self._running = False
        _StubWorker.instances.append(self)

    def start(self) -> None:
        self.started = True
        self._running = True

    def isRunning(self) -> bool:
        return self._running

    def cancel(self) -> None:
        self.cancelled = True
        self._running = False

    def requestInterruption(self) -> None:
        self.interrupted = True

    def wait(self, ms: int = 0) -> bool:
        self.waited = ms
        self._running = False
        return True

    def skip(self, key: str) -> bool:
        return False

    # ── 手动推进 ──────────────────────────────────────────────

    def emit_started(self, key: str, name: str = "") -> None:
        self.step_started.emit(key, name)

    def emit_progress(self, key: str, percent: int, message: str) -> None:
        self.step_progress.emit(key, percent, message)

    def emit_completed(self, key: str, success: bool, message: str) -> None:
        self.step_completed.emit(key, success, message)

    def emit_all(self, success: bool, summary: str) -> None:
        """整轮结束 —— 顺带把「线程不再运行」置上，好让后续操作能重入。"""
        self._running = False
        self.all_completed.emit(success, summary)


class _SlowWorker(_StubWorker):
    """一直说自己在跑的替身 —— 覆盖关窗收尾与非空操作路径。"""

    def start(self) -> None:
        self.started = True
        self._running = True

    def isRunning(self) -> bool:
        return True

    def cancel(self) -> None:
        self.cancelled = True

    def wait(self, ms: int = 0) -> bool:
        self.waited = ms
        return True


class _WizardFactory:
    """造 QML 版数据初始化向导。

    顺带把「实时缺失步骤」做成可改的：原版 `_start_init` 会**先把 `_has_run`
    置 True 再调 `_current_missing()`**，于是「首次复用启动预检」那条分支在开跑时
    根本走不到 —— 每次开始/继续都是现扫一遍库。桥逐字保留了这一点，所以这里必须让
    `get_missing_steps` 可编程，否则「开始只跑缺失步骤」根本测不出来。
    """

    def __init__(self, monkeypatch: Any) -> None:
        self._monkeypatch = monkeypatch
        #: 当前「实时」缺失的步骤 key（测试可直接改，模拟中途就绪/仍缺）
        self.missing: list[str] = []

    def __call__(
        self,
        *,
        worker: type = _StubWorker,
        missing: list[str] | None = None,
        **kwargs: Any,
    ) -> InitWizardQmlDialog:
        self.missing = list(missing) if missing is not None else []
        self._monkeypatch.setattr(iwb, "InitServiceWorker", worker)
        self._monkeypatch.setattr(iwb, "get_missing_steps", lambda: [s for s in STEPS if s.key in self.missing])
        _StubWorker.instances.clear()
        return InitWizardQmlDialog(prechecked_missing=missing, **kwargs)


@pytest.fixture
def wizard(qapp, monkeypatch) -> _WizardFactory:
    return _WizardFactory(monkeypatch)


def _spin(ms: int = 60) -> None:
    """转一会儿事件循环（auto 模式的 `QTimer.singleShot` 要靠它才跑得到）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _rows(dialog: InitWizardQmlDialog) -> dict[str, dict]:
    return {row["key"]: row for row in dialog.bridge.steps}


# ════════════════════════════════════════════════════════════════
#  纯函数（不需要 Qt）
# ════════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_format_elapsed_matches_the_widgets_format():
    """与原 `_elapsed_str` 逐字一致：只到分钟，没有小时档。"""
    assert format_elapsed(0) == "0s"
    assert format_elapsed(45) == "45s"
    assert format_elapsed(59.9) == "59s"
    assert format_elapsed(60) == "1m0s"
    assert format_elapsed(3700) == "61m40s"


@pytest.mark.fast
def test_step_row_flags_follow_status_and_criticality():
    """图标 / 颜色 / 进度条 / 两个按钮的可见性 —— 与原 `_StepRow.set_state` 四条规则一致。"""
    critical = InitStep("items", "物品数据", critical=True)
    optional = InitStep("icons", "物品图标", critical=False)

    pending = step_row(optional, StepStatus.PENDING)
    assert pending["icon"] == "⏸️"
    assert pending["color"] == theme.TEXT_SECONDARY
    assert pending["skipVisible"] is True
    assert pending["retryVisible"] is False
    assert pending["running"] is False

    running = step_row(critical, StepStatus.RUNNING, "正在下载...", 42)
    assert running["icon"] == "⏳"
    assert running["color"] == theme.PRIMARY
    assert running["running"] is True
    assert running["percent"] == 42
    assert running["skipVisible"] is False, "关键步骤不给跳过（原版按钮也是 setVisible(not critical)）"

    failed = step_row(critical, StepStatus.FAILED, "超时")
    assert failed["icon"] == "❌"
    assert failed["color"] == theme.ACCENT_RED
    assert failed["retryVisible"] is True
    assert failed["skipVisible"] is False
    assert step_row(optional, StepStatus.FAILED)["skipVisible"] is True, "非关键步骤失败仍可跳过"

    completed = step_row(critical, StepStatus.COMPLETED, "数据已就绪")
    assert completed["icon"] == "✅"
    assert completed["color"] == theme.ACCENT_GREEN
    assert (completed["retryVisible"], completed["skipVisible"], completed["running"]) == (False, False, False)

    skipped = step_row(optional, StepStatus.SKIPPED, "已跳过")
    assert (skipped["icon"], skipped["color"]) == ("⏭️", theme.TEXT_SECONDARY)

    cancelled = step_row(critical, StepStatus.CANCELLED)
    assert cancelled["icon"] == "🚫"


# ════════════════════════════════════════════════════════════════
#  就绪预检
# ════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_dialog_keeps_the_widgets_geometry(wizard):
    """构造签名与几何对齐原 `InitWizard(parent)`（`setMinimumSize(620, 520)` + 不 resize）。"""
    dialog = wizard(missing=[])
    try:
        assert dialog.windowTitle() == "数据初始化"
        assert (dialog.width(), dialog.height()) == (620, 520)
        assert (dialog.minimumWidth(), dialog.minimumHeight()) == (620, 520)
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_prechecked_missing_marks_the_ready_steps(wizard):
    dialog = wizard(missing=["items", "icons"])
    try:
        bridge = dialog.bridge
        rows = _rows(dialog)
        assert len(rows) == len(STEPS)
        assert rows["schema"]["icon"] == "✅"
        assert rows["schema"]["message"] == "数据已就绪"
        assert rows["items"]["icon"] == "⏸️"
        assert rows["items"]["message"] == "", "缺失步骤的消息原版也是空的（刷新时把它冲掉了）"

        total = len(STEPS)
        assert (bridge.totalMaximum, bridge.totalCurrent) == (total, total - 2)
        assert bridge.totalText == f"{total - 2}/{total} 就绪"
        assert bridge.startVisible is True
        assert bridge.startText == "开始初始化（2 步）"
        assert bridge.etaText == f"剩余 2/{total} 个步骤"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_all_ready_hides_the_start_button(wizard):
    dialog = wizard(missing=[])
    try:
        bridge = dialog.bridge
        assert bridge.totalCurrent == len(STEPS)
        assert bridge.totalText == "全部就绪"
        assert bridge.startVisible is False, "全部就绪时原版把开始按钮藏了"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_without_precheck_it_scans_the_databases_itself(qapp, monkeypatch):
    """没有启动预检（手动从设置里打开）时自己扫一次。

    注意「开始」时会**再扫一次**：原版 `_start_init` 先把 `_has_run` 置 True 才调
    `_current_missing()`，预检分支因此走不到 —— 逐字保留，不在这里「顺手修好」。
    """
    calls = {"n": 0}

    def _missing() -> list[InitStep]:
        calls["n"] += 1
        return [s for s in STEPS if s.key == "items"]

    monkeypatch.setattr(iwb, "InitServiceWorker", _StubWorker)
    monkeypatch.setattr(iwb, "get_missing_steps", _missing)
    _StubWorker.instances.clear()

    dialog = InitWizardQmlDialog(prechecked_missing=None)
    try:
        assert calls["n"] == 1, "一次 check_all 定全部步骤，不该每步查一遍"
        assert dialog.bridge.startText == "开始初始化（1 步）"

        dialog.bridge.startInit()
        assert calls["n"] == 2, "开跑时按实时检测重算（原版行为）"
        assert _StubWorker.instances[-1].step_keys == ["items"]
    finally:
        dialog.deleteLater()


# ════════════════════════════════════════════════════════════════
#  开始 / 进度 / 完成
# ════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_start_runs_only_the_missing_steps(wizard):
    dialog = wizard(missing=["items", "icons"])
    try:
        bridge = dialog.bridge
        bridge.startInit()

        worker = _StubWorker.instances[-1]
        assert worker.started is True
        assert worker.step_keys == ["items", "icons"]
        assert bridge.runActive is True
        assert bridge.startVisible is False
        assert bridge.cancelVisible is True
        assert bridge.bgEnabled is False
        assert bridge.totalText == "准备中..."
        assert bridge.totalCurrent == len(STEPS) - 2
        assert bridge.etaText == "正在初始化 2 个步骤..."
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_step_signals_drive_rows_and_the_total_bar(wizard):
    dialog = wizard(missing=["items"])
    try:
        bridge = dialog.bridge
        bridge.startInit()
        worker = _StubWorker.instances[-1]

        worker.emit_started("items", "物品数据")
        row = _rows(dialog)["items"]
        assert row["icon"] == "⏳"
        assert row["running"] is True
        assert row["message"] == "正在下载..."

        worker.emit_progress("items", 40, "下载 40%")
        row = _rows(dialog)["items"]
        assert row["percent"] == 40
        assert row["message"] == "下载 40%"

        worker.emit_completed("items", True, "完成")
        assert _rows(dialog)["items"]["icon"] == "✅"
        assert bridge.totalCurrent == len(STEPS)

        worker.emit_all(True, "全部初始化完成")
        assert bridge.runActive is False
        assert bridge.totalText == "全部初始化完成"
        assert bridge.etaText.startswith("✅")
        assert bridge.continueVisible is False
        assert bridge.startVisible is False, "全部成功时不该再露开始按钮"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_network_status_colours_follow_the_result(wizard):
    dialog = wizard(missing=["items"])
    try:
        bridge = dialog.bridge
        assert bridge.netText == "🌐 检测中..."

        bridge._on_network_status(True, "ESI 连接正常")
        assert bridge.netText == "🌐 ESI 已连接"
        assert bridge.netColor == theme.ACCENT_GREEN

        bridge._on_network_status(False, "超时")
        assert bridge.netText == "🌐 网络不可用: 超时"
        assert bridge.netColor == theme.ACCENT_RED
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_failed_step_offers_retry_continue_and_restart(wizard):
    dialog = wizard(missing=["items"])
    try:
        bridge = dialog.bridge
        bridge.startInit()
        worker = _StubWorker.instances[-1]

        worker.emit_completed("items", False, "超时")
        row = _rows(dialog)["items"]
        assert row["retryVisible"] is True
        assert row["message"] == "超时"
        assert bridge.continueVisible is True

        worker.emit_all(False, "完成 0/1")
        assert bridge.runActive is False
        assert bridge.startVisible is True
        assert bridge.startEnabled is True
        assert bridge.startText == "重试失败步骤"
        assert bridge.etaText.startswith("❌")
    finally:
        dialog.deleteLater()


# ════════════════════════════════════════════════════════════════
#  重试 / 跳过 / 继续 / 取消
# ════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_retry_runs_a_single_step_worker(wizard):
    """重试用**单步** worker，不是把整批再跑一遍（原 `_on_retry`）。"""
    dialog = wizard(missing=["items"])
    try:
        bridge = dialog.bridge
        bridge.startInit()
        first = _StubWorker.instances[-1]
        first.emit_completed("items", False, "超时")
        first.emit_all(False, "完成 0/1")

        bridge.retryStep("items")
        retry = _StubWorker.instances[-1]
        assert retry is not first
        assert retry.step_keys == ["items"]
        assert bridge.runActive is True
        assert _rows(dialog)["items"]["icon"] == "⏸️", "重试先把该行打回等待态"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_skip_marks_a_non_critical_step_and_counts_it_done(wizard):
    dialog = wizard(missing=["icons", "items"])
    try:
        bridge = dialog.bridge
        total = len(STEPS)
        bridge.skipStep("icons")

        row = _rows(dialog)["icons"]
        assert row["icon"] == "⏭️"
        assert row["message"] == "已跳过"
        assert bridge.totalCurrent == total - 1, "跳过的步骤算已完成"
        assert bridge.totalText == f"{total - 1}/{total}"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_continue_ignores_the_stale_precheck(wizard):
    """「继续」按**实时**检测补步骤 —— 已经就绪的不重跑。"""
    dialog = wizard(missing=["items", "icons"])
    try:
        bridge = dialog.bridge
        bridge.startInit()
        first = _StubWorker.instances[-1]
        assert first.step_keys == ["items", "icons"]
        first.emit_all(False, "完成 0/2")

        wizard.missing = ["icons"]  # items 期间已就绪
        bridge.continueInit()

        assert _StubWorker.instances[-1].step_keys == ["icons"], "已就绪的 items 不该重跑"
        assert bridge.continueVisible is False
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_cancel_unlocks_the_dialog_and_offers_restart(wizard):
    dialog = wizard(missing=["items"])
    try:
        bridge = dialog.bridge
        bridge.startInit()
        worker = _StubWorker.instances[-1]

        bridge.cancelInit()
        assert worker.cancelled is True
        assert bridge.runActive is False
        assert bridge.cancelVisible is False
        assert bridge.closeVisible is True
        assert bridge.startVisible is True
        assert bridge.startText == "重新开始"
        assert bridge.etaText.startswith("🚫")
    finally:
        dialog.deleteLater()


# ════════════════════════════════════════════════════════════════
#  auto 模式（启动场景）
# ════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_auto_mode_starts_downloading_on_its_own(wizard):
    dialog = wizard(missing=["items"], auto_mode=True)
    try:
        bridge = dialog.bridge
        assert bridge.autoMode is True
        assert bridge.bgText == "后台运行", "auto 模式按钮文案是「后台运行」，手动模式是「最小化」"

        _spin(80)
        assert len(_StubWorker.instances) == 1, "有缺失就该自动开跑"
        assert _StubWorker.instances[0].step_keys == ["items"]
        assert bridge.runActive is True
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_auto_mode_closes_itself_when_everything_is_ready(wizard):
    dialog = wizard(missing=[], auto_mode=True)
    try:
        assert dialog.result() == 0
        _spin(400)
        assert dialog.result() == 1, "全部就绪该自动关窗（等价于「跳过进主界面」）"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_auto_mode_calls_on_done_before_closing(wizard):
    calls: list[int] = []
    dialog = wizard(missing=["items"], auto_mode=True, on_done=lambda: calls.append(1))
    try:
        _spin(80)
        _StubWorker.instances[-1].emit_all(True, "全部初始化完成")

        assert calls == [1]
        assert dialog.result() == 1
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_auto_mode_failure_keeps_the_window_open(wizard):
    """关键步骤失败时 auto 模式不关窗 —— 用户可以重试（原版这里是空 pass）。"""
    dialog = wizard(missing=["items"], auto_mode=True)
    try:
        _spin(80)
        _StubWorker.instances[-1].emit_all(False, "完成 0/1")

        assert dialog.result() == 0
        assert dialog.bridge.startVisible is True
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_skip_enter_cancels_and_closes(wizard):
    """auto 模式的逃生口：跳过 → 直接进主界面。"""
    dialog = wizard(missing=["items"], auto_mode=True)
    try:
        _spin(80)
        worker = _StubWorker.instances[-1]

        dialog.bridge.skipEnter()
        assert worker.cancelled is True
        assert dialog.result() == 1
    finally:
        dialog.deleteLater()


# ════════════════════════════════════════════════════════════════
#  关窗语义与收尾
# ════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_running_wizard_refuses_to_close(wizard):
    """下载中不关窗（防静默放弃）：Esc 与窗口 X 都不生效。"""
    dialog = wizard(missing=["items"])
    try:
        bridge = dialog.bridge
        bridge.startInit()
        assert bridge.runActive is True

        finished: list[int] = []
        dialog.finished.connect(finished.append)

        dialog.reject()  # Esc
        assert finished == []

        event = QCloseEvent()
        dialog.closeEvent(event)  # 窗口 X
        assert event.isAccepted() is False

        # 跑完（或取消）之后关窗恢复可用
        bridge.cancelInit()
        dialog.reject()
        assert finished == [0], "空闲态 Esc 该真实关闭（QDialog.Rejected = 0）"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_close_button_reaches_the_host(wizard):
    """QML「关闭」按钮 → 桥 `requestClose()` → 宿主关窗（原 `_request_close`）。"""
    dialog = wizard(missing=["items"])
    try:
        finished: list[int] = []
        dialog.finished.connect(finished.append)
        dialog.bridge.requestClose()
        assert finished == [0]
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_background_button_asks_the_host_to_hide(wizard):
    dialog = wizard(missing=["items"])
    try:
        hidden: list[int] = []
        dialog.bridge.hideRequested.connect(lambda: hidden.append(1))
        dialog.bridge.hideWizard()
        assert hidden == [1]
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_closing_the_dialog_stops_the_running_worker(wizard):
    """关窗必须让初始化线程收尾。

    不收尾的话，线程是桥的子对象、桥随对话框一起销毁 —— `QThread` 在运行时被析构
    Qt 直接 `abort()`，整个进程静默死掉、一行日志都没有。
    """
    dialog = wizard(missing=["items"], worker=_SlowWorker)
    try:
        bridge = dialog.bridge
        bridge.startInit()
        worker = _StubWorker.instances[-1]
        assert worker.isRunning(), "替身应当一直说自己在跑"

        dialog.done(0)  # 确定 / 取消 / Esc 都走这里

        assert worker.cancelled, "该让 worker 在下一个步骤前退出"
        assert worker.interrupted
        assert worker.waited > 0, "关窗该等线程收尾，而不是撒手不管"
    finally:
        dialog.deleteLater()
