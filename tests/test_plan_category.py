"""计划类别推导测试 — services/plan_category.py"""

from services.plan_category import category_symbol, load_category_map


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


class TestDelegateIcons:
    """计划表格 delegate 的类别/层级自绘图标与列宽。"""

    def test_category_column_fixed_width(self):
        from ui_pyside6.views.industry.plan_table_constants import COL_CATEGORY, FIXED_WIDTHS

        assert FIXED_WIDTHS[COL_CATEGORY] == 32

    def test_category_icons_available(self, qapp):
        from PySide6.QtGui import QIcon

        from ui_pyside6.views.industry.plan_table_delegate import _category_icon

        for cat in ("manufacturing", "copying", "invention", "reaction"):
            icon = _category_icon(cat)
            assert isinstance(icon, QIcon)
            assert not icon.isNull(), f"{cat} 图标应为空"

    def test_category_icon_unknown_returns_none(self, qapp):
        from ui_pyside6.views.industry.plan_table_delegate import _category_icon

        assert _category_icon("not_a_category") is None

    def test_level_icon_available(self, qapp):
        from PySide6.QtGui import QIcon

        from ui_pyside6.views.industry.plan_table_delegate import _level_icon

        icon = _level_icon()
        assert isinstance(icon, QIcon)
        assert not icon.isNull()
