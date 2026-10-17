"""人物设置共享常量与公式。"""

from __future__ import annotations

from core.skill_keys import RETAIL, TRADE, TYCOON, WHOLESALE

SKILL_CATEGORIES = [
    (
        "制造",
        "settings",
        [
            "工业理论",
            "高级工业理论",
            "高级量产技术",
            "批量生产学",
            "供给链管理",
        ],
    ),
    # 精炼产率 = 基础 ×(1+3%×提炼学概论) ×(1+2%×提炼效率理论) ×(1+2%×矿石专精)
    # （见 `core/eve_formulas.calc_refining_yield`）。查询页「精炼产物」面板按人物
    # 读这里填的等级算产率，所以必须能在人物设置里填。
    #
    # 矿石专精是**按矿种**的技能，所以下面列了 SDE 里能解析出来的全部 25 个 —— 与
    # `services/refining_service.ore_skill_info` 的解析能力一一对应。只填你实际会精炼的
    # 那几种即可，没填的按 0 级算（面板上会写明用的是哪个技能）。
    #
    # ⚠️ 2024 年后的新矿种（杜希石/艾弗石/萤石…）**没有对应技能可填**：SDE 里既没有同名
    # 技能，本地也查不到官方关联（EVE 用 dogma 属性 `reprocessingSkillType` 连，而本仓
    # 那份数据是空壳）。这类矿种在面板上会明说「该矿种未映射到处理技术」。
    (
        "精炼",
        "recycle",
        [
            "提炼学概论",
            "提炼效率理论",
            "冰矿处理技术",
            "凡晶石处理技术",
            "灼烧岩处理技术",
            "干焦岩处理技术",
            "斜长岩处理技术",
            "奥贝尔石处理技术",
            "水硼砂处理技术",
            "杰斯贝矿处理技术",
            "希莫非特处理技术",
            "同位原矿处理技术",
            "片麻岩处理技术",
            "黑赭石处理技术",
            "克洛基处理技术",
            "双多特处理技术",
            "艾克诺处理技术",
            "灰岩处理技术",
            "基腹断岩处理技术",
            "贝兹岩处理技术",
            "拉克岩处理技术",
            "塔拉岩处理技术",
            "常见卫星矿石处理技术",
            "普通卫星矿石处理技术",
            "罕见卫星矿石处理技术",
            "稀有卫星矿石处理技术",
            "非凡卫星矿石处理技术",
        ],
    ),
    (
        "科学",
        "dna",
        [
            "科学原理",
            "研究概论",
            "冶金学",
            "实验室运作理论",
            "高级实验室运作理论",
        ],
    ),
    (
        "船体",
        "shield",
        [
            "高级小型舰船建造研究",
            "高级中型舰船建造研究",
            "高级大型舰船建造研究",
            "高级工业舰船建造研究",
            "旗舰级船只建造研究",
            "高级旗舰建造",
        ],
    ),
    (
        "科技",
        "test-tube",
        [
            "电子工程学",
            "机械工程学",
            "量子物理学",
            "核芯物理学",
            "电磁物理学",
            "火箭科学",
            "引力子物理学",
            "等离子物理学",
            "高能物理学",
            "空间定锚",
            "哨站建造研究",
            "昇威星舰工程学",
            "突变稳定",
        ],
    ),
    ("蓝图研究加速", "book", ["研究概论", "冶金学"]),
    ("深渊", "spiral", ["三神裔量子工程学", "三神裔加密技术原理", "昇威加密技术原理"]),
    ("研究线", "microscope", ["高级实验室运作理论", "实验室运作理论", "科学网络学"]),
    ("其他技能", "sailboat", ["气云采集理论", "无人机概论"]),
    ("行星基础", "globe", ["行星统筹管理学", "指挥中心升级理论", "海关操作专业理论"]),
    (
        "T2 制造",
        "factory",
        [
            "高级小型舰船建造研究",
            "高级工业舰船建造研究",
            "高级中型舰船建造研究",
            "高级大型舰船建造研究",
        ],
    ),
    ("反应", "flask", ["反应理论"]),
    ("反应线", "test-tube", ["大规模反应理论", "高级大规模反应理论"]),
    (
        "改装件",
        "wrench",
        [
            "构件改装技术",
            "装甲改装技术",
            "空间航行改装技术",
            "无人机改装技术",
            "电子优势改装技术",
            "射弹武器改装技术",
            "能量武器改装技术",
            "混合武器改装技术",
            "发射器改装技术",
            "护盾改装技术",
        ],
    ),
    ("工业基础", "factory", ["工业理论", "高级工业理论"]),
    ("建筑制造", "buildings", ["空间定锚", "哨站建造研究"]),
    ("旗舰制造", "sailboat", ["旗舰级船只建造研究", "高级旗舰建造"]),
    ("生产线", "package", ["高级量产技术", "批量生产学"]),
    # ── 蓝图制造/发明实际要求、但原面板缺失的技能 ──
    # 来源：`database/reference.db item WHERE category_id=16` ∩
    #       `database/blueprint.db blueprint_skills.activity='manufacturing'`（2026-10-17 实测
    #       31 个不在原面板）。缺键会让 `domain/formulas.calc_production_time` 与发明成功率
    #       一律按 0 级算（角色满级也填不进去、ESI 也不会写入）。名字必须与 reference.db
    #       `item.zh_name` 逐字一致 —— ESI 技能导入按这个名字回填（见 esi_skill_worker）。
    (
        "蓝图技能",
        "flask",
        [
            "激光物理学",
            "磁流体物理学",
            "纳米工程学",
            "分子工程学",
            "盖伦特星舰工程学",
            "米玛塔尔星舰工程学",
            "艾玛星舰工程学",
            "加达里星舰工程学",
            "药品制备",
            "全能理论",
            "推进子系统技术",
            "核心子系统技术",
            "防御子系统技术",
            "攻击子系统技术",
            "殷郡技术研究",
            "冬眠者技术研究",
            "塔洛迦技术研究",
            "艾玛加密技术原理",
            "盖伦特加密技术原理",
            "加达里加密技术原理",
            "塔克玛技术研究",
            "母星管理",
            "米玛塔尔加密技术原理",
            "生产管理学",
            "电子子系统技术",
            "精炼厂管理",
            "首席科研官培训",
            "空间航行工程学",
            "超网络科学",
            "空间站管理学",
            "神经毒化控制理论",
        ],
    ),
    # 交易费率（经纪人费 / 销售税 / 改单折扣）的三个技能键：原先根本不在面板，
    # 导致 `core.eve_formulas` 的费率永远按 0 级（最差档）算，用户也没地方填。
    ("贸易", "coins", ["会计学", "经纪人关系学", "高级经纪人关系学"]),
]

ALL_SKILLS = []
for _cat_name, _icon_key, skills in SKILL_CATEGORIES:
    for s in skills:
        ALL_SKILLS.append(s)

TRADE_HUBS = [
    ("jita", "吉他 Jita", "加达里 Caldari", "加达里海军 Caldari Navy"),
    ("amarr", "艾玛 Amarr", "艾玛 Amarr", "皇族 Emperor Family"),
    ("dodixie", "多迪 Dodixie", "盖伦特 Gallente", "盖伦特统计局"),
    ("rens", "伦斯 Rens", "米玛塔尔 Minmatar", "米玛塔尔矿业"),
]


def calc_broker_fee(skills: dict, faction_standing: float, corp_standing: float, base_rate: float = 3.0) -> float:
    """计算 NPC 空间站经纪人费率 (%)。委托 core.eve_formulas.calc_broker_rate。

    ``base_rate`` 只在非常规缩放时使用（现行公式基准 3%；传入其它值时按比例缩放），
    常规调用不传即得官方口径。玩家 Upwell 结构市场由结构主定价、技能无效。
    """
    from core.eve_formulas import calc_broker_rate

    market_data = {"faction_standing": faction_standing, "corp_standing": corp_standing}
    rate = calc_broker_rate(skills, market_data)
    if base_rate != 3.0:
        return max(1.0, rate * base_rate / 3.0)  # type: ignore[no-any-return]
    return rate  # type: ignore[no-any-return]


def calc_relist_discount(skills: dict) -> float:
    """计算改单折扣 (%)。委托 core.eve_formulas。"""
    from core.eve_formulas import calc_relist_discount as _calc_relist_discount

    return _calc_relist_discount(skills)  # type: ignore[no-any-return]


def calc_sales_tax(skills: dict, base_tax: float = 7.5) -> float:
    """计算销售税率 (%)。委托 core.eve_formulas。``base_tax`` 非常规缩放用（基准 7.5%）。"""
    from core.eve_formulas import calc_sales_tax_rate

    rate = calc_sales_tax_rate(skills)
    if base_tax != 7.5:
        return rate * (base_tax / 7.5)  # type: ignore[no-any-return]
    return rate  # type: ignore[no-any-return]


def calc_max_orders(skills: dict, base_orders: int = 15) -> int:
    """计算最大订单数。"""
    trade = skills.get(TRADE, 0)
    retail = skills.get(RETAIL, 0)
    wholesale = skills.get(WHOLESALE, 0)
    tycoon = skills.get(TYCOON, 0)
    return base_orders + 4 * trade + 8 * retail + 16 * wholesale + 32 * tycoon  # type: ignore[no-any-return]


def format_pct(value: float) -> str:
    return f"{value:.2f}%"


def apply_skill_queue_finished(levels: dict[int, int], queue: list[dict], now: str) -> dict[int, int]:
    """把技能队列里已练完的条目叠加到 `/skills` 的结果上。

    CCP 文档原文：`/skills` 对角色**离线期间**练完的技能是过期的，必须用
    `/skillqueue` 里 `finish_date` 已过的条目修正，否则拿到的是旧等级。

    `now` 与 `finish_date` 都必须是 ESI 那种 `%Y-%m-%dT%H:%M:%SZ` 的 UTC 串
    —— 同格式 ISO8601 按字典序比较即等价于按时间比较。
    """
    merged = dict(levels)
    for entry in queue:
        finish = entry.get("finish_date")
        skill_id = entry.get("skill_id")
        if not finish or skill_id is None or finish > now:
            continue
        sid = int(skill_id)
        merged[sid] = max(merged.get(sid, 0), int(entry.get("finished_level") or 0))
    return merged


def merge_esi_skill_levels(existing: dict[str, int], esi: dict[str, int], panel_names: list[str]) -> dict[str, int]:
    """把 ESI 等级落到「面板能显示的名字 ∪ 配置里已有的名字」上。

    **面板全集都要写**（ESI 没给出的记 0）—— 否则用户只在自己手填过的那十几个
    技能上看到真实等级，造船/冶金/研究那一大片仍是 0，看起来像「没导入」。
    配置里用户自建的、不在面板里的技能名保留原值。

    ESI 返回的其它几百个技能**仍然不写**：配置只保留这个应用真正会用的集合。
    """
    merged: dict[str, int] = {}
    for name in dict.fromkeys([*panel_names, *existing]):
        merged[name] = int(esi[name]) if name in esi else int(existing.get(name, 0))
    return merged


def union_skill_levels(characters: dict, esi: dict[str, int], panel_names: list[str]) -> dict[str, int]:
    """新导入角色的初始技能集 = 面板全集 ∪ 其它角色用过的技能名，等级取自 ESI。

    新角色没有自己的技能集可「刷新」，所以铺面板全集做骨架（缺的记 0），
    等级用 ESI 的真实值填；同样不写 ESI 的几百个无关技能。
    """
    custom: list[str] = []
    for data in characters.values():
        custom.extend(data.get("skills") or {})
    return {name: int(esi.get(name, 0)) for name in dict.fromkeys([*panel_names, *custom])}
