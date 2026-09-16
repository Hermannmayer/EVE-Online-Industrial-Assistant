"""裁剪版 QtQml 钩子 —— 只收应用真正用到的 QML 模块。

**为什么需要它**：上游 `PyInstaller/hooks/hook-PySide6.QtQml.py` 调用的
`collect_qtqml_files()` 内部是 `rglob('**/qmldir')`，**无条件**收集
`PySide6/qml/` 下的全部模块，没有任何过滤。这些模块的插件 DLL 又会被二进制
依赖分析顺带展开 —— 最贵的一笔是 `qml/QtWebEngine` 的插件依赖
`Qt6WebEngineCore.dll`，**单文件 195 MB**，而本项目从不使用 WebEngine。

结果就是：应用一旦开始用 QtQml（QML 迁移），打包体积从 62 MB 跳到 177 MB，
其中 45% 是这一个用不到的库。实测裁剪后 onefile exe 从约 190 MB 降到 80 MB。

本钩子保留上游的全部行为（`add_qt6_dependencies` 照常调用，qml/ 之外的条目
一律放行），只在 qml 数据与二进制上按模块名做一次白名单过滤。
"""

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

# 应用 .qml 里实际出现的 import 只有 QtQuick 系列
# （QtQuick / QtQuick.Controls / QtQuick.Effects / QtQuick.Layouts /
#   QtQuick.Shapes / QtQuick.Window），加上 QML 引擎自身的 QtQml 与 QtCore。
# 这三项之外的 qml/ 模块（QtWebEngine、Qt3D、QtCharts、QtGraphs、
# QtDataVisualization、Qt5Compat、QtTest、QtLocation、QtMultimedia…）都没用到。
_KEEP_QML_MODULES = {"QtQuick", "QtQml", "QtCore"}


def _keep(name: str) -> bool:
    """qml/ 之外的条目一律保留（Qt 自身 DLL、平台插件等由别的钩子负责）。"""
    normalized = name.replace("\\", "/")
    if "/qml/" not in normalized:
        return True
    module = normalized.split("/qml/", 1)[1].split("/", 1)[0]
    return module in _KEEP_QML_MODULES


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()

binaries += [b for b in qml_binaries if _keep(b[0])]
datas += [d for d in qml_datas if _keep(d[0])]
