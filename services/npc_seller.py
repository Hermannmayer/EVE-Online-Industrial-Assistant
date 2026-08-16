"""蓝图 NPC 卖家查询 — 从 ESI 卖单中筛出 NPC 公司的卖单。

纯函数（filter_npc_sell_orders）便于单测；DB 查询（NPC 公司/空间站）走 reference.db。
"""

from __future__ import annotations

from sqlite3 import Connection


def load_npc_corp_context() -> tuple[set[int], dict[int, str]]:
    """打开 reference.db 并返回 (npc_corp_ids, corp_names)。"""
    from core.container import get_container

    with get_container().db.connect("ref") as conn:
        return load_npc_corp_ids(conn), load_corp_names(conn)


def resolve_stations_by_ids(location_ids: set[int]) -> dict[int, tuple[str, str]]:
    """打开 reference.db 并解析空间站名称。"""
    from core.container import get_container

    with get_container().db.connect("ref") as conn:
        return resolve_stations(conn, location_ids)


def filter_npc_sell_orders(orders: list[dict], npc_corp_ids: set[int]) -> list[dict]:
    """从 ESI 市场卖单里筛出 NPC 公司的卖单。

    orders: ESI /markets/{region}/orders?order_type=sell 返回的卖单列表。
    判定：非买单 && 公司订单(is_corporation_order) && 公司属于 NPC 公司表。
    """
    return [
        o
        for o in orders
        if not o.get("is_buy_order") and o.get("is_corporation_order") and o.get("corporation_id") in npc_corp_ids
    ]


def load_npc_corp_ids(conn: Connection) -> set[int]:
    """reference.db 中全部 NPC 公司 id 集合。"""
    rows = conn.execute("SELECT corporation_id FROM npc_corporation").fetchall()
    return {r[0] for r in rows}


def load_corp_names(conn: Connection) -> dict[int, str]:
    """corp_id → 显示名（zh 优先 → en → str(id)）。"""
    rows = conn.execute("SELECT corporation_id, zh_name, en_name FROM npc_corporation").fetchall()
    return {r[0]: (r[1] or r[2] or str(r[0])) for r in rows}


def resolve_stations(conn: Connection, location_ids: set[int]) -> dict[int, tuple[str, str]]:
    """location_id → (空间站名, 星系名)。NPC 空间站的 location_id 即 station.station_id。"""
    location_ids = {lid for lid in location_ids if lid}
    if not location_ids:
        return {}
    placeholders = ",".join("?" * len(location_ids))
    rows = conn.execute(
        f"SELECT s.station_id, s.station_name, ss.solar_system_name "
        f"FROM station s LEFT JOIN solar_system ss ON ss.solar_system_id = s.solar_system_id "
        f"WHERE s.station_id IN ({placeholders})",
        tuple(location_ids),
    ).fetchall()
    return {r[0]: (r[1] or "", r[2] or "") for r in rows}
