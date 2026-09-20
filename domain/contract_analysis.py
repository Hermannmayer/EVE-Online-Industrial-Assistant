"""合同「值不值得」判定 —— 纯计算，无 DB / Qt / 缓存。

三个子页共用的口径都收在这里，调用方（`services/contract_service.py`）只负责把
物品、价格、配方查好传进来：

  拍卖 / 物品交换 —— 合同内容物的市场价 vs 合同价（一口价优先，其次当前出价）
  含蓝图合同      —— 蓝图本身市价 + 制造利润，再与合同价比
  运输合同        —— 每跳 ISK / 每方每跳 ISK（跳数由调用方算好传进来 ——
                     本地 BFS 要查星门图，不属于「纯计算」）

**价格缺失绝不静默当 0**：一件没价的物品按 0 计，会把「总市价」压低成假信号，
让用户以为合同大幅折价。缺价时 `status` 置为非空、价差置 None，由界面显示「—」。
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from domain.formulas import calc_material_for_runs

#: 判定结果的状态码 —— 界面**按码分支**，不解析中文文案。
STATUS_OK = "ok"
STATUS_NO_ITEMS = "no_items"  # 合同里没有物品（courier，或物品还没拉）
STATUS_NO_PRICE = "no_price"  # 有物品但一件都查不到价
STATUS_PARTIAL_PRICE = "partial_price"  # 部分物品缺价 —— 价差偏低，仅供参考

PriceMap = Mapping[int, float]
Item = Mapping[str, Any]
Contract = Mapping[str, Any]


def parse_expiry(date_expired: str | None) -> datetime | None:
    """ESI 的 `date_expired` → datetime；解析不出返回 None。"""
    if not date_expired:
        return None
    try:
        return datetime.fromisoformat(str(date_expired).replace("Z", "+00:00"))
    except ValueError:
        return None


def remaining_seconds(date_expired: str | None, now: datetime | None = None) -> int | None:
    """距离过期还有多少秒；已过期为负；解析不出返回 None。"""
    expiry = parse_expiry(date_expired)
    if expiry is None:
        return None
    return int((expiry - (now or datetime.now(UTC))).total_seconds())


def total_quantity(items: Sequence[Item]) -> int:
    return sum(int(it.get("quantity") or 0) for it in items)


def market_value(items: Sequence[Item], price_map: PriceMap) -> tuple[float, int, int]:
    """合同内容物的市场总价 → `(总价, 有价的物品数, 缺价的物品数)`。

    蓝图复制品按它自己的市价算 —— 市价里已经含了可运行数，不再乘 `runs`。
    """
    total = 0.0
    priced = 0
    missing = 0
    for it in items:
        unit = price_map.get(int(it.get("type_id") or 0))
        if unit is None or unit <= 0:
            missing += 1
            continue
        total += float(unit) * int(it.get("quantity") or 0)
        priced += 1
    return total, priced, missing


#: 合同行前面画几件物品的图标。3 件足以看出「里面是什么」，再多会挤掉标题。
ICON_ITEM_LIMIT = 3


def icon_type_ids(items: Sequence[Item], price_map: PriceMap, limit: int = ICON_ITEM_LIMIT) -> list[int]:
    """合同行前面该画哪几件物品的图标 —— 按 `单价 × 数量` 降序取前 `limit` 件。

    取「值钱的」而不是「列在前面的」：一份合同动辄几十件，排第一的往往是顺手塞的杂物，
    看图标的人想知道的是这份合同的核心是什么。

    缺价的物品**排在有价的之后**（内部再按数量降序），不拿 0 参与价值排序 ——
    否则缺价时大家并列，排序退化成「数据库给什么序就什么序」，同一份合同每次刷新
    图标都在变。同 type_id 只画一次。
    """

    def _rank(item: Item) -> tuple[int, float, int, int]:
        unit = float(price_map.get(int(item.get("type_id") or 0)) or 0)
        quantity = int(item.get("quantity") or 0)
        return (0 if unit > 0 else 1, -(unit * quantity), -quantity, int(item.get("type_id") or 0))

    out: list[int] = []
    for item in sorted(items, key=_rank):
        type_id = int(item.get("type_id") or 0)
        if type_id and type_id not in out:
            out.append(type_id)
        if len(out) >= limit:
            break
    return out


def price_diff(value: float | None, cost: float | None) -> tuple[float | None, float | None]:
    """`(价差, 价差%)`。任一为 None 或成本 ≤ 0 时百分比无法定义 → 返回 None。"""
    if value is None or cost is None:
        return None, None
    diff = value - cost
    pct = (diff / cost * 100.0) if cost > 0 else None
    return diff, pct


def _value_status(items: Sequence[Item], priced: int, missing: int) -> str:
    if not items:
        return STATUS_NO_ITEMS
    if priced == 0:
        return STATUS_NO_PRICE
    return STATUS_PARTIAL_PRICE if missing else STATUS_OK


def _base_metrics(contract: Contract, items: Sequence[Item], price_map: PriceMap, now: datetime | None) -> dict:
    value, priced, missing = market_value(items, price_map)
    return {
        "market_value": value,
        "priced_items": priced,
        "unpriced_items": missing,
        "total_quantity": total_quantity(items),
        "volume_m3": float(contract.get("volume") or 0),
        "remaining_seconds": remaining_seconds(contract.get("date_expired"), now),
        "status": _value_status(items, priced, missing),
    }


def auction_metrics(
    contract: Contract,
    items: Sequence[Item],
    price_map: PriceMap,
    now: datetime | None = None,
) -> dict:
    """拍卖合同：把「内容物市价」与「要花多少钱拿到手」比。

    一口价（`buyout` > 0）能直接买断，按它算；没有一口价就要继续叫价，
    按当前出价（`price`）算 —— 后者是**下限**，实际会更高。
    """
    buyout = float(contract.get("buyout") or 0)
    current_bid = float(contract.get("price") or 0)
    entry_cost = buyout if buyout > 0 else current_bid

    out = _base_metrics(contract, items, price_map, now)
    diff, pct = price_diff(out["market_value"], entry_cost)
    out.update(
        {
            "buyout": buyout,
            "current_bid": current_bid,
            "entry_cost": entry_cost,
            "entry_kind": "buyout" if buyout > 0 else "bid",
            "price_diff": diff,
            "diff_pct": pct,
        }
    )
    return out


def exchange_metrics(
    contract: Contract,
    items: Sequence[Item],
    price_map: PriceMap,
    now: datetime | None = None,
) -> dict:
    """物品交换合同：内容物市价 vs 合同标价 `price`。"""
    cost = float(contract.get("price") or 0)
    out = _base_metrics(contract, items, price_map, now)
    diff, pct = price_diff(out["market_value"], cost)
    out.update({"entry_cost": cost, "price_diff": diff, "diff_pct": pct})
    return out


def manufacturing_profit(bp_item: Item, recipe: Mapping[str, Any], price_map: PriceMap) -> float:
    """一份蓝图按 `runs` 次作业制造出来能赚多少（产物市价 − 材料成本）。

    - 材料量走 `calc_material_for_runs`（ME 单一定义处，含「单件材料豁免 ME」）
    - 任一**材料**缺价就返回 0：这样的成本是低估的，算出来的「利润」是假的
    - 产物缺价返回 0
    - BPO（`is_blueprint_copy` 为假）没有作业数上限，按 1 次作业估
    """
    runs = 1 if not bp_item.get("is_blueprint_copy") else max(1, int(bp_item.get("runs") or 1))
    me = int(bp_item.get("material_efficiency") or 0)

    product_unit = price_map.get(int(recipe.get("product_type_id") or 0))
    if not product_unit or product_unit <= 0:
        return 0.0
    revenue = float(product_unit) * int(recipe.get("output_qty") or 1) * runs

    cost = 0.0
    for mat_id, base_qty in recipe.get("materials") or ():
        mat_unit = price_map.get(int(mat_id))
        if not mat_unit or mat_unit <= 0:
            return 0.0
        cost += float(mat_unit) * calc_material_for_runs(int(base_qty), me_level=me, runs=runs)

    return revenue - cost


def blueprint_exchange_metrics(
    contract: Contract,
    items: Sequence[Item],
    price_map: PriceMap,
    recipes: Mapping[int, Mapping[str, Any]],
    blueprint_type_ids: Collection[int] = (),
    now: datetime | None = None,
) -> dict:
    """含蓝图的物品交换合同。

    合同价值 = **蓝图本身市价 + 制造利润**（其余非蓝图物品按普通市价计），
    再与合同标价 `price` 比。

    - `recipes`：`{蓝图 type_id: 配方}`，查不到的蓝图只算它自己的市价、不贡献制造利润
    - `blueprint_type_ids`：**蓝图身份**的判据（由 `services/item_kind` 给出）。
      不能只看「有没有配方」—— `blueprints.db` 里查不到配方时，那份合同会在界面上
      显示成「不含蓝图」，而它明明是蓝图合同。

    返回里 `blueprint_value` / `manufacturing_profit` 分开给，界面要能拆开看 ——
    「蓝图贵」和「造出来赚钱」是两回事，合并成一个数字没法判断贵在哪。
    """
    blueprint_ids = set(blueprint_type_ids)
    blueprint_value = 0.0
    blueprint_profit = 0.0
    other_value = 0.0
    blueprint_count = 0
    priced = 0
    missing = 0

    for it in items:
        type_id = int(it.get("type_id") or 0)
        quantity = int(it.get("quantity") or 0)
        unit = price_map.get(type_id)

        if unit is None or unit <= 0:
            missing += 1
            continue
        priced += 1

        recipe = recipes.get(type_id)
        if recipe is None and type_id not in blueprint_ids:
            other_value += float(unit) * quantity
            continue

        blueprint_count += 1
        blueprint_value += float(unit) * quantity
        if recipe is not None:
            blueprint_profit += manufacturing_profit(it, recipe, price_map) * quantity

    cost = float(contract.get("price") or 0)
    value = blueprint_value + blueprint_profit + other_value
    diff, pct = price_diff(value, cost)

    return {
        "market_value": value,
        "blueprint_value": blueprint_value,
        "manufacturing_profit": blueprint_profit,
        "other_value": other_value,
        "blueprint_count": blueprint_count,
        "priced_items": priced,
        "unpriced_items": missing,
        "total_quantity": total_quantity(items),
        "volume_m3": float(contract.get("volume") or 0),
        "remaining_seconds": remaining_seconds(contract.get("date_expired"), now),
        "entry_cost": cost,
        "price_diff": diff,
        "diff_pct": pct,
        "status": _value_status(items, priced, missing),
    }


def courier_metrics(
    contract: Contract,
    jumps: int | None,
    now: datetime | None = None,
) -> dict:
    """运输合同：报酬摊到「每跳」与「每方每跳」。

    `jumps` 为 None（起止点解析不出星系，或用户还没选口径）时两个指标都是 None ——
    界面显示「—」。**不拿 0 兜底**：0 ISK/跳 与「算不出来」是两码事，
    兜底会把一条好路线排在末尾，看起来像不值得跑。

    `isk_per_jump_m3` 是**真正的比较基准** —— 只比每跳 ISK 会偏向小体积合同，
    但同样的跳数拉 1000 方比拉 1 方费力得多。
    """
    reward = float(contract.get("reward") or 0)
    collateral = float(contract.get("collateral") or 0)
    volume = float(contract.get("volume") or 0)
    days = int(contract.get("days_to_complete") or 0)

    usable = jumps is not None and jumps > 0
    per_jump = reward / jumps if usable and jumps else None
    per_jump_m3 = reward / (jumps * volume) if usable and jumps and volume > 0 else None

    return {
        "reward": reward,
        "collateral": collateral,
        "volume_m3": volume,
        "days_to_complete": days,
        "jumps": jumps,
        "isk_per_jump": per_jump,
        "isk_per_jump_m3": per_jump_m3,
        # 抵押越高，一次失败亏得越多；报酬/抵押 是这条合同的风险回报比
        "reward_to_collateral": (reward / collateral) if collateral > 0 else None,
        "remaining_seconds": remaining_seconds(contract.get("date_expired"), now),
    }
