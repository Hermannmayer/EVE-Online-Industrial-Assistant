"""机库工业配置解析服务 — 设施类型/结构改装件 → 制造加成。

每个机库可配置所在设施类型（决定结构本体基础加成）+ 结构改装件列表
（材料/时间效率钻机，加成数值来自 ESI 拉取的 structure_rigs 表）+ 设施税。
制造计划从材料机库读取这些配置，影响材料/时间/安装费成本。

叠加方式（EVE 机制，乘算）：有效倍率 = 结构本体基数 × Π(1 + 改件加成/100)。
"""

import json

from core.logger import log
from services.database_manager import DatabaseManager, get_db

db = get_db()

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
    "me_research": "ME 研究",
    "te_research": "TE 研究",
    "bp_copy": "蓝图复制",
    "laboratory": "实验室(科研, XL)",
}


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
    conn_mgr = _db or db
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
                "category_label": RIG_CATEGORY_LABELS.get(cat, cat),
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


def resolve_rig_multipliers(
    rig_ids: list[int],
    *,
    _db: DatabaseManager | None = None,
) -> tuple[float, float]:
    """(材料倍率, 时间倍率) 乘算叠加：Π(1 + bonus/100)。structure_rigs 缺行按加成 0。"""
    mat_mult = 1.0
    time_mult = 1.0
    if not rig_ids:
        return mat_mult, time_mult
    conn_mgr = _db or db
    try:
        with conn_mgr.connect("ref") as conn:
            placeholders = ",".join("?" * len(rig_ids))
            rows = conn.execute(
                f"SELECT type_id, mat_bonus, time_bonus FROM structure_rigs WHERE type_id IN ({placeholders})",
                rig_ids,
            ).fetchall()
    except Exception:
        # structure_rigs 表未初始化（未运行改件数据拉取）→ 无加成
        log.warning("structure_rigs 表未就绪，改件加成按 0")
        return mat_mult, time_mult
    bonus = {int(r[0]): (float(r[1] or 0), float(r[2] or 0)) for r in rows}
    for rid in rig_ids:
        mb, tb = bonus.get(int(rid), (0.0, 0.0))
        mat_mult *= 1.0 + mb / 100.0
        time_mult *= 1.0 + tb / 100.0
    return round(mat_mult, 6), round(time_mult, 6)


def resolve_hangar_industry_config(
    hangar_id: int | None,
    *,
    _db: DatabaseManager | None = None,
) -> dict:
    """解析机库工业配置 → {structure_mat_saving, structure_time_mod, structure_cost_mult,
    facility_tax, facility_type, rig_ids}。无机库/未配置 → 全默认（倍率 1.0、税 None）。"""
    conn_mgr = _db or db
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
    base = STRUCTURE_BASE.get(facility_type or "npc", STRUCTURE_BASE["npc"])
    mat_mult, time_mult = resolve_rig_multipliers(rig_ids, _db=_db)
    return {
        "structure_mat_saving": round(base["mat"] * mat_mult, 6),
        "structure_time_mod": round(base["time"] * time_mult, 6),
        "structure_cost_mult": base["cost"],
        "facility_tax": facility_tax,
        "facility_type": facility_type,
        "rig_ids": rig_ids,
    }
