"""
集中式路径管理 —— 兼容开发环境和 PyInstaller 打包环境

开发环境：
    eve/
        Main.py
        database/items.db
        data/caches/icons/
        services/workers/getprices.py

PyInstaller 打包后：
    dist/EVE商人助手/
        EVE商人助手.exe
        database/items.db
        data/caches/icons/
        data/update_progress.json
        data/search_history.json
        data/window_geometry.json
"""
import os
import sys


def is_frozen() -> bool:
    """判断是否运行在 PyInstaller 打包后的环境中"""
    return getattr(sys, 'frozen', False)


def app_root() -> str:
    """返回应用根目录

    开发环境：项目根目录（eve/）
    打包环境：exe 所在目录（dist/EVE商人助手/）
    """
    if is_frozen():
        # PyInstaller 打包后，exe 就在我们要的目录下
        return os.path.dirname(sys.executable)
    else:
        # 开发环境：取项目根目录（core/paths.py 的父目录的父目录）
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def database_dir() -> str:
    """数据库目录"""
    return os.path.join(app_root(), "database")


def database_path() -> str:
    """数据库文件路径"""
    return os.path.join(database_dir(), "items.db")


def data_dir() -> str:
    """数据目录（图标缓存、搜索历史等）"""
    return os.path.join(app_root(), "data")


def icon_cache_dir() -> str:
    """图标缓存目录"""
    return os.path.join(data_dir(), "caches", "icons")


def progress_file() -> str:
    """更新进度文件路径"""
    return os.path.join(data_dir(), "update_progress.json")


def search_history_file() -> str:
    """搜索历史文件路径"""
    return os.path.join(data_dir(), "search_history.json")


def window_geometry_file() -> str:
    """窗口位置文件路径"""
    return os.path.join(data_dir(), "window_geometry.json")


def ensure_dirs_exist():
    """确保所有必要目录存在（打包后首次运行时创建）"""
    os.makedirs(database_dir(), exist_ok=True)
    os.makedirs(data_dir(), exist_ok=True)
    os.makedirs(icon_cache_dir(), exist_ok=True)


# 兼容旧版直接引用
DB_PATH = database_path()
ICON_DIR = icon_cache_dir()
