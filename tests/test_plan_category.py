"""计划类别推导测试 — services/plan_category.py"""

import pytest
from PySide6.QtCore import Qt

from services.plan_category import category_symbol, load_category_map

pytestmark = pytest.mark.ui


def _build_ref(db_manager):
    with db_manager.connect("ref") as conn:
        conn.execute("CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time INTEGER)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3001,'manufacturing',3600)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3001,'copying',4800)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3002,'manufacturing',3600)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3002,'reaction',1800)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3003,'manufacturing',7200)")
        conn.execute(
            "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER, probability REAL)"
        )
        conn.execute("INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1,NULL)")
        conn.execute("INSERT INTO blueprint_products VALUES (3002,'manufacturing',2002,1,NULL)")
        conn.execute("INSERT INTO blueprint_products VALUES (3003,'manufacturing',2003,1,NULL)")
        # 3001 是发明产物（T2）
        conn.execute("INSERT INTO blueprint_products VALUES (3004,'invention',3001,1,0.3)")
    return db_manager


class TestLoadCategoryMap:
    def test_reaction(self, db_manager):
        _build_ref(db_manager)
        with db_manager.connect("ref") as conn:
            assert load_category_map(conn, [3002]) == {3002: "reaction"}

    def test_invention_t2(self, db_manager):
        _build_ref(db_manager)
        with db_manager.connect("ref") as conn:
            assert load_category_map(conn, [3001]) == {3001: "invention"}

    def test_copying(self, db_manager):
        _build_ref(db_manager)
        with db_manager.connect("ref") as conn:
            # 3005 仅 copying（无 reaction/发明）→ copying
            conn.execute("INSERT INTO blueprint_activities VALUES (3005,'copying',4800)")
            assert load_category_map(conn, [3005]) == {3005: "copying"}

    def test_manufacturable_blueprint_is_not_copying(self, db_manager):
        """能制造 + 能复制 → manufacturing，不是 copying。

        回归用例：EVE 里几乎所有可制造蓝图都能复制，旧实现只看 copying 活动就把普通制造
        蓝图全判成 copying（实测全库 3283 个，而真正「只能复制、不能制造」的只有 70 个），
        再经 capacity_line_for_category 映到科研线 → 制造计划漏进产线小助手的「科研」筛选。
        """
        _build_ref(db_manager)
        with db_manager.connect("ref") as conn:
            conn.execute("INSERT INTO blueprint_activities VALUES (3006,'manufacturing',3600)")
            conn.execute("INSERT INTO blueprint_activities VALUES (3006,'copying',4800)")
            assert load_category_map(conn, [3006]) == {3006: "manufacturing"}

    def test_manufacturing_default(self, db_manager):
        _build_ref(db_manager)
        with db_manager.connect("ref") as conn:
            assert load_category_map(conn, [3003]) == {3003: "manufacturing"}

    def test_priority_reaction_over_invention(self, db_manager):
        _build_ref(db_manager)
        with db_manager.connect("ref") as conn:
            # 3002 既是 reaction 又有 invention 产物 → reaction 优先
            conn.execute("INSERT INTO blueprint_products VALUES (3005,'invention',3002,1,0.5)")
            assert load_category_map(conn, [3002]) == {3002: "reaction"}


class TestSymbolsAndColors:
    def test_symbols(self):
        assert category_symbol("manufacturing") == "⚙"
        assert category_symbol("copying") == "📋"
        assert category_symbol("invention") == "💡"
        assert category_symbol("reaction") == "⚗"


class TestQmlCategoryIcons:
    """QML 侧类别/层级图标的取图路径与列宽。

    阶段 2a 后计划表由 QML 渲染：图标不再是 `QIcon`，而是走
    `image://phosphor/...` 供应器（原始 SVG 的 fill 在根节点上，QML 的 Image
    不会继承给 <path>，必须在取图时注入颜色）。详见 tests/test_qml_plan_model.py。
    """

    def test_category_column_width_fits_header(self):
        """类别列要放得下「类别」两个字，写死 32 会把表头挤成「…」。"""
        from ui_qml.models.plan_table_constants import COL_CATEGORY, FIXED_WIDTHS

        assert FIXED_WIDTHS[COL_CATEGORY] >= 38

    def test_category_icons_available(self, qapp):
        from ui_qml.models.plan_qml_model import PlanQmlModel

        for cat in ("manufacturing", "copying", "invention", "reaction"):
            model = PlanQmlModel([{"category": cat, "product_name": "x"}])
            url = model.data(model.index(0, 1), Qt.ItemDataRole.UserRole + 4)
            assert url.startswith("image://phosphor/"), f"{cat} 应有图标，实得 {url!r}"

    def test_category_icon_unknown_is_empty(self, qapp):
        from ui_qml.models.plan_qml_model import PlanQmlModel

        model = PlanQmlModel([{"category": "not_a_category", "product_name": "x"}])
        assert model.data(model.index(0, 1), Qt.ItemDataRole.UserRole + 4) == ""

    def test_level_icon_available(self, qapp):
        from ui_qml.models.plan_qml_model import PlanQmlModel

        model = PlanQmlModel([{"product_name": "x", "child_level": 1}])
        url = model.data(model.index(0, 3), Qt.ItemDataRole.UserRole + 4)
        assert "caret-right" in url
