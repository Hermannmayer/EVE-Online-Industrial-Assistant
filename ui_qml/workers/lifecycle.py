"""后台线程收尾 —— 「QThread 在运行中被析构会让 Qt 直接 abort()」的统一兜底。

本仓真实崩过（退出码 127，`ui_snapshot.py --dialog contract_detail` 可复现）。
各桥原先各自内联实现这段收尾逻辑（5 处逐字重复的 `_DETACHED` + 3 个 `stop()`），
这里汇总成一份。

两种语义，按**等不等得到**选：

- `drop_worker(worker)` —— 等满 `wait_ms` 仍没结束才摘出去保活。用于 `run()` 会查
  中断标志、正常远小于超时的 worker（如评分线程）。
- `detach_worker(worker)` —— 超时短、`cancel()` 对阻塞式 ESI 请求无效时用，语义是
  「中断不了就别让它随对话框一起销毁」。

`_DETACHED` 必须是模块级强引用：线程被摘出对话树后若没人持有，`QThread` 的析构
就会在中止进程。线程自己 `finished` 后从集合里放掉。
"""

from __future__ import annotations

from typing import Any

__all__ = ["DEFAULT_WAIT_MS", "detach_worker", "drop_worker"]

#: 默认等待时长（ms）。会响应中断的 worker 正常远小于它。
DEFAULT_WAIT_MS = 2000

#: 阻塞式请求（ESI 拉单等）用的短超时 —— `requestInterruption()` 对它无效。
BLOCKING_WAIT_MS = 500

_DETACHED: set[Any] = set()


def _detach(worker: Any) -> None:
    """把 worker 摘出对话树并挂到模块级集合上保活。"""
    _DETACHED.add(worker)
    worker.setParent(None)
    worker.finished.connect(lambda: _DETACHED.discard(worker))


def drop_worker(worker: Any, *, cancel: bool = False, wait_ms: int = DEFAULT_WAIT_MS) -> None:
    """停掉后台线程；超时就摘出对话树保活。

    Args:
        worker: 目标线程；None 或已结束直接返回（调用方不必先判空）。
        cancel: 调不调 `worker.cancel()`（worker 自带这个方法时才传 True）。
        wait_ms: 等待上限，超过就摘出去保活。
    """
    if worker is None or not worker.isRunning():
        return
    if cancel:
        worker.cancel()
    worker.requestInterruption()
    if worker.wait(wait_ms):
        return
    _detach(worker)


def detach_worker(worker: Any) -> None:
    """中断不了就直接保活（阻塞式请求专用）。

    与 `drop_worker` 的区别：短超时（`BLOCKING_WAIT_MS`），且不假设 worker 有 `cancel()`。
    还会跳过非 QThread 的对象（`getattr` 守卫，见 `price_chart_bridge` 的历史写法）。
    """
    is_running = getattr(worker, "isRunning", None)
    if worker is None or not callable(is_running) or not is_running():
        return
    worker.requestInterruption()
    if worker.wait(BLOCKING_WAIT_MS):
        return
    _detach(worker)
