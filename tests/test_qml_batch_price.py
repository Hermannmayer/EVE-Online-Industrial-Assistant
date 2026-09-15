"""QML 版「批量查价」对话框的业务契约（阶段 4b）。

只测行为：解析输入 → 起线程查价 → 行装配与配色 → 状态文案 → 导出 CSV → 关窗收尾。
「QML 加载无告警」那条通用护栏在 `tests/test_qml_dialogs.py` 里统一跑，这里不重复。

搜索与查价线程都换成同步替身（`_SyncWorker`），因此本文件不碰 DB、不碰真线程；
真线程的取消-等待路径由 `_SlowWorker` 覆盖。
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal

import ui_pyside6.theme as theme
import ui_qml.bridge.batch_price_bridge as bp
from ui_qml.bridge.batch_price_bridge import (
    BatchPriceQmlDialog,
    export_rows,
    merge_results,
    result_cells,
    status_line,
)

# ════════════════════════════════════════════════════════════════
#  替身：搜索与查价线程
# ════════════════════════════════════════════════════════════════


def _result(name: str, *, buy: float = 4.0, sell: float = 5.0, not_found: bool = False) -> dict:
    """一行查询结果（字段与原 `BatchPriceWorker._query_one` 的输出同构）。

    价差 / 均值的口径也照抄原实现：只有买卖价都在时才算是价差，否则为 0。
    """
    if not_found:
        return {
            "type_id": 0,
            "name": name,
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
    spread = sell - buy if (buy > 0 and sell > 0) else 0.0
    avg = (buy + sell) / 2 if spread else max(buy, sell)
    return {
        "type_id": 1001,
        "name": name,
        "not_found": False,
        "buy_str": f"{buy:,.2f}",
        "sell_str": f"{sell:,.2f}",
        "avg_str": f"{avg:,.2f}",
        "spread_str": f"{spread:+,.2f}" if spread else "—",
        "vol_str": "1,800",
        "buy_val": buy,
        "sell_val": sell,
        "avg_val": avg,
        "spread_val": spread,
        "vol_val": 1800,
    }


def _default_search(lines: list[str]) -> list[dict]:
    """搜索替身：查询词当物品名，唯独「查不到」这个词解析不出来（覆盖占位行分支）。"""
    out = []
    for q in lines:
        if q == "查不到":
            out.append({"type_id": 0, "name": q, "raw_query": q, "not_found": True})
        else:
            out.append({"type_id": 1001, "name": q, "raw_query": q})
    return out


class _SyncWorker(QObject):
    """查价线程的同步替身：`start()` 里直接把进度与结果推回来。"""

    finished_signal = Signal(list)
    progress_signal = Signal(int, int)
    error_signal = Signal(str)
    #: `QThread.finished`（桥的「摘出去保活」分支要连它）
    finished = Signal()

    def __init__(self, items: list[dict], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.items = list(items)
        self.cancelled = False
        self.interrupted = False
        self.waited = 0

    def start(self) -> None:
        for i, _item in enumerate(self.items):
            self.progress_signal.emit(i + 1, len(self.items))
        self.finished_signal.emit([_result(it["name"]) for it in self.items])

    def isRunning(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True

    def requestInterruption(self) -> None:
        self.interrupted = True

    def wait(self, ms: int = 0) -> bool:
        self.waited = ms
        return True


class _ProgressOnlyWorker(_SyncWorker):
    """只推进度、不出结果 —— 用来观察「查询进行中」的那几行文案与控件态。"""

    def start(self) -> None:
        for i, _item in enumerate(self.items):
            self.progress_signal.emit(i + 1, len(self.items))


class _SlowWorker(_SyncWorker):
    """一直「在跑」的替身 —— 用来验证关窗时确实做了收尾。"""

    def start(self) -> None: ...

    def isRunning(self) -> bool:
        return True


@pytest.fixture
def price_dialog(qapp, monkeypatch):
    """造 QML 版批量查价对话框；`worker` / `search` 可按需替换替身。"""

    def _make(*, worker: type = _SyncWorker, search: Any = _default_search) -> BatchPriceQmlDialog:
        monkeypatch.setattr(bp, "BatchPriceWorker", worker)
        monkeypatch.setattr(bp, "_search_items", search)
        return BatchPriceQmlDialog(None)

    return _make


# ════════════════════════════════════════════════════════════════
#  纯函数：行装配与文案（不需要 Qt）
# ════════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_status_line_counts_priced_and_missing_rows():
    assert status_line([]) == "查询完成: 0 个有价格"
    assert status_line([_result("甲"), _result("乙")]) == "查询完成: 2 个有价格"
    assert status_line([_result("甲"), _result("缺", not_found=True)]) == "查询完成: 1 个有价格, 1 个未找到"


@pytest.mark.fast
def test_merge_results_appends_placeholders_after_the_priced_rows():
    merged = merge_results([_result("甲")], [{"name": "查不到", "type_id": 0, "not_found": True}])
    assert [r["name"] for r in merged] == ["甲", "查不到"]
    # 占位行也要补齐成同构字段：否则导出与行装配会各写一份兜底默认值
    assert merged[1]["not_found"] is True
    assert (merged[1]["buy_str"], merged[1]["vol_str"]) == ("—", "—")
    assert (merged[1]["buy_val"], merged[1]["vol_val"]) == (0.0, 0)


@pytest.mark.fast
def test_result_cells_colour_buy_sell_and_spread():
    """有买价染绿、有卖价染红、价差按正负；均价与成交量原版就是默认前景色。"""
    cells = result_cells(_result("甲", buy=4.0, sell=5.0))["cells"]
    assert cells[1]["color"] == theme.GREEN
    assert cells[2]["color"] == theme.RED
    assert cells[4]["color"] == theme.GREEN
    assert (cells[3]["color"], cells[5]["color"]) == ("", "")

    negative = result_cells(_result("乙", buy=10.0, sell=8.0))["cells"]
    assert negative[4]["color"] == theme.RED, "负价差该染红"

    # 只有一边有价：原版对缺的那边与算不出的价差都用次要色
    half = result_cells(_result("丙", buy=0.0, sell=5.0))["cells"]
    assert half[1]["color"] == theme.TEXT_SECONDARY
    assert half[2]["color"] == theme.RED
    assert half[4]["color"] == theme.TEXT_SECONDARY


@pytest.mark.fast
def test_result_cells_dims_the_name_of_missing_rows():
    """未找到的行原先是整行底色；表组件不支持按行改底色，改压暗物品名。"""
    cells = result_cells(_result("查不到", not_found=True))["cells"]
    assert cells[0]["text"] == "查不到"
    assert cells[0]["color"] == theme.TEXT_SECONDARY
    assert [c["text"] for c in cells[1:]] == ["—"] * 5


@pytest.mark.fast
def test_export_rows_follow_the_table_columns():
    rows = export_rows([_result("甲"), _result("缺", not_found=True)])
    assert [len(r) for r in rows] == [6, 6]
    assert rows[0][0] == "甲"
    assert rows[1][0] == "缺" and rows[1][1] == "—"


# ════════════════════════════════════════════════════════════════
#  查询流程
# ════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_dialog_keeps_the_widgets_geometry(price_dialog):
    """构造签名与几何逐字对齐原 `BatchPriceDialog(parent)`。"""
    dialog = price_dialog()
    try:
        assert dialog.windowTitle() == "批量查价"
        assert (dialog.width(), dialog.height()) == (780, 560)
        assert (dialog.minimumWidth(), dialog.minimumHeight()) == (700, 500)
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_query_fills_the_table_and_the_status_line(price_dialog):
    dialog = price_dialog()
    try:
        bridge = dialog.bridge
        bridge.setInputText("三钛合金\n渡鸦级")
        bridge.query()

        assert bridge.busy is False
        assert bridge.progressVisible is False
        names = [row["cells"][0]["text"] for row in bridge.rows]
        assert names == ["三钛合金", "渡鸦级"]
        assert bridge.statusText == "查询完成: 2 个有价格"
        assert bridge.exportEnabled is True
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_query_skips_blank_lines(price_dialog):
    """空行不算物品 —— 原版也是先 strip 再过滤空串。"""
    dialog = price_dialog()
    try:
        bridge = dialog.bridge
        bridge.setInputText("  三钛合金  \n\n   \n渡鸦级")
        bridge.query()
        assert bridge.statusText == "查询完成: 2 个有价格"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_query_with_blank_input_only_hints(price_dialog):
    dialog = price_dialog()
    try:
        bridge = dialog.bridge
        bridge.setInputText("   \n\n  ")
        bridge.query()

        assert bridge.statusText == "请先输入物品名称或 ID"
        assert bridge.rows == []
        assert bridge.exportEnabled is False
        assert bridge._worker is None, "没解析出任何东西就不该起线程"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_query_without_any_match_keeps_export_disabled(price_dialog):
    dialog = price_dialog()
    try:
        bridge = dialog.bridge
        bridge.setInputText("查不到")
        bridge.query()

        assert bridge.statusText == "未找到任何匹配的物品"
        assert bridge.rows == []
        assert bridge.exportEnabled is False
        assert bridge.busy is False, "提前返回也要把查询态解除，否则查询按钮永久禁用"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_query_keeps_placeholder_rows_for_unknown_names(price_dialog):
    """解析不到的词不丢掉：排在有价行后面、整行破折号（原 `_on_query_done` 的合并）。"""
    dialog = price_dialog()
    try:
        bridge = dialog.bridge
        bridge.setInputText("三钛合金\n查不到")
        bridge.query()

        assert bridge.statusText == "查询完成: 1 个有价格, 1 个未找到"
        assert [row["cells"][0]["text"] for row in bridge.rows] == ["三钛合金", "查不到"]
        assert [c["text"] for c in bridge.rows[1]["cells"][1:]] == ["—"] * 5
        assert bridge.exportEnabled is True
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_progress_comes_from_the_worker_signal(price_dialog):
    """进度条与「正在查询... N/M」由线程的 `progress_signal` 驱动，期间按钮禁用。"""
    dialog = price_dialog(worker=_ProgressOnlyWorker)
    try:
        bridge = dialog.bridge
        bridge.setInputText("甲\n乙")
        bridge.query()

        assert bridge.busy is True
        assert bridge.progressVisible is True
        assert (bridge.progressCurrent, bridge.progressTotal) == (2, 2)
        assert bridge.statusText == "正在查询... 2/2"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_query_error_clears_the_busy_state(price_dialog):
    """线程报错（现行 worker 不会走到，通道仍在）要给文案并解除查询态。"""
    dialog = price_dialog()
    try:
        bridge = dialog.bridge
        bridge.setInputText("三钛合金")
        bridge.query()
        bridge._on_query_error("超时")

        assert bridge.statusText == "查询出错: 超时"
        assert bridge.busy is False
        assert bridge.progressVisible is False
    finally:
        dialog.deleteLater()


# ════════════════════════════════════════════════════════════════
#  导出 CSV
# ════════════════════════════════════════════════════════════════


def _ready_to_export(dialog) -> None:
    dialog.bridge.setInputText("三钛合金")
    dialog.bridge.query()


@pytest.mark.ui
def test_export_writes_the_same_columns_as_the_table(price_dialog, monkeypatch):
    written: dict[str, Any] = {}
    monkeypatch.setattr(bp, "get_save_filename", lambda *a: "C:/tmp/批量查价.csv")
    monkeypatch.setattr(
        bp,
        "export_to_csv",
        lambda headers, rows, path: written.update(headers=headers, rows=rows, path=path),
    )

    dialog = price_dialog()
    try:
        _ready_to_export(dialog)
        dialog.bridge.exportCsv()

        assert written["headers"] == ["物品名", "买价", "卖价", "均价", "价差", "成交量"]
        assert written["rows"][0][0] == "三钛合金"
        assert written["path"] == "C:/tmp/批量查价.csv"
        assert dialog.bridge.statusText == "已导出: C:/tmp/批量查价.csv"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_export_cancelled_in_the_file_dialog_writes_nothing(price_dialog, monkeypatch):
    written: list[Any] = []
    monkeypatch.setattr(bp, "get_save_filename", lambda *a: "")
    monkeypatch.setattr(bp, "export_to_csv", lambda *a: written.append(a))

    dialog = price_dialog()
    try:
        _ready_to_export(dialog)
        status_before = dialog.bridge.statusText
        dialog.bridge.exportCsv()

        assert written == []
        assert dialog.bridge.statusText == status_before, "取消保存不该改状态行"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_export_failure_lands_in_the_status_line(price_dialog, monkeypatch):
    def _boom(*_a: Any) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(bp, "get_save_filename", lambda *a: "C:/tmp/只读.csv")
    monkeypatch.setattr(bp, "export_to_csv", _boom)

    dialog = price_dialog()
    try:
        _ready_to_export(dialog)
        dialog.bridge.exportCsv()

        assert dialog.bridge.statusText == "导出失败: permission denied"
    finally:
        dialog.deleteLater()


@pytest.mark.ui
def test_export_without_results_never_asks_for_a_path(price_dialog, monkeypatch):
    asked: list[Any] = []
    monkeypatch.setattr(bp, "get_save_filename", lambda *a: asked.append(a) or "")

    dialog = price_dialog()
    try:
        dialog.bridge.exportCsv()
        assert asked == [], "没有结果就不该弹保存对话框"
    finally:
        dialog.deleteLater()


# ════════════════════════════════════════════════════════════════
#  关窗收尾
# ════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_closing_the_dialog_stops_the_running_worker(price_dialog):
    """关窗必须让查价线程收尾。

    不停的话，线程作为桥的子对象随对话框一起销毁 —— `QThread` 在运行中被析构时
    Qt 直接 `abort()`，整个进程静默死掉、一行日志都没有。
    """
    dialog = price_dialog(worker=_SlowWorker)
    try:
        bridge = dialog.bridge
        bridge.setInputText("三钛合金")
        bridge.query()
        worker = bridge._worker
        assert worker is not None and worker.isRunning(), "替身应当一直说自己在跑"

        dialog.done(0)  # 确定 / 取消 / Esc 都走这里

        assert worker.cancelled, "该让 worker 在下一件物品前退出循环"
        assert worker.interrupted
        assert worker.waited > 0, "关窗该等线程收尾，而不是撒手不管"
    finally:
        dialog.deleteLater()
