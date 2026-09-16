"""产线启动小助手测试。

阶段 2c 起整窗由 QML 渲染（L1–L4），本文件改为断言**视图模型**：
`ProductionLauncher` 把每行/每个占用条算成 dict 交给桥，QML 只负责画。
原先断言 `PlanRow._btn_start.isHidden()` 这类控件状态的地方，现在断言
`row["actionKind"] / row["actionText"] / row["actionTip"]` —— 判据仍在 Python 侧，
所以覆盖没有减少，只是观察点从控件换成了数据。
"""

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject

import services.plan_execution as plan_execution
from tests.clipboard_wait import wait_for_clipboard
from tests.qml_click import press_move_release, spin

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


def _plan(plan_id: int, *, status: str = "pending", name: str = "渡鸦级", **extra) -> dict:
    """单条计划夹具 —— 与 SAMPLE_PLANS 同形状，便于按场景构造最小列表。"""
    base = {
        "id": plan_id,
        "product_type_id": 2001,
        "product_name": name,
        "blueprint_type_id": 3001,
        "status": status,
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
        "material_cost": 100,
    }
    base.update(extra)
    return base


READY_PLAN = _plan(101, status="ready", name="待下线成品")
RUNNING_PLAN = _plan(102, status="in_progress", name="生产中成品")
# 跨 ≥2 个母项引用 → 被 group_and_sort_plans 提到合成「共享组件」根节点下
SHARED_CHILD_PLAN = _plan(103, name="共享子件", child_level=1, source_mother_ids="1,2")


# ── 视图模型访问器（取代对 QML 控件内部状态的断言） ──────────────


def _ids(w) -> list[int]:
    """列表当前展示的计划 id（顺序 = 界面顺序）。"""
    return [int(r["id"]) for r in w.row_view_models()]


def _root(w):
    """`press_move_release` 要的那个「既能 `findChild` 又能 `mapToItem` 的根」。

    批次 7.4 起根元素是 `Window`（不再是 `Item`），它没有 `rootObject()`；而窗口的
    `contentItem()` 也当不了这个根 —— 根是 `Window` 时，**声明出来的顶层 Item 的
    QObject 父是窗口本身**，`parentItem` 才是 `contentItem`，于是从 `contentItem()`
    往下 `findChild` 一个都找不到。所以落到列表区这个真正的 Item 祖先上
    （它的场景坐标会被 `mapToItem` 往返抵消，取哪一层都一样准）。
    """
    from PySide6.QtQuick import QQuickItem

    root = w._window.findChild(QQuickItem, "listArea")
    assert root is not None, "LauncherWindow.qml 里找不到 objectName=listArea 的列表区"
    return root


def _row(w, plan_id: int) -> dict:
    """按计划 id 取行视图模型。"""
    hit: dict | None = next((r for r in w.row_view_models() if int(r["id"]) == plan_id), None)
    assert hit is not None, f"列表里没有计划 {plan_id}，现有 {_ids(w)}"
    return hit


def _make_launcher(qapp, monkeypatch, chars=("甲", "乙"), plans=None):
    from ui_qml.views.industry import production_launcher as pl

    chars = list(chars)
    rows = SAMPLE_PLANS if plans is None else plans
    monkeypatch.setattr(plan_execution, "expire_overdue_plans", lambda: 0)
    # 必须接受 **kwargs：`_shortfall_count` 会传 stock=…；签名不匹配会抛 TypeError，
    # 又被那里的 except 静默吞掉 → 缺口恒为 0，新用例会「假通过」。
    monkeypatch.setattr(plan_execution, "check_materials", lambda plan, mat, **kw: [])
    monkeypatch.setattr(plan_execution, "output_per_run", lambda tid: 1)
    monkeypatch.setattr(plan_execution, "start_plan", lambda *a, **k: {"ok": True, "message": "ok"})
    monkeypatch.setattr(pl, "load_plans_for_wizard", lambda: rows)
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
            assert w._window is not None and _root(w) is not None, "LauncherWindow.qml 加载失败"
            assert len(w.row_view_models()) == 4  # 全部计划
            # 占用区渲染了 甲/乙 两行
            assert len(w.occupancy_rows()) >= 2
        finally:
            w.close()

    def test_group_parent_first(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            # 组 10：母项 id=3 在前，子项 id=4 在后；独立计划 1/2 殿后
            assert _ids(w) == [3, 4, 1, 2]
            # 母项有未完成子项 → 折叠按钮（含子项数）
            parent = _row(w, 3)
            assert parent["actionKind"] == "toggle"
            assert "折叠(1)" in parent["actionText"]
        finally:
            w.close()

    def test_collapse_toggle(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            # 折叠组 10 → 子项 id=4 隐藏
            w._on_row_toggle(10)
            assert _ids(w) == [3, 1, 2]
            assert "展开(1)" in _row(w, 3)["actionText"]
            # 再次展开 → 子项恢复
            w._on_row_toggle(10)
            assert _ids(w) == [3, 4, 1, 2]
        finally:
            w.close()

    def test_startable_row_has_button(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            # pending + 有图 + 无机库缺口 → 可启动
            assert _row(w, 1)["actionKind"] == "start"
            assert _row(w, 1)["actionText"] == "启动"
        finally:
            w.close()

    def test_blocked_row_shows_short_label_and_full_reason(self, qapp, monkeypatch):
        """被阻塞的行不留空、也不再显示「?」：动作槽是短标签，完整原因进 tooltip。"""
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            monkeypatch.setattr(
                w,
                "_block_state",
                lambda plan: ("children_running", "子项产线运行中") if plan.get("id") == 2 else (None, None),
            )
            w._sync_rows(w._visible_plans)
            row = _row(w, 2)
            assert row["actionKind"] == "blocked"
            assert row["actionText"] == "子项运行中"
            assert row["actionTip"] == "子项产线运行中"
        finally:
            w.close()

    def test_action_slot_width_fits_every_label(self, qapp, monkeypatch):
        """动作槽宽度固定，且必须容得下**所有可能文案**（否则最长的那条会被截断）。"""
        from PySide6.QtGui import QFont, QFontMetrics

        import ui_qml.theme.registry as theme

        w, pl = _make_launcher(qapp, monkeypatch)
        try:
            slot = w.action_slot_width()
            font = QFont(theme.FONT_FAMILY)
            font.setPixelSize(theme.fs(pl._FS_BODY))
            fm = QFontMetrics(font)
            for sample in pl._SLOT_SAMPLES:
                assert slot >= fm.horizontalAdvance(sample) + 2 * pl._GAP_MD, sample
            assert slot >= pl._SLOT_MIN_W
        finally:
            w.close()

    def test_filter_summary_indicates_active_filter(self, qapp, monkeypatch):
        """筛选激活时用户能看出数据已被过滤。"""
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            assert w.filter_summary_text() == "共 4 条"
            w.set_char_filter_index(2)  # [全部人物, 未分配, 甲, 乙]
            assert w.filter_summary_text() == "已筛选 2/4"
        finally:
            w.close()

    def test_bottom_is_compact_without_selection(self, qapp, monkeypatch):
        """未选中时底部为紧凑单行，不再露出全宽空下拉。"""
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            assert w.bottom_expanded() is False
            assert w.main_button_visible() is False
            assert w.feedback_text() == ""
            assert w.bottom_hint_text()

            w.select_plan(1)
            assert w.bottom_expanded() is True
        finally:
            w.close()

    def test_occupancy_collapse_toggle(self, qapp, monkeypatch):
        """占用区可折叠；角色多于 4 个时由 QML 侧限高内部滚动。"""
        w, _ = _make_launcher(qapp, monkeypatch, chars=[f"角色{i}" for i in range(7)])
        try:
            assert len(w.occupancy_rows()) == 7
            assert w.occupancy_collapsed() is False
            w.toggle_occupancy()
            assert w.occupancy_collapsed() is True
            w.toggle_occupancy()
            assert w.occupancy_collapsed() is False
        finally:
            w.close()

    def test_copy_blueprint_writes_clipboard(self, qapp, monkeypatch):
        """复制蓝图名进剪贴板（原向导测试删除后由本例接管该覆盖）。"""
        from types import SimpleNamespace

        w, pl = _make_launcher(qapp, monkeypatch)
        try:
            monkeypatch.setattr(pl, "get_container", lambda: SimpleNamespace(db=None))
            monkeypatch.setattr(
                "services.ui_data_service.resolve_plan_blueprint_name",
                lambda plan, db=None: "渡鸦级蓝图",
            )
            w._copy_blueprint(1)
            assert wait_for_clipboard("渡鸦级蓝图") == "渡鸦级蓝图"
            assert "渡鸦级蓝图" in w.feedback_text()

            # 无蓝图信息 → 给反馈而不是静默
            monkeypatch.setattr(
                "services.ui_data_service.resolve_plan_blueprint_name",
                lambda plan, db=None: None,
            )
            w._copy_blueprint(1)
            assert w.feedback_text() == "该计划无蓝图信息"
        finally:
            w.close()

    def test_module_source_has_no_hardcoded_color(self, qapp):
        """源码里不得出现硬编码 hex 颜色字面量（配色铁律）。

        本窗原来的 `_launcher_qss()` 已随阶段 2c 删除（整窗改由 QML 渲染），
        配色改由 `FCapacityRow` / `LauncherWindow.qml` 从 `Theme` 取；
        QML 侧的同类护栏见 `test_qml_theme_bridge.test_qml_only_references_existing_theme_tokens`。
        """
        import re
        from pathlib import Path

        from ui_qml.views.industry import production_launcher as pl

        src = Path(pl.__file__).read_text(encoding="utf-8")
        found = re.findall(r"#[0-9a-fA-F]{6}(?![0-9a-fA-F])", src)
        assert not found, f"源码中出现硬编码颜色：{found}"

    def test_line_filter(self, qapp, monkeypatch):
        """线型筛选按蓝图类别过滤（对齐游戏作业类型）；copying 不再被并进科研。

        SAMPLE_PLANS：id 1/3/4 = manufacturing，id 2 = copying。
        """
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            assert sorted(_ids(w)) == [1, 2, 3, 4]  # 默认「全部」

            w.set_line_filter_index(2)  # [全部, 制造, 拷贝, 发明, 反应]
            assert _ids(w) == [2]

            w.set_line_filter_index(1)
            assert sorted(_ids(w)) == [1, 3, 4]
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
            labels = [o["label"] for o in w.line_filter_options()]
            assert term.activity("invention") in labels

            w.set_line_filter_index(3)  # 「发明」
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
            labels = [o["label"] for o in w.line_filter_options()]
            assert labels == [
                "全部",
                term.activity("manufacturing"),
                term.activity("copying"),
                term.activity("invention"),
                term.activity("reaction"),
            ]
            assert w.line_filter_options()[0]["value"] is None
        finally:
            w.close()

    def test_char_filter(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            w.set_char_filter_index(2)  # 甲
            assert _ids(w) == [1, 2]
        finally:
            w.close()

    def test_selection_updates_bottom(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            w.select_plan(1)  # 可启动
            assert w.main_button_visible() is True
            # 按钮只放动作与数量；产品名放在可换行的摘要行 + tooltip，
            # 否则长产品名会把按钮撑爆、挤掉执行人物下拉
            assert w.main_button_text() == "启动 x 1"
            assert "渡鸦级" in w.main_button_tip()
            assert "渡鸦级" in w.params_text()
        finally:
            w.close()

    def test_start_calls_plan_execution(self, qapp, monkeypatch):
        import services.plan_execution as plan_execution
        from ui_qml.views.industry import production_launcher as pl

        w, _ = _make_launcher(qapp, monkeypatch)
        calls = []

        def fake_start(plan, *, mat_hangar_id, char_name, **kw):
            calls.append((plan.get("id"), char_name))
            return {"ok": True, "message": "ok"}

        monkeypatch.setattr(plan_execution, "start_plan", fake_start)
        # 容量判定读真实人物配置（同套件别的用例会改它）→ 钉死，避免弹模态超员确认框
        monkeypatch.setattr(pl, "max_lines_for_category", lambda *a, **k: 99)
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


class TestCharStatus:
    """占用条状态文案：超员 / 空闲 / 生产中。

    阶段 2c 前这段逻辑在 `CapacitySlotBar._status_text()`（自绘控件）里，
    现在搬到 `ProductionLauncher._char_status()` 供 QML 直接画。

    （原先同类的**几何**用例 —— sizeHint / 最小宽度 / 窗口够宽 —— 已删除：
    占用条改由 QML 的 `FCapacityRow` 布局，「按固定 x 画状态文字被裁掉」那类
    回归在布局系统下结构上不存在。）
    """

    def test_status_text_reflects_usage(self, qapp):
        from ui_qml.views.industry.production_launcher import ProductionLauncher

        cases = [
            ({"manufacturing": (0, 5), "research": (0, 5), "reaction": (0, 0)}, "空闲"),
            ({"manufacturing": (2, 5), "research": (0, 5), "reaction": (0, 0)}, "生产中"),
            # 超员按三条线求和判定：12 > 5+5+0
            ({"manufacturing": (9, 5), "research": (3, 5), "reaction": (0, 0)}, "超员"),
        ]
        for usage, expected in cases:
            assert ProductionLauncher._char_status(usage)[0].startswith(expected), usage


class TestForceStartOnShortfall:
    """缺料是唯一阻塞时，行上应给「启动」而非问号（与计划表格同口径）。"""

    @staticmethod
    def _shortfall(plan, mat, **kw):
        return [{"type_id": 1001, "name": "三钛合金", "need": 10, "owned": 0, "missing": 10}]

    def test_shortfall_row_shows_start_button(self, qapp, monkeypatch):
        from services import plan_execution

        w, _pl = _make_launcher(qapp, monkeypatch)
        try:
            monkeypatch.setattr(plan_execution, "check_materials", self._shortfall)
            w._shortfall_cache.clear()
            w._stock_cache.clear()
            w._stock_fp.clear()
            w._on_poll()
            row = _row(w, 1)  # SAMPLE_PLANS id=1：pending 制造计划
            assert row["actionKind"] == "start", "缺料可强制时应给启动按钮"
            # 按钮文字直接说明堵点，而不是含糊的「启动」
            assert row["actionText"] == "材料不够"
            assert "材料不足" in row["actionTip"]
        finally:
            w.close()

    def test_start_button_text_and_tooltip_cleared_when_unblocked(self, qapp, monkeypatch):
        """缺料补齐后同一行会被原地复用 —— 短标签文字与 tooltip 都必须复位。

        旧实现在可启动分支只 `show()`，既不重设文本也不清 tooltip，于是行上会
        残留上一轮的「材料不够」与强制启动提示。
        """
        from services import plan_execution

        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            short = True

            def _check(plan, mat, **kw):
                return self._shortfall(plan, mat) if short else []

            monkeypatch.setattr(plan_execution, "check_materials", _check)
            w._shortfall_cache.clear()
            w._stock_cache.clear()
            w._stock_fp.clear()
            w._on_poll()
            assert _row(w, 1)["actionText"] == "材料不够"

            short = False
            w._shortfall_cache.clear()
            w._stock_cache.clear()
            w._stock_fp.clear()
            w._on_poll()
            row = _row(w, 1)
            assert row["actionText"] == "启动"
            assert row["actionTip"] == ""
        finally:
            w.close()

    @staticmethod
    def _no_shortfall(plan, mat, **kw):
        return []

    def test_missing_blueprint_shows_short_label(self, qapp, monkeypatch):
        """硬阻塞（拷贝未绑输入蓝图）→ 动作槽显示「缺蓝图」，完整原因进 tooltip。

        这里用**拷贝作业**：制造计划在未绑蓝图时按「不绑也能启动」的宽松语义算就绪，
        拷贝/研究则必须有输入蓝图（见 services.plan_job_kinds），所以换 activity 才拦得住。
        """
        from services import plan_execution

        w, pl = _make_launcher(qapp, monkeypatch)
        try:
            plans = [dict(p) for p in SAMPLE_PLANS]  # 深拷贝，别污染模块级夹具
            for p in plans:
                if p["id"] == 1:
                    p["activity"] = "copying"
                    p["has_image"] = False
                    p["assigned_blueprint_id"] = None
            monkeypatch.setattr(pl, "load_plans_for_wizard", lambda: plans)
            monkeypatch.setattr(plan_execution, "check_materials", self._no_shortfall)
            w._shortfall_cache.clear()
            w._stock_cache.clear()
            w._stock_fp.clear()
            w._on_poll()
            row = _row(w, 1)
            assert row["actionKind"] == "blocked"
            assert row["actionText"] == "缺蓝图"
            assert "蓝图原本" in row["actionTip"]
        finally:
            w.close()

    def test_soft_shortfall_with_hard_block_keeps_material_label(self, qapp, monkeypatch):
        """缺料 + 另有硬阻塞：动作槽仍显示「材料不够」。

        这是**刻意接受**的口径：`plan_start_block` 按固定顺序先报缺料，短标签与
        tooltip 同源（tooltip 也写「材料不足 N 种」），不会自相矛盾。只是把材料补齐
        并不能解锁该行——真正的门要等下一轮轮询才会显形。改判定顺序会动到
        `plan_start_block_reason` 被测试冻结的文案，代价更大。
        """
        from services import plan_execution

        w, pl = _make_launcher(qapp, monkeypatch)
        try:
            plans = [dict(p) for p in SAMPLE_PLANS]
            for p in plans:
                if p["id"] == 1:
                    p["activity"] = "copying"
                    p["has_image"] = False
                    p["assigned_blueprint_id"] = None
            monkeypatch.setattr(pl, "load_plans_for_wizard", lambda: plans)
            monkeypatch.setattr(plan_execution, "check_materials", self._shortfall)
            w._shortfall_cache.clear()
            w._stock_cache.clear()
            w._stock_fp.clear()
            w._on_poll()
            row = _row(w, 1)
            # 不可强制（蓝图是硬阻塞）→ 不是启动按钮
            assert row["actionKind"] == "blocked"
            assert row["actionText"] == "材料不够"
            assert "材料不足" in row["actionTip"]
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


class TestActionSlotStates:
    """动作槽直接显示真实状态：可下线的行给按钮，其余给短标签，不再出现「?」。"""

    def test_ready_row_shows_complete_button(self, qapp, monkeypatch):
        w, pl = _make_launcher(qapp, monkeypatch, plans=[dict(READY_PLAN)])
        try:
            row = _row(w, 101)
            assert row["actionKind"] == "complete"
            assert row["actionText"] == pl._COMPLETE_LABEL == "可下线"
            assert "入库" in row["actionTip"]
        finally:
            w.close()

    def test_ready_row_complete_runs_flow_and_keeps_feedback(self, qapp, monkeypatch):
        """点「可下线」→ 走共用的单行下线；成功后行会消失，提示不得被刷新擦掉。"""
        from ui_qml.views.industry import complete_plans_dialog as cpd

        rows = [dict(READY_PLAN)]
        w, _ = _make_launcher(qapp, monkeypatch, plans=rows)
        try:
            seen: list = []

            def _complete(parent, plan):
                rows.clear()  # 模拟库里已 completed → 下一轮轮询不再出现该行
                seen.append(plan)
                return {"completed": 1}

            monkeypatch.setattr(cpd, "complete_one_plan", _complete)
            emitted: list = []
            w.plans_changed.connect(lambda: emitted.append(True))

            w._on_row_complete(101)

            assert [p["id"] for p in seen] == [101]
            assert emitted == [True]
            # 紧凑态文案真的被刷新了（只设 _hint_text 不重渲染等于没提示）
            assert w.bottom_hint_text() == "已下线：待下线成品"
        finally:
            w.close()

    def test_ready_row_complete_cancel_is_noop(self, qapp, monkeypatch):
        from ui_qml.views.industry import complete_plans_dialog as cpd

        w, _ = _make_launcher(qapp, monkeypatch, plans=[dict(READY_PLAN)])
        try:
            monkeypatch.setattr(cpd, "complete_one_plan", lambda parent, plan: None)
            emitted: list = []
            w.plans_changed.connect(lambda: emitted.append(True))
            hint_before = w.bottom_hint_text()

            w._on_row_complete(101)

            assert emitted == []
            assert w.bottom_hint_text() == hint_before
        finally:
            w.close()

    def test_complete_hint_mentions_child_cleanup(self, qapp, monkeypatch):
        """母项下线顺带清理了子项行时，紧凑态提示要说明，否则用户只看到行凭空少了几条。"""
        from ui_qml.views.industry import complete_plans_dialog as cpd

        rows = [dict(READY_PLAN)]
        w, _ = _make_launcher(qapp, monkeypatch, plans=rows)
        try:

            def _complete(parent, plan):
                rows.clear()
                return {"completed": 1, "removed": 2}

            monkeypatch.setattr(cpd, "complete_one_plan", _complete)

            w._on_row_complete(101)

            assert w._hint_text == "已下线：待下线成品（子项产线已清理）"
            assert w.bottom_hint_text() == "已下线：待下线成品（子项产线已清理）"
        finally:
            w.close()

    def test_in_progress_row_shows_short_label(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch, plans=[dict(RUNNING_PLAN)])
        try:
            row = _row(w, 102)
            assert row["actionKind"] == "blocked"
            assert row["actionText"] == "生产中"
            assert row["actionTip"] == "生产中"
        finally:
            w.close()

    def test_synthetic_root_row_has_no_action_button(self, qapp, monkeypatch):
        """共享组件的合成根行不属于任何可操作状态 → 动作槽留空。

        旧实现会落到兜底分支，显示「?」并在 tooltip 写「状态「」不可启动」。
        """
        w, _ = _make_launcher(qapp, monkeypatch, plans=[dict(SHARED_CHILD_PLAN)])
        try:
            # 合成根行 id=None → 行键为 0
            assert _ids(w)[0] == 0
            assert _row(w, 0)["actionKind"] == "none"
            assert _row(w, 0)["actionText"] == ""
        finally:
            w.close()


# 多并行产线的独立计划 —— 部分启动的可见条件需要 parallels > 1
PARTIAL_PLAN = _plan(201, name="多线成品", parallels=3)


class TestLauncherContextMenu:
    """行右键菜单：添加备注 / 部分启动。"""

    def test_partial_start_visible_for_standalone_plan(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch, plans=[dict(PARTIAL_PLAN)])
        try:
            assert w._can_partial_start(w._plan_map[201]) is True
        finally:
            w.close()

    def test_partial_start_hidden_for_child_row(self, qapp, monkeypatch):
        child = _plan(202, name="子项", child_level=1, parallels=3)
        w, _ = _make_launcher(qapp, monkeypatch, plans=[child])
        try:
            assert w._can_partial_start(w._plan_map[202]) is False
        finally:
            w.close()

    def test_partial_start_hidden_for_single_line(self, qapp, monkeypatch):
        single = _plan(203, name="单线", parallels=1)
        w, _ = _make_launcher(qapp, monkeypatch, plans=[single])
        try:
            assert w._can_partial_start(w._plan_map[203]) is False
        finally:
            w.close()

    def test_partial_start_hidden_for_mother_with_pending_children(self, qapp, monkeypatch):
        """母项还有未完成子项 → 不可启动，也不给部分启动。"""
        mother = _plan(204, name="母项", group_number=9, child_level=0, parallels=3)
        pending_child = _plan(205, name="子项", group_number=9, child_level=1)
        w, _ = _make_launcher(qapp, monkeypatch, plans=[mother, pending_child])
        try:
            assert w._can_partial_start(w._plan_map[204]) is False
        finally:
            w.close()

    def test_partial_start_calls_service_with_n(self, qapp, monkeypatch):
        from ui_qml.bridge import partial_start_bridge as psd
        from ui_qml.views.industry import production_launcher as pl

        w, _ = _make_launcher(qapp, monkeypatch, plans=[dict(PARTIAL_PLAN)])
        try:
            seen: dict = {}

            class _Dlg:
                def __init__(self, *args, **kwargs):
                    pass

                def exec(self):
                    return 1

                def lines(self):
                    return 2

            monkeypatch.setattr(psd, "PartialStartQmlDialog", _Dlg)
            # 容量判定要读**真实**人物配置（同套件里别的用例会改它），必须钉死，
            # 否则会弹出模态的「人物产线超员」确认框把测试挂住
            monkeypatch.setattr(pl, "max_lines_for_category", lambda *a, **k: 99)
            monkeypatch.setattr(
                plan_execution,
                "preview_partial_start",
                lambda pid, lines, mat: {"ok": True, "shortfalls": [], "bp_short": None},
            )
            monkeypatch.setattr(
                plan_execution,
                "start_plan_partial",
                lambda pid, lines, **kw: seen.update(pid=pid, lines=lines, kw=kw) or {"ok": True},
            )
            emitted: list = []
            w.plans_changed.connect(lambda: emitted.append(True))

            w._on_row_partial_start(201)

            assert seen["pid"] == 201 and seen["lines"] == 2
            assert emitted == [True]
        finally:
            w.close()

    def test_notes_menu_writes_repo(self, qapp, monkeypatch):
        from types import SimpleNamespace

        from ui_qml.views.industry import production_launcher as pl

        w, _ = _make_launcher(qapp, monkeypatch, plans=[dict(PARTIAL_PLAN)])
        try:
            repo = MagicMock()
            monkeypatch.setattr(pl, "get_container", lambda: SimpleNamespace(plan_repo=repo))
            monkeypatch.setattr(pl.InputQmlDialog, "get_multiline_text", lambda *a, **k: ("待补蓝图", True))

            w._on_row_notes(201)

            repo.update.assert_called_once_with(201, notes="待补蓝图")
            assert w._plan_map[201]["notes"] == "待补蓝图"
        finally:
            w.close()

    def test_notes_menu_cancel_writes_nothing(self, qapp, monkeypatch):
        from types import SimpleNamespace

        from ui_qml.views.industry import production_launcher as pl

        w, _ = _make_launcher(qapp, monkeypatch, plans=[dict(PARTIAL_PLAN)])
        try:
            repo = MagicMock()
            monkeypatch.setattr(pl, "get_container", lambda: SimpleNamespace(plan_repo=repo))
            monkeypatch.setattr(pl.InputQmlDialog, "get_multiline_text", lambda *a, **k: ("x", False))

            w._on_row_notes(201)

            repo.update.assert_not_called()
        finally:
            w.close()


def _wait_true(predicate, timeout_ms: int = 800) -> bool:
    """轮询等待条件成立。

    `Menu` 的弹出是异步的（`popupSoon()` 还额外经 `Qt.callLater` 延迟一拍），
    点击/发信号返回时 `opened` 仍是 false —— 固定 sleep 会在慢机器上偶发失败。
    """
    waited = 0
    while waited < timeout_ms:
        if predicate():
            return True
        spin(50)
        waited += 50
    return bool(predicate())


class TestLauncherRowMenuWiring:
    """行右键菜单迁到 QML 后的接线：Python 判定条目 → QML 弹 `FMenu`。"""

    def test_context_menu_request_carries_partial_flag(self, qapp, monkeypatch):
        """右键不再自建原生 `QMenu`，而是把 (计划, 是否给「部分启动」) 交给 QML。"""
        w, _ = _make_launcher(qapp, monkeypatch, plans=[dict(PARTIAL_PLAN), dict(READY_PLAN)])
        try:
            seen: list = []
            w._bridge.contextMenuRequested.connect(lambda pid, can: seen.append((pid, can)))

            w._on_row_context_menu(201)  # parallels=3 的独立计划 → 给「部分启动」
            w._on_row_context_menu(101)  # 待下线（非 pending）→ 不给
            w._on_row_context_menu(9999)  # 不在列表里 → 什么都不发

            assert seen == [(201, True), (101, False)]
        finally:
            w.close()

    def test_bridge_row_slots_reach_the_controller(self, qapp, monkeypatch):
        """桥按**公开名** `row_start` / `row_toggle` / `row_complete` / `row_context_menu` /
        `row_notes` / `row_partial_start` 转发进来。

        回归背景：这几个名字一度只在页面里以 `_on_*` 形式存在，桥一调就是
        `AttributeError` —— QML 里点启动/折叠/可下线、右键行，全部断掉。
        """
        w, _ = _make_launcher(qapp, monkeypatch, plans=[dict(PARTIAL_PLAN)])
        try:
            calls: list = []

            def _record(name):
                return lambda plan_id: calls.append((name, int(plan_id)))

            for name in ("row_start", "row_toggle", "row_complete", "row_notes", "row_partial_start"):
                monkeypatch.setattr(w, name, _record(name))
            # 右键走真实现（它要读 `_can_partial_start`），只把出口换成记录
            monkeypatch.setattr(
                w._bridge,
                "request_context_menu",
                lambda pid, can: calls.append(("row_context_menu", int(pid))),
            )

            w._bridge.rowStart(201)
            w._bridge.rowToggle(7)
            w._bridge.rowComplete(201)
            w._bridge.rowNotes(201)
            w._bridge.rowPartialStart(201)
            w._bridge.rowContextMenu(201)

            assert calls == [
                ("row_start", 201),
                ("row_toggle", 7),
                ("row_complete", 201),
                ("row_notes", 201),
                ("row_partial_start", 201),
                ("row_context_menu", 201),
            ]
        finally:
            w.close()

    def test_qml_menu_opens_and_gates_partial_item(self, qapp, monkeypatch):
        """整条链：桥发信号 → QML 的 `rowMenu` 真的打开，条目标志随之更新。"""
        w, _ = _make_launcher(qapp, monkeypatch, plans=[dict(PARTIAL_PLAN), dict(READY_PLAN)])
        try:
            menu = w._window.findChild(QObject, "rowMenu")
            assert menu is not None, "LauncherWindow.qml 里没有 objectName=rowMenu 的菜单"

            w._bridge.request_context_menu(201, True)
            assert _wait_true(lambda: menu.property("opened") is True), "右键菜单没打开"
            assert menu.property("planId") == 201
            assert menu.property("canPartial") is True
            menu.close()
            spin()

            w._bridge.request_context_menu(101, False)
            assert _wait_true(lambda: menu.property("opened") is True), "右键菜单没打开"
            assert menu.property("planId") == 101
            assert menu.property("canPartial") is False
            menu.close()
            spin()
        finally:
            w.close()


class TestLauncherRowClick:
    """行点击命中固定在按下那一刻（见 `ui_qml/qml/components/FTableClickArea.qml`）。

    回归背景：delegate 里的 `TapHandler` 配 `ReleaseWithinBounds` 在**释放**时判定
    命中，而 `ListView` 也是 Flickable —— 内容一移动（甩动/惯性沉降），按下位置那行
    已经被复用走，整次点击被丢掉。
    """

    def test_click_survives_content_move(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            # 必须给窗口真实尺寸并显示：不显示时内部 ListView 高度是 0，点击区
            # 根本不在可点范围内（与产品无关，是测试环境要满足的前提）
            w.resize(1000, 700)
            w.show()
            spin(400)
            rows = w._bridge.rows
            assert len(rows) >= 4, "用例需要至少 4 行才能验证滚动中的点击"
            press_move_release(
                w._window,
                _root(w),
                area_name="launcherClickArea",
                row=3,
                read_current=lambda: w._bridge.selectedId,
                expect=rows[3]["id"],
                delta=1,
            )
        finally:
            w.close()


# ═══════════════════════════════════════════════════
#  置顶：显示时重申
# ═══════════════════════════════════════════════════


def test_show_reasserts_the_pin(qapp, monkeypatch):
    """窗口显示时必须重申置顶 —— 与采购小助手同一条。

    `_restore_pin` 只在构造时设过置顶，而那一刻窗口还没显示（SetWindowPos 作用在一个
    随后会被 Qt 重新定位、显示的平台窗口上）；`QWindow.raise_()` 又是 `SetWindowPos(HWND_TOP)`。
    两者都可能让置顶在用户真正看到窗口之前丢掉，表现是「勾着置顶却没置顶，再点一次才好」。
    """
    w, _ = _make_launcher(qapp, monkeypatch)
    try:
        calls: list[bool] = []
        monkeypatch.setattr(
            "ui_qml.views.industry.production_launcher.reassert_pin",
            lambda window, pinned: calls.append(bool(pinned)),
        )

        w._pinned = True
        w.window_visibility_changed(True)
        assert calls == [True], "显示时要重申置顶"

        calls.clear()
        w.window_visibility_changed(False)
        assert calls == [], "隐藏时不该去动窗口"
    finally:
        w.close()


# ═══════════════════════════════════════════════════
#  选中通知 / 占用条几何
# ═══════════════════════════════════════════════════


def test_select_plan_notifies_selection_change(qapp, monkeypatch):
    """选中某行必须发 `selectionChanged`，且**不得**因此发 `rowsChanged`。

    回归：`select_plan` 原先只更新底部面板（发 `bottomChanged`）并请求滚动，而
    `selectedId` 挂的通知是 `rowsChanged` —— 行卡的 `selected` 绑定于是**永不重新求值**：
    点了行底色不动，亮着的是 delegate 创建那一刻恰好选中的那条（用户报的「选中状态色差错乱」）。

    为什么用 `selectionChanged` 而不是顺手复用 `rowsChanged`：后者会把 ListView 的
    `model` 整个换掉 —— 每点一次行就重建一次 delegate，还冲掉滚动位置。
    """
    w, _ = _make_launcher(qapp, monkeypatch)
    try:
        selections: list[int] = []
        row_rebuilds: list[int] = []
        w._bridge.selectionChanged.connect(lambda: selections.append(w._bridge.selectedId))
        w._bridge.rowsChanged.connect(lambda: row_rebuilds.append(1))

        target = w._bridge.rows[-1]["id"]
        w._bridge.selectRow(target)

        assert selections == [target], "选中变化没有通知出去，行卡底色会不跟着动"
        assert w._bridge.selectedId == target
        assert row_rebuilds == [], "选中不该重建整张列表（rowsChanged 会换掉 ListView 的 model）"
    finally:
        w.close()


def test_capacity_group_x_accumulates_previous_groups():
    """静态护栏：`FCapacityRow.groupX` 必须**累加前面各组**的占位。

    写成 `index * (labelW + gapSm) + index * lines[index].cap * effStride` 会拿**本组**的 cap
    当累计量：三类产线容量不同（制造 / 科研 / 反应），每组都被摆到偏左的 x 上 ——
    方块压到标签、整体与右侧徽章脱节。这条在运行期只有「看着错位」，没有任何报错。

    （历史上同类**几何**用例被判为「布局系统下结构上不存在」而删除；但这里的位置是手算的
    `x:`，布局系统管不到 —— 所以补回一条，形式改成静态检查。）
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "ui_qml" / "qml" / "components" / "FCapacityRow.qml").read_text(
        encoding="utf-8"
    )
    body = src.split("function groupX(")[1].split("\n    }")[0]

    assert "for (" in body, f"groupX 必须按前面的组累加，实得：{body!r}"
    assert "lines[index].cap" not in body, f"不能拿本组的 cap 当累计量：{body!r}"


def test_dispose_actually_destroys_the_qml_tree(qapp, monkeypatch):
    """退出时要**拆掉** QML 场景，不能只关窗。

    只 `close()` 的话 QML 树与 `QQmlEngine` 都还活着；等 Python 收尾回收 `Theme` 单例
    （`theme_bridge._singleton`，模块级全局，解释器收尾时会被清掉），场景里那些
    `Theme.xxx` 绑定重算就会对着 null 求值 —— 实测一次退出刷 **528 条**
    `Cannot read property 'xxx' of null`。

    这里断言的是**窗口真的没了**：光丢引用删不掉（window 是 engine 的 QObject 父，
    而 engine 又持有根对象 = 跨 Python/C++ 的引用环，实测 `isValid` 仍为真），
    必须走 `deleteLater()`。
    """
    from shiboken6 import isValid

    w, _ = _make_launcher(qapp, monkeypatch)
    window = w._window
    assert window is not None
    w.show()
    assert _wait_true(lambda: window.isVisible())

    w.dispose()

    assert w._window is None and w._engine is None and w._component is None
    assert _wait_true(lambda: not isValid(window)), "窗口没被真正删掉 —— 引用环还在，退出时会刷 null 绑定告警"
