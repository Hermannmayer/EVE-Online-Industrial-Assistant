"""QML 侧的主题模块。

`registry.py` 是真身：色板、`THEME_REGISTRY`、运行时 token、切换与持久化都在那里。
QML 的 `Theme` 单例经 `ui_qml.bridge.theme_bridge` 读同一份 token ——
「配色只在 theme」这条铁律在 QML 侧同样成立。
"""

__all__: list[str] = []
