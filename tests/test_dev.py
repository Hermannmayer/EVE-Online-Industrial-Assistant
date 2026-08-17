"""Tests for dev.py hot-reload launcher."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import dev

pytestmark = pytest.mark.fast


def test_build_args_includes_hot_reload():
    args = dev.build_args(debug=False)
    assert str(dev.ROOT / "Main.py") in args
    assert "--hot-reload" in args
    assert "--debug" not in args


def test_build_args_debug_combo():
    args = dev.build_args(debug=True)
    assert "--hot-reload" in args
    assert "--debug" in args


def test_start_app_passes_args_to_popen(monkeypatch):
    captured = {}

    def fake_popen(args, **kw):
        captured["args"] = args
        captured["kw"] = kw
        return MagicMock()

    monkeypatch.setattr(dev.subprocess, "Popen", fake_popen)
    dev.start_app(debug=True)
    assert captured["kw"]["cwd"] == dev.ROOT
    assert "--hot-reload" in captured["args"]
    assert "--debug" in captured["args"]


def test_start_app_clears_trigger(monkeypatch):
    monkeypatch.setattr(dev, "clear_trigger", MagicMock())
    monkeypatch.setattr(dev.subprocess, "Popen", MagicMock())
    dev.start_app()
    dev.clear_trigger.assert_called_once_with()


def test_main_acquires_and_releases_dev_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(dev, "DEV_LOCK", tmp_path / "dev.lock")
    monkeypatch.setattr(dev, "_run", MagicMock())
    calls = []
    monkeypatch.setattr(dev, "try_lock", lambda **kw: calls.append(("try", kw)) or True)
    monkeypatch.setattr(dev, "unlock", lambda **kw: calls.append(("unlock", kw)))
    dev.main()
    assert calls == [
        ("try", {"lock_file": tmp_path / "dev.lock"}),
        ("unlock", {"lock_file": tmp_path / "dev.lock"}),
    ]
    dev._run.assert_called_once_with()


def test_main_exits_1_when_lock_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(dev, "DEV_LOCK", tmp_path / "dev.lock")
    monkeypatch.setattr(dev, "try_lock", lambda **kw: False)
    monkeypatch.setattr(dev, "_run", MagicMock())
    with pytest.raises(SystemExit) as e:
        dev.main()
    assert e.value.code == 1


def test_mtime_changed_ignores_unchanged(tmp_path):
    """mtime 未变 → 视为扫描式误报，不触发重启"""
    f = tmp_path / "x.py"
    f.write_text("a", encoding="utf-8")
    base = {os.path.normcase(str(f.resolve())): f.stat().st_mtime}
    assert dev._mtime_changed(base, f) is False
    assert base[os.path.normcase(str(f.resolve()))] == f.stat().st_mtime  # 基线不刷新


def test_mtime_changed_detects_real_edit(tmp_path):
    """真实写入（mtime 变化）→ 触发重启"""
    f = tmp_path / "x.py"
    f.write_text("a", encoding="utf-8")
    st = f.stat()
    base = {os.path.normcase(str(f.resolve())): st.st_mtime}
    os.utime(f, (st.st_atime, st.st_mtime + 10))  # 模拟真实写入
    assert dev._mtime_changed(base, f) is True
    assert base[os.path.normcase(str(f.resolve()))] == pytest.approx(f.stat().st_mtime)


def test_mtime_changed_new_file_is_change(tmp_path):
    """新文件不在基线里 → 视为真实变更"""
    f = tmp_path / "new.py"
    f.write_text("x", encoding="utf-8")
    assert dev._mtime_changed({}, f) is True


def test_wait_and_cleanup_settles_after_force_kill(monkeypatch):
    """强杀后应等待 OS 释放 DB 文件句柄再继续（防新进程 disk I/O error）"""
    proc = MagicMock()
    proc.poll.return_value = None  # 进程仍在运行
    sleeps: list[float] = []
    calls = {"n": 0}

    def _wait(_timeout):
        calls["n"] += 1
        if calls["n"] in (1, 2):  # 优雅退出超时 + terminate 后仍超时
            raise dev.subprocess.TimeoutExpired(dev.build_args(), 5)
        return 0  # kill 后进程终于退出

    proc.wait.side_effect = _wait
    monkeypatch.setattr(dev, "write_trigger", MagicMock())
    monkeypatch.setattr(dev, "time", SimpleNamespace(sleep=sleeps.append))

    dev._wait_and_cleanup(proc)

    assert sleeps == [dev.FORCE_KILL_SETTLE]
    proc.terminate.assert_called_once_with()
    proc.kill.assert_called_once_with()


def test_restart_state_continuous_changes_push_debounce():
    """agent 连续改文件（间隔 < 防抖）→ 不重启，直到真正安静满 12s"""
    s = dev.RestartState(debounce=12.0, cooldown=15.0)
    s.on_change(0)
    s.on_change(4)
    s.on_change(8)
    assert s.should_restart(9) is False  # 距上次变更 1s
    assert s.should_restart(19) is False  # 距上次变更 11s，仍 < 12
    assert s.should_restart(20) is True  # 安静满 12s → 可以重启


def test_restart_state_batch_fires_once_then_cooldown():
    """一批变更只重启一次；重启后冷却期内不重启，直到新一轮变更"""
    s = dev.RestartState(debounce=12.0, cooldown=15.0)
    s.on_change(0)
    assert s.should_restart(12) is True
    s.mark_restarted(12)
    assert s.should_restart(20) is False  # 冷却期内（< 27）
    assert s.should_restart(30) is False  # 冷却已过但无新变更 → 不重启
    s.on_change(30)  # agent 新一轮编辑
    assert s.should_restart(41) is False  # 距变更 11s
    assert s.should_restart(42) is True  # 距变更 12s


def test_restart_state_change_during_cooldown_still_counts():
    """冷却期内的真实变更也顺延防抖：冷却结束 + 安静满 12s 后才重启"""
    s = dev.RestartState(debounce=12.0, cooldown=15.0)
    s.on_change(0)
    s.mark_restarted(12)  # t=12 重启，冷却至 27
    s.on_change(13)  # 新进程启动期 agent 又写了一个文件
    assert s.should_restart(20) is False  # 冷却未过（20 < 27）
    assert s.should_restart(26) is False  # 冷却未过（26 < 27）
    assert s.should_restart(27) is True  # 冷却过(27≥27) 且安静满 12s（27-13=14）


def test_restart_state_no_change_no_restart():
    s = dev.RestartState(debounce=12.0, cooldown=15.0)
    assert s.should_restart(1000) is False


def test_ignore_dirs_excludes_background_agent_files():
    """agent 改后台文件（工作树/测试/脚本/工具/运行时数据）不应触发重启"""
    for d in (".claude", "tests", "scripts", "tools", "data", "database", "docs", "build"):
        assert d in dev.IGNORE_DIRS, f"缺少 IGNORE_DIRS 条目: {d}"


def test_is_watched_path_filters_background_vs_source(tmp_path):
    """仅应用源码触发重启；后台/运行时文件一律忽略"""
    wat = dev._is_watched_path
    root = tmp_path
    assert wat(root / "core" / "logger.py") is True
    assert wat(root / "services" / "plan_decompose.py") is True
    assert wat(root / "ui_pyside6" / "theme.py") is True
    assert wat(root / "Main.py") is True  # 根入口
    # agent 改后台文件 → 不触发
    assert wat(root / ".claude" / "worktrees" / "z" / "dev.py") is False
    assert wat(root / "tests" / "test_dev.py") is False
    assert wat(root / "scripts" / "migrate_split_db.py") is False
    assert wat(root / "tools" / "downloaders" / "getitems.py") is False
    # 运行时/非源码 → 不触发
    assert wat(root / "data" / "settings.json") is False
    assert wat(root / "database" / "user.db") is False
    assert wat(root / "docs" / "x.md") is False


def test_agent_edit_sequence_restarts_once_after_quiet(tmp_path):
    """模拟 agent 编辑：后台文件完全不触发；源码文件在安静满防抖后才重启一次"""
    root = tmp_path
    core = root / "core"
    core.mkdir()
    tests = root / "tests"
    tests.mkdir()
    wt = root / ".claude" / "worktrees" / "z"
    wt.mkdir(parents=True)

    src = core / "logger.py"
    tst = tests / "test_x.py"
    work = wt / "dev.py"
    for p in (src, tst, work):
        p.write_text("a", encoding="utf-8")

    state = dev.RestartState(debounce=12.0, cooldown=15.0)
    known = {os.path.normcase(str(p)): p.stat().st_mtime for p in (src, tst, work)}

    def _agent_edit(path: Path) -> bool:
        st = path.stat()
        os.utime(path, (st.st_atime, st.st_mtime + 1))  # 模拟真实写入
        if not dev._is_watched_path(path):
            return False
        if not dev._mtime_changed(known, path):
            return False
        state.on_change(1.0)  # 用固定时间推进状态机，仅验证判定链
        return True

    # agent 改后台文件（测试/工作树）→ 不调度重启
    assert _agent_edit(tst) is False
    assert _agent_edit(work) is False
    assert state.restart_scheduled is False

    # agent 改应用源码 → 调度重启；未安静时不触发，安静满 12s 才触发
    assert _agent_edit(src) is True
    assert state.restart_scheduled is True
    assert state.should_restart(1.0) is False
    assert state.should_restart(12.0) is False
    assert state.should_restart(13.0) is True

    # 重启后进入冷却期
    state.mark_restarted(13.0)
    assert state.should_restart(20.0) is False


def _fake_proc():
    class _FakeProc:
        def wait(self) -> int:
            return 0

    return _FakeProc()


def _spawn_fresh(monkeypatch, tmp_path, keep: bool, seed_existing: bool = False):
    """模拟 start_fresh：monkeypatch Popen 捕获启动参数，不真正启动 GUI"""
    env_dir = tmp_path / "fresh_env"
    if seed_existing:
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "database").mkdir(exist_ok=True)
        marker = env_dir / "database" / "reference.db"
        marker.write_text("old-data", encoding="utf-8")
        assert marker.exists()
    monkeypatch.setattr(dev, "FRESH_ENV_DIR", env_dir)

    spawned: dict = {}

    def fake_popen(cmd, cwd, env):
        spawned["cmd"] = cmd
        spawned["cwd"] = cwd
        spawned["env"] = env
        return _fake_proc()

    monkeypatch.setattr(dev.subprocess, "Popen", fake_popen)
    dev.start_fresh(keep=keep)
    return spawned, env_dir


class TestStartFresh:
    """dev.py --fresh / --keep 的隔离目录准备与子进程启动"""

    def test_reset_cleans_old_data(self, monkeypatch, tmp_path):
        """--fresh（keep=False）清空已有环境，模拟新用户开箱"""
        spawned, env_dir = _spawn_fresh(monkeypatch, tmp_path, keep=False, seed_existing=True)
        marker = env_dir / "database" / "reference.db"
        assert not marker.exists(), "重置模式应清空旧数据"
        assert env_dir.is_dir(), "隔离目录应已重建"
        # 子进程命令：Main.py --force（跳过单实例锁），注入隔离根目录环境变量
        assert spawned["cmd"] == [sys.executable, str(dev.ROOT / "Main.py"), "--force"]
        assert spawned["env"][dev.FRESH_ENV_VAR] == str(env_dir)
        # 不传 --hot-reload（初始化中途被热重载退出会中断下载）
        assert "--hot-reload" not in spawned["cmd"]

    def test_keep_preserves_data(self, monkeypatch, tmp_path):
        """--fresh --keep 保留已有环境数据，模拟二次启动"""
        spawned, env_dir = _spawn_fresh(monkeypatch, tmp_path, keep=True, seed_existing=True)
        marker = env_dir / "database" / "reference.db"
        assert marker.exists(), "keep 模式应保留旧数据"
        assert marker.read_text(encoding="utf-8") == "old-data"
        assert spawned["env"][dev.FRESH_ENV_VAR] == str(env_dir)

    def test_fresh_env_under_project_root(self):
        """隔离目录固定为项目根下 fresh_env（.gitignore 已忽略）"""
        assert dev.FRESH_ENV_DIR == dev.ROOT / "fresh_env"
