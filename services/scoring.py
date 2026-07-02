"""
评分模块 — 向后兼容层。

所有功能已移植到 services.scoring_service。
此模块仅为保持向后兼容保留，将在未来版本中移除。
"""

import warnings

warnings.warn(
    "services.scoring 已弃用，请从 services.scoring_service 直接导入所需组件",
    DeprecationWarning,
    stacklevel=2,
)

from services.scoring_service import (  # noqa: E402
    REACTION_INSTALL_FEE_RATE,
    ScoringCache,
    ScoringService,
    cache_key,
    calc_manufacturing_score,
    calc_reaction_score,
    calc_trade_score,
    db,
    get_cache,
    get_price,
    get_system_cost_index,
    get_volume,
    invalidate_cache,
    set_cache,
)

__all__ = [
    "REACTION_INSTALL_FEE_RATE",
    "ScoringCache",
    "ScoringService",
    "cache_key",
    "calc_manufacturing_score",
    "calc_reaction_score",
    "calc_trade_score",
    "db",
    "get_cache",
    "get_price",
    "get_system_cost_index",
    "get_volume",
    "invalidate_cache",
    "set_cache",
]
