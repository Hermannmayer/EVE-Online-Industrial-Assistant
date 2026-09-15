"""价格走势图（阶段 4b）的业务契约测试。

重点是**几何**：轴范围（nice numbers）、刻度值、数据点 → 0..1 画布坐标的映射。
这套算法是原版 QChart 自动范围 + `QValueAxis` 的等价物，算错了图就是错的；
放进 Python 纯函数才测得动（留在 QML 的 Canvas JS 里只能靠截图肉眼看）。

另加桥的两条：结果整形（状态文案 + 画布模型）与「过期的后台结果要丢掉」。

「QML 是否加载成功 / 有无告警」那两条由 `tests/test_qml_dialogs.py` 统一管。
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from PySide6.QtCore import QEventLoop, QThread, QTimer, Signal

import ui_qml.bridge.price_chart_bridge as pcb
from ui_qml.bridge.price_chart_bridge import (
    PriceChartBridge,
    axis_values,
    map_values,
    nice_range,
    pick_indices,
    plot_model,
)

pytestmark = pytest.mark.ui

_NAME = "三钛合金"


def _spin(ms: int = 200) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _data(days: int = 5, base: float = 100.0, volume: int = 1000) -> list[dict]:
    """ESI /markets/{region}/history/ 的行形状。"""
    return [
        {
            "date": f"2026-01-{i + 1:02d}",
            "average": base + i * 3,
            "highest": base + i * 3 + 5,
            "lowest": base + i * 3 - 5,
            "volume": volume * (i + 1),
            "order_count": 10,
        }
        for i in range(days)
    ]


# ════════════════════════════════════════════════════════════
#  轴范围（nice numbers）
# ════════════════════════════════════════════════════════════


class TestNiceRange:
    def test_keeps_round_bounds_untouched(self):
        assert nice_range(0.0, 100.0, 5) == (0.0, 100.0, 20.0)

    def test_rounds_outward_to_whole_steps(self):
        lo, hi, step = nice_range(3.0, 97.0, 5)
        assert (lo, hi, step) == (0.0, 100.0, 20.0)

    def test_step_is_never_smaller_than_raw(self):
        for lo, hi in ((1.0, 9.0), (0.02, 0.17), (500.0, 64000.0)):
            _, _, step = nice_range(lo, hi, 5)
            assert step * 5 >= hi - lo

    def test_flat_series_gets_a_window(self):
        """每天都一个价：轴不能退化成一个点（下面还要拿它当分母）。"""
        lo, hi, step = nice_range(5.0, 5.0)
        assert lo < 5.0 < hi
        assert step > 0

    def test_all_zero_data(self):
        lo, hi, _ = nice_range(0.0, 0.0)
        assert lo < 0.0 < hi

    def test_swapped_bounds_are_normalized(self):
        assert nice_range(97.0, 3.0, 5) == nice_range(3.0, 97.0, 5)

    def test_non_finite_falls_back_to_unit_axis(self):
        assert nice_range(math.nan, 5.0) == (0.0, 1.0, 1.0)
        assert nice_range(0.0, math.inf) == (0.0, 1.0, 1.0)

    def test_decimal_step_has_no_float_tail(self):
        lo, hi, step = nice_range(1.5, 1.9, 4)
        assert (lo, hi, step) == (1.5, 1.9, 0.1)


class TestAxisValues:
    def test_includes_both_ends(self):
        assert axis_values(0.0, 100.0, 20.0) == [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]

    def test_stops_at_last_step_inside_the_range(self):
        # 上界不整除步长时，最后一个刻度落在上界之内（不越过）
        assert axis_values(0.0, 95.0, 20.0) == [0.0, 20.0, 40.0, 60.0, 80.0]

    def test_rejects_degenerate_step(self):
        assert axis_values(0.0, 100.0, 0.0) == []
        assert axis_values(100.0, 0.0, 20.0) == []


class TestMapValues:
    def test_normalizes_to_unit_interval(self):
        assert map_values([0.0, 50.0, 100.0], 0.0, 100.0) == [0.0, 0.5, 1.0]

    def test_clamps_out_of_range(self):
        assert map_values([-10.0, 110.0], 0.0, 100.0) == [0.0, 1.0]

    def test_degenerate_span_maps_to_bottom(self):
        assert map_values([1.0, 2.0], 5.0, 5.0) == [0.0, 0.0]


class TestPickIndices:
    def test_all_indices_when_few_points(self):
        assert pick_indices(3, 6) == [0, 1, 2]

    def test_samples_evenly_and_keeps_both_ends(self):
        assert pick_indices(12, 6) == [0, 2, 4, 7, 9, 11]

    def test_no_points(self):
        assert pick_indices(0, 6) == []


# ════════════════════════════════════════════════════════════
#  画布模型
# ════════════════════════════════════════════════════════════


class TestPlotModel:
    def test_empty_data(self):
        model = plot_model([])
        assert model["isEmpty"] is True
        assert model["count"] == 0
        assert model["series"] == []

    def test_points_span_the_full_width(self):
        model = plot_model(_data(5))
        xs = [round(p["x"], 4) for p in model["series"][0]["points"]]
        assert xs == [0.0, 0.25, 0.5, 0.75, 1.0]

    def test_y_is_within_the_axis(self):
        model = plot_model(_data(30))
        for series in model["series"]:
            assert all(0.0 <= p["y"] <= 1.0 for p in series["points"])

    def test_higher_price_is_higher_on_the_canvas(self):
        """y 越大越靠上：价格最高那天的 y 必须是最大值。"""
        model = plot_model(_data(5))
        ys = [p["y"] for p in model["series"][0]["points"]]
        assert ys == sorted(ys)
        assert ys[-1] == pytest.approx(1.0, abs=0.2)

    def test_flat_prices_are_not_on_the_axis_floor(self):
        """全平序列的点该落在中段，而不是贴底（否则图看着像跌没了）。"""
        model = plot_model([dict(d, average=42.0) for d in _data(4)])
        ys = [p["y"] for p in model["series"][0]["points"]]
        assert all(0.05 < y < 0.95 for y in ys)

    def test_volume_has_its_own_axis(self):
        """双 Y 轴：成交量的量级（百万）和价格（几 ISK）差太远，不能共用一个范围。"""
        model = plot_model(_data(6, base=1.0, volume=2_000_000))
        assert model["volumeTicks"] != model["priceTicks"]
        assert len(model["volumeTicks"]) >= 2
        assert len(model["priceTicks"]) >= 2

    def test_axis_ticks_are_never_negative_for_real_data(self):
        """价格与成交量没有负数：轴不能伸到负半轴（否则小幅波动看着像跌穿）。"""
        model = plot_model(_data(6))
        ticks = model["priceTicks"] + model["volumeTicks"]
        assert all(not t["label"].startswith("-") for t in ticks)

    def test_all_zero_axis_still_starts_at_zero(self):
        # 成交量整天为 0（冷门物品）时，nice_range 的居中窗口会给出负下界 —— 必须夹回 0
        rows = [dict(d, volume=0) for d in _data(4)]
        model = plot_model(rows)
        assert model["volumeTicks"][0]["label"] == "0"

    def test_x_ticks_carry_the_dates(self):
        model = plot_model(_data(12))
        labels = [t["label"] for t in model["xTicks"]]
        assert labels[0] == "2026-01-01"
        assert labels[-1] == "2026-01-12"
        assert len(labels) <= 6

    def test_single_day_is_centered(self):
        model = plot_model(_data(1))
        assert model["series"][0]["points"] == [{"x": 0.5, "y": pytest.approx(0.5, abs=0.5)}]

    def test_series_labels_match_the_widgets_legend(self):
        model = plot_model(_data(3))
        assert [s["label"] for s in model["series"]] == ["日均价 (ISK)", "成交量"]

    def test_bad_rows_are_skipped(self):
        rows = [*_data(2), {"date": "2026-01-03", "average": "abc", "volume": 1}, {}]
        assert plot_model(rows)["count"] == 2


# ════════════════════════════════════════════════════════════
#  桥
# ════════════════════════════════════════════════════════════


class TestPriceChartBridge:
    def test_starts_in_loading_state(self, qapp):
        bridge = PriceChartBridge(34, _NAME)
        assert bridge.statusText == "加载中..."
        assert bridge.plot["isEmpty"] is True
        assert bridge.title_text() == "价格走势 — 三钛合金"

    def test_loaded_data_fills_plot_and_status(self, qapp):
        bridge = PriceChartBridge(34, _NAME)
        bridge._on_data_loaded(34, _data(12))
        assert bridge.statusText == "已加载 12 天数据"
        assert bridge.day_count() == 12
        assert bridge.plot["isEmpty"] is False
        assert bridge.headerText == "三钛合金 (Type ID: 34)"

    def test_stale_result_is_dropped(self, qapp):
        """切了物品之后回来的旧结果不能覆盖新图（原版也按 type_id 过滤）。"""
        bridge = PriceChartBridge(34, _NAME)
        bridge._on_data_loaded(35, _data(3))
        assert bridge.day_count() == 0
        assert bridge.statusText == "加载中..."

    def test_error_is_shown_in_the_status_line(self, qapp):
        bridge = PriceChartBridge(34, _NAME)
        bridge._on_error(34, "无历史数据")
        assert bridge.statusText == "错误: 无历史数据"

    def test_worker_result_reaches_the_bridge(self, qapp, monkeypatch):
        """取价线程仍然复用原 `PriceHistoryWorker`，这里换成不发网络的替身。"""

        class _StubWorker(QThread):
            finished_signal = Signal(int, list)
            error_signal = Signal(int, str)

            def __init__(self, type_id: int, parent: Any = None) -> None:
                super().__init__(parent)
                self._tid = int(type_id)

            def run(self) -> None:
                self.finished_signal.emit(self._tid, _data(4))

        monkeypatch.setattr(pcb, "_history_worker", lambda type_id, parent: _StubWorker(type_id, parent))
        bridge = PriceChartBridge(34, _NAME)
        bridge.reload()
        _spin(300)
        assert bridge.day_count() == 4
        bridge.stop()  # 已经跑完的线程不该被摘出去，也不该抛

    def test_reload_is_not_restarted_while_running(self, qapp, monkeypatch):
        class _StubWorker(QThread):
            finished_signal = Signal(int, list)
            error_signal = Signal(int, str)

            def __init__(self, type_id: int, parent: Any = None) -> None:
                super().__init__(parent)
                self._tid = int(type_id)

            def run(self) -> None:
                QThread.msleep(150)
                self.finished_signal.emit(self._tid, _data(2))

        created: list = []

        def _make(type_id: int, parent: Any) -> _StubWorker:
            worker = _StubWorker(type_id, parent)
            created.append(worker)
            return worker

        monkeypatch.setattr(pcb, "_history_worker", _make)
        bridge = PriceChartBridge(34, _NAME)
        bridge.reload()
        bridge.reload()  # 第二次必须被挡住，否则两个线程同时回写同一份 plot
        assert len(created) == 1
        bridge.stop()
        _spin(300)
