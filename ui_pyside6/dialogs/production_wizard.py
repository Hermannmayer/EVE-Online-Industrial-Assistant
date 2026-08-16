"""产线启动小助手 — 两列布局 + 人物产线占用图形化 + 技能联动

顶部：按人物的产线占用卡片（进度条，max=1+高级量产技术等级）。
左侧：全部产线清单（产品/蓝图名可点击复制/流程/状态）。
右侧：选中产线的启动/状态区（备料足→启动按钮；缺料→灰字；运行中/待下线/已完成→文本）。
底部：当前人物下拉（未分配计划默认归此）+ 应用到所选 + 刷新备料。
"""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services import plan_execution
from services.char_capacity import active_lines_per_character, character_line_usage
from services.char_config_resolver import get_character_list

_COL_PRODUCT = 0
_COL_BLUEPRINT = 1  # 点击复制蓝图名
_COL_RUNS = 2
_COL_STATUS = 3

_STATUS_LABELS = {
    "pending": "待生产",
    "in_progress": "运行中",
    "running": "运行中",
    "ready": "待下线",
    "completed": "已完成",
    "done": "已完成",
}


def _fmt_remaining(plan: dict) -> str:
    """运行中计划的剩余时间文本。"""
    rem = plan_execution.remaining_seconds(plan)
    if rem is None:
        return ""
    if rem <= 0:
        return "已超时"
    secs = int(rem)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d {hours}h {mins}m"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


class _UsageCard(QFrame):
    """单个人物的产线占用卡片（进度条 + 文字）。"""

    def __init__(self, char_name: str, active: int, mx: int, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        color = theme.ACCENT_GREEN if active < mx else (theme.ACCENT_YELLOW if active == mx else theme.ACCENT_RED)
        label = QLabel(f"👤 {char_name}  <span style='color:{color};font-weight:bold;'>{active}/{mx}</span>")
        label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
        layout.addWidget(label)

        bar = QProgressBar()
        bar.setRange(0, max(mx, 1))
        bar.setValue(min(active, mx))
        bar.setTextVisible(False)
        bar.setFixedWidth(140)
        bar.setStyleSheet(
            f"QProgressBar {{ background: {theme.BG_SURFACE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
        )
        layout.addWidget(bar)

        if active > mx:
            over = QLabel("⚠ 超员")
            over.setStyleSheet(f"color: {theme.ACCENT_RED}; font-size: 10px;")
            layout.addWidget(over)


class ProductionWizard(QDialog):
    """产线启动小助手 — 图形化占用 + 两列启动"""

    def __init__(self, plans: list[dict], parent=None, *, mat_hangar_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("产线启动小助手")
        self.resize(980, 660)
        self.setMinimumSize(900, 600)
        self.setObjectName("production_wizard")

        self._plans = sorted(plans, key=lambda p: p.get("child_level", 0), reverse=True)  # 子级高的先做
        self._mat_hangar_id = mat_hangar_id
        self._chars = get_character_list()
        self._current_char = self._chars[0] if self._chars else None
        self._bp_names: dict[int, str] = {}  # blueprint_type_id → 蓝图名
        self._shortfall: dict[int, int] = {}  # plan_id → 缺料种数

        self._load_blueprint_names()
        self._compute_readiness()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── 标题 ──
        header = QLabel(f"产线启动小助手 — 共 {len(plans)} 条产线")
        header.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 15px; font-weight: bold;")
        layout.addWidget(header)

        # ── 顶部：产线占用卡片 ──
        self._occ_layout = QHBoxLayout()
        self._occ_layout.setContentsMargins(0, 0, 0, 0)
        self._occ_layout.setSpacing(8)
        layout.addLayout(self._occ_layout)
        self._build_occupancy()

        # ── 主体：两列 ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["产品", "蓝图(点击复制)", "流程", "状态"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(_COL_PRODUCT, 220)
        splitter.addWidget(self._table)

        self._detail = QWidget()
        dl = QVBoxLayout(self._detail)
        dl.setContentsMargins(12, 8, 12, 8)
        self._detail_name = QLabel("")
        self._detail_name.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 14px; font-weight: bold;")
        self._detail_info = QLabel("")
        self._detail_info.setWordWrap(True)
        self._detail_info.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        self._start_btn = QPushButton("▶ 启动产线")
        self._start_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT_GREEN}; color: {theme.TEXT_ON_PRIMARY}; padding: 8px 20px;"
            f" border: none; border-radius: 5px; font-size: 14px; }}"
            f"QPushButton:hover {{ background: {theme.ACCENT_GREEN}; }}"
        )
        self._start_btn.clicked.connect(self._on_start)
        self._start_btn.hide()
        dl.addWidget(self._detail_name)
        dl.addWidget(self._detail_info)
        dl.addWidget(self._start_btn)
        dl.addStretch()
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        # ── 底部：人物 + 应用 + 刷新 + 状态 ──
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("当前人物:"))
        self._char_combo = QComboBox()
        self._char_combo.addItems(self._chars if self._chars else ["（未设置人物）"])
        if self._chars:
            self._char_combo.setCurrentIndex(0)
        self._char_combo.currentTextChanged.connect(self._on_char_changed)
        bottom.addWidget(self._char_combo)

        self._apply_btn = QPushButton("应用到所选")
        self._apply_btn.setToolTip("把当前人物写入选中的产线")
        self._apply_btn.clicked.connect(self._on_apply_char)
        bottom.addWidget(self._apply_btn)

        self._refresh_btn = QPushButton("刷新备料")
        self._refresh_btn.clicked.connect(self._on_refresh_readiness)
        bottom.addWidget(self._refresh_btn)

        bottom.addStretch()
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        bottom.addWidget(self._status_label)
        layout.addLayout(bottom)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn.rejected.connect(self.close)
        layout.addWidget(btn)

        self._populate_table()
        theme.add_theme_listener(self._on_theme_changed)

    # ── 数据准备 ──

    def _load_blueprint_names(self) -> None:
        """批量解析 blueprint_type_id → 蓝图名（reference.db item 表）。"""
        from services.ui_data_service import get_item_names_batch

        bp_ids = {int(p["blueprint_type_id"]) for p in self._plans if p.get("blueprint_type_id")}
        if not bp_ids:
            return
        self._bp_names.update(get_item_names_batch(list(bp_ids), db=get_container().db))

    def _compute_readiness(self) -> None:
        """对 pending 计划批量算缺料种数（mat_hangar_id 未设置则视为充足）。"""
        self._shortfall.clear()
        if not self._mat_hangar_id:
            return
        for p in self._plans:
            if (p.get("status") or "").lower() != "pending":
                continue
            pid = p.get("id")
            if pid is None:
                continue
            try:
                missing = [
                    r for r in plan_execution.check_materials(p, self._mat_hangar_id) if (r.get("missing") or 0) > 0
                ]
                self._shortfall[int(pid)] = len(missing)
            except Exception:
                self._shortfall[int(pid)] = 0

    # ── 顶部占用 ──

    def _build_occupancy(self) -> None:
        """重建人物产线占用卡片。"""
        while self._occ_layout.count():
            item = self._occ_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w:
                    w.deleteLater()
        usage = active_lines_per_character()
        chars = list(self._chars) + [c for c in usage if c and c not in self._chars]
        if not chars:
            hint = QLabel("（无人物配置，请在人物设置中添加）")
            hint.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
            self._occ_layout.addWidget(hint)
            return
        for c in chars:
            active, mx = character_line_usage(c)
            self._occ_layout.addWidget(_UsageCard(c, active, mx, self))
        self._occ_layout.addStretch(1)

    # ── 左侧表格 ──

    def _populate_table(self) -> None:
        self._table.setRowCount(0)
        self._table.setRowCount(len(self._plans))
        for row, p in enumerate(self._plans):
            status = (p.get("status") or "").lower()
            name = p.get("product_name") or f"ID:{p.get('product_type_id', '')}"
            level = p.get("child_level", 0)
            name_text = f"{name}  [子级{level}]" if level else name

            prod = QTableWidgetItem(name_text)
            prod.setData(Qt.ItemDataRole.UserRole, row)
            self._table.setItem(row, _COL_PRODUCT, prod)

            bp_name = self._bp_names.get(p.get("blueprint_type_id") or 0, "")
            bp_btn = QPushButton(f"⧉ {bp_name}" if bp_name else "⧉ 复制")
            bp_btn.setFlat(True)
            bp_btn.setStyleSheet(
                f"QPushButton {{ color: {theme.PRIMARY}; border: none; text-align: left; font-size: 12px; }}"
                f"QPushButton:hover {{ text-decoration: underline; }}"
            )
            bp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            bp_btn.setToolTip("复制蓝图名到剪贴板（在游戏中粘贴搜索）")
            bp_btn.clicked.connect(lambda _, b=bp_name: self._copy_blueprint(b))
            self._table.setCellWidget(row, _COL_BLUEPRINT, bp_btn)

            runs = p.get("runs", 1)
            parallels = p.get("parallels", 1)
            runs_item = QTableWidgetItem(f"{parallels}X{runs}")
            runs_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, _COL_RUNS, runs_item)

            status_item = QTableWidgetItem(_STATUS_LABELS.get(status, status))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status == "pending":
                if self._shortfall.get(int(p.get("id") or 0), 0):
                    status_item.setForeground(QColor(theme.ACCENT_ORANGE))
                else:
                    status_item.setForeground(QColor(theme.ACCENT_GREEN))
            self._table.setItem(row, _COL_STATUS, status_item)
        if self._plans:
            self._table.selectRow(0)

    def _copy_blueprint(self, bp_name: str) -> None:
        QApplication.clipboard().setText(bp_name)
        self._status_label.setText(f"已复制蓝图名: {bp_name}")

    # ── 右侧详情 ──

    def _on_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        self._update_detail(rows[0].row())

    def _update_detail(self, row: int) -> None:
        if not (0 <= row < len(self._plans)):
            return
        p = self._plans[row]
        status = (p.get("status") or "").lower()
        level = p.get("child_level", 0)
        name = p.get("product_name") or f"ID:{p.get('product_type_id', '')}"
        level_tag = f"  [子级{level}]" if level else ""
        self._detail_name.setText(f"{name}{level_tag}")
        runs = p.get("runs", 1)
        parallels = p.get("parallels", 1)
        info = f"并行 {parallels} x 流程 {runs}"
        if p.get("char_name"):
            info += f"  |  人物 {p['char_name']}"
        self._start_btn.hide()
        if status == "pending":
            short = self._shortfall.get(int(p.get("id") or 0), 0)
            if short:
                info += "\n\n⚠ 备料不足，缺 " + str(short) + " 种材料（请先填料或刷新备料）"
                self._detail_info.setStyleSheet(f"color: {theme.ACCENT_ORANGE}; font-size: 12px;")
            else:
                info += "\n\n备料充足，可启动。"
                self._detail_info.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
                self._start_btn.show()
        elif status in ("in_progress", "running"):
            rem = _fmt_remaining(p)
            info += f"\n\n运行中 · 剩余 {rem}"
            self._detail_info.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        elif status == "ready":
            info += "\n\n待下线（请到主表下线入库）"
            self._detail_info.setStyleSheet(f"color: {theme.ACCENT_ORANGE}; font-size: 12px;")
        else:
            info += "\n\n已完成"
            self._detail_info.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        self._detail_info.setText(info)

    # ── 启动 ──

    def _on_start(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        p = self._plans[rows[0].row()]
        char = self._current_char
        # 未分配人物 → 默认当前人物
        assign_char = (p.get("char_name") or "").strip() or char
        # 软提示：超产线上限
        active, mx = character_line_usage(assign_char)
        if active + (p.get("parallels") or 1) > mx:
            ret = QMessageBox.question(
                self,
                "人物产线超员",
                f"{assign_char} 当前占用 {active}/{mx} 条产线，启动后超员。仍要启动？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
        res = plan_execution.start_plan(p, mat_hangar_id=self._mat_hangar_id, char_name=assign_char)
        if res.get("ok"):
            self._status_label.setText(f"已启动: {p.get('product_name', '')}")
            p["status"] = "in_progress"
            p["char_name"] = assign_char
            p["started_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            self._build_occupancy()
            self._populate_table()
        else:
            QMessageBox.warning(self, "启动失败", res.get("message", "未知错误"))

    # ── 人物应用 / 刷新 ──

    def _on_char_changed(self, text: str) -> None:
        self._current_char = text if text != "（未设置人物）" else None

    def _on_apply_char(self) -> None:
        if not self._current_char:
            return
        rows = [idx.row() for idx in self._table.selectionModel().selectedRows()]
        if not rows:
            return
        ids = [self._plans[r]["id"] for r in rows if self._plans[r].get("id")]
        get_container().plan_repo.update_many(ids, char_name=self._current_char)
        for r in rows:
            self._plans[r]["char_name"] = self._current_char
        self._status_label.setText(f"已把 {len(ids)} 条产线应用到人物 {self._current_char}")
        self._build_occupancy()
        self._populate_table()

    def _on_refresh_readiness(self) -> None:
        self._compute_readiness()
        self._populate_table()
        self._status_label.setText("已刷新备料状态")

    def _on_theme_changed(self) -> None:
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
