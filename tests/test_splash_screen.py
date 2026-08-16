"""测试启动 SplashScreen — 状态更新、进度推进与完成淡出回调。"""

import pytest
from PySide6.QtTest import QTest

from ui_pyside6.splash_screen import SplashScreen


@pytest.fixture
def splash(qapp):
    s = SplashScreen(min_ms=0)
    yield s
    s.close()


def test_set_stage_updates_label(splash):
    splash.set_stage("检查数据")
    assert splash._stage_label.text() == "检查数据"


def test_init_all_steps_checking(splash):
    """构造后全部步骤显示「检查中」状态。"""
    for icon in splash._icon_rows.values():
        assert icon.text() == "·"


def test_set_component_ready(splash):
    splash.set_component("items", "物品数据", True)
    assert splash._icon_rows["items"].text() == "✓"
    assert "就绪" in splash._msg_label.text()


def test_set_component_missing(splash):
    splash.set_component("icons", "物品图标", False)
    assert splash._icon_rows["icons"].text() == "✗"
    assert "未就绪" in splash._msg_label.text()


def _wait_for_done(splash, done: list) -> None:
    """轮询等待 complete 动画走完（负载下固定 qWait 可能不足，避免 flaky）。"""
    for _ in range(120):  # 最多 12s
        QTest.qWait(100)
        if done and splash._loader._progress >= 100:
            return


def test_complete_fills_progress_to_100(splash):
    """检查完成后进度自然走满到 100%（匀速驱动，不受检查快慢影响）。"""
    splash._shown_at = 0.0
    done: list = []
    splash.complete(lambda: done.append(1))
    _wait_for_done(splash, done)
    assert splash._loader._progress == 100
    assert done == [1]


def test_unknown_key_ignored(splash):
    splash.set_component("not_a_step", "未知", True)
    assert "not_a_step" not in splash._icon_rows


def test_complete_invokes_done_after_fill(splash):
    """检查完成：进度走满后淡出并回调 on_done。"""
    splash._shown_at = 0.0
    done: list = []
    splash.complete(lambda: done.append(1))
    _wait_for_done(splash, done)
    assert done == [1]
    assert not splash.isVisible()
