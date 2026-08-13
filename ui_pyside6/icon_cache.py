"""物品图标加载 — 统一 QPixmapCache 缓存 + 路径拼装

消除 procurement_tab / inventory_helpers / plan_table 及多个模型里重复的
_load_icon 与裸 QPixmap(icon_path) 加载（原本各拼路径、部分无缓存）。
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPixmapCache

from core.paths import ICON_DIR


def item_icon_path(type_id: int) -> str:
    """图标文件路径（文件可能不存在）"""
    return os.path.join(ICON_DIR, f"{type_id}.png")


def load_item_icon(type_id: int, size: int = 32) -> QPixmap | None:
    """加载物品图标（QPixmapCache 缓存），文件缺失/损坏返回 None

    Args:
        type_id: 物品 type_id
        size: 缩放目标尺寸（px），不同 UI 位置可按需传不同尺寸
    """
    if not type_id:
        return None
    cache_key = f"itemicon_{type_id}_{size}"
    pixmap = QPixmap(cache_key)
    if not pixmap.isNull():
        return pixmap
    path = item_icon_path(type_id)
    if not os.path.isfile(path):
        return None
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return None
    pixmap = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    QPixmapCache.insert(cache_key, pixmap)
    return pixmap
