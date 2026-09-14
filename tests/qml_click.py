"""表行点击的共享回归辅助 —— 各页面测试共用一份动作序列。

全项目表行的统一契约（实现见 `ui_qml/qml/components/FTableClickArea.qml`）：
**命中在按下那一刻算好，释放时按记下的值派发**。

历史故障：在 delegate 里挂 `TapHandler` 配 `ReleaseWithinBounds`，它是在**释放**时
判定命中的 —— 而表（`TableView` / `ListView`）是 Flickable，甩动/惯性沉降期间内容
会移动，按下位置的 delegate 已被复用走，于是整次点击被丢掉。界面表现就是
「单击不到所对应的行上，有偏移」。

所以每个表页都跑同一段动作：**按下 → 内容移动 → 原处释放 → 该行仍被选中**。
各页面只需给出点击区的 `objectName` 与页面根对象上的「当前行」属性名。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEventLoop, QObject, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

__all__ = ["spin", "area_of", "scrolling_table_of", "press_move_release"]


def spin(ms: int = 150) -> None:
    """跑一小段事件循环（QML 的布局/信号是异步的，断言前要给它机会）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def area_of(root: Any, area_name: str) -> Any:
    area = root.findChild(QObject, area_name)
    assert area is not None, f"QML 里找不到 {area_name}（objectName 改了吗？）"
    return area


def scrolling_table_of(area: Any) -> Any:
    """点击区所属的可滚动表。

    点击区必须声明在表的内部（Flickable 的内联子项进 `contentData`，事件是内容
    坐标 —— 见该组件的坐标约定），所以沿父链找 `contentY` 就能定位。
    """
    node = area.parentItem()
    while node is not None:
        if node.property("contentY") is not None:
            return node
        node = node.parentItem()
    raise AssertionError(f"{area.objectName()} 不在任何可滚动表内")


def press_move_release(
    host: Any, root: Any, *, area_name: str, row: int, read_current, expect: Any = None, delta: int = 1
) -> None:
    """按下第 `row` 行 → 让内容移动 `delta` 行 → 原处释放，断言该行仍被选中。

    `read_current` 是读「当前行」的可调用（多数页面是 `lambda: root.property("currentRow")`；
    也允许读桥上的状态，比如启动器窗口的 `selectedId` —— 那种页面按行号取不到值，
    再用 `expect` 给出期望值（如该行的 id）。
    按下位置按点击区自己的 `rowHeight` / `rowSpacing` 反推，`TableView` 与
    `ListView` 行卡片通用。
    """
    # 有些页面的 fixture 只建 host 不设尺寸，表格高度会是 0 —— 点击区压根不在可点
    # 范围内。辅助自己保证一个够放几行的尺寸，调用方就不必每处再写一遍。
    host.resize(1200, 800)
    host.show()
    spin(250)

    area = area_of(root, area_name)
    table = scrolling_table_of(area)

    stride = float(area.property("rowHeight")) + float(area.property("rowSpacing"))
    content_y = float(table.property("contentY"))
    # 自动退到「能完整显示」的最后一行：各页面窗口高矮不一，把挑可见行的负担留给
    # 每个调用点只会到处踩「用例自身有误」，与要验的东西无关。
    max_row = int((table.height() - stride / 2) / stride) - 1
    row = min(row, max(0, max_row))
    y_in_table = row * stride - content_y + stride / 2
    assert 0 < y_in_table < table.height(), f"用例自身有误：第 {row} 行在 contentY={content_y} 下不可见"

    origin = table.mapToItem(root, 0.0, 0.0)
    host_origin = root.mapToItem(None, origin.x(), origin.y())
    pt = QPoint(int(host_origin.x()) + 60, int(host_origin.y()) + int(y_in_table))

    QTest.mousePress(host, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pt)
    QApplication.processEvents()  # 让「按下」先落地，再动内容
    table.setProperty("contentY", content_y + delta * stride)
    spin()
    QTest.mouseRelease(host, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pt)
    spin()

    got = read_current()
    want = row if expect is None else expect
    assert got == want, f"内容移动 {delta} 行后，当前行应仍是按下那一刻的第 {row} 行（期望 {want}），实得 {got}"
