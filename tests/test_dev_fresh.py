"""dev.py 全新开箱模式测试 — --fresh / --keep 的隔离目录准备与子进程启动"""

import sys

import dev as dev_mod


class _FakeProc:
    def wait(self) -> int:
        return 0


def _spawn_fresh(monkeypatch, tmp_path, keep: bool, seed_existing: bool = False):
    """模拟 start_fresh：monkeypatch Popen 捕获启动参数，不真正启动 GUI"""
    env_dir = tmp_path / "fresh_env"
    if seed_existing:
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "database").mkdir(exist_ok=True)
        marker = env_dir / "database" / "reference.db"
        marker.write_text("old-data", encoding="utf-8")
        assert marker.exists()
    monkeypatch.setattr(dev_mod, "FRESH_ENV_DIR", env_dir)

    spawned: dict = {}

    def fake_popen(cmd, cwd, env):
        spawned["cmd"] = cmd
        spawned["cwd"] = cwd
        spawned["env"] = env
        return _FakeProc()

    monkeypatch.setattr(dev_mod.subprocess, "Popen", fake_popen)
    dev_mod.start_fresh(keep=keep)
    return spawned, env_dir


class TestStartFresh:
    def test_reset_cleans_old_data(self, monkeypatch, tmp_path):
        """--fresh（keep=False）清空已有环境，模拟新用户开箱"""
        spawned, env_dir = _spawn_fresh(monkeypatch, tmp_path, keep=False, seed_existing=True)
        marker = env_dir / "database" / "reference.db"
        assert not marker.exists(), "重置模式应清空旧数据"
        assert env_dir.is_dir(), "隔离目录应已重建"

        # 子进程命令：Main.py --force（跳过单实例锁），注入隔离根目录环境变量
        assert spawned["cmd"] == [sys.executable, str(dev_mod.ROOT / "Main.py"), "--force"]
        assert spawned["env"][dev_mod.FRESH_ENV_VAR] == str(env_dir)
        # 不传 --hot-reload（初始化中途被热重载退出会中断下载）
        assert "--hot-reload" not in spawned["cmd"]

    def test_keep_preserves_data(self, monkeypatch, tmp_path):
        """--fresh --keep 保留已有环境数据，模拟二次启动"""
        spawned, env_dir = _spawn_fresh(monkeypatch, tmp_path, keep=True, seed_existing=True)
        marker = env_dir / "database" / "reference.db"
        assert marker.exists(), "keep 模式应保留旧数据"
        assert marker.read_text(encoding="utf-8") == "old-data"
        assert spawned["env"][dev_mod.FRESH_ENV_VAR] == str(env_dir)

    def test_fresh_env_under_project_root(self):
        """隔离目录固定为项目根下 fresh_env（.gitignore 已忽略）"""
        assert dev_mod.FRESH_ENV_DIR == dev_mod.ROOT / "fresh_env"
