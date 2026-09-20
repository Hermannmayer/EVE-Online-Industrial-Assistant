"""合同市场 — 后台 Worker 线程。

**两类写库任务互斥**：`ContractFetchWorker`（拉列表）与 `ContractFillWorker`（补物品）
都写 market.db，SQLite 是单写者 —— 桥在同一时刻只允许跑一个，见
`ui_qml/bridge/contract_bridge.py` 的 `_busy_worker`。

**只给真正慢的事开线程**：查库（最重一档实测 49 ms）走同步，不再开线程 ——
异步结果回来时视图可能正在销毁，实测会让 ui 档后续用例 `access violation`。
留在本模块的两件事都要打 ESI：拉列表（几十秒）与补物品（几万次请求、可中断）。

**线程生命周期与桥解耦**：桥随页面销毁，线程若还在跑会被连带析构，Qt 直接 abort。
所以 worker 一律 `parent=None`，由本模块的 `spawn()` 持强引用、跑完自摘；
对已销毁桥的信号投递由 Qt 自动断连兜底。
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.logger import log

#: 在跑的 worker 的强引用集合 —— QThread **不能在运行中被析构**。
#: 挂到桥上（`parent=bridge`）就会随宿主一起走，宿主先销毁即崩；挂在这里则跑到自然结束。
_LIVE_WORKERS: set[QThread] = set()


def spawn(worker: QThread) -> QThread:
    """启动 worker 并由本模块持有，直到它跑完。"""
    _LIVE_WORKERS.add(worker)
    worker.finished.connect(lambda: _LIVE_WORKERS.discard(worker))
    worker.start()
    return worker


class ContractFetchWorker(QThread):
    """拉取合同**列表**（不含物品）—— 每个星域拉完立刻落库。"""

    finished_signal = Signal(bool, str)

    def __init__(self, region_ids: list[int], parent=None):
        super().__init__(parent)
        self._region_ids = region_ids

    def run(self) -> None:
        try:
            from services.importers.getcontracts import run_contract_update

            counts = run_contract_update(self._region_ids)
            total = sum(counts.values())
            self.finished_signal.emit(True, f"已拉取 {total:,} 条合同")
        except Exception as ex:
            log.exception("合同列表拉取失败")
            self.finished_signal.emit(False, str(ex))


class ContractFillWorker(QThread):
    """后台补齐物品详情 —— 分批拉、**分批回写**，可随时中断。

    物品是「价差」列的前提，而一个星域有 3.4 万份合同、一份一个请求，
    所以它必须能停、且进度可见。
    """

    progress = Signal(int, int)  # 已完成, 总数
    finished_signal = Signal(int, str)  # 写入的物品行数, 文案

    def __init__(self, region_id: int, contract_type: str, parent=None):
        super().__init__(parent)
        self._region_id = region_id
        self._contract_type = contract_type
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            from services.importers.getcontracts import list_contracts_needing_items, run_items_fill

            ids = list_contracts_needing_items(self._region_id, self._contract_type, limit=50_000)
            if not ids:
                self.finished_signal.emit(0, "没有待补齐的合同")
                return
            self.progress.emit(0, len(ids))
            written = run_items_fill(ids, progress_cb=self.progress.emit, should_stop=lambda: self._stop)
            msg = "已停止" if self._stop else "补齐完成"
            self.finished_signal.emit(written, msg)
        except Exception as ex:
            log.exception("物品补齐失败")
            self.finished_signal.emit(0, f"补齐失败: {ex}")


class ContractItemsLoadWorker(QThread):
    """加载某份合同的物品明细（含市价，供详情面板显示）。"""

    finished_signal = Signal(list)

    def __init__(self, contract_id: int, region_id: int = 0, price_type: str = "sell", parent=None):
        super().__init__(parent)
        self._contract_id = contract_id
        self._region_id = region_id
        self._price_type = price_type

    def run(self) -> None:
        try:
            from services.contract_service import load_contract_items, price_map_for

            items = load_contract_items(self._contract_id)
            prices = price_map_for((it["type_id"] for it in items), self._region_id, self._price_type)
            for it in items:
                it["unit_price"] = prices.get(int(it["type_id"] or 0))
            self.finished_signal.emit(items)
        except Exception:
            log.exception("合同物品加载失败, contract_id=%s", self._contract_id)
            self.finished_signal.emit([])
