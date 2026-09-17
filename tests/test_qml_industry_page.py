"""工业页 QML 的运行时位置类护栏。

只放「静态扫描看不出来、必须在真界面里量」的问题。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject
from PySide6.QtQuick import QQuickItem

from tests.qml_click import spin as _spin

pytestmark = pytest.mark.ui


def _find_by_placeholder(root: QQuickItem, text: str) -> QQuickItem | None:
    stack: list[QQuickItem] = list(root.childItems())
    while stack:
        item = stack.pop()
        if item.metaObject().indexOfProperty("placeholderText") >= 0:
            try:
                if item.property("placeholderText") == text:
                    return item
            except Exception:
                pass
        stack.extend(item.childItems())
    return None


def test_suggestion_popup_anchors_below_the_input(main_window, qapp):
    """蓝图候选框必须贴在输入框正下方，不能落在页面左上角。

    原写法 `x: input.mapToItem(page, 0, 0).x` **建立不起绑定依赖**：`mapToItem` 在 C++
    里读的几何属性不被 QML 的依赖追踪记录，整条绑定只在创建时求值一次，而那一刻输入框
    还没布局完（坐标 0,0）—— 候选框于是永远贴在左上角（用户反馈实测踩过）。
    改成「以输入框为父项 + 相对偏移」后，位置由 Qt 的弹出物定位在 open 时换算。

    ⚠️ 批次 7.4 起工业页控制器是纯 `QObject`、**不再自建宿主**（`page._host` 已删），
    渲染面只存在于外壳的场景里 —— 所以这里改从**外壳**取根项。原先的 `page.resize/show`
    也一并换成外壳的（要量的本来就是它在真实布局下的位置）。
    """
    main_window.resize(1200, 720)
    main_window.show()
    main_window.navigate_to("industry")
    _spin(400)

    root = main_window._pages["industry"].item
    popup = root.findChild(QObject, "suggestionPopup")
    assert popup is not None, "找不到候选框（objectName 改了吗？）"
    field = _find_by_placeholder(root, "粘贴蓝图名或剪贴板内容")
    assert field is not None, "找不到蓝图输入框"

    # 绕开「得先有搜索建议」的前置条件，直接把弹层显出来量位置
    popup.setProperty("visible", True)
    _spin(250)

    assert popup.property("parent") is field, "候选框必须以输入框为父项 —— 位置才跟着输入框走，由 Qt 在 open 时换算"

    field_at = field.mapToItem(None, 0, 0)
    popup_at = field.mapToItem(None, float(popup.property("x")), float(popup.property("y")))

    assert not (abs(popup_at.x()) < 2 and abs(popup_at.y()) < 2), "候选框又跑回页面左上角了"
    assert popup_at.y() >= field_at.y() + field.height() - 2, (
        f"候选框没有贴在输入框下方：输入框底边 y={field_at.y() + field.height():.0f}，候选框顶边 y={popup_at.y():.0f}"
    )
