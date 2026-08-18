"""无控制台（--windowed）GUI 下的标准流兜底。

PyInstaller/--windowed 打包的应用没有控制台，`sys.stdout`/`sys.stderr` 为 None。
任何写这两个流的库（logging、tqdm、print）会在第一行输出时抛
`AttributeError: 'NoneType' object has no attribute 'write'`——例如 items/blueprints
初始化步骤里的 `tqdm(...)` 直接导致步骤失败。本模块在应用最早期把 None 的流替换为
静默丢弃的 `NullWriter`，让所有写流的地方都有可靠落点。
"""

from __future__ import annotations

import sys


class NullWriter:
    """静默丢弃所有写入的“黑洞”流，提供 write/flush/isatty 以兼容 io 协议。"""

    def write(self, s) -> int:
        return len(s)

    def flush(self) -> None:
        return

    def isatty(self) -> bool:
        return False

    def writelines(self, lines) -> None:
        return


def ensure_console_streams() -> None:
    """把 None 的 sys.stdout / sys.stderr 替换为 NullWriter。

    必须在任何 print / tqdm / logging 之前调用（如 Main.py 最顶部）。
    """
    if sys.stdout is None:
        sys.stdout = NullWriter()
    if sys.stderr is None:
        sys.stderr = NullWriter()
