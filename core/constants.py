"""
全局常量 — 贸易中心 ID 等
"""

# 四大贸易中心 region_id
TRADE_HUB_IDS = {
    "Jita": 10000002,
    "Amarr": 10000043,
    "Dodixie": 10000032,
    "Rens": 10000030,
    "Hek": 10000028,
}
HUB_NAMES = {v: k for k, v in TRADE_HUB_IDS.items()}
TRADE_HUBS = list(TRADE_HUB_IDS.keys())  # ["Jita", "Amarr", "Dodixie", "Rens"]

# 贸易中心 → 太阳系 ID（SCI 查询用；避免多处重复定义）
TRADE_HUB_SYSTEM_IDS: dict[str, int] = {
    "Jita": 30000142,
    "Amarr": 30002187,
    "Dodixie": 30002659,
    "Rens": 30002510,
    "Hek": 30002070,
}

# 系统成本指数(SCI)兜底值：星系未知或库中无该星系数据时使用（≈吉他制造 SCI 水平）。
# 统一未知与查无两个分支，避免一个给 0.05、一个给 1.0 的语义分裂。
DEFAULT_SYSTEM_COST_INDEX = 0.05

# ── 订单簿深度取价（domain/market_depth.py）──
# 直接取 min(卖价)/max(买价) 会被「只有一两个单位」的凑数挂单带偏
# （实例：大型EMP立体炸弹 I 的卖单里有一笔 2 个 @543,800，真实深度在 995,900）。
# 改为按挂单量累计取价，阈值占该物品该侧总挂单量的比例。
PRICE_DEPTH_VOLUME_PCT = 0.01
# 阈值下限：挂单量太小时不受比例约束（总量 100 的 1% 只有 1 个单位，剔除不动）
PRICE_DEPTH_MIN_UNITS = 5
# 盘口总量低于此值时不剔除薄单（整个市场都很薄时，薄单就是真实价）
PRICE_DEPTH_MIN_BOOK = 50
