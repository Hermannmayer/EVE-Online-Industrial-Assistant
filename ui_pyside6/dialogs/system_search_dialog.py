"""星系搜索选择对话框 — 供机库设置 / 生产计划设施选择复用。

依赖 reference.db 的 solar_system 表（由 SDE universe 数据加载填充）；
表为空时禁用搜索并提示先运行数据初始化。
"""

from PySide6.QtCore import QTimer
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services.name_resolver import resolve_system_name
from services.terminology import term


class SystemSearchDialog(QDialog):
    """按名称搜索并选择一个星系，返回 (solar_system_id, 星系名)。"""

    def __init__(self, parent=None, title="选择星系"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(480, 420)
        self._selected: tuple[int, str] | None = None
        self._data: list[tuple[int, str, float]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("输入星系名（如 Jita / 吉他）...")
        self._search.setClearButtonEnabled(True)
        layout.addWidget(self._search)

        self._table = QTableView()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(self._accept_current)
        layout.addWidget(self._table, 1)

        self._hint = QLabel("")
        layout.addWidget(self._hint)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self._accept_current)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        self._model = QStandardItemModel(0, 2, self)
        self._model.setHorizontalHeaderLabels(["星系", "安全等级"])
        self._table.setModel(self._model)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        # 星系数据是否已加载（solar_system 表为空 → 提示先运行数据初始化）
        self._data_ready = self._check_data()
        if not self._data_ready:
            self._search.setEnabled(False)
            self._table.setEnabled(False)
            self._hint.setText("⚠ 星系数据尚未加载，请先在 设置 → 数据初始化 重跑 SDE 扩展数据")

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._run_search)
        self._search.textChanged.connect(lambda _: self._debounce.start())
        self._run_search()

        theme.add_theme_listener(self._on_theme_changed)

    def _check_data(self) -> bool:
        try:
            with get_container().db.connect("ref") as conn:
                row = conn.execute("SELECT COUNT(*) FROM solar_system").fetchone()
                return bool(row and row[0] > 0)
        except Exception:
            return False

    def _run_search(self):
        if not self._data_ready:
            return
        q = self._search.text().strip()
        self._data = []
        try:
            with get_container().db.connect("ref") as conn:
                if q:
                    # 英文 LIKE + 中文名反查（terminology.system_names）合并
                    zh_ens = term.search_system_names(q)
                    en_sql = "solar_system_name LIKE ?"
                    params: list = [f"%{q}%"]
                    if zh_ens:
                        placeholders = ",".join("?" * len(zh_ens))
                        en_sql += f" OR solar_system_name IN ({placeholders})"
                        params.extend(zh_ens)
                    cur = conn.execute(
                        "SELECT solar_system_id, solar_system_name, security FROM solar_system"
                        f" WHERE {en_sql} ORDER BY solar_system_name LIMIT 30",
                        params,
                    )
                else:
                    cur = conn.execute(
                        "SELECT solar_system_id, solar_system_name, security FROM solar_system "
                        "ORDER BY solar_system_name LIMIT 30"
                    )
                for sid, _en, sec in cur.fetchall():
                    display = resolve_system_name(conn, int(sid))
                    self._data.append((int(sid), display, float(sec or 0)))
        except Exception:
            self._data = []

        self._model.removeRows(0, self._model.rowCount())
        for sid, name, sec in self._data:
            self._model.appendRow(
                [
                    QStandardItem(name or str(sid)),
                    QStandardItem(f"{sec:.1f}" if sec else ""),
                ]
            )
        self._hint.setText(f"共 {len(self._data)} 个星系")

    def _accept_current(self):
        idx = self._table.currentIndex()
        if idx.isValid() and 0 <= idx.row() < len(self._data):
            sid, name, _sec = self._data[idx.row()]
            self._selected = (sid, name or str(sid))
            self.accept()

    def get_selected(self) -> tuple[int, str] | None:
        """返回 (solar_system_id, 星系名)；未选择返回 None。"""
        return self._selected

    def _on_theme_changed(self):
        """主题切换时刷新提示色（表格走全局 QSS）"""
        self._hint.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
