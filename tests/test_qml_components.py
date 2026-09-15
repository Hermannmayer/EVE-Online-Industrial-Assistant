"""QML 公共组件的运行时护栏。

两类曾经真实出现过、且都只在运行期暴露的问题：

1. **样式不支持自定义** —— 测试进程没调 `QQuickStyle.setStyle("FluentWinUI3")` 时，
   Windows 上会退回**原生**样式，它禁止自定义 `background`/`indicator`，
   于是每个自定义组件都刷一条「The current style does not support customization」
   告警，且渲染结果与生产完全不同。→ `test_qml_style_matches_production`（确定性）。
2. **绑定循环** —— 绑定体里写入自己依赖的属性。Qt 的循环检测**不是每次求值都告警**
   （实测同一份代码两次运行一次报一次不报），运行时也测不出「是不是绑定」
   （给有绑定的属性赋值会直接打断绑定）→ `test_max_item_width_is_measured_not_bound`
   用**静态检查**钉住。

`test_components_load_and_interact_without_warnings` 是覆盖面较广的冒烟：
它不保证抓到每一类告警（见上），但能拦住加载期报错与常见的 polish/hover/popup 告警。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEventLoop, QTimer, QtMsgType, QUrl, qInstallMessageHandler
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle

from ui_qml.bridge import theme_singleton
from ui_qml.icon_provider import PROVIDER_ID, PhosphorIconProvider

QML_ROOT = Path(__file__).resolve().parent.parent / "ui_qml" / "qml"

# 每个组件都实例化一遍，把 polish / hover / popup 路径都走到
_PROBE = """
import QtQuick
import QtQuick.Controls
import "components"

Window {
    width: 640; height: 480
    visible: true
    flags: Qt.WindowDoesNotAcceptFocus

    FButton { text: "次要按钮" }
    FButton { text: "主按钮"; primary: true }
    FCard { width: 120; height: 80 }
    FCheckBox { text: "勾选"; checked: true }
    FComboBox { model: ["第一项", "更长一些的第二项"]; currentIndex: 1 }
    FDialog { title: "对话框" }
    FDoubleSpinBox { value: 1.25 }
    FSpinBox { value: 7 }
    FTextField { text: "文本" }
    FArrowButton { active: true; hovered: true }
    FMenu { MenuItem { text: "菜单项" } }
}
"""


@pytest.fixture
def qml_warnings():
    """捕获测试期间的全部 Qt 告警/严重消息。"""
    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            else None
        )
    )
    try:
        yield caught
    finally:
        qInstallMessageHandler(previous)


@pytest.fixture
def make_qml():
    """造一段探针 QML 并实例化。

    **引擎 / 组件 / 创建出的对象三者都要保活**：`QQmlComponent.create()` 产物的
    Python 包装一旦失去引用，shiboken 就会析构底层 C++ 对象 —— 表现为后续访问抛
    `Internal C++ object already deleted`，而 `setData` 时引擎若被回收更会直接报
    「Must provide an engine before calling setData」。
    """
    alive: list[Any] = []

    def _make(qml: str, name: str) -> Any:
        engine = QQmlEngine()
        engine.addImageProvider(PROVIDER_ID, PhosphorIconProvider())
        engine.rootContext().setContextProperty("Theme", theme_singleton())

        component = QQmlComponent(engine)
        # 基址落在 qml 目录下，`import "components"` 才能解析到真实组件目录
        component.setData(qml.encode("utf-8"), QUrl.fromLocalFile(str(QML_ROOT / name)))
        assert not component.isError(), "; ".join(e.toString() for e in component.errors())

        obj = component.create()
        assert obj is not None, "; ".join(e.toString() for e in component.errors())
        alive.extend((engine, component, obj))
        return obj

    try:
        yield _make
    finally:
        for item in alive:
            if isinstance(item, QQmlEngine):
                continue
            item.deleteLater()
        _spin()
        alive.clear()


def _spin() -> None:
    loop = QEventLoop()
    QTimer.singleShot(120, loop.quit)
    loop.exec()


@pytest.mark.ui
def test_qml_style_matches_production(qapp):
    """QML 控件样式必须是 FluentWinUI3 —— 与 Main.py 一致。

    不设会用平台默认样式（Windows 上为原生样式），它禁止自定义
    `background`/`indicator`，自定义组件会全部失效并刷告警。
    """
    assert QQuickStyle.name() == "FluentWinUI3"


@pytest.mark.ui
def test_components_load_and_interact_without_warnings(qapp, qml_warnings, make_qml):
    make_qml(_PROBE, "_probe_components.qml")
    _spin()  # 让窗口完成 polish（原生样式的告警只在这一步之后才可能出现）

    assert not qml_warnings, "QML 组件产生了 Qt 告警：\n" + "\n".join(dict.fromkeys(qml_warnings))


@pytest.mark.fast
def test_every_page_paints_a_root_background():
    """每个页面根节点都必须铺满一块不透明底色。

    `PageHost` 是 `QQuickWidget`，为了让窗口级 Mica 透出来设了
    `setClearColor(transparent)`——于是**页面没画到的地方会直接透出窗口背后的东西**
    （Widgets 窗口的 palette 底色，暗色下近似纯黑）。

    实测踩过：`IndustryPage.qml` 少这一块时，表格行区以外全是黑洞，
    用户报「表格背景是黑的 / 还有黑色背景留着」。表格、甘特图这些子组件即便各自
    铺了底色，页级留白仍在页面这一层，补不到。

    静态扫描而不是渲染断言：这是「有没有写」的问题，源码里看得一清二楚。
    """
    pages = sorted((QML_ROOT / "pages").glob("*.qml"))
    assert pages, "没找到任何页面 QML"

    missing = [
        p.name
        for p in pages
        if not re.search(
            r"Rectangle\s*\{\s*\n\s*anchors\.fill:\s*parent\s*\n\s*color:\s*Theme\.", p.read_text(encoding="utf-8")
        )
    ]
    assert not missing, (
        "以下页面没有全幅根底色，未绘制区域会透出窗口背后（暗色下是黑洞）："
        + "、".join(missing)
        + "。照 EstimatePage.qml 的写法加 Rectangle { anchors.fill: parent; color: Theme.bgDark }。"
    )


@pytest.mark.fast
def test_positions_do_not_map_in_the_binding():
    """`x:` / `y:` 绑定里不许调 `mapToItem` / `mapFromItem`。

    这类函数调用**建立不起绑定依赖**：QML 只追踪绑定表达式里读到的属性，
    而 `mapToItem` 内部读的 x/y/width/height 是在 C++ 里读的，引擎看不见。
    于是整条绑定只在创建时求值一次 —— 那一刻布局往往还没跑完（坐标 0,0），
    此后无论怎么变都不重算，控件永远停在左上角（估价页的候选框就是这么错的）。

    正确做法是让位置相对**父项**表达（`parent: 某控件` + `y: 某控件.height`），
    由 Qt 的定位器在显示时换算。与 `Theme.fs()` 不被追踪是同一类坑。
    """
    offenders = []
    for path in sorted(QML_ROOT.rglob("*.qml")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*[xy]\s*:", line) and re.search(r"\bmap(To|From)Item\s*\(", line):
                offenders.append(f"{path.relative_to(QML_ROOT)}:{lineno}: {line.strip()}")

    assert not offenders, "这些位置绑定用了 mapToItem/mapFromItem，会因为不被依赖追踪而永远停在初值：\n" + "\n".join(
        offenders
    )


@pytest.mark.fast
def test_max_item_width_is_measured_not_bound():
    """`FComboBox.maxItemWidth` 必须用**普通属性 + 主动测量**，不能写成绑定。

    绑定体里要给 `itemMetrics.text` 赋值，而该绑定又读 `itemMetrics.width`，
    Qt 判定为绑定循环（实测告警 `Binding loop detected for property "maxItemWidth"`）。

    这里做**静态检查**而不是运行时断言，因为运行时测不出来：
    - 给一个有绑定的属性赋值会**打断绑定**（QML 语义），赋值照样保留；
    - 循环告警不是每次求值都出现（实测同一份代码两次运行一次报一次不报）。
    """
    text = (QML_ROOT / "components" / "FComboBox.qml").read_text(encoding="utf-8")
    match = re.search(r"^\s*property\s+real\s+maxItemWidth\s*:(.*)$", text, re.MULTILINE)
    assert match, "未找到 maxItemWidth 声明（改名了？请同步更新本护栏）"
    assert not match.group(1).strip().startswith("{"), (
        "maxItemWidth 被写成了绑定：绑定体里写 itemMetrics.text 会与它读取的 "
        "itemMetrics.width 形成绑定循环，改成普通属性 + measureMaxItemWidth()"
    )
