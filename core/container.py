"""IOC 容器（兼容转发）。

实际组合根已迁移到 `bootstrap.container`，本模块保留旧导入路径
`from core.container import get_container` 以兼容现有调用方。
"""

from bootstrap.container import (
    AppContainer,
    get_container,
    init_container,
)

__all__ = ["AppContainer", "get_container", "init_container"]
