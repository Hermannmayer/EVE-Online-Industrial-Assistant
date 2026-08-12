"""蓝图粘贴导入 — 解析/比对/应用 纯函数测试（对齐材料导入流程）"""

from types import SimpleNamespace

from ui_pyside6.views.inventory.blueprint_import_worker import (
    apply_blueprint_diff,
    build_blueprint_changes,
    parse_blueprint_clipboard,
)


def _ref_cursor(db_manager):
    """构造含 item / blueprint_products 的 ref 库连接，返回 cursor"""
    conn = db_manager.connect("ref").__enter__()
    conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT)")
    conn.execute("INSERT INTO item VALUES (3001,'渡鸦级蓝图','Raven Blueprint')")
    conn.execute("INSERT INTO item VALUES (2001,'渡鸦级','Raven')")
    conn.execute(
        "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
        "product_type_id INTEGER, quantity INTEGER)"
    )
    conn.execute("INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1)")
    conn.commit()
    return conn.cursor()


class TestParseBlueprintClipboard:
    def test_parses_blueprint_lines(self, db_manager):
        """标准剪贴板行：蓝图名\tME\tTE\t流程\t类型 → 解析出属性"""
        conn = _ref_cursor(db_manager)
        raw = "渡鸦级蓝图\t0\t0\t1\t原图\n渡鸦级蓝图\t5\t2\t3\t拷贝\n"
        result = parse_blueprint_clipboard(raw, conn)
        assert len(result) == 2
        r0 = result[0]
        assert r0["blueprint_type_id"] == 3001
        assert r0["is_bpo"] is True
        assert (r0["me"], r0["te"], r0["runs"]) == (0, 0, 1)
        assert r0["qty"] == 1
        r1 = result[1]
        assert r1["is_bpo"] is False
        assert (r1["me"], r1["te"], r1["runs"]) == (5, 2, 3)

    def test_duplicates_aggregated(self, db_manager):
        """同属性多行 → qty 合并"""
        conn = _ref_cursor(db_manager)
        raw = "渡鸦级蓝图\t0\t0\t1\t拷贝\n渡鸦级蓝图\t0\t0\t1\t拷贝\n渡鸦级蓝图\t0\t0\t1\t拷贝\n"
        result = parse_blueprint_clipboard(raw, conn)
        assert len(result) == 1
        assert result[0]["qty"] == 3

    def test_product_name_reverse_lookup(self, db_manager):
        """产物名 → 反查制造蓝图（蓝图名缺失时）"""
        conn = _ref_cursor(db_manager)
        raw = "渡鸦级\t0\t0\t1\t原图\n"
        result = parse_blueprint_clipboard(raw, conn)
        assert len(result) == 1
        assert result[0]["blueprint_type_id"] == 3001

    def test_invalid_lines_skipped(self, db_manager):
        """不足 5 列 / 非数字 ME / 未知名称 → 跳过"""
        conn = _ref_cursor(db_manager)
        raw = "渡鸦级蓝图\t0\t0\n未知物品\tx\t0\t1\t原图\n\n"
        result = parse_blueprint_clipboard(raw, conn)
        assert result == []


class TestBuildBlueprintChanges:
    def test_increase_decrease_detected(self):
        """前→后数量对比 → 只返回变化行，含属性文本"""
        before = {(3001, True, 0, 0, 1): 2, (3002, False, 5, 2, 3): 1}
        after = {(3001, True, 0, 0, 1): 4, (3002, False, 5, 2, 3): 0}
        names = {3001: "渡鸦级蓝图", 3002: "无人机蓝图"}
        changes = build_blueprint_changes(before, after, names)
        assert len(changes) == 2
        inc = next(c for c in changes if c["qty_delta"] > 0)
        assert inc["qty_delta"] == 2
        assert inc["attr"] == "原图  ME0  TE0  流程1"
        dec = next(c for c in changes if c["qty_delta"] < 0)
        assert dec["qty_delta"] == -1

    def test_unchanged_filtered(self):
        """无变化行不返回"""
        before = {(3001, True, 0, 0, 1): 3}
        after = {(3001, True, 0, 0, 1): 3}
        assert build_blueprint_changes(before, after, {}) == []


class TestApplyBlueprintDiff:
    def _user_conn(self, db_manager):
        with db_manager.connect("user") as conn:
            conn.execute(
                "CREATE TABLE user_blueprints (id INTEGER PRIMARY KEY AUTOINCREMENT, hangar_id INTEGER, "
                "blueprint_type_id INTEGER, is_bpo INTEGER, me_level INTEGER, te_level INTEGER, "
                "runs INTEGER, quantity INTEGER, notes TEXT DEFAULT '')"
            )
        return db_manager

    def test_full_mode_add_and_remove(self, db_manager, monkeypatch):
        """全量：target 增加 → 新增差额；target 减少 → 删除多余"""
        db_manager = self._user_conn(db_manager)
        with db_manager.connect("user") as conn:
            for _ in range(3):
                conn.execute(
                    "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity)"
                    " VALUES (1, 3001, 1, 0, 0, 1, 1)"
                )

        monkeypatch.setattr(
            "ui_pyside6.views.inventory.blueprint_import_worker.get_container",
            lambda: SimpleNamespace(db=db_manager),
        )

        diff_rows = [
            {
                "blueprint_type_id": 3001,
                "is_bpo": True,
                "me": 0,
                "te": 0,
                "runs": 1,
                "qty": 5,
                "target_qty": 5,
                "row_ids": [1, 2, 3],
            },
            {
                "blueprint_type_id": 3002,
                "is_bpo": False,
                "me": 1,
                "te": 0,
                "runs": 1,
                "qty": 0,
                "target_qty": 0,
                "row_ids": [],
            },
        ]
        added, removed = apply_blueprint_diff(diff_rows, 1)
        assert added == 2  # 3 → 5
        assert removed == 0

        with db_manager.connect("user") as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM user_blueprints").fetchone()[0]
            assert cnt == 5

    def test_incremental_mode_add_only(self, db_manager, monkeypatch):
        """增量：只加不减（target 被忽略，按现有+剪贴板）"""
        db_manager = self._user_conn(db_manager)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity)"
                " VALUES (1, 3001, 1, 0, 0, 1, 1)"
            )

        monkeypatch.setattr(
            "ui_pyside6.views.inventory.blueprint_import_worker.get_container",
            lambda: SimpleNamespace(db=db_manager),
        )

        diff_rows = [
            {
                "blueprint_type_id": 3001,
                "is_bpo": True,
                "me": 0,
                "te": 0,
                "runs": 1,
                "qty": 2,
                "target_qty": 0,  # 增量模式忽略 target
                "row_ids": [1],
            }
        ]
        added, removed = apply_blueprint_diff(diff_rows, 1, mode="incremental")
        assert added == 2  # 现有 1 + 剪贴板 2 = 3（新增 2）
        assert removed == 0

        with db_manager.connect("user") as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM user_blueprints").fetchone()[0]
            assert cnt == 3

    def test_full_mode_zero_target_removes_all(self, db_manager, monkeypatch):
        """全量：target=0 → 全部删除"""
        db_manager = self._user_conn(db_manager)
        with db_manager.connect("user") as conn:
            for _ in range(2):
                conn.execute(
                    "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity)"
                    " VALUES (1, 3001, 1, 0, 0, 1, 1)"
                )

        monkeypatch.setattr(
            "ui_pyside6.views.inventory.blueprint_import_worker.get_container",
            lambda: SimpleNamespace(db=db_manager),
        )

        diff_rows = [
            {
                "blueprint_type_id": 3001,
                "is_bpo": True,
                "me": 0,
                "te": 0,
                "runs": 1,
                "qty": 0,
                "target_qty": 0,
                "row_ids": [1, 2],
            }
        ]
        added, removed = apply_blueprint_diff(diff_rows, 1)
        assert added == 0
        assert removed == 2

        with db_manager.connect("user") as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM user_blueprints").fetchone()[0]
            assert cnt == 0


class TestBlueprintImportChangeDialog:
    def test_build_summary_counts(self):
        """汇总文案：增量/减量行数 + 新增/删除条数"""

        from ui_pyside6.views.inventory.blueprint_import_dialog import BlueprintImportChangeDialog

        changes = [
            {"name": "A", "attr": "原图  ME0  TE0  流程1", "qty_before": 1, "qty_after": 3, "qty_delta": 2},
            {"name": "B", "attr": "拷贝  ME5  TE0  流程1", "qty_before": 2, "qty_after": 0, "qty_delta": -2},
        ]
        summary = BlueprintImportChangeDialog._build_summary(changes, added=3, removed=1)
        assert "2 项变化" in summary
        assert "增加 1" in summary
        assert "减少 1" in summary
        assert "新增 3 张" in summary
        assert "删除 1 张" in summary

    def test_build_summary_empty_changes(self):
        """无属性变化 → 只报新增/删除条数"""
        from ui_pyside6.views.inventory.blueprint_import_dialog import BlueprintImportChangeDialog

        summary = BlueprintImportChangeDialog._build_summary([], added=2, removed=0)
        assert "新增 2 条" in summary

    def test_dialog_renders(self, qapp):
        """对话框可构建：表头 3 列，行内容正确"""

        from ui_pyside6.views.inventory.blueprint_import_dialog import BlueprintImportChangeDialog

        changes = [
            {"name": "渡鸦级蓝图", "attr": "原图  ME0  TE0  流程1", "qty_before": 1, "qty_after": 2, "qty_delta": 1},
        ]
        dlg = BlueprintImportChangeDialog(changes, added=1, removed=0, hangar_name="测试机库")
        assert dlg._table.rowCount() == 1
        assert dlg._table.item(0, 0).text() == "渡鸦级蓝图"
        assert dlg._table.item(0, 1).text() == "原图  ME0  TE0  流程1"
        assert dlg._table.item(0, 2).text() == "1 → 2"
