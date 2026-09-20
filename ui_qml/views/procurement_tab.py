"""采购小助手 —— **控制器**（渲染已整体交给 QML）。

对照改造前：本类原本是「QDialog + 满屏 Widgets 控件」。阶段 4b 把渲染交给
`ui_qml/qml/pages/ProcurementWindow.qml`（经 `ProcurementBridge` 转发），
本类退化为**控制器 + QQuickWidget 宿主**；批次 7.4 再把宿主也交出去 —— QML 根
从 `Item` 换成 `Window`，本类从 `QDialog` 退成 **`QObject`**，与
`production_launcher` 同款（那是阶段 2c 就定下的非模态工具窗终态）。

因此**业务一行未改**，改的只是「谁来画」：聚合采购需求、删除/手改的回放、
轮询同步、置顶、完成所有，全部留在本类。

非模态独立工具窗：可置顶悬浮于游戏之上，不影响主界面操作。
计划/库存变化由 10s 轮询同步（见 `window_visibility_changed`）；本窗入库/下线后发
`plans_changed` 通知主界面刷新。

批次 7.4：QML 根从 `Item` 换成 `Window`，本类从 `QDialog` 退成 **`QObject`** ——
窗口语义（标题 / 尺寸 / 顶层 / 关闭 / Esc / 显示隐藏事件）由 QML 的 `Window` 自持，
Python 侧只在 `show()` / `raise_()` / `activateWindow()` 上转发（调用方一行未改）。

纯函数（名称解析 / 分区 / 复制文本 / 行装配）在 `ui_qml.bridge.procurement_bridge` 里，
桥与本类共用同一份；本模块把它们再导出，方便既有调用方与测试。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

from core.logger import log
from ui_qml.bridge.procurement_bridge import (
    _SORT_FIELDS,
    ProcurementBridge,
    copy_cell_text,
    display_name,
    split_sections,
)
from ui_qml.pin_utils import apply_window_pin, reassert_pin

__all__ = [
    "ProcurementDialog",
    "copy_cell_text",
    "display_name",
    "split_sections",
]

_QML_FILE = "pages/ProcurementWindow.qml"


class ProcurementDialog(QObject):
    """待采购窗口 —— 根据生产计划和库存计算需要采购的材料（控制器；窗口在 QML 侧）。"""

    plans_changed = Signal()  # 入库/下线后通知主界面重载计划

    POLL_INTERVAL_MS = 10_000
    COPY_HINT_MS = 5_000  # 底部复制提示的停留时长

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        #: QML 根是 `Window`，实例化出来的就是本窗（`_build_window` 里赋值）。
        self._window: QQuickWindow | None = None
        self._engine: QQmlEngine | None = None
        self._component: QQmlComponent | None = None
        #: 窗口标题（`_reload_plans` 按材料机库改写，桥的 `titleText` 读它）
        self._window_title = "待采购 - 材料需求"

        self._active_plans: list[dict] = []
        self._default_mat_hangar_id: int | None = None
        self._rows: list[dict] = []
        #: 分区后的两份行（按 to_buy 切分）；桥按 `section` 名读它们
        self._sections: dict[str, list[dict]] = {"buy": [], "stock": []}
        #: 每个分区各自的排序状态 (列号, 是否升序)。与「两表各自排序」的原行为一致
        self._sort_state: dict[str, tuple[int, bool]] = {"buy": (-1, True), "stock": (-1, True)}
        self._price_type = "sell"
        self._hub_text = "Jita"
        self._manual_overrides: dict[int, float] = {}  # 用户手改的采购量，重算后回放
        self._deleted_ids: set[int] = set()  # 本次打开期间删除的行；关闭窗口即清空
        self._summary_text = ""
        self._copy_hint_text = ""
        self._complete_all_text = ""
        self._pinned = False
        self._poll_timer: QTimer | None = None
        self._copy_hint_timer: QTimer | None = None

        self._build_window()
        self._reload_plans()
        self._restore_pin()

    # ── 窗口 ──────────────────────────────────────────────────
    #
    # 批次 7.4：QML 根从 `Item` 换成 `Window`，本类不再是 QDialog，于是窗口语义一分为二：
    #   * 声明性的（标题 / 初始尺寸 / 最小尺寸 / 顶层属性）在 QML 里；
    #   * 命令式的（显示 / 前置 / 激活 / 关闭 / Esc）在这里转发给 `self._window`。
    # `industry_view.py` 调用的 `show()` / `raise_()` / `activateWindow()` 因此一行未改。

    def _build_window(self) -> None:
        """把 `ProcurementWindow.qml`（根元素是 `Window`）实例化成本窗。

        ⚠️ 根是 `Window` 时 `QQuickView` / `QQuickWidget` 都用不了（两者的根必须是 `Item`），
        只能走 `QQmlEngine` + `QQmlComponent` —— 与 `ui_qml/splash_window.py` 同法，
        也从 `component.errors()` 里拿结构化错误（加载失败**直接抛**，不静默成空白窗口）。
        """
        from ui_qml.bridge import CONTEXT_NAME, theme_singleton
        from ui_qml.host import QML_ROOT

        self._bridge = ProcurementBridge(self, self)
        self._bridge.plansChanged.connect(self.plans_changed)
        engine = QQmlEngine()
        self._engine = engine
        ctx = engine.rootContext()
        ctx.setContextProperty(CONTEXT_NAME, theme_singleton())
        ctx.setContextProperty("bridge", self._bridge)
        path = QML_ROOT / _QML_FILE
        component = QQmlComponent(engine)
        component.setData(path.read_bytes(), QUrl.fromLocalFile(str(path)))
        if component.isError():
            raise RuntimeError("; ".join(e.toString() for e in component.errors()))
        self._component = component
        window = component.create(ctx)
        if not isinstance(window, QQuickWindow):
            raise RuntimeError(f"{_QML_FILE} 的根元素不是 Window：{window!r}")
        # 所有权：**引擎挂到窗口名下**（`QQuickView` 自己就是 `new QQmlEngine(view)` 这么干的）。
        # 于是「窗口先销毁、引擎随后跟着走」由 Qt 的父子关系保证，不依赖 Python 的析构顺序 ——
        # 反过来（引擎先走、场景还在）时，任何一次绑定重算都会撞上被拆掉的上下文。
        # ⚠️ 不能反过来把窗口挂到控制器名下：PySide 的 `QWindow.setParent` 只收 `QWindow`。
        component.setParent(engine)
        engine.setParent(window)
        self._window = window

    # ── 窗口命令（转发给 QML 的 `Window`）──────────────────────

    def show(self) -> None:
        if self._window is not None:
            self._window.show()

    def hide(self) -> None:
        if self._window is not None:
            self._window.hide()

    def close(self) -> None:
        """关窗（X 按钮走 QML 的 `onClosing`，这里走程序化路径）。

        ⚠️ `QWindow.close()` **只在窗口当前可见时才发 `closing`**（Qt 的语义：已经关着的
        窗口再关一次没有意义）。而「关过」在本窗是一件**状态** —— 它是「本次会话结束」的
        分界（`_deleted_ids` 在这条线上清空）。所以先把收尾走完（幂等），再让窗口真的关。
        """
        if self._window is None:
            return
        self.window_closing()
        self._window.close()

    def dispose(self) -> None:
        """退出时**拆掉** QML 场景（不是关窗）。由页面关机钩子调，见 `IndustryPage.shutdown`。

        只 `close()` 是不够的：关窗只是隐藏，QML 树与 `QQmlEngine` 都还活着。等 Python
        收尾把 `Theme` 单例（`theme_bridge._singleton`，模块级全局，解释器收尾时会被清掉）
        回收之后，场景里那些 `Theme.xxx` 绑定就会重算并对着 null 求值 —— 实测一次退出刷
        出 **528 条** `Cannot read property 'xxx' of null`，全出自我们自己这几个 qml。

        顺序与外壳 `ShellWindow._teardown_qml` 同一条：**先删根对象（= 窗口）连同场景，
        再让引擎/组件沿父子链走**。反过来（引擎先走、场景还在）撞的是同一堵墙。

        所有权：`QQmlComponent.create()` 把根对象的归属转给调用方（= 本类），
        而 `_build_window` 里挂了 `component → engine → window` 的父子链。
        所以先摘掉 Python 侧对 engine / component 的引用，最后丢 window —— PySide 立刻
        析构窗口（连同 QML 场景），父子链再把引擎与组件一并收走。
        """
        window = self._window
        if window is None:
            return
        self._window = None
        self._component = None
        self._engine = None
        window.close()
        # ⚠️ **不能靠丢引用析构**：window 是 engine 的 QObject 父，而 engine 又持有根对象
        # （就是 window）—— 跨 Python/C++ 的引用环，丢引用后两边都活着（实测 `isValid` 仍为真、
        # 窗口还挂在 `QGuiApplication.allWindows()` 里）。走 `deleteLater()`，由事件循环
        # 回头把它真正删掉。
        window.deleteLater()

    def resize(self, width: int, height: int) -> None:
        if self._window is not None:
            self._window.resize(int(width), int(height))

    def raise_(self) -> None:
        """对应 `QWidget.raise_()`。置顶态下改走带 `HWND_TOPMOST` 的前置（见 `reassert_pin`）。"""
        if self._window is None:
            return
        if self._pinned:
            reassert_pin(self._window, True)
            return
        self._window.raise_()

    def activateWindow(self) -> None:
        """对应 `QWidget.activateWindow()`；QWindow 上是 `requestActivate()`。"""
        if self._window is not None:
            self._window.requestActivate()

    def isVisible(self) -> bool:
        return self._window is not None and bool(self._window.isVisible())

    def window_title(self) -> str:
        """当前窗口标题（桥的 `titleText` 读它，QML 的 `Window.title` 再绑上去）。"""
        return str(self._window_title)

    def _notify(self) -> None:
        self._bridge.stateChanged.emit()

    # ── 桥的取数接口（QML 只读这些，业务判断全在本类）─────────

    def price_type(self) -> str:
        return str(self._price_type)

    def set_price_type(self, value: str) -> None:
        if value == self._price_type:
            return
        self._price_type = value
        self.recalculate()

    def hub_text(self) -> str:
        return str(self._hub_text)

    def set_hub(self, value: str) -> None:
        if value == self._hub_text:
            return
        self._hub_text = value
        self.recalculate()

    def pinned(self) -> bool:
        return bool(self._pinned)

    def set_pinned(self, checked: bool) -> None:
        self._pinned = bool(checked)
        # 置顶作用在**窗口**上，不是控制器上（`apply_window_pin` 两种窗口都吃）。
        if self._window is not None:
            apply_window_pin(self._window, self._pinned)
        try:
            from services.user_settings import save_settings

            save_settings({"procurement_pin": self._pinned})
        except Exception:
            log.warning("保存采购窗置顶偏好失败", exc_info=True)
        self._notify()

    def complete_all_text(self) -> str:
        return str(self._complete_all_text)

    def section_rows(self, section: str) -> list[dict]:
        return self._sections.get(section, [])

    def section_label(self, section: str) -> str:
        from services.terminology import term

        if section == "buy":
            return f"{term.label('procure_buy')}({len(self._sections['buy'])})"
        return f"{term.label('procure_stocked')}({len(self._sections['stock'])})"

    def sort_column(self, section: str) -> int:
        return self._sort_state.get(section, (-1, True))[0]

    def sort_ascending(self, section: str) -> bool:
        return self._sort_state.get(section, (-1, True))[1]

    def summary_text(self) -> str:
        return str(self._summary_text)

    def copy_hint_text(self) -> str:
        return str(self._copy_hint_text)

    # ── 数据加载 ──────────────────────────────────────────

    def _reload_plans(self) -> None:
        """重新加载活跃计划、推导机库标签并重算（自给自足，不由调用方传入）。"""
        from services import inventory_manager
        from services.plan_service import load_active_plans_for_procurement

        self._active_plans = load_active_plans_for_procurement()
        default_hid = inventory_manager.get_default_mat_hangar_and_system()[0]
        self._default_mat_hangar_id = default_hid

        mat_hids = {p.get("mat_hangar_id") for p in self._active_plans if p.get("mat_hangar_id")}
        if not mat_hids and default_hid is not None:
            mat_hids = {default_hid}
        if not mat_hids:
            label = "未配置材料机库"
        elif len(mat_hids) == 1:
            hid = next(iter(mat_hids))
            label = inventory_manager.get_hangar_name(hid) or f"机库 #{hid}"
        else:
            label = f"{len(mat_hids)} 个材料机库"
        # 标题写进字段、由 QML 的 `Window.title` 绑定（原来是 `setWindowTitle`）——
        # 跟着下面 `recalculate()` 里的 `_notify()` 一起刷新。
        self._window_title = f"待采购 - 材料需求 ({label})"
        self.recalculate()

    # ── 生命周期（单实例复用：关闭后重开必须能继续刷新）──
    #
    # 基类换成 `QObject` 后 `showEvent` / `hideEvent` / `closeEvent` / `done()` 都不再存在，
    # 等价语义由 QML 的 `Window` 转发进来（见 `ProcurementWindow.qml`）：
    #   showEvent  → window_visibility_changed(True)   （**顺带 `_reload_plans()`**）
    #   hideEvent  → window_visibility_changed(False)
    #   closeEvent → window_closing()
    #   done()/Esc → reject() → done()
    # ⚠️ `showEvent` 里原来是「重载计划 + 起表」两件事，换宿主时只搬定时器会让
    # 「复用后重开」看到过期数据 —— 两条都在 `window_visibility_changed` 里。

    def window_visibility_changed(self, visible: bool) -> None:
        """窗口显示/隐藏 —— 等价于原 `showEvent` / `hideEvent`。"""
        if not visible:
            if self._poll_timer is not None:
                self._poll_timer.stop()
            return
        # 每次显示都重申置顶：构造时那一次是设在「还没显示」的窗口上的，未必留得住
        reassert_pin(self._window, self._pinned)
        self._reload_plans()
        if self._poll_timer is None:
            self._poll_timer = QTimer(self)
            self._poll_timer.setInterval(self.POLL_INTERVAL_MS)
            self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start()

    def window_closing(self) -> None:
        """关闭窗口（X 按钮）= 本次会话结束：被删的行下次打开重新算回来（见 `_deleted_ids`）。"""
        self._deleted_ids.clear()

    def done(self, result: int = 0) -> None:
        """Esc / 程序调用关闭 —— 等价于原 `QDialog.done()` 的覆盖，同样按结束本次会话处理。

        `result` 只为对齐 `QDialog.done(result)` 的形状，本窗不读它。
        """
        self._deleted_ids.clear()
        if self._window is not None:
            self._window.hide()

    def reject(self) -> None:
        """Esc 的等价入口（对齐 `QDialog.reject()`）—— QML 侧 `Shortcut` 转到 `done()`。"""
        self.done(0)

    def _on_poll(self) -> None:
        """定时同步主界面：计划/库存变化后重算（手动改量由 `_manual_overrides` 回放保留）。"""
        if not self.isVisible():
            return
        try:
            self._reload_plans()
        except Exception:
            log.exception("待采购轮询失败")

    # ── 置顶 ──────────────────────────────────────────────

    def _restore_pin(self) -> None:
        try:
            from services.user_settings import load_settings

            if load_settings().get("procurement_pin"):
                self._pinned = True
                if self._window is not None:
                    apply_window_pin(self._window, True)
                self._notify()
        except Exception:
            log.warning("读取采购窗置顶偏好失败", exc_info=True)

    # ── 计算 ──────────────────────────────────────────────

    def recalculate(self) -> None:
        """根据生产计划和库存计算需要采购的材料。"""
        from core.constants import TRADE_HUB_IDS
        from core.container import get_container
        from services.plan_aggregator import aggregate_procurement, self_made_type_ids

        self._rows = []
        rows: list[dict] = []
        # 与状态栏「备料中采购」口径一致：仅统计未运行且已勾选备料的计划，
        # ready/running 计划材料已扣库存，计入会虚高。
        proc_plans = [
            p for p in self._active_plans if p.get("materials_ready", 0) and (p.get("status") or "pending") == "pending"
        ]
        with get_container().db.connect("user", "ref", "bp", "mkt") as conn:
            rows, _cost, _vol = aggregate_procurement(
                conn,
                proc_plans,
                hangar_id=None,
                default_hangar_id=self._default_mat_hangar_id,
                region_id=TRADE_HUB_IDS.get(self._hub_text, 10000002),
                price_type=self._price_type,
                # 自制件集合按**全量**活跃计划算：`proc_plans` 只留了备料中的，而子项产线
                # 往往正在生产中 —— 拿它现算会把子线漏掉、产物被重复计成待采购。
                self_made=self_made_type_ids(self._active_plans),
            )
        self._rows = rows
        self._apply_deleted_filter()
        self._apply_manual_overrides()

        # 检查是否有「待下线」的计划，显示「完成所有」按钮
        ready_plans = [p for p in self._active_plans if p.get("status") == "ready"]
        self._complete_all_text = f"完成所有 ({len(ready_plans)} 项)" if ready_plans else ""

        if not self._rows:
            self._sections = {"buy": [], "stock": []}
            self._summary_text = "无活跃计划材料需求"
            self._notify()
            return

        self._rebuild_sections()
        self._notify()

    def _rebuild_sections(self) -> None:
        """按当前 rows 重切两个分区，并对每个分区重放它自己的排序。"""
        buy_rows, stock_rows = split_sections(self._rows)
        self._sections = {"buy": buy_rows, "stock": stock_rows}
        # 排序状态是持久的（原版由表格控件重放），重建后按记录的列重排一次
        for section in ("buy", "stock"):
            col = self._sort_state[section][0]
            if col >= 0:
                self._sort_rows(section, col, self._sort_state[section][1])
        self._update_summary()

    def _sort_rows(self, section: str, column: int, ascending: bool) -> None:
        """按列排序该分区。列 0 用显示名（`casefold`），其余按数值 —— 对齐原表模型。"""
        if not 0 <= column < len(_SORT_FIELDS):
            return
        field = _SORT_FIELDS[column]
        rows = self._sections.get(section)
        if rows is None:
            return
        if field == "name":
            rows.sort(key=lambda r: display_name(r).casefold(), reverse=not ascending)
        else:
            rows.sort(key=lambda r: r.get(field) or 0.0, reverse=not ascending)

    def sort_section(self, section: str, column: int) -> None:
        """点表头：同列反向、换列从升序开始（与 QTableView 一致）。"""
        if not 0 <= column < len(_SORT_FIELDS):
            return
        prev_col, prev_asc = self._sort_state.get(section, (-1, True))
        ascending = not (prev_col == column and prev_asc)
        self._sort_state[section] = (column, ascending)
        self._sort_rows(section, column, ascending)

    def _apply_deleted_filter(self) -> None:
        """滤掉本次打开期间删掉的行 —— 轮询/刷新重算不得把它们放回来（关闭窗口后清空）。"""
        if self._deleted_ids:
            self._rows = [r for r in self._rows if int(r.get("type_id") or 0) not in self._deleted_ids]

    def _apply_manual_overrides(self) -> None:
        """把用户手改的采购量回放到刚算出的行上 —— 轮询重算不丢改动。"""
        if not self._manual_overrides:
            return
        for row in self._rows:
            tid = row.get("type_id")
            if tid is not None and int(tid) in self._manual_overrides:
                qty = self._manual_overrides[int(tid)]
                row["to_buy"] = qty
                row["total"] = qty * row.get("price", 0)

    def _update_summary(self) -> None:
        """底部统计（两分区汇总）。"""
        all_rows = self._sections["buy"] + self._sections["stock"]
        total_cost = sum(r.get("total", 0) for r in all_rows)
        total_volume = sum(r.get("volume", 0) for r in all_rows)
        self._summary_text = (
            f"共 {len(all_rows)} 种材料 | 需采购总金额: {total_cost:,.0f} ISK | 总体积: {total_volume:,.2f} m³"
            f" | 来源: {self._hub_text} ({self._price_type})"
        )

    # ── 行交互 ────────────────────────────────────────────

    def _row_at(self, section: str, row: int) -> dict | None:
        rows = self._sections.get(section, [])
        return rows[row] if 0 <= row < len(rows) else None

    def copy_cell(self, section: str, row: int, column: int) -> None:
        """双击单元格 → 复制该列内容（名称列给物品名，数字列给纯数字），便于游戏内下单。"""
        item = self._row_at(section, row)
        if not item:
            return
        text = copy_cell_text(item, column)
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        self.show_copy_hint(f"已复制: {text}")

    def delete_row(self, section: str, row: int) -> None:
        """删除该行：本次打开期间不再出现（轮询/刷新重算也不放回来），关闭窗口后恢复。"""
        rows = self._sections.get(section)
        item = self._row_at(section, row)
        if rows is None or not item:
            return
        tid = item.get("type_id")
        if tid is not None:
            self._deleted_ids.add(int(tid))
        # 分区表与 self._rows 是同一批 dict 对象，按身份从主列表移除，避免重建时复活
        self._rows = [r for r in self._rows if r is not item]
        rows.remove(item)
        self._update_summary()
        self.show_copy_hint("已移除 1 项（重新打开后恢复）")
        self._notify()

    def edit_qty(self, section: str, row: int) -> None:
        item = self._row_at(section, row)
        if not item:
            return
        from ui_qml.bridge.input_dialog import InputQmlDialog

        qty, ok = InputQmlDialog.get_double(
            self,
            "修改采购数量",
            f"输入新采购数量 ({display_name(item)}):",
            value=float(item.get("to_buy", 0)),
            minimum=0.0,
            maximum=99999999.0,
            decimals=2,
        )
        if not ok:
            return
        old = item.get("to_buy", 0)
        item["to_buy"] = qty
        item["total"] = qty * item.get("price", 0)
        tid = item.get("type_id")
        if tid is not None:
            self._manual_overrides[int(tid)] = qty  # 轮询重算后回放，不丢手改
        # 跨分区边界（>0 ↔ <=0）时把行搬去另一分区；否则就地更新
        if (old > 0) != (qty > 0):
            self._rebuild_sections()
        else:
            self._update_summary()
        self._notify()

    def copy_qty(self, section: str, row: int) -> None:
        item = self._row_at(section, row)
        if not item:
            return
        qty = item.get("to_buy", 0)
        text = str(int(qty) if qty == int(qty) else qty)
        QGuiApplication.clipboard().setText(text)
        self.show_copy_hint(f"已复制: {text}")

    def copy_line(self, section: str, row: int) -> None:
        item = self._row_at(section, row)
        if not item:
            return
        text = f"{display_name(item)}\t{item['to_buy']:,.2f}\t{item['price']:,.2f}\t{item['total']:,.2f}"
        QGuiApplication.clipboard().setText(text)
        self.show_copy_hint("已复制整行")

    def copy_all_to_clipboard(self) -> None:
        """将需采购清单复制到剪贴板（格式：凡晶石*4）——只复制 to_buy>0 的需采购分区。"""
        rows = self._sections["buy"]
        if not rows:
            return
        lines = [f"{display_name(r)}* {r.get('to_buy', 0):.0f}" for r in rows]
        QGuiApplication.clipboard().setText("\n".join(lines))
        total_qty = sum(r.get("to_buy", 0) for r in rows)
        self.show_copy_hint(f"已复制 {len(rows)} 种材料（共 {total_qty:,.0f} 个）到剪贴板")

    def show_copy_hint(self, text: str) -> None:
        """底部状态栏右侧显示复制结果，`COPY_HINT_MS` 后自动清空。"""
        self._copy_hint_text = text
        if self._copy_hint_timer is None:
            self._copy_hint_timer = QTimer(self)
            self._copy_hint_timer.setSingleShot(True)
            self._copy_hint_timer.timeout.connect(self._clear_copy_hint)
        self._copy_hint_timer.start(self.COPY_HINT_MS)
        self._notify()

    def _clear_copy_hint(self) -> None:
        self._copy_hint_text = ""
        self._notify()

    # ── 顶部动作 ──────────────────────────────────────────

    def add_to_hangar(self) -> None:
        """增量添加到仓库 — 读剪贴板（游戏内复制已购材料），走仓库同款导入预览后增量入默认材料机库。"""
        from services.inventory_manager import get_default_mat_hangar_and_system, get_hangar_name
        from ui_qml.bridge.review_bridge import run_clipboard_import

        hid, _sys = get_default_mat_hangar_and_system()
        if not hid:
            self.show_copy_hint("未设置默认材料机库，请先在设置中指定")
            return
        hangar_name = get_hangar_name(hid) or f"机库{hid}"
        run_clipboard_import(hid, hangar_name, self, mode="incremental")
        self.recalculate()
        self.plans_changed.emit()  # 库存变化 → 通知主界面重载计划

    def complete_all(self) -> None:
        """一键完成所有待下线计划：走与工业页**同一套**下线编排（含发明结果回填）。

        必须走 `complete_plans`，不能直接调 `plan_execution.complete_plan`：
        发明是概率作业，产出要用户按游戏实际结果回填（成功几条产线），
        直接调会被 `code='need_outcome'` 拒绝并静默跳过 —— 表现成
        「一键完成后发明行没动静、还要去工业页补填」。
        `update_hangar=False`：这条入口不选机库，入库目标沿用计划自己配的机库。
        """
        ready_plans = [p for p in self._active_plans if p.get("status") == "ready"]
        if not ready_plans:
            return

        from ui_qml.bridge.complete_guard import confirm_bp_shortfall
        from ui_qml.views.industry.complete_plans_dialog import complete_plans

        # 蓝图流程不足是软阻塞：确认一次后整批强制完成。
        # 不覆盖这条入口的话，强制启动过的计划在这里会永远卡住。
        allow_bp_short = confirm_bp_shortfall(self, ready_plans)
        if allow_bp_short is None:
            return

        result = complete_plans(ready_plans, 0, parent=self, allow_bp_short=allow_bp_short, update_hangar=False)
        completed = int(result.get("completed") or 0)
        deposited = int(result.get("deposited") or 0)
        removed = int(result.get("removed") or 0)
        skipped = list(result.get("skipped") or [])
        for reason in result.get("failed_reasons") or []:
            log.warning("一键完成：%s", reason)

        if skipped:
            # 走编排后这里只剩「用户在回填窗点了取消」，不再是「静默跳过」
            self.show_copy_hint(f"{len(skipped)} 条发明的结果回填被取消，未完成")

        if completed > 0:
            msg = f"已完成 {completed}/{len(ready_plans)} 项" + (f"，{deposited} 项入库" if deposited else "")
            if removed:
                msg += f"，{removed} 条已完成的子项产线已清理"
            self.show_copy_hint(msg)
            # 必须整表重载而不是只重算：完成（或被清理）的行会滞留在 `_active_plans` 里，
            # 下次点「完成所有」会把它们再算一遍、计数失真。`_reload_plans` 内部已含 `recalculate`。
            self._reload_plans()
            self.plans_changed.emit()  # 计划状态变化 → 通知主界面重载
        else:
            self.show_copy_hint("没有可完成的计划")

    # ── 供测试/调试读取 ────────────────────────────────────

    def all_rows(self) -> list[dict]:
        return list(self._rows)

    def debug_state(self) -> dict[str, Any]:
        """给测试用的快照：两个分区的行 + 汇总 + 提示。"""
        return {
            "buy": [dict(r) for r in self._sections["buy"]],
            "stock": [dict(r) for r in self._sections["stock"]],
            "summary": self._summary_text,
            "hint": self._copy_hint_text,
        }
