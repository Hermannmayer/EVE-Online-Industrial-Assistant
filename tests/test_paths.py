"""路径模块单元测试 — 验证 core.paths 的目录和文件路径函数"""

import os
import sys

import pytest

from core.paths import (
    app_root,
    blueprint_db_path,
    data_dir,
    database_dir,
    database_path,
    icon_cache_dir,
    market_db_path,
    reference_db_path,
    user_db_path,
)

pytestmark = pytest.mark.fast


class TestAppRoot:
    """app_root() — 应用根目录"""

    def test_app_root_contains_main_py(self):
        """根目录应包含 Main.py"""
        root = app_root()
        assert os.path.isfile(os.path.join(root, "Main.py"))

    def test_app_root_is_absolute(self):
        """根目录应为绝对路径"""
        assert os.path.isabs(app_root())


class TestDatabaseDir:
    """database_dir() — 数据库目录"""

    def test_database_dir_is_under_app_root(self):
        """数据库目录应在 app_root 下"""
        db_dir = database_dir()
        assert db_dir.startswith(app_root())


class TestDatabasePaths:
    """各数据库路径函数"""

    def test_all_db_paths_under_database_dir(self):
        """所有数据库路径都应在 database_dir 下"""
        db_dir = database_dir()
        for fn in (reference_db_path, market_db_path, user_db_path, blueprint_db_path):
            assert fn().startswith(db_dir), f"{fn.__name__} not under database_dir"


class TestDataPaths:
    """data_dir / icon_cache_dir"""

    def test_icon_cache_under_data_dir(self):
        assert icon_cache_dir().startswith(data_dir())


class TestFrozenBoundary:
    """边界测试：frozen 与非 frozen 模式下 app_root() 行为"""

    def test_app_root_frozen_uses_executable_dir(self, monkeypatch):
        """frozen 模式下 app_root 应为 sys.executable 所在目录"""
        monkeypatch.setattr("sys.frozen", True, raising=False)
        root = app_root()
        assert root == os.path.dirname(sys.executable)

    def test_frozen_flag_off_by_default(self, monkeypatch):
        """未设置 sys.frozen 时 is_frozen 应返回 False"""
        monkeypatch.delattr("sys.frozen", raising=False)
        from core.paths import is_frozen

        assert is_frozen() is False

    def test_app_root_env_override_wins(self, monkeypatch):
        """EVE_ASSISTANT_APP_ROOT 覆盖 app_root，优先级高于 frozen"""
        monkeypatch.setenv("EVE_ASSISTANT_APP_ROOT", "C:/fake/release/env")
        monkeypatch.setattr("sys.frozen", True, raising=False)
        assert app_root() == "C:/fake/release/env"
        # 派生路径（database/data）跟随隔离根目录
        assert database_dir().startswith("C:/fake/release/env")
        assert data_dir().startswith("C:/fake/release/env")

    def test_app_root_env_unset_uses_dev(self, monkeypatch):
        """未设置环境变量时退回开发/打包逻辑"""
        monkeypatch.delenv("EVE_ASSISTANT_APP_ROOT", raising=False)
        monkeypatch.delattr("sys.frozen", raising=False)
        root = app_root()
        assert os.path.isdir(os.path.join(root, "core"))


class TestCompatBoundary:
    """边界测试：旧兼容路径 database_path() 与各分库路径"""

    def test_database_path_differs_from_all_split_dbs(self):
        """database_path()（items.db）不应与任何分库路径重叠"""
        split_dbs = [
            reference_db_path(),
            market_db_path(),
            user_db_path(),
            blueprint_db_path(),
        ]
        assert database_path() not in split_dbs

    def test_database_path_is_under_database_dir(self):
        """database_path() 应在 database_dir 下"""
        assert database_path().startswith(database_dir())
