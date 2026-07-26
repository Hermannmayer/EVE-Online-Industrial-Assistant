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
    ScoringService,
)
