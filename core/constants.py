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
    #: 30002070 是 **Uriok**（SCI 0.0014），不是 Hek —— 写错会让「Hek 的 SCI」取到别的
    #: 星系（实测差 ~50 倍）。真值经 `reference.db.solar_system` 核对：Hek = 30002053。
    "Hek": 30002053,
}

# ── 生产计划状态（单一真源）──
# 状态机：pending ──启动──▶ in_progress ──倒计时到期──▶ ready ──完成──▶ completed
# 历史别名（0 写点，保留兼容旧库/旧脚本）：running ≡ in_progress、done ≡ completed。
# 各处**不要**再手写状态元组：口径分裂会让「材料占用 / 重排保护 / 批量重算冻结」各算各的。
PLAN_STATUS_PENDING = "pending"
#: 已启动、仍在生产
PLAN_RUNNING_STATUSES: tuple[str, ...] = ("in_progress", "running")
#: 已造完、待下线
PLAN_AWAITING_STATUSES: tuple[str, ...] = ("ready",)
#: 已结束（下发/复用前）
PLAN_TERMINAL_STATUSES: tuple[str, ...] = ("completed", "done")
#: 活跃 = 待生产 + 在产 + 待下线（这些行参与材料/蓝图需求与批量重算）
PLAN_ACTIVE_STATUSES: tuple[str, ...] = (PLAN_STATUS_PENDING, *PLAN_RUNNING_STATUSES, *PLAN_AWAITING_STATUSES)
#: 已锁料 = 材料已物理扣减 + 蓝图仍被占用（在产 / 待下线）
PLAN_LOCKED_STATUSES: tuple[str, ...] = (*PLAN_RUNNING_STATUSES, *PLAN_AWAITING_STATUSES)
#: 未结束 = 待生产 + 在产（子项「未完成」的判定口径）
PLAN_UNFINISHED_STATUSES: tuple[str, ...] = (PLAN_STATUS_PENDING, *PLAN_RUNNING_STATUSES)

# 系统成本指数(SCI)兜底值：星系未知或库中无该星系数据时使用（≈吉他制造 SCI 水平）。
# 统一未知与查无两个分支，避免一个给 0.05、一个给 1.0 的语义分裂。
DEFAULT_SYSTEM_COST_INDEX = 0.05

# ── 订单簿深度取价（判据与理由见 domain/market_depth.py 模块 docstring）──
PRICE_DEPTH_VOLUME_PCT = 0.01
# 阈值下限：挂单量太小时不受比例约束（总量 100 的 1% 只有 1 个单位，剔除不动）
PRICE_DEPTH_MIN_UNITS = 5
# 盘口总量低于此值时不剔除薄单（整个市场都很薄时，薄单就是真实价）
PRICE_DEPTH_MIN_BOOK = 50

# ── 卖单价可信度（domain/market_depth.sell_price_reliable）──
# 仓库/资产估值一律取「最低卖单价」。实测病灶：极薄的单边品种，一笔离谱卖单就是全市场最低卖价。
#   type 23165 隔热剂 Jita：卖侧 1 笔 @68,000,000×4 件，买侧 7 笔共 2,034,545 件 @1~12 ISK
#   type 21594 预燃室 Jita：卖侧 1 笔 @64,000,000×4 件，买侧 5 笔共 5,408,323 件 @9~12 ISK
# 库里 3 件库存按卖单价估值 135.42 亿 ISK，按买盘实际只值 8,504 ISK（价差 5,700~7,500 倍）。
# 判据只认「卖侧盘口在绝对量级上根本立不住价」，不看价格倍数 —— 价格倍数会把薄单当真实价。
PRICE_CREDIBLE_MIN_SELL_VOLUME = 100
PRICE_CREDIBLE_SELL_BUY_VOLUME_RATIO = 0.01
