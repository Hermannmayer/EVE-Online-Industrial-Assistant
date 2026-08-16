"""领域端口协议 — 定义领域纯函数依赖的数据访问接口。

由 services/application 层的适配器实现，领域层只依赖协议不依赖具体实现。
"""

from __future__ import annotations

from typing import Protocol


class PriceProvider(Protocol):
    """价格 / 成交量 / 成本指数访问接口。"""

    def get_price(self, type_id: int, price_type: str, hub: str | None = None) -> float | None: ...

    def get_volume(self, type_id: int, vol_type: str = "total", hub: str | None = None) -> int: ...

    def get_system_cost_index(
        self, system_id: int | None, activity: str = "manufacturing", hub: str = "Jita"
    ) -> float: ...

    def get_adjusted_price(self, type_id: int) -> float | None: ...
