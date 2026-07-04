"""
评分模块 — 已弃用。

所有功能已迁移至 services.scoring_service。
此文件仅为保留向后兼容而保留，将在未来版本中移除。

请将 import 从 services.scoring 改为 services.scoring_service。
"""

import warnings as _warnings

_warnings.warn(
    "services.scoring 已弃用，请从 services.scoring_service 直接导入",
    DeprecationWarning,
    stacklevel=2,
)

from services.scoring_service import (  # noqa: F401, E402
    REACTION_INSTALL_FEE_RATE,
    ScoringCache,
    ScoringService,
    _get_scoring_service,
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
    resolve_char_config,
    set_cache,
)
