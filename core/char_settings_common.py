"""人物设置共享常量与公式。"""

from __future__ import annotations

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


def calc_broker_fee(skills: dict, faction_standing: float, corp_standing: float, base_rate: float = 1.0) -> float:
    """计算经纪人费率 (%)。委托 core.eve_formulas.calc_broker_rate。"""
    from core.eve_formulas import calc_broker_rate

    market_data = {"faction_standing": faction_standing, "corp_standing": corp_standing}
    if base_rate != 1.0:
        rate = calc_broker_rate(skills, market_data)
        return max(0.1, rate * base_rate)  # type: ignore[no-any-return]
    return calc_broker_rate(skills, market_data)  # type: ignore[no-any-return]


def calc_relist_discount(skills: dict) -> float:
    """计算改单折扣 (%)。委托 core.eve_formulas。"""
    from core.eve_formulas import calc_relist_discount as _calc_relist_discount

    return _calc_relist_discount(skills)  # type: ignore[no-any-return]


def calc_sales_tax(skills: dict, base_tax: float = 2.0) -> float:
    """计算销售税率 (%)。委托 core.eve_formulas。"""
    from core.eve_formulas import calc_sales_tax_rate

    rate = calc_sales_tax_rate(skills)
    if base_tax != 2.0:
        return rate * (base_tax / 2.0)  # type: ignore[no-any-return]
    return rate  # type: ignore[no-any-return]


def calc_max_orders(skills: dict, base_orders: int = 15) -> int:
    """计算最大订单数。"""
    trade = skills.get("贸易学", 0)
    retail = skills.get("零售技巧", 0)
    wholesale = skills.get("批发技巧", 0)
    tycoon = skills.get("商业巨头", 0)
    return base_orders + 4 * trade + 8 * retail + 16 * wholesale + 32 * tycoon  # type: ignore[no-any-return]


def format_pct(value: float) -> str:
    return f"{value:.2f}%"
