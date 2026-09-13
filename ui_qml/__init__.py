"""QML UI 层（Fluent Design）。

与 `ui_pyside6` 并存，通过 `QQuickWidget` 渐进嵌入：页面逐个从 Widgets 换成 QML，
外壳最后一步再整体换成 `QQuickWindow`。详见计划文档与 docs/dev/architecture.md。
"""

__all__: list[str] = []
