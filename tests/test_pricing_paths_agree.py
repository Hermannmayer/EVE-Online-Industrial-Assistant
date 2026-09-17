"""取价的单一定义处 —— 三条调用路径必须给出相同结果。

**为什么值得一条专门的测试**：取价原先有**两份等价 SQL**（`scoring_service` 的模块级
函数直查 market.db，`MarketRepository` 独立一份）。`pricing_service` 的 docstring
曾写着「**改价需两边同步**」—— 那条注释本身就是缺陷的化石：两边真的漏同步过
（`scoring_service._batch_materials` 的注释记录过一次缓存串值）。

2026-09-17 已把两处合一（`MarketRepository` 是唯一定义处，其余为转发）。
这条测试守的就是**合并后不能又裂开**：任何一边被改动而另一边没跟上，这里立刻红。

用**真实数据库**跑（不是 mock）—— 若只在桩上比对，两边同时被同一桩替换就测不出差异。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.fast


@pytest.fixture(scope="module")
def paths():
    """(scoring_service 模块, PricingService 实例)。"""
    import services.scoring_service as ss
    from bootstrap.container import get_container
    from services.pricing_service import PricingService

    return ss, PricingService(get_container().db)


#: 覆盖边界：非法 price_type / 不存在的物品 / 不存在的星系 / hub=None / 未知 hub
_PRICE_CASES = [
    (34, "sell", "Jita"),
    (34, "buy", "Jita"),
    (34, "sell", None),
    (34, "sell", "Amarr"),
    (34, "bogus", "Jita"),  # 非法 price_type → None
    (999999999, "sell", "Jita"),  # 不存在的物品 → None
    (34, "sell", "NotAHub"),  # 未知 hub → 回落 Jita
]

_VOLUME_CASES = [
    (34, "total", "Jita"),
    (34, "buy", "Jita"),
    (34, "sell", "Jita"),
    (34, "total", None),
    (999999999, "total", "Jita"),  # 不存在 → 0
]

_SCI_CASES = [
    (None, "manufacturing", "Jita"),  # system_id=None → 从 hub 推断
    (30000142, "manufacturing", "Jita"),
    (999999, "manufacturing", "Jita"),  # 不存在的星系 → 默认值
    (None, "manufacturing", "Amarr"),
    (None, "manufacturing", "NotAHub"),  # 未知 hub
    (30000142, "researching_time_efficiency", "Jita"),
]


def test_price_paths_agree(paths):
    """两条 get_price 路径必须同值同类型。"""
    ss, ps = paths
    for type_id, price_type, hub in _PRICE_CASES:
        a = ss.get_price(type_id, price_type, hub)
        b = ps.get_price(type_id, price_type, hub)
        assert a == b and type(a) is type(b), f"get_price({type_id}, {price_type!r}, {hub!r}): {a!r} != {b!r}"


def test_volume_paths_agree(paths):
    ss, ps = paths
    for type_id, vol_type, hub in _VOLUME_CASES:
        a = ss.get_volume(type_id, vol_type, hub)
        b = ps.get_volume(type_id, vol_type, hub)
        assert a == b and type(a) is type(b), f"get_volume({type_id}, {vol_type!r}, {hub!r}): {a!r} != {b!r}"


def test_adjusted_price_paths_agree(paths):
    ss, ps = paths
    for type_id in (34, 35, 999999999):
        a = ss.get_adjusted_price(type_id)
        b = ps.get_adjusted_price(type_id)
        assert a == b and type(a) is type(b), f"get_adjusted_price({type_id}): {a!r} != {b!r}"


def test_system_cost_index_paths_agree(paths):
    """SCI 的两条路径同值。

    ⚠️ `scoring_service.get_system_cost_index` 的 **`_db` 在第三位**
    （`(system_id, activity, _db, hub)`，历史签名），而 `PricingService` 的是
    `(system_id, activity, hub)` —— 合并时曾因按位置传参把 hub 传成了 _db，
    直接 `AttributeError`。故此处 scoring 侧**必须用关键字**传 hub。
    """
    ss, ps = paths
    for system_id, activity, hub in _SCI_CASES:
        a = ss.get_system_cost_index(system_id, activity, hub=hub)
        b = ps.get_system_cost_index(system_id, activity, hub)
        assert a == b and type(a) is type(b), f"SCI({system_id}, {activity!r}, {hub!r}): {a!r} != {b!r}"
