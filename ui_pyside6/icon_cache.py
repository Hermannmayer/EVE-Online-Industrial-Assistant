"""物品图标加载的**旧路径转发器** —— 真身已搬到 `ui_qml/icon_cache.py`。

它没有 QtWidgets 依赖，QML 侧（`ui_qml/models/*` 与各对话框桥）也要用，
所以搬到了 `ui_qml/`。本模块只做属性转发、不复制实现：

    from ui_pyside6.icon_cache import item_icon_path   → ui_qml.icon_cache.item_icon_path
    icon_cache.load_item_icon(...)                     → 同上（逐次 getattr，无快照）

新代码请直接 import `ui_qml.icon_cache`。
"""

from typing import Any

from ui_qml import icon_cache as _icon_cache


def __getattr__(name: str) -> Any:
    """未在本模块定义的名字一律转发给 `ui_qml.icon_cache`。"""
    return getattr(_icon_cache, name)
