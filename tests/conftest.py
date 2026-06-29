"""pytest 共享配置与 fixtures"""
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication


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


@pytest.fixture(scope="session")
def qapp():
    """提供全局 QApplication 实例，供 PySide6 UI 测试使用"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mock_db():
    """在 with 块内将 services.database_manager.get_db 替换为 mock"""
    with patch("services.database_manager.get_db", return_value=_mock_db_manager()):
        yield
