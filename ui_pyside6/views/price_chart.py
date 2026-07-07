"""
价格走势图弹窗 — PySide6 QChart 实现
"""

import asyncio

from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QDateTime, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

import ui_pyside6.theme as theme
from services.price_history import fetch_history, get_cached_history, save_cache


class PriceHistoryWorker(QThread):
    """后台线程：获取价格历史数据"""

    finished_signal = Signal(int, list)  # type_id, data
    error_signal = Signal(int, str)  # type_id, error

    def __init__(self, type_id: int, region_id: int = 10000002, parent=None):
        super().__init__(parent)
        self._type_id = type_id
        self._region_id = region_id

    def run(self):
        try:
            # Try cache first
            data = get_cached_history(self._type_id, self._region_id)
            if data is not None:
                self.finished_signal.emit(self._type_id, data)
                return

            # Fetch from ESI
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                data = loop.run_until_complete(fetch_history(self._type_id, self._region_id))
            finally:
                loop.close()

            if data is None:
                self.error_signal.emit(self._type_id, "无历史数据")
                return

            save_cache(self._type_id, self._region_id, data)
            self.finished_signal.emit(self._type_id, data)
        except Exception as e:
            self.error_signal.emit(self._type_id, str(e))


class PriceChartDialog(QDialog):
    """价格走势图弹窗"""

    def __init__(self, type_id: int, name: str, parent=None):
        super().__init__(parent)
        self._type_id = type_id
        self._name = name
        self._data: list[dict] = []

        self.setWindowTitle(f"价格走势 — {name}")
        self.setMinimumSize(800, 500)
        self.resize(900, 550)

        self._build_ui()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

        self._worker = PriceHistoryWorker(type_id, parent=self)
        self._worker.finished_signal.connect(self._on_data_loaded)
        self._worker.error_signal.connect(self._on_error)
        self._worker.start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Title row
        title_row = QHBoxLayout()
        self._title_label = QLabel(f"{self._name} (Type ID: {self._type_id})")
        self._title_label.setObjectName("chart_title")
        title_row.addWidget(self._title_label)
        title_row.addStretch()
        self._status_label = QLabel("加载中...")
        self._status_label.setObjectName("chart_status")
        title_row.addWidget(self._status_label)
        layout.addLayout(title_row)

        # Chart
        self._chart = QChart()
        self._chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        self._chart.legend().setVisible(True)
        self._chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)

        self._chart_view = QChartView(self._chart)
        self._chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout.addWidget(self._chart_view)

        # Bottom row
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("chart_close_btn")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_data_loaded(self, type_id: int, data: list[dict]):
        if type_id != self._type_id:
            return
        self._data = data
        self._status_label.setText(f"已加载 {len(data)} 天数据")
        self._render_chart()

    def _on_error(self, type_id: int, error: str):
        if type_id != self._type_id:
            return
        self._status_label.setText(f"错误: {error}")

    def _render_chart(self):
        if not self._data:
            return

        self._chart.removeAllSeries()
        for axis in list(self._chart.axes()):
            self._chart.removeAxis(axis)

        avg_series = QLineSeries()
        avg_series.setName("日均价 (ISK)")
        vol_series = QLineSeries()
        vol_series.setName("成交量")

        dates: list[QDateTime] = []
        for entry in self._data:
            dt = QDateTime.fromString(entry["date"], "yyyy-MM-dd")
            ts = dt.toMSecsSinceEpoch()
            avg_series.append(ts, entry["average"])
            vol_series.append(ts, entry["volume"])
            dates.append(dt)

        self._chart.addSeries(avg_series)
        self._chart.addSeries(vol_series)

        # X axis (date)
        axis_x = QDateTimeAxis()
        axis_x.setFormat("yyyy-MM-dd")
        axis_x.setTitleText("日期")
        if dates:
            axis_x.setRange(dates[0], dates[-1])
        self._chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        avg_series.attachAxis(axis_x)
        vol_series.attachAxis(axis_x)

        # Y axis 1 (price)
        axis_y = QValueAxis()
        axis_y.setTitleText("价格 (ISK)")
        axis_y.setLabelFormat("%.0f")
        self._chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        avg_series.attachAxis(axis_y)

        # Y axis 2 (volume)
        axis_y2 = QValueAxis()
        axis_y2.setTitleText("成交量")
        axis_y2.setLabelFormat("%.0f")
        self._chart.addAxis(axis_y2, Qt.AlignmentFlag.AlignRight)
        vol_series.attachAxis(axis_y2)

        self._apply_chart_theme()

    def _apply_chart_theme(self):
        """Apply current theme colors to the chart"""
        self._chart.setBackgroundBrush(QColor(theme.BG_DARK))
        self._chart.setPlotAreaBackgroundBrush(QColor(theme.BG_SURFACE))
        self._chart.setPlotAreaBackgroundVisible(True)

        for axis in self._chart.axes():
            if isinstance(axis, (QDateTimeAxis, QValueAxis)):
                axis.setLabelsColor(QColor(theme.TEXT_PRIMARY))
                axis.setTitleBrush(QColor(theme.TEXT_SECONDARY))
                axis.setGridLineColor(QColor(theme.BORDER))

        series = self._chart.series()
        if len(series) >= 1:
            series[0].setColor(QColor(theme.PRIMARY))
        if len(series) >= 2:
            series[1].setColor(QColor(theme.ACCENT_ORANGE))

        self._chart.legend().setLabelColor(QColor(theme.TEXT_PRIMARY))

    def _on_theme_changed(self):
        self._apply_chart_theme()
        self._title_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 13px;")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")

    def closeEvent(self, event):
        theme.remove_theme_listener(self._on_theme_changed)
        if hasattr(self, "_worker") and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)
        super().closeEvent(event)
