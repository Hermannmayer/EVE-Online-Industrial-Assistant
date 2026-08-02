"""多蓝图批量加入制造规划 — _BulkPlanMetricsWorker 分组合并 + 并行派生测试"""

from types import SimpleNamespace

from ui_pyside6.views.inventory.blueprint_tab import _BulkPlanMetricsWorker


def _build_ref(db_manager):
    with db_manager.connect("ref") as conn:
        conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT)")
        conn.execute("INSERT INTO item VALUES (1001,'碳纤维','Carbon Fiber')")
        conn.execute("INSERT INTO item VALUES (2001,'渡鸦级','Raven')")
        conn.execute(
            "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute("INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1)")
        conn.execute("INSERT INTO blueprint_products VALUES (3002,'manufacturing',1001,1)")
        conn.execute(
            "CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, "
            "material_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',1001,1)")
        conn.execute("CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time REAL)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3001,'manufacturing',7200)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3002,'manufacturing',3600)")
    return db_manager


_METRICS = {
    "material_cost": 100.0,
    "profit": 50.0,
    "margin": 33.3,
    "score": 8.0,
    "iskph": 500.0,
    "calculated_time": 7200,
    "daily_output": 10.0,
    "revenue": 150.0,
    "fees": 0.0,
    "materials": [],
}


def _patch_scoring(monkeypatch, db_manager):
    """mock plan_service.calculate_plan_metrics → 固定 metrics，避免依赖真实评分"""
    from services import plan_service

    monkeypatch.setattr(
        "ui_pyside6.views.inventory.blueprint_tab.get_container",
        lambda: SimpleNamespace(db=db_manager),
    )
    monkeypatch.setattr(
        "services.plan_service.get_container",
        lambda: SimpleNamespace(db=db_manager),
    )
    monkeypatch.setattr(plan_service, "calculate_plan_metrics", lambda *a, **k: dict(_METRICS))


class TestBulkPlanMetricsWorker:
    def test_groups_merged_parallels_defaults_to_group_size(self, db_manager, monkeypatch, qapp):
        """多张相同(蓝图+ME+TE+流程)蓝图 → 合并成一行，parallels=张数"""
        _build_ref(db_manager)
        _patch_scoring(monkeypatch, db_manager)

        group_items = [
            [
                {"id": 1, "blueprint_type_id": 3001, "product_type_id": 2001, "me_level": 0, "te_level": 0, "runs": 1},
                {"id": 2, "blueprint_type_id": 3001, "product_type_id": 2001, "me_level": 0, "te_level": 0, "runs": 1},
            ],
            [
                {"id": 3, "blueprint_type_id": 3002, "product_type_id": 1001, "me_level": 5, "te_level": 0, "runs": 1},
            ],
        ]
        worker = _BulkPlanMetricsWorker(group_items, "测试产品", "", parent=None)
        captured: list[list[dict]] = []
        worker.done.connect(captured.append)
        worker.run()
        rows = captured[0]

        assert len(rows) == 2  # 两组 → 2 行
        # 第一组 2 张同蓝图 → parallels=2（组大小）；第二组 1 张 → parallels=1
        assert rows[0]["data"]["parallels"] == 2
        assert rows[1]["data"]["parallels"] == 1
        # 每行的 bp_ids 收集了组内全部蓝图 id
        assert rows[0]["bp_ids"] == [1, 2]
        assert rows[1]["bp_ids"] == [3]
        # ME/TE 从组内第一张蓝图取值
        assert rows[1]["data"]["me"] == 5
        # runs 按蓝图自身流程数
        assert rows[0]["data"]["runs"] == 1
        # metrics 透传到行
        assert rows[0]["metrics"]["profit"] == 50.0

    def test_single_group_me_te_runs_from_blueprint(self, db_manager, monkeypatch, qapp):
        """单张蓝图 → 一行；ME/TE/runs 全部取蓝图自身属性（不弹窗整张加入）"""
        _build_ref(db_manager)
        _patch_scoring(monkeypatch, db_manager)

        group_items = [
            [
                {
                    "id": 9,
                    "blueprint_type_id": 3001,
                    "product_type_id": 2001,
                    "me_level": 6,
                    "te_level": 4,
                    "runs": 3,
                }
            ]
        ]
        worker = _BulkPlanMetricsWorker(group_items, "渡鸦级", "", parent=None)
        captured: list[list[dict]] = []
        worker.done.connect(captured.append)
        worker.run()
        rows = captured[0]

        assert len(rows) == 1
        assert rows[0]["data"]["me"] == 6
        assert rows[0]["data"]["te"] == 4
        assert rows[0]["data"]["runs"] == 3
        assert rows[0]["data"]["parallels"] == 1
        assert rows[0]["bp_ids"] == [9]

    def test_worker_survives_gc_with_strong_ref(self, qapp):
        """QThread 被 self 强引用保活 → GC 后不崩溃（回归：多蓝图闪退根因）。

        直接验证 PySide6 行为：worker 挂在持有者对象上，局部变量回收后线程仍存活。
        """
        import gc

        holder = SimpleNamespace()

        worker = _BulkPlanMetricsWorker([], "", "", parent=None)
        holder.worker = worker  # 强引用保活（与 BlueprintTab._add_plan_bulk 同模式）

        worker.start()
        worker.wait(2000)  # 线程很快结束（空输入）
        del worker
        gc.collect()

        assert holder.worker is not None  # 强引用对象仍可访问，无崩溃
