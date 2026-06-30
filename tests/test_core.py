"""测试核心模块"""

from core.paths import app_root


def test_app_root_exists():
    root = app_root()
    assert root is not None
    assert len(root) > 0


def test_database_path():
    from core.paths import database_path

    path = database_path()
    assert path.endswith("items.db")
