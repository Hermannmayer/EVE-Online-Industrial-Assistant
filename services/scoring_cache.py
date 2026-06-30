"""
评分结果缓存 — 向后兼容层。

实际实现已迁移到 services/scoring.py，此模块仅重新导出以保持向后兼容。
"""

from services.scoring import (  # noqa: F401
    ScoringCache,
    cache_key,
    get_cache as get,
    invalidate_cache as invalidate,
    set_cache as set,
)
