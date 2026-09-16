"""剪贴板断言的**有界等待** —— 各页面测试共用。

**为什么不能 `setText()` 之后直接 `text()`**：Windows 上 `QClipboard::setText` 是
**异步**的 —— 它先把内容挂到本进程、再去向系统申领剪贴板所有权，函数返回时系统那边
可能还没拿到数据。而且它用的是**真实系统剪贴板**，同机器上别的进程也能干扰
（剪贴板管理器、其他应用）。

实测到的失败形态是：`setText` 之后立刻 `text()` **读回空串**（不是旧值）。
注意它的复现是**间歇且看环境**的 —— 抓到过一次 300 次里 34 次，之后再跑同样的探针
就一次也复现不出（当时多半有别的进程压着剪贴板）。所以别把它当固定概率；
**结论只需一条：这个读是竞态，不能假设同步**。

这是**测试侧的竞态**，不是产品缺陷：真实用户点一下、过一会儿再粘贴，内容早就到位了。
但用例若直接断言，失败形态恰好是「复制没生效」这种最容易误判成产品 bug 的样子
（本仓因此红过 `test_qml_all_items::test_click_cell_selects_and_copies` 一次）。

用法：

    from tests.clipboard_wait import wait_for_clipboard

    bridge.clickCell(0, 3)
    assert wait_for_clipboard("100.0") == "100.0", "复制的是原始值，不是千分位显示串"

⚠️ 断言里要**同时**写字面量与返回值 —— 只写 `assert wait_for_clipboard(x)` 的话，
失败信息里看不到实际读到了什么，又变成「不知道哪出问题」。
"""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication

__all__ = ["clipboard_text", "wait_for_clipboard", "wait_for_clipboard_prefix"]


def clipboard_text() -> str:
    """当前系统剪贴板的文本（可能尚未同步到位，见模块说明）。"""
    return QGuiApplication.clipboard().text()


def wait_for_clipboard(expected: str, timeout_ms: int = 2000, step_ms: int = 10) -> str:
    """等剪贴板变成 `expected`，返回**最终读到的内容**（超时也返回，交给调用方断言）。

    转事件循环而不是 `time.sleep`：剪贴板的同步要靠 Qt 的事件处理推进，
    纯睡眠会让等待永远等不到。
    """
    text = clipboard_text()
    waited = 0
    while text != expected and waited < timeout_ms:
        loop = QEventLoop()
        QTimer.singleShot(step_ms, loop.quit)
        loop.exec()
        waited += step_ms
        text = clipboard_text()
    return text


def wait_for_clipboard_prefix(prefix: str, timeout_ms: int = 2000, step_ms: int = 10) -> str:
    """等剪贴板内容**以 `prefix` 开头**，返回最终读到的内容。

    有些复制是多列 / 多行的（整表 CSV、带制表符的行），用例断言的是「开头是什么」
    而不是全等 —— 等待条件跟着放宽，否则永远等不到。
    """
    text = clipboard_text()
    waited = 0
    while not text.startswith(prefix) and waited < timeout_ms:
        loop = QEventLoop()
        QTimer.singleShot(step_ms, loop.quit)
        loop.exec()
        waited += step_ms
        text = clipboard_text()
    return text
