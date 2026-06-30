"""路径模块单元测试 — 验证 core.paths 的目录和文件路径函数"""

import os
import sys

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


class TestAppRoot:
    """app_root() — 应用根目录"""

    def test_app_root_exists(self):
        """根目录应存在"""
        root = app_root()
        assert root is not None
        assert os.path.isdir(root)

    def test_app_root_contains_main_py(self):
        """根目录应包含 Main.py"""
        root = app_root()
        assert os.path.isfile(os.path.join(root, "Main.py"))

    def test_app_root_is_absolute(self):
        """根目录应为绝对路径"""
        assert os.path.isabs(app_root())


class TestDatabaseDir:
    """database_dir() — 数据库目录"""

    def test_database_dir_exists(self):
        """数据库目录路径函数返回正确路径"""
        db_dir = database_dir()
        assert db_dir.endswith(os.sep + "database")

    def test_database_dir_is_under_app_root(self):
        """数据库目录应在 app_root 下"""
        db_dir = database_dir()
        assert db_dir.startswith(app_root())


class TestDatabasePaths:
    """各数据库路径函数"""

    def test_reference_db_path_ends_with_reference_db(self):
        assert reference_db_path().endswith("reference.db")

    def test_market_db_path_ends_with_market_db(self):
        assert market_db_path().endswith("market.db")

    def test_user_db_path_ends_with_user_db(self):
        assert user_db_path().endswith("user.db")

    def test_blueprint_db_path_ends_with_blueprint_db(self):
        assert blueprint_db_path().endswith("blueprint.db")

    def test_database_path_ends_with_items_db(self):
        """旧兼容路径应以 items.db 结尾"""
        assert database_path().endswith("items.db")

    def test_all_db_paths_under_database_dir(self):
        """所有数据库路径都应在 database_dir 下"""
        db_dir = database_dir()
        for fn in (reference_db_path, market_db_path, user_db_path, blueprint_db_path):
            assert fn().startswith(db_dir), f"{fn.__name__} not under database_dir"


class TestDataPaths:
    """data_dir / icon_cache_dir"""

    def test_data_dir_exists(self):
        assert data_dir().endswith(os.sep + "data")

    def test_icon_cache_dir_exists(self):
        assert icon_cache_dir().endswith(os.sep + "icons")

    def test_icon_cache_under_data_dir(self):
        assert icon_cache_dir().startswith(data_dir())


class TestFrozenBoundary:
    """边界测试：frozen 与非 frozen 模式下 app_root() 行为"""

    def test_app_root_dev_contains_core(self, monkeypatch):
        """开发模式下 app_root 应包含 core 目录"""
        monkeypatch.delattr("sys.frozen", raising=False)
        root = app_root()
        assert os.path.isdir(os.path.join(root, "core"))

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


class TestEnsureDirsBoundary:
    """边界测试：ensure_dirs_exist 的幂等性"""

    def test_ensure_dirs_exist_idempotent(self):
        """重复调用 ensure_dirs_exist 不应抛出异常"""
        from core.paths import ensure_dirs_exist

        ensure_dirs_exist()
        ensure_dirs_exist()  # 第二次调用，目录已存在


class TestCompatBoundary:
    """边界测试：旧兼容路径 database_path() 与各分库路径"""

    def test_database_path_is_items_db(self):
        """database_path() 应始终指向 items.db"""
        assert database_path().endswith("items.db")

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
