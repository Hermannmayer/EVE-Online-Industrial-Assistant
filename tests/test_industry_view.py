"""工业制造视图单元测试 — IndustryPage + init_plan_db

测试覆盖:
  - PLAN_DB_SCHEMA 定义完整性
  - 数据模型操作
  - 筛选（状态 / 类别）不改材料判定与成本指标
"""

from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import Qt

from services.repositories.plan_repository import PlanRepository
from ui_qml.models.industry_models import PlanTableModel
from ui_qml.models.plan_table_constants import COL_MARKET_MARGIN, COL_PROFIT, COL_STATUS
from ui_qml.views.industry_view import IndustryPage

pytestmark = pytest.mark.ui

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
        """市场利润率列展示（列号走常量：加「自制成本/件」后会整体后移）"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        val = model.data(model.index(0, COL_MARKET_MARGIN), Qt.ItemDataRole.DisplayRole)
        assert "20.0%" in str(val)

    def test_plan_status_pending(self, qapp):
        """待生产状态展示（列6）"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        assert model.data(model.index(0, 7), Qt.ItemDataRole.DisplayRole) == "待生产"

    def test_plan_status_in_progress(self, qapp):
        """生产中状态展示（列6）"""
        model = PlanTableModel(self.SAMPLE_PLANS)
        assert model.data(model.index(1, 7), Qt.ItemDataRole.DisplayRole) == "生产中"

    def test_plan_profit_colors_moved_to_qml_model(self, qapp):
        """利润列染色已随阶段 2a 迁到 QML 模型（详见 tests/test_qml_plan_model.py）。

        这里只钉住「旧 delegate 已删除」这一点，防止有人误把它加回来。
        """
        import importlib.util

        assert importlib.util.find_spec("ui_qml.views.industry.plan_table_delegate") is None
        from ui_qml.models.plan_qml_model import PlanQmlModel

        model = PlanQmlModel([dict(self.SAMPLE_PLANS[0], profit=100.0)])
        assert model.data(model.index(0, COL_PROFIT), Qt.ItemDataRole.UserRole + 2) != ""

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


# ══════════════════════════════════════
#  筛选只筛显示行，不改材料/成本判定
# ══════════════════════════════════════


class _PlanLoadHost:
    """承载 `IndustryPage.load_plans` 的最小宿主（不构造整页：本用例不需要 QML/线程）。

    业务方法（`load_plans` / `_visible_rows` / `_annotate_material_status` /
    `_material_fingerprint` / `_material_stock`）**全部从 `IndustryPage` 借** ——
    只把表格以外的两个后台 worker 换成 no-op：它们不是本用例的断言对象，
    真起线程只会拖慢用例。
    """

    load_plans = IndustryPage.load_plans
    _visible_rows = IndustryPage._visible_rows
    _annotate_material_status = IndustryPage._annotate_material_status
    _material_fingerprint = IndustryPage._material_fingerprint
    _material_stock = IndustryPage._material_stock

    def __init__(self, table, filter_key: str, category_key: str = "") -> None:
        self._plan_table_widget = table
        self._bridge = _Bridge(filter_key, category_key)
        self._overdue_checked = True  # 过期补算已跑过，本用例不碰它
        self._refresh_procurement_summary = lambda rows: None
        self._auto_calculate_plans = lambda rows: None
        self._recalc_settings_fp = lambda: ()
        self._loaded_rows: list[dict] = []
        self._mat_fp = None


class _Bridge:
    """`IndustryBridge` 的替身：只提供 `load_plans` 真正会读的那几个取值入口。"""

    def __init__(self, filter_key: str, category_key: str = "") -> None:
        self._filter = filter_key
        self._category = category_key
        self.viewMode = "data"
        self.stats: list[dict] = []

    def current_filter(self) -> str:
        return self._filter

    def current_category(self) -> str:
        return self._category

    def update_stats(self, rows: list[dict]) -> None:
        self.stats = rows


class _FakeScoring:
    """只回答本用例会问的两件事：材料需求 与 「自制成本/件」。"""

    @staticmethod
    def calculate_plan_metrics(plan, char_config=None, **kwargs):
        # 渡鸦级每轮吃 5 个中间件 2003（不再吃其它料）—— 需求全由子线覆盖，
        # 于是「子项行在不在判定集合里」直接决定母项显示「等子项」还是「材料不足」
        if int(plan.get("product_type_id") or 0) == 2001:
            return {"materials": [{"type_id": 2003, "qty": 5, "name": "聚变反应堆"}]}
        return {"materials": []}

    @staticmethod
    def manufacturing_unit_costs(type_ids, **kwargs):
        # 给母项一个非空「自制成本/件」：筛选前后这一列也要一模一样（别退化成 None == None）
        return {2001: 42.5}


def _seed_filter_case(temp_db):
    """母项 2001（待生产）+ 运行中的子项 2003，BOM 见 `_FakeScoring`。

    子项状态取 `in_progress`（不是 pending）：状态筛选「待排」会把它筛掉 ——
    这正是回归要复现的输入（筛选漏掉同组子项 → 母项判定掉档）。
    """
    from services import inventory_manager
    from tests.test_plan_rebuild import _insert_mother

    inventory_manager.init_db()
    repo = PlanRepository(temp_db)
    repo.ensure_table()
    with temp_db.connect("bp") as conn:
        # 中间件 2003 的制造蓝图：每轮产 1（`_pending_children_output_by_type` 读它算子线产出）
        conn.execute("INSERT INTO blueprint_activities VALUES (3003, 'manufacturing', 600)")
        conn.execute("INSERT INTO blueprint_products VALUES (3003, 'manufacturing', 2003, 1)")

    mother = _insert_mother(repo, 2001, runs=1, group=1, mat_hangar_id=1)
    child = _insert_mother(repo, 2003, runs=5, group=1, mat_hangar_id=1)
    repo.update(child, sub_level=1, status="in_progress")
    # 成本/利润率给一组非零值：本用例要证明的正是「筛选不重算它们」，
    # 全零会让这几项的比较恒真（等于没测）
    repo.update(mother, material_cost=1010.0, profit=250.0, market_margin=12.5, personal_margin=8.75)
    return repo, mother, child


def _row_of(model, product_type_id: int) -> int:
    for row in range(model.rowCount()):
        if int(model.get_plan(row).get("product_type_id") or 0) == product_type_id:
            return row
    raise AssertionError(f"表格里没有 product_type_id={product_type_id} 的行")


#: 筛选前后必须一字不差的字段（用户报的「筛选后重算」就是它们跟着变）
_STABLE_FIELDS = (
    "material_waiting",
    "material_status",
    "material_cost",
    "make_cost",
    "profit",
    "market_margin",
    "personal_margin",
)


def test_filter_only_picks_rows_it_does_not_re_judge_materials(temp_db, qapp, monkeypatch):
    """回归：切状态/类别筛选不得改变任何一行的缺料/等子项判定与成本指标。

    缺陷：`load_plans` 原先把筛选串直接喂给 `plan_service.load_plans`，SQL 先按状态
    筛行 → 同组的**运行中**子项不在结果里 → `pending_children_count` 与
    `_pending_children_output_by_type` 都看不到它 → 母项从「等待 1 条子项」掉成
    「材料不足」，连带成本/利润率一起被重算成另一套值（用户报的「筛选后重算」）。

    修法：全量加载 + 标注，筛选只决定**显示哪些行**（`IndustryPage._visible_rows`）。
    """
    from services import inventory_manager, plan_execution, plan_service
    from ui_qml.views.industry.plan_table import PlanTable

    container = SimpleNamespace(
        db=temp_db,
        plan_repo=PlanRepository(temp_db),
        scoring_service=_FakeScoring,
    )
    monkeypatch.setattr(inventory_manager, "_default_db", lambda: temp_db)
    monkeypatch.setattr(plan_service, "get_container", lambda: container)
    monkeypatch.setattr(plan_execution, "_container", lambda: container)
    monkeypatch.setattr("ui_qml.views.industry_view._default_mat_hangar_id", lambda: 1)

    _repo, mother_id, _child_id = _seed_filter_case(temp_db)
    table = PlanTable()

    def load(filter_key: str, category_key: str = "") -> tuple[Any, dict]:
        host = _PlanLoadHost(table, filter_key, category_key)
        # `load_plans` 是从 `IndustryPage` 借来的未绑定函数（替身没有继承它），mypy 会
        # 按 `Callable[[IndustryPage], Any]` 检查 self —— 这里的替身故意只实现用到的那几个成员
        host.load_plans()  # type: ignore[misc]
        model = table.get_model()
        assert model is not None
        rows = [int(model.get_plan(i).get("product_type_id") or 0) for i in range(model.rowCount())]
        view: dict = {"rows": rows, "status_text": None, "fields": None, "plan_id": None}
        if 2001 in rows:
            row = _row_of(model, 2001)
            plan = model.get_plan(row)
            view["status_text"] = model.data(model.index(row, COL_STATUS), Qt.ItemDataRole.DisplayRole)
            view["fields"] = {k: plan.get(k) for k in _STABLE_FIELDS}
            view["plan_id"] = plan.get("id")
        return model, view

    # ── 「全部」：全量判定，母项在等子项 ──
    _model_all, all_view = load("全部")
    assert all_view["plan_id"] == mother_id
    assert all_view["status_text"] == "等待 1 条子项", all_view
    assert sorted(all_view["rows"]) == [2001, 2003], "全部筛选下两条行都要在"

    # ── 「待排」：子项（运行中）被筛掉，但母项的判定与全量一字不差 ──
    _model_pending, pending_view = load("待排")
    assert pending_view["rows"] == [2001], "待排只留待生产的母项（子项在运行中）"
    assert pending_view["status_text"] == all_view["status_text"] == "等待 1 条子项"
    assert pending_view["fields"] == all_view["fields"], "筛选不得重判材料/成本/利润率"

    # ── 类别筛选：与状态筛选正交，且同样不参与判定 ──
    _model_mfg, mfg_view = load("全部", "manufacturing")
    assert sorted(mfg_view["rows"]) == [2001, 2003]
    assert mfg_view["fields"] == all_view["fields"]
    assert load("全部", "reaction")[1]["rows"] == [], "反应筛选下不该有制造行"
    assert load("全部", "research")[1]["rows"] == [], "科研筛选下不该有制造行"
    assert load("待排", "manufacturing")[1]["status_text"] == "等待 1 条子项"

    # 状态栏统计用全量口径（计划总数不随显示筛选变）
    host = _PlanLoadHost(table, "待排")
    host._bridge.stats = None
    host.load_plans()
    assert [int(r["product_type_id"]) for r in host._bridge.stats] == [2001, 2003], (
        "状态栏统计按全量算，不受显示筛选影响"
    )
