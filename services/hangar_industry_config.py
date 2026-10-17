"""机库工业配置解析服务 — 设施类型/结构改装件 → 制造加成。

每个机库可配置所在设施类型（决定结构本体基础加成）+ 结构改装件列表
（材料/时间/成本效率钻机，加成数值来自 ESI 拉取的 structure_rigs 表）+ 设施税。
制造计划从材料机库读取这些配置，影响材料/时间/安装费成本。

叠加方式（EVE 机制，乘算）：有效倍率 = 结构本体基数 × Π(1 + 改件加成/100)。

2026-10-17 审计 01-13 补齐：`structure_rigs` 新增 `cost_bonus` 列（发明/ME/TE/拷贝
成本优化钻机，ESI attributeEngRigCostBonus=2595）；`resolve_hangar_industry_config`
的成本倍率现在乘上改件成本加成。制造类的「蓝图类别 → 改件类别」映射在
`domain.rigs`（纯函数），真实用户机库 `rigs` 为空 → 可观测零漂移。
"""

import json

from core.container import get_container
from core.logger import log
from domain.rigs import rig_category_applies, rig_category_for_product
from services.database_manager import DatabaseManager
from services.terminology import term


def _default_db() -> DatabaseManager:
    """惰性获取 DatabaseManager（经容器，消除模块级单例双轨）。"""
    return get_container().db


# 结构本体基数（材料/成本/时间倍率 + 可装改件尺寸）
# 来源：ESI 实测属性 strEngMatBonus=2600 / strEngCostBonus=2601 / strEngTimeBonus=2602
STRUCTURE_BASE: dict[str, dict] = {
    "npc": {"mat": 1.0, "cost": 1.0, "time": 1.0, "rig_size": None},
    "raitaru": {"mat": 0.99, "cost": 0.97, "time": 0.85, "rig_size": "M"},
    "azbel": {"mat": 0.99, "cost": 0.96, "time": 0.80, "rig_size": "L"},
    "sotiyo": {"mat": 0.99, "cost": 0.95, "time": 0.70, "rig_size": "XL"},
}

FACILITY_TYPE_LABELS: dict[str, str] = {
    "npc": "NPC 空间站",
    "raitaru": "莱塔卢 (Raitaru, 中)",
    "azbel": "阿兹贝尔 (Azbel, 大)",
    "sotiyo": "索迪约 (Sotiyo, 超大)",
}

# 结构改装件组 → (尺寸, 制造类别 key, 效果)。effect ∈ mat|time|both|cost。
# 制造类别 key 定义「每类最多 1 个」（ME/TE 同类别互斥）；组号来自 reference.db item 表实测。
RIG_GROUP_MAP: dict[int, tuple[str, str, str]] = {
    # ── M-Set（莱塔卢）──
    1816: ("M", "equipment", "mat"),
    1819: ("M", "equipment", "time"),
    1820: ("M", "ammunition", "mat"),
    1821: ("M", "ammunition", "time"),
    1822: ("M", "drone_fighter", "mat"),
    1823: ("M", "drone_fighter", "time"),
    1824: ("M", "basic_small_ship", "mat"),
    1825: ("M", "basic_small_ship", "time"),
    1826: ("M", "basic_medium_ship", "mat"),
    1827: ("M", "basic_medium_ship", "time"),
    1828: ("M", "basic_large_ship", "mat"),
    1829: ("M", "basic_large_ship", "time"),
    1830: ("M", "advanced_small_ship", "mat"),
    1831: ("M", "advanced_small_ship", "time"),
    1832: ("M", "advanced_medium_ship", "mat"),
    1833: ("M", "advanced_medium_ship", "time"),
    1834: ("M", "advanced_large_ship", "mat"),
    1835: ("M", "advanced_large_ship", "time"),
    1836: ("M", "advanced_component", "mat"),
    1837: ("M", "advanced_component", "time"),
    1838: ("M", "basic_capital_component", "time"),
    1839: ("M", "basic_capital_component", "mat"),
    1840: ("M", "structure", "mat"),
    1841: ("M", "structure", "time"),
    1842: ("M", "invention", "cost"),
    1843: ("M", "invention", "time"),
    1844: ("M", "me_research", "cost"),
    1845: ("M", "me_research", "time"),
    1846: ("M", "te_research", "cost"),
    1847: ("M", "te_research", "time"),
    1848: ("M", "bp_copy", "cost"),
    1849: ("M", "bp_copy", "time"),
    # ── L-Set（阿兹贝尔，Efficiency 改件同时减材料和时间）──
    1850: ("L", "equipment", "both"),
    1851: ("L", "ammunition", "both"),
    1852: ("L", "drone_fighter", "both"),
    1853: ("L", "basic_small_ship", "both"),
    1854: ("L", "basic_medium_ship", "both"),
    1855: ("L", "basic_large_ship", "both"),
    1856: ("L", "advanced_small_ship", "both"),
    1857: ("L", "advanced_medium_ship", "both"),
    1858: ("L", "advanced_large_ship", "both"),
    1859: ("L", "capital_ship", "both"),
    1860: ("L", "advanced_component", "both"),
    1861: ("L", "basic_capital_component", "both"),
    1862: ("L", "structure", "both"),
    1863: ("L", "invention", "both"),
    1864: ("L", "me_research", "both"),
    1865: ("L", "te_research", "both"),
    1866: ("L", "bp_copy", "both"),
    # ── XL-Set（索迪约，合并类别各自成组）──
    1867: ("XL", "equipment_consumable", "both"),
    1868: ("XL", "ship", "both"),
    1869: ("XL", "structure_component", "both"),
    1870: ("XL", "laboratory", "both"),
}

RIG_CATEGORY_LABELS: dict[str, str] = {
    "equipment": "装备制造",
    "ammunition": "弹药制造",
    "drone_fighter": "无人机/铁骑舰载机",
    "basic_small_ship": "基础小型舰船",
    "basic_medium_ship": "基础中型舰船",
    "basic_large_ship": "基础大型舰船",
    "advanced_small_ship": "高级小型舰船",
    "advanced_medium_ship": "高级中型舰船",
    "advanced_large_ship": "高级大型舰船",
    "advanced_component": "高级组件",
    "basic_capital_component": "基础旗舰组件",
    "structure": "建筑制造",
    "capital_ship": "旗舰",
    "equipment_consumable": "装备/消耗品(XL)",
    "ship": "舰船(XL)",
    "structure_component": "建筑/组件(XL)",
    "invention": "发明",
    "me_research": "材料效率研究",
    "te_research": "生产效率研究",
    "bp_copy": "蓝图复制",
    "laboratory": "实验室(科研, XL)",
}


def rig_category_label(cat: str) -> str:
    """改件类别标签：terminology.json（rig_categories）为权威来源，内置表兜底。"""
    return term.rig_category(cat) or RIG_CATEGORY_LABELS.get(cat, cat)


def parse_rigs(raw: str | None) -> list[int]:
    """json.loads 容错：None/非法 JSON/非列表 → []，元素 int 化。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    result: list[int] = []
    for item in data:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def get_rig_catalog(facility_type: str | None, *, _db: DatabaseManager | None = None) -> list[dict]:
    """返回该设施可装配的改件目录（含 ESI 加成），供机库设置 UI 使用。NPC/未选 → []。

    返回 list[dict]，按制造类别分组，含 type_id/名称/加成/效果。
    """
    base = STRUCTURE_BASE.get(facility_type or "npc")
    if not base or not base["rig_size"]:
        return []
    size = base["rig_size"]
    group_ids = [g for g, (s, _, _) in RIG_GROUP_MAP.items() if s == size]
    conn_mgr = _db or _default_db()
    placeholders = ",".join("?" * len(group_ids))
    try:
        with conn_mgr.connect("ref") as conn:
            rows = conn.execute(
                f"""SELECT i.type_id, i.zh_name, i.en_name, i.group_id,
                           COALESCE(r.mat_bonus, 0), COALESCE(r.time_bonus, 0)
                    FROM item i LEFT JOIN structure_rigs r ON r.type_id = i.type_id
                    WHERE i.group_id IN ({placeholders}) ORDER BY i.group_id, i.type_id""",
                group_ids,
            ).fetchall()
    except Exception:
        # structure_rigs 表未初始化 → 降级仅列 item（加成 0，UI 显示「加成未拉取」）
        log.warning("structure_rigs 表未就绪，改件加成显示为 0")
        with conn_mgr.connect("ref") as conn:
            rows = conn.execute(
                f"SELECT type_id, zh_name, en_name, group_id, 0, 0 FROM item"
                f" WHERE group_id IN ({placeholders}) ORDER BY group_id, type_id",
                group_ids,
            ).fetchall()
    catalog: list[dict] = []
    for type_id, zh, en, gid, mat, tm in rows:
        _size, cat, effect = RIG_GROUP_MAP.get(int(gid), ("", "", "mat"))
        catalog.append(
            {
                "type_id": int(type_id),
                "zh_name": zh or en or str(type_id),
                "en_name": en or "",
                "group_id": int(gid),
                "category_key": cat,
                "category_label": rig_category_label(cat),
                "effect": effect,
                "mat_bonus": float(mat or 0),
                "time_bonus": float(tm or 0),
            }
        )
    return catalog


def validate_rig_set(rig_ids: list[int], facility_type: str | None, *, _db: DatabaseManager | None = None) -> list[str]:
    """返回违规描述列表（空=合法）。规则：同制造类别互斥、尺寸匹配、未知 id。"""
    base = STRUCTURE_BASE.get(facility_type or "npc")
    if not base or not base["rig_size"]:
        return ["NPC 站/未选设施无法装配结构改装件"] if rig_ids else []
    if not rig_ids:
        return []
    catalog = get_rig_catalog(facility_type, _db=_db)
    by_id = {c["type_id"]: c for c in catalog}
    problems: list[str] = []
    seen: dict[str, int] = {}
    for rid in rig_ids:
        item = by_id.get(rid)
        if not item:
            problems.append(f"改件 {rid} 不属于该设施可装配目录")
            continue
        cat = item["category_key"]
        if cat in seen:
            problems.append(f"制造类别「{item['category_label']}」最多装配 1 个改件")
        else:
            seen[cat] = rid
    return problems


#: 科研活动 → 改件类别 key（`RIG_GROUP_MAP` 的 category_key）
_SCIENCE_RIG_CATEGORY: dict[str, str] = {
    "copying": "bp_copy",
    "invention": "invention",
    "researching_material_efficiency": "me_research",
    "researching_time_efficiency": "te_research",
}
#: 只作用于科研的改件类别（制造作业不应吃到它们的加成，反之亦然）
_SCIENCE_RIG_CATEGORIES = frozenset({"invention", "me_research", "te_research", "bp_copy", "laboratory"})


def _rig_matches_activity(
    rig_group: int,
    *,
    activity: str | None,
    blueprint_category: str | None,
) -> bool:
    """该改件是否作用于当前活动/蓝图类别。

    ``activity`` 为 None → 不筛（向后兼容旧调用方 / 机库设置页展示）。
    科研活动按活动精确匹配（发明 rig 不作用于 ME 研究）。
    制造活动：给了 ``blueprint_category`` 就按 `domain.rigs` 的映射匹配（含 XL 宽口径），
    不给（旧调用方/未覆盖类别）则只排除科研类改件 —— 旧行为不变。
    """
    if activity is None:
        return True
    _size, cat, _effect = RIG_GROUP_MAP.get(int(rig_group), ("", "", "mat"))
    if not cat:
        return False
    science_cat = _SCIENCE_RIG_CATEGORY.get(activity)
    if science_cat is not None:
        # XL-Set Laboratory Optimization（组 1870，类别 laboratory）按 ESI 描述同时覆盖
        # 发明/拷贝/ME/TE 研究（成本+时间），不是单一活动的专属类别。
        return cat == science_cat or cat == "laboratory"
    if cat in _SCIENCE_RIG_CATEGORIES:
        return False
    if blueprint_category is None:
        return True
    return rig_category_applies(cat, blueprint_category)


def _load_rig_bonuses(
    rig_ids: list[int],
    *,
    activity: str | None,
    _db: DatabaseManager | None,
) -> tuple[dict[int, tuple[float, float, float]], dict[int, int] | None] | None:
    """读改件加成（mat/time/cost）与 item.group 归属；表未就绪 → None。

    旧缓存库没有 `cost_bonus` 列（`getrigdata.init_db` 会在下次数据初始化时补列）：
    这里按 cost=0 处理，保证升级前成本倍率不被改变（零漂移）。
    """
    conn_mgr = _db or _default_db()
    try:
        with conn_mgr.connect("ref") as conn:
            placeholders = ",".join("?" * len(rig_ids))
            columns = {str(r[1]) for r in conn.execute("PRAGMA table_info(structure_rigs)")}
            cost_col = ", cost_bonus" if "cost_bonus" in columns else ""
            rows = conn.execute(
                f"SELECT type_id, mat_bonus, time_bonus{cost_col}"
                f" FROM structure_rigs WHERE type_id IN ({placeholders})",
                rig_ids,
            ).fetchall()
            groups: dict[int, int] | None = None
            if activity is not None and rows:
                # 需要 group_id 才能按活动/类别筛改件；结构表可能来自不含 item 表的测试库，
                # 查不到时退回「不筛活动」（与旧行为一致，不会丢加成）。
                try:
                    groups = {
                        int(r[0]): int(r[1])
                        for r in conn.execute(
                            f"SELECT type_id, group_id FROM item WHERE type_id IN ({placeholders})",
                            tuple(int(r[0]) for r in rows),
                        ).fetchall()
                    }
                except Exception:  # sqlite3.OperationalError：测试库缺 item 表
                    # 吞的是 sqlite3.OperationalError（测试库/旧库缺 item 表）：按无加成继续
                    log.debug("改件查询失败，按无 item 归属处理", exc_info=True)
                    groups = None
    except Exception:
        # structure_rigs 表未初始化（未运行改件数据拉取）→ 无加成
        log.warning("structure_rigs 表未就绪，改件加成按 0")
        return None
    bonus: dict[int, tuple[float, float, float]] = {}
    for r in rows:
        cost = float(r[3] or 0) if len(r) > 3 else 0.0
        bonus[int(r[0])] = (float(r[1] or 0), float(r[2] or 0), cost)
    return bonus, groups


def resolve_rig_multipliers(
    rig_ids: list[int],
    *,
    activity: str | None = None,
    blueprint_category: str | None = None,
    _db: DatabaseManager | None = None,
) -> tuple[float, float]:
    """(材料倍率, 时间倍率) 乘算叠加：Π(1 + bonus/100)。structure_rigs 缺行按加成 0。

    传入 ``activity`` 时只叠加**匹配该活动/蓝图类别**的改件（RIG_GROUP_MAP 的
    category_key）；不传则保持旧行为（全部改件都算，供机库设置页展示用）。
    成本类改件（effect="cost"）不在本函数的返回里 —— 见 `resolve_rig_cost_multiplier`
    （审计 01-13 补；本函数保持 2 元组不变，避免影响既有调用方与测试）。
    """
    mat_mult = 1.0
    time_mult = 1.0
    if not rig_ids:
        return mat_mult, time_mult
    loaded = _load_rig_bonuses(rig_ids, activity=activity, _db=_db)
    if loaded is None:
        return mat_mult, time_mult
    bonus, groups = loaded
    for rid in rig_ids:
        mb, tb, _cb = bonus.get(int(rid), (0.0, 0.0, 0.0))
        if groups is not None and not _rig_matches_activity(
            groups.get(int(rid), 0), activity=activity, blueprint_category=blueprint_category
        ):
            continue
        mat_mult *= 1.0 + mb / 100.0
        time_mult *= 1.0 + tb / 100.0
    return round(mat_mult, 6), round(time_mult, 6)


def resolve_rig_cost_multiplier(
    rig_ids: list[int],
    *,
    activity: str | None = None,
    blueprint_category: str | None = None,
    _db: DatabaseManager | None = None,
) -> float:
    """成本倍率 Π(1 + cost_bonus/100)；无数据 → 1.0（零漂移）。

    成本优化改件（ESI attributeEngRigCostBonus=2595）只作用于发明/ME/TE/拷贝，
    由 `RIG_GROUP_MAP` 的 category_key 与活动匹配；结构类改件该属性为 0，乘 1.0。
    旧缓存库没有 `cost_bonus` 列时同样返回 1.0，绝不改结构成本。
    """
    if not rig_ids:
        return 1.0
    loaded = _load_rig_bonuses(rig_ids, activity=activity, _db=_db)
    if loaded is None:
        return 1.0
    bonus, groups = loaded
    cost_mult = 1.0
    for rid in rig_ids:
        _mb, _tb, cb = bonus.get(int(rid), (0.0, 0.0, 0.0))
        if groups is not None and not _rig_matches_activity(
            groups.get(int(rid), 0), activity=activity, blueprint_category=blueprint_category
        ):
            continue
        cost_mult *= 1.0 + cb / 100.0
    return round(cost_mult, 6)


def _blueprint_rig_category(product_type_id: int | None, *, _db: DatabaseManager | None) -> str | None:
    """产物 type_id → rig 制造类别 key（查 reference.db item，纯映射在 `domain.rigs`）。

    查不到 / 未覆盖类别 → None（调用方退回旧行为：不按类别筛，不静默丢加成）。
    """
    if not product_type_id:
        return None
    conn_mgr = _db or _default_db()
    try:
        with conn_mgr.connect("ref") as conn:
            row = conn.execute(
                "SELECT category_id, group_id FROM item WHERE type_id = ?",
                (int(product_type_id),),
            ).fetchone()
    except Exception:
        # 吞的是 sqlite3.OperationalError：测试库/旧库缺 item 表 → 不做类别筛选（旧行为）
        log.debug("产物类别查询失败，跳过改件类别筛选", exc_info=True)
        return None
    if not row:
        return None
    return rig_category_for_product(category_id=row[0], group_id=row[1])


def resolve_hangar_industry_config(
    hangar_id: int | None,
    *,
    activity: str | None = None,
    blueprint_category: str | None = None,
    product_type_id: int | None = None,
    _db: DatabaseManager | None = None,
) -> dict:
    """解析机库工业配置 → {structure_mat_saving, structure_time_mod, structure_cost_mult,
    facility_tax, facility_type, rig_ids}。无机库/未配置 → 全默认（倍率 1.0、税 None）。

    ``activity``（如 manufacturing / invention / copying / researching_*）传入时，
    改件加成只叠加与该活动匹配的类别（避免「发明加速 rig」把制造时长也减了，审计 01-13）。
    ``product_type_id`` 传入且 ``blueprint_category`` 未给时，按 `domain.rigs` 的
    SDE 类别/组映射推导制造类别（舰船/模块/弹药/无人机/组件/建筑），供制造类改件细分；
    推导不到（未覆盖类别）→ 退回旧行为。真实用户机库 `rigs` 为空 → 可观测零漂移。
    """
    conn_mgr = _db or _default_db()
    facility_type: str | None = None
    facility_tax: float | None = None
    rig_ids: list[int] = []
    if hangar_id:
        with conn_mgr.connect("user") as conn:
            row = conn.execute(
                "SELECT facility_type, facility_tax, rigs FROM hangars WHERE id = ?",
                (hangar_id,),
            ).fetchone()
            if row:
                facility_type = row[0]
                facility_tax = row[1]
                rig_ids = parse_rigs(row[2])
    if blueprint_category is None and product_type_id and rig_ids:
        blueprint_category = _blueprint_rig_category(product_type_id, _db=_db)
    base = STRUCTURE_BASE.get(facility_type or "npc", STRUCTURE_BASE["npc"])
    mat_mult, time_mult = resolve_rig_multipliers(
        rig_ids, activity=activity, blueprint_category=blueprint_category, _db=_db
    )
    cost_mult = resolve_rig_cost_multiplier(rig_ids, activity=activity, blueprint_category=blueprint_category, _db=_db)
    return {
        "structure_mat_saving": round(base["mat"] * mat_mult, 6),
        "structure_time_mod": round(base["time"] * time_mult, 6),
        # 成本：结构本体基数 × 成本优化改件（旧库无 cost 列 → cost_mult=1.0，零漂移）
        "structure_cost_mult": round(base["cost"] * cost_mult, 6),
        "facility_tax": facility_tax,
        "facility_type": facility_type,
        "rig_ids": rig_ids,
    }
