"""蓝图 NPC 卖家查询测试 — services/npc_seller.py"""

from services.npc_seller import (
    filter_npc_sell_orders,
    load_corp_names,
    load_npc_corp_ids,
    resolve_stations,
)


class TestFilterNpcSellOrders:
    def test_filters_npc_corp_sell_orders(self):
        orders = [
            {"is_buy_order": False, "is_corporation_order": True, "corporation_id": 1000001, "price": 10},
            {"is_buy_order": False, "is_corporation_order": True, "corporation_id": 99999999, "price": 20},
            {"is_buy_order": False, "is_corporation_order": False, "corporation_id": 1000001, "price": 30},
            {"is_buy_order": True, "is_corporation_order": True, "corporation_id": 1000001, "price": 40},
        ]
        result = filter_npc_sell_orders(orders, {1000001})
        assert len(result) == 1
        assert result[0]["price"] == 10

    def test_no_npc_orders(self):
        assert filter_npc_sell_orders([], {1000001}) == []


def _build_ref(db_manager):
    with db_manager.connect("ref") as conn:
        conn.execute(
            "CREATE TABLE npc_corporation (corporation_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT)"
        )
        conn.execute("INSERT INTO npc_corporation VALUES (1000001, 'NPC一', 'Npc One')")
        conn.execute(
            "CREATE TABLE station (station_id INTEGER PRIMARY KEY, station_name TEXT, "
            "solar_system_id INTEGER, corporation_id INTEGER)"
        )
        conn.execute("INSERT INTO station VALUES (60003760, 'Jita IV - Moon 4', 30000142, 1000001)")
        conn.execute(
            "CREATE TABLE solar_system (solar_system_id INTEGER PRIMARY KEY, solar_system_name TEXT)"
        )
        conn.execute("INSERT INTO solar_system VALUES (30000142, 'Jita')")
    return db_manager


class TestNpcDbQueries:
    def test_load_npc_corp_ids(self, db_manager):
        _build_ref(db_manager)
        with db_manager.connect("ref") as conn:
            assert load_npc_corp_ids(conn) == {1000001}

    def test_load_corp_names(self, db_manager):
        _build_ref(db_manager)
        with db_manager.connect("ref") as conn:
            assert load_corp_names(conn) == {1000001: "NPC一"}

    def test_resolve_stations(self, db_manager):
        _build_ref(db_manager)
        with db_manager.connect("ref") as conn:
            assert resolve_stations(conn, {60003760}) == {60003760: ("Jita IV - Moon 4", "Jita")}
            assert resolve_stations(conn, set()) == {}

    def test_resolve_unknown_station(self, db_manager):
        _build_ref(db_manager)
        with db_manager.connect("ref") as conn:
            assert resolve_stations(conn, {123456}) == {}
