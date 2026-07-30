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
    InitStep("items",      "物品数据",   needs_network=True,  critical=True),
    InitStep("prices",     "市场价格",   needs_network=True,  critical=True,  depends_on=["items"]),
    InitStep("blueprints", "蓝图数据",   needs_network=True,  critical=True,  depends_on=["items"]),
    InitStep("implants",   "植入体数据", needs_network=True,  critical=False),
    InitStep("industry",   "工业数据",   needs_network=True,  critical=True,  depends_on=["items"]),
    InitStep("icons",      "物品图标",   needs_network=True,  critical=False),
    InitStep("sde_data",   "SDE扩展数据",needs_network=False, critical=True,  depends_on=["items"]),
]

STEP_MAP: dict[str, InitStep] = {s.key: s for s in STEPS}


# ── 回调类型（CLI 模式） ──

StepStartedCb = Callable[[str, str], None]       # step_key, step_name
StepProgressCb = Callable[[str, int, str], None]  # step_key, percent, message
StepCompletedCb = Callable[[str, bool, str], None]  # step_key, success, message
AllCompletedCb = Callable[[bool, str], None]      # all_done, summary


def _noop(*args, **kwargs):
    pass


# ── 状态查询 ──


def is_step_satisfied(step_key: str) -> bool:
    """检查某步骤是否已就绪（数据是否存在）"""
    from services.init_check import check_all

    status = check_all()
    return status.get(step_key, False)


def get_missing_steps() -> list[InitStep]:
    """返回所有未就绪的步骤"""
    return [s for s in STEPS if not is_step_satisfied(s.key)]


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
    step_started = Signal(str, str)             # step_key, step_name
    step_progress = Signal(str, int, str)       # step_key, percent_0_100, message
    step_completed = Signal(str, bool, str)     # step_key, success, message
    all_completed = Signal(bool, str)           # all_done, summary
    network_status = Signal(bool, str)          # ok, message

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        # 每步状态: key → StepStatus
        self._status: dict[str, StepStatus] = {s.key: StepStatus.PENDING for s in STEPS}
        # 每步失败消息
        self._errors: dict[str, str] = {}
        # 当前正在执行的步骤
        self._current_key: str | None = None
        # 是否已取消
        self._cancelled = False

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
        self._cancelled = False
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
        """取消当前执行"""
        self._cancelled = True
        if self._current_key:
            self._status[self._current_key] = StepStatus.CANCELLED

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
        self._current_key = None
        self._cancelled = False

    # ── 网络检查 ──

    async def check_network(self) -> bool:
        """检查 ESI 连通性"""
        import aiohttp

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("https://esi.evetech.net/status/") as resp:
                    ok = resp.status == 200
                    msg = "ESI 连接正常" if ok else f"ESI 返回 {resp.status}"
                    self._emit_network(ok, msg)
                    return ok
        except Exception as e:
            msg = f"网络不可用: {e}"
            self._emit_network(False, msg)
            return False

    # ── 内部执行逻辑 ──

    async def _run_sequence(self, keys: list[str]):
        """顺序执行步骤列表"""
        success_count = 0
        fail_count = 0

        for key in keys:
            if self._cancelled:
                break

            step = STEP_MAP.get(key)
            if not step:
                continue

            # 如果前置步骤未完成，跳过
            if not self._deps_satisfied(step):
                self._status[key] = StepStatus.SKIPPED
                self._emit_step_completed(key, True, "前置步骤未就绪，跳过")
                continue

            # 如果已经是 COMPLETED/SKIPPED，跳过
            if self._status.get(key) in (StepStatus.COMPLETED, StepStatus.SKIPPED):
                continue

            # 网络检查
            if step.needs_network:
                net_ok = await self.check_network()
                if not net_ok:
                    self._status[key] = StepStatus.FAILED
                    self._errors[key] = "网络不可用"
                    self._emit_step_completed(key, False, "网络不可用")
                    fail_count += 1
                    continue

            # 执行
            self._current_key = key
            self._status[key] = StepStatus.RUNNING
            self._emit_step_started(key, step.name)
            try:
                success, msg = await self._run_step(key)
                self._status[key] = StepStatus.COMPLETED if success else StepStatus.FAILED
                if not success:
                    self._errors[key] = msg
                    fail_count += 1
                else:
                    success_count += 1
                self._emit_step_completed(key, success, msg)
            except Exception as e:
                self._status[key] = StepStatus.FAILED
                msg = str(e)
                self._errors[key] = msg
                fail_count += 1
                self._emit_step_completed(key, False, msg)
            finally:
                self._current_key = None

        all_done = fail_count == 0
        summary = f"完成 {success_count}/{success_count + fail_count}"
        if all_done:
            summary = "全部初始化完成"
        self._emit_all_completed(all_done, summary)

    def _deps_satisfied(self, step: InitStep) -> bool:
        """检查前置步骤是否已完成"""
        return all(
            self._status.get(dep) in (StepStatus.COMPLETED, StepStatus.SKIPPED)
            for dep in step.depends_on
        )

    async def _run_step(self, key: str) -> tuple[bool, str]:
        """实际执行一个初始化步骤

        Returns:
            (success: bool, message: str)
        """
        # 映射 key → (module_path, entry_func_name, param_name)
        # param_name: 入口函数的 progress_cb 参数名（None=不支持）
        entry_map = {
            "items":      ("tools.downloaders.getitems", "main", True),
            "prices":     ("services.workers.getprices", "main", True),
            "blueprints": ("tools.downloaders.getblueprints", "run_blueprint_update", True),
            "implants":   ("tools.downloaders.getimplantdata", "main", True),
            "icons":      ("tools.downloaders.geticon", "main", True),
            "industry":   ("services.workers.getindustry", "run_industry_update", True),
            "sde_data":   ("tools.downloaders.sde_loader", "main", True),
        }

        mapping = entry_map.get(key)
        if not mapping:
            return False, f"未知步骤: {key}"

        mod_path, func_name, use_cb = mapping

        def _progress(pct: int, msg: str):
            self._emit_step_progress(key, pct, msg)

        try:
            import importlib

            mod = importlib.import_module(mod_path)
            func = getattr(mod, func_name, None)
            if func is None:
                return False, f"模块 {mod_path} 中未找到 {func_name}"

            if asyncio.iscoroutinefunction(func):
                if use_cb:
                    try:
                        await func(progress_cb=_progress)
                    except TypeError:
                        # 如果该函数不支持 progress_cb，不带参数重新调用
                        await func()
                else:
                    await func()
            else:
                # 同步函数放在线程池执行
                loop = asyncio.get_event_loop()
                if use_cb:
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
