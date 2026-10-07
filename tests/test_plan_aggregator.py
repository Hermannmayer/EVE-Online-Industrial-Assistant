"""备料采购聚合测试 — services/plan_aggregator.aggregate_procurement（需求2）"""

import pytest

from services.plan_aggregator import aggregate_procurement, collect_direct_materials


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

    def test_zero_runs_plan_contributes_nothing(self, temp_db):
        """runs=0 的产线一个都不产出 → 它不该往待采购里塞任何需求（其余计划的需求不变）。

        回归（用户报「待采购提示 7000 万、计划表却显示已满足」）：`total_runs` 原先写
        `max(int(runs or 1), 1)`，把 runs=0 兜成「1 轮 × 并行数」算料，于是这条没在跑的
        产线报出一份没人消耗的需求；1b 段的 `material_short` 与 `collect_direct_materials`
        同病。0 轮 = 0 材料、0 产出，三个入口必须同意这一条。
        """
        running = {"product_type_id": 2001, "runs": 1, "parallels": 1, "me_level": 0}
        stopped = {
            "product_type_id": 2002,  # 无人机：100 三钛/轮
            "runs": 0,
            "parallels": 3,
            "me_level": 0,
            "material_short": '{"1002": 77}',  # 强制启动缺口也不该并入
        }
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            rows, cost, _vol = aggregate_procurement(conn, [running, stopped], price_type="sell")
            solo, solo_cost, _v = aggregate_procurement(conn, [running], price_type="sell")
            mats = collect_direct_materials(conn, [running, stopped])

        by_type = {r["type_id"]: r for r in rows}
        # 1001 只要 1000（不是 1000 + 100/轮 × 3 并行）；1002 只要 500（不是 +77）
        assert (by_type[1001]["need"], by_type[1002]["need"]) == (1000, 500)
        assert cost == pytest.approx(solo_cost)
        assert {(r["type_id"], r["need"], r["to_buy"]) for r in rows} == {
            (r["type_id"], r["need"], r["to_buy"]) for r in solo
        }, "runs=0 的计划不得改变其余计划的需求"
        assert mats[1001]["total_qty"] == 1000, "collect_direct_materials 必须同一口径"

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

    def test_pure_purchase_plan_reports_no_overflow(self, temp_db):
        """**纯采购**的计划不许报「材料溢出」——溢出只在真的自制时成立。

        回归背景（2026-09-28，用户报告）：溢出原先只看 SDE —— 只要中间件在
        `blueprint_products` 里有制造蓝图，就按 `ceil(需求/单次产出)` 假装你会自己跑，
        于是**全部直接采购**的计划也报溢出（实测 R.A.M.-装甲/船体科技「溢出 62 个」、
        R.A.M.-能源科技「91 个 / 65 个」）。列名又叫「材料溢出」，必然被读成 bug。

        修法是加自制闸门：`step.type_id` 必须真的出现在这批计划的子项产线里
        （`sub_level > 0`）才算。这里同时钉死**不能修过头** —— 一旦真有子线，照旧要报。
        """
        self._seed_intermediate(temp_db)
        # 让中间件 2003 每轮产 4（`_seed_intermediate` 默认产 1），这样母项对它取整后
        # 一定多产几个 → 旧口径下溢出必然 > 0，修复后必然为 False，对比才有意义。
        with temp_db.connect("bp") as conn:
            conn.execute("DELETE FROM blueprint_products WHERE blueprint_type_id=3003")
            conn.execute("INSERT INTO blueprint_products VALUES (3003,'manufacturing',2003,4)")

        from services.plan_aggregator import calculate_output_with_overflow

        mother = {
            "product_type_id": 2001,
            "product_name": "渡鸦级",
            "runs": 1,
            "parallels": 1,
            "me_level": 0,
            "sub_level": 0,  # 母项
            "status": "pending",
        }
        with temp_db.connect("user", "ref", "bp", "mkt") as conn:
            out = calculate_output_with_overflow(conn, [mother])
            assert out[0]["has_overflow"] is False, f"纯采购不该报溢出：{out[0]['overflow_text']}"

            # 同一件一旦真有子项产线，就该照旧报溢出（修复不能修过头）
            subline = {**mother, "product_type_id": 2003, "sub_level": 1, "status": "in_progress"}
            out2 = calculate_output_with_overflow(conn, [mother, subline])
            row = next(r for r in out2 if r["product_type_id"] == 2001)
            assert row["has_overflow"] is True, "有子线自制时应当照旧报溢出"


# ════════════════════════════════════════════════════════════════
#  蓝图需求展开 — 科研行（拷贝/发明/研究）+ 反应行
# ════════════════════════════════════════════════════════════════
#
# 回归背景（2026-10-02，用户报告）：工业规划页「所需蓝图」表里，发明/拷贝项目缺的
# 前置蓝图一个都不显示。根因两处：调用方 SELECT 没取 `activity`（`is_science(None)`
# 归一到制造），科研行于是被当成「制造产物」去反查制造蓝图 —— 而科研行的
# `product_type_id` 是**蓝图**，查不到就静默丢弃。修法是按活动给出该作业真正
# 消耗的那张蓝图（真源 `services.plan_job_kinds`）。
# 同一类静默丢失还有**反应行**：反应产物的蓝图挂在 `activity='reaction'` 行上，
# 只反查 manufacturing 一样查不到（见 `test_..._covers_reaction_rows`）。

#: 回归用计划（id 必须给：拷贝行要按 id 解析绑定 BPO）
_SCIENCE_PLANS = [
    {
        "id": 1,
        "product_type_id": 2001,
        "product_name": "渡鸦级",
        "runs": 2,
        "parallels": 3,
        "activity": "manufacturing",
    },
    # 发明产物 4002 ← T1 4001
    {"id": 2, "product_type_id": 4002, "product_name": "T2蓝图", "runs": 3, "parallels": 4, "activity": "invention"},
    # 未绑定 → 回退 product_type_id
    {"id": 3, "product_type_id": 4003, "product_name": "普通蓝图", "runs": 10, "parallels": 5, "activity": "copying"},
    # 绑定 ub.id=9（那份的类型是 4009，与 product_type_id 4006 不同）
    {
        "id": 4,
        "product_type_id": 4006,
        "product_name": "被绑定的拷贝",
        "runs": 10,
        "parallels": 2,
        "activity": "copying",
    },
    # 与计划 3 研究/拷贝同一张蓝图 → 用途并成一格
    {
        "id": 5,
        "product_type_id": 4003,
        "product_name": "普通蓝图",
        "runs": 8,
        "parallels": 1,
        "activity": "researching_material_efficiency",
    },
    {
        "id": 6,
        "product_type_id": 4008,
        "product_name": "待研究蓝图",
        "runs": 5,
        "parallels": 1,
        "activity": "researching_time_efficiency",
    },
    # 发明 4005 ← 输入 4010（**遗物**，不是蓝图）→ 用途列带「（遗物）」括注
    {"id": 7, "product_type_id": 4005, "product_name": "T3蓝图", "runs": 2, "parallels": 3, "activity": "invention"},
    # 反应：蓝图挂在 activity='reaction' 行上（每轮产 4），只认 manufacturing 会查不到
    {"id": 8, "product_type_id": 5001, "product_name": "反应产物", "runs": 4, "parallels": 5, "activity": "reaction"},
    # 同一产物挂**两张**反应蓝图：4011「测试反应配方」（20/轮）与 4012 真配方（2/轮）。
    # 旧 SQL 无 ORDER BY，哪张先返回全看 rowid 运气 —— 这里两张都插，钉死必须取真配方。
    {"id": 9, "product_type_id": 6001, "product_name": "双蓝图产物", "runs": 2, "parallels": 2, "activity": "reaction"},
]

#: {蓝图 type_id: (needed_runs, 用途/来源列文案)}
_SCIENCE_EXPECTED = {
    3001: (6, "制造蓝图"),  # 2×3 流程 ÷ 单轮产出 1（制造行口径不变）
    4001: (12, "发明输入"),  # 3×4 尝试
    4003: (5, "被拷贝蓝图、被研究蓝图"),  # 5 份拷贝；研究同张只并用途不加流程
    4009: (2, "被拷贝蓝图"),  # 绑定那份 BPO 的类型（product_type_id 4006 ≠ 4009）
    4008: (1, "被研究蓝图"),
    4010: (6, "发明输入（遗物）"),  # T3 发明的输入是冬眠者遗物，永远不在 user_blueprints 里
    5002: (5, "反应蓝图"),  # 4×5=20 产出 ÷ 每轮 4 = 5 次反应作业
    4012: (2, "反应蓝图"),  # 2×2=4 产出 ÷ 每轮 2 = 2 次（**不是**测试蓝图 4011 的 20/轮 → 4）
}


def _seed_science_plans(db) -> None:
    """建科研回归用的最小三库（user/bp/ref），并写入计划、绑定、发明路径。"""
    with db.connect("user") as conn:
        conn.executescript(
            """
            CREATE TABLE production_plans (
                id INTEGER PRIMARY KEY, product_type_id INTEGER, product_name TEXT,
                runs INTEGER, parallels INTEGER, me_level INTEGER DEFAULT 0,
                activity TEXT, assigned_blueprint_id INTEGER, status TEXT DEFAULT 'pending'
            );
            CREATE TABLE plan_blueprint_bindings (plan_id INTEGER, blueprint_id INTEGER, runs_used INTEGER);
            CREATE TABLE user_blueprints (
                id INTEGER PRIMARY KEY, blueprint_type_id INTEGER, is_bpo INTEGER DEFAULT 1,
                runs INTEGER DEFAULT 0, quantity INTEGER DEFAULT 1,
                me_level INTEGER DEFAULT 0, te_level INTEGER DEFAULT 0
            );
            INSERT INTO user_blueprints (id, blueprint_type_id, is_bpo, quantity) VALUES (9, 4009, 1, 1);
            """
        )
        for p in _SCIENCE_PLANS:
            conn.execute(
                "INSERT INTO production_plans "
                "(id, product_type_id, product_name, runs, parallels, activity, status) "
                "VALUES (?,?,?,?,?,?,'pending')",
                (
                    p["id"],
                    p["product_type_id"],
                    p["product_name"],
                    p["runs"],
                    p["parallels"],
                    p["activity"],
                ),
            )
        conn.execute("INSERT INTO plan_blueprint_bindings (plan_id, blueprint_id) VALUES (4, 9)")

    with db.connect("ref") as conn:
        # group 名后缀是 `item_kind` 判定「是不是蓝图」的唯一口径（跟真实库同形状）
        conn.execute(
            "CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT, "
            "zh_group_name TEXT, en_group_name TEXT, volume REAL)"
        )
        for tid, zh, group in (
            (2001, "渡鸦级", "巡洋舰"),
            (3001, "渡鸦级蓝图", "巡洋舰蓝图"),
            (4001, "T1蓝图", "护卫舰蓝图"),
            (4002, "T2蓝图", "战术驱逐舰蓝图"),
            (4003, "普通蓝图", "通用蓝图"),
            (4005, "T3蓝图", "战术驱逐舰蓝图"),
            (4008, "待研究蓝图", "通用蓝图"),
            (4009, "绑定的蓝图", "通用蓝图"),
            (4010, "完整的小型船体舱段", "冬眠者船体"),  # 古遗物：group 不以「蓝图」结尾
            (5001, "反应产物", "反应材料"),
            (5002, "反应式蓝图", "反应蓝图"),
            (6001, "双蓝图产物", "反应材料"),
            # 4001 / 4003 / 4008 / 4009 / 4010 走的是**别的**查询路径，但统一入口
            # 「排除测试蓝图」要靠 `ref.item` 的名称判 —— 真实 SDE 里每张蓝图在 item 表
            # 都有行，所以这里也必须给全，否则测的是一个不存在的形状。4011 的名字带
            # 「测试」→ 正是统一入口的排除判据。
            (4011, "测试反应配方", "反应蓝图"),
            (4012, "真反应配方", "反应蓝图"),
        ):
            conn.execute(
                "INSERT INTO item (type_id, zh_name, en_name, zh_group_name, en_group_name) VALUES (?,?,?,?,?)",
                (tid, zh, zh, group, group),
            )

    with db.connect("bp") as conn:
        conn.executescript(
            """
            CREATE TABLE blueprint_products (
                blueprint_type_id INTEGER, activity TEXT, product_type_id INTEGER,
                quantity INTEGER, probability REAL
            );
            CREATE TABLE blueprint_activities (
                blueprint_type_id INTEGER, activity TEXT, time REAL, max_production_limit INTEGER
            );
            INSERT INTO blueprint_products VALUES (3001, 'manufacturing', 2001, 1, NULL);
            INSERT INTO blueprint_products VALUES (4001, 'invention', 4002, 1, 0.34);
            INSERT INTO blueprint_products VALUES (4010, 'invention', 4005, 1, 0.34);
            INSERT INTO blueprint_products VALUES (5002, 'reaction', 5001, 4, NULL);
            INSERT INTO blueprint_products VALUES (4011, 'reaction', 6001, 20, NULL);
            INSERT INTO blueprint_products VALUES (4012, 'reaction', 6001, 2, NULL);
            -- 统一入口按 (blueprint_type_id, activity) 内连活动表取时间，缺行等于「没这张蓝图」
            INSERT INTO blueprint_activities VALUES (3001, 'manufacturing', 3600, NULL);
            INSERT INTO blueprint_activities VALUES (5002, 'reaction', 3600, NULL);
            INSERT INTO blueprint_activities VALUES (4011, 'reaction', 3600, NULL);
            INSERT INTO blueprint_activities VALUES (4012, 'reaction', 3600, NULL);
            INSERT INTO blueprint_activities VALUES (4001, 'invention', 3600, NULL);
            INSERT INTO blueprint_activities VALUES (4010, 'invention', 3600, NULL);
            """
        )


def test_expand_blueprint_requirements_covers_science_rows(db_manager):
    """科研/反应行给出「该作业真正要消耗的那张蓝图」，制造行口径不变。

    覆盖：发明 → T1 输入；拷贝 → 绑定的 BPO（`plan_blueprint_bindings` 口径，
    行 id ≠ type_id）/ 未绑定回退；研究 → 被研究的那张 BPO 本身；反应 → 挂在
    `activity='reaction'` 行上的反应蓝图（单轮产出也按 reaction 行取）；同一张蓝图的
    多种用途并成一格；发明输入**不是蓝图**（T3 遗物）时用途列带「（遗物）」；
    制造行 `needed_runs` 仍是 `ceil(runs×parallels ÷ 单轮产出)`；
    **同一产物同时挂测试蓝图与真实蓝图时必须取真实蓝图**（产物 6001 两张都挂，
    旧 SQL 没有 ORDER BY，取到哪张全看 rowid 运气 → 流程数会差 10 倍量级）。
    """
    from services.plan_aggregator import expand_blueprint_requirements

    _seed_science_plans(db_manager)
    with db_manager.connect("user", "ref", "bp") as conn:
        needed = expand_blueprint_requirements(conn, _SCIENCE_PLANS)

    assert {tid: (v["needed_runs"], v["source"]) for tid, v in needed.items()} == _SCIENCE_EXPECTED
    assert needed[4001]["name"] == "T1蓝图"
    assert needed[4009]["name"] == "绑定的蓝图"
    assert needed[4010]["name"] == "完整的小型船体舱段"
    # 测试蓝图 4011 与真实蓝图 4012 都产出 6001：只许留下真实的那张
    assert 4011 not in needed, "测试蓝图被当成了配方"
    assert needed[4012]["needed_runs"] == 2, "取到测试蓝图的话这里是 2×2÷20 → 1"

    # 同一判据的另一个入口（「要绑哪张蓝图」弹窗），用的是同一个统一入口
    from services.plan_aggregator import plan_input_blueprint_type_id

    with db_manager.connect("user", "ref", "bp") as conn:
        assert plan_input_blueprint_type_id(conn, _SCIENCE_PLANS[8]) == 4012


def test_expand_blueprint_requirements_covers_reaction_rows(db_manager):
    """反应计划也要列出它的**反应蓝图** —— 只反查 manufacturing 会整行静默丢失。

    连带钉死单轮产出必须同取 `activity='reaction'` 那一行：拿 manufacturing 拿不到
    会兜成 1，「所需流程数」从 5 虚高到 20。
    """
    from services.plan_aggregator import expand_blueprint_requirements

    _seed_science_plans(db_manager)
    reaction_plans = [p for p in _SCIENCE_PLANS if p["activity"] == "reaction"]
    with db_manager.connect("user", "ref", "bp") as conn:
        needed = expand_blueprint_requirements(conn, reaction_plans)

    assert {tid: (v["needed_runs"], v["source"]) for tid, v in needed.items()} == {
        5002: (5, "反应蓝图"),
        4012: (2, "反应蓝图"),  # 6001 挂了测试 4011(20/轮) 与真实 4012(2/轮) → 必须取后者
    }


def test_get_blueprint_requirements_includes_science_rows(db_manager):
    """端到端回归：`get_blueprint_requirements` 漏取 `activity` 时这些行整行消失。

    断言表里真出现发明输入 / 反应蓝图，并且 `bp_inv` 覆盖到全部
    （桥按 `needed`/`bp_inv` 两半拼表）。
    """
    from services.industry_dialog_queries import get_blueprint_requirements

    _seed_science_plans(db_manager)
    result = get_blueprint_requirements(db_manager)

    assert result["status"] == "ok"
    assert set(result["needed"]) == set(_SCIENCE_EXPECTED)
    assert result["needed"][4001] == {"name": "T1蓝图", "needed_runs": 12, "source": "发明输入"}
    assert result["needed"][4010]["source"] == "发明输入（遗物）"  # 遗物输入照实标注
    assert set(result["bp_inv"]) == set(result["needed"])
    assert result["bp_inv"][4001]["count"] == 0  # T1 不在库里 → 桥显示「缺少」
    assert result["bp_inv"][4009]["is_bpo"] is True  # 绑定的那份是 BPO → 「无限」


def test_plan_input_blueprint_type_id_resolves_per_activity(db_manager):
    """「要绑哪张蓝图」按活动解析 —— 弹窗与自动绑定共用这一份取数。

    回归（2026-10-06，用户报「点『蓝图差几张』弹窗完全为空」）：老口径无脑按
    `product_type_id` 反查 `activity='manufacturing'`，而科研行的产物是**蓝图**、不是
    制造品，必然查不到；发明的输入更是要由产物那张 T2 **反查 T1**（发明作业跑在 T1 上）。
    同一份取数也供 `plan_execution._available_blueprint_options` 用，两处不会各说一套。
    """
    from services.plan_aggregator import plan_input_blueprint_type_id

    _seed_science_plans(db_manager)
    with db_manager.connect("user", "ref", "bp") as conn:
        got = {p["id"]: plan_input_blueprint_type_id(conn, p) for p in _SCIENCE_PLANS}

    assert got == {
        1: 3001,  # 制造：按产物反查
        2: 4001,  # 发明：产物 T2 4002 → 输入 T1 4001
        3: 4003,  # 拷贝未绑定：回退 product_type_id（产出的 BPC 就代表这张）
        4: 4009,  # 拷贝已绑定：绑的那份的类型（绑定存的是行 id 9，≠ type_id 4009）
        5: 4003,  # 研究：被研究的那张本身
        6: 4008,
        7: 4010,  # T3 发明：输入是古遗物（调用方据 is_blueprint 提示绑不了）
        8: 5002,  # 反应：蓝图挂在 activity='reaction' 行上
        9: 4012,  # 6001 同时挂测试蓝图 4011 与真配方 4012 → 必须给真的那张
    }
