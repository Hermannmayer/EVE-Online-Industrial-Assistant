"""外壳状态与价格 worker 的护栏。

原先这些用例测的是 `ui_pyside6.main_window.MainWindow`；批次 6.2 把 Widgets 外壳删掉后
改指 `ui_qml.shell_window.ShellWindow` —— **测的行为一条没变**（状态序列化、置顶持久化、
价格检查的间隔判定），只是宿主换了。NAV_TREE 与图标那几组随 Widgets 控件一起删掉：
导航现在是 QML 的，等价断言在 `tests/test_qml_shell.py`（导航条目、图标映射）。

`needs_price_update` 的间隔判定是**纯函数**，与本仓踩过的坑直接相关
（「数据 ≥ 间隔−60s 触发」是为了消除严格 `>` 导致的 2× 周期跳过），必须留着。
"""

from __future__ import annotations

import pytest

from ui_qml.shell_window import ShellWindow
from ui_qml.workers.main_window_workers import (
    PriceCheckWorker,
    PriceUpdateWorker,
    needs_price_update,
)

pytestmark = pytest.mark.ui

_TOLERANT_STATES = [({}), (None), ({"current_page": "nonexistent"})]


@pytest.fixture(autouse=True)
def _no_price_network(monkeypatch):
    """掐掉启动即发的价格检查：它是真 QThread + 真 ESI，测试里不该跑。"""
    monkeypatch.setattr(ShellWindow, "_init_price_check", lambda self: None)


@pytest.fixture
def shell(app, mock_db):
    win = ShellWindow()
    yield win
    win.close()
    win.deleteLater()


class TestPriceUpdateWorker:
    """价格更新后台线程"""

    def test_worker_can_be_created(self, qapp):
        assert PriceUpdateWorker() is not None


class TestPriceCheckWorker:
    """价格时效检查后台线程"""

    def test_default_interval(self, qapp):
        assert PriceCheckWorker()._interval == 30 * 60

    def test_custom_interval(self, qapp):
        assert PriceCheckWorker(interval_minutes=60)._interval == 60 * 60

    def test_fresh_data_no_update(self, qapp):
        """数据未到（间隔-60s）不需要更新"""
        assert needs_price_update(5 * 60, 30) is False  # 5 分钟前
        assert needs_price_update(28 * 60, 30) is False  # 28 分钟（容差窗口内）

    def test_stale_data_triggers_update(self, qapp):
        """数据 ≥ 间隔-60s 触发更新（消除严格 > 导致的 2× 周期跳过）"""
        assert needs_price_update(30 * 60, 30) is True  # 正好 30 分钟（旧实现会跳过）
        assert needs_price_update(29 * 60 + 5, 30) is True  # 29:05 分钟
        assert needs_price_update(56 * 60, 30) is True  # 用户观察到的 56 分钟

    def test_interval_edge(self, qapp):
        """其它间隔：容差为 60s"""
        assert needs_price_update(10 * 60, 10) is True  # 10 分钟正好到点
        assert needs_price_update(9 * 60 + 30, 10) is True  # 9:30
        assert needs_price_update(8 * 60, 10) is False  # 8 分钟（容差窗口内）


class TestShellState:
    """外壳状态序列化"""

    def test_save_state_returns_dict(self, shell):
        state = shell.save_state()
        assert isinstance(state, dict)
        assert set(state) >= {"version", "current_page", "pages"}

    def test_save_state_version(self, shell):
        assert shell.save_state()["version"] == 1

    @pytest.mark.parametrize("state", _TOLERANT_STATES, ids=["empty", "none", "unknown_page"])
    def test_restore_state_tolerant(self, shell, state):
        """空 / None / 未知页面 key 均不崩溃。"""
        shell.restore_state(state)

    def test_pin_persists_across_windows(self, shell, app, mock_db, monkeypatch):
        """置顶开关要落到 settings 并能读回来。"""
        monkeypatch.setattr(ShellWindow, "_init_price_check", lambda self: None)
        shell.set_pinned(True)
        assert shell.is_pinned() is True

        again = ShellWindow()
        try:
            assert again.is_pinned() is True, "置顶状态没持久化"
        finally:
            again.close()
            again.deleteLater()

        shell.set_pinned(False)
        assert shell.is_pinned() is False
