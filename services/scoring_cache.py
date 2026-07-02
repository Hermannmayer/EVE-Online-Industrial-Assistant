"""
评分结果缓存 — 向后兼容层。

已弃用：请直接从 services.scoring 导入 ScoringCache / cache_key。
此模块仅为保持向后兼容保留，将在未来版本中移除。
"""

import warnings

warnings.warn(
    "services.scoring_cache 已弃用，请从 services.scoring 直接导入 ScoringCache / cache_key",
    DeprecationWarning,
    stacklevel=2,
)

from services.scoring import (  # noqa: F401
    ScoringCache,
    cache_key,
)
from services.scoring import (
    get_cache as get,
)
from services.scoring import (
    invalidate_cache as invalidate,
)
from services.scoring import (
    set_cache as set,
)

__all__ = [
    "ScoringCache",
    "cache_key",
    "get",
    "invalidate",
    "set",
]
