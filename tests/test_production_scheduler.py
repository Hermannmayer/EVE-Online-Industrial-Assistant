"""生产排程单元测试 — 使用临时数据库"""

import sqlite3

import pytest

from tests.conftest import _create_temp_databases

# ════════════════════════════════════════════════════════════════
#  辅助：在 user.db 中创建 production_plans 表并插入数据
# ════════════════════════════════════════════════════════════════


def _setup_production_plans(db_paths: dict):
    """向 user.db 写入 production_plans 表和测试数据"""
    conn = sqlite3.connect(db_paths["user"])
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hangar_id INTEGER NOT NULL,
            type_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS production_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_type_id INTEGER NOT NULL,
            product_name TEXT,
            blueprint_type_id INTEGER,
            runs INTEGER DEFAULT 1,
            parallels INTEGER DEFAULT 1,
            me_level INTEGER DEFAULT 0,
            te_level INTEGER DEFAULT 0,
            mat_hub TEXT DEFAULT 'Jita',
            sell_hub TEXT DEFAULT 'Jita',
            facility TEXT DEFAULT '',
            char_name TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            profit REAL DEFAULT 0,
            margin REAL DEFAULT 0,
            score REAL DEFAULT 0,
            material_cost REAL DEFAULT 0,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT
        );

        -- plan 1: 渡鸦级 (2001), blueprint 3001, 1 run
        INSERT INTO production_plans
            (id, product_type_id, product_name, runs, parallels, me_level, status, profit, score, created_at)
        VALUES
            (101, 2001, '渡鸦级', 1, 1, 0, 'pending', 5000000, 85, '2026-06-01 10:00:00');

        -- plan 2: 无人机 (2002), blueprint 3002, 5 runs
        INSERT INTO production_plans
            (id, product_type_id, product_name, runs, parallels, me_level, status, profit, score, created_at)
        VALUES
            (102, 2002, '无人机', 5, 1, 0, 'pending', 20000, 60, '2026-06-02 10:00:00');

        -- plan 3: 不存在的蓝图物品 → no_blueprint
        INSERT INTO production_plans
            (id, product_type_id, product_name, runs, parallels, status, created_at)
        VALUES
            (103, 99999, '未知物品', 1, 1, 'pending', '2026-06-03 10:00:00');
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def ps_db():
    """创建含 production_plans 数据的临时数据库，返回 (db_manager, db_paths)"""
    import shutil
    import tempfile

    from services.database_manager import DB_PATH_MAP, DatabaseManager

    tmpdir = tempfile.mkdtemp(prefix="eve_ps_")
    db_paths = _create_temp_databases(tmpdir)
    _setup_production_plans(db_paths)

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP.update(db_paths)

    db = DatabaseManager()
    yield db, db_paths

    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    shutil.rmtree(tmpdir, ignore_errors=True)


# ════════════════════════════════════════════════════════════════
#  测试类
# ════════════════════════════════════════════════════════════════


class TestAnalyzeProductionPlan:
    """analyze_production_plan 基础功能"""

    def test_plan_not_found(self, ps_db):
        """不存在的 plan_id 返回 not_found"""
        db_mgr, _ = ps_db
        import services.production_scheduler as ps
        ps.db = db_mgr

        result = ps.analyze_production_plan(plan_id=99999)
        assert result["status"] == "not_found"
        assert result["plan_id"] == 99999

    def test_plan_no_blueprint(self, ps_db):
        """物品无蓝图时返回 no_blueprint"""
        db_mgr, _ = ps_db
        import services.production_scheduler as ps
        ps.db = db_mgr

        result = ps.analyze_production_plan(plan_id=103)  # type_id=99999
        assert result["status"] == "no_blueprint"
        assert result["product_name"] == "未知物品"

    def test_plan_no_materials(self, ps_db):
        """蓝图无材料时返回 no_materials"""
        db_mgr, db_paths = ps_db
        # 清空 blueprint_materials 表，使蓝图有产品但无材料
        conn = sqlite3.connect(db_paths["bp"])
        conn.execute("DELETE FROM blueprint_materials WHERE blueprint_type_id = 3001")
        conn.commit()
        conn.close()

        import services.production_scheduler as ps
        ps.db = db_mgr

        result = ps.analyze_production_plan(plan_id=101)
        assert result["status"] == "no_materials"

    def test_plan_success(self, ps_db):
        """正常计划应返回材料明细和成本"""
        db_mgr, _ = ps_db
        import services.production_scheduler as ps
        ps.db = db_mgr

        result = ps.analyze_production_plan(plan_id=101)
        assert result["status"] == "pending"
        assert result["product_name"] == "渡鸦级"
        assert result["material_count"] == 2
        assert result["quantity"] > 0
        assert "total_material_cost" in result
        # missing_materials 应包含两种材料
        assert len(result["missing_materials"]) == 2
        mat_type_ids = [m["type_id"] for m in result["missing_materials"]]
        assert 1001 in mat_type_ids  # 三钛合金
        assert 1002 in mat_type_ids  # 类银超金属

    def test_plan_missing_materials(self, ps_db):
        """材料缺量表应正确计算"""
        db_mgr, _ = ps_db
        import services.production_scheduler as ps
        ps.db = db_mgr

        result = ps.analyze_production_plan(plan_id=101)
        assert "missing_materials" in result
        # 库存为 0，所有材料都缺
        assert len(result["missing_materials"]) == 2
        # 每种材料的 deficit>0
        for m in result["missing_materials"]:
            assert m["deficit"] > 0


class TestGetAllPlansSummary:
    """get_all_plans_summary 功能"""

    def test_summary_returns_all_plans(self, ps_db):
        """应返回所有计划"""
        db_mgr, _ = ps_db
        import services.production_scheduler as ps
        ps.db = db_mgr

        summary = ps.get_all_plans_summary()
        assert isinstance(summary, list)
        assert len(summary) == 3
        plan_ids = [s["plan_id"] for s in summary]
        assert 101 in plan_ids
        assert 102 in plan_ids
        assert 103 in plan_ids

    def test_summary_structure(self, ps_db):
        """每条摘要应包含关键字段"""
        db_mgr, _ = ps_db
        import services.production_scheduler as ps
        ps.db = db_mgr

        summary = ps.get_all_plans_summary()
        for item in summary:
            assert "plan_id" in item
            assert "status" in item
            # Successful plans have product_name; error ones have status key instead
            if "product_name" in item:
                assert isinstance(item["product_name"], str)


class TestSuggestProductionOrder:
    """suggest_production_order 功能"""

    def test_suggest_returns_ranked_list(self, ps_db):
        """应返回排序后的生产建议"""
        db_mgr, _ = ps_db
        import services.production_scheduler as ps
        ps.db = db_mgr

        result = ps.suggest_production_order()
        assert isinstance(result, list)
        # 至少包含 pending 状态的计划
        assert len(result) >= 2
        for item in result:
            assert "rank" in item
            assert "reason" in item


class TestOptimizeMaterialPurchase:
    """optimize_material_purchase 功能"""

    def test_optimize_with_plans(self, ps_db):
        """多计划材料采购优化"""
        db_mgr, _ = ps_db
        import services.production_scheduler as ps
        ps.db = db_mgr

        result = ps.optimize_material_purchase(plan_ids=[101, 102])
        assert "purchase_list" in result
        assert "total_cost" in result
        assert result["budget_remaining"] is None  # 无预算限制
        assert len(result["purchase_list"]) > 0

    def test_optimize_with_budget(self, ps_db):
        """有限预算应只购买部分材料"""
        db_mgr, _ = ps_db
        import services.production_scheduler as ps
        ps.db = db_mgr

        result = ps.optimize_material_purchase(plan_ids=[101, 102], budget=100)
        assert result["budget_remaining"] == 0 or result["budget_remaining"] <= 100
        assert result["total_cost"] <= 100
        # 预算极低时可能买不到任何材料
        if len(result["purchase_list"]) == 0:
            assert result["total_cost"] == 0

    def test_optimize_empty_plan_list(self, ps_db):
        """空计划列表应返回空采购清单"""
        db_mgr, _ = ps_db
        import services.production_scheduler as ps
        ps.db = db_mgr

        result = ps.optimize_material_purchase(plan_ids=[])
        assert result == {
            "purchase_list": [],
            "total_cost": 0,
            "budget_remaining": None,
        }
