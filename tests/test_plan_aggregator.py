"""备料采购聚合测试 — services/plan_aggregator.aggregate_procurement（需求2）"""

import pytest

from services.plan_aggregator import aggregate_procurement


def _inventory(db_manager, hangar_id, type_id, qty):
    with db_manager.connect("user") as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS inventory_items (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "hangar_id INTEGER, type_id INTEGER, quantity INTEGER, cost_price REAL)"
        )
        conn.execute(
            "INSERT INTO inventory_items (hangar_id, type_id, quantity, cost_price) VALUES (?,?,?,0)",
            (hangar_id, type_id, qty),
        )


class TestAggregateProcurement:
    def test_basic_cost_and_volume(self, temp_db):
        """渡鸦级 1 流程：1000 三钛 + 500 类银；sell 价 5/9；无库存。"""
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            rows, cost, vol = aggregate_procurement(conn, [plan], price_type="sell")
        by_type = {r["type_id"]: r for r in rows}
        assert by_type[1001]["to_buy"] == 1000
        assert by_type[1002]["to_buy"] == 500
        assert by_type[1001]["price"] == 5
        assert cost == pytest.approx(1000 * 5 + 500 * 9)
        assert vol == pytest.approx(1000 * 0.01 + 500 * 0.01)

    def test_deduct_per_plan_hangar(self, temp_db):
        """按各计划 mat_hangar_id 扣库存：机库 5 有 400 三钛 → to_buy=600。"""
        _inventory(temp_db, 5, 1001, 400)
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0, "mat_hangar_id": 5}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            rows, cost, _ = aggregate_procurement(conn, [plan], price_type="sell")
        by_type = {r["type_id"]: r for r in rows}
        assert by_type[1001]["owned"] == 400
        assert by_type[1001]["to_buy"] == 600
        assert cost == pytest.approx(600 * 5 + 500 * 9)

    def test_ignores_inventory_in_other_hangar(self, temp_db):
        """机库 6 的三钛不抵扣机库 5 计划的采购需求。"""
        _inventory(temp_db, 6, 1001, 999)
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0, "mat_hangar_id": 5}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            _rows, cost, _ = aggregate_procurement(conn, [plan], price_type="sell")
        assert cost == pytest.approx(1000 * 5 + 500 * 9)  # 其他机库库存不影响

    def test_single_hangar_mode(self, temp_db):
        """hangar_id 非 None（采购弹窗模式）：统一扣该机库，忽略计划 mat_hangar_id。"""
        _inventory(temp_db, 5, 1001, 100)
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0, "mat_hangar_id": 7}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            _rows, cost, _ = aggregate_procurement(conn, [plan], hangar_id=5, price_type="sell")
        assert cost == pytest.approx(900 * 5 + 500 * 9)  # 扣机库 5 的 100 三钛

    def test_default_hangar_fallback(self, temp_db):
        """计划无 mat_hangar_id → 用 default_hangar_id 兜底扣库存。"""
        _inventory(temp_db, 5, 1001, 300)
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0}  # 无 mat_hangar_id
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            _rows, cost, _ = aggregate_procurement(conn, [plan], default_hangar_id=5, price_type="sell")
        assert cost == pytest.approx(700 * 5 + 500 * 9)

    def test_buy_price_type(self, temp_db):
        """price_type='buy' 用买价 4/8。"""
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            _rows, cost, _ = aggregate_procurement(conn, [plan], price_type="buy")
        assert cost == pytest.approx(1000 * 4 + 500 * 8)

    def test_empty_plans(self, temp_db):
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            rows, cost, vol = aggregate_procurement(conn, [], price_type="sell")
        assert rows == [] and cost == 0.0 and vol == 0.0

    def test_excludes_subitem_products_from_procurement(self, temp_db):
        """母项拆解后：有子线的组件排除（自制），未拆解的直接材料计入，子线原材料计入。"""
        # 让母项 2001 的直接配方含子项 2002（自制）+ 三钛/类银（外购）
        with temp_db.connect("bp") as conn:
            conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',2002,2,10)")
        mother = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0, "group_id": 10, "child_level": 0}
        subitem = {"product_type_id": 2002, "runs": 1, "parallels": 1, "me_level": 0, "group_id": 10, "child_level": 1}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            rows, cost, _ = aggregate_procurement(conn, [mother, subitem], price_type="sell")
        by_type = {r["type_id"]: r for r in rows}
        # 子项产品 2002 被排除（自制）；母项 2001 的三钛/类银计入；子项 2002 的三钛计入
        assert 2002 not in by_type
        assert by_type[1001]["to_buy"] == 1100  # 母项 1000 + 子项 100
        assert by_type[1002]["to_buy"] == 500
        assert cost == pytest.approx(1100 * 5 + 500 * 9)

    def test_deleted_subitem_reverts_to_procurement(self, temp_db):
        """子线被删后（无 sub_level>0 计划生产该组件）→ 组件回到待采购。"""
        with temp_db.connect("bp") as conn:
            conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',2002,2,10)")
        mother = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0, "group_id": 10, "child_level": 0}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            rows, _cost, _ = aggregate_procurement(conn, [mother], price_type="sell")
        by_type = {r["type_id"]: r for r in rows}
        assert 2002 in by_type  # 无子线 → 组件需采购
        assert by_type[2002]["to_buy"] == 2
