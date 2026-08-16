"""生产计划管理 — 统一页面（5 区布局）"""

from __future__ import annotations

from datetime import UTC

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.logger import log
from ui_pyside6.views.char_settings_view import load_all_data
from ui_pyside6.views.industry import (
    ActionButtons,
    BlueprintRequirementsDialog,
    CharacterUsageDialog,
    GanttView,
    MaterialsSummaryDialog,
    OutputSummaryDialog,
    PlanTable,
    StatusBar,
    TopToolbar,
)
from ui_pyside6.views.industry.complete_plans_dialog import CompletePlansDialog, complete_plans
from ui_pyside6.views.manufacturable_items_dialog import ManufacturableItemsDialog
from ui_pyside6.workers.industry_workers import BatchPlanCalcWorker, ProcurementSummaryWorker

# ── 工业数据后台补拉 ──


class IndustryDataWorker(QThread):
    """后台线程拉取工业系统成本指数 + 设施数据"""

    finished = Signal(bool, str)  # success, message

    def run(self):
        try:
            import asyncio

            from services.importers.getindustry import run_industry_update

            asyncio.run(run_industry_update())
            self.finished.emit(True, "工业数据拉取完成")
        except Exception as e:
            log.exception("工业数据拉取失败: %s", e)
            self.finished.emit(False, str(e))


def init_plan_db():
    """初始化 production_plans 表。

    production_plans 的 schema 单一来源是 PlanRepository.SCHEMA；
    price_snapshots 已由 schema_migrations user v10→v11 统一管理，不再在 UI 层建表。
    """
    try:
        get_container().plan_repo.ensure_table()
    except Exception:
        log.exception("初始化生产计划数据库失败")


class PlanPriceRefreshWorker(QThread):
    """定向拉取计划涉及物品的 ESI 市场价格——带 5 分钟缓存"""

    finished = Signal(bool, str)  # success, message

    _CACHE_TTL = 300  # 5 分钟缓存有效期（秒）

    def __init__(self, type_ids: set[int], parent=None):
        super().__init__(parent)
        self._type_ids = type_ids

    def run(self):
        import asyncio

        try:
            count = asyncio.run(self._fetch_and_save())
            if count == 0:
                self.finished.emit(True, "价格数据在缓存有效期内（5分钟），直接使用缓存数据")
            else:
                self.finished.emit(True, f"已刷新 {count} 个物品的价格")
        except Exception as e:
            log.exception("定向价格刷新失败")
            self.finished.emit(False, str(e))

    async def _check_cache(self, db) -> set[int]:
        """检查哪些 type_id 已过期（无数据或超过 TTL），返回需要刷新的 type_id 集合。"""
        stale: set[int] = set()
        from datetime import datetime

        now = datetime.now(UTC)
        cursor = await db.execute(
            "SELECT type_id, fetch_time FROM market_prices WHERE type_id IN ({}) AND region_id=10000002".format(
                ",".join("?" for _ in self._type_ids)
            ),
            list(self._type_ids),
        )
        rows = await cursor.fetchall()
        fetched = {r[0] for r in rows}
        # 无数据 → 需要刷新
        stale.update(self._type_ids - fetched)
        for tid, ft_str in rows:
            try:
                # fetch_time 格式: "YYYY-MM-DD HH:MM:SS" (SQLite localtime)
                ft = datetime.strptime(ft_str, "%Y-%m-%d %H:%M:%S")
                ft = ft.replace(tzinfo=UTC)
                if (now - ft).total_seconds() > self._CACHE_TTL:
                    stale.add(tid)
            except (ValueError, TypeError):
                stale.add(tid)
        return stale

    async def _fetch_and_save(self) -> int:
        """异步拉取 ESI + 写入 market.db（仅拉取缓存过期的物品）"""
        import asyncio

        import aiosqlite

        from core.paths import market_db_path

        MKT_DB = market_db_path()

        # 1. 检查缓存：哪些 type_id 需要刷新
        async with aiosqlite.connect(MKT_DB) as db:
            stale_ids = await self._check_cache(db)

        if not stale_ids:
            log.info("定向价格: 所有物品均在缓存有效期内，跳过刷新")
            return 0

        # 2. 并发拉取过期物品的 Jita 订单（统一走 APIClient 全局限流）
        from services.client import APIClient

        ESI_BASE = "https://esi.evetech.net/latest"
        REGION_JITA = 10000002

        type_orders: dict[int, dict] = {}

        async with APIClient(timeout=180, concurrency=50) as client:
            async def fetch_item_orders(tid: int) -> tuple[int, dict]:
                url = f"{ESI_BASE}/markets/{REGION_JITA}/orders/"
                result: dict = {"buy_price": 0.0, "sell_price": float("inf"), "buy_volume": 0, "sell_volume": 0}

                async def fetch_one(order_type: str) -> list[dict]:
                    try:
                        data = await client.fetch_raw(f"{url}?type_id={tid}&order_type={order_type}")
                        return data if isinstance(data, list) else []
                    except Exception:
                        log.warning("拉取 %s type_id=%s 失败", order_type, tid)
                        return []

                buy_data, sell_data = await asyncio.gather(fetch_one("buy"), fetch_one("sell"))

                for o in buy_data:
                    if o["price"] > result["buy_price"]:
                        result["buy_price"] = o["price"]
                    result["buy_volume"] += o.get("volume_remain", 0)

                for o in sell_data:
                    if o["price"] < result["sell_price"]:
                        result["sell_price"] = o["price"]
                    result["sell_volume"] += o.get("volume_remain", 0)

                if result["sell_price"] == float("inf"):
                    result["sell_price"] = 0.0

                return tid, result

            tasks = [fetch_item_orders(tid) for tid in stale_ids]
            gathered = await asyncio.gather(*tasks, return_exceptions=True)

            for g in gathered:
                if isinstance(g, Exception):
                    log.warning("物品订单拉取异常: %s", g)
                    continue
                tid, result = g  # type: ignore[misc]
                type_orders[tid] = result

        # 3. 写入 market_prices（只写入实际拉取到的过期物品）
        count = 0
        async with aiosqlite.connect(MKT_DB) as db:
            for tid in stale_ids:
                p = type_orders.get(tid)
                if not p:
                    continue
                cur = await db.execute(
                    """UPDATE market_prices
                       SET buy_price=?, sell_price=?, buy_volume=?, sell_volume=?,
                           fetch_time=datetime('now')
                       WHERE type_id=? AND region_id=?""",
                    (
                        p["buy_price"],
                        p["sell_price"],
                        int(p["buy_volume"]),
                        int(p["sell_volume"]),
                        tid,
                        REGION_JITA,
                    ),
                )
                if cur.rowcount == 0:
                    await db.execute(
                        """INSERT INTO market_prices
                           (type_id, region_id, buy_price, sell_price, adjusted_price,
                            buy_volume, sell_volume, fetch_time)
                           VALUES (?, ?, ?, ?, 0.0, ?, ?, datetime('now'))""",
                        (
                            tid,
                            REGION_JITA,
                            p["buy_price"],
                            p["sell_price"],
                            int(p["buy_volume"]),
                            int(p["sell_volume"]),
                        ),
                    )
                count += 1
            await db.commit()

        log.info("定向价格刷新完成: %s 个物品（缓存跳过 %s 个）", count, len(self._type_ids) - len(stale_ids))
        return count


class IndustryPage(QWidget):
    """生产计划管理统一页面 — 5 区布局"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        init_plan_db()
        self.setObjectName("industry_page")
        self._recalc_worker = None
        self._proc_worker: QThread | None = None
        self._proc_fp: tuple | None = None
        self._proc_result: tuple[float, float] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 1. 页面标题栏 ──────────────────────────────────────
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(12, 8, 12, 4)
        title_bar.setSpacing(12)
        self._title_label = QLabel("生产规划")
        title_bar.addWidget(self._title_label)
        self._plan_count = QLabel("")
        title_bar.addWidget(self._plan_count)
        title_bar.addStretch(1)
        root.addLayout(title_bar)

        # ── 2. 顶部工具栏 ──────────────────────────────────────
        self._toolbar = TopToolbar()
        root.addWidget(self._toolbar)

        # ── 3. 视图切换区域（数据表格 / 甘特图）──────────────────
        self._view_stack = QStackedWidget()

        # 页0: 数据视图（表格 + 添加按钮）
        data_page = QWidget()
        data_layout = QVBoxLayout(data_page)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(0)
        self._plan_table_widget = PlanTable()
        data_layout.addWidget(self._plan_table_widget, 1)
        self._view_stack.addWidget(data_page)

        # 页1: 甘特图
        self._gantt_view = GanttView()
        gantt_scroll = QScrollArea()
        gantt_scroll.setWidget(self._gantt_view)
        gantt_scroll.setWidgetResizable(True)
        gantt_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._view_stack.addWidget(gantt_scroll)

        root.addWidget(self._view_stack, 1)  # stretch=1 填充剩余空间

        # ── 4. 底部状态栏 ──────────────────────────────────────
        self._status_bar = StatusBar()
        root.addWidget(self._status_bar)

        # ── 5. 底部功能按钮 ────────────────────────────────────
        self._action_buttons = ActionButtons()
        root.addWidget(self._action_buttons)

        # ── 信号连接 ───────────────────────────────────────────
        self._connect_signals()

        # ── 初始加载 ───────────────────────────────────────────
        self.load_plans()

        # ── 倒计时定时器（进行中计划剩余时间 → 到期自动转待下线）──
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(30 * 1000)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._countdown_timer.start()

        # ── 后台补拉工业数据（成本指数/设施，首次访问时自动）───────
        QTimer.singleShot(200, self._check_industry_data)

        # ── 主题 ───────────────────────────────────────────────
        theme.add_theme_listener(self._on_theme_changed)

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

    # ── 信号连接 ──────────────────────────────────────────────

    def _connect_signals(self):
        # TopToolbar
        self._toolbar.refresh_requested.connect(self._on_industry_refresh)
        self._toolbar.filter_changed.connect(self.load_plans)
        self._toolbar.price_setting_changed.connect(self.load_plans)
        self._toolbar.plan_add_requested.connect(self._on_plan_add)
        self._toolbar.manufacturable_browser_requested.connect(self._on_manufacturable_browser)

        self._toolbar.view_changed.connect(self._on_view_changed)

        # PlanTable
        self._plan_table_widget.plan_updated.connect(self.load_plans)
        self._plan_table_widget.refresh_requested.connect(self.load_plans)
        self._plan_table_widget.plan_detail_requested.connect(self._on_plan_detail)

        # StatusBar
        self._status_bar.save_price_requested.connect(self._on_save_prices)
        self._status_bar.complete_all_requested.connect(self._on_complete_all)

        # ActionButtons
        self._action_buttons.launch_wizard_requested.connect(self._on_launch_wizard)
        self._action_buttons.refresh_procurement_requested.connect(self._on_procurement)
        self._action_buttons.blueprint_list_requested.connect(self._on_blueprint_list)
        self._action_buttons.materials_summary_requested.connect(self._on_materials_summary)
        self._action_buttons.output_summary_requested.connect(self._on_output_summary)
        self._action_buttons.char_usage_requested.connect(self._on_char_usage)

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

        with get_container().db.connect("user", "bp") as conn:
            f = self._toolbar.get_filter()
            sql = "SELECT * FROM production_plans"
            if f == "待排":
                sql += " WHERE status = 'pending'"
            elif f == "运行中":
                sql += " WHERE status IN ('in_progress','running')"
            elif f == "待下线":
                sql += " WHERE status = 'ready'"
            elif f == "已完成":
                sql += " WHERE status IN ('completed','done')"
            sql += " ORDER BY created_at DESC"
            c = conn.cursor()
            c.execute(sql)
            cols = [d[0] for d in c.description]
            rows = [dict(zip(cols, r, strict=False)) for r in c.fetchall()]

            # 填充蓝图列「有图/没图」：用户库存中是否有该产品对应蓝图
            owned_bp = {r[0] for r in conn.execute("SELECT DISTINCT blueprint_type_id FROM user_blueprints").fetchall()}
            prod_to_bp: dict[int, list[int]] = {}
            for tid, bpid in conn.execute(
                "SELECT product_type_id, blueprint_type_id FROM bp.blueprint_products WHERE activity='manufacturing'"
            ).fetchall():
                prod_to_bp.setdefault(tid, []).append(bpid)
            # 机库名称映射：设施列（材料机库）/输出列（输出机库）显示用
            hangar_names = dict(conn.execute("SELECT id, name FROM hangars").fetchall())
        for row in rows:
            ptid = row.get("product_type_id")
            has_bp = bool(row.get("assigned_blueprint_id")) or any(b in owned_bp for b in prod_to_bp.get(ptid, []))
            row["has_image"] = has_bp
            # 兼容 key 映射：DB 列 group_number/sub_level → 模型读取的 group_id/child_level
            row["group_id"] = row.get("group_number", 0)
            row["child_level"] = row.get("sub_level", 0)

        # 类别列：从蓝图活动批量推导（反应/发明/拷贝/制造）
        from services.plan_category import load_category_map

        bp_ids = [r.get("blueprint_type_id") for r in rows if r.get("blueprint_type_id")]
        cat_map: dict[int, str] = {}
        if bp_ids:
            with get_container().db.connect("bp") as bp_conn:
                cat_map = load_category_map(bp_conn, bp_ids)
        for row in rows:
            row["category"] = cat_map.get(row.get("blueprint_type_id"), "manufacturing")
        # 设施列（材料机库名）/ 输出列（输出机库名）：显示层补全，不落库
        from services.plan_service import enrich_plan_hangar_names

        enrich_plan_hangar_names(rows, hangar_names)
        from ui_pyside6.models.industry_models import PlanTableModel

        # 注入当前材料机库（启动旧计划时兜底）
        self._plan_table_widget.set_mat_hangar_id(self._toolbar.get_mat_hangar_id())

        # 复用已有 model，避免 setModel 清除选中状态
        model = self._plan_table_widget.get_model()
        if model is None:
            model = PlanTableModel(rows)
            self._plan_table_widget.set_model(model)
        else:
            model.set_plans(rows)

        self._status_bar.update_stats(rows)
        self._refresh_procurement_summary(rows)
        self._plan_count.setText(f"共 {len(rows)} 条计划")

        # 如果当前是甘特图模式，同步刷新甘特图
        if self._view_stack.currentIndex() == 1:
            self._refresh_gantt()
        self._auto_calculate_plans(rows)

    def _refresh_procurement_summary(self, rows: list[dict]):
        """刷新状态栏「备料中采购」汇总。

        DB 查询较重，放后台线程；带指纹缓存避免数据未变时重复查询。
        「备料中」= 未运行（pending）且已勾选备料（materials_ready==1）；
        ready 计划材料已扣库存，计入会虚高，排除。
        """
        procur = [p for p in rows if p.get("materials_ready", 0) and (p.get("status") or "pending") == "pending"]
        fp = tuple(
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
        )
        if fp == self._proc_fp and self._proc_result is not None:
            self._status_bar.update_material(*self._proc_result)
            return
        if not procur:
            self._status_bar.update_material(0.0, 0.0)
            self._proc_fp = None
            self._proc_result = None
            return
        if self._proc_worker and self._proc_worker.isRunning():
            return  # 已有汇总线程运行中（严禁 terminate），等其完成
        ps = self._toolbar.get_price_settings()
        mat_hub = ps.get("mat_hub")
        mat_price_type = ps.get("mat_price_type") or "sell"
        self._proc_fp = fp
        self._proc_result = None
        self._proc_worker = ProcurementSummaryWorker(
            procur,
            default_mat_hangar_id=self._toolbar.get_mat_hangar_id(),
            region_id=TRADE_HUB_IDS.get(mat_hub, 10000002),
            price_type=mat_price_type,
            parent=self,
        )
        self._proc_worker.finished.connect(self._on_procurement_summary_done)
        self._proc_worker.start()

    def _on_procurement_summary_done(self, cost: float, vol: float):
        """采购汇总线程完成 → 更新状态栏（stale guard 防旧线程结果覆盖新指纹）"""
        if self._proc_worker is not self.sender():
            return
        self._proc_result = (cost, vol)
        self._status_bar.update_material(cost, vol)

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
        ps = self._toolbar.get_price_settings()
        self._recalc_worker = BatchPlanCalcWorker(
            todo,
            char_config,
            char_name=current_char,
            mat_hub=ps["mat_hub"],
            mat_price_type=ps["mat_price_type"],
            prod_hub=ps["prod_hub"],
            prod_price_type=ps["prod_price_type"],
            parent=self,
        )
        self._recalc_worker.finished.connect(self._on_recalc_done)
        self._recalc_worker.start()

    def _on_recalc_done(self, results: list):
        """批量重算完成 → 更新数据库并刷新显示"""
        if not results:
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
            ) in results:
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
        self._status_bar.show_message("正在后台拉取工业数据...")
        self._industry_worker = IndustryDataWorker(parent=self)
        self._industry_worker.finished.connect(self._on_industry_data_ready)
        self._industry_worker.start()

    def _on_industry_data_ready(self, success: bool, message: str):
        if success:
            log.info("工业数据后台拉取完成")
            self._status_bar.show_message("工业数据拉取完成", timeout=5000)
        else:
            log.warning("工业数据拉取失败: %s", message)
            self._status_bar.show_message(f"工业数据拉取失败: {message}", timeout=8000)

    def _on_view_changed(self, view_mode: str):
        if view_mode == "gantt":
            self._view_stack.setCurrentIndex(1)
            self._refresh_gantt()
            self._status_bar.setVisible(False)
            self._action_buttons.setVisible(False)
        else:
            self._view_stack.setCurrentIndex(0)
            self._status_bar.setVisible(True)
            self._action_buttons.setVisible(True)

    def _refresh_gantt(self):
        model = self._plan_table_widget.get_model()
        plans = []
        if model:
            for row in range(model.rowCount()):
                p = model.get_plan(row)
                if p:
                    plans.append(p)
        self._gantt_view.load_from_plans(plans)

    # ── 价格定向刷新 ────────────────────────────────────────────

    def _on_industry_refresh(self):
        """刷新按钮点击 → 收集 type_id → 启动定向 ESI 价格拉取"""
        # 1. 获取活跃计划
        with get_container().db.connect("user") as conn:
            c = conn.execute(
                "SELECT id, product_type_id FROM production_plans "
                "WHERE status IN ('pending','in_progress','running','ready')"
            )
            plans = c.fetchall()

        if not plans:
            self.load_plans()
            return

        # 2. 收集产品 type_ids
        product_ids = {r[1] for r in plans}

        # 3. 从 blueprint.db 查物料 type_ids（复用 _on_save_prices 的 JOIN 写法）
        with get_container().db.connect("bp") as conn:
            placeholders = ",".join("?" for _ in product_ids)
            c = conn.execute(
                "SELECT DISTINCT bm.material_type_id "
                "FROM blueprint_products bp "
                "JOIN blueprint_materials bm ON bm.blueprint_type_id=bp.blueprint_type_id "
                "AND bm.activity=bp.activity "
                f"WHERE bp.product_type_id IN ({placeholders}) AND bp.activity='manufacturing'",
                list(product_ids),
            )
            material_ids = {r[0] for r in c.fetchall()}

        # 4. 合并为唯一 type_ids
        all_ids: set[int] = product_ids | material_ids
        if not all_ids:
            self.load_plans()
            return

        # 5. 进度反馈 + 启动后台拉取
        # 先检查缓存是否有效（如果全部已缓存则跳过进度提示）
        is_cached = 0
        with get_container().db.connect("mkt") as conn:
            ph = ",".join("?" for _ in all_ids)
            c = conn.execute(
                f"SELECT COUNT(*) FROM market_prices WHERE type_id IN ({ph}) "
                "AND region_id=10000002 "
                "AND fetch_time > datetime('now', '-5 minutes', 'utc')",
                list(all_ids),
            )
            is_cached = (c.fetchone() or [0])[0]

        suffix = "（可能使用缓存）" if is_cached == len(all_ids) else ""
        self._status_bar.show_message(f"正在获取 {len(all_ids)} 个物品的价格{suffix}...")
        self._refresh_worker = PlanPriceRefreshWorker(all_ids, self)
        self._refresh_worker.finished.connect(self._on_industry_refresh_done)
        self._refresh_worker.start()

    def _on_industry_refresh_done(self, success: bool, message: str):
        """价格拉取完成 → 刷新显示 + 状态栏反馈"""
        if success:
            self._status_bar.show_message(message, timeout=5000)
        else:
            self._status_bar.show_message(f"价格刷新失败: {message}", timeout=8000)
        self.load_plans()

    # ── 对话框打开方法 ────────────────────────────────────────

    def _on_plan_add(self, text: str):
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

        char_name = self._toolbar.get_char_name()
        ps = self._toolbar.get_price_settings()
        from services import inventory_manager

        preview_system_id = inventory_manager.get_hangar_system_id(self._toolbar.get_mat_hangar_id())

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
            dlg = AddPlanDialog(product_name, result, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data()
            if not data:
                return
            # \u4ece\u6750\u6599\u673a\u5e93\u5e26\u51fa\u6240\u5728\u661f\u7cfb\uff08\u661f\u7cfb\u6210\u672c\u6307\u6570\u5f71\u54cd\u5b89\u88c5\u8d39\uff09\uff1bfacility \u672a\u586b\u65f6\u7528\u6750\u6599\u673a\u5e93\u540d\u79f0
            mat_hangar_id = self._toolbar.get_mat_hangar_id()
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
                )
            )
            # \u7edf\u4e00\u8d70 plan_service \u843d\u5e93\uff08\u907f\u514d UI \u5185\u8054 INSERT \u91cd\u590d\uff09
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
                deposit_hangar_id=self._toolbar.get_hangar_id(),
                metrics=metrics,
            )
            self.load_plans()
            QMessageBox.information(self, "\u5b8c\u6210", f"\u5df2\u6dfb\u52a0\u8ba1\u5212: {product_name}")

        self._score_worker.finished.connect(_on_score)
        self._score_worker.start()

    def _on_manufacturable_browser(self):
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

    def _on_blueprint_list(self):
        dlg = BlueprintRequirementsDialog(self)
        dlg.exec()

    def _on_materials_summary(self):
        dlg = MaterialsSummaryDialog(self)
        dlg.exec()

    def _on_output_summary(self):
        dlg = OutputSummaryDialog(self)
        dlg.exec()

    def _on_char_usage(self):
        dlg = CharacterUsageDialog(self)
        dlg.exec()

    def _on_procurement(self):
        """打开待采购对话框"""
        from ui_pyside6.views.procurement_tab import ProcurementDialog

        plans = []
        with get_container().db.connect("user", "ref", "mkt") as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, product_type_id, product_name, runs, parallels, me_level, mat_hub, sell_hub, "
                "materials_ready, status, deposit_hangar_id, deposited, material_cost, "
                "assigned_blueprint_id, mat_hangar_id, material_short, group_number, sub_level "
                "FROM production_plans WHERE status IN ('pending', 'in_progress', 'running', 'ready')"
            )
            for pr in c.fetchall():
                plans.append(
                    {
                        "id": pr[0],
                        "product_type_id": pr[1],
                        "product_name": pr[2],
                        "runs": pr[3],
                        "parallels": pr[4],
                        "me_level": pr[5],
                        "mat_hub": pr[6],
                        "sell_hub": pr[7],
                        "materials_ready": pr[8],
                        "status": pr[9],
                        "deposit_hangar_id": pr[10],
                        "deposited": pr[11],
                        "material_cost": pr[12],
                        "assigned_blueprint_id": pr[13],
                        "mat_hangar_id": pr[14],
                        "material_short": pr[15],
                        "group_id": pr[16],
                        "child_level": pr[17],
                    }
                )
        if not plans:
            QMessageBox.information(self, "提示", "没有活跃计划")
            return
        ps = self._toolbar.get_price_settings()
        dlg = ProcurementDialog(plans, ps["mat_hub"], ps["prod_hub"], self)
        dlg.exec()
        self.load_plans()

    # ── 保存价格快照 ──────────────────────────────────────────

    def _on_save_prices(self):
        with get_container().db.connect("user", "ref", "mkt", "bp") as conn:
            c = conn.cursor()
            c.execute(
                "SELECT product_type_id FROM production_plans WHERE status IN ('pending','in_progress','running')"
            )
            plan_pids = [r[0] for r in c.fetchall()]
            if not plan_pids:
                QMessageBox.information(self, "提示", "没有活跃计划")
                return
            placeholders = ",".join("?" for _ in plan_pids)
            c.execute(
                "SELECT DISTINCT bm.material_type_id "
                "FROM bp.blueprint_products bp "
                "JOIN bp.blueprint_materials bm "
                "ON bm.blueprint_type_id=bp.blueprint_type_id "
                "AND bm.activity=bp.activity "
                f"WHERE bp.product_type_id IN ({placeholders}) "
                "AND bp.activity='manufacturing'",
                plan_pids,
            )
            type_ids = {r[0] for r in c.fetchall()}
            type_ids.update(plan_pids)
            count = 0
            for tid in type_ids:
                c.execute(
                    "SELECT sell_price, buy_price FROM mkt.market_prices "
                    "WHERE type_id=? AND region_id=10000002 LIMIT 1",
                    (tid,),
                )
                row = c.fetchone()
                if row:
                    conn.execute(
                        "INSERT OR IGNORE INTO price_snapshots(type_id,region_id,sell_price,buy_price) "
                        "VALUES (?,10000002,?,?)",
                        (tid, row[0] or 0, row[1] or 0),
                    )
                    count += 1
            QMessageBox.information(self, "完成", f"已保存 {count} 个价格快照")

    def _on_complete_all(self):
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

        hangars = get_hangars()
        default_hid = get_default_hangar_id("default_deposit_hangar_id")
        dlg = CompletePlansDialog(ready, hangars, default_hid, self)
        if not dlg.exec():
            return
        result = complete_plans(ready, dlg.selected_hangar_id())
        self.load_plans()
        msg = f"已下线 {result['completed']} 项"
        if result["deposited"]:
            msg += f"，入库 {result['deposited']} 项"
        if result["failed"]:
            msg += f"，失败 {len(result['failed'])} 项"
        QMessageBox.information(self, "完成", msg)

    def _on_launch_wizard(self):
        """产线启动小助手（一级菜单）：收集全部活跃计划 → 打开启动向导"""
        model = self._plan_table_widget.get_model()
        if model is None:
            return
        plans = []
        for i in range(model.rowCount()):
            plan = model.get_plan(i)
            if plan and (plan.get("status") or "").lower() in ("pending", "in_progress", "running", "ready"):
                plans.append(plan)
        if not plans:
            QMessageBox.information(self, "提示", "没有活跃的计划")
            return
        from ui_pyside6.dialogs.production_wizard import ProductionWizard

        mat_hangar_id = self._toolbar.get_mat_hangar_id()
        dlg = ProductionWizard(plans, self, mat_hangar_id=mat_hangar_id)
        dlg.exec()
        self.load_plans()

    # ── 状态保存/恢复 ─────────────────────────────────────────

    def save_state(self) -> dict:
        data = {}
        table = self._plan_table_widget.get_table()
        vs = table.verticalScrollBar()
        if vs:
            data["v_scroll"] = vs.value()
        return data

    def restore_state(self, data: dict) -> None:
        if not data:
            return
        table = self._plan_table_widget.get_table()
        vs = table.verticalScrollBar()
        if vs and "v_scroll" in data:
            vs.setValue(data["v_scroll"])

    # ── 外部刷新接口 ──────────────────────────────────────────

    def refresh_display(self):
        self.load_plans()

    def update_status_bar(self):
        self.load_plans()

    # ── 主题 ──────────────────────────────────────────────────

    def _on_theme_changed(self):
        self._title_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 16px; font-weight: bold; background: transparent;"
        )
        self._plan_count.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 13px; background: transparent;")
