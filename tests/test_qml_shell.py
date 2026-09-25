"""QML 外壳（阶段 5 / 批次 6.1）的护栏。

这一批把主窗口从 `QMainWindow` 换成 `QQuickView`，**页面宿主必须跟着从
`QQuickWidget` 变成 `QQuickItem`** —— `QQuickWidget` 是 QWidget，Qt 明确不支持
嵌进 `QQuickWindow`。这条不变量的失败方式很隐蔽：QML 照旧能加载、页面照旧能建，
只是**永远不显示**（或整块空白）。所以单列一条断言钉死「页面不是 QWidget」。

其余几条护栏对着外壳对页面承诺的接口：切页只显示一个、状态栏/进度条能到 QML、
状态存取能把当前页带过去。

批次 6.2 删掉了 Widgets 外壳与它的 `EVE_WIDGETS_SHELL` 回退开关（连同回退页一起），
所以「回退开关可用」那条护栏也一并删了 —— 没有另一套外壳可回。
"""

from __future__ import annotations

import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QWidget

from ui_qml.constants import NAV_TREE
from ui_qml.shell_window import ShellWindow

pytestmark = pytest.mark.ui

#: 导航树里的页面 key（顺序即 `NAV_TREE` 的显示顺序）
_KEYS = [key for key, _label, _icon, _color in NAV_TREE]


@pytest.fixture(autouse=True)
def _no_price_network(monkeypatch):
    """掐掉启动即发的价格检查：它是真 QThread + 真 ESI，测试里不该跑。"""
    monkeypatch.setattr(ShellWindow, "_init_price_check", lambda self: None)


@pytest.fixture
def shell(app, mock_db, monkeypatch):
    """造一个 QML 外壳。

    `mock_db` 之外还要给仓库管理补一层 mock：`InventoryBridge` 构造时会把
    Widgets 版仓库页也拉起来（它调 `init_db()`），没有这层就整页建不出来
    —— 与 `conftest.inventory_page` 同一个理由。
    """
    from unittest.mock import MagicMock

    cursor = MagicMock()
    cursor.fetchone.return_value = (0,)
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.execute.return_value = cursor
    conn.executescript = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    mgr = MagicMock()
    mgr.connect.return_value = cm
    monkeypatch.setattr("services.inventory_manager._default_db", mgr)

    win = ShellWindow()
    yield win
    win.close()
    win.deleteLater()


# ── 1. 页面宿主形态（本批次的核心不变量）────────────────────


def test_every_page_is_a_qml_item_not_a_widget(shell):
    """页面必须是 `QQuickItem` —— 是 `QWidget` 就装不进 `QQuickWindow`。"""
    assert sorted(shell._pages) == sorted(_KEYS), "有页面没装载"
    for key, page in shell._pages.items():
        assert isinstance(page.item, QQuickItem), f"{key} 的页面不是 QQuickItem"
        assert not isinstance(page.item, QWidget), f"{key} 的页面是 QWidget，装不进 QQuickWindow"
        assert page.item.parentItem() is shell._content_area, f"{key} 的页面没挂进内容区"


# ── 2. 切页 ────────────────────────────────────────────────


def test_exactly_one_page_is_visible_and_navigation_switches_it(shell):
    visible = [k for k, p in shell._pages.items() if p.item.isVisible()]
    assert len(visible) == 1, f"可见页面应当恰好 1 个，实际 {visible}"

    target = next(k for k in _KEYS if k != shell.current_page_key())
    assert shell.navigate_to(target) is True
    assert shell.current_page_key() == target
    visible = [k for k, p in shell._pages.items() if p.item.isVisible()]
    assert visible == [target], f"切页后可见的应该是 {target}，实际 {visible}"


def test_navigating_to_an_unknown_key_is_a_noop(shell):
    before = shell.current_page_key()
    assert shell.navigate_to("不存在的页") is False
    assert shell.current_page_key() == before


# ── 3. 外壳给页面的接口（ShellBridge 按鸭子类型调）──────────


def test_status_and_progress_reach_the_bridge(shell):
    bridge = shell._bridge

    shell.set_status("正在读取")
    assert bridge.statusText == "正在读取"

    shell.show_progress("处理中", 20)
    assert bridge.progressVisible is True
    assert bridge.progressMaximum == 20

    shell.update_progress(7, "第七个")
    assert (bridge.progressValue, bridge.statusText) == (7, "第七个")

    shell.hide_progress("就绪")
    assert bridge.progressVisible is False
    assert bridge.statusText == "就绪"


def test_status_label_shim_keeps_the_settings_bridges_working(shell):
    """设置族桥按 Widgets 版的形状调 `mw._status_label.setText(...)`。

    外壳没有 QLabel，靠一个薄壳转发 —— 少了它，保存设置后状态栏不会有反馈
    （而且是静默的：`getattr(..., None)` 拿不到就跳过）。
    """
    shell._status_label.setText("设置已保存")
    assert shell._bridge.statusText == "设置已保存"


def test_region_and_auto_update_text_follow_the_state(shell):
    bridge = shell._bridge
    shell._update_regions = ["Jita", "Amarr"]
    assert bridge.regionText == "区域: Jita, Amarr"

    shell._update_regions = ["Jita", "Amarr", "Rens", "Dodixie"]
    assert bridge.regionText == "区域: Jita, Amarr +2"

    shell._auto_update_enabled = True
    shell._update_interval_minutes = 45
    assert bridge.autoUpdateText == "每 45 分钟"
    shell._auto_update_enabled = False
    assert bridge.autoUpdateText == "自动更新: 关"


# ── 图标：语义键必须经 ICON_MAP 换成文件名 ──────────────────


def test_icon_file_maps_semantic_keys_to_phosphor_filenames(shell):
    """`iconFile` 把语义键换成**文件名**（键与文件名不是一回事）。

    回归背景：外壳最初把语义键直接拼进 `image://phosphor/<file>` ——
    `close` 实际是 `x.svg`、`hangar` 是 `warehouse.svg`，取不到图时 provider
    返回**空白图且不报错**，表现为「图标整片消失」。只有 `user` / `gear-six`
    这类「键恰好等于文件名」的能显示出来，所以极易漏掉。
    """
    assert shell._bridge.iconFile("close") == "x"
    assert shell._bridge.iconFile("hangar") == "warehouse"
    assert shell._bridge.iconFile("settings") == "gear-six"
    # 未知键原样返回（沿用 `ICON_MAP.get(k, k)` 的约定），不至于拼出空 URL
    assert shell._bridge.iconFile("no-such-key") == "no-such-key"


def test_every_nav_icon_color_is_a_token_and_meets_graphic_contrast(shell):
    """导航图标配色：`NAV_TREE` 写 token 名，桥解析后**两个主题下都要 ≥3:1**。

    这条是 `ensure_contrast` 那道兜底的护栏。浅色主题的琥珀 `#ffb300` 对白底只有
    1.79:1（WCAG 1.4.11 要求图形 3:1），直接画会糊成一片 —— 桥那边压暗到达标，
    这里守住「每条都有可解析的 token」+「解析结果真的达标」。
    """
    from domain.theme_contrast import MIN_NON_TEXT_RATIO, contrast_ratio
    from ui_qml.shell_window import theme

    tokens = [color for _k, _l, _i, color in NAV_TREE]
    assert all(isinstance(t, str) and t for t in tokens), "每个导航条目都要写配色 token"

    original = theme.current_theme()
    try:
        for name in ("fluent-dark", "fluent-light"):
            theme.apply_theme(name)
            items = shell._bridge.navItems
            for key, label, _icon, _token in NAV_TREE:
                color = next(i["color"] for i in items if i["key"] == key)
                ratio = contrast_ratio(color, theme.BG_SURFACE)
                assert ratio >= MIN_NON_TEXT_RATIO, f"{label} 的图标色 {color} 在 {name} 下对侧栏底色只有 {ratio:.2f}:1"
            colors = [i["color"] for i in items]
            assert len(set(colors)) == len(NAV_TREE), f"{name} 下图例颜色有重复，看不出区分"
    finally:
        theme.apply_theme(original)


def test_unknown_nav_color_token_falls_back_instead_of_blanking(shell):
    """token 名写错时退回次要文字色，不返回空串 —— 空串会让图标整片消失。"""
    assert shell._bridge.navIconColor("NO_SUCH_TOKEN") == shell._bridge.navIconColor("TEXT_SECONDARY")


# ── 3b. 退出期的拆除顺序 ───────────────────────────────────


def test_closing_dismantles_the_qml_scene_before_the_engine_goes_away(shell, app):
    """关闭时必须**先**拆掉页面与根对象，再让引擎/窗口析构。

    反序（引擎先走、场景还在）时，任何一次绑定重算都会撞上已经被拆掉的上下文，
    抛成片 `Cannot read property 'xxx' of null`（`Theme` / `shell` 全变 null）。
    """
    assert shell._pages, "没有页面可拆，护栏自身失效"
    shell.show()  # 没显示过的窗口 `close()` 不派发 closeEvent
    shell._bridge.closeWindow()
    app.processEvents()  # 关闭是延迟一拍的（见 closeWindow 的说明），这里放它跑

    assert shell._pages == {}, "关闭后页面 Item 没被拆掉"
    assert shell.rootObject() is None, "关闭后根对象还在（QML 场景没清）"


def test_close_window_defers_so_the_qml_handler_can_return(shell, app):
    """`closeWindow()` 必须**延迟一拍**再真的关。

    它是从 QML 的 `onClicked` 调进来的，而关闭会同步拆掉 QML 场景 —— 在信号处理器
    还没返回时销毁它自己所属的对象，Qt 直接报 CRITICAL：
    「Object 0x… destroyed while one of its QML signal handlers is in progress」。
    """
    shell.show()
    shell._bridge.closeWindow()
    assert shell.rootObject() is not None, "closeWindow() 立刻就把场景拆了 —— 处理器还在栈上"
    app.processEvents()
    assert shell.rootObject() is None, "延迟一拍之后应当已经关掉"


def test_bridge_stops_notifying_qml_after_shutdown_begins(shell, monkeypatch):
    """退出期不许再发 `stateChanged` —— 那会让整个场景重算。

    外壳里几乎所有 QML 属性都挂在它上面：一发就是几百次绑定求值，
    而那时上下文正在被拆，必然成片报 null。
    """
    from core import qt_noise

    seen: list[int] = []
    shell._bridge.stateChanged.connect(lambda: seen.append(1))

    shell._bridge.notify()
    assert len(seen) == 1, "运行期 notify 应当照常发"

    monkeypatch.setattr(qt_noise, "_shutting_down", True)
    shell._bridge.notify()
    assert len(seen) == 1, "退出期 notify 不该再发"


# ── 4. 状态存取 ────────────────────────────────────────────


def test_save_and_restore_state_round_trips_the_current_page(shell):
    keys = list(_KEYS)
    shell.navigate_to(keys[-1])
    state = shell.save_state()
    assert state["current_page"] == keys[-1]

    shell.navigate_to(keys[0])
    shell.restore_state(state)
    assert shell.current_page_key() == keys[-1]


# ── 5. QML 必须干净加载 ────────────────────────────────────


def test_shell_qml_loads_without_warnings(app, mock_db, monkeypatch):
    """外壳 QML 不许有加载告警（缺 import / 绑错属性这类问题只在运行时吐一条）。"""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    monkeypatch.setattr(ShellWindow, "_init_price_check", lambda self: None)
    messages: list[str] = []

    def _handler(msg_type, context, message):
        if msg_type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            messages.append(message)

    previous = qInstallMessageHandler(_handler)
    try:
        win = ShellWindow()
        win.close()
        win.deleteLater()
    finally:
        qInstallMessageHandler(previous)

    # 只盯**我们自己的** QML：Qt 自带样式的告警（`qrc:/qt-project.org/...`）与
    # 引擎创建顺序有关，真机同序不报（见 tests/test_qml_dialogs.py 的 _is_qt_internal）。
    qml_issues = [m for m in messages if ".qml" in m and "qrc:/qt-project.org/" not in m]
    assert not qml_issues, "外壳 QML 加载有告警：\n" + "\n".join(qml_issues)


# ── 6. 两条页面钩子分发（批次 7.4 新加，都是静默失效型）────────


def test_switching_to_a_page_calls_its_on_shown_hook(shell, monkeypatch):
    """切到某页必须调它的 `on_shown`。

    批次 7.4 起工业页控制器是 `QObject`，**没有 `showEvent` 可依赖** ——
    这条分发是唯一的「页面重新可见」唤醒路径。丢了它不会报错，只是从仓库页
    改完材料倍率切回工业页时，工具栏旋钮停在旧值。
    """
    seen: list[str] = []
    for key, page in shell._pages.items():
        if page.hooks is None:
            continue
        monkeypatch.setattr(page.hooks, "on_shown", lambda k=key: seen.append(k), raising=False)

    target = next(k for k in _KEYS if k != shell.current_page_key())
    assert shell.navigate_to(target) is True
    assert seen == [target], f"切到 {target} 应当只调它的 on_shown，实际 {seen}"


def test_shutdown_hook_reaches_page_controllers(shell, monkeypatch):
    """关窗必须把页面控制器的关机钩子也走一遍。

    外壳自己的线程靠 `findChildren(QThread)` 收得到，但**页面控制器不是外壳的子对象**：
    `IndustryPage(main_window)` 的第一个参数是位置参数、不是 `parent`，所以
    `findChildren` 找不到它名下的 worker。漏掉的后果是 `QThread` 在运行中被析构 ——
    Qt 直接 `abort()`，静默死进程且不留一行日志。
    """
    called: list[str] = []
    for key, page in shell._pages.items():
        if page.hooks is None:
            continue
        monkeypatch.setattr(page.hooks, "shutdown", lambda k=key: called.append(k), raising=False)

    shell._stop_running_threads()
    expected = {k for k, p in shell._pages.items() if p.hooks is not None}
    assert set(called) == expected, f"关机钩子没覆盖到全部页面：{sorted(expected - set(called))}"


def test_shutdown_detaches_uninterruptible_worker(shell, monkeypatch):
    """关窗时收不完的后台线程必须被**摘出**外壳，否则会被连带析构 → Qt 直接 abort()。

    回归背景：`_stop_running_threads` 曾内联写 `requestInterruption() + wait(3000)`，
    超时之后**什么也不做** —— worker 仍是本窗的子对象。紧接着 `closeEvent` 拆窗，
    运行中的 QThread 被连带析构，而 Qt 对这件事的处理是 `abort()`：实测进程以
    `0xC0000409` 退出、**一行 Python traceback 都不留**，日志里只剩一对先兆
    （`QObject::killTimer: Timers cannot be stopped from another thread`）和临终通告
    （`QThread: Destroyed while thread '' is still running`）。

    为什么必须有一条：中断请求对阻塞式 worker **无效** —— `PriceUpdateWorker.run`
    跑的是 `getprices.run_price_update()`（实测一次 809 页订单簿），中途不查中断标志。
    所以「超时之后怎么办」才是唯一能防住崩溃的地方。

    这里验的是**可观察契约**「摘出去了」：不再是外壳的子对象 → 拆窗带不走它。
    没断言 `drop_worker` 被调用（那是实现细节代理）。
    """
    import time

    from PySide6.QtCore import QThread

    class _StubbornWorker(QThread):
        """无视 `requestInterruption()` —— 模拟阻塞式 ESI 拉取。"""

        def run(self) -> None:
            for _ in range(45):  # 4.5s > wait_ms(3000)，保证走「超时」分支
                time.sleep(0.1)

    monkeypatch.setattr(ShellWindow, "_init_price_check", lambda self: None)
    shell._pages.clear()  # 只关心线程收尾，绕开页面关机钩子

    w = _StubbornWorker(shell)
    w.start()
    try:
        time.sleep(0.3)
        assert w.isRunning(), "前提：worker 必须在跑"

        shell._stop_running_threads()

        assert w.isRunning(), "前提：它不该被中断请求停掉 —— 否则测的不是超时分支"
        assert w.parent() is not shell, (
            "超时后必须把线程摘出对话树（`lifecycle.drop_worker` 的 `_detach`），"
            "否则紧随其后的拆窗会连带析构一个运行中的 QThread → Qt abort()"
        )
    finally:
        w.wait(10000)  # 让它自己收尾，别把运行中的线程留给别的用例


# ── 7. 主题监听器在「窗口已销毁」时自己收敛 ────────────────────


def test_theme_change_after_the_window_is_destroyed_is_harmless(app, mock_db, monkeypatch):
    """窗口**没走 `closeEvent` 就被销毁**时，切主题不许把栈刷进日志。

    回归背景：`closeEvent` 会注销主题监听器，但那条路只覆盖正常关闭。测试与截图工具里
    大量「建窗后直接 `deleteLater()`、从不 `close()`」，于是监听器还活着、窗口的 C++ 对象
    已经没了 —— 下一次 `apply_theme` 就在 `_sync_window_color` 的 `setColor` 上撞
    `RuntimeError: Internal C++ object already deleted`，日志成片刷「主题监听器回调失败」
    （真机连跑几次快照能刷出十几条）。

    这里验的是**行为**而不是日志文本：切一次主题之后，那条已经没救的监听器应当被注销掉。
    """
    from PySide6.QtCore import QEvent

    from ui_qml.theme import registry as theme
    from ui_qml.theme.registry import apply_theme

    monkeypatch.setattr(ShellWindow, "_init_price_check", lambda self: None)
    win = ShellWindow()
    before = len(theme._theme_listeners)

    win.deleteLater()
    # ⚠️ 必须 sendPostedEvents 才真删：`processEvents()` 在嵌套层级不匹配时不处理
    # DeferredDelete（本仓在 `PageHost` 那边踩过同一条）
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    apply_theme("light")  # 不许抛

    assert len(theme._theme_listeners) < before, "已销毁窗口的监听器没有被注销，下次切主题还会再撞一次"
    del win
