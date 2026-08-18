"""初始化向导交互测试 — Qt 界面 + 伪 Worker（不真跑下载/网络）。

覆盖：
- 取消后/空闲态窗口可关闭；运行态禁止关闭（防静默放弃）。
- ESC（reject）运行态不锁死、空闲态真实关闭。
- 智能继续：_current_missing 首次复用预检、跑过后忽略预检实时重算。
- 防双 Worker：运行中 _start_init 不再新建 Worker。
- UI 侧步骤状态映射（不依赖 emoji 字符串）。
"""

from unittest.mock import patch

import pytest
from PySide6.QtGui import QCloseEvent

from services.init_service import STEPS, InitStep, StepStatus
from ui_pyside6.views.init_wizard import InitWizard

pytestmark = pytest.mark.ui


def _make_wizard(qapp, prechecked_missing=None, auto_mode=False):
    """构造向导；传 prechecked_missing 避免真跑 get_missing_steps（查库）。"""
    return InitWizard(prechecked_missing=prechecked_missing, auto_mode=auto_mode)


def _all_missing_wizard(qapp):
    """所有步骤均为 PENDING 的向导（prechecked_missing = 全部 key）。"""
    return _make_wizard(qapp, prechecked_missing=[s.key for s in STEPS])


# ═══════════════════════════════════════════
#  关闭行为
# ═══════════════════════════════════════════


def test_close_accepted_when_idle(qapp):
    """空闲态关闭按钮 → 真实关闭（closeEvent accept）。"""
    w = _make_wizard(qapp, prechecked_missing=[])
    w._run_active = False
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert ev.isAccepted()


def test_close_ignored_when_running(qapp):
    """运行态关闭被忽略（不静默放弃下载）。"""
    w = _make_wizard(qapp, prechecked_missing=[])
    w._run_active = True
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert not ev.isAccepted()


def test_reject_ends_modal_when_idle(qapp):
    """空闲态按 ESC → 结束 modal 循环（发出 rejected 信号），保证 exec() 能返回不卡死。"""
    w = _all_missing_wizard(qapp)
    w._run_active = False
    emitted = []
    w.rejected.connect(lambda: emitted.append(True))
    w.reject()
    assert emitted == [True]


def test_reject_ignored_when_running(qapp):
    """运行态按 ESC 不结束 modal（不丢下载），不发 rejected。"""
    w = _all_missing_wizard(qapp)
    w._run_active = True
    emitted = []
    w.rejected.connect(lambda: emitted.append(True))
    w.reject()  # 应直接返回，不触发 super().reject()
    assert emitted == []


def test_request_close_calls_close(qapp):
    """「关闭」按钮走真实 close → closeEvent 被 accept。"""
    w = _make_wizard(qapp, prechecked_missing=[])
    w._run_active = False
    with patch.object(w, "close", return_value=False) as close:
        w._request_close()
    close.assert_called_once()


# ═══════════════════════════════════════════
#  智能继续（_current_missing）
# ═══════════════════════════════════════════


def test_current_missing_reuses_precheck_first_run(qapp):
    """首运行（_has_run=False）复用预检结果，不查库。"""
    w = _make_wizard(qapp, prechecked_missing=["items", "blueprints"])
    with patch(
        "ui_pyside6.views.init_wizard.get_missing_steps",
        side_effect=AssertionError("首运行不应实时重算"),
    ) as gm:
        missing = w._current_missing()
        gm.assert_not_called()
    assert set(missing) == {"items", "blueprints"}


def test_current_missing_ignores_precheck_after_run(qapp):
    """跑过之后（_has_run=True）忽略预检，实时重算缺失步骤。"""
    w = _make_wizard(qapp, prechecked_missing=["items"])  # 预检 BE 只有 items
    w._has_run = True
    fake_step = InitStep(key="blueprints", name="蓝图数据")
    with patch("ui_pyside6.views.init_wizard.get_missing_steps", return_value=[fake_step]):
        missing = w._current_missing()
    assert missing == ["blueprints"]  # 忽略预检的 items，只用实时结果


def test_current_missing_filters_unknown_keys(qapp):
    """实时结果过滤掉未知 key。"""
    w = _make_wizard(qapp, prechecked_missing=[])
    w._has_run = True
    unknown = InitStep(key="nope", name="不存在")
    known = InitStep(key="items", name="物品数据")
    with patch("ui_pyside6.views.init_wizard.get_missing_steps", return_value=[unknown, known]):
        missing = w._current_missing()
    assert missing == ["items"]


# ═══════════════════════════════════════════
#  防双 Worker 重入
# ═══════════════════════════════════════════


class _FakeRunningWorker:
    def isRunning(self):
        return True

    def start(self):
        raise AssertionError("运行中不应新建 Worker")


def test_start_init_noop_when_worker_running(qapp):
    """worker 运行中 → _start_init 直接返回，不新建 Worker。"""
    w = _make_wizard(qapp, prechecked_missing=["items"])
    fake = _FakeRunningWorker()
    w._worker = fake  # type: ignore[assignment]
    with patch(
        "ui_pyside6.views.init_wizard.InitServiceWorker",
        side_effect=AssertionError("不应构建 Worker"),
    ) as ctor:
        w._start_init()
        ctor.assert_not_called()
    assert w._worker is fake  # 仍是旧 Worker


# ═══════════════════════════════════════════
#  步骤状态映射（不依赖 emoji）
# ═══════════════════════════════════════════


def test_step_status_mapping_updated(qapp):
    """_set_step 同时更新 _step_status 与行 UI，进度判断不依赖 emoji。"""
    w = _all_missing_wizard(qapp)
    assert w._done_count() == 0  # 基线全 PENDING
    w._set_step("items", StepStatus.COMPLETED, "数据已就绪")
    assert w._step_status["items"] == StepStatus.COMPLETED
    assert w._done_count() == 1
    w._set_step("blueprints", StepStatus.SKIPPED, "已跳过")
    assert w._done_count() == 2


def test_done_count_excludes_failed_pending(qapp):
    """已完成/跳过计入 done；失败/进行中不计。"""
    w = _all_missing_wizard(qapp)
    w._set_step("items", StepStatus.FAILED)
    w._set_step("blueprints", StepStatus.RUNNING)
    assert w._done_count() == 0
