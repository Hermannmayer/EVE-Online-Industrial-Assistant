"""向后兼容 shim — 下载器已迁移到 services/importers。

保留旧导入路径（services.workers.getprices 等）与测试 patch 语义：
sys.modules 别名 + 父包属性都指向 services.importers 下的同名真实模块。
"""

import sys

from services import importers as _imp

_pkg = sys.modules[__name__]
for _name in ("getprices", "getindustry", "getcontracts"):
    _mod = getattr(_imp, _name)
    sys.modules[f"{__name__}.{_name}"] = _mod
    setattr(_pkg, _name, _mod)
