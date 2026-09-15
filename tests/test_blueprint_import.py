"""蓝图粘贴导入 — 解析/比对/应用 逻辑测试（对齐材料导入流程）。

纯逻辑用例不标 ui，纳入 validate 档；只有真正需要 QApplication 的对话框用例
标 ``ui``。
"""

from types import SimpleNamespace

import pytest

from ui_qml.workers.blueprint_import_worker import (
    apply_blueprint_diff,
    build_blueprint_changes,
    parse_blueprint_clipboard,
    snapshot_blueprints,
)


def _ref_cursor(db_manager):
    """构造含 item / blueprint_products 的 ref 库连接，返回 cursor

    item 带 group 名（蓝图判定依据 `en_group_name`/`zh_group_name` 后缀）。
    """
    conn = db_manager.connect("ref").__enter__()
    conn.execute(
        "CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT, "
        "zh_group_name TEXT, en_group_name TEXT)"
    )
    conn.execute("INSERT INTO item VALUES (3001,'渡鸦级蓝图','Raven Blueprint','战列舰蓝图','Battleship Blueprint')")
    conn.execute("INSERT INTO item VALUES (2001,'渡鸦级','Raven','战列舰','Battleship')")
    conn.execute("INSERT INTO item VALUES (3002,'聚合反应公式','Polymer Formula','反应公式','Reaction Formula')")
    conn.execute(
        "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
        "product_type_id INTEGER, quantity INTEGER)"
    )
    conn.execute("INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1)")
    conn.execute("INSERT INTO blueprint_products VALUES (3002,'reaction',2002,1)")
    conn.commit()
    return conn.cursor()


class TestParseBlueprintClipboard:
    def test_parses_blueprint_lines(self, db_manager):
        """标准剪贴板行：蓝图名\tME\tTE\t流程\t类型 → 解析出属性"""
        conn = _ref_cursor(db_manager)
        raw = "渡鸦级蓝图\t0\t0\t1\t原图\n渡鸦级蓝图\t5\t2\t3\t拷贝\n"
        result, filtered, unresolved = parse_blueprint_clipboard(raw, conn)
        assert (filtered, unresolved) == (0, 0)
        assert len(result) == 2
        r0 = result[0]
        assert r0["blueprint_type_id"] == 3001
        assert r0["is_bpo"] is True
        # 原图的流程数列在游戏里就是 -1，归一后落成 0
        assert (r0["me"], r0["te"], r0["runs"]) == (0, 0, 0)
        assert r0["qty"] == 1
        r1 = result[1]
        assert r1["is_bpo"] is False
        assert (r1["me"], r1["te"], r1["runs"]) == (5, 2, 3)

    def test_duplicates_aggregated(self, db_manager):
        """同属性多行 → qty 合并"""
        conn = _ref_cursor(db_manager)
        raw = "渡鸦级蓝图\t5\t2\t3\t拷贝\n渡鸦级蓝图\t5\t2\t3\t拷贝\n渡鸦级蓝图\t5\t2\t3\t拷贝\n"
        result, _, _ = parse_blueprint_clipboard(raw, conn)
        assert len(result) == 1
        assert result[0]["qty"] == 3

    def test_negative_runs_promoted_to_bpo(self, db_manager):
        """流程数 -1 → 原图（英文客户端判词失配时的兜底），runs 归一为 0"""
        conn = _ref_cursor(db_manager)
        result, _, _ = parse_blueprint_clipboard("渡鸦级蓝图\t10\t20\t-1\t拷贝\n", conn)
        assert len(result) == 1
        assert result[0]["is_bpo"] is True
        assert result[0]["runs"] == 0

    def test_english_original_marker_accepted(self, db_manager):
        """英文客户端：Original 也判为原图（只认中文会把原图记成拷贝）"""
        conn = _ref_cursor(db_manager)
        result, _, _ = parse_blueprint_clipboard("Raven Blueprint\t10\t20\t1\tOriginal\n", conn)
        assert len(result) == 1
        assert result[0]["is_bpo"] is True

    def test_reaction_formula_parsed(self, db_manager):
        """反应公式是蓝图仓库的正式成员，必须能解析（否则全量同步会误删它）"""
        conn = _ref_cursor(db_manager)
        result, filtered, unresolved = parse_blueprint_clipboard("聚合反应公式\t0\t0\t200\t拷贝\n", conn)
        assert (filtered, unresolved) == (0, 0)
        assert [r["blueprint_type_id"] for r in result] == [3002]

    def test_material_line_filtered(self, db_manager):
        """材料/产物行（精确命中非蓝图物品）→ 按材料过滤并计数，不再反查成蓝图"""
        conn = _ref_cursor(db_manager)
        result, filtered, unresolved = parse_blueprint_clipboard("渡鸦级\t0\t0\t1\t原图\n", conn)
        assert result == []
        assert (filtered, unresolved) == (1, 0)

    def test_mixed_lines_count_materials(self, db_manager):
        """混合剪贴板：蓝图行保留，材料行过滤并计数"""
        conn = _ref_cursor(db_manager)
        raw = "渡鸦级蓝图\t0\t0\t1\t原图\n渡鸦级\t1000\t0\t3\t材料\n"
        result, filtered, _ = parse_blueprint_clipboard(raw, conn)
        assert filtered == 1
        assert [r["blueprint_type_id"] for r in result] == [3001]

    def test_unresolved_blueprint_lines_counted(self, db_manager):
        """结构完整、不是材料、但认不出蓝图 → 计入 unresolved（不再静默丢弃）"""
        conn = _ref_cursor(db_manager)
        raw = "查无此级蓝图\t0\t0\t1\t原图\n渡鸦级蓝图\t0\t0\t1\t原图\n"
        result, filtered, unresolved = parse_blueprint_clipboard(raw, conn)
        assert filtered == 0
        assert unresolved == 1
        assert [r["blueprint_type_id"] for r in result] == [3001]

    def test_invalid_lines_skipped(self, db_manager):
        """不足 5 列 / 非数字 ME / 空行 → 跳过，不计入过滤数也不计入未识别数"""
        conn = _ref_cursor(db_manager)
        raw = "渡鸦级蓝图\t0\t0\n未知物品\tx\t0\t1\t原图\n\n"
        result, filtered, unresolved = parse_blueprint_clipboard(raw, conn)
        assert result == []
        assert (filtered, unresolved) == (0, 0)


class TestBuildBlueprintChanges:
    def test_increase_decrease_detected(self):
        """前→后数量对比 → 只返回变化行，含属性文本"""
        before = {(3001, True, 0, 0): (2, (0, 0)), (3002, False, 5, 2): (1, (3,))}
        after = {(3001, True, 0, 0): (4, (0, 0, 0, 0)), (3002, False, 5, 2): (0, ())}
        names = {3001: "渡鸦级蓝图", 3002: "无人机蓝图"}
        changes = build_blueprint_changes(before, after, names)
        assert len(changes) == 2
        inc = next(c for c in changes if c["qty_delta"] > 0)
        assert inc["qty_delta"] == 2
        assert inc["attr"] == "原图  ME0  TE0"
        dec = next(c for c in changes if c["qty_delta"] < 0)
        assert dec["qty_delta"] == -1

    def test_runs_change_detected_without_count_change(self):
        """张数不变但流程数变了（BPC 被消耗）→ 仍应出现在变动汇总里"""
        before = {(3002, False, 10, 20): (1, (4000,))}
        after = {(3002, False, 10, 20): (1, (2996,))}
        changes = build_blueprint_changes(before, after, {3002: "无人机蓝图"})
        assert len(changes) == 1
        assert changes[0]["qty_delta"] == 0
        assert changes[0]["attr"] == "拷贝  ME10  TE20  流程2996"

    def test_unchanged_filtered(self):
        """无变化行不返回"""
        before = {(3001, True, 0, 0): (3, (0, 0, 0))}
        after = {(3001, True, 0, 0): (3, (0, 0, 0))}
        assert build_blueprint_changes(before, after, {}) == []


class TestSnapshotBlueprints:
    def test_counts_quantity_not_rows(self, monkeypatch):
        """quantity>1 的合并行按张数计（下线产出会把同规格 BPC 并成一行）"""
        monkeypatch.setattr(
            "services.inventory_manager.get_blueprints",
            lambda hangar_id=None: [
                {
                    "blueprint_type_id": 3002,
                    "is_bpo": False,
                    "me_level": 10,
                    "te_level": 20,
                    "runs": 2996,
                    "quantity": 3,
                    "notes": "",
                },
            ],
        )
        snap = snapshot_blueprints(1)
        assert snap == {(3002, False, 10, 20): (3, (2996, 2996, 2996))}

    def test_groups_by_spec_ignoring_runs(self, monkeypatch):
        """流程数不同的同规格行合成一组（流程数是行内属性，不进组键）"""
        monkeypatch.setattr(
            "services.inventory_manager.get_blueprints",
            lambda hangar_id=None: [
                {
                    "blueprint_type_id": 3002,
                    "is_bpo": False,
                    "me_level": 10,
                    "te_level": 20,
                    "runs": 2996,
                    "quantity": 1,
                    "notes": "",
                },
                {
                    "blueprint_type_id": 3002,
                    "is_bpo": False,
                    "me_level": 10,
                    "te_level": 20,
                    "runs": 1004,
                    "quantity": 1,
                    "notes": "",
                },
                {
                    "blueprint_type_id": 3002,
                    "is_bpo": True,
                    "me_level": 10,
                    "te_level": 20,
                    "runs": 0,
                    "quantity": 1,
                    "notes": "",
                },
            ],
        )
        snap = snapshot_blueprints(1)
        assert snap[(3002, False, 10, 20)] == (2, (1004, 2996))
        assert snap[(3002, True, 10, 20)] == (1, (0,))


class TestApplyBlueprintDiff:
    def _user_conn(self, db_manager):
        with db_manager.connect("user") as conn:
            conn.execute(
                "CREATE TABLE user_blueprints (id INTEGER PRIMARY KEY AUTOINCREMENT, hangar_id INTEGER, "
                "blueprint_type_id INTEGER, is_bpo INTEGER, me_level INTEGER, te_level INTEGER, "
                "runs INTEGER, quantity INTEGER, notes TEXT DEFAULT '')"
            )
        return db_manager

    def _patch(self, monkeypatch, db_manager):
        monkeypatch.setattr(
            "ui_qml.workers.blueprint_import_worker.get_container",
            lambda: SimpleNamespace(db=db_manager),
        )

    @staticmethod
    def _diff(existing_rows, clip_runs, *, is_bpo=True, me=0, te=0, target_qty=None) -> list[dict]:
        return [
            {
                "blueprint_type_id": 3001,
                "is_bpo": is_bpo,
                "me": me,
                "te": te,
                "clip_runs": list(clip_runs),
                "existing_rows": existing_rows,
                "qty": len(clip_runs),
                "existing_qty": sum(max(int(r.get("quantity") or 1), 0) for r in existing_rows),
                "target_qty": len(clip_runs) if target_qty is None else target_qty,
            }
        ]

    @staticmethod
    def _row(row_id: int, runs: int = 0, quantity: int = 1, notes: str = "") -> dict:
        return {"id": row_id, "runs": runs, "quantity": quantity, "notes": notes}

    def test_full_mode_add_and_remove(self, db_manager, monkeypatch):
        """全量：target 增加 → 新增差额；target 减少 → 删除多余"""
        db_manager = self._user_conn(db_manager)
        with db_manager.connect("user") as conn:
            for _ in range(3):
                conn.execute(
                    "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity)"
                    " VALUES (1, 3001, 1, 0, 0, 0, 1)"
                )
        self._patch(monkeypatch, db_manager)

        added, removed, blocked = apply_blueprint_diff(self._diff([self._row(i) for i in (1, 2, 3)], [0] * 5), 1)
        assert (added, removed, blocked) == (2, 0, 0)

        with db_manager.connect("user") as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM user_blueprints").fetchone()[0]
            assert cnt == 5

    def test_incremental_mode_add_only(self, db_manager, monkeypatch):
        """增量：只加不减（按现有 + 剪贴板）"""
        db_manager = self._user_conn(db_manager)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity)"
                " VALUES (1, 3001, 1, 0, 0, 0, 1)"
            )
        self._patch(monkeypatch, db_manager)

        added, removed, blocked = apply_blueprint_diff(
            self._diff([self._row(1)], [0, 0], target_qty=0), 1, mode="incremental"
        )
        assert (added, removed, blocked) == (2, 0, 0)

        with db_manager.connect("user") as conn:
            assert conn.execute("SELECT COUNT(*) FROM user_blueprints").fetchone()[0] == 3

    def test_full_mode_zero_target_removes_all(self, db_manager, monkeypatch):
        """全量：target=0 → 全部删除"""
        db_manager = self._user_conn(db_manager)
        with db_manager.connect("user") as conn:
            for _ in range(2):
                conn.execute(
                    "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity)"
                    " VALUES (1, 3001, 1, 0, 0, 0, 1)"
                )
        self._patch(monkeypatch, db_manager)

        added, removed, blocked = apply_blueprint_diff(self._diff([self._row(1), self._row(2)], [], target_qty=0), 1)
        assert (added, removed, blocked) == (0, 2, 0)
        with db_manager.connect("user") as conn:
            assert conn.execute("SELECT COUNT(*) FROM user_blueprints").fetchone()[0] == 0

    def test_runs_change_updates_in_place_keeping_id_and_notes(self, db_manager, monkeypatch):
        """流程数变化 → 原地更新，保住行 id 与备注（旧实现会删旧行插新行）"""
        db_manager = self._user_conn(db_manager)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity, notes)"
                " VALUES (1, 3001, 0, 10, 20, 4000, 1, '主力图')"
            )
        self._patch(monkeypatch, db_manager)

        added, removed, blocked = apply_blueprint_diff(
            self._diff([self._row(1, runs=4000, notes="主力图")], [2996], is_bpo=False, me=10, te=20), 1
        )
        assert (added, removed, blocked) == (0, 0, 0)

        with db_manager.connect("user") as conn:
            row = conn.execute("SELECT id, runs, notes FROM user_blueprints").fetchone()
        assert tuple(row) == (1, 2996, "主力图")

    def test_quantity_block_not_inflated(self, db_manager, monkeypatch):
        """库中 1 行 quantity=3、剪贴板 3 张同规格 → 无增删（按张数而非行数计）"""
        db_manager = self._user_conn(db_manager)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity)"
                " VALUES (1, 3001, 0, 10, 20, 2996, 3)"
            )
        self._patch(monkeypatch, db_manager)

        added, removed, blocked = apply_blueprint_diff(
            self._diff([self._row(1, runs=2996, quantity=3)], [2996, 2996, 2996], is_bpo=False, me=10, te=20), 1
        )
        assert (added, removed, blocked) == (0, 0, 0)
        with db_manager.connect("user") as conn:
            assert conn.execute("SELECT quantity FROM user_blueprints").fetchone()[0] == 3

    def test_quantity_shrinks_without_deleting_row(self, db_manager, monkeypatch):
        """容量用不完只缩减张数，绝不整行删除"""
        db_manager = self._user_conn(db_manager)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity)"
                " VALUES (1, 3001, 0, 10, 20, 2996, 3)"
            )
        self._patch(monkeypatch, db_manager)

        added, removed, blocked = apply_blueprint_diff(
            self._diff([self._row(1, runs=2996, quantity=3)], [2996, 2996], is_bpo=False, me=10, te=20), 1
        )
        assert (added, removed, blocked) == (0, 0, 0)
        with db_manager.connect("user") as conn:
            rows = conn.execute("SELECT id, quantity FROM user_blueprints").fetchall()
        assert [tuple(r) for r in rows] == [(1, 2)]

    def test_occupied_rows_are_not_deleted(self, db_manager, monkeypatch):
        """被活跃计划占用的蓝图拒绝删除（删它会静默解除计划绑定）"""
        db_manager = self._user_conn(db_manager)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity)"
                " VALUES (1, 3001, 1, 0, 0, 0, 1)"
            )
            conn.execute(
                "CREATE TABLE production_plans (id INTEGER PRIMARY KEY, status TEXT, assigned_blueprint_id INTEGER)"
            )
            conn.execute("CREATE TABLE plan_blueprint_bindings (plan_id INTEGER, blueprint_id INTEGER)")
            conn.execute("INSERT INTO production_plans VALUES (7, 'ready', NULL)")
            conn.execute("INSERT INTO plan_blueprint_bindings VALUES (7, 1)")
        self._patch(monkeypatch, db_manager)

        added, removed, blocked = apply_blueprint_diff(self._diff([self._row(1)], [], target_qty=0), 1)
        assert (added, removed, blocked) == (0, 0, 1)
        with db_manager.connect("user") as conn:
            assert conn.execute("SELECT COUNT(*) FROM user_blueprints").fetchone()[0] == 1

    def test_paste_twice_is_noop(self, db_manager, monkeypatch):
        """同一份剪贴板连粘两次：第二次零增删（幂等）。"""
        db_manager = self._user_conn(db_manager)
        self._patch(monkeypatch, db_manager)

        diff = self._diff([], [0, 0])
        assert apply_blueprint_diff(diff, 1)[:2] == (2, 0)

        with db_manager.connect("user") as conn:
            rows = [
                self._row(r[0], runs=r[1], quantity=r[2])
                for r in conn.execute("SELECT id, runs, quantity FROM user_blueprints ORDER BY id")
            ]
        assert apply_blueprint_diff(self._diff(rows, [0, 0]), 1) == (0, 0, 0)


class TestBlueprintImportChangeDialog:
    @pytest.mark.ui
    def test_build_summary_counts(self):
        """汇总文案：增量/减量行数 + 新增/删除条数。

        判定函数已随对话框迁到 `ui_qml.bridge.blueprint_import_bridge`（阶段 4b）：
        从 Widgets 类的静态方法变成模块级纯函数，**逻辑一字未改**，断言值保持原样。
        """
        from ui_qml.bridge.blueprint_import_bridge import build_summary

        changes = [
            {"name": "A", "attr": "原图  ME0  TE0", "qty_before": 1, "qty_after": 3, "qty_delta": 2},
            {"name": "B", "attr": "拷贝  ME5  TE0  流程1", "qty_before": 2, "qty_after": 0, "qty_delta": -2},
        ]
        summary = build_summary(changes, added=3, removed=1)
        assert "2 项变化" in summary
        assert "增加 1" in summary
        assert "减少 1" in summary
        assert "新增 3 张" in summary
        assert "删除 1 张" in summary

    @pytest.mark.ui
    def test_build_summary_empty_changes(self):
        """无属性变化 → 只报新增/删除条数"""
        from ui_qml.bridge.blueprint_import_bridge import build_summary

        summary = build_summary([], added=2, removed=0)
        assert "新增 2 条" in summary

    @pytest.mark.ui
    def test_dialog_renders(self, qapp):
        """对话框可构建：3 列，行内容正确（QML 版断言桥的行数据）"""
        from ui_qml.bridge.blueprint_import_bridge import BlueprintImportChangeQmlDialog

        changes = [
            {"name": "渡鸦级蓝图", "attr": "原图  ME0  TE0", "qty_before": 1, "qty_after": 2, "qty_delta": 1},
        ]
        dlg = BlueprintImportChangeQmlDialog(changes, added=1, removed=0, hangar_name="测试机库")
        try:
            assert dlg.bridge.rowCount == 1
            assert [c["text"] for c in dlg.bridge.rows[0]["cells"]] == ["渡鸦级蓝图", "原图  ME0  TE0", "1 → 2"]
        finally:
            dlg.deleteLater()
