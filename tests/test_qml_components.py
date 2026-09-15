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
from PySide6.QtQuick import QQuickWindow
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
    FTabBar {
        TabButton { text: "短" }
        TabButton { text: "更长的一个标签" }
    }
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


#: 标签栏宽度探针：同一个窄容器里放裸 `TabBar`（对照组）与 `FTabBar`（被测）
_TABFIT_PROBE = """
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

Window {
    width: 400
    height: 200
    visible: true
    flags: Qt.WindowDoesNotAcceptFocus

    // 对照组：裸 TabBar 被按在 150px 的窄容器里，最长的标签放不下
    Item {
        width: 150
        height: 40

        TabBar {
            objectName: "bareBar"
            anchors.fill: parent
            TabButton { text: "跨区域价差" }
            TabButton { text: "运输利润" }
        }
    }

    // 被测：同样 150px 的窄容器，FTabBar 自己撑开，标签不该被截
    Item {
        y: 60
        width: 150
        height: 40

        RowLayout {
            anchors.fill: parent

            FTabBar {
                objectName: "fitBar"
                TabButton { text: "跨区域价差" }
                TabButton { text: "运输利润" }
            }
        }
    }
}
"""


def _by_name(item: Any, name: str) -> Any:
    if item.objectName() == name:
        return item
    if isinstance(item, QQuickWindow):  # 窗口的子树挂在 contentItem 上，没有 childItems()
        item = item.contentItem()
    for child in item.childItems():
        found = _by_name(child, name)
        if found is not None:
            return found
    return None


def _tab_buttons(bar: Any) -> list[Any]:
    out: list[Any] = []
    for child in bar.childItems():
        if "TabButton" in child.metaObject().className():
            out.append(child)
        out.extend(_tab_buttons(child))
    return out


def _elided(buttons: list[Any]) -> list[str]:
    """哪些按钮窄于自己需要的宽度（= 文字被 elide 成省略号）。"""
    return [
        f"{b.property('text')}（{b.property('width'):.0f} < {b.property('implicitWidth'):.0f}）"
        for b in buttons
        if b.property("width") + 0.5 < b.property("implicitWidth")
    ]


@pytest.mark.ui
def test_ftabbar_keeps_labels_intact_where_a_bare_tabbar_elides(qapp, make_qml):
    """`FTabBar` 的契约：窄容器里不截标签 —— 并用**对照组**证明这条断言有牙。

    裸 `TabBar` 把宽度等分给按钮而不看各自的 `implicitWidth`，它自己的 `implicitWidth`
    又是从被挤窄的按钮反推的，两者互相锁死：收窄的容器里最长的标签必然被截
    （实测「市场费率」48px / 需要 60，「ESI 与数据」55 / 需要 69）。

    对照组必须**确实被截**：它要是也被放下，说明这个探针根本测不出问题，那条
    「FTabBar 没截」就成了摆设 —— 没牙的断言比没有断言更糟。
    """
    root = make_qml(_TABFIT_PROBE, "_probe_tabfit.qml")
    _spin()

    fit = _by_name(root, "fitBar")
    bare = _by_name(root, "bareBar")
    assert fit is not None and bare is not None, "探针里的两个标签栏没找到"

    fit_buttons = _tab_buttons(fit)
    bare_buttons = _tab_buttons(bare)
    assert fit_buttons and bare_buttons, "没取到 TabButton"

    assert not _elided(fit_buttons), "FTabBar 也把标签截了：" + "、".join(_elided(fit_buttons))
    assert _elided(bare_buttons), (
        "对照组（裸 TabBar 按在 150px 里）居然没截断 —— 探针测不出问题、护栏失去意义，把容器改窄或换更长的标签"
    )


def _code_only(qml: str) -> str:
    """去掉 QML 注释再扫 —— 本仓注释里大量举例 `Rectangle { … }`，注释掉的代码不算数。"""
    return re.sub(r"(?<!:)//[^\n]*", "", re.sub(r"/\*.*?\*/", "", qml, flags=re.S))


#: 全幅底色：与页面那条护栏同一个形状
_FULL_BLEED = re.compile(r"Rectangle\s*\{\s*\n\s*anchors\.fill:\s*parent\s*\n\s*color:\s*Theme\.")

#: 住在 `dialogs/` 下但**不是**窗口根的字段组件（被对话框复用的零件，不该有底色）
_DIALOG_SUB_COMPONENTS = frozenset({"CharField.qml", "FacilityField.qml", "ResearchCommonFields.qml"})


@pytest.mark.fast
def test_qml_does_not_use_a_bare_tabbar():
    """标签栏一律走 `FTabBar`，别直接用 Qt 的 `TabBar`。

    裸 `TabBar` 把宽度**等分**给每个按钮而不看各自的 `implicitWidth`，而它自己的
    `implicitWidth` 又是从被挤窄的按钮反推的 —— 两者互相锁死，收窄的容器里最长的标签
    必然被截成省略号（实测「市场费率」每格 48px、需要 60；「ESI 与数据」55、需要 69）。
    `FTabBar` 显式算好总宽；铺满整行（`Layout.fillWidth: true`）时两者**完全一致**，
    所以没有理由再用裸的。
    """
    offenders = []
    for p in sorted(QML_ROOT.rglob("*.qml")):
        if p.name == "FTabBar.qml":  # 它自己就是 TabBar 的替身
            continue
        if re.search(r"^\s*TabBar\s*\{", _code_only(p.read_text(encoding="utf-8")), re.M):
            offenders.append(p.relative_to(QML_ROOT).as_posix())

    assert not offenders, "以下 QML 直接用了 `TabBar`，改用 `FTabBar`：" + "、".join(offenders)


@pytest.mark.fast
def test_every_dialog_paints_a_root_background():
    """每个对话框都必须铺满一块不透明底色 —— 与页面那条同源，代价也一样。

    对话框装在同一套 `PageHost` 上（透明清屏 + `WA_TranslucentBackground`），
    没画到的地方直接透出窗口背后。**离屏快照看不出来**：`QWidget.grab()` 会把空区补成
    调色板底色，`ui_snapshot.py --dialog settings` 一切正常；真窗口抓屏
    （`QScreen.grabWindow`）测得 **77% 像素是纯黑** —— 用户报「设置界面是黑的」就是它。

    以 `FDialogFrame` 为根节点的对话框不用再写（骨架自己铺，见下一条）；其余照
    `ContractDetailDialog.qml` 的写法。
    """
    missing = []
    for p in sorted((QML_ROOT / "dialogs").glob("*.qml")):
        if p.name in _DIALOG_SUB_COMPONENTS:
            continue
        src = _code_only(p.read_text(encoding="utf-8"))
        root = re.search(r"^\s*([A-Za-z_][\w.]*)\s*\{", src, re.M)
        if root and root.group(1) == "FDialogFrame":
            continue
        if _FULL_BLEED.search(src):
            continue
        missing.append(f"{p.name}（根节点 {root.group(1) if root else '?'}）")

    assert not missing, (
        "以下对话框没有全幅底色，未绘制区域会透出窗口背后（真窗口下是纯黑）："
        + "、".join(missing)
        + "。改用 FDialogFrame 作根节点，或照 ContractDetailDialog.qml 加"
        + " Rectangle { anchors.fill: parent; color: Theme.bgDark }。"
    )


@pytest.mark.fast
def test_dialog_frame_paints_the_background():
    """`FDialogFrame` 必须自己铺底色 —— 30 个对话框都指望它这一块。"""
    src = _code_only((QML_ROOT / "components" / "FDialogFrame.qml").read_text(encoding="utf-8"))
    assert _FULL_BLEED.search(src), (
        "FDialogFrame 没铺底色：所有以它为根节点的对话框都会漏出透明洞（真窗口下是纯黑，离屏快照反而看不出来）"
    )


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
