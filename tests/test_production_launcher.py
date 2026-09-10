"""产线启动小助手 UI 冒烟测试（slow，--quick 时跳过）。"""

import pytest
from PySide6.QtCore import Qt

import services.plan_execution as plan_execution

pytestmark = pytest.mark.ui

SAMPLE_PLANS = [
    {
        "id": 1,
        "product_type_id": 2001,
        "product_name": "渡鸦级",
        "blueprint_type_id": 3001,
        "status": "pending",
        "char_name": "甲",
        "category": "manufacturing",
        "group_id": 0,
        "child_level": 0,
        "runs": 1,
        "parallels": 1,
        "calculated_time": 3600,
        "mat_hangar_id": 1,
        "facility": "仓库A",
        "output_hangar": "仓库B",
        "has_image": True,
        "assigned_blueprint_id": None,
        "material_cost": 12345,
    },
    {
        "id": 2,
        "product_type_id": 2002,
        "product_name": "无人机",
        "blueprint_type_id": 3002,
        "status": "pending",
        "char_name": "甲",
        "category": "copying",
        "group_id": 0,
        "child_level": 0,
        "runs": 2,
        "parallels": 3,
        "calculated_time": 600,
        "mat_hangar_id": 1,
        "facility": "仓库A",
        "output_hangar": "",
        "has_image": True,
        "assigned_blueprint_id": None,
        "material_cost": 999,
    },
    {
        "id": 3,
        "product_type_id": 2001,
        "product_name": "母项成品",
        "blueprint_type_id": 3001,
        "status": "pending",
        "char_name": "乙",
        "category": "manufacturing",
        "group_id": 10,
        "child_level": 0,
        "runs": 1,
        "parallels": 1,
        "calculated_time": 3600,
        "mat_hangar_id": 1,
        "facility": "仓库A",
        "output_hangar": "仓库B",
        "has_image": True,
        "assigned_blueprint_id": None,
        "material_cost": 100,
    },
    {
        "id": 4,
        "product_type_id": 2002,
        "product_name": "子项材料",
        "blueprint_type_id": 3002,
        "status": "pending",
        "char_name": "乙",
        "category": "manufacturing",
        "group_id": 10,
        "child_level": 1,
        "runs": 1,
        "parallels": 1,
        "calculated_time": 600,
        "mat_hangar_id": 1,
        "facility": "仓库A",
        "output_hangar": "",
        "has_image": True,
        "assigned_blueprint_id": None,
        "material_cost": 50,
    },
]


def _make_launcher(qapp, monkeypatch, chars=("甲", "乙")):
    from ui_pyside6.views.industry import production_launcher as pl

    chars = list(chars)
    monkeypatch.setattr(plan_execution, "expire_overdue_plans", lambda: 0)
    # 必须接受 **kwargs：`_shortfall_count` 会传 stock=…；签名不匹配会抛 TypeError，
    # 又被那里的 except 静默吞掉 → 缺口恒为 0，新用例会「假通过」。
    monkeypatch.setattr(plan_execution, "check_materials", lambda plan, mat, **kw: [])
    monkeypatch.setattr(plan_execution, "output_per_run", lambda tid: 1)
    monkeypatch.setattr(plan_execution, "start_plan", lambda *a, **k: {"ok": True, "message": "ok"})
    monkeypatch.setattr(pl, "load_plans_for_wizard", lambda: SAMPLE_PLANS)
    monkeypatch.setattr(pl, "load_item_icon", lambda tid, size=None: None)
    monkeypatch.setattr(pl, "get_character_list", lambda: list(chars))
    monkeypatch.setattr(
        pl,
        "load_all_data",
        lambda: {
            "current": chars[0],
            "characters": {
                name: {
                    "skills": {
                        "高级量产技术": 5,
                        "批量生产学": 5,
                        "高级实验室运作理论": 5,
                        "科学网络学": 5,
                        "大规模反应理论": 5,
                        "高级大规模反应理论": 5,
                    }
                }
                for name in chars
            },
        },
    )
    monkeypatch.setattr("services.inventory_manager.get_default_mat_hangar_and_system", lambda: (None, None))
    monkeypatch.setattr(
        "services.ui_data_service.get_item_names_batch",
        lambda ids, db=None: {i: f"蓝图{i}" for i in ids},
    )

    w = pl.ProductionLauncher()
    w._tick_timer.stop()
    w._poll_timer.stop()
    return w, pl


class TestProductionLauncher:
    def test_constructs_and_builds_rows(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            assert w._list.count() == 4  # 全部计划
            assert len(w._widgets) == 4
            # 占用区渲染了 甲/乙 两行
            assert w._occ_layout.count() >= 2
        finally:
            w.close()

    def test_group_parent_first(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            # 组 10：母项 id=3 在前，子项 id=4 在后；独立计划 1/2 殿后
            ids = [w._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w._list.count())]
            assert ids == [3, 4, 1, 2], ids
            # 母项有未完成子项 → 折叠按钮（含子项数）
            parent_row = w._widgets[3]
            assert parent_row._btn_toggle.isHidden() is False
            assert "折叠(1)" in parent_row._btn_toggle.text()
        finally:
            w.close()

    def test_collapse_toggle(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            # 折叠组 10 → 子项 id=4 隐藏
            w._on_row_toggle(10)
            ids = [w._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w._list.count())]
            assert ids == [3, 1, 2], ids
            parent_row = w._widgets[3]
            assert "展开(1)" in parent_row._btn_toggle.text()
            # 再次展开 → 子项恢复
            w._on_row_toggle(10)
            ids = [w._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w._list.count())]
            assert ids == [3, 4, 1, 2], ids
        finally:
            w.close()

    def test_startable_row_has_button(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            row = w._widgets[1]  # pending + 有图 + 无机库缺口 → 可启动
            assert row._btn_start.isHidden() is False
            assert row._btn_toggle.isHidden() is True
        finally:
            w.close()

    def test_blocked_row_shows_reason_affordance(self, qapp, monkeypatch):
        """被阻塞的行不再留空：给出可见的 ? 入口，tooltip 即阻塞原因。"""
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            monkeypatch.setattr(w, "_block_reason", lambda plan: "生产中" if plan.get("id") == 2 else None)
            w._sync_rows(w._visible_plans)
            row = w._widgets[2]
            assert row._btn_start.isHidden() is True
            assert row._btn_toggle.isHidden() is True
            assert row._btn_blocked.isHidden() is False
            assert row._btn_blocked.toolTip() == "生产中"
        finally:
            w.close()

    def test_action_slot_width_is_uniform(self, qapp, monkeypatch):
        """三种按钮共用同一槽位宽度，避免行动作区左右跳动，且折叠文案不被截断。"""
        from PySide6.QtGui import QFontMetrics

        w, pl = _make_launcher(qapp, monkeypatch)
        try:
            row = w._widgets[1]
            widths = {row._btn_start.minimumWidth(), row._btn_toggle.minimumWidth(), row._btn_blocked.minimumWidth()}
            assert len(widths) == 1, widths
            slot = widths.pop()
            fm = QFontMetrics(row._btn_toggle.font())
            assert slot >= fm.horizontalAdvance("折叠(99)") + 2 * pl._GAP_MD
            # 槽位宽度必须按最宽文案（折叠/展开）取值，不能只按「启动」取值
            assert slot > fm.horizontalAdvance("启动") + 2 * pl._GAP_MD
            # 跨行一致
            assert w._widgets[2]._action_slot_w == row._action_slot_w
        finally:
            w.close()

    def test_toolbar_is_single_row_without_duplicate_title(self, qapp, monkeypatch):
        """工具条是 QFrame（QSS 才能命中 #launcher_toolbar），且不再重复窗口标题。"""
        from PySide6.QtWidgets import QFrame, QLabel

        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            assert isinstance(w._toolbar, QFrame)
            for child in (w._line_filter, w._char_filter, w._pin_btn, w._filter_summary):
                assert child.parent() is w._toolbar, child
            assert "产线启动小助手" not in [lbl.text() for lbl in w.findChildren(QLabel)]
        finally:
            w.close()

    def test_filter_summary_indicates_active_filter(self, qapp, monkeypatch):
        """筛选激活时用户能看出数据已被过滤。"""
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            assert w._filter_summary.text() == "共 4 条"
            w._char_filter.setCurrentIndex(w._char_filter.findData("甲"))
            assert w._filter_summary.text() == "已筛选 2/4"
        finally:
            w.close()

    def test_bottom_is_compact_without_selection(self, qapp, monkeypatch):
        """未选中时底部为紧凑单行，不再露出全宽空下拉。"""
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            assert w._detail_panel.isHidden() is True
            assert w._executor_combo.isHidden() is True
            assert w._bottom_hint.isHidden() is False
            assert w._feedback.isHidden() is True
            w._list.setCurrentRow(1)
            assert w._detail_panel.isHidden() is False
            assert w._executor_combo.isHidden() is False
            assert w._bottom_hint.isHidden() is True
        finally:
            w.close()

    def test_occupancy_height_capped_at_four_rows(self, qapp, monkeypatch):
        """角色多于 4 个时占用区内部滚动，不撑高顶部把列表挤扁。"""
        w, pl = _make_launcher(qapp, monkeypatch, chars=[f"角色{i}" for i in range(7)])
        try:
            assert len(w.findChildren(pl.CapacitySlotBar)) == 7
            per_row = w._occ_layout.spacing() + pl.CapacitySlotBar.row_height()
            assert w._occ_scroll.maximumHeight() == pl._MAX_OCC_ROWS * per_row + 2
            # 折叠后高度归零
            w._on_occ_toggle()
            assert w._occ_scroll.maximumHeight() == 0
            w._on_occ_toggle()
            assert w._occ_scroll.maximumHeight() > 0
        finally:
            w.close()

    def test_copy_blueprint_writes_clipboard(self, qapp, monkeypatch):
        """复制蓝图名进剪贴板（原向导测试删除后由本例接管该覆盖）。"""
        from types import SimpleNamespace

        from PySide6.QtWidgets import QApplication

        w, pl = _make_launcher(qapp, monkeypatch)
        try:
            monkeypatch.setattr(pl, "get_container", lambda: SimpleNamespace(db=None))
            monkeypatch.setattr(
                "services.ui_data_service.resolve_plan_blueprint_name",
                lambda plan, db=None: "渡鸦级蓝图",
            )
            w._copy_blueprint(1)
            assert QApplication.clipboard().text() == "渡鸦级蓝图"
            assert w._feedback.isHidden() is False
            assert "渡鸦级蓝图" in w._feedback.text()

            # 无蓝图信息 → 给反馈而不是静默
            monkeypatch.setattr(
                "services.ui_data_service.resolve_plan_blueprint_name",
                lambda plan, db=None: None,
            )
            w._copy_blueprint(1)
            assert w._feedback.text() == "该计划无蓝图信息"
        finally:
            w.close()

    def test_launcher_qss_colors_come_from_theme_only(self, qapp):
        """本窗样式表的每个颜色都必须来自当前主题调色板（配色铁律）。

        QSS 里的 hex 是 `theme.*` token 插值的结果，所以不能断言「没有 hex」；
        正确的不变量是：出现的 hex 全部属于当前主题的颜色集合。
        """
        import re

        import ui_pyside6.theme as theme
        from ui_pyside6.views.industry.production_launcher import _launcher_qss

        qss = _launcher_qss()
        used = set(re.findall(r"#[0-9a-fA-F]{6}(?![0-9a-fA-F])", qss))
        spec = theme.current_theme_spec()
        allowed = set(spec["colors"].values()) if spec else set()
        assert used <= allowed, f"QSS 中出现了非主题色：{used - allowed}"
        assert used, "QSS 未取到任何主题色"

    def test_module_source_has_no_hardcoded_color(self, qapp):
        """源码里不得出现硬编码 hex 颜色字面量（配色铁律）。"""
        import re
        from pathlib import Path

        from ui_pyside6.views.industry import production_launcher as pl

        src = Path(pl.__file__).read_text(encoding="utf-8")
        found = re.findall(r"#[0-9a-fA-F]{6}(?![0-9a-fA-F])", src)
        assert not found, f"源码中出现硬编码颜色：{found}"

    def test_line_filter(self, qapp, monkeypatch):
        """线型筛选按蓝图类别过滤（对齐游戏作业类型）；copying 不再被并进科研。

        SAMPLE_PLANS：id 1/3/4 = manufacturing，id 2 = copying。
        用 findText 而非 findData —— 下拉 data 是 frozenset，Qt 的 findData 匹配不了。
        """
        from services.terminology import term

        w, _ = _make_launcher(qapp, monkeypatch)
        try:

            def shown():
                return [w._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w._list.count())]

            assert sorted(shown()) == [1, 2, 3, 4]  # 默认「全部」

            w._line_filter.setCurrentIndex(w._line_filter.findText(term.activity("copying")))
            assert shown() == [2]

            w._line_filter.setCurrentIndex(w._line_filter.findText(term.activity("manufacturing")))
            assert sorted(shown()) == [1, 3, 4]
        finally:
            w.close()

    def test_line_filter_invention_absorbs_research(self, qapp, monkeypatch):
        """「发明」项收纳 invention / 材料效率研究 / 生产效率研究 三类。

        后两类在本应用建不出计划（`production_plans` 无 activity 字段，取数链路全写死
        manufacturing），独立成项会恒空，故并入「发明」。
        """
        from services.terminology import term

        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            idx = w._line_filter.findText(term.activity("invention"))
            assert idx >= 0, "下拉里应有「发明」项"
            assert w._line_filter.itemData(idx) == frozenset({"invention", "research_material", "research_time"})

            w._line_filter.setCurrentIndex(idx)
            for cat in ("invention", "research_material", "research_time"):
                assert w._match_filters({"category": cat}), cat
            assert not w._match_filters({"category": "manufacturing"})
            assert not w._match_filters({"category": "copying"})
        finally:
            w.close()

    def test_line_filter_items_match_game_activities(self, qapp, monkeypatch):
        """下拉项名走术语中心（CCP 官方中文），且与游戏作业类型一一对应。"""
        from services.terminology import term

        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            labels = [w._line_filter.itemText(i) for i in range(w._line_filter.count())]
            assert labels == [
                "全部",
                term.activity("manufacturing"),
                term.activity("copying"),
                term.activity("invention"),
                term.activity("reaction"),
            ]
            assert w._line_filter.itemData(0) is None
        finally:
            w.close()

    def test_char_filter(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            idx = w._char_filter.findData("甲")
            w._char_filter.setCurrentIndex(idx)
            ids = [w._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w._list.count())]
            assert ids == [1, 2]
        finally:
            w.close()

    def test_selection_updates_bottom(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            # 可见顺序 [3(母项), 4, 1, 2]；选索引 2 = 计划 1（可启动）
            w._list.setCurrentRow(2)
            assert w._main_btn.isHidden() is False
            # 按钮只放动作与数量；产品名放在可换行的摘要行 + tooltip，
            # 否则长产品名会把按钮撑爆、挤掉执行人物下拉
            assert w._main_btn.text() == "启动 x 1"
            assert "渡鸦级" in w._main_btn.toolTip()
            assert "渡鸦级" in w._params_label.text()
        finally:
            w.close()

    def test_start_calls_plan_execution(self, qapp, monkeypatch):
        import services.plan_execution as plan_execution

        w, _ = _make_launcher(qapp, monkeypatch)
        calls = []

        def fake_start(plan, *, mat_hangar_id, char_name, **kw):
            calls.append((plan.get("id"), char_name))
            return {"ok": True, "message": "ok"}

        monkeypatch.setattr(plan_execution, "start_plan", fake_start)
        try:
            w._start(1)
            assert calls == [(1, "甲")]  # 默认执行人物 = 计划人物甲
        finally:
            w.close()

    def test_close_stops_timers(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        w._tick_timer.start()
        w._poll_timer.start()
        w.close()
        assert w._tick_timer.isActive() is False
        assert w._poll_timer.isActive() is False

    def test_reopen_restarts_timers(self, qapp, monkeypatch):
        """回归：closeEvent 停表后不会自动恢复，单实例复用时重开必须重启定时器。

        否则「关闭再打开」得到的是不刷新倒计时/计划列表的死窗口。
        """
        w, _ = _make_launcher(qapp, monkeypatch)
        w._tick_timer.start()
        w._poll_timer.start()
        w.close()
        assert w._tick_timer.isActive() is False

        w.show()
        qapp.processEvents()
        assert w._tick_timer.isActive() is True
        assert w._poll_timer.isActive() is True
        w.close()


class TestCapacitySlotBar:
    """占用条几何自适应。

    回归点：旧版在 paintEvent 里按固定 x=544 绘制状态文字，控件被 QScrollArea
    压缩到该宽度以下时「空闲」被裁掉。
    """

    USAGE = {"manufacturing": (1, 5), "research": (0, 5), "reaction": (0, 0)}

    def _bar(self, name_width: int = 76):
        from ui_pyside6.views.industry.production_launcher import CapacitySlotBar

        bar = CapacitySlotBar(name_width=name_width)
        bar.set_usage("新角色5", self.USAGE)
        return bar

    def test_size_hint_positive_and_ordered(self, qapp):
        bar = self._bar()
        assert bar.sizeHint().width() > 0
        assert bar.minimumSizeHint().width() > 0
        assert bar.minimumSizeHint().width() < bar.sizeHint().width()

    def test_minimum_width_reserves_status_text_and_blocks(self, qapp):
        from PySide6.QtGui import QFontMetrics

        bar = self._bar()
        # 必须用控件自身字体量宽 —— 自绘与量宽用同一字体（套用全局样式表后 QFont() 会分叉）
        status_w = QFontMetrics(bar.font()).horizontalAdvance(bar._status_text()[0])
        blocks = 3 * 11 * 6  # 3 条线 × 11 格 × (最小块宽 4 + 最小间距 2)
        assert bar.minimumSizeHint().width() >= status_w + blocks

    def test_renders_at_minimum_width(self, qapp):
        bar = self._bar()
        bar.resize(bar.minimumSizeHint().width(), bar.minimumHeight())
        assert not bar.grab().isNull()

    def test_longer_name_widens_hint(self, qapp):
        assert self._bar(name_width=160).sizeHint().width() > self._bar(name_width=60).sizeHint().width()

    def test_status_text_reflects_usage(self, qapp):
        from ui_pyside6.views.industry.production_launcher import CapacitySlotBar

        cases = [
            ({"manufacturing": (0, 5), "research": (0, 5), "reaction": (0, 0)}, "空闲"),
            ({"manufacturing": (2, 5), "research": (0, 5), "reaction": (0, 0)}, "生产中"),
            # 超员按三条线求和判定：12 > 5+5+0
            ({"manufacturing": (9, 5), "research": (3, 5), "reaction": (0, 0)}, "超员"),
        ]
        for usage, expected in cases:
            bar = CapacitySlotBar()
            bar.set_usage("甲", usage)
            assert bar._status_text()[0].startswith(expected), usage

    def test_window_is_wide_enough_for_occupancy(self, qapp, monkeypatch):
        """默认窗宽必须容得下占用条，否则状态文字又会被裁。"""
        w, pl = _make_launcher(qapp, monkeypatch)
        try:
            bars = w.findChildren(pl.CapacitySlotBar)
            assert bars
            widest = max(b.sizeHint().width() for b in bars)
            assert w.width() >= min(widest, 1100)
        finally:
            w.close()


class TestForceStartOnShortfall:
    """缺料是唯一阻塞时，行上应给「启动」而非问号（与计划表格同口径）。"""

    @staticmethod
    def _shortfall(plan, mat, **kw):
        return [{"type_id": 1001, "name": "三钛合金", "need": 10, "owned": 0, "missing": 10}]

    def test_shortfall_row_shows_start_button(self, qapp, monkeypatch):
        from services import plan_execution

        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            monkeypatch.setattr(plan_execution, "check_materials", self._shortfall)
            w._shortfall_cache.clear()
            w._stock_cache.clear()
            w._stock_fp.clear()
            w._on_poll()
            row = w._widgets[1]  # SAMPLE_PLANS id=1：pending 制造计划
            assert not row._btn_start.isHidden(), "缺料可强制时应给启动按钮"
            assert row._btn_blocked.isHidden()
        finally:
            w.close()

    def test_non_material_block_still_question(self, qapp, monkeypatch):
        """缺料之外还有阻塞（这里用无可用蓝图）→ 仍然只是问号。"""
        from services import plan_execution

        w, pl = _make_launcher(qapp, monkeypatch)
        try:
            plans = [dict(p) for p in SAMPLE_PLANS]  # 深拷贝，别污染模块级夹具
            for p in plans:
                if p["id"] == 1:
                    p["has_image"] = False
                    p["assigned_blueprint_id"] = None
            monkeypatch.setattr(pl, "load_plans_for_wizard", lambda: plans)
            monkeypatch.setattr(plan_execution, "check_materials", self._shortfall)
            w._shortfall_cache.clear()
            w._stock_cache.clear()
            w._stock_fp.clear()
            w._on_poll()
            row = w._widgets[1]
            assert row._btn_start.isHidden()
            assert not row._btn_blocked.isHidden()
        finally:
            w.close()

    def test_stock_change_invalidates_shortfall_cache(self, qapp, monkeypatch):
        """库存补齐后必须重算缺口 —— 缓存指纹含库存，不再永远停在旧值。"""
        from services import plan_execution

        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            calls: list[dict | None] = []

            def _check(plan, mat, stock=None, **kw):
                calls.append(stock)
                return [] if stock and stock.get(1001) else self._shortfall(plan, mat)

            monkeypatch.setattr(plan_execution, "check_materials", _check)
            monkeypatch.setattr("services.inventory_manager.get_hangar_stock", lambda hid: {1001: 0, 1002: 0})
            w._shortfall_cache.clear()
            w._stock_cache.clear()
            w._stock_fp.clear()
            w._on_poll()
            assert w._shortfall_count({"id": 1, "status": "pending", "mat_hangar_id": 1}) == 1

            # 材料补齐 → 下一轮轮询必须重算（旧实现指纹里没有库存，永远返回 1）
            monkeypatch.setattr("services.inventory_manager.get_hangar_stock", lambda hid: {1001: 999, 1002: 999})
            w._stock_cache.clear()
            w._stock_fp.clear()
            assert w._shortfall_count({"id": 1, "status": "pending", "mat_hangar_id": 1}) == 0
        finally:
            w.close()
