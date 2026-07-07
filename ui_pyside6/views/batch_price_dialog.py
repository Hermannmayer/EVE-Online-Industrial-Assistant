"""
批量查价对话框 — 同时查询多个物品的市场价格
"""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container
from ui_pyside6.views.export_helper import export_to_csv, get_save_filename

# ── 列定义 ──
_COLUMNS = [
    ("物品名", 160),
    ("买价", 130),
    ("卖价", 130),
    ("均价", 110),
    ("价差", 110),
    ("成交量", 100),
]

_SORT_KEYS = ["name", "buy_val", "sell_val", "avg_val", "spread_val", "vol_val"]


class BatchPriceModel(QAbstractTableModel):
    """批量查价表格模型"""

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(_COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.get("name", "—")
            elif col == 1:
                return row.get("buy_str", "—")
            elif col == 2:
                return row.get("sell_str", "—")
            elif col == 3:
                return row.get("avg_str", "—")
            elif col == 4:
                return row.get("spread_str", "—")
            elif col == 5:
                return row.get("vol_str", "—")
            return ""

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 1:
                return QColor(theme.GREEN) if row.get("buy_val", 0) > 0 else QColor(theme.TEXT_SECONDARY)
            elif col == 2:
                return QColor(theme.RED) if row.get("sell_val", 0) > 0 else QColor(theme.TEXT_SECONDARY)
            elif col == 4:
                sp = row.get("spread_val", 0)
                if sp > 0:
                    return QColor(theme.GREEN)
                elif sp < 0:
                    return QColor(theme.RED)
                return QColor(theme.TEXT_SECONDARY)

        elif role == Qt.ItemDataRole.BackgroundRole:
            if row.get("not_found"):
                return QColor(theme.BG_HOVER)
            if index.row() % 2 == 0:
                return QColor(theme.BG_SURFACE)
            return QColor(theme.BG_DARK)

        elif role == Qt.ItemDataRole.UserRole:
            return row

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _COLUMNS[section][0]
        return super().headerData(section, orientation, role)

    def get_row(self, row_idx: int) -> dict | None:
        if 0 <= row_idx < len(self._rows):
            return self._rows[row_idx]
        return None

    def get_all_rows(self) -> list[dict]:
        return list(self._rows)


class BatchPriceWorker(QThread):
    """批量查价工作线程"""

    finished_signal = Signal(list)  # list[dict]
    progress_signal = Signal(int, int)  # current, total
    error_signal = Signal(str)

    def __init__(self, items: list[dict], parent=None):
        super().__init__(parent)
        self._items = items
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        results = []
        total = len(self._items)
        for i, item in enumerate(self._items):
            if self._cancelled:
                return
            try:
                result = self._query_one(item)
                results.append(result)
            except Exception as e:
                results.append(
                    {
                        "name": item.get("name", str(item.get("type_id", "?"))),
                        "not_found": True,
                        "error": str(e),
                    }
                )
            self.progress_signal.emit(i + 1, total)
        self.finished_signal.emit(results)

    def _query_one(self, item: dict) -> dict:
        """查询单个物品价格"""
        type_id = item["type_id"]
        name = item.get("name", str(type_id))

        with get_container().db.connect("ref") as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                FROM mkt.market_prices mp
                WHERE mp.type_id = ?
                ORDER BY mp.fetch_time DESC
                LIMIT 1
                """,
                (type_id,),
            )
            row = c.fetchone()

        if not row:
            return {"type_id": type_id, "name": name, "not_found": True}

        buy_p, sell_p, buy_v, sell_v = row
        buy_v = buy_v or 0
        sell_v = sell_v or 0

        # 格式价格
        buy_str = "—"
        buy_val = 0.0
        if buy_p is not None and buy_v > 0:
            buy_str = f"{buy_p:,.2f} ({buy_v:,})"
            buy_val = buy_p
        elif buy_p is not None:
            buy_str = f"{buy_p:,.2f}"
            buy_val = buy_p

        sell_str = "—"
        sell_val = 0.0
        if sell_p is not None and sell_v > 0:
            sell_str = f"{sell_p:,.2f} ({sell_v:,})"
            sell_val = sell_p
        elif sell_p is not None:
            sell_str = f"{sell_p:,.2f}"
            sell_val = sell_p

        # 均价
        avg_val = 0.0
        avg_str = "—"
        if buy_val > 0 and sell_val > 0:
            avg_val = (buy_val + sell_val) / 2
            avg_str = f"{avg_val:,.2f}"
        elif buy_val > 0:
            avg_val = buy_val
            avg_str = f"{buy_val:,.2f}"
        elif sell_val > 0:
            avg_val = sell_val
            avg_str = f"{sell_val:,.2f}"

        # 价差
        spread_val = sell_val - buy_val if buy_val > 0 and sell_val > 0 else 0.0
        spread_str = f"{spread_val:+,.2f}" if buy_val > 0 and sell_val > 0 else "—"

        # 成交量
        vol_val = buy_v + sell_v
        vol_str = f"{vol_val:,}" if vol_val > 0 else "—"

        return {
            "type_id": type_id,
            "name": name,
            "buy_str": buy_str,
            "sell_str": sell_str,
            "avg_str": avg_str,
            "spread_str": spread_str,
            "vol_str": vol_str,
            "buy_val": buy_val,
            "sell_val": sell_val,
            "avg_val": avg_val,
            "spread_val": spread_val,
            "vol_val": vol_val,
            "not_found": False,
        }


# ── 数据库搜索 ──


def _search_items(queries: list[str]) -> list[dict]:
    """批量搜索物品，返回 [{type_id, name, raw_query}]"""
    results = []
    seen_type_ids = set()
    with get_container().db.connect("ref") as conn:
        c = conn.cursor()
        for q in queries:
            q = q.strip()
            if not q:
                continue
            if q.isdigit():
                c.execute(
                    "SELECT type_id, zh_name, en_name FROM item WHERE type_id = ?",
                    (int(q),),
                )
            else:
                c.execute(
                    "SELECT type_id, zh_name, en_name FROM item WHERE zh_name LIKE ? OR en_name LIKE ? LIMIT 1",
                    (f"%{q}%", f"%{q}%"),
                )
            row = c.fetchone()
            if row:
                tid, zh, en = row
                if tid not in seen_type_ids:
                    seen_type_ids.add(tid)
                    name = zh or en or str(tid)
                    results.append({"type_id": tid, "name": name, "raw_query": q})
            else:
                # 未找到 — 保留占位
                results.append({"type_id": 0, "name": q, "raw_query": q, "not_found": True})
    return results


class BatchPriceDialog(QDialog):
    """批量查价对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量查价")
        self.setMinimumSize(700, 500)
        self.resize(780, 560)

        self._worker: BatchPriceWorker | None = None
        self._current_results: list[dict] = []

        self._build_ui()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.quit()
            self._worker.wait(2000)
        super().closeEvent(event)

    def _on_theme_changed(self):
        self._input_text.setStyleSheet(
            f"QPlainTextEdit {{"
            f"  background-color: {theme.BG_SURFACE};"
            f"  color: {theme.TEXT_PRIMARY};"
            f"  border: 1px solid {theme.BORDER};"
            f"  border-radius: 4px;"
            f"  padding: 6px;"
            f"  font-size: 12px;"
            f"}}"
        )

        self._query_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {theme.PRIMARY};"
            f"  color: {theme.TEXT_ON_PRIMARY};"
            f"  border: none;"
            f"  border-radius: 4px;"
            f"  padding: 6px 18px;"
            f"  font-size: 12px;"
            f"  font-weight: bold;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {theme.ACCENT_CYAN};"
            f"}}"
            f"QPushButton:disabled {{"
            f"  background-color: {theme.TEXT_SECONDARY};"
            f"  color: {theme.BG_SURFACE};"
            f"}}"
        )

        self._export_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {theme.BG_SURFACE};"
            f"  color: {theme.TEXT_PRIMARY};"
            f"  border: 1px solid {theme.BORDER};"
            f"  border-radius: 4px;"
            f"  padding: 5px 14px;"
            f"  font-size: 11px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {theme.BG_HOVER};"
            f"  border-color: {theme.PRIMARY};"
            f"}}"
            f"QPushButton:disabled {{"
            f"  background-color: {theme.BG_SURFACE};"
            f"  color: {theme.TEXT_SECONDARY};"
            f"}}"
        )

        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")

        self._progress.setStyleSheet(
            f"QProgressBar {{"
            f"  background-color: {theme.BG_SURFACE};"
            f"  border: none;"
            f"  border-radius: 1px;"
            f"  height: 3px;"
            f"}}"
            f"QProgressBar::chunk {{"
            f"  background-color: {theme.PRIMARY};"
            f"  border-radius: 1px;"
            f"}}"
        )

        self._table.setStyleSheet(
            f"QTableView {{"
            f"  background-color: {theme.BG_DARK};"
            f"  alternate-background-color: {theme.BG_SURFACE};"
            f"  border: 1px solid {theme.BORDER};"
            f"  border-radius: 4px;"
            f"  gridline-color: {theme.BORDER};"
            f"  selection-background-color: {theme.PRIMARY};"
            f"  selection-color: {theme.TEXT_BRIGHT};"
            f"  outline: none;"
            f"}}"
            f"QTableView::item {{"
            f"  padding: 3px 6px;"
            f"  border-bottom: 1px solid {theme.BORDER};"
            f"}}"
            f"QTableView::item:selected {{"
            f"  background-color: {theme.PRIMARY};"
            f"  color: {theme.TEXT_BRIGHT};"
            f"}}"
            f"QHeaderView::section {{"
            f"  background-color: {theme.BG_SURFACE};"
            f"  color: {theme.TEXT_PRIMARY};"
            f"  padding: 4px 6px;"
            f"  border: none;"
            f"  border-right: 1px solid {theme.BORDER};"
            f"  border-bottom: 1px solid {theme.BORDER};"
            f"  font-weight: bold;"
            f"  font-size: 11px;"
            f"}}"
            f"QHeaderView::section:hover {{"
            f"  background-color: {theme.BG_HOVER};"
            f"}}"
        )

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # ── 输入区 ──
        input_label = QLabel("输入物品名称或 ID（每行一个，支持粘贴）:")
        layout.addWidget(input_label)

        self._input_text = QPlainTextEdit()
        self._input_text.setPlaceholderText("例如:\n三神裔无畏舰\nTritanium\n10000002\nPlex")
        self._input_text.setMinimumHeight(100)
        self._input_text.setMaximumHeight(160)
        layout.addWidget(self._input_text)

        # ── 按钮行 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._query_btn = QPushButton("查询")
        self._query_btn.clicked.connect(self._on_query)
        btn_row.addWidget(self._query_btn)

        btn_row.addStretch()

        self._export_btn = QPushButton("导出 CSV")
        self._export_btn.clicked.connect(self._on_export_csv)
        self._export_btn.setEnabled(False)
        btn_row.addWidget(self._export_btn)

        layout.addLayout(btn_row)

        # ── 进度条 ──
        self._progress = QProgressBar()
        self._progress.setFixedHeight(3)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # ── 结果表格 ──
        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setDefaultSectionSize(28)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(True)

        self._model = BatchPriceModel()
        self._table.setModel(self._model)

        for i, (_, w) in enumerate(_COLUMNS):
            self._table.setColumnWidth(i, w)

        layout.addWidget(self._table, 1)

        # ── 状态栏 ──
        self._status_label = QLabel("输入物品名称或 ID 后点击查询")
        layout.addWidget(self._status_label)

    # ═══════════════════════════════════════
    #  查询
    # ═══════════════════════════════════════

    def _on_query(self):
        text = self._input_text.toPlainText().strip()
        if not text:
            self._status_label.setText("请先输入物品名称或 ID")
            return

        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            self._status_label.setText("请先输入物品名称或 ID")
            return

        self._query_btn.setEnabled(False)
        self._export_btn.setEnabled(False)
        self._model.set_rows([])
        self._current_results = []

        # 搜索物品
        self._status_label.setText(f"正在解析 {len(lines)} 个物品...")
        items = _search_items(lines)

        # 统计有效查询
        valid = [it for it in items if not it.get("not_found")]
        if not valid:
            self._status_label.setText("未找到任何匹配的物品")
            self._query_btn.setEnabled(True)
            return

        self._status_label.setText(f"正在查询 {len(valid)} 个物品的价格...")
        self._progress.setVisible(True)
        self._progress.setRange(0, len(valid))
        self._progress.setValue(0)

        self._worker = BatchPriceWorker(valid, self)
        self._worker.finished_signal.connect(self._on_query_done)
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.error_signal.connect(self._on_query_error)
        self._worker.start()

    def _on_progress(self, current: int, total: int):
        self._progress.setValue(current)
        self._status_label.setText(f"正在查询... {current}/{total}")

    def _on_query_done(self, results: list[dict]):
        self._progress.setVisible(False)
        self._query_btn.setEnabled(True)

        # 合并未找到的项目
        text = self._input_text.toPlainText().strip()
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        items = _search_items(lines)
        not_found_items = [it for it in items if it.get("not_found")]

        all_results = list(results)
        for nf in not_found_items:
            all_results.append(
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

        self._current_results = all_results
        self._model.set_rows(all_results)

        found_count = sum(1 for r in all_results if not r.get("not_found"))
        nf_count = sum(1 for r in all_results if r.get("not_found"))
        status = f"查询完成: {found_count} 个有价格"
        if nf_count:
            status += f", {nf_count} 个未找到"
        self._status_label.setText(status)

        self._export_btn.setEnabled(bool(all_results))

    def _on_query_error(self, error: str):
        self._progress.setVisible(False)
        self._query_btn.setEnabled(True)
        self._status_label.setText(f"查询出错: {error}")

    # ═══════════════════════════════════════
    #  导出 CSV
    # ═══════════════════════════════════════

    def _on_export_csv(self):
        if not self._current_results:
            return

        path = get_save_filename(self, "批量查价.csv", "CSV 文件 (*.csv)")
        if not path:
            return

        headers = ["物品名", "买价", "卖价", "均价", "价差", "成交量"]
        rows = []
        for r in self._current_results:
            rows.append(
                [
                    r.get("name", "—"),
                    r.get("buy_str", "—"),
                    r.get("sell_str", "—"),
                    r.get("avg_str", "—"),
                    r.get("spread_str", "—"),
                    r.get("vol_str", "—"),
                ]
            )

        try:
            export_to_csv(headers, rows, path)
            self._status_label.setText(f"已导出: {path}")
        except Exception as e:
            self._status_label.setText(f"导出失败: {e}")
