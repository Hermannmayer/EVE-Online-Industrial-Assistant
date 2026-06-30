"""贸易页面 — 后台 Worker 线程"""

from PySide6.QtCore import QThread, Signal

from core.constants import TRADE_HUB_IDS
from services.scoring import calc_trade_score, get_price, get_volume


class CrossRegionPriceWorker(QThread):
    """获取物品在四大贸易中心的价格"""
    finished = Signal(list)

    def __init__(self, type_id: int, db, parent=None):
        super().__init__(parent)
        self._tid = type_id
        self._db = db

    def run(self):
        results = []
        for hub_name, region_id in TRADE_HUB_IDS.items():
            sell = get_price(self._tid, "sell", hub_name)
            buy = get_price(self._tid, "buy", hub_name)
            vol = get_volume(self._tid, "total", hub_name)
            spread = (sell - buy) if (sell and buy) else 0
            spread_pct = (spread / buy * 100) if (buy and buy > 0) else 0
            results.append({
                "hub": hub_name,
                "region_id": region_id,
                "buy_price": buy or 0,
                "sell_price": sell or 0,
                "spread": round(spread, 2),
                "spread_pct": round(spread_pct, 2),
                "volume": vol,
            })
        self.finished.emit(results)


class TradeScoreWorker(QThread):
    """单项贸易评分"""
    finished = Signal(dict)

    def __init__(
        self,
        type_id: int,
        buy_hub: str = "Jita",
        sell_hub: str = "Jita",
        buy_price_type: str = "buy",
        sell_price_type: str = "sell",
        quantity: int = 1,
        parent=None,
    ):
        super().__init__(parent)
        self._tid = type_id
        self._buy_hub = buy_hub
        self._sell_hub = sell_hub
        self._buy_price_type = buy_price_type
        self._sell_price_type = sell_price_type
        self._quantity = quantity

    def run(self):
        result = calc_trade_score(
            type_id=self._tid,
            buy_hub=self._buy_hub,
            sell_hub=self._sell_hub,
            buy_price_type=self._buy_price_type,
            sell_price_type=self._sell_price_type,
            quantity=self._quantity,
        )
        self.finished.emit(result)


class TransportWorker(QThread):
    """跨区域运输利润计算"""
    finished = Signal(dict)

    def __init__(
        self,
        type_id: int,
        buy_hub: str,
        sell_hub: str,
        buy_price_type: str,
        sell_price_type: str,
        quantity: int,
        distance_jumps: int,
        use_public_freight: bool = True,
        char_config: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._tid = type_id
        self._buy_hub = buy_hub
        self._sell_hub = sell_hub
        self._buy_price_type = buy_price_type
        self._sell_price_type = sell_price_type
        self._quantity = quantity
        self._distance_jumps = distance_jumps
        self._use_public_freight = use_public_freight
        self._char_config = char_config

    def run(self):
        from services.logistics import calc_transport_profit

        result = calc_transport_profit(
            type_id=self._tid,
            buy_hub=self._buy_hub,
            sell_hub=self._sell_hub,
            buy_price_type=self._buy_price_type,
            sell_price_type=self._sell_price_type,
            quantity=self._quantity,
            distance_jumps=self._distance_jumps,
            use_public_freight=self._use_public_freight,
            char_config=self._char_config,
        )
        self.finished.emit(result)
