"""评分编排门面（兼容转发）。

实际实现已下沉到 `services.scoring_facade`，本模块保留旧导入路径
`application.scoring_facade.calc_*` 以兼容现有调用方与测试。
"""

from services.scoring_facade import (
    _char_config_fingerprint,
    _DbPriceProvider,
    calc_manufacturing_score,
    calc_reaction_score,
    calc_trade_score,
)

__all__ = [
    "_DbPriceProvider",
    "_char_config_fingerprint",
    "calc_manufacturing_score",
    "calc_reaction_score",
    "calc_trade_score",
]
