"""路径模块单元测试 — 验证 core.paths 的目录和文件路径函数"""

import os
import sys
from pathlib import Path

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
        """数据库目录恰为 app_root/database"""
        assert database_dir() == os.path.join(app_root(), "database")


class TestDatabasePaths:
    """各数据库路径函数"""

    def test_all_db_paths_under_database_dir(self):
        """每个分库路径恰为 database_dir/<文件名>"""
        expected = {
            reference_db_path: "reference.db",
            market_db_path: "market.db",
            user_db_path: "user.db",
            blueprint_db_path: "blueprint.db",
        }
        for fn, filename in expected.items():
            assert fn() == os.path.join(database_dir(), filename), fn.__name__


class TestDataPaths:
    """data_dir / icon_cache_dir"""

    def test_icon_cache_under_data_dir(self):
        assert icon_cache_dir() == os.path.join(data_dir(), "caches", "icons")


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
        assert database_dir() == os.path.join("C:/fake/release/env", "database")
        assert data_dir() == os.path.join("C:/fake/release/env", "data")

    def test_app_root_env_unset_uses_dev(self, monkeypatch):
        """未设置环境变量时退回开发/打包逻辑 → 项目根目录"""
        monkeypatch.delenv("EVE_ASSISTANT_APP_ROOT", raising=False)
        monkeypatch.delattr("sys.frozen", raising=False)
        assert app_root() == str(Path(__file__).resolve().parents[1])


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
        """旧兼容路径恰为 database_dir/items.db"""
        assert database_path() == os.path.join(database_dir(), "items.db")
