"""蓝图产物 → 结构改装件（rig）适用类别映射（纯函数，无 DB / Qt / 缓存）。

背景（审计 01-13 剩余缺口）：`services.hangar_industry_config` 已有 `RIG_GROUP_MAP`
（组号 → (尺寸, 制造类别 key, 效果)），但「某个制造蓝图该吃哪一类改件」此前没有映射——
只能按活动过滤，装备改件会加到舰船制造上。本模块把 SDE `item.category_id` /
`item.group_id` 映射到 `RIG_GROUP_MAP` 的 `category_key`。

数据依据（2026-10-17 只读核对）：
- `database/reference.db` 的 `item` 表：`category_id` + `group_id`（50,219 行全量；
  `category` 表在本地库的 `en_name/zh_name` 是空串，故用 `data/sde.zip → fsd/categories.yaml`
  取类别名：6=Ship / 7=Module / 8=Charge / 17=Commodity / 18=Drone / 20=Implant /
  22=Deployable / 23=Starbase / 32=Subsystem / 65=Structure / 66=Structure Module /
  87=Fighter）。
- 各 rig 组的适用对象取自 ESI `universe/types/{type_id}/` 的 `description` 原文
  （2026-10-17 21:09 +0800 抓取；例：Group 1824 M-Set Basic Small Ship "frigates,
  destroyers and shuttles"；1830 Advanced Small "Tech 2 frigates, Tech 2 and Tech 3
  destroyers"；1840 Structure "structure components, structure modules, structure rigs,
  Upwell structures, starbase structures and fuel blocks"；1867 XL Equipment and
  Consumable 覆盖 modules/rigs/deployables/implants/cargo containers；1868 XL Ship
  "any ship"；1869 XL Structure and Component 覆盖 components/structures/modules/
  starbase structures/fuel blocks）。
- 舰船/组件按 `group_id` 精确映射（group id 来自 `reference.db` 实测；`meta_group_id`
  列在本地库全为 NULL，无法用于 Tech I/II 划分，故不做猜测，未列出的组一律返回 None）。

**保守原则**：映射不到 → 返回 None（不加成），绝不猜。未覆盖清单见模块末尾注释。
"""

from __future__ import annotations

#: 舰船（category 6）group_id → rig 制造类别 key。
#: key 与 `services.hangar_industry_config.RIG_GROUP_MAP` 的 category_key 一一对应。
SHIP_RIG_CATEGORY_BY_GROUP: dict[int, str] = {
    # ── 基础小型（Frigates / Destroyers / Shuttles）──
    25: "basic_small_ship",  # Frigate
    420: "basic_small_ship",  # Destroyer
    31: "basic_small_ship",  # Shuttle
    237: "basic_small_ship",  # Corvette
    # ── 基础中型（Cruisers / Battlecruisers / Industrials / Mining Barges）──
    26: "basic_medium_ship",  # Cruiser
    419: "basic_medium_ship",  # Combat Battlecruiser
    1201: "basic_medium_ship",  # Attack Battlecruiser
    28: "basic_medium_ship",  # Hauler
    463: "basic_medium_ship",  # Mining Barge
    # ── 基础大型（Battleships / Freighters / Industrial Command Ships）──
    27: "basic_large_ship",  # Battleship
    513: "basic_large_ship",  # Freighter
    941: "basic_large_ship",  # Industrial Command Ship
    # ── 高级小型（Tech 2 frigates / Tech 2·3 destroyers）──
    324: "advanced_small_ship",  # Assault Frigate
    831: "advanced_small_ship",  # Interceptor
    830: "advanced_small_ship",  # Covert Ops
    834: "advanced_small_ship",  # Stealth Bomber
    893: "advanced_small_ship",  # Electronic Attack Ship
    1527: "advanced_small_ship",  # Logistics Frigate
    541: "advanced_small_ship",  # Interdictor
    1534: "advanced_small_ship",  # Command Destroyer
    1305: "advanced_small_ship",  # Tactical Destroyer
    # ── 高级中型（Tech 2 cruisers/BCs/haulers + Tech 3 cruisers/subsystems + exhumers）──
    358: "advanced_medium_ship",  # Heavy Assault Cruiser
    894: "advanced_medium_ship",  # Heavy Interdiction Cruiser
    906: "advanced_medium_ship",  # Combat Recon Ship
    833: "advanced_medium_ship",  # Force Recon Ship
    832: "advanced_medium_ship",  # Logistics
    540: "advanced_medium_ship",  # Command Ship
    963: "advanced_medium_ship",  # Strategic Cruiser
    543: "advanced_medium_ship",  # Exhumer
    380: "advanced_medium_ship",  # Deep Space Transport
    1202: "advanced_medium_ship",  # Blockade Runner
    # ── 高级大型（Tech 2 battleships / jump freighters）──
    898: "advanced_large_ship",  # Black Ops
    900: "advanced_large_ship",  # Marauder
    902: "advanced_large_ship",  # Jump Freighter
    # ── 旗舰（L-Set Capital Ship）──
    485: "capital_ship",  # Dreadnought
    4594: "capital_ship",  # Lancer Dreadnought
    547: "capital_ship",  # Carrier
    659: "capital_ship",  # Supercarrier
    1538: "capital_ship",  # Force Auxiliary
    30: "capital_ship",  # Titan
    883: "capital_ship",  # Capital Industrial Ship
}

#: 组件（category 17）group_id → rig 制造类别 key。
COMPONENT_RIG_CATEGORY_BY_GROUP: dict[int, str] = {
    873: "basic_capital_component",  # Capital Construction Components
    913: "advanced_component",  # Advanced Capital Construction Components
    536: "structure",  # Structure Components（M-Set Structure 描述明确含 structure components）
    332: "advanced_component",  # Tool
    716: "advanced_component",  # Data Interfaces
    964: "advanced_component",  # Hybrid Tech Components（Tech 3 components）
}

#: 非舰船/非组件：类别级默认 rig 制造类别 key。
RIG_CATEGORY_BY_CATEGORY_ID: dict[int, str] = {
    7: "equipment",  # Module（含 ship modules / ship rigs）
    8: "ammunition",  # Charge
    18: "drone_fighter",  # Drone
    20: "equipment",  # Implant（M-Set Equipment 描述含 implants）
    22: "equipment",  # Deployable（含 personal deployables）
    23: "structure",  # Starbase（M-Set Structure 描述含 starbase structures）
    32: "advanced_medium",  # Subsystem（Tech 3 subsystems → Advanced Medium Ship）
    65: "structure",  # Structure（Upwell structures）
    66: "structure",  # Structure Module（含 structure rigs 本体）
    87: "drone_fighter",  # Fighter
}

#: 需要按 group 细分的类别（优先于 `RIG_CATEGORY_BY_CATEGORY_ID` 的默认值）。
SPECIAL_GROUP_RIG_CATEGORY: dict[int, str] = {
    1136: "structure",  # Fuel Block（M-Set Structure 描述明确含 fuel blocks）
    12: "equipment",  # Cargo Container
    448: "equipment",  # Audit Log Secure Container
    340: "equipment",  # Secure Cargo Container
    649: "equipment",  # Freight Container
}

#: 宽口径 rig 类别 → 它能覆盖的细分产品类别（XL-Set 多为跨类合并，见 ESI description）。
BROAD_RIG_CATEGORIES: dict[str, frozenset[str]] = {
    # XL 1867 Equipment and Consumable：modules / ship rigs / deployables / implants / cargo containers
    "equipment_consumable": frozenset({"equipment", "ammunition"}),
    # XL 1868 Ship：any ship（所有已映射的舰船细分类）
    "ship": frozenset(SHIP_RIG_CATEGORY_BY_GROUP.values()),
    # XL 1869 Structure and Component：components / Upwell structures / structure modules / fuel blocks
    "structure_component": frozenset({"structure", "advanced_component", "basic_capital_component"}),
}


def rig_category_for_product(*, category_id: int | None, group_id: int | None) -> str | None:
    """SDE 产物（category_id, group_id）→ rig 制造类别 key；映射不到返回 None。

    None 的语义是「没有可对应的改件」——调用方应退回旧行为（不按类别筛），
    而不是把所有改件都算上。
    """
    try:
        cid = int(category_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        cid = 0
    try:
        gid = int(group_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        gid = 0
    if cid == 6:
        return SHIP_RIG_CATEGORY_BY_GROUP.get(gid)
    if cid == 17:
        return COMPONENT_RIG_CATEGORY_BY_GROUP.get(gid)
    if gid in SPECIAL_GROUP_RIG_CATEGORY:
        return SPECIAL_GROUP_RIG_CATEGORY[gid]
    return RIG_CATEGORY_BY_CATEGORY_ID.get(cid)


def rig_category_applies(rig_category: str | None, product_category: str | None) -> bool:
    """`rig_category` 是否作用于 `product_category` 的产品（含 XL 宽口径 rig）。

    两者都是 `RIG_GROUP_MAP` 的 category_key；`product_category` 是
    `rig_category_for_product` 的返回值。
    """
    if not rig_category or not product_category:
        return False
    if rig_category == product_category:
        return True
    return product_category in BROAD_RIG_CATEGORIES.get(rig_category, frozenset())


#: 未覆盖清单（2026-10-17 只读核对：`blueprint_products` 的全部产物类别里，
#: 本模块给不出映射的部分）：
#:   category 5  Clone（克隆体）
#:   category 25 Asteroid（小行星）
#:   category 39 Infrastructure Upgrades / 40 Sovereignty Structures / 46 Orbitals / 63 Special Edition
#:   category 2  的 Cynosural Fields / Construction Platform（集装箱已覆盖）
#:   category 4  的 Intermediate Materials / Biochemical Material / Composite / Hybrid Polymers /
#:               Molecular-Forged Materials / 矿物等（Fuel Block 已覆盖）
#:   category 6  的 Capsule / Citizen Ships / Prototype Exploration Ship / Expedition Frigate /
#:               Flag Cruiser（tech 口径不确定，保守不映射）
#:   category 17 的 Construction Components（T1 非旗舰组件；rig 描述未提及）
#: 这些类别在 `resolve_hangar_industry_config` 里退回旧行为（不按类别筛），不会静默丢加成。
UNCOVERED_PRODUCT_CATEGORY_IDS: tuple[int, ...] = (2, 4, 5, 25, 39, 40, 46, 63)
