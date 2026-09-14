"""产线启动小助手的 Python ↔ QML 桥。

覆盖 L1–L4 四区（工具条 / 占用面板 / 产线列表 / 详情执行面板）。

**只做转发与整形**：业务动作仍留在 `ui_pyside6/views/industry/production_launcher.py`
的 `ProductionLauncher` 里；本类把 QML 的调用翻译成对它的方法调用，
并把「行 / 占用条」这类需要逐项算的业务数据取回来交给 QML 渲染。

QML 侧以 context property `bridge` 注入（见 `ui_qml/host.PageHost`）。
"""

from __future__ import annotations

# `_page` 刻意是 Any：本模块不能导入 ui_pyside6.views（会形成「包初始化 → 页面 →
# ui_qml → 包初始化」的循环），于是它的每个返回值对 mypy 都是 Any。
# 这些属性本就是「原样转发给 QML」的通道，逐处 cast 只会淹没真正的问题。
# mypy: disable-error-code="no-any-return"
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

__all__ = ["LauncherBridge"]


class LauncherBridge(QObject):
    """产线启动小助手桥。`_page` 是 `ProductionLauncher` 实例（避免循环导入用 Any）。"""

    #: 工具条（筛选文案 / 置顶态）变化
    toolbarChanged = Signal()
    #: 占用面板变化
    occupancyChanged = Signal()
    #: 产线列表变化
    rowsChanged = Signal()
    #: 底部面板变化
    bottomChanged = Signal()
    #: 请求 QML 把列表滚到某行 / 选中某行
    selectionRequested = Signal(int)
    #: 1s 心跳（只改运行中行的剩余时长，不重建列表）
    tickChanged = Signal()

    def __init__(self, page: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._page = page

    # ── L1 工具条 ─────────────────────────────────────────────

    @Property(str, constant=True)
    def titleText(self) -> str:
        return "产线启动小助手"

    @Property(list, constant=True)
    def lineFilters(self) -> list[dict]:
        return self._page.line_filter_options()

    @Property(list, notify=toolbarChanged)
    def charFilters(self) -> list[dict]:
        return self._page.char_filter_options()

    @Property(int, notify=toolbarChanged)
    def lineFilterIndex(self) -> int:
        return self._page.line_filter_index()

    @Property(int, notify=toolbarChanged)
    def charFilterIndex(self) -> int:
        return self._page.char_filter_index()

    @Slot(int)
    def setLineFilterIndex(self, index: int) -> None:
        self._page.set_line_filter_index(int(index))

    @Slot(int)
    def setCharFilterIndex(self, index: int) -> None:
        self._page.set_char_filter_index(int(index))

    @Property(str, notify=toolbarChanged)
    def filterSummary(self) -> str:
        return self._page.filter_summary_text()

    @Property(bool, notify=toolbarChanged)
    def pinned(self) -> bool:
        return self._page.is_pinned()

    @Slot(bool)
    def setPinned(self, value: bool) -> None:
        self._page.set_pinned(bool(value))

    # ── L2 占用面板 ───────────────────────────────────────────

    @Property(bool, notify=occupancyChanged)
    def occupancyCollapsed(self) -> bool:
        return self._page.occupancy_collapsed()

    @Slot()
    def toggleOccupancy(self) -> None:
        self._page.toggle_occupancy()

    @Property(str, notify=occupancyChanged)
    def occupancySummary(self) -> str:
        return self._page.occupancy_summary()

    @Property(list, notify=occupancyChanged)
    def occupancyRows(self) -> list[dict]:
        """每角色一行：{name, nameWidth, lines:[{label, color, active, max, cap}],
        statusText, statusColor, slotTotal}。"""
        return self._page.occupancy_rows()

    # ── L3 产线列表 ───────────────────────────────────────────

    @Property(list, notify=rowsChanged)
    def rows(self) -> list[dict]:
        """每行：{id, name, indent, iconUrl, iconFallback, iconTip, statusText,
        statusTip, durationText, durationTip, metaText, planStatus,
        actionKind, actionText, actionTip}。"""
        return self._page.row_view_models()

    @Property(bool, notify=rowsChanged)
    def isEmpty(self) -> bool:
        return self._page.is_empty()

    @Property(int, notify=rowsChanged)
    def selectedId(self) -> int:
        return self._page.selected_plan_id()

    @Property(int, notify=rowsChanged)
    def rowHeight(self) -> int:
        return self._page.row_height()

    @Property(int, notify=rowsChanged)
    def actionSlotWidth(self) -> int:
        """动作槽固定宽度（按全部短标签的最宽者算）—— 五个按钮切换时占位不变，
        避免行动作区左右跳动。"""
        return self._page.action_slot_width()

    @Property(int, notify=tickChanged)
    def tickRevision(self) -> int:
        """1s 心跳计数。

        QML 的 `model` 是普通 `var` 列表，改字典里的值**不会**触发重绘；
        duration 的绑定显式读一下它，才能跟着重新求值（比整表重置便宜，
        也不会把滚动位置与选中态冲掉）。
        """
        return self._page.tick_revision()

    @Slot(int)
    def selectRow(self, plan_id: int) -> None:
        self._page.select_plan(int(plan_id))

    @Slot(int)
    def rowClicked(self, plan_id: int) -> None:
        self._page.copy_blueprint(int(plan_id))

    @Slot(int)
    def rowStart(self, plan_id: int) -> None:
        self._page.row_start(int(plan_id))

    @Slot(int)
    def rowToggle(self, group_id: int) -> None:
        self._page.row_toggle(int(group_id))

    @Slot(int)
    def rowBlocked(self, plan_id: int) -> None:
        self._page.select_plan(int(plan_id))

    @Slot(int)
    def rowComplete(self, plan_id: int) -> None:
        self._page.row_complete(int(plan_id))

    @Slot(int)
    def rowContextMenu(self, plan_id: int) -> None:
        self._page.row_context_menu(int(plan_id))

    # ── L4 详情 / 执行面板 ────────────────────────────────────

    @Property(bool, notify=bottomChanged)
    def bottomExpanded(self) -> bool:
        return self._page.bottom_expanded()

    @Property(str, notify=bottomChanged)
    def bottomHint(self) -> str:
        return self._page.bottom_hint_text()

    @Property(str, notify=bottomChanged)
    def paramsText(self) -> str:
        return self._page.params_text()

    @Property(list, notify=bottomChanged)
    def executors(self) -> list[dict]:
        return self._page.executor_options()

    @Property(int, notify=bottomChanged)
    def executorIndex(self) -> int:
        return self._page.executor_index()

    @Slot(int)
    def setExecutorIndex(self, index: int) -> None:
        self._page.set_executor_index(int(index))

    @Property(str, notify=bottomChanged)
    def mainButtonText(self) -> str:
        return self._page.main_button_text()

    @Property(str, notify=bottomChanged)
    def mainButtonTip(self) -> str:
        return self._page.main_button_tip()

    @Property(bool, notify=bottomChanged)
    def mainButtonVisible(self) -> bool:
        return self._page.main_button_visible()

    @Property(str, notify=bottomChanged)
    def feedback(self) -> str:
        return self._page.feedback_text()

    @Slot()
    def mainAction(self) -> None:
        self._page.main_action()

    # ── 刷新通知（由页面在数据变化后调用） ──────────────────────

    def notify_toolbar(self) -> None:
        self.toolbarChanged.emit()

    def notify_occupancy(self) -> None:
        self.occupancyChanged.emit()

    def notify_rows(self) -> None:
        self.rowsChanged.emit()

    def notify_bottom(self) -> None:
        self.bottomChanged.emit()

    def notify_tick(self) -> None:
        self.tickChanged.emit()

    def request_selection(self, plan_id: int) -> None:
        self.selectionRequested.emit(int(plan_id))
