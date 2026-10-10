# ui_qml.workers.__init__

> 源文件 `ui_qml/workers/__init__.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

QML 侧的取数线程。

这些 worker 原先在 Widgets 视图层，因为 QML 页面与对话框桥都要用、
跨层共用同一份实现，所以统一放在这里。

它们本来就不碰 QtWidgets（只有 QtCore 的 QThread + Signal）；旧路径**不留转发器** ——
多处 `mock.patch` 打在 worker 模块上，模块身份一分为二会让 patch 静默空转。

_（此模块无可公开的类或函数）_
