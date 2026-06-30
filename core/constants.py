"""
全局常量 — 贸易中心 ID 等
"""

# 四大贸易中心 region_id
TRADE_HUB_IDS = {
    "Jita": 10000002,
    "Amarr": 10000043,
    "Dodixie": 10000032,
    "Rens": 10000030,
}
HUB_NAMES = {v: k for k, v in TRADE_HUB_IDS.items()}
TRADE_HUBS = list(TRADE_HUB_IDS.keys())  # ["Jita", "Amarr", "Dodixie", "Rens"]
