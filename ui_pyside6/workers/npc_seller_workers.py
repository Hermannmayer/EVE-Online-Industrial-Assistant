"""蓝图 NPC 卖家查询的后台 Worker。

原先定义在 `ui_pyside6/dialogs/npc_seller_dialog.py` 里（对话框与线程同文件）。
对话框迁到 QML 后那个模块被删除，线程按项目约定挪到 `ui_pyside6/workers/`。
"""

from __future__ import annotations

import asyncio
from typing import Any

from PySide6.QtCore import QThread, Signal

from core.logger import log
from services.npc_seller import (
    filter_npc_sell_orders,
    load_npc_corp_context,
    resolve_stations_by_ids,
)

__all__ = ["NpcOrderWorker", "npc_seller_rows"]

ESI_BASE_URL = "https://esi.evetech.net/latest"


def npc_seller_rows(
    orders: list[dict],
    npc_ids: set[int],
    corp_names: dict[int, str],
    stations: dict[int, tuple[str, str]],
) -> list[dict]:
    """ESI 卖单 → 表格行（按价格升序）。纯函数，便于单测。

    只保留 NPC 公司的直售单；地点解析不出名字时退回 location_id 原文。

    `corporation_id` 与 `location_id` 在 ESI 回包里是可缺字段，逐个转 int 后再进字典，
    免得把 `None` 当成键传下去（原实现直接透传，mypy 在这里是过不了的）。
    """
    rows: list[dict] = []
    for order in sorted(filter_npc_sell_orders(orders, npc_ids), key=lambda o: o.get("price", 0)):
        corp_id = int(order.get("corporation_id") or 0)
        raw_location = order.get("location_id")
        location_id = int(raw_location) if raw_location else 0
        station, system = stations.get(location_id, ("", ""))
        location = f"{station}（{system}）" if station else str(raw_location or "未知")
        rows.append(
            {
                "corp": corp_names.get(corp_id, str(corp_id)),
                "location": location,
                "price": float(order.get("price") or 0),
                "volume": int(order.get("volume_remain") or 0),
            }
        )
    return rows


class NpcOrderWorker(QThread):
    """后台拉取指定蓝图的 ESI 卖单并按 NPC 公司过滤。"""

    result = Signal(list, str)  # rows: [dict], error

    def __init__(self, region_id: int, blueprint_type_id: int, parent: Any = None) -> None:
        super().__init__(parent)
        self._region_id = region_id
        self._type_id = blueprint_type_id

    def run(self) -> None:
        try:

            async def _fetch() -> list:
                from services.client import APIClient

                async with APIClient(timeout=20) as client:
                    url = f"{ESI_BASE_URL}/markets/{self._region_id}/orders/?order_type=sell&type_id={self._type_id}"
                    return await client.fetch_raw(url) or []

            orders = asyncio.run(_fetch())

            npc_ids, corp_names = load_npc_corp_context()
            # 先筛再解析空间站：只有 NPC 直售单才需要地点，原实现就是按筛后的集合查的
            sellers = filter_npc_sell_orders(orders, npc_ids)
            stations = resolve_stations_by_ids({int(o["location_id"]) for o in sellers if o.get("location_id")})
            self.result.emit(npc_seller_rows(sellers, npc_ids, corp_names, stations), "")
        except Exception as ex:
            log.exception("拉取蓝图NPC卖家失败 type_id=%s", self._type_id)
            self.result.emit([], f"拉取失败：{ex}")
