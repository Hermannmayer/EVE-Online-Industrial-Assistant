"""生产计划管理 — 统一页面（5 区布局，阶段 2b 起整页由 QML 渲染）"""

from __future__ import annotations

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget

from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.logger import log
from services.user_settings import get_price_settings
from ui_pyside6.views.char_settings_view import load_all_data
from ui_pyside6.views.industry import (
    PlanTable,
)
from ui_pyside6.views.industry.complete_plans_dialog import complete_plans
from ui_pyside6.workers.industry_page_workers import (
    IndustryDataWorker,
    PlanPriceRefreshWorker,
    init_plan_db,
)
from ui_pyside6.workers.industry_workers import BatchPlanCalcWorker, ProcurementSummaryWorker
from ui_qml.bridge.blueprint_dialog_bridge import (
    BlueprintRequirementsQmlDialog as BlueprintRequirementsDialog,
)
from ui_qml.bridge.char_usage_bridge import CharacterUsageQmlDialog as CharacterUsageDialog
from ui_qml.bridge.complete_plans_bridge import CompletePlansQmlDialog as CompletePlansDialog
from ui_qml.bridge.industry_bridge import IndustryBridge
from ui_qml.bridge.manufacturable_items_bridge import ManufacturableItemsQmlDialog as ManufacturableItemsDialog
from ui_qml.bridge.materials_dialog_bridge import MaterialsSummaryQmlDialog as MaterialsSummaryDialog
from ui_qml.bridge.output_dialog_bridge import OutputSummaryQmlDialog as OutputSummaryDialog
from ui_qml.host import PageHost

#: QML 页面路径（相对 ui_qml/qml/）
QML_PAGE = "pages/IndustryPage.qml"

#: 人物选择已移除，全应用固定用 main（与旧 TopToolbar.get_char_name 一致）
MAIN_CHAR_NAME = "main"


def _default_mat_hangar_id() -> int | None:
    """默认材料机库（机库设置里配置，settings.default_mat_hangar_id）。"""
    from services import inventory_manager

    return inventory_manager.get_default_mat_hangar_and_system()[0]


class IndustryPage(QWidget):
    """生产计划管理统一页面 — 5 区布局（阶段 2b：整页由 QML 渲染）

    与阶段 2a 的 `PlanTable` 同一套路：**业务方法与信号一律不动**，
    只把原来的五个 Widgets 子控件（标题栏 / 工具栏 / 视图栈 / 状态栏 / 功能按钮）
    换成**一个** QML 宿主；QML 的每次交互都经 `IndustryBridge` 转回本类的方法，
    所以迁移期只有一份业务实现。

    `_plan_table_widget` 仍然存在，但以 `headless=True` 构造 —— 它只作业务控制器
    与对话框的窗口父，表格本身由 `IndustryPage.qml` 里的 `PlanTablePane` 渲染。
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
        self._proc_rows: list[dict] = []  # 本次汇总的计划集（供完成回调按新指纹补算）
        self._refresh_worker = None
        self._score_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 计划表：只作业务控制器（headless 不再自建 QML 宿主），桥注入给 QML 树
        self._plan_table_widget = PlanTable(headless=True)
        # 注入价格设置/人物访问器（母项拆解利润预览用）
        self._plan_table_widget.set_price_context(get_price_settings, lambda: MAIN_CHAR_NAME)
        self._plan_table_widget.plan_updated.connect(self.load_plans)
        self._plan_table_widget.refresh_requested.connect(self.load_plans)
        self._plan_table_widget.plan_detail_requested.connect(self._on_plan_detail)
        self._plan_table_widget.launcher_requested.connect(self._on_launch_wizard_from_row)

        self._bridge = IndustryBridge(self, self)
        self._host = PageHost(
            QML_PAGE,
            context={
                "bridge": self._bridge,
                "planTableBridge": self._plan_table_widget.bridge,
            },
            parent=self,
        )
        root.addWidget(self._host)

        # ── 初始加载 ───────────────────────────────────────────
        self.load_plans()

        # ── 倒计时定时器（进行中计划剩余时间 → 到期自动转待下线）──
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(30 * 1000)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._countdown_timer.start()

        # ── 后台补拉工业数据（成本指数/设施，首次访问时自动）───────
        QTimer.singleShot(200, self._check_industry_data)

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

    def showEvent(self, event):
        """页面重新可见时同步价格设置。

        材料倍率与仓库页（导入预览 / 批量设置成本价）是**同一个** settings.json 字段，
        在那边改完回到本页时，工具栏旋钮不能还停在旧值。
        """
        super().showEvent(event)
        self._bridge.reloadPriceSettings()

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
        from ui_pyside6.models.industry_models import PlanTableModel

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
        price_fp = self._price_fp()
        fp = (
            price_fp,
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
            self._proc_rows = procur
            return
        region_id, price_type, price_mult, default_hangar_id = price_fp
        self._proc_fp = fp
        self._proc_result = None
        self._proc_rows = procur
        self._proc_worker = ProcurementSummaryWorker(
            procur,
            default_mat_hangar_id=default_hangar_id,
            region_id=region_id,
            price_type=price_type,
            price_mult=price_mult,
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
            pending_rows = self._proc_rows
            self._proc_fp = None
            self._proc_result = None
            self._refresh_procurement_summary(pending_rows)

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
        """\u641c\u7d22\u7269\u54c1 -> \u8bc4\u5206 -> AddPlanDialog -> INSERT\uff08\u7528\u7528\u6237\u8bbe\u5b9a\u7684 ME/TE \u91cd\u7b97\uff09"""
        text = text.strip()
        if not text:
            return

        from PySide6.QtWidgets import QDialog

        from ui_pyside6.dialogs.industry_dialogs import AddPlanDialog

        # 1) \u641c\u7d22\u7269\u54c1\uff08\u8d70 repository\uff0c\u4e0d\u5728 UI \u76f4\u8fde SQLite\uff09
        items = get_container().item_repo.search_by_name(text, limit=10)

        if not items:
            QMessageBox.information(self, "\u63d0\u793a", f"\u672a\u627e\u5230\u7269\u54c1: {text}")
            return

        type_id = items[0]["type_id"]
        product_name = items[0]["zh_name"] or items[0]["en_name"] or str(type_id)

        # 2) \u68c0\u67e5\u662f\u5426\u53ef\u5236\u9020\uff08\u8d70 repository\uff09
        has_bp = get_container().blueprint_repo.get_blueprint_for_product(type_id) is not None

        if not has_bp:
            QMessageBox.information(
                self, "\u63d0\u793a", f"\u300c{product_name}\u300d\u6ca1\u6709\u5236\u9020\u84dd\u56fe"
            )
            return

        # 3) \u521d\u6b65\u8bc4\u5206\uff08ME=0/TE=0 \u9884\u89c8\u7528\uff09
        from services.char_config_resolver import resolve_char_config
        from ui_pyside6.workers.industry_workers import ScoreWorker

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
            dlg = AddPlanDialog(product_name, result, self)
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
            QMessageBox.information(self, "\u5b8c\u6210", f"\u5df2\u6dfb\u52a0\u8ba1\u5212: {product_name}")

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
        from ui_pyside6.views.procurement_tab import ProcurementDialog

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
            QMessageBox.information(self, "提示", "没有活跃计划")
            return
        QMessageBox.information(self, "完成", f"已保存 {count} 个价格快照")

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
            QMessageBox.information(self, "提示", "没有待下线的计划")
            return
        from services.inventory_manager import get_hangars
        from services.user_settings import get_default_hangar_id
        from ui_pyside6.views.industry.complete_guard import confirm_bp_shortfall

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
        if result["failed"]:
            msg += f"，失败 {len(result['failed'])} 项"
            # 只报产品名等于没说：把 complete_plan 的拒绝原因带出来
            reasons = result.get("failed_reasons") or []
            if reasons:
                msg += "\n\n" + "\n".join(reasons[:10])
        QMessageBox.information(self, "完成", msg)

    def _on_launch_wizard_from_row(self, char_name: str):
        """行右键入口：初始定位到该行所属人物（空串=未分配）。"""
        self.open_launcher(char_name)

    def open_launcher(self, char_name: str | None) -> None:
        """打开共享的产线启动小助手窗口（单实例，重复打开复用）。

        功能按钮（`char_name=None`）与计划表行右键（带人物名）共用这一条路径。
        """
        from ui_pyside6.views.industry.production_launcher import ProductionLauncher

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
