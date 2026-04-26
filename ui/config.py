"""
全局配置：路径、字体、窗口位置持久化
"""
import os
import json
import tkinter as tk
from pathlib import Path

# ── 路径 ──
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = str(ROOT_DIR / "database" / "items.db")

# ── 字体 ──
CJK_FONT = ('Microsoft YaHei UI', 11)
CJK_LARGE = ('Microsoft YaHei UI', 14)

# ── 窗口几何位置持久化 ──
_GEOMETRY_FILE = ROOT_DIR / "data" / "window_geometry.json"


def load_window_geometry(win_name: str, default_geometry: str = "1280x720") -> str:
    """读取上次保存的窗口几何位置"""
    try:
        if _GEOMETRY_FILE.exists():
            data = json.loads(_GEOMETRY_FILE.read_text(encoding="utf-8"))
            return data.get(win_name, default_geometry)
    except Exception:
        pass
    return default_geometry


def save_window_geometry(win_name: str, geometry: str):
    """保存窗口几何位置"""
    try:
        _GEOMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if _GEOMETRY_FILE.exists():
            data = json.loads(_GEOMETRY_FILE.read_text(encoding="utf-8"))
        data[win_name] = geometry
        _GEOMETRY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"保存窗口位置失败: {e}")


def bind_geometry_persistence(window, win_name: str):
    """绑定窗口的 geometry 保存（拖动和调整大小时自动保存）"""
    def _save(*args):
        try:
            save_window_geometry(win_name, window.geometry())
        except:
            pass

    # 窗口关闭时保存
    window.bind("<Destroy>", _save, add="+")
    # 移动/调整大小时保存（防抖）
    def _on_configure(event):
        if event.widget == window:
            window.after(300, _save)
    window.bind("<Configure>", _on_configure, add="+")
