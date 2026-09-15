# core.qt_noise

> 源文件 `core/qt_noise.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

退出期的 Qt 内建 QML 告警抑制。

点右上角关闭按钮后，Qt 开始拆除 QML 引擎。此时 `FluentWinUI3` 样式**自己**的
`qrc:` 文件会成片报警：

    qrc:/qt-project.org/imports/QtQuick/Controls/FluentWinUI3/Button.qml:25:
        TypeError: Value is null and could not be converted to an object

机理是绑定重算赶在析构之后：样式单例（`background` / `label` / `padding` 的来源）
已经被销毁，而控件还在求值，于是必然拿到 null。**这不是我们的 QML 写错了** ——
同一条绑定在运行期一直是对的。

这些信息在退出阶段没有任何可操作性（应用已经在关了），却会一次刷出上百行，
看起来像崩了。所以：

- **只在退出已经开始之后**丢（`begin_shutdown()` 由外壳的 `closeEvent` / `aboutToQuit` 调）；
- **只丢 Qt 自带 QML**（`qrc:/qt-project.org/`）的告警。

运行期的同类告警照旧记录 —— 那时候它们可能是真问题；我们自己 `.qml` 的告警
更是一条都不丢。

## 函数

### `begin_shutdown`

```python
def begin_shutdown() -> None
```

标记「退出已经开始」。可重入（`closeEvent` 与 `aboutToQuit` 都会调）。

定义行：`33`

### `shutting_down`

```python
def shutting_down() -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`39`

### `is_qt_internal_qml`

```python
def is_qt_internal_qml(message: str) -> bool
```

该消息是否出自 Qt 自带的 QML 文件。

定义行：`43`
