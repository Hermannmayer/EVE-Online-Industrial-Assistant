"""pytest 共享配置与 fixtures"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

# 测试分档由 marker 驱动（见 scripts/run_tests.sh）：
#   fast  = 纯计算/轻服务白名单
#   ui    = Qt 界面 + 真 QThread
# validate = -m "not ui"，ui-retest = -m "ui"，二者互斥覆盖全部用例。


# ════════════════════════════════════════════════════════════════
#  跑测账本：把「一次任务跑一次测试」变成一道可执行的门
# ════════════════════════════════════════════════════════════════
#
# 约定（CLAUDE.md「测试边界」）原先只有散文，没有任何执行点 —— 同一档被跑第二遍、
# `--lf` 在没有失败项时退化成**整档**、两个整档同时对撞（实测两个 `-m ui` 一起卡在
# QQuickWidget 死锁上白烧十几分钟），这些都只在「事后自述」里才看得见。这里补三道闸：
#
#   1. 重复闸：同一档（同一 marker 整档 / 同一组文件）窗口期内已跑绿 → 拒绝启动；
#   2. 并发闸：已有整档在跑 → 拒绝再起整档（点名不同文件仍可并行）；
#   3. `--lf` 空缓存：它会退化成整档跑 → 直接拒绝。
#
# CLAUDE.md 明文允许的例外**不受闸限制**：单文件（TDD 迭代）、`-k`、具体 node id、
# 有失败项的 `--lf`。账本落在 `.pytest_cache/`（已 gitignore）。
# 逃生：`EVE_TEST_RERUN=1` 放行重复闸；`EVE_TEST_LEDGER=0` 整关。
# CI 每个 job 只跑一次 `pytest tests/`，不受影响。

_LEDGER_DIR = Path(__file__).resolve().parent.parent / ".pytest_cache"
_LEDGER_FILE = _LEDGER_DIR / "eve_test_ledger.jsonl"
_ACTIVE_DIR = _LEDGER_DIR / "eve_test_active"
_REPEAT_WINDOW_S = 30 * 60
_ACTIVE_STALE_S = 2 * 60 * 60
_STATE: dict = {}


def _opt(config, name, default=None):
    """取 pytest 选项；插件被禁用（如 `-p no:cacheprovider`）时不炸。"""
    try:
        return config.getoption(name)
    except Exception:
        return default


def _targets(config) -> list[str]:
    return [str(a) for a in config.args if not str(a).startswith("-")]


def _is_whole(config) -> bool:
    targets = _targets(config)
    return not targets or targets in (["tests"], ["tests/"])


def _run_key(config) -> str:
    """档位键：整档按 marker 表达式的原文分，点名按文件集合分。"""
    expr = " ".join(str(_opt(config, "markexpr") or "").split())
    if expr:
        return f"marker:{expr}" if _is_whole(config) else "files:" + "|".join(sorted(_targets(config)))
    return "full" if _is_whole(config) else "files:" + "|".join(sorted(_targets(config)))


def _is_narrow(config) -> bool:
    """CLAUDE.md 明文允许的例外：单文件 TDD、`-k`、具体 node id、有失败项的 `--lf`。"""
    if _opt(config, "lf") or _opt(config, "keyword"):
        return True
    targets = _targets(config)
    if any("::" in t for t in targets):
        return True
    return len(targets) == 1 and targets[0].endswith(".py")


def _ledger_rows() -> list[dict]:
    try:
        text = _LEDGER_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _active_rows() -> list[dict]:
    """当前活跃的跑测记录；顺手清掉被强杀留下的僵尸条目。"""
    if not _ACTIVE_DIR.is_dir():
        return []
    now = time.time()
    rows = []
    for path in list(_ACTIVE_DIR.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if now - float(row.get("started") or 0) > _ACTIVE_STALE_S:
            path.unlink(missing_ok=True)
            continue
        rows.append(row)
    return rows


def _hhmm(ts) -> str:
    return time.strftime("%H:%M:%S", time.localtime(float(ts or 0)))


def _refuse(reason: str) -> None:
    pytest.exit(
        f"\n[跑测账本] {reason}\n"
        "  约定见 CLAUDE.md「测试边界」；逃生："
        "EVE_TEST_RERUN=1（放行重复闸）/ EVE_TEST_LEDGER=0（整关）\n",
        returncode=2,
    )


# ════════════════════════════════════════════════════════════════
#  跑测环境守卫：Windows 上禁止用 offscreen 平台
# ════════════════════════════════════════════════════════════════
#
# 本仓用 `QQuickWidget` 承载 QML 页面（`ui_qml/host.py::PageHost`）。**Windows +
# `QT_QPA_PLATFORM=offscreen`** 这个组合下，`PageHost.setSource()` 会卡在 Qt 的 QML 线程上
# 永远不返回（`QQmlThread` 空转、无 Python 栈、换哪个对话框都能中）：
#
#   Thread 0x... [QQmlThread] (most recent call first):
#     <no Python frame>
#   Thread 0x... (most recent call first):
#     File "ui_qml/host.py", line 66 in __init__      ← self.setSource(...)
#
# 2026-09-27 记过一次（当时把整个 `ui-retest` 档拖成无摘要），2026-10-05 本机又踩：
# 同一个 `tests/test_qt_noise.py` 真平台 **2.36s 通过**、offscreen **卡死**；
# `tests/test_qml_dialogs.py` 同样是「offscreen 卡第一个用例、真平台全绿」。
#
# 这条规矩原先只写在 `docs/dev/testing.md` 的散文里 —— 没人看，所以这里做成**硬门**：
# 与其让人在「随机卡死、没有栈」上白烧半小时，不如启动就拒绝并说清原因。
#
# Linux CI（无显示器）**必须**用它，且 CI 只跑 `-m "not ui"`（非 QML 档）—— 故守卫只在
# Windows 生效。确要压过去做实验：`EVE_ALLOW_OFFSCREEN_TESTS=1`。

_WINDOWS = "win32"
_OFFSCREEN_ALLOW_ENV = "EVE_ALLOW_OFFSCREEN_TESTS"


def offscreen_is_forbidden(platform_name: str, qpa_platform: str, allow_env: str) -> bool:
    """这次跑测是否该因 offscreen 平台被拒（纯函数，便于单测）。

    `allow_env` 传 `EVE_ALLOW_OFFSCREEN_TESTS` 的值：`"1"` = 显式放行。
    """
    if platform_name != _WINDOWS:
        return False
    if (qpa_platform or "").strip().lower() != "offscreen":
        return False
    return allow_env != "1"


def _refuse_offscreen() -> None:
    pytest.exit(
        "\n[跑测环境] 检测到 Windows + QT_QPA_PLATFORM=offscreen —— 这个组合下 QQuickWidget 会卡死在\n"
        "  `PageHost.setSource()`（Qt 的 QML 线程空转、没有 Python 栈；现场记录见 tests/conftest.py）。\n"
        "  本仓测试**不需要**离屏：Windows 上默认就跑真平台（多数用例不 show()，少数窗口一闪而过）。\n"
        "  请去掉该环境变量后重跑，例如：\n"
        "      Remove-Item Env:\\QT_QPA_PLATFORM      # PowerShell\n"
        "  确要压过去做实验：EVE_ALLOW_OFFSCREEN_TESTS=1\n",
        returncode=2,
    )


def pytest_configure(config) -> None:
    """会话级 Qt 消息处理器：丢掉 **Qt 自带 QML** 的告警（判据与生产同一份）。

    生产在 `Main.py` 里装处理器、且只在「退出已开始」之后丢这类噪音
    （`core.qt_noise` 说明：FluentWinUI3 自己的 `qrc:` 文件在引擎拆除期成片报 null，
    不是我们的 QML 写错了）。**测试里要一直丢**：测试就是「建窗口 → `deleteLater()`」
    的循环，析构随时发生，而 `begin_shutdown()` 只在 `closeEvent` 里调，于是同一批
    噪音一直刷 —— 本机整档 `-m ui` 实测 **6 MB stderr**，既拖慢跑测、又把真正的告警
    埋掉（`ci.yml` 还记过「管道写满会让 QML 线程与主线程死锁」）。我们自己 `.qml` 的
    告警一条都不丢。

    其余消息照生产的做法转给 `core.logger`，测试输出与真机同形同源。
    """
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    from core import qt_noise
    from core.logger import log

    def _handler(msg_type, _context, message: str) -> None:
        if qt_noise.is_qt_internal_qml(str(message)):
            return
        if msg_type == QtMsgType.QtDebugMsg:
            log.debug(message)
        elif msg_type == QtMsgType.QtWarningMsg:
            log.warning(message)
        elif msg_type == QtMsgType.QtCriticalMsg:
            log.error(message)
        elif msg_type == QtMsgType.QtFatalMsg:
            log.critical(message)

    qInstallMessageHandler(_handler)


def _drop_active_entry() -> None:
    entry = _STATE.pop("entry", None)
    if entry is None:
        return
    try:
        entry.unlink(missing_ok=True)
    except OSError as exc:
        print(f"[跑测账本] 摘除活跃标记失败：{exc}", file=sys.stderr)


def _enter_test_run_gate(config) -> None:
    if _opt(config, "collectonly"):
        return
    # 平台守卫**不受账本开关影响**：它是「换了平台就必挂」的硬伤，
    # 不是「同一档别跑第二遍」的流程约定。
    if offscreen_is_forbidden(
        sys.platform, os.environ.get("QT_QPA_PLATFORM", ""), os.environ.get(_OFFSCREEN_ALLOW_ENV, "")
    ):
        _refuse_offscreen()
    if os.environ.get("EVE_TEST_LEDGER") == "0":
        return
    key = _run_key(config)
    narrow = _is_narrow(config)
    whole = _is_whole(config)

    cache = getattr(config, "cache", None)
    lastfailed = (cache.get("cache/lastfailed", {}) or {}) if cache is not None else {}
    if _opt(config, "lf") and not lastfailed:
        _refuse("`--lf` 现在没有失败项可跑 —— pytest 会退化成**整档**跑（踩过这个坑）。请点名 node id，或先让它红。")

    for row in _active_rows():
        if row.get("key") == key:
            _refuse(f"同一档已经在跑：{key}（pid {row.get('pid')}，起于 {_hhmm(row.get('started'))}）。")
        if whole and row.get("whole"):
            _refuse(
                f"已有整档在跑（{row.get('key')}，pid {row.get('pid')}，起于 {_hhmm(row.get('started'))}）"
                "—— 两个整档对撞只会互相拖慢，Qt 档还会一起卡死。等它跑完，或点名不同文件并行。"
            )

    if not narrow and not os.environ.get("EVE_TEST_RERUN"):
        now = time.time()
        for row in reversed(_ledger_rows()):
            if float(row.get("ts") or 0) < now - _REPEAT_WINDOW_S:
                break
            if row.get("key") == key and row.get("ok"):
                _refuse(
                    f"这一档刚跑绿过：{key} @ {_hhmm(row.get('ts'))}（{row.get('summary')}）。"
                    "「一次任务跑一次测试」—— 不要为「确认一下没坏」重跑已经绿过的档。"
                )

    _ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    entry = _ACTIVE_DIR / f"{os.getpid()}.json"
    entry.write_text(
        json.dumps({"pid": os.getpid(), "key": key, "whole": whole, "started": time.time()}), encoding="utf-8"
    )
    _STATE.update(entry=entry, key=key, narrow=narrow)


def _leave_test_run_gate(session, exitstatus) -> None:
    _drop_active_entry()
    key = _STATE.pop("key", None)
    narrow = _STATE.pop("narrow", False)
    if key is None or narrow:
        return  # 例外档（单文件 / -k / node id / --lf）不入账，免得挡住后续
    collected = int(getattr(session, "testscollected", 0) or 0)
    failed = int(getattr(session, "testsfailed", 0) or 0)
    ok = int(exitstatus) == 0 and not failed
    summary = f"{collected - failed} passed" if ok else f"{failed} failed / exit {int(exitstatus)}（{collected} 条）"
    try:
        _LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        with _LEDGER_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "key": key, "ok": bool(ok), "summary": summary}) + "\n")
    except OSError as exc:
        print(f"[跑测账本] 写账本失败：{exc}", file=sys.stderr)


def pytest_sessionstart(session) -> None:
    try:
        _enter_test_run_gate(session.config)
    except BaseException:
        _drop_active_entry()
        raise


def pytest_sessionfinish(session, exitstatus) -> None:
    """只在**测试真的跑过**时记账 —— 收集期就退出的（UsageError / 收集失败）不算一次跑测。"""
    if _opt(session.config, "collectonly"):
        _drop_active_entry()
        _STATE.clear()
        return
    _teardown_qt_leftovers()
    _leave_test_run_gate(session, exitstatus)


def _teardown_qt_leftovers() -> None:
    """会话结束前，把还活着的 QML 宿主 / 顶层窗口在**事件循环还在**的时候拆掉。

    为什么：Qt 在解释器退出阶段按自己的顺序销毁残留对象，顺序不受我们控制。整档
    `-m ui`（58 个模块）实测会在**测试全部跑完、摘要都打出来之后**以 `0xC000041D`
    （回调里未处理异常）收场 —— 拿到 1156 passed 却拿不到退码 0，CI 照样判红。
    6 个重 UI 文件一起跑是干净的（252 passed / exit 0），只有攒到整档才出。

    这段只做「关窗 → 清 DeferredDelete → 跑一轮事件循环」，不改任何业务状态：
    测试用的 settings / 窗口几何在 `isolate_*` fixture 里已经指向临时文件。
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QGuiApplication

    app = QApplication.instance()
    if app is None:
        return
    for window in list(QGuiApplication.topLevelWindows()):
        window.close()
    for widget in list(app.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def reset_db_locks_each_test():
    """每次测试后重置 per-DB 写锁。

    services.db_locks 的 asyncio.Lock 是模块级持久，会绑定首次使用的事件循环；
    pytest-asyncio 每个测试独立循环，跨测试复用同一把锁会抛
    "bound to a different event loop"，故每个测试结束清空。
    """
    yield
    from services.db_locks import reset_db_locks

    reset_db_locks()


def _refuse_network(*args, **kwargs):
    """应用**自动**发起的下载路径：测试里一律空转。"""
    return None


@pytest.fixture(autouse=True)
def no_auto_price_download(monkeypatch):
    """阻断应用**自动发起**的网络：价格检查/下载、SDE/ESI 初始化。

    原先这里 patch 的是 `MainWindow._init_price_check` —— Widgets 外壳的一个私有方法。
    外壳换成 QML（批次 6.1）之后那个 patch 点**直接消失**，而它在 autouse fixture 里，
    等于每个测试的 setup 都炸。教训：**别把全局安全网挂在某一层外壳的私有方法上**。

    现在挂在**会自己发请求的那几个入口**上（两条价格 worker + 价格更新服务 +
    工业数据 worker），与外壳无关、与页面无关：谁在什么时候起线程都拦得住。

    **不**在 `aiohttp.ClientSession` 这一层封：那样会把 `test_client.py` /
    `test_price_history.py` 这些「用 mock 会话测客户端本身」的用例一起打挂
    —— 它们要的正是真实的 ClientSession 语义。

    **工业数据 worker（2026-10-01 补）**：`IndustryPage.__init__` 排了
    `QTimer.singleShot(200, _check_industry_data)`；没有本地 `database/reference.db`
    时（CI）必然判定数据缺失、起 `IndustryDataWorker`（QThread）去拉 ESI。线程会一直跑，
    而页面随用例析构 → `QThread: Destroyed while thread '' is still running` 直接把
    整个进程 abort（Windows `0xC0000409` / Linux SIGABRT），同进程**后续**用例一并陪葬
    （实测：`test_qt_noise.py` 那条建外壳的用例会把 `test_research_calculator.py` 的 SCI
    两条与 `test_watchlist_manager.py` 带红）。这里让它空转即可。
    """
    from services.importers import getprices
    from ui_qml.workers import industry_page_workers, main_window_workers

    monkeypatch.setattr(main_window_workers.PriceCheckWorker, "run", _refuse_network)
    monkeypatch.setattr(main_window_workers.PriceUpdateWorker, "run", _refuse_network)
    monkeypatch.setattr(getprices, "run_price_update", _refuse_network)
    monkeypatch.setattr(industry_page_workers.IndustryDataWorker, "run", _refuse_network)
    yield


@pytest.fixture(autouse=True)
def _reset_qt_noise_state():
    """复位 `core.qt_noise` 的退出标记。

    它是**进程级全局**：某个用例跑过 `begin_shutdown()`（构造外壳并关窗就会）之后，
    同进程后续用例的 `ShellWindowBridge.notify()` 会静默变成空操作 —— 表现为
    「后面的外壳用例莫名其妙拿不到 QML 更新」，且很难查。每个用例结束复位。
    """
    yield
    from core import qt_noise

    qt_noise._shutting_down = False


@pytest.fixture(autouse=True)
def _flush_deferred_deletes():
    """每个用例结束后把 `DeferredDelete` 事件清干净 —— 别把 QML 宿主堆到下一次清。

    QML 宿主的析构走 `deleteLater()`，而它**要等事件循环处理 `DeferredDelete` 才会真删**。
    测试之间没人跑事件循环（pytest 也不跑），于是：

    - 每个用例 `deleteLater()` 掉的对话框/页面/外壳都被搁置；
    - 攒到 `tests/test_qml_shell.py::test_theme_change_after_the_window_is_destroyed_is_harmless`
      里那句 `app.sendPostedEvents(None, DeferredDelete)` —— 那是**整档里第一次真正清账**，
      一次性销毁几十个模块累积下来的上百个 QML 宿主与引擎（每个都带自己的 `QQmlEngine`
      和 QML 线程）→ 直接卡死（2026-10-05 整档 `-m ui` 复现：stdout 停在那个用例、
      `faulthandler_timeout=120` 整点超时、栈在 `sendPostedEvents`）。

    每个用例结束时清一次，「一次清一批」变成「一次清一个」，卡死的前提就不成立了。
    顺带的好处：上一个用例的窗口不会活到下一个用例（主题/置顶这类进程级状态更干净）。

    ⚠️ **只 `sendPostedEvents(DeferredDelete)`，不跑 `processEvents()`**：要的只是把
    `deleteLater()` 排下的删除事件清掉，而 `processEvents()` 会把**任意**排队工作也跑一遍
    —— 那等于在 teardown 里跑业务事件（QThread 收尾、信号回调都可能被提前触发），
    实测把「碰已析构对象」的窗口放大到别的用例头上（2026-10-05 审计：崩溃落在一个
    只跑 worker 的用例的 teardown，末句是 `QObject::disconnect: Unexpected nullptr`）。
    `ShellWindow._teardown_qml` 的注释也写着：真删 `deleteLater` 靠 `sendPostedEvents`，
    `processEvents()` 在嵌套层级不匹配时**不**处理它。
    """
    yield
    app = QApplication.instance()
    if app is None:
        return
    from PySide6.QtCore import QEvent

    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def no_auto_daily_backup(monkeypatch):
    """测试里绝不跑「每天一次的用户数据备份」—— 它是**写磁盘 + 写 settings.json** 的副作用。

    回归背景（2026-09-28）：`ShellWindow.__init__` 挂了
    `QTimer.singleShot(1200, _maybe_daily_backup)`，测试的事件循环只要跑到 1.2s 就会触发：

    - 往**真实**的 `database/backups/user/` 写备份（`mock_db` 不替换 `DB_PATH_MAP`）；
    - 调 `user_settings.set_last_backup_date` → 触发 `save_settings`，于是
      `test_shell_state.py::test_pin_is_session_only_and_never_restored`（它断言
      「置顶不该落盘 ⇒ save_settings 一次都不该被调」）被这条无关的写入搞红。

    ⚠️ 只关这**一个**开关，不动 `DB_PATH_MAP`（动它会构造出缺表的空库，把页面建页打挂）。
    """
    monkeypatch.setattr("services.user_settings.get_backup_enabled", lambda: False)


@pytest.fixture(autouse=True)
def isolate_user_settings(tmp_path, monkeypatch):
    """把 settings.json 指向临时文件 —— 测试绝不写用户真实数据。

    回归背景：tests/test_ui_main_window.py 用 patch 替换 user_settings.load_settings
    后构造 MainWindow；MainWindow.__init__ → theme.apply_theme → save_theme_preference
    → save_settings（read-modify-write）此时读到的是 patch 的返回值，于是把真实
    data/settings.json 全量覆盖成那个字典（用户的默认机库等设置被擦除）。
    """
    monkeypatch.setattr("services.user_settings.SETTINGS_PATH", str(tmp_path / "settings.json"))
    yield


@pytest.fixture(autouse=True)
def isolate_window_geometry(tmp_path, monkeypatch):
    """把窗口几何文件指向临时文件 —— 测试绝不写用户真实的 `data/window_geometry.json`。

    回归背景：`ShellWindow.__init__` 无条件 `theme.set_geometry_file(window_geometry_file())`，
    而 `closeEvent` 会 `save_window_geometry`。跑一次 UI 档就等于把测试平台下的窗口坐标
    （离屏虚拟屏只有 800x800）写回用户真实文件；该文件在开发机上还是**跨 worktree 的硬链接**，
    于是「测试把主窗口挪到屏幕外」这种故障能被一次测试跑出来。

    patch 的是 `ui_qml.shell_window` 里的模块级名字（`shell_window.py:32` 是
    `from core.paths import … window_geometry_file`，import 时已绑定），这样才命中
    `__init__` 里的那次调用。
    """
    monkeypatch.setattr("ui_qml.shell_window.window_geometry_file", lambda: str(tmp_path / "window_geometry.json"))
    yield


# ════════════════════════════════════════════════════════════════
#  辅助：创建标准临时数据库套件
# ════════════════════════════════════════════════════════════════


def _create_temp_databases(tmpdir: str):
    """在 tmpdir 中创建 ref/mkt/bp/user 四个数据库，返回 {alias: path} 字典"""
    ref_path = Path(tmpdir) / "reference.db"
    mkt_path = Path(tmpdir) / "market.db"
    bp_path = Path(tmpdir) / "blueprint.db"
    user_path = Path(tmpdir) / "user.db"

    # ── reference.db ──
    conn = sqlite3.connect(str(ref_path))
    conn.executescript("""
        CREATE TABLE item (
            type_id INTEGER PRIMARY KEY,
            zh_name TEXT,
            en_name TEXT,
            volume REAL DEFAULT 1.0,
            market_group_id INTEGER
        );
        CREATE TABLE industry_system_costs (
            solar_system_id INTEGER,
            activity TEXT,
            cost_index REAL
        );
        -- 市场分类树：4/9 是顶层，100 挂在 4 下面（跨区域排行的分类筛选走递归 CTE）
        CREATE TABLE market_tree (
            market_group_id INTEGER PRIMARY KEY,
            parent_group_id INTEGER,
            zh_name TEXT,
            en_name TEXT
        );
        INSERT INTO market_tree VALUES (4, NULL, '舰船', 'Ships');
        INSERT INTO market_tree VALUES (9, NULL, '舰船装备', 'Ship Equipment');
        INSERT INTO market_tree VALUES (19, NULL, '贸易货物', 'Trade Goods');
        INSERT INTO market_tree VALUES (100, 4, '护卫舰', 'Frigates');
        INSERT INTO item (type_id, zh_name, en_name, volume, market_group_id)
            VALUES (1001, '三钛合金', 'Tritanium', 0.01, 19);
        INSERT INTO item (type_id, zh_name, en_name, volume, market_group_id)
            VALUES (1002, '类银超金属', 'Pyerite', 0.01, 19);
        INSERT INTO item (type_id, zh_name, en_name, volume, market_group_id)
            VALUES (2001, '渡鸦级', 'Raven', 50000, 100);
        INSERT INTO item (type_id, zh_name, en_name, volume, market_group_id)
            VALUES (2002, '无人机', 'Drone', 5, 9);
    """)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    # ── market.db ──
    conn = sqlite3.connect(str(mkt_path))
    conn.executescript("""
        CREATE TABLE market_prices (
            type_id INTEGER,
            region_id INTEGER,
            buy_price REAL,
            sell_price REAL,
            adjusted_price REAL DEFAULT 0.0,
            buy_volume INTEGER DEFAULT 0,
            sell_volume INTEGER DEFAULT 0,
            fetch_time TEXT
        );
        -- 材料价格 (Jita region 10000002)
        INSERT INTO market_prices VALUES (1001, 10000002, 4.0, 5.0, 0.0, 10000000, 8000000, '2026-01-01 00:00:00');
        INSERT INTO market_prices VALUES (1002, 10000002, 8.0, 9.0, 0.0, 5000000, 4000000, '2026-01-01 00:00:00');
        -- 成品价格 (Jita region 10000002)
        INSERT INTO market_prices VALUES (2001, 10000002, 50000000, 55000000, 50000000, 1000000, 800000, '2026-01-01 00:00:00');
        INSERT INTO market_prices VALUES (2002, 10000002, 100000, 120000, 110000, 500000, 400000, '2026-01-01 00:00:00');
        -- 挂单量快照（跨区域排行的「B侧挂单变化」读它；日期由各用例自己插）
        CREATE TABLE market_volume_snapshots (
            type_id INTEGER NOT NULL,
            region_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            buy_price REAL DEFAULT 0,
            sell_price REAL DEFAULT 0,
            buy_volume BIGINT DEFAULT 0,
            sell_volume BIGINT DEFAULT 0,
            PRIMARY KEY (type_id, region_id, date)
        );
    """)
    conn.execute("PRAGMA user_version = 4")  # 与 DB_SCHEMA_VERSIONS["mkt"] 同步（见 docs/dev/schema-migration.md）
    conn.commit()
    conn.close()

    # ── blueprint.db ──
    conn = sqlite3.connect(str(bp_path))
    conn.executescript("""
        CREATE TABLE blueprint_activities (
            blueprint_type_id INTEGER,
            activity TEXT,
            time INTEGER
        );
        CREATE TABLE blueprint_products (
            blueprint_type_id INTEGER,
            activity TEXT,
            product_type_id INTEGER,
            quantity INTEGER
        );
        CREATE TABLE blueprint_materials (
            blueprint_type_id INTEGER,
            activity TEXT,
            material_type_id INTEGER,
            quantity INTEGER,
            wastefactor INTEGER DEFAULT 10
        );
        -- 制造所需技能（评分链路会读它算「每级 -1% 生产时间」；本夹具留空 = 无减免）
        CREATE TABLE blueprint_skills (
            blueprint_type_id INTEGER,
            activity TEXT,
            skill_type_id INTEGER,
            level INTEGER,
            PRIMARY KEY (blueprint_type_id, activity, skill_type_id)
        );
        -- 渡鸦级蓝图: 需要 1000 Trit + 500 Pyer, 产出 1 个, 时间 3600s
        INSERT INTO blueprint_activities VALUES (3001, 'manufacturing', 3600);
        INSERT INTO blueprint_activities VALUES (3002, 'manufacturing', 600);
        INSERT INTO blueprint_products VALUES (3001, 'manufacturing', 2001, 1);
        INSERT INTO blueprint_products VALUES (3002, 'manufacturing', 2002, 1);
        INSERT INTO blueprint_materials VALUES (3001, 'manufacturing', 1001, 1000, 10);
        INSERT INTO blueprint_materials VALUES (3001, 'manufacturing', 1002, 500, 10);
        INSERT INTO blueprint_materials VALUES (3002, 'manufacturing', 1001, 100, 10);
    """)
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    # ── user.db ──
    conn = sqlite3.connect(str(user_path))
    conn.execute("PRAGMA user_version = 20")
    conn.commit()
    conn.close()

    return {
        "ref": str(ref_path),
        "mkt": str(mkt_path),
        "bp": str(bp_path),
        "user": str(user_path),
    }


def _create_user_v4(db_path):
    """构造 v4 的 user.db（模拟 ALTER 迁移缺口库）。

    - hangars：**无** solar_system_id 列（v5 迁移待加）
    - production_plans：**显式不含** facility_cost_mult 列
      （该列现仅存在于 CREATE TABLE 路径，v2→v3 ALTER 迁移遗漏 → v4→v5 需补）
    - 已含 v3→v4 执行列（assigned_blueprint_id / mat_hangar_id / material_short）
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE hangars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            notes TEXT DEFAULT ''
        );
        CREATE TABLE production_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_type_id INTEGER NOT NULL,
            product_name TEXT,
            blueprint_type_id INTEGER,
            runs INTEGER DEFAULT 1,
            parallels INTEGER DEFAULT 1,
            me_level INTEGER DEFAULT 0,
            te_level INTEGER DEFAULT 0,
            mat_hub TEXT DEFAULT 'Jita',
            sell_hub TEXT DEFAULT 'Jita',
            facility TEXT DEFAULT '',
            char_name TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            profit REAL DEFAULT 0,
            margin REAL DEFAULT 0,
            score REAL DEFAULT 0,
            material_cost REAL DEFAULT 0,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            calculated_time REAL DEFAULT 0,
            notes TEXT DEFAULT '',
            group_number INTEGER DEFAULT 0,
            sub_level INTEGER DEFAULT 0,
            output_location TEXT DEFAULT '',
            market_margin REAL DEFAULT 0,
            personal_margin REAL DEFAULT 0,
            daily_output REAL DEFAULT 0,
            materials_ready INTEGER DEFAULT 0,
            iskph REAL DEFAULT 0,
            deposit_hangar_id INTEGER DEFAULT NULL,
            deposited INTEGER DEFAULT 0,
            assigned_blueprint_id INTEGER DEFAULT NULL,
            mat_hangar_id INTEGER DEFAULT NULL,
            material_short TEXT DEFAULT ''
        );
        """
    )
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()


def _create_user_v5(db_path):
    """构造 v5 的 user.db（hangars 含 solar_system_id、production_plans 含 v5 全列，无 v6 设施列）"""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE hangars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            notes TEXT DEFAULT '',
            solar_system_id INTEGER DEFAULT NULL
        );
        CREATE TABLE production_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_type_id INTEGER NOT NULL,
            product_name TEXT,
            blueprint_type_id INTEGER,
            runs INTEGER DEFAULT 1,
            parallels INTEGER DEFAULT 1,
            me_level INTEGER DEFAULT 0,
            te_level INTEGER DEFAULT 0,
            mat_hub TEXT DEFAULT 'Jita',
            sell_hub TEXT DEFAULT 'Jita',
            facility TEXT DEFAULT '',
            char_name TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            profit REAL DEFAULT 0,
            margin REAL DEFAULT 0,
            score REAL DEFAULT 0,
            material_cost REAL DEFAULT 0,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            facility_cost_mult REAL DEFAULT 1.0,
            calculated_time REAL DEFAULT 0,
            notes TEXT DEFAULT '',
            group_number INTEGER DEFAULT 0,
            sub_level INTEGER DEFAULT 0,
            output_location TEXT DEFAULT '',
            market_margin REAL DEFAULT 0,
            personal_margin REAL DEFAULT 0,
            daily_output REAL DEFAULT 0,
            materials_ready INTEGER DEFAULT 0,
            iskph REAL DEFAULT 0,
            deposit_hangar_id INTEGER DEFAULT NULL,
            deposited INTEGER DEFAULT 0,
            assigned_blueprint_id INTEGER DEFAULT NULL,
            mat_hangar_id INTEGER DEFAULT NULL,
            material_short TEXT DEFAULT '',
            solar_system_id INTEGER DEFAULT NULL
        );
        """
    )
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════
#  Mock helpers
# ════════════════════════════════════════════════════════════════


def _mock_db_manager():
    """返回一个用于替换 database_manager.get_db 的 mock DatabaseManager"""
    manager = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    conn.cursor.return_value = cursor
    conn.executescript = MagicMock()
    conn.execute.return_value = cursor

    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    manager.connect.return_value = cm
    manager.direct_connect.return_value = conn
    return manager


# ════════════════════════════════════════════════════════════════
#  Fixtures — Session / Qt
# ════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def qapp():
    """提供全局 QApplication 实例，供 PySide6 UI 测试使用"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    # QML 控件样式必须与生产一致（见 Main.py 同名调用）。
    # 不设会用平台默认样式 —— Windows 上是**原生**样式，它禁止自定义
    # background/indicator/contentItem，会为 FTextField/FSpinBox 等自定义组件
    # 刷「The current style does not support customization of this control」告警，
    # 且渲染结果与真实运行不同。必须在加载任何 QML 之前设置。
    from PySide6.QtQuickControls2 import QQuickStyle

    QQuickStyle.setStyle("FluentWinUI3")
    yield app


@pytest.fixture(scope="session")
def app(qapp):
    """qapp 的别名，与默认 fixture 命名保持一致"""
    yield qapp


# ════════════════════════════════════════════════════════════════
#  Fixtures — Mock Database
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_db():
    """在 with 块内将 DB 相关依赖替换为 mock"""
    mock_mgr = _mock_db_manager()

    # 清除数据库管理器的线程局部连接缓存，防止旧连接指向已清理的 tempdir
    from services.database_manager import get_db as _get_db

    _scoring_db = _get_db()
    _scoring_db._local.connections.clear() if hasattr(_scoring_db._local, "connections") else None

    # plan_service 用 `from core.container import get_container` 绑定旧引用，
    # patch core.container 无法覆盖已导入模块里的名字；须同时 patch 该模块引用，
    # 否则依赖 load_plans 的 UI 测试会穿透到真实库（no such table）。
    #
    # ⚠️ `AppContainer` 是**进程级单例**，`db` / `item_repo` / `scoring_service` … 都是
    # 「解析一次就永久缓存」。`patch("core.container.get_container")` 只堵住这一个入口：
    # 窗口期内若有代码经 `bootstrap.container.get_container`（`core.container` 只是它的
    # 转发）或经**早已绑好的模块级引用**拿到那个**真容器**，真容器的 `_db` 就会被解析成
    # mock 并留在单例里 —— 窗口关掉之后，同进程后续用例继续拿到 mock db。
    # 实测（2026-10-01，无本地库的 CI 环境）：`test_qt_noise.py` 那条建 QML 外壳的用例
    # 之后，`test_watchlist_manager.py` 的 CRUD 拿到 MagicMock 游标
    # （`'>' not supported between 'MagicMock' and 'int'`）、`test_research_calculator.py`
    # 的 SCI 查询退化成默认值（`assert 54.62 > 54.62`）。
    # 因此：把真容器的缓存状态整个存下来，窗口关掉后原样放回。
    from bootstrap import container as _bootstrap_container

    real = _bootstrap_container._container
    saved_state = dict(vars(real)) if real is not None else None

    with (
        patch("services.database_manager.get_db", return_value=mock_mgr),
        patch("core.container.get_container") as mock_cont,
        patch("services.plan_service.get_container") as mock_plan_cont,
    ):
        cont = mock_cont.return_value
        cont.db = mock_mgr
        mock_plan_cont.return_value = cont
        try:
            yield
        finally:
            if real is not None and saved_state is not None:
                vars(real).clear()
                vars(real).update(saved_state)
            elif real is None and _bootstrap_container._container is not None:
                # 真容器是这段窗口里第一次被建出来的（`_db` 已经是 mock）→ 丢掉这个单例，
                # 下次 `get_container()` 会重新建一个干净的。
                _bootstrap_container._container = None


# ════════════════════════════════════════════════════════════════
#  Fixtures — 真实临时数据库
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def temp_db():
    """创建临时 SQLite 数据库（含标准测试数据），返回 DatabaseManager 实例。

    数据包含:
      - item 表: 三钛合金(1001), 类银超金属(1002), 渡鸦级(2001), 无人机(2002)
      - market_prices: Jita 区域买卖价格
      - blueprint: 渡鸦级蓝图(3001) + 无人机蓝图(3002)
    """
    from services.database_manager import DB_PATH_MAP, DatabaseManager, get_db

    tmpdir = tempfile.mkdtemp(prefix="eve_test_")
    db_paths = _create_temp_databases(tmpdir)

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP.update(db_paths)

    db = DatabaseManager()
    yield db

    # 恢复 & 清理
    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    get_db().close_all()  # 清共享单例缓存的临时库连接，防泄漏污染后续测试
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def db_manager():
    """创建一个使用临时数据库的 DatabaseManager，与 temp_db 功能相同。

    区别：此 fixture 不预填充测试数据，适用于需要纯净数据库的测试。
    """
    from services.database_manager import DB_PATH_MAP, DatabaseManager, get_db

    tmpdir = tempfile.mkdtemp(prefix="eve_dbmgr_")
    ref_path = Path(tmpdir) / "reference.db"
    mkt_path = Path(tmpdir) / "market.db"
    bp_path = Path(tmpdir) / "blueprint.db"
    user_path = Path(tmpdir) / "user.db"

    # 创建空数据库（仅建表，不插入数据）
    for p in (ref_path, mkt_path, bp_path, user_path):
        conn = sqlite3.connect(str(p))
        conn.close()

    db_paths = {"ref": str(ref_path), "mkt": str(mkt_path), "bp": str(bp_path), "user": str(user_path)}

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP.update(db_paths)

    db = DatabaseManager()
    yield db

    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    get_db().close_all()  # 清共享单例缓存的临时库连接，防泄漏污染后续测试
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def sample_char_config():
    """返回一个标准的角色配置 dict，含满级技能和 Jita 声望"""
    return {
        "skills": {
            "工业理论": 5,
            "高级工业理论": 5,
            "经纪人关系学": 5,
            "高级经纪人关系学": 5,
            "会计学": 5,
        },
        "market": {
            "jita": {"faction_standing": 6.7, "corp_standing": 5.0},
        },
    }


@pytest.fixture
def sample_market_prices(temp_db):
    """插入示例市场价格数据并返回 type_id。

    使用 temp_db fixture（含完整测试数据库），直接返回无人机 type_id=2002。
    """
    return 2002


# ════════════════════════════════════════════════════════════════
#  Fixtures — UI Pages
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def main_window(app, mock_db, monkeypatch):
    """主窗口（**QML 外壳**）—— 批次 6.1 起主窗口就是 `ui_qml.shell_window.ShellWindow`。

    名字仍叫 `main_window`：几十个用例按这个名字取「主窗口」，改名的收益抵不上改动面。
    `_init_price_check` 由全局的 `no_auto_price_download` 掐掉，这里不用再管。
    """
    from ui_qml.shell_window import ShellWindow

    window = ShellWindow()
    yield window
    window.close()


@pytest.fixture
def industry_page(main_window):
    """创建工业页**控制器**（`IndustryPage`）用于 UI 测试。

    批次 7.4 起它是纯 `QObject` 控制器：**不再自建 QML 宿主**（`_host` / `make_qml_host`
    已删），渲染面由外壳决定。需要渲染 `IndustryPage.qml` 的用例得自己造宿主
    （`ui_qml.host.PageHost`，或外壳的 `ui_qml.registry.build_qml_page`）。
    """
    from ui_qml.views.industry_view import IndustryPage

    page = IndustryPage(main_window)
    yield page
    page.deleteLater()


# ════════════════════════════════════════════════════════════════
#  共享蓝图测试数据 — plan_decompose / parent_decompose 等复用
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def seed_bp_blueprints():
    """返回在指定 connection 上建立 bp 蓝图表并注入渡鸦级/组件数据的函数。

    bp3001 → 产物 2001，材料 1001×5 + 35×10；bp3002 → 产物 1001，材料 34×2。
    跨测试文件共享，避免 _build_dbs 逐行复制。
    """

    def _seed(conn):
        conn.execute(
            "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute(
            "CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, "
            "material_type_id INTEGER, quantity INTEGER)"
        )
        # 评分链路会读 blueprint_skills 算所需技能的 1%/级时间减免；留空 = 无减免
        conn.execute(
            "CREATE TABLE blueprint_skills (blueprint_type_id INTEGER, activity TEXT, "
            "skill_type_id INTEGER, level INTEGER)"
        )
        conn.execute("CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time REAL)")
        conn.execute("INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1)")
        conn.execute("INSERT INTO blueprint_products VALUES (3002,'manufacturing',1001,1)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',1001,5)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',35,10)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3002,'manufacturing',34,2)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3001,'manufacturing',3600)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3002,'manufacturing',1800)")

    return _seed
