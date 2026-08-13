"""
初始化流程控制器 — 状态管理 + 进度信号 + 重试/跳过

用法(CLI):
    from services.init_service import InitService
    service = InitService()
    asyncio.run(service.run_all())

用法(GUI):
    service = InitService()
    service.step_progress.connect(on_progress)
    service.start()
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

from core.logger import log

try:
    from PySide6.QtCore import QObject, Signal
except ImportError:
    # 无 Qt 环境（CLI 模式）下 fallback
    class Signal:  # type: ignore[no-redef]
        def __init__(self, *types): ...
        def connect(self, slot): ...
        def emit(self, *args): ...

    class QObject:  # type: ignore[no-redef]
        pass


# ── 步骤定义 ──


@dataclass
class InitStep:
    """单个初始化步骤的元信息"""

    key: str
    name: str
    needs_network: bool = True
    critical: bool = True  # True = 不能跳过, False = 可选
    depends_on: list[str] = field(default_factory=list)  # 前置步骤 key


class StepStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    SKIPPED = auto()
    CANCELLED = auto()


# ── 默认步骤列表 ──

STEPS = [
    InitStep("schema", "数据库结构", needs_network=False, critical=True),
    InitStep("items", "物品数据", needs_network=True, critical=True, depends_on=["schema"]),
    # 完整订单簿价格不属于初始化职责——由主窗口后台更新（自动更新默认开启）。
    # 初始化只做「价格基础数据」兜底：全新安装（market_prices 为空）时快速拉一次
    # /markets/prices/ 基准价，非关键步骤不阻塞主窗口。
    InitStep("price_baseline", "价格基础数据", needs_network=True, critical=False, depends_on=["items"]),
    InitStep("blueprints", "蓝图数据", needs_network=True, critical=True, depends_on=["items"]),
    InitStep("implants", "植入体数据", needs_network=True, critical=False, depends_on=["items"]),
    InitStep("rigs", "结构改装件数据", needs_network=True, critical=False, depends_on=["items"]),
    InitStep("industry", "工业数据", needs_network=True, critical=True, depends_on=["items"]),
    InitStep("icons", "物品图标", needs_network=True, critical=False, depends_on=["items"]),
    InitStep("sde_data", "SDE扩展数据", needs_network=False, critical=True, depends_on=["items"]),
]

STEP_MAP: dict[str, InitStep] = {s.key: s for s in STEPS}


# ── 回调类型（CLI 模式） ──

StepStartedCb = Callable[[str, str], None]  # step_key, step_name
StepProgressCb = Callable[[str, int, str], None]  # step_key, percent, message
StepCompletedCb = Callable[[str, bool, str], None]  # step_key, success, message
AllCompletedCb = Callable[[bool, str], None]  # all_done, summary


def _noop(*args, **kwargs):
    pass


# ── 状态查询 ──


def is_step_satisfied(step_key: str) -> bool:
    """检查某步骤是否已就绪（数据是否存在）"""
    from services.init_check import check_all

    status = check_all()
    return bool(status.get(step_key, False))


def get_missing_steps() -> list[InitStep]:
    """返回所有未就绪的步骤（check_all 只跑一次，避免 8 次重复查询）"""
    from services.init_check import check_all

    status = check_all()
    return [s for s in STEPS if not status.get(s.key, False)]


def get_missing_count() -> int:
    """返回未就绪的步骤数"""
    return len(get_missing_steps())


# ══════════════════════════════════════════════════════
#  InitService
# ══════════════════════════════════════════════════════


class InitService(QObject):
    """初始化流程控制器

    信号（GUI 模式）：
        step_started(key, name)
        step_progress(key, percent, message)
        step_completed(key, success, message)
        all_completed(success, summary)
        network_status(ok, message)

    回调（CLI 模式）：
        on_step_started(key, name)
        on_step_progress(key, percent, message)
        on_step_completed(key, success, message)
        on_all_completed(success, summary)
    """

    # Qt 信号
    step_started = Signal(str, str)  # step_key, step_name
    step_progress = Signal(str, int, str)  # step_key, percent_0_100, message
    step_completed = Signal(str, bool, str)  # step_key, success, message
    all_completed = Signal(bool, str)  # all_done, summary
    network_status = Signal(bool, str)  # ok, message

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        # 每步状态: key → StepStatus
        self._status: dict[str, StepStatus] = {s.key: StepStatus.PENDING for s in STEPS}
        # 每步失败消息
        self._errors: dict[str, str] = {}
        # 当前正在执行的步骤（并行时可能多个）
        self._running: set[str] = set()
        # 本轮创建的 asyncio.Task 映射（并行调度用，key → Task）
        self._task_map: dict[str, asyncio.Task] = {}
        # 是否已取消
        self._cancelled = False
        # 本轮网络检查单飞任务（多个网络步骤并发时只查一次）
        self._net_task: asyncio.Task[bool] | None = None

        # CLI 模式回调
        self.on_step_started: StepStartedCb = _noop
        self.on_step_progress: StepProgressCb = _noop
        self.on_step_completed: StepCompletedCb = _noop
        self.on_all_completed: AllCompletedCb = _noop

    # ── 公开 API ──

    def start(self, step_keys: list[str] | None = None):
        """开始初始化

        Args:
            step_keys: 要执行的步骤 key 列表。None = 自动选择未就绪步骤。
        """
        # 重置跨事件循环的异步锁（重试会新建 asyncio.run，旧锁绑定上一循环会报错）
        from services.db_locks import reset_db_locks
        from services.importers.sde_cache import reset_async_locks

        reset_db_locks()
        reset_async_locks()

        self._cancelled = False
        self._net_task = None  # 重置本轮网络检查单飞任务
        targets = step_keys or [s.key for s in STEPS]
        # 过滤出需要执行的步骤
        to_run = [k for k in targets if self._status.get(k) in (StepStatus.PENDING, StepStatus.FAILED)]
        if not to_run:
            self._emit_all_completed(True, "所有步骤已完成")
            return

        asyncio.run(self._run_sequence(to_run))

    def retry(self, step_key: str):
        """重试单个失败步骤"""
        if self._status.get(step_key) != StepStatus.FAILED:
            return
        self._status[step_key] = StepStatus.PENDING
        self._errors.pop(step_key, None)
        self.start([step_key])

    def retry_all_failed(self):
        """重试所有失败步骤"""
        failed = [k for k, s in self._status.items() if s == StepStatus.FAILED]
        if not failed:
            return
        for k in failed:
            self._status[k] = StepStatus.PENDING
            self._errors.pop(k, None)
        self.start(failed)

    def skip(self, step_key: str) -> bool:
        """跳过非关键步骤。返回 True 表示跳过成功。"""
        step = STEP_MAP.get(step_key)
        if not step:
            return False
        if step.critical:
            return False
        if self._status.get(step_key) not in (StepStatus.PENDING, StepStatus.FAILED, StepStatus.RUNNING):
            return False
        self._status[step_key] = StepStatus.SKIPPED
        self._emit_step_completed(step_key, True, "已跳过（可选步骤）")
        return True

    def cancel(self):
        """取消当前执行（并行时取消所有正在运行的步骤）"""
        self._cancelled = True
        for key in list(self._running):
            self._status[key] = StepStatus.CANCELLED

    def get_status(self) -> dict[str, StepStatus]:
        """返回所有步骤的当前状态"""
        return dict(self._status)

    def get_errors(self) -> dict[str, str]:
        """返回所有失败步骤的错误消息"""
        return dict(self._errors)

    def reset(self):
        """重置所有步骤为 PENDING"""
        for k in self._status:
            self._status[k] = StepStatus.PENDING
        self._errors.clear()
        self._running.clear()
        self._task_map.clear()
        self._cancelled = False
        self._net_task = None

    # ── 网络检查 ──

    async def check_network(self) -> bool:
        """检查 ESI 连通性（带重试：网络抖动/慢响应不误判为不可用）。

        并行初始化时所有网络步骤共享这一次检查结果——单次 10s 超时且无重试时，
        赶上网速波动或事件循环短暂被同步大循环阻塞就会误判，连累整批网络步骤
        报"网络不可用"。重试 3 次、超时放宽到 15s、指数退避。
        """
        import aiohttp

        last_err: str | None = None
        for attempt in range(3):
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get("https://esi.evetech.net/status/") as resp:
                        if resp.status == 200:
                            msg = "ESI 连接正常"
                            self._emit_network(True, msg)
                            return True
                        last_err = f"ESI 返回 {resp.status}"
            except Exception as e:
                last_err = str(e)
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))  # 指数退避：2s, 4s

        msg = f"网络不可用: {last_err}"
        self._emit_network(False, msg)
        return False

    # ── 内部执行逻辑 ──

    async def _run_sequence(self, keys: list[str]):
        """按依赖图并行执行步骤列表。

        items 之前只有 schema/items（串行由 depends_on 保证）；
        items 之后的 7 步互不依赖，全部并发执行——icons/sde_data 等大头
        与 prices/implants/rigs/industry 重叠运行，总时长大幅缩短。
        单个步骤失败只影响其后继，不阻塞同层其它步骤。
        """
        self._running.clear()
        self._task_map.clear()
        self._net_task = None
        self._prepare_ref_db_for_parallel()

        tasks: dict[str, asyncio.Task] = {}
        for key in keys:
            step = STEP_MAP.get(key)
            if not step or self._status.get(key) in (StepStatus.COMPLETED, StepStatus.SKIPPED):
                continue
            tasks[key] = asyncio.create_task(self._run_one(key))
        self._task_map = tasks

        await asyncio.gather(*tasks.values(), return_exceptions=True)

        success_count = sum(1 for st in self._status.values() if st == StepStatus.COMPLETED)
        fail_count = sum(1 for st in self._status.values() if st == StepStatus.FAILED)
        # 只有关键步骤失败才阻止进入主窗口；非关键步骤（icons/implants/rigs）失败可跳过
        # —— 否则个别可选步骤失败会让启动对话框永远不关闭、主窗口不出现
        critical_failed = any(self._status[k] == StepStatus.FAILED and bool(STEP_MAP[k].critical) for k in self._status)
        all_done = not critical_failed
        summary = f"完成 {success_count}/{success_count + fail_count}"
        if fail_count == 0:
            summary = "全部初始化完成"
        self._emit_all_completed(all_done, summary)

        # 初始化结束，释放 YAML 解析缓存（typeIDs.yaml 148MB 等大文件）
        try:
            from services.importers.sde_cache import clear_yaml_cache

            clear_yaml_cache()
        except Exception:
            pass

    async def _run_one(self, key: str):
        """单个步骤任务：等依赖 → 网络检查 → 执行 → 上报（可并行运行）"""
        step = STEP_MAP.get(key)
        if not step:
            return

        # 1) 等待本轮执行的依赖任务完成（已完成/跳过/失败都不会抛异常，
        #    依赖失败由 _deps_satisfied 兜底判定 SKIPPED）
        for dep in step.depends_on:
            t = self._task_map.get(dep)
            if t:
                await t

        if self._cancelled:
            self._status[key] = StepStatus.CANCELLED
            self._emit_step_completed(key, False, "已取消")
            return

        # 2) 依赖就绪性（复用现有逻辑，含 is_step_satisfied 全局兜底）
        if not self._deps_satisfied(step):
            self._status[key] = StepStatus.SKIPPED
            self._emit_step_completed(key, True, "前置步骤未就绪，跳过")
            return

        # 3) 网络检查（单飞：全部网络步骤共享一次结果）。
        #    预检失败不立即 FAILED：大 YAML 解析（PyYAML C loader 持有 GIL）
        #    会阻塞事件循环线程，导致 aiohttp 预检请求超时误判"网络不可用"，
        #    连累整批网络步骤（用户看到"解析完网络就恢复了"）。让实际下载去验证
        #    ——APIClient 自带重试/限流，真没网会在下载阶段失败。
        if step.needs_network:
            if not await self._ensure_net_once():
                log.warning(
                    "步骤 %s：网络预检未通过，继续尝试实际下载（可能因大 YAML 解析阻塞事件循环误判）",
                    key,
                )

        # 4) 执行
        self._running.add(key)
        self._status[key] = StepStatus.RUNNING
        self._emit_step_started(key, step.name)
        try:
            success, msg = await self._run_step(key)
            if self._cancelled:
                self._status[key] = StepStatus.CANCELLED
                self._emit_step_completed(key, False, "已取消")
            elif success:
                self._status[key] = StepStatus.COMPLETED
                self._emit_step_completed(key, True, msg)
            else:
                self._status[key] = StepStatus.FAILED
                self._errors[key] = msg
                self._emit_step_completed(key, False, msg)
        except Exception as e:
            self._status[key] = StepStatus.FAILED
            msg = str(e)
            self._errors[key] = msg
            self._emit_step_completed(key, False, msg)
        finally:
            self._running.discard(key)

    async def _ensure_net_once(self) -> bool:
        """网络检查单飞：并发请求合并为一次 check_network，结果共享。"""
        if self._net_task is None:
            self._net_task = asyncio.create_task(self.check_network())
        return await self._net_task

    @staticmethod
    def _prepare_ref_db_for_parallel():
        """并行前准备 reference.db：WAL + 长 busy_timeout。

        items/industry/implants/rigs/sde_data 五步都会写 reference.db，
        WAL 允许读写并发、多写者排队而非立即报 database is locked；
        busy_timeout 是本连接级参数，真正持久化的是 journal_mode=WAL。
        """
        import sqlite3

        from core.paths import reference_db_path

        try:
            conn = sqlite3.connect(reference_db_path(), timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.close()
        except Exception:
            # 库尚不存在（全新初始化时 schema 步骤会创建），静默跳过
            pass

    def _deps_satisfied(self, step: InitStep) -> bool:
        """检查前置步骤是否已完成。

        本次未执行（PENDING）但已全局就绪的依赖（如单独初始化缺失步骤时，
        依赖的 items 在本轮 _status 仍为 PENDING）也视为满足，避免误跳过。
        """
        for dep in step.depends_on:
            st = self._status.get(dep)
            if st in (StepStatus.COMPLETED, StepStatus.SKIPPED):
                continue
            try:
                if is_step_satisfied(dep):
                    continue
            except Exception:
                pass
            return False
        return True

    async def _run_step(self, key: str) -> tuple[bool, str]:
        """实际执行一个初始化步骤

        Returns:
            (success: bool, message: str)
        """
        # 映射 key → (module_path, entry_func_name, param_name)
        # param_name: 入口函数的 progress_cb 参数名（None=不支持）
        # 下载器统一在 services.importers（tools.downloaders / services.workers 为兼容 shim）
        entry_map = {
            "schema": ("services.schema_migrations", "ensure_all_schemas", False),
            "items": ("services.importers.getitems", "main", True),
            "price_baseline": ("services.importers.getprices", "fetch_baseline_only", True),
            "blueprints": ("services.importers.getblueprints", "run_blueprint_update", True),
            "implants": ("services.importers.getimplantdata", "main", True),
            "icons": ("services.importers.geticon", "main", True),
            "industry": ("services.importers.getindustry", "run_industry_update", True),
            "rigs": ("services.importers.getrigdata", "main", True),
            "sde_data": ("services.importers.sde_loader", "main", True),
        }

        mapping = entry_map.get(key)
        if not mapping:
            return False, f"未知步骤: {key}"

        mod_path, func_name, use_cb = mapping

        def _progress(pct: int, msg: str):
            self._emit_step_progress(key, pct, msg)

        try:
            import importlib
            import inspect

            mod = importlib.import_module(mod_path)
            func = getattr(mod, func_name, None)
            if func is None:
                return False, f"模块 {mod_path} 中未找到 {func_name}"

            # 提前判断入口函数是否接受 progress_cb 参数，
            # 避免用 except TypeError 兜底导致「真实 TypeError 被掩盖 + 函数执行两次」
            accepts_cb = "progress_cb" in inspect.signature(func).parameters

            if asyncio.iscoroutinefunction(func):
                if use_cb and accepts_cb:
                    await func(progress_cb=_progress)
                else:
                    await func()
            else:
                # 同步函数放在线程池执行
                loop = asyncio.get_event_loop()
                if use_cb and accepts_cb:
                    await loop.run_in_executor(None, lambda: func(progress_cb=_progress))
                else:
                    await loop.run_in_executor(None, func)

            return True, "完成"
        except Exception as e:
            log.exception("步骤 %s 执行失败", key)
            return False, str(e)

    def _inject_progress_callback(self, key: str):
        """设置进度回调环境变量（给 write_progress 使用）"""
        import os

        os.environ["_INIT_STEP_KEY"] = key
        # 未来: 可以设置一个 module-level callback 供 worker 调用

    # ── 信号/回调发射 ──

    def _emit_step_started(self, key: str, name: str):
        try:
            self.step_started.emit(key, name)
        except (RuntimeError, TypeError):
            pass
        self.on_step_started(key, name)

    def _emit_step_progress(self, key: str, percent: int, message: str):
        try:
            self.step_progress.emit(key, percent, message)
        except (RuntimeError, TypeError):
            pass
        self.on_step_progress(key, percent, message)

    def _emit_step_completed(self, key: str, success: bool, message: str):
        try:
            self.step_completed.emit(key, success, message)
        except (RuntimeError, TypeError):
            pass
        self.on_step_completed(key, success, message)

    def _emit_all_completed(self, success: bool, summary: str):
        try:
            self.all_completed.emit(success, summary)
        except (RuntimeError, TypeError):
            pass
        self.on_all_completed(success, summary)

    def _emit_network(self, ok: bool, message: str):
        try:
            self.network_status.emit(ok, message)
        except (RuntimeError, TypeError):
            pass
