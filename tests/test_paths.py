"""路径模块单元测试 — 验证 core.paths 的目录和文件路径函数"""

import os

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
