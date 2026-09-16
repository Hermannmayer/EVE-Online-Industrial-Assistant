"""产线启动小助手 v3 — 可置顶悬浮的紧凑工具窗。

竖分四区（编号 L1–L4，详见 `docs/dev/ui-blueprint.md`）：

- **L1 工具条** `#launcher_toolbar` —— 线型/人物筛选 + 筛选激活指示 + 置顶（固定单行）
- **L2 占用面板** `#launcher_occupancy` —— 每角色一行产线占用，可折叠，≤4 行不滚动
- **L3 产线列表** `#launcher_list` —— 主工作区，行卡片，动作槽位固定宽（不跳动）
- **L4 详情/执行面板** `#launcher_bottom` —— 未选中为紧凑单行；选中后给参数摘要 + 执行人物 + 启动

实时刷新：1s 内存 tick（运行中行剩余时长）+ 5s DB 轮询（计划增删改自动同步）。

设计依据（间距/字号/图标/配色/披露层级）见 `docs/dev/ui-blueprint.md`；
配色可访问性契约在 `domain/theme_contrast.py::CONTRAST_CONTRACT`，
由 `tests/test_theme_registry.py` 对全部主题断言。

渲染已整体迁到 QML（`ui_qml/qml/pages/LauncherWindow.qml`，阶段 2c）：本类现在只作
**headless 控制器**——算数据、给 `launcher_bridge` 供值，自己不再画任何东西。
零星的 `QColor` 用法是给 QML 传色值（QML 要 `#rrggbb` 字符串），不是自绘。

批次 7.4 起**连窗口外壳也交出去了**：QML 根从 `Item` 换成 `Window`，本类从 `QWidget`
退成 `QObject` —— 不再有 `QVBoxLayout(self)` + `root.addWidget(host)`，窗口语义
（标题 / 尺寸 / 驻留 / 关闭 / 显示事件）由 QML 的 `Window` 自持，Python 侧只在
`show()` / `raise_()` / `activateWindow()` 上做转发（调用方 `industry_view.py` 一行未改）。
"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QDialog

import ui_qml.theme.registry as theme
from core.container import get_container
from core.logger import log
from domain.theme_contrast import ensure_contrast
from services import plan_execution
from services.char_capacity import (
    CAPACITY_LINE_MANUFACTURING,
    CAPACITY_LINE_REACTION,
    CAPACITY_LINE_RESEARCH,
    active_lines_by_category,
    capacity_line_for_category,
    line_label,
    max_lines_for_category,
)
from services.char_config_resolver import get_character_list, load_all_data
from services.plan_category import (
    CATEGORY_COPYING,
    CATEGORY_INVENTION,
    CATEGORY_MANUFACTURING,
    CATEGORY_REACTION,
)
from services.plan_service import group_and_sort_plans, load_plans_for_wizard
from services.plan_start_check import can_force_start, plan_start_block
from services.terminology import term
from ui_qml.bridge.input_dialog import InputQmlDialog
from ui_qml.bridge.message_dialog import FMessageDialog
from ui_qml.pin_utils import apply_window_pin

MAX_SLOTS_PER_LINE = 11  # 单行每类产线最大格块数（技能满级 1+5+5）

#: QML 页面路径（相对 ui_qml/qml/）
LAUNCHER_QML = "pages/LauncherWindow.qml"

# ── 线型筛选 ────────────────────────────────────────────
# 对齐游戏工业窗口的作业类型；名称走术语中心（`term.activity`），不硬编码中文。
# `production_plans` 无 activity 字段（每条计划都是制造作业），故只能按「蓝图用途性质」
# 分类，即 `services/plan_category` 推导出的 category —— 不能用 capacity_line_for_category，
# 那个映射是为「技能决定的产线容量」服务的（copying/invention 合并成科研线）。
# 材料效率研究 / 生产效率研究并入「发明」：本应用建不了研究计划（取数链路写死
# activity='manufacturing'），独立成项会恒空。
_ACTIVITY_FILTERS: tuple[tuple[str, frozenset[str]], ...] = (
    ("manufacturing", frozenset({CATEGORY_MANUFACTURING})),
    ("copying", frozenset({CATEGORY_COPYING})),
    ("invention", frozenset({CATEGORY_INVENTION, "research_material", "research_time"})),
    ("reaction", frozenset({CATEGORY_REACTION})),
)

# ── 间距标尺（Windows/Fluent 8/12/16 体系） ──────────────
# 控件间距 8、控件↔标签 12、表面↔边缘 16。布局里禁止写裸数字。
_GAP_XS = 4
_GAP_SM = 8
_GAP_MD = 12
_GAP_LG = 16

# ── 字号 ────────────────────────────────────────────────
# Windows 11 类型梯度的最小值是 12px regular，更小在 CJK 下不可读；本窗为悬浮工具窗、
# 常在放大的窗口里使用，故取梯度里更舒适的一档：Caption 13 / Body 14。
_FS_CAPTION = 13
_FS_BODY = 14

# ── 几何 ────────────────────────────────────────────────
_NAME_W = 76  # 占用区角色名默认宽（由 ProductionLauncher 按最长角色名统一算出后传入）
_MIN_NAME_W = 60
_MAX_NAME_W = 140
_OCC_ROW_H = 32
_MAX_OCC_ROWS = 4  # 超出则内部滚动，避免占用区把列表挤扁
_ICON_PX = 32  # 多行列表图标尺寸（Windows 文档：32epx）
_ROW_H = 68  # 容得下「标题+副标题」两行文字与 32px 图标，并留 8px 上下内边距
_BADGE_H = 22.0

_MIN_BLOCK_W = 4.0
_NOMINAL_BLOCK_W = 12.0  # sizeHint 里假设的格宽（决定初始窗宽）
_BLOCK_GAP = 3.0
_MIN_BLOCK_GAP = 2.0

_LINE_TYPES = (CAPACITY_LINE_MANUFACTURING, CAPACITY_LINE_RESEARCH, CAPACITY_LINE_REACTION)
_LINE_COLORS = {
    CAPACITY_LINE_MANUFACTURING: "ACCENT_GREEN",
    CAPACITY_LINE_RESEARCH: "ACCENT_CYAN",
    CAPACITY_LINE_REACTION: "ACCENT_PURPLE",
}

_STATUS_LABELS = {
    "pending": "待生产",
    "in_progress": "生产中",
    "running": "生产中",
    "ready": "待下线",
    "completed": "已完成",
    "done": "已完成",
}

# ⚠️ 字形可用性约束：段首是符号、后面紧跟中文时，Qt 会把整段解析到中文字体
# （theme.FONT_FAMILY = Microsoft YaHei UI）。实测 YaHei **有** ◆ ○ ● ▲ ▼ ■ → · × + −，
# **没有** ▸ ▾ ▶ ✓ ⓘ 📌 —— 后者会渲染成豆腐块（□）。
# 另外符号字形来自不同字体、字号与中文不匹配（▼ 明显比「折叠」大一圈），
# 故**正文里尽量不用几何符号**：状态用文字，折叠用 +/−，只有父项前缀保留 ◆。
_PARENT_GLYPH = "◆ "
_COLLAPSED_GLYPH = "+"  # 已折叠（可展开）
_EXPANDED_GLYPH = "−"  # 已展开（可折叠）

# 动作槽按钮文案。阻塞行不再用「?」占位：直接显示短标签，完整原因放 tooltip
# （`plan_start_block` 的类别码 → 短标签；code 由 services 层给出，不解析文案）。
_COMPLETE_LABEL = "可下线"
_START_LABEL = "启动"
_BLOCK_SHORT_LABELS = {
    "status_running": "生产中",
    "status_done": "已完成",
    "status_other": "不可启动",
    "no_mat_hangar": "未设材料库",
    "material_short": "材料不够",
    "blueprint_missing": "缺蓝图",
    "blueprint_short": "缺蓝图",
    "children_running": "子项运行中",
    "waiting_children": "等子项",
}


def _short_label(code: str | None, status: str) -> str:
    """阻塞类别码 → 动作槽短标签；码缺失时退回状态标签。

    短标签放 UI 层：它是本窗动作槽的展示文案（与 `_STATUS_LABELS` 同类），不是
    EVE 游戏术语，不入 `services.terminology`。完整原因只进 tooltip —— 蓝图流程
    不足的原文可达数十字，直接上按钮会把 68px 的行撑爆。
    """
    return _BLOCK_SHORT_LABELS.get(code or "") or _STATUS_LABELS.get(status, "") or "不可启动"


# 动作槽宽度按这些文案的**最宽者**取值（新增短标签会自动纳入，不会截断）
_SLOT_SAMPLES = (_START_LABEL, _COMPLETE_LABEL, "折叠(99)", "展开(99)", *_BLOCK_SHORT_LABELS.values())
_SLOT_MIN_W = 88


def _fmt_hms(seconds) -> str:
    """秒 → HH:MM:SS（<1 小时也显示 HH:MM:SS，保持行内对齐）。"""
    seconds = max(int(seconds or 0), 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_remaining(plan: dict) -> str:
    """运行中计划剩余时长文本。"""
    rem = plan_execution.remaining_seconds(plan)
    if rem is None:
        return ""
    if rem <= 0:
        return "已超时"
    return _fmt_hms(rem)


def _default_mat_hangar_id() -> int | None:
    """默认材料机库（settings.default_mat_hangar_id）。"""
    from services import inventory_manager

    return inventory_manager.get_default_mat_hangar_and_system()[0]


class ProductionLauncher(QObject):
    """产线启动小助手 — 非模态紧凑工具窗（控制器；窗口是 `LauncherWindow.qml` 的 `Window`）。"""

    plans_changed = Signal()  # 启动成功后触发，供主窗口刷新

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        #: QML 根是 `Window`，实例化出来的就是本窗（`_build_window` 里赋值）。
        #: 类型由 `_build_window` 保证，这里先占位以便生命周期槽能安全早退。
        self._window: QQuickWindow | None = None
        self._engine: QQmlEngine | None = None
        self._component: QQmlComponent | None = None

        self._all_plans: list[dict] = []
        self._visible_plans: list[dict] = []
        self._plan_map: dict[int, dict] = {}
        self._usage: dict[str, dict[str, int]] = {}
        self._shortfall_cache: dict[int, tuple] = {}
        # 本轮轮询的机库库存（内容 + 指纹），按 mat_hangar_id 记忆；_on_poll 开头清空。
        # 库存必须进缺口指纹：它不进计划字段，只按计划字段缓存会让「材料补齐后」一直显示旧缺口。
        self._stock_cache: dict[int, dict[int, int]] = {}
        self._stock_fp: dict[int, frozenset] = {}
        self._bp_short_cache: dict[int, str | None] = {}  # 本轮蓝图流程预检结果
        # 输入蓝图就绪缓存（按计划指纹），避免每行每次刷新都打 DB
        self._bp_ready_cache: dict[int, tuple] = {}
        self._collapsed: set[int] = set()  # 已折叠的组号（隐藏其子项）
        self._occ_collapsed = False
        self._selected_id: int | None = None
        self._default_mat_hangar = _default_mat_hangar_id()
        self._char_list = get_character_list()

        # ── QML 渲染状态（阶段 2c：四个区都交给 QML，这里只存数据） ──
        self._line_filter_index = 0  # 0 = 全部
        self._char_filter_index = 0  # 0 = 全部人物
        self._pinned = False
        self._filter_summary = ""
        self._occ_summary = ""
        self._occ_rows: list[dict] = []
        self._rows_view: list[dict] = []
        self._hint_text = "在上方列表选一条产线"
        self._feedback_text = ""
        self._params_text = ""
        self._executor_options: list[dict] = []
        self._executor_index = 0
        self._main_btn_text = ""
        self._main_btn_tip = ""
        self._main_btn_visible = False
        self._bottom_expanded = False
        self._tick_revision = 0

        self._build_window()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start()

        self._on_poll()
        self._restore_pin()

    # ── 窗口 ────────────────────────────────────────────
    #
    # 批次 7.4：QML 根从 `Item` 换成 `Window`，本类不再是 QWidget，于是**窗口语义一分为二**：
    #   * 声明性的（标题 / 初始尺寸 / 最小尺寸 / 顶层属性 / 关闭即隐藏）在 QML 里；
    #   * 命令式的（显示 / 前置 / 激活 / 尺寸）在这里转发给 `self._window`。
    # `industry_view.py` 调用的 `show()` / `raise_()` / `activateWindow()` 因此一行未改。

    def _build_window(self) -> None:
        """把 `LauncherWindow.qml`（根元素是 `Window`）实例化成本窗。

        ⚠️ 根是 `Window` 时 `QQuickView` / `QQuickWidget` 都用不了（两者的根必须是 `Item`），
        只能走 `QQmlEngine` + `QQmlComponent` —— 与 `ui_qml/splash_window.py` 同法，
        也从 `component.errors()` 里拿结构化错误（加载失败**直接抛**，不静默成空白窗口）。
        """
        from ui_qml.bridge import CONTEXT_NAME, theme_singleton
        from ui_qml.bridge.launcher_bridge import LauncherBridge
        from ui_qml.host import QML_ROOT

        self._bridge = LauncherBridge(self, self)
        engine = QQmlEngine()
        self._engine = engine
        ctx = engine.rootContext()
        ctx.setContextProperty(CONTEXT_NAME, theme_singleton())
        ctx.setContextProperty("bridge", self._bridge)
        path = QML_ROOT / LAUNCHER_QML
        component = QQmlComponent(engine)
        component.setData(path.read_bytes(), QUrl.fromLocalFile(str(path)))
        if component.isError():
            raise RuntimeError("; ".join(e.toString() for e in component.errors()))
        self._component = component
        window = component.create(ctx)
        if not isinstance(window, QQuickWindow):
            raise RuntimeError(f"{LAUNCHER_QML} 的根元素不是 Window：{window!r}")
        # 所有权：**引擎挂到窗口名下**（`QQuickView` 自己就是 `new QQmlEngine(view)` 这么干的）。
        # 于是「窗口先销毁、引擎随后跟着走」由 Qt 的父子关系保证，不依赖 Python 的析构顺序 ——
        # 反过来（引擎先走、场景还在）时，任何一次绑定重算都会撞上被拆掉的上下文。
        # ⚠️ 不能反过来把窗口挂到控制器名下：PySide 的 `QWindow.setParent` 只收 `QWindow`。
        component.setParent(engine)
        engine.setParent(window)
        self._window = window

    # ── 窗口命令（转发给 QML 的 `Window`）──────────────────

    def show(self) -> None:
        if self._window is not None:
            self._window.show()

    def hide(self) -> None:
        if self._window is not None:
            self._window.hide()

    def close(self) -> None:
        """关窗。

        ⚠️ `QWindow.close()` **只在窗口当前可见时才发 `closing`**（Qt 的语义：已经关着的
        窗口再关一次没有意义）。而「关过」在本窗是一件**状态**（关闭即停表，重开再启）——
        调用方（复用路径与测试）也照旧把 `close()` 当那次状态切换用。所以先把收尾走完
        （幂等），再让窗口真的关：可见时它等价于用户点 X，走的仍是 QML 的 `onClosing`。
        """
        if self._window is None:
            return
        self.window_closing()
        self._window.close()

    def resize(self, width: int, height: int) -> None:
        if self._window is not None:
            self._window.resize(int(width), int(height))

    def raise_(self) -> None:
        """对应 `QWidget.raise_()`。QWindow 上同名方法在 PySide 里也是 `raise_`。"""
        if self._window is not None:
            self._window.raise_()

    def activateWindow(self) -> None:
        """对应 `QWidget.activateWindow()`；QWindow 上是 `requestActivate()`。"""
        if self._window is not None:
            self._window.requestActivate()

    def isVisible(self) -> bool:
        return self._window is not None and bool(self._window.isVisible())

    # ── 桥的取数接口（QML 只读这些，业务判断全在本类） ──────────

    def line_filter_options(self) -> list[dict]:
        out: list[dict] = [{"label": "全部", "value": None}]
        for key, _cats in _ACTIVITY_FILTERS:
            out.append({"label": term.activity(key), "value": key})
        return out

    def char_filter_options(self) -> list[dict]:
        out: list[dict] = [{"label": "全部人物", "value": None}, {"label": "未分配", "value": ""}]
        for name in self._char_list:
            out.append({"label": name, "value": name})
        return out

    def line_filter_index(self) -> int:
        return self._line_filter_index

    def char_filter_index(self) -> int:
        return self._char_filter_index

    def set_line_filter_index(self, index: int) -> None:
        self._line_filter_index = max(0, min(int(index), len(_ACTIVITY_FILTERS)))
        self._apply_filters()

    def set_char_filter_index(self, index: int) -> None:
        self._char_filter_index = max(0, min(int(index), len(self._char_list) + 1))
        self._apply_filters()

    def _line_filter_cats(self) -> frozenset[str] | None:
        """当前线型筛选对应的类别集合；None = 全部。"""
        if self._line_filter_index <= 0:
            return None
        return _ACTIVITY_FILTERS[self._line_filter_index - 1][1]

    def _char_filter_value(self) -> str | None:
        """当前人物筛选值；None = 全部人物，"" = 未分配。"""
        if self._char_filter_index <= 0:
            return None
        if self._char_filter_index == 1:
            return ""
        return self._char_list[self._char_filter_index - 2]

    def filter_summary_text(self) -> str:
        return self._filter_summary

    def is_pinned(self) -> bool:
        return self._pinned

    def set_pinned(self, value: bool) -> None:
        if bool(value) == self._pinned:
            return
        self._pinned = bool(value)
        # 置顶作用在**窗口**上，不是控制器上（`apply_window_pin` 两种窗口都吃）。
        if self._window is not None:
            apply_window_pin(self._window, self._pinned)
        from services.user_settings import save_settings

        try:
            save_settings({"production_launcher_pin": self._pinned})
        except Exception:
            log.exception("保存产线小助手置顶偏好失败")
        self._notify_toolbar()

    def _restore_pin(self) -> None:
        try:
            from services.user_settings import load_settings

            if load_settings().get("production_launcher_pin"):
                self._pinned = True
                if self._window is not None:
                    apply_window_pin(self._window, True)
                self._notify_toolbar()
        except Exception:
            log.exception("恢复产线小助手置顶偏好失败")

    # ── L2 折叠 ──────────────────────────────────────────

    def occupancy_collapsed(self) -> bool:
        return self._occ_collapsed

    def toggle_occupancy(self) -> None:
        self._occ_collapsed = not self._occ_collapsed
        self._notify_occupancy()

    def occupancy_summary(self) -> str:
        return self._occ_summary

    def occupancy_rows(self) -> list[dict]:
        return self._occ_rows

    # ── L3 列表接口 ──────────────────────────────────────

    def row_view_models(self) -> list[dict]:
        return self._rows_view

    def is_empty(self) -> bool:
        return not self._rows_view

    def selected_plan_id(self) -> int:
        return int(self._selected_id or 0)

    @staticmethod
    def row_height() -> int:
        return _ROW_H

    def action_slot_width(self) -> int:
        """动作槽固定宽度：按全部候选短标签的最宽者算。

        五个按钮互斥显隐但**占位不变**，槽宽按最长文案取值，切换时不左右跳动。
        """
        font = QFont(theme.FONT_FAMILY)
        font.setPixelSize(theme.fs(_FS_BODY))
        fm = QFontMetrics(font)
        text_w = max(fm.horizontalAdvance(sample) for sample in _SLOT_SAMPLES)
        return max(_SLOT_MIN_W, text_w + 2 * _GAP_MD)

    def select_plan(self, plan_id: int) -> None:
        """把某计划设为列表选中项（行内启动 / 阻塞提示共用）。"""
        if plan_id not in self._plan_map:
            return
        self._selected_id = int(plan_id)
        self._hint_text = "在上方列表选一条产线"
        self._update_bottom()
        if getattr(self, "_bridge", None) is not None:
            self._bridge.request_selection(int(plan_id))

    def _notify_toolbar(self) -> None:
        if getattr(self, "_bridge", None) is not None:
            self._bridge.notify_toolbar()

    def _notify_occupancy(self) -> None:
        if getattr(self, "_bridge", None) is not None:
            self._bridge.notify_occupancy()

    def _notify_rows(self) -> None:
        if getattr(self, "_bridge", None) is not None:
            self._bridge.notify_rows()

    def _notify_bottom(self) -> None:
        if getattr(self, "_bridge", None) is not None:
            self._bridge.notify_bottom()

    def _notify_tick(self) -> None:
        if getattr(self, "_bridge", None) is not None:
            self._bridge.notify_tick()

    def tick_revision(self) -> int:
        """1s 心跳计数 —— QML 的 duration 绑定依赖它才会重新求值（见 `_on_tick`）。"""
        return self._tick_revision

    # ── 数据刷新 ─────────────────────────────────────────

    def _on_poll(self) -> None:
        """5s 轮询：补算过期 + 重载非完成计划 + 刷新占用/列表。

        库存快照在这里作废：材料是否备齐不进计划字段，必须每轮重取，
        否则「补齐材料」后缺口判定永远停在旧值。
        """
        self._stock_cache.clear()
        self._stock_fp.clear()
        self._bp_short_cache.clear()
        try:
            plan_execution.expire_overdue_plans()
            self._all_plans = load_plans_for_wizard()
        except Exception:
            log.exception("产线小助手轮询失败")
            return
        self._refresh_occupancy()
        self._apply_filters()

    def _on_tick(self) -> None:
        """1s 心跳：只刷新运行中行的剩余时长，不重建列表。

        QML 的 `model` 是普通 `var` 列表，改字典里的值不会触发重绘，
        故额外给一个自增的 `tickRevision` 让 duration 的绑定重新求值
        （比整表重置便宜，也不会把滚动位置与选中态冲掉）。
        """
        touched = False
        for row in self._rows_view:
            plan = self._plan_map.get(int(row.get("id") or 0))
            if plan is None or (plan.get("status") or "").lower() not in ("in_progress", "running"):
                continue
            rem = _fmt_remaining(plan)
            if rem:
                row["durationText"] = f"剩 {rem}"
                touched = True
        if touched:
            self._tick_revision += 1
            self._notify_tick()

    def _refresh_occupancy(self) -> None:
        """算出占用面板要画的内容：每角色一行（含每类产线的占用/容量/上限）。

        行内方块区宽度按各类产线的**最大容量**比例分配（`slotTotal` = 各类上限之和），
        这样「制造 13 格 / 科研 1 格」不会在一行里留下十几个空档，各行也仍能纵向对齐。
        """
        self._usage = active_lines_by_category(self._all_plans)
        data = load_all_data()
        chars_data = data.get("characters", {}) or {}
        chars = list(self._char_list)
        for c in self._usage:
            if c and c not in chars:
                chars.append(c)

        if not chars:
            self._occ_summary = "（无人物配置，请在人物设置中添加）"
            self._occ_rows = []
            self._notify_occupancy()
            return

        # 统一角色名列宽 → 各行的产线方块保持纵向对齐（逐行自算会错位）
        name_font = QFont(theme.FONT_FAMILY)
        name_font.setPixelSize(theme.fs(_FS_BODY))
        name_font.setBold(True)
        fm = QFontMetrics(name_font)
        name_width = max((fm.horizontalAdvance(c or "(未分配)") for c in chars), default=_NAME_W) + _GAP_SM
        name_width = max(_MIN_NAME_W, min(name_width, _MAX_NAME_W))

        per_char: list[tuple[str, dict[str, tuple[int, int]]]] = []
        line_caps: dict[str, int] = dict.fromkeys(_LINE_TYPES, 0)
        active_total = 0
        max_total = 0
        for char in chars:
            skills = (chars_data.get(char, {}) or {}).get("skills", {}) or {}
            usage = self._usage.get(char or "", {})
            per_line: dict[str, tuple[int, int]] = {}
            for line in _LINE_TYPES:
                mx = max_lines_for_category(char, line, skills=skills)
                active = usage.get(line, 0)
                per_line[line] = (active, mx)
                line_caps[line] = max(line_caps[line], mx)
                active_total += active
                max_total += mx
            per_char.append((char, per_line))

        slot_total = max(sum(line_caps.values()), 1)
        rows: list[dict] = []
        for char, per_line in per_char:
            lines_data = []
            for line in _LINE_TYPES:
                active, mx = per_line[line]
                # 颜色在 Python 侧解析并由 ensure_contrast 校正到 WCAG 非文字 3:1 ——
                # 强调色是给填充用的中间调，部分浅色主题下直接用会不达标。
                # 计算在 `domain/theme_contrast`（纯 hex），这里只把结果包成 QColor 给 QML 用。
                accent = str(getattr(theme, _LINE_COLORS[line]))
                lines_data.append(
                    {
                        "label": line_label(line),
                        "color": QColor(ensure_contrast(accent, theme.BG_DARK)).name(),
                        "active": int(active),
                        "max": int(mx),
                        "cap": int(line_caps[line]),
                    }
                )
            status_text, status_token = self._char_status(per_line)
            rows.append(
                {
                    "name": char or "(未分配)",
                    "nameWidth": name_width,
                    "lines": lines_data,
                    "statusText": status_text,
                    "statusColor": str(getattr(theme, status_token)),
                    "slotTotal": slot_total,
                }
            )

        self._occ_rows = rows
        self._occ_summary = f"{len(chars)} 人物 · 占用 {active_total}/{max_total}"
        self._notify_occupancy()

    @staticmethod
    def _char_status(per_line: dict[str, tuple[int, int]]) -> tuple[str, str]:
        """(状态文本, 语义色 token) —— 超员 / 空闲 / 生产中。

        文本以「空闲/生产中/超员」开头（既有测试依赖这个契约）。
        """
        active_total = sum(per_line.get(line, (0, 0))[0] for line in _LINE_TYPES)
        max_total = sum(per_line.get(line, (0, 0))[1] for line in _LINE_TYPES)
        if active_total > max_total:
            return f"超员 +{active_total - max_total}", "ACCENT_RED"
        if active_total == 0:
            return "空闲", "ACCENT_GREEN"
        return "生产中", "PRIMARY"

    def _match_filters(self, plan: dict) -> bool:
        cats = self._line_filter_cats()
        if cats is not None and str(plan.get("category") or CATEGORY_MANUFACTURING) not in cats:
            return False
        char = self._char_filter_value()
        if char is None:
            return True
        plan_char = (plan.get("char_name") or "").strip()
        return bool(plan_char == char)

    def _apply_filters(self) -> None:
        full = group_and_sort_plans(self._all_plans)
        # 自动展开：子项全部完成（_pending_children==0）的组不再折叠
        for p in full:
            gid = int(p.get("group_id") or 0)
            if gid and int(p.get("child_level") or 0) == 0 and not p.get("_pending_children"):
                self._collapsed.discard(gid)
        visible = [p for p in full if self._match_filters(p) and not self._is_collapsed_child(p)]
        self._visible_plans = visible
        self._sync_rows(visible)
        self._update_filter_summary(len(full), len(visible))
        self._update_bottom()

    def _update_filter_summary(self, total: int, shown: int) -> None:
        """筛选激活指示 —— 用户应能一眼看出「数据已被过滤」（NN/g 表设计）。"""
        filtered = self._line_filter_cats() is not None or self._char_filter_value() is not None
        self._filter_summary = f"已筛选 {shown}/{total}" if filtered else f"共 {total} 条"
        self._notify_toolbar()

    def _is_collapsed_child(self, plan: dict) -> bool:
        gid = int(plan.get("group_id") or plan.get("group_number") or 0)
        return bool(gid and int(plan.get("child_level") or plan.get("sub_level") or 0) > 0 and gid in self._collapsed)

    # ── 列表同步 ─────────────────────────────────────────

    def _hangar_stock(self, mat_hangar_id: int) -> dict[int, int]:
        """本轮轮询内的机库库存快照（每机库只查一次）。"""
        stock = self._stock_cache.get(mat_hangar_id)
        if stock is None:
            from services import inventory_manager

            stock = inventory_manager.get_hangar_stock(mat_hangar_id)
            self._stock_cache[mat_hangar_id] = stock
        return stock

    def _stock_key(self, mat_hangar_id: int) -> frozenset:
        """该机库本轮库存的内容指纹（每机库只构造一次）。"""
        key = self._stock_fp.get(mat_hangar_id)
        if key is None:
            key = frozenset(self._hangar_stock(mat_hangar_id).items())
            self._stock_fp[mat_hangar_id] = key
        return key

    def _shortfall_count(self, plan: dict) -> int:
        """材料缺口种数（指纹缓存，避免每轮全量评分）。

        指纹**必须含库存内容**：库存变化不进计划字段，只按计划字段缓存会在「材料补齐后」
        永远命中旧值，行上于是一直显示问号，直到改计划字段或重启应用（历史缺陷）。
        库存在 `_on_poll` 的节拍上重取（每机库每轮一次），内容没变仍命中缓存。
        """
        pid = int(plan.get("id") or 0)
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar
        is_pending = (plan.get("status") or "").lower() == "pending"
        stock_key = self._stock_key(int(mat)) if (is_pending and mat) else None
        fp = (
            plan.get("status"),
            plan.get("runs"),
            plan.get("parallels"),
            plan.get("me_level"),
            plan.get("te_level"),
            plan.get("char_name"),
            plan.get("mat_hangar_id"),
            stock_key,
        )
        cached = self._shortfall_cache.get(pid)
        if cached and cached[0] == fp:
            return int(cached[1])
        count = 0
        if is_pending and mat:
            try:
                missing = [
                    r
                    for r in plan_execution.check_materials(plan, mat, stock=self._stock_cache.get(int(mat)))
                    if (r.get("missing") or 0) > 0
                ]
                count = len(missing)
            except Exception:
                log.exception("材料缺口计算失败 plan_id=%s", plan.get("id"))
                count = 0
        self._shortfall_cache[pid] = (fp, count)
        return count

    def _bp_short(self, plan: dict) -> str | None:
        """蓝图流程不足的原因（本轮轮询内每计划只查一次）。"""
        pid = int(plan.get("id") or 0)
        if pid not in self._bp_short_cache:
            try:
                self._bp_short_cache[pid] = plan_execution.binding_shortfall(pid)
            except Exception:
                log.exception("蓝图流程预检失败 plan_id=%s", pid)
                self._bp_short_cache[pid] = None
        return self._bp_short_cache[pid]

    def _blueprint_ready(self, plan: dict) -> bool:
        """输入蓝图是否就绪（按活动规则，见 services.plan_job_kinds）。带指纹缓存。"""
        pid = int(plan.get("id") or 0)
        fp = (
            plan.get("status"),
            plan.get("activity"),
            plan.get("runs"),
            plan.get("parallels"),
            plan.get("assigned_blueprint_id"),
        )
        cached = self._bp_ready_cache.get(pid)
        if cached and cached[0] == fp:
            return bool(cached[1])
        try:
            ready = plan_execution.plan_blueprint_ready(plan)
        except Exception:
            ready = True  # 读不到时不拦（与旧宽松语义一致）
        self._bp_ready_cache[pid] = (fp, ready)
        return ready

    def _block_state(self, plan: dict) -> tuple[str | None, str | None]:
        """启动阻塞 → (类别码, 原因文案)；None = 可启动。

        每行只算一次并同时把两者交给 `PlanRow`，短标签与 tooltip 因此同源，
        不会出现「按钮说材料不够、悬停说别的」。
        """
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar
        block = plan_start_block(
            plan,
            mat,
            self._all_plans,
            shortfall_count=self._shortfall_count(plan),
            bp_short=self._bp_short(plan),
            blueprint_ready=self._blueprint_ready(plan),
        )
        return block if block else (None, None)

    def _block_reason(self, plan: dict) -> str | None:
        return self._block_state(plan)[1]

    def _can_force_start(self, plan: dict) -> bool:
        """缺料 / 蓝图流程不足是否为唯一阻塞（是 → 仍给「启动」，点击时二次确认）。"""
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar
        return can_force_start(
            plan,
            mat,
            self._all_plans,
            shortfall_count=self._shortfall_count(plan),
            bp_short=self._bp_short(plan),
            blueprint_ready=self._blueprint_ready(plan),
        )

    def _row_collapsed(self, plan: dict) -> bool:
        gid = int(plan.get("group_id") or plan.get("group_number") or 0)
        return bool(gid and gid in self._collapsed)

    def _sync_rows(self, visible: list[dict]) -> None:
        """把可见计划算成 QML 直接可画的行视图模型。

        每次全量重建（行数不大）：`row_view_models()` 返回新列表，
        QML 的 ListView 才会重绘；选中态由 `selectedId` 单独承载，不受重建影响。
        """
        rows: list[dict] = []
        self._plan_map.clear()
        for plan in visible:
            pid = int(plan.get("id") or 0)
            self._plan_map[pid] = plan
            rows.append(self._row_view(plan))
        self._rows_view = rows
        self._notify_rows()

    def _row_view(self, plan: dict) -> dict:
        """单行的展示数据；五态动作槽在这里判定，QML 只负责画。"""
        pid = int(plan.get("id") or 0)
        status = (plan.get("status") or "").lower()
        level = int(plan.get("child_level") or 0)
        name = plan.get("product_name") or f"ID:{plan.get('product_type_id', '')}"
        cat = capacity_line_for_category(str(plan.get("category") or ""))
        group_id = int(plan.get("group_id") or plan.get("group_number") or 0)

        # 时长：运行中显示剩余，其余显示总时长；总量放 tooltip，不在正文重复
        total = int(plan.get("calculated_time") or 0)
        if status in ("in_progress", "running"):
            rem = _fmt_remaining(plan)
            duration_text = f"剩 {rem}" if rem else _fmt_hms(total)
            duration_tip = f"总时长 {_fmt_hms(total)}"
        elif status == "ready":
            duration_text, duration_tip = "待下线", ""
        else:
            duration_text, duration_tip = _fmt_hms(total), "预计总时长"

        # 副标题：把原先散在 3 行的信息压成 1 行（信息集中）
        parts = [line_label(cat), f"{plan.get('runs', 1)}×{plan.get('parallels', 1)}"]
        parts.append(f"人物 {plan.get('char_name') or '未分配'}")
        loc = self._location_text(plan)
        if loc:
            parts.append(loc)

        icon_url, icon_fallback, icon_tip = self._icon_view(plan, cat)

        block_code, block_reason = self._block_state(plan)
        pending = int(plan.get("_pending_children") or 0)
        collapsed = bool(group_id and group_id in self._collapsed)
        can_force = self._can_force_start(plan)

        # 五态互斥，槽位恒占宽；**不出现占位符**
        kind, text, tip = "none", "", ""
        if pid and level == 0 and pending > 0:
            kind = "toggle"
            text = ("展开" if collapsed else "折叠") + f"({pending})"
        elif pid and status == "ready":
            kind, text = "complete", _COMPLETE_LABEL
            tip = "产出已跑完，点击下线（成品入库、消耗绑定流程）"
        elif pid and block_reason is None and status == "pending":
            kind, text, tip = "start", _START_LABEL, ""
        elif pid and can_force and status == "pending":
            # 缺料/蓝图流程不足是**唯一**阻塞：按钮文字直接说明堵点，仍可点，点击时二次确认
            kind, text = "start", _short_label(block_code, status)
            tip = f"{block_reason}，点击后需确认"
        elif pid:
            kind = "blocked"
            text = _short_label(block_code, status)
            tip = block_reason or _STATUS_LABELS.get(status, status) or "不可启动"

        return {
            "id": pid,
            "name": (_PARENT_GLYPH if level == 0 else "") + name,
            "indent": level * _GAP_LG,
            "iconUrl": icon_url,
            "iconFallback": icon_fallback,
            "iconTip": icon_tip,
            "statusText": _STATUS_LABELS.get(status, status),
            "statusTip": _STATUS_LABELS.get(status, status),
            "durationText": duration_text,
            "durationTip": duration_tip,
            "metaText": " · ".join(parts),
            "groupId": group_id,
            "actionKind": kind,
            "actionText": text,
            "actionTip": tip,
        }

    @staticmethod
    def _location_text(plan: dict) -> str:
        src = plan.get("facility") or ""
        dst = plan.get("output_hangar") or ""
        if src and dst:
            return f"{src}→{dst}"
        return src

    @staticmethod
    def _icon_view(plan: dict, cat: str) -> tuple[str, str, str]:
        """(图标 URL, 无图时的占位字, tooltip)。

        没有图标文件时用**类别首字**占位，不用 `category_symbol()` 的 emoji
        （⚙ 📋 ⚗ 💡）—— 它们来自符号/emoji 字体，在本窗的字体环境里会渲染成空白或豆腐块。
        """
        from ui_qml.icon_cache import item_icon_path

        type_id = int(plan.get("product_type_id") or 0)
        if type_id:
            path = item_icon_path(type_id)
            if os.path.isfile(path):
                return QUrl.fromLocalFile(path).toString(), "", ""
        label = line_label(cat) or "?"
        return "", label[:1], label

    def _select_visible_row(self, plan_id: int) -> bool:
        """把某计划设为列表选中项（行内启动 / 阻塞提示共用）。"""
        if plan_id not in self._plan_map:
            return False
        self.select_plan(plan_id)
        return True

    def _on_row_clicked(self, plan_id: int):
        self.copy_blueprint(plan_id)

    def copy_blueprint(self, plan_id: int) -> None:
        """点信息区 → 复制蓝图名（原 `_copy_blueprint`）。"""
        self._copy_blueprint(plan_id)

    def _on_row_start(self, plan_id: int):
        # 行内启动：先让该行成为选中 → 执行人物组合框跟随该计划
        self._select_visible_row(plan_id)
        self._start(plan_id)

    def _on_blocked_info(self, plan_id: int) -> None:
        """点动作槽位的短标签：选中该行 → 底部反馈区给出完整不可启动原因。"""
        self._select_visible_row(plan_id)

    def _on_row_complete(self, plan_id: int) -> None:
        """行内「可下线」→ 单行下线（本窗是小助手侧的第五条入口）。

        与计划表格单行下线共用 `complete_one_plan`，因此机库选择、蓝图流程预检、
        失败原因提示的口径完全一致。
        """
        plan = self._plan_map.get(plan_id)
        if plan is None:
            return
        if (plan.get("status") or "").lower() != "ready":
            return
        self._select_visible_row(plan_id)

        from ui_qml.views.industry.complete_plans_dialog import complete_one_plan

        if complete_one_plan(self, plan) is None:  # 取消或失败（已弹过告警）
            return
        # ⚠️ 顺序要紧：`_on_poll` 内部就会重算紧凑态文案，提示必须先落进
        # `_hint_text`；放在它之后再赋值不会触发任何重渲染。
        self._hint_text = f"已下线：{plan.get('product_name') or plan_id}"
        self.plans_changed.emit()
        self._on_poll()

    # ── 右键菜单：备注 / 部分启动 ────────────────────────

    def _on_row_context_menu(self, plan_id: int) -> None:
        """行右键 → 交给 QML 侧的 `FMenu`（`LauncherWindow.qml#rowMenu`）。

        菜单条目的可见性要读计划状态（`_can_partial_start`），故在 Python 侧判定后把
        结果传给 QML；QML 只负责画与把点击回传。原先这里自建 `QMenu` 并
        `menu.exec(QCursor.pos())`：那是从 QML 里冒出来的**原生 Widgets 菜单**，
        样式不跟主题，且 `QMenu` 要求 `self` 是 QWidget（批次 7.4 起本类已不是）。
        """
        plan = self._plan_map.get(plan_id)
        if plan is None:
            return
        if getattr(self, "_bridge", None) is None:  # 构造中途桥还没建好
            return
        self._bridge.request_context_menu(int(plan_id), bool(self._can_partial_start(plan)))

    def _can_partial_start(self, plan: dict) -> bool:
        """部分启动的可见条件。

        用户口径：只对**独立计划**与**子项全部完成的母项**开放 —— 即
        `child_level == 0` 且该行当前可启动（或可强制启动：缺料/蓝图流程不足）。
        子项行由母项需求驱动，拆了会被重放改写；母项还有未完成子项时
        `_block_state` 会给出 `children_running`/`waiting_children` 且不可强制，自然被排除。
        """
        if not plan.get("id") or plan.get("_synthetic"):
            return False
        if int(plan.get("child_level") or plan.get("sub_level") or 0) != 0:
            return False
        if str(plan.get("status") or "").lower() != "pending":
            return False
        if max(int(plan.get("parallels") or 1), 1) <= 1:
            return False
        code, _reason = self._block_state(plan)
        return code is None or self._can_force_start(plan)

    def _on_row_notes(self, plan_id: int) -> None:
        """添加备注 —— 与主表格右键「添加备注」同构，写 `production_plans.notes`。"""
        plan = self._plan_map.get(plan_id)
        if plan is None:
            return
        # 多行输入（备注可换行）：`QInputDialog.getMultiLineText` 的 QML 替身。
        # 与计划表右键「添加备注」同源同参，两边不会写出不同的行为。
        text, ok = InputQmlDialog.get_multiline_text(self, "添加备注", "输入备注内容:", str(plan.get("notes") or ""))
        if not ok:
            return
        notes = text.strip()
        get_container().plan_repo.update(plan_id, notes=notes)
        plan["notes"] = notes
        self._show_feedback(f"备注已保存：{notes}" if notes else "备注已清空")
        self.plans_changed.emit()  # 主界面备注列随之刷新
        self._on_poll()

    def _on_row_partial_start(self, plan_id: int) -> None:
        """部分启动：只启动 N 条，其余拆成一条「待生产」行留在主界面。"""
        from ui_qml.bridge.partial_start_bridge import PartialStartQmlDialog as PartialStartDialog

        plan = self._plan_map.get(plan_id)
        if plan is None or not self._can_partial_start(plan):
            return
        total = max(int(plan.get("parallels") or 1), 1)
        dlg = PartialStartDialog(plan.get("product_name") or str(plan_id), total, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        lines = dlg.lines()

        mat = plan.get("mat_hangar_id") or self._default_mat_hangar
        executor = self._executor_value(plan)

        # 预检必须按 **N 条**口径：用整条计划算会报出虚高的缺料
        preview = plan_execution.preview_partial_start(plan_id, lines, mat)
        if not preview.get("ok"):
            FMessageDialog.warning(self, "部分启动失败", preview.get("message") or "无法预览材料需求")
            return
        confirm = self._confirm_start(
            plan,
            mat,
            executor,
            lines=lines,
            shortfalls=preview.get("shortfalls") or [],
            bp_short=preview.get("bp_short"),
        )
        if confirm is None:
            return
        allow_short, allow_bp_short = confirm

        res = plan_execution.start_plan_partial(
            plan_id,
            lines,
            mat_hangar_id=mat,
            char_name=executor,
            allow_short=allow_short,
            allow_bp_short=allow_bp_short,
        )
        if not res.get("ok"):
            FMessageDialog.warning(self, "部分启动失败", res.get("message") or "未知错误")
            return
        self._show_feedback(f"已启动 {lines} 条，剩余 {total - lines} 条待生产")
        self.plans_changed.emit()
        self._on_poll()

    def _on_row_toggle(self, group_id: int) -> None:
        """折叠/展开一组子项。"""
        if group_id in self._collapsed:
            self._collapsed.discard(group_id)
        else:
            self._collapsed.add(group_id)
        self._apply_filters()

    # ── 桥的入口 ─────────────────────────────────────────
    # `LauncherBridge` 按这几个**公开名**调进来（见 `ui_qml/bridge/launcher_bridge.py`）。
    # 缺了它们不是「静默失效」而是每次行内互动都抛 `AttributeError` —— QML 里点启动/
    # 折叠/可下线、右键行，全部会断在这里。薄转发，业务仍在上面那些 `_on_*` 里。

    def row_start(self, plan_id: int) -> None:
        self._on_row_start(int(plan_id))

    def row_toggle(self, group_id: int) -> None:
        self._on_row_toggle(int(group_id))

    def row_complete(self, plan_id: int) -> None:
        self._on_row_complete(int(plan_id))

    def row_context_menu(self, plan_id: int) -> None:
        self._on_row_context_menu(int(plan_id))

    def row_notes(self, plan_id: int) -> None:
        self._on_row_notes(int(plan_id))

    def row_partial_start(self, plan_id: int) -> None:
        self._on_row_partial_start(int(plan_id))

    # ── 选中 / 底部 ──────────────────────────────────────

    def _show_feedback(self, text: str) -> None:
        """反馈按需显示 —— 无内容时不占位。"""
        self._feedback_text = text or ""
        self._notify_bottom()

    def _update_bottom(self) -> None:
        """算出 L4 底部面板的内容：未选中 = 紧凑单行；选中 = 参数摘要 + 执行人物 + 主按钮。"""
        plan = self._plan_map.get(self._selected_id or -1)
        if plan is None:
            # 紧凑态：只留一行提示，不再露出全宽空下拉
            self._bottom_expanded = False
            self._params_text = ""
            self._executor_options = []
            self._executor_index = 0
            self._main_btn_text = ""
            self._main_btn_tip = ""
            self._main_btn_visible = False
            self._feedback_text = ""
            self._notify_bottom()
            return

        # 选中了具体行 → 之前那条「已下线：X」的常驻提示作废
        self._hint_text = "在上方列表选一条产线"
        self._bottom_expanded = True

        cat = capacity_line_for_category(str(plan.get("category") or ""))
        runs = plan.get("runs", 1)
        parallels = plan.get("parallels", 1)
        facility = plan.get("facility") or "—"
        output = plan.get("output_hangar") or "—"
        status = (plan.get("status") or "").lower()
        cost = plan.get("material_cost") or 0
        name = plan.get("product_name") or f"ID:{plan.get('product_type_id', '')}"
        # 产品名放在可换行的摘要行，而不是按钮上 —— 否则长名会把按钮撑爆、挤掉执行人物下拉
        parts = [name, line_label(cat), f"流程 {runs}×{parallels}", f"{facility} → {output}"]
        if status in ("in_progress", "running"):
            rem = _fmt_remaining(plan)
            if rem:
                parts.append(f"剩余 {rem}")
        if cost:
            parts.append(f"预计成本 {cost:,.0f} ISK")
        self._params_text = " · ".join(parts)

        # 执行人物下拉（含剩余容量）—— 注意别复用 `name`（那是产品名）
        options: list[dict] = []
        chars = list(self._char_list)
        plan_char = (plan.get("char_name") or "").strip()
        if plan_char and plan_char not in chars:
            chars.insert(0, plan_char)
        index = 0
        for char_name in chars:
            remaining = max_lines_for_category(char_name, cat) - int(self._usage.get(char_name or "", {}).get(cat, 0))
            options.append({"label": f"{char_name}（剩 {max(remaining, 0)} 条）", "value": char_name})
            if plan_char and char_name == plan_char:
                index = len(options) - 1
        self._executor_options = options
        self._executor_index = index
        self._feedback_text = ""

        # 主按钮
        reason = self._block_reason(plan)
        force = reason is not None and self._can_force_start(plan)
        if status == "ready":
            # 待下线行的唯一动作是下线（选产出机库 → 成品入库、消耗绑定流程）。
            # 旧版这里走 else 分支弹「不可启动：待下线」——与行上「?」是同一类毛病。
            self._main_btn_text = "下线"
            self._main_btn_tip = f"{name} 下线（产出成品入库，不可逆）"
            self._main_btn_visible = True
        elif reason is None or force:
            qty = 1
            try:
                qty = plan_execution.output_per_run(int(plan.get("product_type_id") or 0))
            except Exception:
                log.exception("产量查询失败 type_id=%s", plan.get("product_type_id"))
                qty = 1
            total = max(int(runs or 1), 1) * max(int(parallels or 1), 1) * qty
            # 缺料是唯一阻塞时仍给按钮（点击后二次确认），文案点明是强制启动 ——
            # 否则会出现「行上显示启动、选中反而报不可启动」的自相矛盾
            self._main_btn_text = f"强制启动 x {total}" if force else f"启动 x {total}"
            self._main_btn_tip = f"{name} × {total}"
            self._main_btn_visible = True
        else:
            self._main_btn_visible = False
            self._main_btn_text = ""
            self._main_btn_tip = ""
            self._feedback_text = f"不可启动：{reason}"

        self._notify_bottom()

    # ── L4 取数接口 ──────────────────────────────────────

    def bottom_expanded(self) -> bool:
        return self._bottom_expanded

    def bottom_hint_text(self) -> str:
        return self._hint_text

    def params_text(self) -> str:
        return self._params_text

    def executor_options(self) -> list[dict]:
        return self._executor_options

    def executor_index(self) -> int:
        return self._executor_index

    def set_executor_index(self, index: int) -> None:
        if 0 <= int(index) < len(self._executor_options):
            self._executor_index = int(index)

    def main_button_text(self) -> str:
        return self._main_btn_text

    def main_button_tip(self) -> str:
        return self._main_btn_tip

    def main_button_visible(self) -> bool:
        return self._main_btn_visible

    def feedback_text(self) -> str:
        return self._feedback_text

    def _copy_blueprint(self, plan_id: int) -> None:
        plan = self._plan_map.get(plan_id)
        if plan is None:
            return
        from services.ui_data_service import resolve_plan_blueprint_name

        bp_name = resolve_plan_blueprint_name(plan, db=get_container().db)
        if not bp_name:
            self._show_feedback("该计划无蓝图信息")
            return
        QGuiApplication.clipboard().setText(bp_name)
        self._show_feedback(f"「{bp_name}」已复制进剪切板")

    # ── 启动 ─────────────────────────────────────────────

    def _confirm_start(
        self,
        plan: dict,
        mat: int | None,
        executor: str | None,
        *,
        lines: int,
        shortfalls: list[dict],
        bp_short: str | None,
    ) -> tuple[bool, bool] | None:
        """启动前的公共把关：超员软提示 + 软阻塞确认（整条启动与部分启动共用）。

        ``lines`` 是**本次启动的产线条数**（整条启动 = parallels、部分启动 = N）：
        超员判断必须用它，否则部分启动会按整条线数误报超员。
        Returns: (allow_short, allow_bp_short)；用户取消返回 None。
        """
        # 软提示：执行人物超员（沿用旧向导，不硬拦）
        if executor:
            cat = capacity_line_for_category(str(plan.get("category") or ""))
            active = int(self._usage.get(executor or "", {}).get(cat, 0))
            mx = max_lines_for_category(executor, cat)
            if active + max(int(lines), 1) > mx:
                if not FMessageDialog.question(
                    self,
                    "人物产线超员",
                    f"{executor} 当前占用 {active}/{mx} 条{line_label(cat)}线，启动后超员。仍要启动？",
                ):
                    return None

        reasons: list[str] = []
        if shortfalls:
            listing = "\n".join(f"  {r.get('name')}: 缺 {r.get('missing'):,.0f}" for r in shortfalls[:10])
            if len(shortfalls) > 10:
                listing += f"\n  … 等 {len(shortfalls)} 种"
            reasons.append(f"材料不足：\n{listing}")
        if bp_short:
            reasons.append(f"蓝图流程不足：{bp_short}")
        if not reasons:
            return (False, False)
        if not can_force_start(plan, mat, self._all_plans, shortfall_count=len(shortfalls), bp_short=bp_short):
            # 除软阻塞外还有别的硬阻塞（无蓝图 / 等子项）→ 不该走到这里，兜底拦住
            FMessageDialog.warning(self, "启动失败", self._block_reason(plan) or "当前不可启动")
            return None
        if not FMessageDialog.question(
            self,
            "启动前确认",
            "\n\n".join(reasons) + "\n\n是否强制启动？\n"
            "材料按现有库存扣减、缺口记待补；蓝图**不会**自动补流程或换绑，"
            "完成时按实际可用流程消耗。\n"
            "由此产生的账面偏差，请稍后用「蓝图管理 → 粘贴导入蓝图 → 全量同步」矫正。",
        ):
            return None
        return (bool(shortfalls), bool(bp_short))

    def _start(self, plan_id: int) -> None:
        plan = self._plan_map.get(plan_id)
        if plan is None:
            return
        executor = self._executor_value(plan)
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar

        # 软阻塞预检：材料缺口 / 蓝图流程不足 —— 两者都可强制启动（与计划表格同口径）
        shortfalls: list[dict] = []
        if mat:
            try:
                shortfalls = [
                    r
                    for r in plan_execution.check_materials(plan, mat, stock=self._stock_cache.get(int(mat)))
                    if (r.get("missing") or 0) > 0
                ]
            except Exception:
                log.exception("材料校验失败 plan_id=%s", plan_id)
                shortfalls = []
        bp_short = self._bp_short(plan)

        confirm = self._confirm_start(
            plan,
            mat,
            executor,
            lines=max(int(plan.get("parallels") or 1), 1),
            shortfalls=shortfalls,
            bp_short=bp_short,
        )
        if confirm is None:
            return
        allow_short, allow_bp_short = confirm

        res = plan_execution.start_plan(
            plan,
            mat_hangar_id=mat,
            char_name=executor,
            allow_short=allow_short,
            allow_bp_short=allow_bp_short,
        )
        if res.get("ok"):
            self._show_feedback(f"已启动：{plan.get('product_name', '')}")
            self.plans_changed.emit()
            self._on_poll()
        else:
            FMessageDialog.warning(self, "启动失败", res.get("message", "未知错误"))

    def _executor_value(self, plan: dict | None = None) -> str | None:
        """底部执行人物下拉当前选中的人。

        下拉未初始化（还没选中过任何行，例如行内直接点「启动」）时，
        退回**本次要启动的那条计划**自身的人物 —— 这是旧实现的口径，
        退回「当前选中行」会拿到 None（选中行与本次启动的行并不总是同一条）。
        """
        if self._executor_options and 0 <= self._executor_index < len(self._executor_options):
            return str(self._executor_options[self._executor_index]["value"])
        fallback = plan if plan is not None else (self._plan_map.get(self._selected_id or -1) or {})
        return (fallback.get("char_name") or "").strip() or None

    def main_action(self) -> None:
        """底部主按钮：待下线走下线流程，其余走启动。"""
        if self._selected_id is None:
            return
        plan = self._plan_map.get(self._selected_id)
        if plan is not None and (plan.get("status") or "").lower() == "ready":
            self._on_row_complete(self._selected_id)
            return
        self._start(self._selected_id)

    # ── 过滤器 ───────────────────────────────────────────

    def _on_filter_changed(self):
        """筛选变化 → 重算可见集（QML 侧改的是索引，经 set_*_filter_index 进来）。"""
        self._apply_filters()

    def focus_character(self, char_name: str | None) -> None:
        """把人物过滤定位到指定角色（右键入口初始定位）；None → 全部。"""
        if char_name is None:
            index = 0
        elif char_name == "":
            index = 1
        elif char_name in self._char_list:
            index = self._char_list.index(char_name) + 2
        else:
            index = 0
        if index != self._char_filter_index:
            self._char_filter_index = index
            self._notify_toolbar()
            self._apply_filters()

    def window_visibility_changed(self, visible: bool) -> None:
        """窗口变为可见 —— 等价于原 `showEvent`（QML 的 `onVisibleChanged` 调进来）。

        单实例复用时必须重启定时器：关闭时停表后不会自动恢复，否则「关闭再打开」
        得到的是不刷新倒计时/计划列表的死窗口。
        """
        if not visible or getattr(self, "_tick_timer", None) is None:
            return
        self._tick_timer.start()
        self._poll_timer.start()
        self._on_poll()

    def window_closing(self) -> None:
        """窗口即将关闭 —— 等价于原 `closeEvent`（QML 的 `onClosing` 调进来）。

        与旧行为的唯一差别：原来还跟着一次 `hideEvent`，而本类从来没有覆写它 ——
        所以**单纯 `hide()` 不停表**这一条也照旧。
        """
        if getattr(self, "_tick_timer", None) is not None:
            self._tick_timer.stop()
            self._poll_timer.stop()
