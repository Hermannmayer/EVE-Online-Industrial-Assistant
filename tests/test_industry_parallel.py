"""大规模/子项并行测试 — 纯函数 + 弹窗校验"""

from types import SimpleNamespace

from ui_pyside6.views.industry.mass_parallel_dialog import (
    compute_parallel_by_duration,
    compute_parallel_by_lines,
)


class TestComputeParallelByLines:
    def test_even_distribution(self):
        subitems = [{"id": 1, "demand": 100, "per_run": 1}, {"id": 2, "demand": 100, "per_run": 1}]
        result = compute_parallel_by_lines(subitems, 6)
        assert {r["id"]: r["parallels"] for r in result} == {1: 3, 2: 3}

    def test_weighted(self):
        subitems = [{"id": 1, "demand": 300, "per_run": 1}, {"id": 2, "demand": 100, "per_run": 1}]
        result = compute_parallel_by_lines(subitems, 6)
        assert {r["id"]: r["parallels"] for r in result} == {1: 4, 2: 2}

    def test_less_lines_than_items(self):
        subitems = [{"id": 1, "demand": 10, "per_run": 1}, {"id": 2, "demand": 10, "per_run": 1}]
        result = compute_parallel_by_lines(subitems, 1)
        assert {r["id"]: r["parallels"] for r in result} == {1: 1, 2: 1}  # 每子项至少 1

    def test_empty(self):
        assert compute_parallel_by_lines([], 10) == []


class TestComputeParallelByDuration:
    def test_ceil_to_target_days(self):
        subitems = [
            {"id": 1, "duration_sec": 10 * 86400},
            {"id": 2, "duration_sec": 3 * 86400},
        ]
        result = compute_parallel_by_duration(subitems, 5)
        assert {r["id"]: r["parallels"] for r in result} == {1: 2, 2: 1}  # ceil(10/5)=2, ceil(3/5)=1

    def test_zero_duration(self):
        assert compute_parallel_by_duration([{"id": 1, "duration_sec": 0}], 5) == [{"id": 1, "parallels": 1}]


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
        conn.execute(
            "CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time REAL)"
        )
        conn.execute("INSERT INTO blueprint_activities VALUES (3001,'manufacturing',7200)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3002,'manufacturing',3600)")
    return db_manager


class TestChildParallelDialog:
    def test_validation_blocks_insufficient(self, db_manager, monkeypatch, qapp):
        from ui_pyside6.views.industry.child_parallel_dialog import ChildParallelDialog

        _build_ref(db_manager)
        monkeypatch.setattr(
            "ui_pyside6.views.industry.child_parallel_dialog.get_container",
            lambda: SimpleNamespace(db=db_manager),
        )
        plans = [
            {"id": 10, "product_type_id": 2001, "sub_level": 0, "runs": 2, "parallels": 1, "me_level": 0},
            {"id": 11, "product_type_id": 1001, "sub_level": 1, "runs": 1, "parallels": 1, "blueprint_type_id": 3002},
        ]
        dlg = ChildParallelDialog(plans)
        # 母项需求 1001 = 2；子项 runs1×parallels1×per_run1 = 1 < 2 → 校验拦截
        assert not dlg._ok_btn.isEnabled()
        # 提高到 runs=2 → 产出 2 ≥ 2 → 通过
        dlg._spins[0][1].setValue(2)
        assert dlg._ok_btn.isEnabled()

    def test_sufficient_passes(self, db_manager, monkeypatch, qapp):
        from ui_pyside6.views.industry.child_parallel_dialog import ChildParallelDialog

        _build_ref(db_manager)
        monkeypatch.setattr(
            "ui_pyside6.views.industry.child_parallel_dialog.get_container",
            lambda: SimpleNamespace(db=db_manager),
        )
        plans = [
            {"id": 10, "product_type_id": 2001, "sub_level": 0, "runs": 2, "parallels": 1, "me_level": 0},
            {"id": 11, "product_type_id": 1001, "sub_level": 1, "runs": 2, "parallels": 1, "blueprint_type_id": 3002},
        ]
        dlg = ChildParallelDialog(plans)
        assert dlg._ok_btn.isEnabled()  # runs2×1×1=2 ≥ 需求2
