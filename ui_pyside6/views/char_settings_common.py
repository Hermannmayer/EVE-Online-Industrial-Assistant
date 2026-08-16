"""人物设置共享常量与公式。"""

from __future__ import annotations

SKILL_CATEGORIES = [
    (
        "⚙️ 制造",
        [
            "工业理论",
            "高级工业理论",
            "量产技术",
            "高级量产技术",
            "批量生产学",
            "Advanced Industry",
            "Mass Production",
            "Advanced Mass Production",
            "Supply Chain Management",
        ],
    ),
    (
        "🧬 科学",
        [
            "科学原理",
            "研究概论",
            "冶金学",
            "实验室运作理论",
            "高级实验室运作理论",
        ],
    ),
    (
        "🛡️ 船体",
        [
            "小型舰船制造研究",
            "中型舰船制造研究",
            "大型舰船制造研究",
            "工业舰船制造研究",
            "旗舰级船只建造研究",
            "高级旗舰建造",
        ],
    ),
    (
        "🧪 科技",
        [
            "电子技术",
            "机械工程",
            "量子物理",
            "核物理",
            "电磁物理",
            "火箭科学",
            "引力子物理",
            "等离子物理",
            "高频激发物理学",
            "生化反应学",
            "空间定锚",
            "哨站建造研究",
            "血袭者改造技术研究",
            "天蛇改造技术研究",
            "天使改造技术研究",
            "古斯塔斯改造技术研究",
            "昇威星舰工程学",
            "突变稳定",
        ],
    ),
    ("📖 蓝图研究加速", ["研究概论", "冶金学"]),
    ("🌀 深渊", ["三神裔量子工程学", "三神裔加密技术原理", "昇威加密技术原理"]),
    ("🔬 研究线", ["高级实验室运作理论", "实验室运作理论", "科学网络学"]),
    ("🚢 其他技能", ["气云采集理论", "无人机概论"]),
    ("🌍 行星基础", ["行星统筹管理学", "指挥中心升级理论", "海关操作专业理论"]),
    (
        "🏭 T2 制造",
        [
            "高级小型舰船建造研究",
            "高级工业舰船建造研究",
            "高级中型舰船建造研究",
            "高级大型舰船建造研究",
        ],
    ),
    ("⚗️ 反应", ["反应理论"]),
    ("🧪 反应线", ["大规模反应理论", "高级大规模反应理论"]),
    (
        "🔧 改装件",
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
    ("🏭 工业基础", ["工业理论", "高级工业理论"]),
    ("🏗️ 建筑制造", ["空间定锚", "哨站建造研究"]),
    ("🚢 旗舰制造", ["旗舰级船只建造研究", "高级旗舰建造"]),
    ("📦 生产线", ["高级量产技术", "批量生产学"]),
]

ALL_SKILLS = []
for _cat_name, skills in SKILL_CATEGORIES:
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
