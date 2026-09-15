"""QML 侧的取数线程。

这些 worker 原先在 `ui_pyside6/workers/`，因为 QML 页面与对话框桥都要用、
而 `ui_qml` 不能反向依赖 `ui_pyside6`，所以搬到这里。

它们本来就不碰 QtWidgets（只有 QtCore 的 QThread + Signal），Widgets 侧照旧
import 本包；旧路径**不留转发器** —— 多处 `mock.patch` 打在 worker 模块上，
模块身份一分为二会让 patch 静默空转。
"""

__all__: list[str] = []
