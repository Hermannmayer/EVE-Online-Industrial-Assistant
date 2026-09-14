"""工业页页面骨架的 Python ↔ QML 桥。

覆盖阶段 2b 前的五个 Widgets 子控件：顶部工具栏（蓝图导入 / 价格来源 / 视图筛选）、
底部状态栏（统计 + 采购汇总 + 全部下线）、功能按钮组、甘特图。

**只做转发**：业务动作仍留在 `ui_pyside6/views/industry_view.py` 的 `IndustryPage`
里，QML 的每次交互都调 `bridge.<方法>` 转过去，保证迁移期只有一份业务实现。

QML 侧以 context property `bridge` 注入（见 `ui_qml/host.PageHost`）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core.constants import TRADE_HUBS
from services.terminology import term
from services.user_settings import get_price_settings, save_settings

__all__ = ["IndustryBridge", "FILTERS", "PRICE_TYPES"]

#: 计划状态筛选（与旧 TopToolbar.FILTERS 一致，顺序即下拉项顺序）
FILTERS: tuple[str, ...] = ("全部", "待排", "运行中", "待下线", "已完成")

#: 价格类型：(值, 显示名)。显示名走术语中心，不写死中文。
PRICE_TYPES: tuple[tuple[str, str], ...] = (
    ("sell", term.label("sell_price")),
    ("buy", term.label("buy_price")),
)

#: 蓝图输入框的搜索防抖（ms），与旧 TopToolbar 一致
_SEARCH_DEBOUNCE_MS = 200
#: 少于该长度不触发搜索
_MIN_SEARCH_LEN = 2


class IndustryBridge(QObject):
    """工业页桥。`_page` 是 `IndustryPage` 实例（避免循环导入用 Any 标注）。"""

    #: 状态栏文案变化
    statusChanged = Signal()
    #: 统计/采购汇总变化
    statsChanged = Signal()
    #: 价格设置变化（QML 重读 priceSettings）
    priceSettingsChanged = Signal()
    #: 蓝图输入的搜索候选变化
    suggestionsChanged = Signal()
    #: 筛选条件变化
    filterChanged = Signal()
    #: 视图模式变化（数据视图 ↔ 甘特图）
    viewModeChanged = Signal()
    #: 甘特图数据变化
    ganttChanged = Signal()

    def __init__(self, page: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._page = page
        self._filter_index = 0
        self._view_mode = "data"
        self._suggestions: list[str] = []
        self._last_query = ""
        self._stats_text = "计划总数: 0 | 运行中: 0 | 待排: 0 | 产线(备料): 0"
        self._material_text = "备料中采购: 0 ISK | 体积: 0.0 m3"
        self._message = ""
        self._plan_total = 0
        self._complete_all_text = ""
        self._complete_all_visible = False
        self._gantt_rows: list[dict] = []
        self._gantt_max_hours = 48
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._run_search)
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self.clear_message)

    # ── 页面抬头 ──────────────────────────────────────────────

    @Property(str, constant=True)
    def titleText(self) -> str:
        return "生产规划"

    @Property(str, notify=statsChanged)
    def planCountText(self) -> str:
        return f"共 {self._plan_total} 条计划"

    # ── 筛选 ─────────────────────────────────────────────────

    @Property(list, constant=True)
    def filterOptions(self) -> list[str]:
        return list(FILTERS)

    @Property(int, notify=filterChanged)
    def filterIndex(self) -> int:
        return self._filter_index

    @Slot(int)
    def setFilterIndex(self, index: int) -> None:
        index = max(0, min(int(index), len(FILTERS) - 1))
        if index == self._filter_index:
            return
        self._filter_index = index
        self.filterChanged.emit()
        self._page.load_plans()

    def current_filter(self) -> str:
        """当前筛选文案（`IndustryPage` 读它组装查询条件）。"""
        return FILTERS[self._filter_index] if 0 <= self._filter_index < len(FILTERS) else FILTERS[0]

    # ── 视图模式 ──────────────────────────────────────────────

    @Property(str, notify=viewModeChanged)
    def viewMode(self) -> str:
        return self._view_mode

    @Slot(str)
    def setViewMode(self, mode: str) -> None:
        mode = "gantt" if mode == "gantt" else "data"
        if mode == self._view_mode:
            return
        self._view_mode = mode
        self.viewModeChanged.emit()
        if mode == "gantt":
            self._page.refresh_gantt()

    @Property(bool, notify=viewModeChanged)
    def statusVisible(self) -> bool:
        """甘特图模式下隐藏状态栏与功能按钮（与旧 `_on_view_changed` 一致）。"""
        return self._view_mode == "data"

    # ── 蓝图导入 ──────────────────────────────────────────────

    @Property(list, notify=suggestionsChanged)
    def suggestions(self) -> list[str]:
        return self._suggestions

    @Slot(str)
    def requestSuggestions(self, text: str) -> None:
        text = text.strip()
        self._last_query = text
        if len(text) < _MIN_SEARCH_LEN:
            self._search_timer.stop()
            self._set_suggestions([])
            return
        self._search_timer.start(_SEARCH_DEBOUNCE_MS)

    @Slot()
    def clearSuggestions(self) -> None:
        self._search_timer.stop()
        self._last_query = ""
        self._set_suggestions([])

    def _run_search(self) -> None:
        from ui_pyside6.views.compare.compare_chart import search_items

        # 用**发起时的文本**搜，不回头去问输入框：用户可能在防抖窗口里又改了字，
        # 那时该等下一次触发，而不是拿新文本去配旧候选。
        text = self._last_query
        if len(text) < _MIN_SEARCH_LEN:
            return
        items = search_items(text)
        out: list[str] = []
        for i in items:
            zh, en = i.get("zh_name"), i.get("en_name")
            out.append(f"{zh} ({en})" if zh else str(en))
        self._set_suggestions(out)

    def _set_suggestions(self, value: list[str]) -> None:
        if value == self._suggestions:
            return
        self._suggestions = value
        self.suggestionsChanged.emit()

    @Slot(str)
    def addPlan(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.show_message("请输入蓝图名称或粘贴蓝图信息", timeout=4000)
            return
        self.clearSuggestions()
        self._page.add_plan(text)

    @Slot()
    def openManufacturableBrowser(self) -> None:
        self._page.open_manufacturable_browser()

    # ── 价格来源 ──────────────────────────────────────────────

    @Property(list, constant=True)
    def hubs(self) -> list[str]:
        return list(TRADE_HUBS)

    @Property(list, constant=True)
    def priceTypes(self) -> list[dict]:
        return [{"value": value, "label": label} for value, label in PRICE_TYPES]

    @Property(dict, notify=priceSettingsChanged)
    def priceSettings(self) -> dict:
        return get_price_settings()

    @Slot(str, "QVariant")
    def setPriceSetting(self, key: str, value: Any) -> None:
        """任一价格设置变化 → 落盘 + 通知外部重算。

        键名与 `services.user_settings` 的 `price_settings` 字段一致：
        `mat_hub` / `mat_price_type` / `mat_mult` / `prod_hub` / `prod_price_type` / `prod_mult`。
        """
        settings = dict(get_price_settings())
        if settings.get(key) == value:
            return
        settings[key] = value
        save_settings({"price_settings": settings})
        self.priceSettingsChanged.emit()
        self._page.load_plans()

    @Slot()
    def reloadPriceSettings(self) -> None:
        """页面重新可见时同步一次。

        材料倍率与仓库页（导入预览 / 批量设置成本价）是**同一个** settings 字段，
        在那边改完回到本页时不能还停在旧值。
        """
        self.priceSettingsChanged.emit()

    # ── 状态栏 ────────────────────────────────────────────────

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        """状态栏文案：有临时消息时显示消息，否则显示统计。"""
        return self._message or self._stats_text

    @Property(str, notify=statsChanged)
    def completeAllText(self) -> str:
        return self._complete_all_text

    @Property(bool, notify=statsChanged)
    def completeAllVisible(self) -> bool:
        return self._complete_all_visible

    @Property(str, notify=statsChanged)
    def materialText(self) -> str:
        return self._material_text

    def update_stats(self, plans: list[dict]) -> None:
        """按计划集刷新统计与「全部下线」按钮（原 `StatusBar.update_stats`）。"""
        self._plan_total = len(plans)
        running = sum(1 for p in plans if p.get("status") in ("in_progress", "running"))
        pending = sum(1 for p in plans if p.get("status") == "pending")
        ready = sum(1 for p in plans if p.get("status") == "ready")
        mats_lines = sum(int(p.get("parallels") or 0) for p in plans if p.get("materials_ready", 0))
        self._stats_text = f"计划总数: {len(plans)} | 运行中: {running} | 待排: {pending} | 产线(备料): {mats_lines}"
        self._complete_all_visible = ready > 0
        self._complete_all_text = f"全部下线 ({ready})" if ready else "全部下线"
        self.statsChanged.emit()
        self.statusChanged.emit()

    def update_material(self, total_cost: float, volume: float) -> None:
        self._material_text = f"备料中采购: {total_cost:,.0f} ISK | 体积: {volume:,.1f} m3"
        self.statsChanged.emit()

    def show_message(self, text: str, timeout: int = 0) -> None:
        """临时消息；`timeout>0` 时到期自动恢复统计文案。"""
        self._message = text
        self.statusChanged.emit()
        self._message_timer.stop()
        if timeout > 0:
            self._message_timer.start(int(timeout))

    @Slot()
    def clear_message(self) -> None:
        if not self._message:
            return
        self._message = ""
        self.statusChanged.emit()

    @Slot()
    def savePrices(self) -> None:
        self._page.save_prices()

    @Slot()
    def completeAll(self) -> None:
        self._page.complete_all()

    # ── 功能按钮 ──────────────────────────────────────────────

    @Slot()
    def refreshPrices(self) -> None:
        self._page.refresh_prices()

    @Slot()
    def launchWizard(self) -> None:
        self._page.open_launcher(None)

    @Slot()
    def openProcurement(self) -> None:
        self._page.open_procurement()

    @Slot()
    def openBlueprintList(self) -> None:
        self._page.open_blueprint_list()

    @Slot()
    def openMaterialsSummary(self) -> None:
        self._page.open_materials_summary()

    @Slot()
    def openOutputSummary(self) -> None:
        self._page.open_output_summary()

    @Slot()
    def openCharUsage(self) -> None:
        self._page.open_char_usage()

    # ── 甘特图 ────────────────────────────────────────────────

    @Property(list, notify=ganttChanged)
    def ganttRows(self) -> list[dict]:
        return self._gantt_rows

    @Property(int, notify=ganttChanged)
    def ganttMaxHours(self) -> int:
        return self._gantt_max_hours

    def set_gantt_plans(self, plans: list[dict]) -> None:
        """按计划集重算甘特条（排期逻辑在 `services.plan_gantt`，这里只搬运）。"""
        from services.plan_gantt import build_rows, max_hours

        self._gantt_rows = build_rows(plans)
        self._gantt_max_hours = max_hours(self._gantt_rows)
        self.ganttChanged.emit()
