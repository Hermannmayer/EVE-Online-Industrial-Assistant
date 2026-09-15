"""生产计划表的「多选」与「右键菜单」回归。

对应阶段 2a 上线后暴露的两个故障，**都出在选中上**：

**其一（已修）**：`PlanTablePane.qml` 的 `loadedCell()` 调了
`tableView.itemAtIndex(row, col)`。而 `QQuickTableView::itemAtIndex` 的签名是
**`itemAtIndex(QModelIndex)`**（按单元格取 delegate 的是 `itemAtCell(column, row)`），
传两个 int 进去，Qt 在运行期报：

    Too many arguments, ignoring 1
    Could not convert argument 0 from 0 to QModelIndex
    TypeError: Passing incompatible arguments to C++ functions from JavaScript is not allowed.

调用链 `右键 TapHandler → openRowMenu → rowsForMenu → loadedCell`，异常在
`rowMenu.open()` **之前**抛出 —— 右键菜单永远打不开（JS 异常被 Qt 吞成一条 WARNING）。

**其二（本文件的主要防线）**：Qt 6.11 的 `TableView` **内建点击选中不工作**。
最小 QML 复现（与 delegate 有无 handler 无关）：不给 `selectionModel` 时它恒为 null，
`selectionMode` 设成 Single/Extended 也不会自建；自己塞一个进去再点击，`currentRow`
会更新（说明按下确实到了 TableView），但选中集**只被清空、从不写入**。
所以选中改由 `PlanTableBridge` 自己实现（`selectRow` / `ensureRowSelected`），
并用 `selectionBehavior: TableView.SelectionDisabled` 把 Qt 的内建选中关掉。

**这些只能靠真鼠标验证**：两个故障在运行期都只表现为一条被吞掉的 WARNING，
静态检查和纯 Python 断言都拦不住。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QObject, QPoint, Qt, QTimer, QtMsgType, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import ui_pyside6.theme as theme
from ui_pyside6.models.industry_models import PlanTableModel
from ui_pyside6.views.industry.plan_table import PlanTable

pytestmark = pytest.mark.ui

QML_ROOT = Path(__file__).resolve().parent.parent / "ui_qml" / "qml"
PANE = QML_ROOT / "pages" / "PlanTablePane.qml"

#: 点在这一列上只会改变选中，不会触发任何业务动作。
#: 列 0 是备料勾选、列 1/2 是图标列、列 3 是产品列 —— 产品列只有带折叠箭头
#: 或合成行时才是可点击的，本文件的测试数据两者都没有。
_SAFE_COLUMN_X = 200


def _spin(ms: int = 150) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_until(predicate, timeout_ms: int = 1500) -> bool:
    """轮询等待条件成立。

    `Menu.open()` 是**异步**的：点击返回时 `opened` 还是 false，要等弹出物真正建立
    才变 true（实测 100ms 时仍为 false、300ms 时已为 true）。固定 sleep 会在慢机器上
    偶发失败，这里按条件轮询。
    """
    waited = 0
    while waited < timeout_ms:
        if predicate():
            return True
        _spin(50)
        waited += 50
    return bool(predicate())


def _plans(count: int = 6) -> list[dict]:
    return [
        {
            "id": i + 1,
            "product_name": f"产品{i}",
            "status": "pending",
            "runs": 1,
            "parallels": 1,
        }
        for i in range(count)
    ]


def _find_menu(root: QObject, name: str) -> QObject:
    found = root.findChild(QObject, name)
    assert found is not None, f"QML 里找不到 {name}（objectName 改了吗？）"
    return found


def _wait_open(root: QObject, name: str) -> QObject:
    menu = _find_menu(root, name)
    assert _wait_until(lambda: menu.property("opened") is True), f"{name} 没有打开"
    return menu


@pytest.fixture
def table(qapp):
    widget = PlanTable()
    widget.set_model(PlanTableModel(_plans()))
    # 高度要放得下整个右键菜单（约 470px）：悬停子菜单的用例要把鼠标移到菜单下部的
    # 「智能调整」上，落点必须还在控件内，否则事件根本递不进去（实测踩过）
    widget.resize(900, 640)
    widget.move(60, 60)  # 固定窗口位置：悬停用例要把鼠标移到控件内某点，位置不确定时
    widget.show()  # 换算出的全局坐标可能落到屏幕外，事件就递不进去
    _spin(400)  # 等 QML 完成布局：后面要按 rowH / headerH 算点击坐标
    yield widget
    widget.close()
    widget.deleteLater()
    _spin(60)


# ════════════════════════════════════════════════════════════
#  静态护栏
# ════════════════════════════════════════════════════════════


def test_pane_does_not_use_itemAtIndex():
    """`itemAtIndex` 只吃 `QModelIndex`，传行列号是运行期才炸的 TypeError。

    要按行列取 delegate 用 `itemAtCell(column, row)`（注意是**列在前**）。
    本用例做静态检查，因为运行时只会得到一条被吞掉的 WARNING：
    界面表现为「右键没反应」，日志里才有线索。
    """
    text = PANE.read_text(encoding="utf-8")
    assert not re.search(r"\bitemAtIndex\s*\(", text), (
        "PlanTablePane.qml 又用上了 itemAtIndex。它的签名是 itemAtIndex(QModelIndex)，"
        "不是 (row, column)；按单元格取 delegate 请用 itemAtCell(column, row)。"
    )


def test_pane_keeps_builtin_selection_disabled():
    """内建选中必须关掉，否则每次点击都会把 bridge 设好的选中集抹掉。

    开关是 `selectionBehavior: SelectionDisabled` —— 枚举里**没有** `NoSelection`
    （只有 Single/Contiguous/Extended），写成 NoSelection 会得到 undefined，
    Qt 只记一条 assign 告警然后静默保留原值（实测踩过）。
    """
    text = PANE.read_text(encoding="utf-8")
    assert "selectionBehavior: TableView.SelectionDisabled" in text, (
        "计划表的选中由 PlanTableBridge 实现；不关掉内建选中，每次点击都会清空 bridge 刚设的选中集。"
    )
    assert not re.search(r"^\s*selectionMode\s*:\s*TableView\.NoSelection", text, re.MULTILINE), (
        "`TableView.NoSelection` 不存在（SelectionMode 枚举只有 Single/Contiguous/Extended），"
        "会让 selectionMode 静默保持原值。"
    )


def test_pane_binds_the_bridge_selection_model():
    """选中模型由桥持有并绑到 `TableView.selectionModel`，delegate 的 `selected` 才会跟随。"""
    text = PANE.read_text(encoding="utf-8")
    assert "planBridge.selectionModel" in text
    assert "planBridge.selectRow(" in text, "左键必须经桥落选中"
    assert "planBridge.ensureRowSelected(" in text, "右键要先把选中换到点中的行"


@pytest.fixture
def qt_warnings():
    """捕获测试期间的 Qt 告警（Qt 会把 QML 运行期错误也走这条路，且只记 WARNING）。"""
    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{ctx.file}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            else None
        )
    )
    try:
        yield caught
    finally:
        qInstallMessageHandler(previous)


def test_load_and_interact_without_qml_warnings(qt_warnings, qapp):
    """加载 + 点选 + 右键全流程不许有任何 QML 告警。

    这三类告警都真实出现过，且运行期只表现为「界面没反应」：
      - `HorizontalHeaderView` 的 textRole 指向模型里不存在的角色（每帧一条）；
      - `TableView.itemAtIndex` 传错参数（TypeError）；
      - `selectionMode: TableView.NoSelection`（该值不存在 → undefined 赋值）。
    前两个用静态护栏也能拦，但这条是唯一能覆盖「加载期整体是否干净」的兜底。
    """
    widget = PlanTable()
    widget.set_model(PlanTableModel(_plans()))
    widget.resize(900, 400)
    widget.show()
    _spin(500)

    host = widget._host
    assert host is not None
    root = host.rootObject()
    header_h = int(root.property("headerH"))
    row_h = int(root.property("rowH"))

    def click(row: int, button: Qt.MouseButton, modifier: Qt.KeyboardModifier) -> None:
        QTest.mouseClick(host, button, modifier, QPoint(_SAFE_COLUMN_X, header_h + row_h * row + row_h // 2))
        _spin()

    try:
        click(0, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        click(1, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier)
        click(1, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier)
        _spin(400)
        # 右键落在选中集内 → 选中集原样保留（菜单作用于 [0, 1] 两行）
        assert widget.bridge.selectedRows() == [0, 1]
    finally:
        widget.close()
        widget.deleteLater()
        _spin(60)

    assert not qt_warnings, "QML 产生了告警：\n" + "\n".join(dict.fromkeys(qt_warnings))


# ════════════════════════════════════════════════════════════
#  桥契约
# ════════════════════════════════════════════════════════════


def test_selection_model_follows_the_model(table):
    """换模型必须换选中模型 —— 否则选中模型会挂在一个已失效的模型上。"""
    first = table.bridge.selectionModel
    assert first is not None
    assert first.model() is table.get_model()

    table.set_model(PlanTableModel(_plans(3)))
    second = table.bridge.selectionModel
    assert second is not first
    assert second.model() is table.get_model()


def test_selected_rows_is_empty_without_selection(table):
    assert table.bridge.selectedRows() == []


def test_select_row_ignores_out_of_range_rows(table):
    """越界行号（delegate 回收期的陈旧 row）不能抛异常，也不能污染选中集。"""
    table.bridge.selectRow(999)
    table.bridge.selectRow(-1)
    assert table.bridge.selectedRows() == []


# ════════════════════════════════════════════════════════════
#  真鼠标：多选与右键菜单
# ════════════════════════════════════════════════════════════


class _Clicks:
    """按 QML 里的 rowH / headerH 换算点击坐标。"""

    def __init__(self, table: PlanTable):
        host = table._host
        assert host is not None, "PlanTable 没有 QML 宿主，量不了点击坐标"
        self.host = host
        self.root = host.rootObject()
        self.header_h = int(self.root.property("headerH"))
        self.row_h = int(self.root.property("rowH"))

    def row_point(self, row: int) -> QPoint:
        return QPoint(_SAFE_COLUMN_X, self.header_h + self.row_h * row + self.row_h // 2)

    def click(self, row: int, modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
        QTest.mouseClick(self.host, Qt.MouseButton.LeftButton, modifier, self.row_point(row))
        _spin()

    def right_click(self, row: int) -> None:
        QTest.mouseClick(self.host, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, self.row_point(row))

    def menu(self, name: str) -> QObject:
        found = self.root.findChild(QObject, name)
        assert found is not None, f"QML 里找不到 {name}（objectName 改了吗？）"
        return found

    def wait_open(self, name: str) -> QObject:
        menu = self.menu(name)
        assert _wait_until(lambda: menu.property("opened") is True), f"{name} 没有打开"
        return menu


@pytest.fixture
def clicks(table):
    assert table._host is not None
    clicks = _Clicks(table)
    assert clicks.header_h > 0 and clicks.row_h > 0, "QML 还没布局完，量不到行高"
    return clicks


def test_plain_click_selects_one_row(table, clicks):
    clicks.click(1)
    assert table.bridge.selectedRows() == [1]


def test_plain_click_replaces_the_previous_selection(table, clicks):
    clicks.click(1)
    clicks.click(3)
    assert table.bridge.selectedRows() == [3]


def test_ctrl_click_selects_multiple_rows(table, clicks):
    """Ctrl+点击必须累积选中 —— 批量操作全靠它。"""
    clicks.click(0)
    assert table.bridge.selectedRows() == [0]

    clicks.click(2, Qt.KeyboardModifier.ControlModifier)
    assert table.bridge.selectedRows() == [0, 2]

    clicks.click(4, Qt.KeyboardModifier.ControlModifier)
    assert table.bridge.selectedRows() == [0, 2, 4]

    # Ctrl 再点一次取消该行
    clicks.click(2, Qt.KeyboardModifier.ControlModifier)
    assert table.bridge.selectedRows() == [0, 4]


def test_shift_click_selects_a_range_from_the_anchor(table, clicks):
    clicks.click(1)
    clicks.click(4, Qt.KeyboardModifier.ShiftModifier)
    assert table.bridge.selectedRows() == [1, 2, 3, 4]

    # 锚点保持在 1：再 Shift 点回去应收窄而不是换成 [4..1] 之外的东西
    clicks.click(2, Qt.KeyboardModifier.ShiftModifier)
    assert table.bridge.selectedRows() == [1, 2]


def test_shift_click_without_anchor_falls_back_to_single(table, clicks):
    """没点过就直接 Shift（锚点未建立）时不能清空选中集。"""
    clicks.click(2)
    table.bridge._anchor_row = -1  # 模拟锚点失效（模型重置过）
    clicks.click(4, Qt.KeyboardModifier.ShiftModifier)
    assert table.bridge.selectedRows() == [4]


def test_right_click_opens_menu_over_the_whole_selection(table, clicks):
    """右键菜单：既要**打得开**，作用行集也要覆盖整个选中集。

    修复前 `openRowMenu` 在 `rowsForMenu` 里抛 TypeError，异常在 `rowMenu.open()`
    之前就冒出去，菜单根本不出现（Qt 只记一条 WARNING）。
    """
    clicks.click(0)
    clicks.click(1, Qt.KeyboardModifier.ControlModifier)

    clicks.right_click(1)

    menu = clicks.wait_open("rowMenu")
    assert list(menu.property("targetRows")) == [0, 1]


def test_right_click_on_unselected_row_targets_only_it(table, clicks):
    """对齐 `QAbstractItemView`：右键落在未选中行上时，选中集换成该行、只作用于它。"""
    clicks.click(0)
    clicks.click(2, Qt.KeyboardModifier.ControlModifier)
    assert table.bridge.selectedRows() == [0, 2]

    clicks.right_click(4)

    assert table.bridge.selectedRows() == [4]
    menu = clicks.wait_open("rowMenu")
    assert list(menu.property("targetRows")) == [4]


def _menu_entries(menu: QObject) -> list:
    """菜单里真正当条目用的项（MenuItem / MenuSeparator），不含 ListView 滚动容器。"""
    out = []
    stack = [menu.property("contentItem")]
    while stack:
        item = stack.pop()
        if item is None:
            continue
        meta = item.metaObject()
        if meta.indexOfProperty("text") >= 0 or "Separator" in meta.className():
            out.append(item)
        stack.extend(item.childItems())
    return out


def test_menu_has_no_reserved_blank_rows(table, clicks):
    """条件显示的菜单项在不可见时必须把高度一并压掉，否则菜单里是一串空行。

    Qt 的 `Menu` 用 ListView 渲染**全部声明项**，`visible: false` 的条目照样占满
    一整行（实测 h=30 且 y 照排），把后面的项整体推下去 —— 用户看到的「一堆空行」。
    状态为 pending 的行会让「撤销启动 / 下线 / 设为待生产」三项都不可见，覆盖面最大。
    """
    clicks.right_click(0)
    menu = clicks.wait_open("rowMenu")

    offenders = [
        (item.property("text"), item.height())
        for item in _menu_entries(menu)
        if item.property("visible") is False and item.height() > 0
    ]

    assert not offenders, f"不可见的菜单项仍然占着高度：{offenders}"


def test_submenu_does_not_open_with_the_parent_menu(qapp):
    """「智能调整」二级菜单**从头到尾**都不能随父菜单弹出来 —— 一帧都不行。

    这条之前是「打开后断言一次 `opened is False`」，**拦不住真正的缺陷**：实测那条路径下
    子菜单会被弹出来、再被 `onOpened` 里的兜底收回去，中间那 160ms 就是用户看到的
    「二级菜单闪一下然后关闭」，而事后采样早已是 False。

    所以这里**逐帧采样**：打开后连续 8 帧检查 `visible` 与 `opened`，只要有一帧为真就失败。

    根因与修法：子菜单原先写了 `visible: !rowMenu.state.synthetic` —— `Menu` 是 `Popup`，
    给 `visible` 赋值就是打开它，每次右键（`state` 被赋值）都会重算成 true 把它弹出来。
    那行**还根本没起到隐藏作用**（嵌套菜单的 visible 由 Qt 托管）。现在改成 `enabled`，
    并去掉了 `onOpened: smartMenu.close()` 这个只治症状的兜底。

    **本用例自己建窗口**，不复用 `table` 夹具：这条路径要求主题在 QML 建好**之前**
    就已应用（与 `Main.py` 的启动顺序一致），复用夹具时主题只能建完再应用。
    """
    theme.apply_theme("fluent-dark")

    widget = PlanTable()
    widget.set_model(PlanTableModel(_plans()))
    widget.resize(900, 640)
    widget.show()
    _spin(600)

    try:
        host = widget._host
        assert host is not None
        root = host.rootObject()
        header_h = int(root.property("headerH"))
        row_h = int(root.property("rowH"))

        submenu = root.findChild(QObject, "smartMenu")
        assert submenu is not None, "找不到智能调整子菜单（objectName 改了吗？）"

        QTest.mouseClick(
            host,
            Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(_SAFE_COLUMN_X, header_h + row_h + row_h // 2),
        )
        _wait_open(root, "rowMenu")

        # 逐帧采样：单次事后断言看不到「弹出又被收回」那一瞬
        popped: list[str] = []
        for i in range(8):
            _spin(40)
            visible = bool(submenu.property("visible"))
            opened = bool(submenu.property("opened"))
            if visible or opened:
                popped.append(f"t={(i + 1) * 40}ms visible={visible} opened={opened}")
        assert not popped, "二级菜单随父菜单弹出来了（用户看到的就是这一闪）：" + "; ".join(popped)
    finally:
        widget.close()
        widget.deleteLater()
        _spin(60)


def test_header_menu_opens(table, clicks):
    """表头右键（列可见性）走的是另一条路径，一并钉住。"""
    QTest.mouseClick(
        clicks.host,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(_SAFE_COLUMN_X, clicks.header_h // 2),
    )

    clicks.wait_open("headerMenu")


# ════════════════════════════════════════════════════════════
#  真鼠标：点击命中必须在**按下那一刻**定下来
# ════════════════════════════════════════════════════════════


def _owning_table(area):
    """点击区所属的 TableView。

    **不能**按「第一个 className 含 TableView 的子项」找：`HorizontalHeaderView`
    内部也有一个 TableView，谁先被遍历到不确定（合并跑时踩到过，同一用例单跑通过）。
    点击区是 TableView 的内联子项（挂在 contentItem 下），从它往父链走是确定的。
    """
    node = area.parentItem()
    while node is not None:
        if "TableView" in node.metaObject().className():
            return node
        node = node.parentItem()
    return None


def _cell_center(root, area, row: int, column: int):
    """从**真实 delegate 几何**取该格中心（不自己按 contentY 推算，少一层假设）。"""
    for ch in area.parentItem().childItems():
        try:
            if ch.property("row") == row and ch.property("column") == column:
                p = ch.mapToItem(root, ch.width() / 2, ch.height() / 2)
                return QPoint(int(p.x()), int(p.y()))
        except Exception:
            continue
    return None


@pytest.mark.ui
def test_click_keeps_the_pressed_row_when_content_moves(qapp):
    """回归：按下与释放之间内容移动（甩动/惯性沉降），仍应选中**按下那一刻**的行。

    故障表现：`delegate` 里的 `TapHandler` 配 `ReleaseWithinBounds` 是在**释放**时
    判定命中的，而 `TableView` 是 Flickable —— 内容一移动，按下位置的 delegate 就被
    复用走了，于是整次点击被丢掉，界面表现就是「单击不到所对应的行上」。

    这里用「按住不动 → 程序移动内容 → 原处释放」确定性复现：内容移动与鼠标无关，
    正是甩动/沉降期间的真实情形。
    """
    widget = PlanTable()
    widget.set_model(PlanTableModel(_plans(120)))
    widget.resize(900, 400)
    widget.move(60, 60)
    widget.show()
    _spin(500)
    try:
        host = widget._host
        assert host is not None
        root = host.rootObject()
        area = root.findChild(QObject, "planClickArea")
        assert area is not None, "PlanTablePane.qml 里找不到 planClickArea"
        view = _owning_table(area)
        assert view is not None, "点击区不在 TableView 里（坐标约定会变，见 FTableClickArea 说明）"
        row_h = int(root.property("rowH"))

        # (内容位移, 目标行, 释放前内容再移动几行)
        for content_y, row, delta in ((0.0, 3, 1), (0.0, 5, -2), (300.0, 14, 2)):
            view.setProperty("contentY", content_y)
            _spin(250)
            pt = _cell_center(root, area, row, 1)  # 列 1 是图标列，点击无业务副作用
            assert pt is not None, f"第 {row} 行在 contentY={content_y} 下没被实例化"

            QTest.mousePress(host, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pt)
            QApplication.processEvents()  # 让「按下」先落地，再动内容
            view.setProperty("contentY", float(view.property("contentY")) + delta * row_h)
            _spin(60)
            QTest.mouseRelease(host, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pt)
            _spin(200)

            assert widget.bridge.selectedRows() == [row], (
                f"contentY={content_y} 内容移动 {delta} 行后，应仍选中按下的第 {row} 行"
            )
    finally:
        widget.close()
        widget.deleteLater()
        _spin(60)


@pytest.mark.ui
def test_double_click_opens_inline_editor_for_editable_cell(qapp):
    """双击可编辑列 → 就地编辑框出现（原实现里这条路径实测触发不到）。"""
    widget = PlanTable()
    widget.set_model(PlanTableModel(_plans(20)))
    widget.resize(900, 500)
    widget.move(60, 60)
    widget.show()
    _spin(500)
    try:
        host = widget._host
        assert host is not None
        root = host.rootObject()
        area = root.findChild(QObject, "planClickArea")
        assert area is not None
        editor = root.findChild(QObject, "inlineEditor")
        assert editor is not None

        editable_col = next((c for c in range(21) if widget.bridge.isCellEditable(0, c)), None)
        assert editable_col is not None, "模型里没有可编辑列了？"
        pt = _cell_center(root, area, 0, editable_col)
        assert pt is not None and pt.x() < widget.width(), f"列 {editable_col} 没在视口内"

        QTest.mouseDClick(host, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pt)
        _spin(500)

        assert editor.property("visible") is True, "双击可编辑列应打开就地编辑框"
        assert int(root.property("editRow")) == 0
        assert int(root.property("editCol")) == editable_col
    finally:
        widget.close()
        widget.deleteLater()
        _spin(60)


@pytest.mark.ui
def test_double_click_non_editable_cell_takes_the_dialog_path(qapp):
    """双击不可编辑列 → 走「打开编辑生产计划对话框」；且不误改选中集。

    Qt 对双击**不发**第一次的 `clicked`，所以双击只跑双击那一次动作，
    不会先把单击的副作用（勾选/折叠/选中）做掉。
    """
    widget = PlanTable()
    widget.set_model(PlanTableModel(_plans(20)))
    widget.resize(900, 500)
    widget.move(60, 60)
    widget.show()
    _spin(500)
    try:
        host = widget._host
        assert host is not None
        root = host.rootObject()
        area = root.findChild(QObject, "planClickArea")
        assert area is not None
        non_editable = next(c for c in range(21) if not widget.bridge.isCellEditable(0, c))
        pt = _cell_center(root, area, 0, non_editable)
        assert pt is not None and pt.x() < widget.width()

        opened: list[int] = []
        widget.bridge.doubleClick = lambda row: opened.append(row)  # 拦掉真对话框
        widget.bridge.selectRow(9)
        _spin(200)

        QTest.mouseDClick(host, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pt)
        _spin(600)

        assert opened == [0], "双击不可编辑列应开编辑对话框"
        assert widget.bridge.selectedRows() == [9], "双击不该顺手改掉选中集"
    finally:
        widget.close()
        widget.deleteLater()
        _spin(60)
