"""批量查价对话框的桥（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/batch_price_dialog.py`：粘贴一批物品名 / ID（每行一个）
→ 解析成 type_id → 逐条查市场最新价 → 预览（买价 / 卖价 / 均价 / 价差 / 成交量）→ 导出 CSV。

**取数与格式化不重写**：直接复用原模块的 `BatchPriceWorker`（`_query_one` 里的千分位
格式化与原版逐字一致）与 `_search_items`（纯数字按 type_id 查、其余按名称模糊匹配取第一条）。
迁移期只保留这一份业务实现，桥里只做「行装配 + 状态文案 + 线程收尾」。

两处刻意与 Widgets 版不同：
- 未找到的行原先整行铺 `BG_HOVER` 底色。`FSummaryTable` 不支持按行改底色（它按奇偶
  交替配色），这里改成把物品名压成次要色 —— 传达同一件事，且不用给通用表开特例。
- 原 `_on_query_done` 会把「未找到」的占位行**再查一遍库**才拼出来。这里复用 `query()`
  时已经拿到的占位行：少一次主线程 DB 往返，可观察结果一致（同名重复查询词的占位也照样保留两条）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from ui_pyside6.views.batch_price_dialog import BatchPriceWorker, _search_items
from ui_pyside6.views.export_helper import export_to_csv, get_save_filename
from ui_qml.bridge.summary_dialog import cell
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = [
    "BatchPriceBridge",
    "BatchPriceQmlDialog",
    "export_rows",
    "merge_results",
    "result_cells",
    "status_line",
]

_QML_FILE = "dialogs/BatchPriceDialog.qml"

#: 列与 Widgets 版同口径；末列吃满剩余空间（对应原 `setStretchLastSection(True)`）
_COLUMNS = [
    {"title": "物品名", "width": 160},
    {"title": "买价", "width": 130},
    {"title": "卖价", "width": 130},
    {"title": "均价", "width": 110},
    {"title": "价差", "width": 110},
    {"title": "成交量", "width": 0},
]

_EXPORT_HEADERS = ["物品名", "买价", "卖价", "均价", "价差", "成交量"]

_HINT_EMPTY = "请先输入物品名称或 ID"
_HINT_IDLE = "输入物品名称或 ID 后点击查询"

#: 无价格 / 未找到的单元格用次要色（原 `ForegroundRole` 用的就是 `theme.TEXT_SECONDARY`）
_DIM = "TEXT_SECONDARY"

#: 关窗时还没跑完、被摘出对话树的线程（见 `BatchPriceBridge.stop`）
_DETACHED: set[Any] = set()


# ══════════════════════════════════════════════════════════════
#  纯函数：行装配与文案（便于单测，不碰 Qt）
# ══════════════════════════════════════════════════════════════


def merge_results(results: list[dict], not_found: list[dict]) -> list[dict]:
    """查询结果 + 未解析到的查询词占位 → 最终结果表。

    占位行一律排最后，且字段补齐成与正常行同构（原实现在 `_on_query_done` 里手工拼的
    就是这几个键）—— 少了它们 `result_cells` / 导出会各写一份 `.get(..., "—")` 兜底。
    """
    merged = list(results)
    for nf in not_found:
        merged.append(
            {
                "name": nf["name"],
                "type_id": 0,
                "not_found": True,
                "buy_str": "—",
                "sell_str": "—",
                "avg_str": "—",
                "spread_str": "—",
                "vol_str": "—",
                "buy_val": 0.0,
                "sell_val": 0.0,
                "avg_val": 0.0,
                "spread_val": 0.0,
                "vol_val": 0,
            }
        )
    return merged


def status_line(results: list[dict]) -> str:
    """结果行 → 状态文案（与原 `_on_query_done` 末尾拼的那句逐字一致）。"""
    found = sum(1 for r in results if not r.get("not_found"))
    text = f"查询完成: {found} 个有价格"
    missing = len(results) - found
    if missing:
        text += f", {missing} 个未找到"
    return text


def result_cells(row: dict) -> dict:
    """一条结果 → `FSummaryTable` 的单元格行。

    配色逐条对齐原 `BatchPriceModel` 的 `ForegroundRole`：有买价染绿、有卖价染红、
    价差按正负染色；均价 / 成交量原版就是默认前景色，这里保持空 token。
    """
    buy = float(row.get("buy_val") or 0.0)
    sell = float(row.get("sell_val") or 0.0)
    spread = float(row.get("spread_val") or 0.0)
    # 未找到的行原先是整行底色（`BackgroundRole`）；表组件不按行改底色，改压暗物品名
    name_token = _DIM if row.get("not_found") else ""
    spread_token = "GREEN" if spread > 0 else ("RED" if spread < 0 else _DIM)
    return {
        "cells": [
            cell(row.get("name", "—"), name_token),
            cell(row.get("buy_str", "—"), "GREEN" if buy > 0 else _DIM),
            cell(row.get("sell_str", "—"), "RED" if sell > 0 else _DIM),
            cell(row.get("avg_str", "—")),
            cell(row.get("spread_str", "—"), spread_token),
            cell(row.get("vol_str", "—")),
        ]
    }


def export_rows(results: list[dict]) -> list[list[str]]:
    """导出用的二维表（取值口径与原 `_on_export_csv` 逐字一致）。"""
    return [
        [
            r.get("name", "—"),
            r.get("buy_str", "—"),
            r.get("sell_str", "—"),
            r.get("avg_str", "—"),
            r.get("spread_str", "—"),
            r.get("vol_str", "—"),
        ]
        for r in results
    ]


# ══════════════════════════════════════════════════════════════
#  桥
# ══════════════════════════════════════════════════════════════


class BatchPriceBridge(DialogBridge):
    """批量查价的 QML 后端。"""

    stateChanged = Signal()
    #: 输入框专用。**不并进 `stateChanged`**：那个信号还挂着表格的 `rows`，
    #: 每敲一个字都发一次会让 ListView 按同内容重建整套 delegate（结果多时肉眼可见地卡）。
    inputChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.set_title("批量查价")
        self._input_text = ""
        self._status = _HINT_IDLE
        self._results: list[dict] = []
        self._rows: list[dict] = []
        self._busy = False
        self._progress_visible = False
        self._progress_current = 0
        self._progress_total = 0
        #: 未解析到的查询词占位（`query()` 时记下，`_on_query_done` 复用，不再二次查库）
        self._placeholders: list[dict] = []
        self._worker: BatchPriceWorker | None = None

    # ── 给 QML 读 ────────────────────────────────────────────

    @Property(list, constant=True)
    def columns(self) -> list[dict]:
        return [dict(c) for c in _COLUMNS]

    @Property(list, notify=stateChanged)
    def rows(self) -> list[dict]:
        return list(self._rows)

    @Property(str, notify=inputChanged)
    def inputText(self) -> str:
        return self._input_text

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status

    @Property(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(bool, notify=stateChanged)
    def exportEnabled(self) -> bool:
        return bool(self._results)

    @Property(bool, notify=stateChanged)
    def progressVisible(self) -> bool:
        return self._progress_visible

    @Property(int, notify=stateChanged)
    def progressCurrent(self) -> int:
        return self._progress_current

    @Property(int, notify=stateChanged)
    def progressTotal(self) -> int:
        return self._progress_total

    # ── 给 QML 调 ────────────────────────────────────────────

    @Slot(str)
    def setInputText(self, text: str) -> None:
        if text == self._input_text:
            return
        self._input_text = text
        self.inputChanged.emit()

    @Slot()
    def query(self) -> None:
        """解析输入 → 起线程逐条取价。流程与状态文案逐条对齐原 `_on_query`。"""
        lines = [line.strip() for line in self._input_text.split("\n") if line.strip()]
        if not lines:
            self._set_status(_HINT_EMPTY)
            return

        self._busy = True
        self._results = []
        self._rows = []
        self._progress_visible = False
        self._set_status(f"正在解析 {len(lines)} 个物品...")

        items = _search_items(lines)
        valid = [it for it in items if not it.get("not_found")]
        self._placeholders = [it for it in items if it.get("not_found")]
        if not valid:
            self._busy = False
            self._set_status("未找到任何匹配的物品")
            return

        self._progress_current = 0
        self._progress_total = len(valid)
        self._progress_visible = True
        self._set_status(f"正在查询 {len(valid)} 个物品的价格...")

        worker = BatchPriceWorker(valid, self)
        self._worker = worker
        worker.finished_signal.connect(self._on_query_done)
        worker.progress_signal.connect(self._on_progress)
        worker.error_signal.connect(self._on_query_error)
        worker.start()

    @Slot()
    def exportCsv(self) -> None:
        """导出当前结果。父窗口走 `host_widget()`（见 `DialogBridge.host_widget` 的说明）。"""
        if not self._results:
            return
        path = get_save_filename(self.host_widget(), "批量查价.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            export_to_csv(_EXPORT_HEADERS, export_rows(self._results), path)
        except Exception as e:  # 磁盘满 / 权限 / 占用 —— 只把原因写进状态行，不打断对话框
            self._set_status(f"导出失败: {e}")
            return
        self._set_status(f"已导出: {path}")

    # ── 线程回调 ─────────────────────────────────────────────

    def _on_progress(self, current: int, total: int) -> None:
        self._progress_current = current
        self._progress_total = total
        self._set_status(f"正在查询... {current}/{total}")

    def _on_query_done(self, results: list[dict]) -> None:
        self._progress_visible = False
        self._busy = False
        merged = merge_results(results, self._placeholders)
        self._results = merged
        self._rows = [result_cells(r) for r in merged]
        self._set_status(status_line(merged))

    def _on_query_error(self, error: str) -> None:
        # 现行 worker 只把单条失败折进结果行，不会走到这里；保留通道以免将来 worker
        # 改成「整批失败」时对话框卡在查询态
        self._progress_visible = False
        self._busy = False
        self._set_status(f"查询出错: {error}")

    def _set_status(self, text: str) -> None:
        self._status = text
        self.stateChanged.emit()

    # ── 关窗收尾 ─────────────────────────────────────────────

    def stop(self) -> None:
        """关窗收尾：`QThread` 在运行中被析构时 Qt 直接 `abort()`。

        先 `cancel()`（worker 会在下一条物品前退出循环）再等 2 秒；真没等到就把它从
        桥的子对象里摘出来，挂到模块级集合上等它自己结束（同 `npc_seller_bridge` 的
        「强引用保活」做法）—— 父对象已随对话框销毁，留着反而是崩溃源。
        """
        worker = self._worker
        if worker is None or not worker.isRunning():
            return
        worker.cancel()
        worker.requestInterruption()
        if worker.wait(2000):
            return
        _DETACHED.add(worker)
        worker.setParent(None)
        worker.finished.connect(lambda: _DETACHED.discard(worker))


class BatchPriceQmlDialog(QmlDialog):
    """QML 版「批量查价」。`BatchPriceDialog(parent)` 的调用方原样可用。"""

    def __init__(self, parent: Any = None) -> None:
        bridge = BatchPriceBridge()
        # 原类 `resize(780, 560)` + `setMinimumSize(700, 500)`：默认尺寸一致，
        # 最小尺寸比默认小（允许缩），故 `size` 之后再压一次最小值
        super().__init__(_QML_FILE, bridge, parent=parent, size=(780, 560))
        self.setMinimumSize(700, 500)
