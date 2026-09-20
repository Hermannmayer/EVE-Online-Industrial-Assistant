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
from ui_qml.workers.main_window_workers import PriceCheckWorker, needs_price_update

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


class TestMaximizeDrag:
    """最大化后拖标题栏：未越阈值不起拖；越阈值先还原再跟手（Windows 标题栏行为）。

    回归背景：原来 `onPressed` 直接 `startSystemMove()`，而系统拖动循环（`SC_MOVE`）
    **不带**「先还原成最大化前的尺寸」——那是原生标题栏 `HTCAPTION` 的附带行为。
    于是最大化窗口被整体拖走，与用户预期不符。
    """

    #: 外壳最小尺寸是 1200x700 —— 测试尺寸必须明显大于它，否则 resize 会被夹到最小值，
    #: 「还原到最大化前的尺寸」就测不出差别
    _NORMAL = (1320, 820)

    def test_press_below_threshold_does_not_start(self, shell):
        """单击（未越过系统拖动阈值）不该还原、也不该起拖。"""
        assert shell.begin_move(100.0, 10.0, 101.0, 11.0) is False

    def test_repeat_calls_within_one_press_start_the_move_once(self, shell, monkeypatch):
        """同一次按下里重复调用只该起拖一次。

        回归背景：QML 侧每次 `onPositionChanged` 都会调进来，而 `startSystemMove()`
        内部先 `ReleaseCapture()` 再投递 `SC_DRAGMOVE` —— 系统拖动循环已经跑起来之后
        再调一次，那次 `ReleaseCapture()` 会把循环掐断，表现成「按住标题栏拖不动」。
        """
        started: list[int] = []
        monkeypatch.setattr(type(shell), "startSystemMove", lambda _self: (started.append(1), True)[1])

        assert shell.begin_move(100.0, 10.0, 300.0, 10.0) is True
        assert shell.begin_move(100.0, 10.0, 320.0, 12.0) is True
        assert shell.begin_move(100.0, 10.0, 340.0, 14.0) is True
        assert len(started) == 1, f"同一次按下只该起拖一次，实得 {len(started)} 次"

        # 下一次按下（哪怕落在同一像素）必须能重新起拖 —— 靠 QML 的 onPressed → end_move 复位
        shell.end_move()
        assert shell.begin_move(100.0, 10.0, 300.0, 10.0) is True
        assert len(started) == 2, "复位后应当能重新起拖"

    def test_drag_restores_previous_size_then_moves(self, shell):
        """越阈值后：窗口回到最大化前的尺寸，且不再处于最大化态。"""
        from PySide6.QtCore import Qt

        from tests.qml_click import spin

        shell.show()  # 需要真窗口：showMaximized 要平台窗口支撑
        shell.resize(*self._NORMAL)
        spin(150)  # 离屏平台下 resize 要事件循环才落地
        normal = shell.geometry()
        assert (normal.width(), normal.height()) == self._NORMAL, "前置条件没成立，后面的断言没意义"

        shell.showMaximized()
        spin(150)
        assert shell.windowState() == Qt.WindowState.WindowMaximized

        started = shell.begin_move(normal.width() / 2, 5.0, normal.width() / 2 + 200.0, 5.0)
        assert started is True, "越过阈值应当起拖"

        assert shell.windowState() != Qt.WindowState.WindowMaximized, "拖动后不该还是最大化"
        assert shell.width() == normal.width(), "该还原到最大化前的宽度"
        assert shell.height() == normal.height(), "该还原到最大化前的高度"

    # 「还原后窗口压在光标处」那条横向跟手断言**不写在这里**：它要么读 `QCursor.pos()`
    # （离屏平台下窗口操作期间会漂，实测偏差百余像素），要么断 `setPosition` 的绝对值
    # （离屏虚拟屏只有 800x800，位置被钳制）。属项目规矩里的「几何/像素断言不写测试」，
    # 走 `shell_snapshot.py --real` 真窗口核对。
