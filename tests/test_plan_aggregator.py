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

    def test_spread_is_the_gap_over_qty_and_ignores_mult(self, temp_db):
        """价差 = (卖价 − 买价) × 需采购量（金额，不是单价差），且**不吃 price_mult**。

        两件的单价差都是 1，数量 1000 / 500 不同 —— 结果必须跟着数量走，
        否则又退回「和总价对不上的那一列单价差」（用户报过）。
        """
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            rows, _cost, _vol = aggregate_procurement(conn, [plan], price_type="sell", price_mult=2.0)
        by_type = {r["type_id"]: r for r in rows}
        assert by_type[1001]["spread"] == pytest.approx((5 - 4) * 1000)
        assert by_type[1002]["spread"] == pytest.approx((9 - 8) * 500)
        assert by_type[1001]["price"] == pytest.approx(5 * 2.0), "单价照旧吃倍率，价差不吃"

    def test_spread_is_none_when_one_side_has_no_order(self, temp_db):
        """单边挂单 → `None` 而不是 0：「算不出」不能伪装成「卖买同价」。"""
        with temp_db.connect("mkt") as conn:
            conn.execute("UPDATE market_prices SET buy_price = 0 WHERE type_id = 1001")
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            rows, _cost, _vol = aggregate_procurement(conn, [plan], price_type="sell")
        by_type = {r["type_id"]: r for r in rows}
        assert by_type[1001]["spread"] is None, "只有卖单时价差算不出来"
        assert by_type[1002]["spread"] == pytest.approx(500.0), "另一件不受影响"

    def test_price_mult_scales_unit_price(self, temp_db):
        """材料倍率乘在单价上：price 与 total 同步缩放，to_buy / volume 不变。"""
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            base_rows, base_cost, base_vol = aggregate_procurement(conn, [plan], price_type="sell")
            rows, cost, vol = aggregate_procurement(conn, [plan], price_type="sell", price_mult=1.1)
        base_by = {r["type_id"]: r for r in base_rows}
        assert cost == pytest.approx(base_cost * 1.1)
        assert vol == pytest.approx(base_vol)  # 体积是物理量，不受价格倍率影响
        for row in rows:
            base = base_by[row["type_id"]]
            assert row["price"] == pytest.approx(base["price"] * 1.1)
            assert row["total"] == pytest.approx(row["to_buy"] * row["price"])  # 单价×数量恒等式仍成立
            assert row["to_buy"] == base["to_buy"]

    def test_price_mult_default_and_invalid_fall_back_to_one(self, temp_db):
        """不传 / 传 1.0 / 传非正数，三者结果一致（settings.json 可手改，不能信）。"""
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            _r, base_cost, _v = aggregate_procurement(conn, [plan], price_type="sell")
            _r, one_cost, _v = aggregate_procurement(conn, [plan], price_type="sell", price_mult=1.0)
            _r, zero_cost, _v = aggregate_procurement(conn, [plan], price_type="sell", price_mult=0)
        assert one_cost == pytest.approx(base_cost)
        assert zero_cost == pytest.approx(base_cost)

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

    def test_material_short_merged_into_need(self, temp_db):
        """强制启动缺口并入需求：material_short 的 300 三钛叠加到 BOM 需求 1000。"""
        _inventory(temp_db, 5, 1001, 400)
        plan = {
            "product_type_id": 2001,
            "runs": 1,
            "parallels": 1,
            "me_level": 0,
            "mat_hangar_id": 5,
            "material_short": '{"1001": 300}',
        }
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            rows, cost, _ = aggregate_procurement(conn, [plan], price_type="sell")
        by_type = {r["type_id"]: r for r in rows}
        assert by_type[1001]["need"] == 1300
        assert by_type[1001]["owned"] == 400
        assert by_type[1001]["to_buy"] == 900
        assert cost == pytest.approx(900 * 5 + 500 * 9)

    def test_rows_include_raw_names(self, temp_db):
        """行携带 zh_name/en_name 原值供 UI 名称展示，而非回退 type_id。"""
        plan = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0}
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            rows, _cost, _vol = aggregate_procurement(conn, [plan], price_type="sell")
        by_type = {r["type_id"]: r for r in rows}
        assert by_type[1001]["zh_name"] == "三钛合金"
        assert by_type[1001]["en_name"] == "Tritanium"
        assert by_type[1001]["name"] != str(1001)


class TestSelfMadeComponents:
    """自制件排除：`self_made` 必须按**全量计划**算，不能按筛过的「备料中」那一份。

    回归背景：调用方为了口径统一会把计划筛成 `materials_ready && pending`，而子项产线
    往往**正在生产中** —— 排除集原先从传进来的 `plans` 现算，于是子线「不存在」了，
    它的产物被当成待采购再买一遍（用户报的「电磁发生器已在生产，采购仍报缺 2504」）。
    """

    @staticmethod
    def _seed_intermediate(db_manager) -> None:
        """给 3001 加一个自制中间件 2003（自己有蓝图 3003，每轮产 1）。"""
        with db_manager.connect("bp") as conn:
            conn.execute("DELETE FROM blueprint_materials WHERE blueprint_type_id=3001")
            for table in ("blueprint_activities", "blueprint_products"):
                conn.execute(f"DELETE FROM {table} WHERE blueprint_type_id=3003")
            conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',2003,5,10)")
            conn.execute("INSERT INTO blueprint_activities VALUES (3003,'manufacturing',3600)")
            conn.execute("INSERT INTO blueprint_products VALUES (3003,'manufacturing',2003,1)")

    def test_self_made_ids_cover_unfinished_sublines_only(self):
        from services.plan_aggregator import self_made_type_ids

        plans = [
            {"product_type_id": 2001, "sub_level": 0, "status": "pending"},  # 母项不算
            {"product_type_id": 2003, "sub_level": 1, "status": "in_progress"},  # 算
            {"product_type_id": 2004, "sub_level": 1, "status": "pending"},  # 算
            {"product_type_id": 2005, "sub_level": 1, "status": "ready"},  # 算（产出还没入库）
            {"product_type_id": 2006, "sub_level": 1, "status": "completed"},  # 不算（产出已入库）
            {"product_type_id": 2007, "sub_level": 1, "status": "done"},  # 不算
        ]
        assert self_made_type_ids(plans) == {2003, 2004, 2005}

    def test_running_sublines_component_is_excluded(self, temp_db):
        """子线在生产中 → 它的产物不该出现在待采购里（这正是用户报的那条）。"""
        self._seed_intermediate(temp_db)
        mother = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0}
        running_sublines = [{"product_type_id": 2003, "sub_level": 1, "status": "in_progress"}]

        from services.plan_aggregator import self_made_type_ids

        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            # 不传排除集 = 旧行为（从筛过的 plans 现算）→ 2003 被算成待采购
            rows, _cost, _vol = aggregate_procurement(conn, [mother])
            assert 2003 in {r["type_id"] for r in rows}, "前提：不传排除集时它就是会算进去"

            # 传「全量计划算出」的排除集 → 2003 被剔除
            rows2, _cost2, _vol2 = aggregate_procurement(
                conn,
                [mother],
                self_made=self_made_type_ids([mother, *running_sublines]),
            )
            assert 2003 not in {r["type_id"] for r in rows2}, "自制件被重复计成待采购了"
