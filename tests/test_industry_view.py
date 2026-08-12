"""工业制造视图单元测试 — IndustryPage + init_plan_db

测试覆盖:
  - PLAN_DB_SCHEMA 定义完整性
  - 数据模型操作
"""

from PySide6.QtCore import Qt

from services.repositories.plan_repository import PlanRepository
from ui_pyside6.models.industry_models import PlanTableModel

# production_plans schema 单一来源：PlanRepository.SCHEMA（原 industry_view.PLAN_DB_SCHEMA 已收敛）
PLAN_DB_SCHEMA = PlanRepository.SCHEMA

# ══════════════════════════════════════
#  PLAN_DB_SCHEMA
# ══════════════════════════════════════


class TestPlanDbSchema:
    """生产计画数据库 Schema 定义"""

    def test_schema_creates_production_plans(self):
        """Schema 应包含 production_plans 表"""
        assert "CREATE TABLE IF NOT EXISTS production_plans" in PLAN_DB_SCHEMA

    def test_schema_has_required_columns(self):
        """Schema 应包含所有必要字段"""
        required = [
            "id INTEGER PRIMARY KEY AUTOINCREMENT",
            "product_type_id INTEGER NOT NULL",
            "product_name TEXT",
            "runs INTEGER DEFAULT 1",
            "profit REAL DEFAULT 0",
            "score REAL DEFAULT 0",
        ]
        for col in required:
            assert col in PLAN_DB_SCHEMA, f"缺少列定义: {col}"

    def test_schema_contains_plan_table(self):
        """Schema 应定义 production_plans 表"""
        assert "CREATE TABLE IF NOT EXISTS production_plans" in PLAN_DB_SCHEMA


# ══════════════════════════════════════
#  PlanTableModel 操作
# ══════════════════════════════════════

# 注意: 完整的 PlanTableModel 测试已在 test_industry_models.py 中覆盖
# 这里只补充 IndustryPage 相关的集成测试


class TestPlanTableIntegration:
    """生产计划表模型集成操作"""

    SAMPLE_PLANS = [
        {
            "product_type_id": 2001,
            "product_name": "渡鸦级",
            "runs": 5,
            "parallels": 2,
            "me_level": 10,
            "te_level": 20,
            "mat_hub": "Jita",
            "sell_hub": "Jita",
            "char_name": "TestChar",
            "profit": 10_000_000,
            "market_margin": 20.0,
            "score": 90,
            "iskph": 2_500_000,
            "material_cost": 30_000_000,
            "status": "pending",
            "notes": "测试备注",
            "facility": "测试设施",
        },
        {
            "product_type_id": 2002,
            "product_name": "无人机",
            "runs": 100,
            "parallels": 1,
            "me_level": 0,
            "te_level": 0,
            "mat_hub": "Amarr",
            "sell_hub": "Jita",
            "char_name": "",
            "profit": 1_000_000,
            "market_margin": 100.0,
            "score": 60,
            "iskph": 100_000,
            "material_cost": 500_000,
            "status": "in_progress",
            "notes": "",
            "facility": "",
        },
    ]

    def test_get_plan(self, qapp):
        """get_plan 返回正确"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        plan = model.get_plan(0)
        assert plan["product_name"] == "渡鸦级"
        assert plan["runs"] == 5
        assert plan["score"] == 90

    def test_get_plan_out_of_range(self, qapp):
        """get_plan 越界返回空 dict"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        assert model.get_plan(-1) == {}
        assert model.get_plan(999) == {}

    def test_get_plan_empty_model(self, qapp):
        """空模型 get_plan 返回空 dict"""
        model = PlanTableModel([])
        assert model.get_plan(0) == {}

    def test_plan_display_name(self, qapp):
        """产品名称展示（列2）"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "渡鸦级"

    def test_plan_display_runs_and_parallels(self, qapp):
        """流程列展示（列9: parallelsXruns）"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        val = model.data(model.index(0, 9), Qt.ItemDataRole.DisplayRole)
        assert "2X5" in val

    def test_plan_display_margin(self, qapp):
        """市场利润率列展示（列16）"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        val = model.data(model.index(0, 17), Qt.ItemDataRole.DisplayRole)
        assert "20.0%" in str(val)

    def test_plan_status_pending(self, qapp):
        """待生产状态展示（列6）"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        assert model.data(model.index(0, 7), Qt.ItemDataRole.DisplayRole) == "待生产"

    def test_plan_status_in_progress(self, qapp):
        """生产中状态展示（列6）"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        assert model.data(model.index(1, 7), Qt.ItemDataRole.DisplayRole) == "生产中"

    def test_plan_profit_foreground_positive(self, qapp):
        """利润列（15）正值绿色"""
        from ui_pyside6 import theme

        model = PlanTableModel(self.SAMPLE_PLANS)
        color = model.data(model.index(0, 16), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == theme.GREEN

    def test_plan_profit_foreground_negative(self, qapp):
        """利润列（15）负值红色"""
        from ui_pyside6 import theme

        plans = [dict(self.SAMPLE_PLANS[0], profit=-5_000_000)]
        model = PlanTableModel(plans)
        color = model.data(model.index(0, 16), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == theme.RED

    def test_plan_profit_foreground_zero(self, qapp):
        """利润为零时无特殊颜色"""
        plans = [dict(self.SAMPLE_PLANS[0], profit=0)]
        model = PlanTableModel(plans)
        color = model.data(model.index(0, 16), Qt.ItemDataRole.ForegroundRole)
        assert color is None

    def test_set_model_replace(self, qapp):
        """替换模型数据"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        assert model.rowCount() == 2
        new_plans = [self.SAMPLE_PLANS[0]]
        model2 = PlanTableModel(new_plans)
        assert model2.rowCount() == 1

    def test_plan_status_column_headers(self, qapp):
        """状态列表头"""
        model = PlanTableModel([])
        assert model.headerData(7, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "状态"

    def test_plan_icon_column_returns_empty_string(self, qapp):
        """图标列 DisplayRole 返回空字符串"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        val = model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole)
        assert val == ""

    def test_plan_display_char_name_default_dash(self, qapp):
        """角色列（7）无人名时显示横线"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        # 第二个计划有 char_name=""
        val = model.data(model.index(1, 8), Qt.ItemDataRole.DisplayRole)
        assert val == "-"
