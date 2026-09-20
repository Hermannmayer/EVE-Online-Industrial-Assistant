"""页面加载护栏的共用实现 —— 各页面测试只写一行调用。

「能加载 + 桥到位 + 不给 Qt 刷告警」这组检查原先在 5 个页面测试文件里**各抄一份**，
每个文件都带一段 15 行的 `qInstallMessageHandler` 骨架：骨架一变就要改 5 处，
新页面又会再抄第 6 份。按判定表「骨架第二次出现就该收敛」，这里只留一份实现。

窗口尺寸由调用方给：各页是**刻意**不同的（存储页 11 列的宽表要更大才铺得开），
统一成一个值会把某几页的真实布局条件测没。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QObject, QtMsgType, qInstallMessageHandler

from tests.qml_click import spin as _spin

__all__ = ["assert_page_loads_quietly", "page_host"]


@contextmanager
def page_host(qml_file: str, bridge: Any) -> Iterator[tuple[Any, Any]]:
    """建一个承载 `qml_file` 的 `PageHost`，交出 `(host, bridge)`，退出时销毁。

    与各页原 fixture 逐字同构：构造完**不**先跑事件循环（`PageHost` 是同步加载的），
    销毁后补 `spin(60)` 让 `deleteLater` 落地。
    """
    from ui_qml.host import PageHost

    host = PageHost(qml_file, context={"bridge": bridge})
    try:
        yield host, bridge
    finally:
        host.deleteLater()
        _spin(60)


def assert_page_loads_quietly(host: Any, bridge: Any, *, key: str, size: tuple[int, int]) -> QObject:
    """加载成功 + 根对象把桥暴露在 `<key>` 上 + 布局期间 Qt 没刷告警。返回根对象。

    告警这几类都真实出现过，且运行期只表现为「界面不对」：
      - `HorizontalHeaderView` 的 `textRole` 指向模型里没有的角色（每帧一条）；
      - 位置绑定里写 `mapToItem`（不被依赖追踪，控件停在左上角）；
      - 引用**已删除**的桥属性 —— 绑定求值失败是静默的，只会让那一格空着。
    """
    assert host.ok(), "; ".join(str(e) for e in host.errors())

    root = host.rootObject()
    assert root is not None
    assert root.property(key) is bridge

    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            else None
        )
    )
    try:
        root.setProperty("width", size[0])
        root.setProperty("height", size[1])
        _spin(300)
    finally:
        qInstallMessageHandler(previous)

    assert not caught, "QML 产生了告警：\n" + "\n".join(dict.fromkeys(caught))
    return cast(QObject, root)
