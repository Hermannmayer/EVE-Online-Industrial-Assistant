"""主题模块的**旧路径转发器** —— 真身已搬到 `ui_qml/theme/registry.py`。

主题 token、注册表、切换、持久化、窗口几何都要给 QML 侧用，不能再让
`ui_qml` 反向 import `ui_pyside6`，所以整份搬到了 `ui_qml/theme/registry.py`。
本模块**不复制任何值**，只做属性转发：

    theme.BG_DARK                       → registry.BG_DARK
    from ui_pyside6.theme import fs     → registry.fs
    patch("ui_pyside6.theme.X")         → 也能取到（patch 先 getattr 再 setattr）

逐次 `getattr` 意味着这里**没有导入期快照**：`apply_theme()` 换过主题后，
从本模块读到的立即是新值，与搬迁前「直接读模块属性」的语义完全一致。

QSS 生成（14 个 `_*_styles()` + `get_stylesheet()` + `themed_menu`）暂时也还在
registry 里：它只服务 Widgets 外壳，等阶段 5 把外壳换成 QML 后整段删除
（见计划批次 6.2 的清理清单），届时本转发器一并消失。
"""

from typing import Any

from ui_qml.theme import registry as _registry


def __getattr__(name: str) -> Any:
    """未在本模块定义的名字一律转发给 registry（含下划线开头的名字）。"""
    return getattr(_registry, name)
