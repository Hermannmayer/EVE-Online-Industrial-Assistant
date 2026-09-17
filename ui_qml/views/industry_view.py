"""生产计划管理 — 统一页面（5 区布局，阶段 2b 起整页由 QML 渲染）"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QThread, QTimer

from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.logger import log
from services.char_config_resolver import load_all_data
from services.plan_aggregator import self_made_type_ids
from services.user_settings import get_price_settings
from ui_qml.bridge.blueprint_dialog_bridge import (
    BlueprintRequirementsQmlDialog as BlueprintRequirementsDialog,
)
from ui_qml.bridge.char_usage_bridge import CharacterUsageQmlDialog as CharacterUsageDialog
from ui_qml.bridge.complete_plans_bridge import CompletePlansQmlDialog as CompletePlansDialog
from ui_qml.bridge.industry_bridge import IndustryBridge
from ui_qml.bridge.manufacturable_items_bridge import ManufacturableItemsQmlDialog as ManufacturableItemsDialog
from ui_qml.bridge.materials_dialog_bridge import MaterialsSummaryQmlDialog as MaterialsSummaryDialog
from ui_qml.bridge.message_dialog import FMessageDialog
from ui_qml.bridge.output_dialog_bridge import OutputSummaryQmlDialog as OutputSummaryDialog
from ui_qml.views.industry import (
    PlanTable,
)
from ui_qml.views.industry.complete_plans_dialog import complete_plans
from ui_qml.workers.industry_page_workers import (
    IndustryDataWorker,
    PlanPriceRefreshWorker,
    init_plan_db,
)
from ui_qml.workers.industry_workers import BatchPlanCalcWorker, ProcurementSummaryWorker

if TYPE_CHECKING:
    from ui_qml.bridge.plan_table_bridge import PlanTableBridge

#: 人物选择已移除，全应用固定用 main（与旧 TopToolbar.get_char_name 一致）
MAIN_CHAR_NAME = "main"


def _default_mat_hangar_id() -> int | None:
    """默认材料机库（机库设置里配置，settings.default_mat_hangar_id）。"""
    from services import inventory_manager

    return inventory_manager.get_default_mat_hangar_and_system()[0]


class IndustryPage(QObject):
    """生产计划管理统一页面 — 5 区布局（阶段 2b：整页由 QML 渲染）

    与阶段 2a 的 `PlanTable` 同一套路：**业务方法与信号一律不动**，
    只把原来的五个 Widgets 子控件（标题栏 / 工具栏 / 视图栈 / 状态栏 / 功能按钮）
    换成**一个** QML 宿主；QML 的每次交互都经 `IndustryBridge` 转回本类的方法，
    所以迁移期只有一份业务实现。

    `_plan_table_widget` 以 `headless=True` 构造 —— 它只作业务控制器，
    表格本身由 `IndustryPage.qml` 里的 `PlanTablePane` 渲染。

    批次 7.4：本类**不再是页面控件**，只是**控制器**（基类 `QWidget` → `QObject`）。
    渲染面由外壳决定（QML 外壳经 `ui_qml.registry.build_qml_page` 把 `IndustryPage.qml`
    实例化成 `Item`），桥与钩子实现由 `ui_qml/industry_page.py::industry_spec` 组装。
    所以 `super().__init__()` 收的 `parent` 只用于**对象树寿命**，不再当窗口父 ——
    任何「拿 self 当 QWidget 父」的调用（`QMessageBox(self, …)` 之类）都不再成立。
    """

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        init_plan_db()
        self.setObjectName("industry_page")
        self._recalc_worker = None
        self._proc_worker: QThread | None = None
        self._proc_fp: tuple | None = None
        self._proc_result: tuple[float, float] | None = None
        # 本次汇总用的**全量**计划（供完成回调按新指纹补算）。
        # 存全量而不是筛过的 procur：自制件集合要按全量算，否则补算那一次又会用回错的口径。
        self._proc_rows: list[dict] = []
        self._refresh_worker = None
        #: 评分线程；`None` = 当前没有在跑的。类型写 `Any` 是因为它有两个来源
        #: （`ScoreWorker` / 断线重连后的新实例），用联合类型反而更难读。
        self._score_worker: Any = None

        # 计划表：只作业务控制器，桥注入给 QML 树
        self._plan_table_widget: PlanTable = PlanTable(headless=True)
        # 注入价格设置/人物访问器（母项拆解利润预览用）
        self._plan_table_widget.set_price_context(get_price_settings, lambda: MAIN_CHAR_NAME)
        self._plan_table_widget.plan_updated.connect(self.load_plans)
        self._plan_table_widget.refresh_requested.connect(self.load_plans)
        self._plan_table_widget.plan_detail_requested.connect(self._on_plan_detail)

        self._bridge: IndustryBridge = IndustryBridge(self, self)
        # 两个 context property（`bridge` / `planTableBridge`）由
        # `ui_qml/industry_page.py::industry_spec` 组装 —— 本文件不拼 QML context，
        # 也不再自建宿主（批次 7.4 起宿主形态由外壳决定）。

        # ── 初始加载 ───────────────────────────────────────────
        self.load_plans()

        # ── 倒计时定时器（进行中计划剩余时间 → 到期自动转待下线）──
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(30 * 1000)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._countdown_timer.start()

        # ── 后台补拉工业数据（成本指数/设施，首次访问时自动）───────
        QTimer.singleShot(200, self._check_industry_data)

    # ── 给 QML 层/注册表的访问器 ────────────────────────────────

    @property
    def bridge(self) -> IndustryBridge:
        """页面骨架桥（宿主注入为 context property `bridge`）。"""
        return self._bridge

    @property
    def plan_table_bridge(self) -> PlanTableBridge:
        """计划表桥（宿主注入为 context property `planTableBridge`）。"""
        return self._plan_table_widget.bridge

    @property
    def plan_table(self) -> PlanTable:
        return self._plan_table_widget

    # ── 倒计时 ────────────────────────────────────────────────

    def _on_countdown_tick(self) -> None:
        """倒计时：刷新时长列 + 到期的进行中计划转 ready。

        model.tick() 只处理当前筛选可见的行（刷新倒计时显示）；
        expire_overdue_plans() 在 DB 层补算所有进行中计划，不受当前筛选影响。
        """
        model = self._plan_table_widget.get_model()
        if model is None:
            return
        expired_visible = model.tick()
        try:
            from services.plan_execution import expire_overdue_plans

            expired_db = expire_overdue_plans()
        except Exception:
            log.exception("倒计时补算失败")
            expired_db = 0
        if expired_visible or expired_db:
            self.load_plans()
            return
        # 顺带刷新「材料不足」标注：材料补齐后没有别的路径会重算，
        # 不挂在这里的话标注会一直陈旧到用户手动刷新（产线小助手 5s 轮询修的就是同一个缺陷）
        self._refresh_material_status()

    def shutdown(self) -> None:
        """停掉本页在跑的后台线程并等它们结束（外壳关窗时按钩子名调进来）。

        为什么必须由外壳显式调，而不是靠 Qt 的父子链自动收：`QThread` 在**仍运行**时被析构，
        Qt 直接 `abort()` —— 静默死进程、退出码 127、连一行日志都没有
        （`ui_qml/dialog_host.py` 记过同一条）。而这些 worker 是 `IndustryPage` 的子对象，
        本类**自己没有 QObject 父**（`main_window` 是第一个**位置参数**、不是 `parent`），
        所以外壳那句 `self.findChildren(QThread)` **找不到它们**。

        可重入：外壳的 `closeEvent` 与 `aboutToQuit` 都会走到这里。
        """
        # 先把两个工具窗（产线小助手 / 采购）的 QML 场景**拆掉**。外壳已经对它们调过
        # `close()`，但那只是隐藏 —— QML 树与 `QQmlEngine` 都还活着。等解释器收尾把
        # `Theme` 单例（`theme_bridge._singleton`）回收掉，场景里那些 `Theme.xxx` 绑定
        # 重算就会对着 null 求值，一次退出刷出几百条 `Cannot read property 'xxx' of null`。
        # 必须趁 QApplication 还活着时做，所以挂在关机钩子里（两条退出路径都会到这里）。
        for attr in ("_launcher", "_procurement"):
            window = getattr(self, attr, None)
            dispose = getattr(window, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:
                    log.exception("工具窗 QML 场景拆除失败：%s", attr)
        for name in ("_industry_worker", "_refresh_worker", "_score_worker", "_proc_worker", "_recalc_worker"):
            worker = getattr(self, name, None)
            if worker is None:
                continue
            try:
                if worker.isRunning():
                    worker.requestInterruption()
                    worker.wait(3000)
            except RuntimeError:
                # 底层 C++ 对象已被销毁（PySide 包装器还在）—— 没什么可等的
                continue

    def on_shown(self) -> None:
        """页面重新可见时的同步（由外壳在切页时按名调用）。

        材料倍率与仓库页（导入预览 / 批量设置成本价）是**同一个** settings.json 字段，
        在那边改完回到本页时，工具栏旋钮不能还停在旧值。

        批次 7.4 起本类是 `QObject`，**没有 `showEvent` 可依赖** —— 唯一唤醒路径是
        `ui_qml/shell_window.py::navigate_to` 里的 `on_shown` 钩子分发（外壳按名 `getattr` 探测）。
        名字改了或删了都是**静默失效**：切回工业页时旋钮停在旧值，且没有任何报错。
        """
        self._bridge.reloadPriceSettings()

    # ── 材料不足标注（派生字段，不落库）─────────────────────────

    def _material_stock(self, hangar_ids: set[int]) -> dict[int, dict[int, int]]:
        """按机库各取一次库存快照。

        `plan_execution.check_materials` 不传 `stock=` 时会**每个计划各查一次库**，
        行数一多就是 N 次查询 —— 所以先取好再逐行传进去。
        """
        from services import inventory_manager

        out: dict[int, dict[int, int]] = {}
        for hid in hangar_ids:
            try:
                out[hid] = inventory_manager.get_hangar_stock(hid)
            except Exception:
                log.exception("读取机库库存失败: %s", hid)
                out[hid] = {}
        return out

    def _material_fingerprint(self, rows: list[dict]) -> tuple:
        """库存内容 + 待生产行特征的指纹。

        本函数自己要查一次库存（每机库一次）——省下的是**每条计划一次评分**那步。
        库存或计划参数一变指纹就变，所以材料补齐后能自己发现并重算，
        不会像只靠 `load_plans` 那样把「材料不足」一直挂到用户手动刷新。
        """
        from services import inventory_manager

        pending = [r for r in rows if (r.get("status") or "") == "pending"]
        hids = sorted({int(r["mat_hangar_id"]) for r in pending if r.get("mat_hangar_id")})
        stock_fp: list[frozenset | None] = []
        for hid in hids:
            try:
                stock_fp.append(frozenset(inventory_manager.get_hangar_stock(hid).items()))
            except Exception:
                stock_fp.append(None)
        plans_fp = tuple(
            (r.get("id"), r.get("runs"), r.get("parallels"), r.get("me_level"), r.get("mat_hangar_id")) for r in pending
        )
        return (tuple(hids), tuple(stock_fp), plans_fp)

    def _annotate_material_status(self, rows: list[dict]) -> None:
        """给**待生产**行标注缺料情况（`material_status` / `material_short_tip`）。

        只算 pending 行：其余状态与「能不能启动」无关，算了也没人看。

        写的是**派生字段**，**绝不覆写 `plan["status"]`** —— 覆写会同时污染第 7 列的
        排序键、右键菜单的互斥分支（判 `status === "pending"`）与落库路径。
        """
        from services.plan_execution import check_materials

        pending = [r for r in rows if (r.get("status") or "") == "pending"]
        if not pending:
            return
        hids = {int(r["mat_hangar_id"]) for r in pending if r.get("mat_hangar_id")}
        stock = self._material_stock(hids)
        for r in pending:
            r["material_status"] = None
            r["material_short_tip"] = ""
            hid = r.get("mat_hangar_id")
            if not hid:
                continue
            try:
                res = check_materials(r, int(hid), stock=stock.get(int(hid)))
            except Exception:
                log.exception("材料判定失败: %s", r.get("id"))
                continue
            short = [x for x in res if (x.get("missing") or 0) > 0]
            if not short:
                continue
            r["material_status"] = "short"
            tip = "\n".join(f"{x.get('name') or x['type_id']}: 缺 {x['missing']:,.0f}" for x in short[:8])
            if len(short) > 8:
                tip += f"\n… 等 {len(short)} 种"
            r["material_short_tip"] = tip

    def _refresh_material_status(self) -> None:
        """心跳里顺手刷新缺料标注；指纹没变则连评分都不做，只花每机库一次库存查询。"""
        rows = getattr(self, "_loaded_rows", None)
        if not rows:
            return
        fp = self._material_fingerprint(rows)
        if fp == getattr(self, "_mat_fp", None):
            return
        self._mat_fp = fp
        self._annotate_material_status(rows)
        model = self._plan_table_widget.get_model()
        if model is not None:
            model.refresh_status_column()

    # ── load_plans ────────────────────────────────────────────

    def load_plans(self):
        # 首次加载前补算：重启后已超时的进行中计划 → ready（避免永远停在生产中）
        if not getattr(self, "_overdue_checked", False):
            self._overdue_checked = True
            try:
                from services.plan_execution import expire_overdue_plans

                expire_overdue_plans()
            except Exception:
                log.exception("补算过期计划失败")

        from services.plan_service import load_plans

        rows = load_plans(self._bridge.current_filter())
        from ui_qml.models.industry_models import PlanTableModel

        # 缺料标注（派生字段）：先记指纹再算，免得 30s 心跳立刻重复算一遍
        self._loaded_rows = rows
        self._mat_fp = self._material_fingerprint(rows)
        self._annotate_material_status(rows)

        # 注入当前材料机库（启动旧计划时兜底）
        self._plan_table_widget.set_mat_hangar_id(_default_mat_hangar_id())

        # 复用已有 model，避免 setModel 清除选中状态
        model = self._plan_table_widget.get_model()
        if model is None:
            model = PlanTableModel(rows)
            self._plan_table_widget.set_model(model)
        else:
            model.set_plans(rows)

        self._bridge.update_stats(rows)
        self._refresh_procurement_summary(rows)

        # 如果当前是甘特图模式，同步刷新甘特图
        if self._bridge.viewMode == "gantt":
            self.refresh_gantt()
        self._auto_calculate_plans(rows)

    def _price_fp(self) -> tuple[int, str, float, int | None]:
        """汇总用到的价格口径 —— 工具栏材料行（Hub / 卖价买价 / 倍率）+ 默认材料机库。

        这四项都是 `ProcurementSummaryWorker` 的入参，必须进指纹：
        漏掉就会在改设置后命中缓存、直接回吐旧值（历史缺陷）。
        """
        ps = get_price_settings()
        return (
            TRADE_HUB_IDS.get(str(ps.get("mat_hub") or ""), 10000002),
            ps.get("mat_price_type") or "sell",
            round(float(ps.get("mat_mult") or 1.0), 4),
            _default_mat_hangar_id(),
        )

    def _refresh_procurement_summary(self, rows: list[dict]):
        """刷新状态栏「备料中采购」汇总。

        DB 查询较重，放后台线程；带指纹缓存避免数据未变时重复查询。
        「备料中」= 未运行（pending）且已勾选备料（materials_ready==1）；
        ready 计划材料已扣库存，计入会虚高，排除。

        指纹 = （价格口径, 计划字段集），两者任一变化都要重算。
        """
        procur = [p for p in rows if p.get("materials_ready", 0) and (p.get("status") or "pending") == "pending"]
        # 自制件集合按**全量** rows 算：procur 是筛过的（只留备料中的），而子项产线往往
        # 正在生产中，拿筛过的列表算会把它们漏掉、产物被重复计成待采购。
        self_made = self_made_type_ids(rows)
        price_fp = self._price_fp()
        fp = (
            price_fp,
            # 自制件集合进指纹：子线状态一变（待生产 → 生产中 → 完工）口径就不同了
            tuple(sorted(self_made)),
            tuple(
                sorted(
                    (
                        p.get("id"),
                        p.get("runs"),
                        p.get("parallels"),
                        p.get("me_level"),
                        p.get("materials_ready"),
                        p.get("status"),
                        p.get("mat_hangar_id"),
                    )
                    for p in procur
                )
            ),
        )
        if fp == self._proc_fp and self._proc_result is not None:
            self._bridge.update_material(*self._proc_result)
            return
        if not procur:
            self._bridge.update_material(0.0, 0.0)
            self._proc_fp = None
            self._proc_result = None
            self._proc_rows = []
            return
        if self._proc_worker and self._proc_worker.isRunning():
            # 运行中改设置：记下本次计划集，完成回调发现口径变了会补算一次
            self._proc_rows = rows
            return
        region_id, price_type, price_mult, default_hangar_id = price_fp
        self._proc_fp = fp
        self._proc_result = None
        self._proc_rows = rows
        self._proc_worker = ProcurementSummaryWorker(
            procur,
            default_mat_hangar_id=default_hangar_id,
            region_id=region_id,
            price_type=price_type,
            price_mult=price_mult,
            self_made=self_made,
            parent=self,
        )
        self._proc_worker.finished_signal.connect(self._on_procurement_summary_done)
        self._proc_worker.start()

    def _on_procurement_summary_done(self, cost: float, vol: float):
        """采购汇总线程完成 → 更新状态栏（stale guard 防旧线程结果覆盖新指纹）"""
        if self._proc_worker is not self.sender():
            return
        self._proc_result = (cost, vol)
        self._bridge.update_material(cost, vol)
        # 算的这段时间里价格设置又变了 → 本次结果已过期，用同一批计划补算一次。
        # 若此刻线程尚未收尾（守卫挡住），_proc_fp 已置 None，下次任何刷新都会重算。
        if self._proc_rows and (self._proc_fp is None or self._price_fp() != self._proc_fp[0]):
            self._proc_fp = None
            self._proc_result = None
            self._refresh_procurement_summary(self._proc_rows)

    def _auto_calculate_plans(self, rows):
        """自动重算计划利润/边际（后台线程触发）"""
        # 避免重入 — 防止 on_recalc_done → load_plans → _auto_calculate 循环
        if getattr(self, "_recalc_busy", False):
            return
        # 避免重复启动
        if self._recalc_worker and self._recalc_worker.isRunning():
            return
        # 只重算 pending/in_progress/ready 的计划
        todo = [
            r
            for r in rows
            if r.get("id") and r.get("status", "").lower() in ("pending", "in_progress", "running", "ready", "")
        ]
        if not todo:
            return
        # 加载角色配置
        try:
            char_data = load_all_data()
            current_char = char_data.get("current", "main")
            char_config = char_data.get("characters", {}).get(current_char, {})
        except Exception:
            current_char = "main"
            char_config = {}
        # 获取工具栏当前价格设置
        ps = get_price_settings()
        self._recalc_worker = BatchPlanCalcWorker(
            todo,
            char_config,
            char_name=current_char,
            mat_hub=ps["mat_hub"],
            mat_price_type=ps["mat_price_type"],
            prod_hub=ps["prod_hub"],
            prod_price_type=ps["prod_price_type"],
            mat_mult=float(ps.get("mat_mult") or 1.0),
            prod_mult=float(ps.get("prod_mult") or 1.0),
            parent=self,
        )
        self._recalc_worker.finished_signal.connect(self._on_recalc_done)
        self._recalc_worker.start()

    def _on_recalc_done(self, results: list):
        """批量重算完成 → 更新数据库并刷新显示"""
        if self._recalc_worker is not self.sender():
            return
        if not results:
            return
        # 防御：后台 worker 可能晚于页面/测试 teardown 触发（指标为 MagicMock/None），
        # 过滤掉非数值结果，避免把 mock 值绑进 SQL 导致后续测试被事件循环异常污染。
        clean: list = []
        for row in results:
            try:
                (
                    plan_id,
                    profit,
                    margin,
                    score,
                    iskph,
                    mat_cost,
                    hours_total,
                    daily_output,
                    personal_margin,
                    market_margin,
                ) = row
            except (ValueError, TypeError):
                continue
            metrics = (
                profit,
                margin,
                score,
                iskph,
                mat_cost,
                hours_total,
                daily_output,
                personal_margin,
                market_margin,
            )
            if not isinstance(plan_id, int) or not all(
                isinstance(m, int | float) and not isinstance(m, bool) for m in metrics
            ):
                continue
            clean.append(row)
        if not clean:
            return
        # 设置重入锁，避免 load_plans → _auto_calculate → 新 worker -> ... 无限循环
        self._recalc_busy = True
        try:
            rows = []
            for (
                plan_id,
                profit,
                margin,
                score,
                iskph,
                mat_cost,
                hours_total,
                daily_output,
                personal_margin,
                market_margin,
            ) in clean:
                # hours_total 转换为秒存入 calculated_time
                rows.append(
                    (
                        plan_id,
                        {
                            "profit": profit,
                            "margin": margin,
                            "score": score,
                            "iskph": iskph,
                            "material_cost": mat_cost,
                            "market_margin": market_margin,
                            "personal_margin": personal_margin,
                            "calculated_time": round(hours_total * 3600),
                            "daily_output": daily_output,
                        },
                    )
                )
            get_container().plan_repo.update_batch(rows)
            self.load_plans()
            # 估值失败的行本轮没写库（保留上次的成本），必须让用户看见，否则就成了静默不更新
            failed = list(getattr(self._recalc_worker, "failed_names", []))
            if failed:
                shown = "、".join(failed[:3]) + ("…" if len(failed) > 3 else "")
                self._bridge.show_message(f"⚠ {len(failed)} 条计划估值失败（{shown}），成本沿用上次值", 8000)
        finally:
            self._recalc_busy = False

    def _check_industry_data(self):
        """检查工业数据，缺失或过时（fetch_time 超阈值）时在后台拉取"""
        from core.paths import REF_DB_PATH
        from services.importers.getindustry import industry_data_is_fresh

        if industry_data_is_fresh(REF_DB_PATH):
            return
        if getattr(self, "_industry_worker", None) and self._industry_worker.isRunning():
            return  # 已有拉取线程在跑
        log.info("工业数据（成本指数/设施）缺失或过时，后台开始拉取...")
        self._bridge.show_message("正在后台拉取工业数据...")
        self._industry_worker = IndustryDataWorker(parent=self)
        self._industry_worker.finished_signal.connect(self._on_industry_data_ready)
        self._industry_worker.start()

    def _on_industry_data_ready(self, success: bool, message: str):
        if self._industry_worker is not self.sender():
            return
        if success:
            log.info("工业数据后台拉取完成")
            self._bridge.show_message("工业数据拉取完成", timeout=5000)
        else:
            log.warning("工业数据拉取失败: %s", message)
            self._bridge.show_message(f"工业数据拉取失败: {message}", timeout=8000)

    # ── 甘特图 ────────────────────────────────────────────────

    def refresh_gantt(self) -> None:
        """按当前计划集重算甘特条（排期逻辑在 `services.plan_gantt`）。

        状态栏 / 功能按钮在甘特模式下的显隐由 QML 绑定 `bridge.statusVisible`，
        不再需要在这里 setVisible。
        """
        model = self._plan_table_widget.get_model()
        plans = []
        if model:
            for row in range(model.rowCount()):
                p = model.get_plan(row)
                if p:
                    plans.append(p)
        self._bridge.set_gantt_plans(plans)

    # ── 价格定向刷新 ────────────────────────────────────────────

    def refresh_prices(self):
        """刷新按钮点击 → 收集 type_id → 启动定向 ESI 价格拉取"""
        # 1. 收集产品/物料 type_ids 并检查缓存
        from services.plan_service import collect_refresh_type_ids

        all_ids, is_cached = collect_refresh_type_ids()
        if not all_ids:
            self.load_plans()
            return

        suffix = "（可能使用缓存）" if is_cached == len(all_ids) else ""
        self._bridge.show_message(f"正在获取 {len(all_ids)} 个物品的价格{suffix}...")
        if self._refresh_worker and self._refresh_worker.isRunning():
            self._bridge.show_message("价格刷新进行中，请稍候", timeout=4000)
            return
        self._refresh_worker = PlanPriceRefreshWorker(all_ids, self)
        self._refresh_worker.finished_signal.connect(self._on_industry_refresh_done)
        self._refresh_worker.start()

    def _on_industry_refresh_done(self, success: bool, message: str):
        """价格拉取完成 → 刷新显示 + 状态栏反馈"""
        if self._refresh_worker is not self.sender():
            return
        if success:
            self._bridge.show_message(message, timeout=5000)
        else:
            self._bridge.show_message(f"价格刷新失败: {message}", timeout=8000)
        self.load_plans()

    # ── 对话框打开方法 ────────────────────────────────────────

    def add_plan(self, text: str):
        """\u641c\u7d22\u7269\u54c1 -> \u8bc4\u5206 -> AddPlanDialogQmlDialog -> INSERT\uff08\u7528\u7528\u6237\u8bbe\u5b9a\u7684 ME/TE \u91cd\u7b97\uff09"""
        text = text.strip()
        if not text:
            return

        from PySide6.QtWidgets import QDialog

        from ui_qml.bridge.industry_dialogs_bridge import AddPlanDialogQmlDialog

        # 1) \u641c\u7d22\u7269\u54c1\uff08\u8d70 repository\uff0c\u4e0d\u5728 UI \u76f4\u8fde SQLite\uff09
        items = get_container().item_repo.search_by_name(text, limit=10)

        if not items:
            FMessageDialog.information(self, "\u63d0\u793a", f"\u672a\u627e\u5230\u7269\u54c1: {text}")
            return

        type_id = items[0]["type_id"]
        product_name = items[0]["zh_name"] or items[0]["en_name"] or str(type_id)

        # 2) \u68c0\u67e5\u662f\u5426\u53ef\u5236\u9020\uff08\u8d70 repository\uff09
        has_bp = get_container().blueprint_repo.get_blueprint_for_product(type_id) is not None

        if not has_bp:
            FMessageDialog.information(
                self, "\u63d0\u793a", f"\u300c{product_name}\u300d\u6ca1\u6709\u5236\u9020\u84dd\u56fe"
            )
            return

        # 3) \u521d\u6b65\u8bc4\u5206\uff08ME=0/TE=0 \u9884\u89c8\u7528\uff09
        from services.char_config_resolver import resolve_char_config
        from ui_qml.workers.industry_workers import ScoreWorker

        char_name = MAIN_CHAR_NAME
        ps = get_price_settings()
        from services import inventory_manager

        preview_system_id = inventory_manager.get_hangar_system_id(_default_mat_hangar_id())

        self._score_worker = ScoreWorker(
            type_id=type_id,
            bp_me=0,
            bp_te=0,
            mat_hub=ps["mat_hub"],
            sell_hub=ps["prod_hub"],
            tax=0.0,
            char_name=char_name,
            system_id=preview_system_id,
            parent=self,
        )

        def _on_score(result: dict):
            if self._score_worker is not self.sender():
                return
            dlg = AddPlanDialogQmlDialog(product_name, result, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data()
            if not data:
                return
            # \u4ece\u6750\u6599\u673a\u5e93\u5e26\u51fa\u6240\u5728\u661f\u7cfb\uff08\u661f\u7cfb\u6210\u672c\u6307\u6570\u5f71\u54cd\u5b89\u88c5\u8d39\uff09\uff1bfacility \u672a\u586b\u65f6\u7528\u6750\u6599\u673a\u5e93\u540d\u79f0
            mat_hangar_id = _default_mat_hangar_id()
            from services import inventory_manager

            solar_system_id = inventory_manager.get_hangar_system_id(mat_hangar_id)
            facility = data.get("fac", "")
            if not facility:
                facility = inventory_manager.get_hangar_name(mat_hangar_id)
            # \u6784\u9020\u4e34\u65f6 plan dict\uff0c\u7528\u7edf\u4e00\u65b9\u6cd5\u8ba1\u7b97\u6d3e\u751f\u6307\u6807
            plan_input = {
                "product_type_id": type_id,
                "product_name": product_name,
                "runs": data.get("runs", 1),
                "parallels": data.get("parallels", 1),
                "me_level": data.get("me", 0),
                "te_level": data.get("te", 0),
                "mat_hub": ps["mat_hub"],
                "sell_hub": ps["prod_hub"],
                "char_name": data.get("char", ""),
                "facility": facility,
                "solar_system_id": solar_system_id,
            }
            actual_char_name = data.get("char", "").strip() or char_name
            actual_config = resolve_char_config(char_name=actual_char_name)
            metrics = (
                get_container()
                .scoring_service()
                .calculate_plan_metrics(
                    plan_input,
                    actual_config,
                    price_type_mat=ps.get("mat_price_type"),
                    price_type_prod=ps.get("prod_price_type"),
                    mat_mult=float(ps.get("mat_mult") or 1.0),
                    prod_mult=float(ps.get("prod_mult") or 1.0),
                )
            )
            # \u7edf\u4e00\u8d70 plan_service \u843d\u5e93\uff08\u907f\u514d UI \u5185\u8054 INSERT \u91cd\u590d\uff09
            from services import user_settings
            from services.plan_service import insert_plan

            insert_plan(
                type_id,
                product_name,
                data={
                    "runs": data["runs"],
                    "parallels": data["parallels"],
                    "me": data["me"],
                    "te": data["te"],
                    "char": data["char"],
                },
                mat_hub=ps["mat_hub"],
                sell_hub=ps["prod_hub"],
                facility=facility,
                solar_system_id=solar_system_id,
                mat_hangar_id=mat_hangar_id,
                deposit_hangar_id=user_settings.get_default_hangar_id("default_deposit_hangar_id"),
                metrics=metrics,
            )
            self.load_plans()
            FMessageDialog.information(self, "\u5b8c\u6210", f"\u5df2\u6dfb\u52a0\u8ba1\u5212: {product_name}")

        self._score_worker.finished_signal.connect(_on_score)
        self._score_worker.start()

    def open_manufacturable_browser(self):
        """打开可制造物品浏览器"""
        dlg = ManufacturableItemsDialog(parent=self)
        dlg.show()

    def _on_plan_detail(self, plan_id: int):
        """双击计划行 → 打开 PlanEditDialog（通过 plan_table 的统一路径）"""
        model = self._plan_table_widget.get_model()
        if not model:
            return
        for row in range(model.rowCount()):
            p = model.get_plan(row)
            if p and p.get("id") == plan_id:
                self._plan_table_widget._edit_plan(row)
                return

    def open_blueprint_list(self):
        dlg = BlueprintRequirementsDialog(self)
        dlg.exec()

    def open_materials_summary(self):
        dlg = MaterialsSummaryDialog(self)
        dlg.exec()

    def open_output_summary(self):
        dlg = OutputSummaryDialog(self)
        dlg.exec()

    def open_char_usage(self):
        dlg = CharacterUsageDialog(self)
        dlg.exec()

    def open_procurement(self):
        """采购小助手：非模态独立窗口（单实例复用，可置顶，不阻塞主界面）。"""
        from ui_qml.views.procurement_tab import ProcurementDialog

        w = getattr(self, "_procurement", None)
        if w is None:
            w = ProcurementDialog()
            w.plans_changed.connect(self.load_plans)
            self._procurement = w
        w.show()
        w.raise_()
        w.activateWindow()

    # ── 保存价格快照 ──────────────────────────────────────────

    def save_prices(self):
        from services.plan_service import save_price_snapshots

        count = save_price_snapshots()
        if count == 0:
            FMessageDialog.information(self, "提示", "没有活跃计划")
            return
        FMessageDialog.information(self, "完成", f"已保存 {count} 个价格快照")

    def complete_all(self):
        """全部下线：确认待下线计划清单 → 选择产出机库 → 完成入库。"""
        model = self._plan_table_widget.get_model()
        if model is None:
            return
        ready = []
        for i in range(model.rowCount()):
            plan = model.get_plan(i)
            if plan and (plan.get("status") or "").lower() == "ready":
                ready.append(plan)
        if not ready:
            FMessageDialog.information(self, "提示", "没有待下线的计划")
            return
        from services.inventory_manager import get_hangars
        from services.user_settings import get_default_hangar_id
        from ui_qml.bridge.complete_guard import confirm_bp_shortfall

        hangars = get_hangars()
        default_hid = get_default_hangar_id("default_deposit_hangar_id")
        dlg = CompletePlansDialog(ready, hangars, default_hid, self)
        if not dlg.exec():
            return
        # 与另外三条入口一致：蓝图流程不足先确认再强制放行。缺这一步时，
        # 强制启动过的计划会被 complete_plan 硬拒，本入口永远下不了线。
        allow_bp_short = confirm_bp_shortfall(self, ready)
        if allow_bp_short is None:
            return
        result = complete_plans(ready, dlg.selected_hangar_id(), parent=self, allow_bp_short=allow_bp_short)
        self.load_plans()
        msg = f"已下线 {result['completed']} 项"
        if result["deposited"]:
            msg += f"，入库 {result['deposited']} 项"
        if result.get("removed"):
            msg += f"，清理了 {result['removed']} 条已完成的子项产线"
        if result["failed"]:
            msg += f"，失败 {len(result['failed'])} 项"
            # 只报产品名等于没说：把 complete_plan 的拒绝原因带出来
            reasons = result.get("failed_reasons") or []
            if reasons:
                msg += "\n\n" + "\n".join(reasons[:10])
        FMessageDialog.information(self, "完成", msg)

    def open_launcher(self, char_name: str | None) -> None:
        """打开共享的产线启动小助手窗口（单实例，重复打开复用）。

        入口是工业页底部状态栏那颗按钮（`char_name=None`，不预定位人物）。
        """
        from ui_qml.views.industry.production_launcher import ProductionLauncher

        w = getattr(self, "_launcher", None)
        if w is None:
            w = ProductionLauncher()
            w.plans_changed.connect(self.load_plans)
            self._launcher = w
        if char_name is not None:
            w.focus_character(char_name)
        w.show()
        w.raise_()
        w.activateWindow()

    # ── 状态保存/恢复 ─────────────────────────────────────────

    def save_state(self) -> dict:
        # 表格已迁 QML（阶段 2a）：滚动位置由 PlanTable 经 bridge 读写，
        # 不再从 QTableView 的滚动条取。
        return {"v_scroll": self._plan_table_widget.scroll_value()}

    def restore_state(self, data: dict) -> None:
        if not data or "v_scroll" not in data:
            return
        self._plan_table_widget.set_scroll_value(data["v_scroll"])

    # ── 外部刷新接口 ──────────────────────────────────────────

    def refresh_display(self):
        self.load_plans()

    def update_status_bar(self):
        self.load_plans()
