"""
初始化步骤 Worker — QThread 包装 InitService，供 InitWizard 使用

每个步骤由 InitService 统一调度，通过信号向 UI 报告进度。
单个步骤也可直接使用单步 Worker（ItemsWorker、PricesWorker 等）。
"""

from typing import ClassVar

from PySide6.QtCore import QThread, Signal

from services.init_service import InitService


class InitServiceWorker(QThread):
    """QThread wrapper — 在后台线程运行 InitService，支持全流程或单步执行"""

    step_started = Signal(str, str)           # step_key, step_name
    step_progress = Signal(str, int, str)     # step_key, percent, message
    step_completed = Signal(str, bool, str)   # step_key, success, message
    all_completed = Signal(bool, str)         # success, summary
    network_status = Signal(bool, str)        # ok, message

    # 重新发射信号（Qt 信号默认线程安全，跨线程 connect 自动排队）
    _SIGNAL_MAP: ClassVar[list[str]] = [
        "step_started", "step_progress", "step_completed",
        "all_completed", "network_status",
    ]

    def __init__(self, step_keys: list[str] | None = None, parent: QThread | None = None):
        super().__init__(parent)
        self._step_keys = step_keys
        self._service = InitService()

    def run(self):
        """在后台线程中执行初始化"""
        self._relay_signals()
        # start() 是同步函数（内部自行管理 asyncio 事件循环）
        self._service.start(self._step_keys)

    def _relay_signals(self):
        """将 InitService 的 Qt 信号转发到本 Worker 的信号"""
        for sig_name in self._SIGNAL_MAP:
            sig = getattr(self._service, sig_name, None)
            target = getattr(self, sig_name, None)
            if sig and target:
                try:
                    sig.connect(target)
                except TypeError:
                    pass  # Qt 环境外忽略

    # ── 代理方法（线程安全调用） ──

    def cancel(self):
        """取消初始化"""
        self._service.cancel()

    def retry(self, step_key: str):
        """重试单个步骤"""
        self._service.retry(step_key)

    def retry_all_failed(self):
        """重试所有失败步骤"""
        self._service.retry_all_failed()

    def skip(self, step_key: str) -> bool:
        """跳过非关键步骤"""
        return self._service.skip(step_key)

    def get_status(self) -> dict:
        """获取步骤状态快照"""
        return self._service.get_status()

    def get_errors(self) -> dict[str, str]:
        """获取错误信息"""
        return self._service.get_errors()

    async def check_network(self) -> bool:
        """检查网络连通性"""
        return await self._service.check_network()


# ── 单步 Worker（专用于单个步骤重试或单独执行） ──

class _SingleStepWorker(InitServiceWorker):
    """单个初始化步骤的专用 Worker 基类"""

    def __init__(self, parent=None):
        super().__init__(step_keys=[self.step_key], parent=parent)


class ItemsWorker(_SingleStepWorker):
    step_key = "items"


class PricesWorker(_SingleStepWorker):
    step_key = "prices"


class BlueprintsWorker(_SingleStepWorker):
    step_key = "blueprints"


class ImplantsWorker(_SingleStepWorker):
    step_key = "implants"


class IconsWorker(_SingleStepWorker):
    step_key = "icons"


class IndustryWorker(_SingleStepWorker):
    step_key = "industry"


class SdeDataWorker(_SingleStepWorker):
    step_key = "sde_data"

