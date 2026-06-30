"""
批量对比模式 — 多物品同屏对比利润和评分
"""

import csv
import os

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QThread, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUBS
from core.container import get_container
from core.paths import ICON_DIR
from services.scoring import calc_manufacturing_score, calc_reaction_score, calc_trade_score
from services.scoring_cache import cache_key as _ck
from services.scoring_cache import get as _cget
from services.scoring_cache import set as _cset
from ui_pyside6.views.char_settings_view import get_character, get_character_list

# ── 搜索 SQL（参数化） ──
_SEARCH_SQL = (
    "SELECT i.type_id, i.zh_name, i.en_name "
    "FROM item i "
    "WHERE (i.type_id = ? OR i.zh_name LIKE ? OR i.en_name LIKE ?) "
    "ORDER BY CASE WHEN i.en_name LIKE ? THEN 0 "
    "WHEN i.zh_name LIKE ? THEN 1 ELSE 2 END, i.zh_name "
    "LIMIT 50"
)


def _search_items(query: str) -> list[dict]:
    """按名称/ID 搜索物品"""
    q = query.strip()
    if not q:
        return []
    like = f"%{q}%"
    with get_container().db.connect("ref") as conn:
        c = conn.cursor()
        if q.isdigit():
            c.execute(_SEARCH_SQL, (int(q), like, like, f"{q}%", f"{q}%"))
        else:
            c.execute(_SEARCH_SQL, (0, like, like, f"{q}%", f"{q}%"))
        return [{"type_id": r[0], "zh_name": r[1] or "", "en_name": r[2] or ""} for r in c.fetchall()]


def _item_name(type_id: int) -> str:
    """获取物品中文名"""
    with get_container().db.connect("ref") as conn:
        c = conn.cursor()
        c.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (type_id,))
        row = c.fetchone()
        return (row[0] or row[1] or str(type_id)) if row else str(type_id)


def _format_isk(value: float) -> str:
    """格式化 ISK 金额"""
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def _fmt_tag(daily_profit: float, veto: str = "") -> str:
    """将日均利润格式化为等级标签"""
    if veto:
        return "✗"
    if daily_profit >= 50_000_000:
        return f"{daily_profit / 100_000_000:.1f}亿 S"
    if daily_profit >= 10_000_000:
        return f"{daily_profit / 10_000:.0f}万 A"
    if daily_profit >= 1_000_000:
        return f"{daily_profit / 10_000:.0f}万 B"
    if daily_profit >= 100_000:
        return f"{daily_profit / 10_000:.0f}万 C"
    return f"{daily_profit / 10_000:.0f}万 D"


# ═══════════════════════════════════════════
#  对比表模型
# ═══════════════════════════════════════════

COMPARE_COLS_MFG = [
    ("物品", 160, "name"),
    ("成本", 100, "cost"),
    ("收入", 100, "revenue"),
    ("利润", 100, "profit"),
    ("利润率%", 70, "margin"),
    ("评分", 60, "score"),
    ("时均ISK/h", 100, "isk_per_hour"),
    ("产能/天", 70, "runs_per_day"),
    ("状态", 90, "status"),
]

COMPARE_COLS_TRADE = [
    ("物品", 160, "name"),
    ("买入", 100, "buy_cost"),
    ("卖出", 100, "sell_revenue"),
    ("毛利", 100, "gross_profit"),
    ("利润率%", 70, "margin"),
    ("评分", 60, "score"),
    ("每方利率", 90, "profit_per_m3"),
    ("状态", 90, "status"),
]

COMPARE_COLS_REACTION = COMPARE_COLS_MFG  # 反应与制造结构一致


class CompareTableModel(QAbstractTableModel):
    """对比结果表格模型"""

    def __init__(self, mode: str = "mfg"):
        super().__init__()
        self._rows: list[dict] = []
        self._mode = mode
        self._cols = self._get_cols()

    def _get_cols(self) -> list[tuple]:
        if self._mode == "trade":
            return COMPARE_COLS_TRADE
        if self._mode == "reaction":
            return COMPARE_COLS_REACTION
        return COMPARE_COLS_MFG

    def set_mode(self, mode: str):
        self.beginResetModel()
        self._mode = mode
        self._cols = self._get_cols()
        self.endResetModel()

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._cols)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        _, _, key = self._cols[index.column()]
        value = row.get(key)

        if role == Qt.ItemDataRole.DecorationRole:
            if key == "name":  # 物品名称列显示图标
                type_id = row.get("type_id")
                if type_id:
                    icon_path = os.path.join(ICON_DIR, f"{type_id}.png")
                    if os.path.exists(icon_path):
                        return QIcon(icon_path)
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            if key == "name":
                return value or ""
            if key in ("cost", "revenue", "profit", "buy_cost", "sell_revenue", "gross_profit"):
                return _format_isk(value) if isinstance(value, (int, float)) and value is not None else "—"
            if key == "margin":
                if value is None:
                    return "—"
                return f"{value:.1f}%"
            if key == "score":
                return f"{value:.1f}" if isinstance(value, (int, float)) and value else "—"
            if key == "isk_per_hour":
                return _format_isk(value) if isinstance(value, (int, float)) and value else "—"
            if key == "profit_per_m3":
                return _format_isk(value) if isinstance(value, (int, float)) and value else "—"
            if key == "runs_per_day":
                return f"{value:.1f}" if isinstance(value, (int, float)) and value else "—"
            if key == "status":
                tips = {
                    "no_blueprint": "无蓝图",
                    "no_price": "无价格",
                    "no_materials": "无材料",
                    "no_depth": "市场无买单",
                }
                return tips.get(value, value) if value else "—"
            return str(value) if value is not None else ""

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if key not in ("name",):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.ForegroundRole:
            if key == "profit":
                v = value or 0
                return QColor(theme.ACCENT_GREEN) if v > 0 else QColor(theme.ACCENT_RED)
            if key == "margin":
                v = float(value or 0)
                return QColor(theme.ACCENT_GREEN) if v > 0 else QColor(theme.ACCENT_RED)
            if key == "gross_profit":
                v = value or 0
                return QColor(theme.ACCENT_GREEN) if v > 0 else QColor(theme.ACCENT_RED)
            if key == "status":
                if value and value != "":
                    return QColor(theme.ACCENT_RED)

        if role == Qt.ItemDataRole.UserRole:
            return row

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section < len(self._cols):
                return self._cols[section][0]
        return None

    def get_export_data(self) -> list[list]:
        """导出 CSV 数据"""
        header = [col[0] for col in self._cols]
        rows = []
        for row in self._rows:
            row_data = []
            for _, _, key in self._cols:
                val = row.get(key)
                if val is None:
                    row_data.append("")
                elif isinstance(val, float):
                    row_data.append(f"{val:.2f}")
                else:
                    row_data.append(str(val))
            rows.append(row_data)
        return [header] + rows


# ═══════════════════════════════════════════
#  对比计算 Worker
# ═══════════════════════════════════════════


class CompareWorker(QThread):
    """后台对比计算 Worker"""

    progress = Signal(int, int)
    item_done = Signal(int, dict)
    done = Signal(list)

    def __init__(self, items: list[dict], mode: str, cfg: dict, parent=None):
        super().__init__(parent)
        self._items = items
        self._mode = mode
        self._cfg = cfg
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self._items)
        results = []
        char_cfg = None
        char_name = self._cfg.get("char", "")
        if char_name:
            char_cfg = get_character(char_name)

        for i, item in enumerate(self._items):
            if self._cancelled:
                break

            tid = item["type_id"]
            name = item.get("name") or _item_name(tid)
            row = {"type_id": tid, "name": name}

            try:
                if self._mode == "mfg":
                    self._calc_mfg(tid, row, char_cfg)
                elif self._mode == "trade":
                    self._calc_trade(tid, row, char_cfg)
                elif self._mode == "reaction":
                    self._calc_reaction(tid, row, char_cfg)
            except Exception as e:
                row["status"] = f"错误: {e}"

            results.append(row)
            self.progress.emit(i + 1, total)
            self.item_done.emit(i + 1, row)

        self.done.emit(results)

    def _calc_mfg(self, tid: int, row: dict, char_cfg: dict | None):
        hub = self._cfg.get("hub", "Jita")
        tax = self._cfg.get("tax", 0)
        me = self._cfg.get("me", 0)
        te = self._cfg.get("te", 0)

        k = _ck(tid, "mfg", hub, self._cfg.get("char", ""))
        r = _cget(k)
        if not r:
            r = calc_manufacturing_score(
                tid,
                char_cfg or {},
                hub,
                hub,
                tax,
                bp_me=me,
                bp_te=te,
            )
            _cset(k, r)

        h = r.get("hours_per_run", 1) or 1
        runs_per_day = 24 / h
        row.update(
            {
                "cost": r.get("cost_per_unit", 0),
                "revenue": r.get("revenue_per_unit", 0),
                "profit": r.get("profit_per_run", 0),
                "margin": r.get("margin_pct", 0),
                "score": r.get("score", 0),
                "isk_per_hour": r.get("isk_per_hour", 0),
                "runs_per_day": runs_per_day,
                "status": r.get("status", ""),
            }
        )

    def _calc_trade(self, tid: int, row: dict, char_cfg: dict | None):
        bh = self._cfg.get("bh", "Jita")
        sh = self._cfg.get("sh", "Jita")
        bs = self._cfg.get("bs", "sell")
        ss = self._cfg.get("ss", "sell")

        k = _ck(tid, "trade", bh + sh, self._cfg.get("char", ""))
        r = _cget(k)
        if not r:
            r = calc_trade_score(tid, bh, sh, bs, ss, char_cfg or {})
            _cset(k, r)

        row.update(
            {
                "buy_cost": r.get("buy_cost", 0),
                "sell_revenue": r.get("sell_revenue", 0),
                "gross_profit": r.get("gross_profit", 0),
                "margin": r.get("margin_pct", 0),
                "score": r.get("score", 0),
                "profit_per_m3": r.get("profit_per_m3", 0),
                "status": r.get("status", ""),
            }
        )

    def _calc_reaction(self, tid: int, row: dict, char_cfg: dict | None):
        hub = self._cfg.get("hub", "Jita")
        tax = self._cfg.get("tax", 0)

        k = _ck(tid, "reaction", hub, self._cfg.get("char", ""))
        r = _cget(k)
        if not r:
            r = calc_reaction_score(
                tid,
                char_cfg or {},
                hub,
                hub,
                tax,
            )
            _cset(k, r)

        h = r.get("hours_per_run", 1) or 1
        runs_per_day = 24 / h
        row.update(
            {
                "cost": r.get("cost_per_unit", 0),
                "revenue": r.get("revenue_per_unit", 0),
                "profit": r.get("profit_per_run", 0),
                "margin": r.get("margin_pct", 0),
                "score": r.get("score", 0),
                "isk_per_hour": r.get("isk_per_hour", 0),
                "runs_per_day": runs_per_day,
                "status": r.get("status", ""),
            }
        )


# ═══════════════════════════════════════════
#  批量对比对话框
# ═══════════════════════════════════════════


class CompareDialog(QDialog):
    """批量对比模式 — 多物品同屏对比利润和评分"""

    def __init__(self, initial_items: list[dict] | None = None, parent=None):
        """
        initial_items: 预选物品列表 [{"type_id": int, "name": str}, ...]
        """
        super().__init__(parent)
        self.setWindowTitle("批量对比")
        self.setMinimumSize(900, 560)
        self.resize(1000, 620)

        self._selected_items: list[dict] = []
        self._search_results: list[dict] = []
        self._worker: CompareWorker | None = None
        self._results: list[dict] = []

        self._build_ui()

        # 加载预选物品
        if initial_items:
            for item in initial_items:
                if not any(it["type_id"] == item["type_id"] for it in self._selected_items):
                    name = item.get("name") or _item_name(item["type_id"])
                    self._selected_items.append({"type_id": item["type_id"], "name": name})
            self._refresh_item_list()

        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.quit()
            self._worker.wait(2000)
        super().closeEvent(event)

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式表"""
        # 主背景
        self.setStyleSheet(f"QDialog {{ background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; }}")
        # 搜索框
        self._search_input.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:4px;padding:4px 8px;"
        )
        # 添加按钮
        self._add_btn.setStyleSheet(
            f"QPushButton{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};"
            f"border:none;border-radius:4px;padding:4px 12px;font-size:11px;}}"
            f"QPushButton:hover{{background:{theme.ACCENT_CYAN};}}"
        )
        # 物品列表
        self._item_list.setStyleSheet(
            f"QListWidget{{background:{theme.BG_SURFACE};border:1px solid {theme.BORDER};"
            f"border-radius:4px;font-size:11px;}}"
            f"QListWidget::item{{padding:3px 6px;border-bottom:1px solid {theme.BORDER};}}"
            f"QListWidget::item:hover{{background:{theme.BG_HOVER};}}"
        )
        # 删除按钮（列表项内）
        # 下拉框
        self._mode_combo.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px 6px;font-size:11px;"
        )
        self._hub_combo.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px 6px;font-size:11px;"
        )
        self._char_combo.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px 6px;font-size:11px;"
        )
        # ME/TE
        self._me_spin.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px;"
        )
        self._te_spin.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px;"
        )
        self._tax_spin.setStyleSheet(
            f"background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px;"
        )
        # 对比按钮
        self._compare_btn.setStyleSheet(
            f"QPushButton{{background:{theme.PRIMARY};color:{theme.TEXT_ON_PRIMARY};"
            f"border:none;border-radius:4px;padding:5px 16px;font-size:12px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{theme.ACCENT_CYAN};}}"
            f"QPushButton:disabled{{background:{theme.TEXT_SECONDARY};color:{theme.BG_SURFACE};}}"
        )
        # 导出按钮
        self._export_btn.setStyleSheet(
            f"QPushButton{{background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:4px;padding:4px 12px;font-size:11px;}}"
            f"QPushButton:hover{{background:{theme.BG_HOVER};border-color:{theme.PRIMARY};}}"
        )
        # 状态栏
        self._status.setStyleSheet(f"color:{theme.TEXT_SECONDARY};font-size:11px;")
        # 进度条
        self._progress.setStyleSheet(
            f"QProgressBar{{background:{theme.BG_SURFACE};border:none;border-radius:1px;height:3px;}}"
            f"QProgressBar::chunk{{background:{theme.PRIMARY};border-radius:1px;}}"
        )
        # 标签
        for lbl in [
            self._lbl_hub,
            self._lbl_mode,
            self._lbl_char,
            self._lbl_me,
            self._lbl_te,
            self._lbl_tax,
            self._lbl_items,
        ]:
            lbl.setStyleSheet(f"color:{theme.TEXT_SECONDARY};font-size:11px;")
        # 清空按钮
        self._clear_btn.setStyleSheet(
            f"QPushButton{{background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"border:1px solid {theme.BORDER};border-radius:4px;padding:3px 8px;font-size:10px;}}"
            f"QPushButton:hover{{background:{theme.BG_HOVER};border-color:{theme.ACCENT_RED};}}"
        )
        # 表格（通过模型控制颜色，这里只设置基本样式）
        self._table.setStyleSheet(
            f"QTableView{{background:{theme.BG_DARK};alternate-background-color:{theme.BG_SURFACE};"
            f"border:1px solid {theme.BORDER};border-radius:4px;gridline-color:{theme.BORDER};"
            f"selection-background-color:{theme.PRIMARY};selection-color:{theme.TEXT_BRIGHT};outline:none;}}"
            f"QTableView::item{{padding:3px 6px;border-bottom:1px solid {theme.BORDER};}}"
            f"QTableView::item:selected{{background:{theme.PRIMARY};color:{theme.TEXT_BRIGHT};}}"
            f"QHeaderView::section{{background:{theme.BG_SURFACE};color:{theme.TEXT_PRIMARY};"
            f"padding:4px 6px;border:none;border-right:1px solid {theme.BORDER};"
            f"border-bottom:1px solid {theme.BORDER};font-weight:bold;font-size:11px;}}"
            f"QHeaderView::section:hover{{background:{theme.BG_HOVER};}}"
        )

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ── 搜索添加区 ──
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索物品名称或ID...")
        self._search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_input, 1)

        self._add_btn = QPushButton("添加")
        self._add_btn.clicked.connect(self._on_add_first_match)
        search_row.addWidget(self._add_btn)
        main_layout.addLayout(search_row)

        # ── 已添加物品列表 ──
        items_header = QHBoxLayout()
        self._lbl_items = QLabel("已添加:")
        items_header.addWidget(self._lbl_items)
        self._clear_btn = QPushButton("清空")
        self._clear_btn.clicked.connect(self._on_clear_items)
        items_header.addWidget(self._clear_btn)
        items_header.addStretch()
        main_layout.addLayout(items_header)

        self._item_list = QListWidget()
        self._item_list.setMaximumHeight(90)
        self._item_list.model().rowsInserted.connect(self._scroll_to_bottom)
        main_layout.addWidget(self._item_list)

        # ── 参数设置 ──
        settings_row = QHBoxLayout()
        settings_row.setSpacing(6)

        self._lbl_mode = QLabel("类型:")
        settings_row.addWidget(self._lbl_mode)
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["制造评分", "贸易评分", "反应评分"])
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        settings_row.addWidget(self._mode_combo)

        self._lbl_hub = QLabel("区域:")
        settings_row.addWidget(self._lbl_hub)
        self._hub_combo = QComboBox()
        self._hub_combo.addItems(TRADE_HUBS)
        settings_row.addWidget(self._hub_combo)

        self._lbl_char = QLabel("角色:")
        settings_row.addWidget(self._lbl_char)
        self._char_combo = QComboBox()
        chars = get_character_list()
        self._char_combo.addItems(chars if chars else ["main"])
        settings_row.addWidget(self._char_combo)

        self._lbl_me = QLabel("ME:")
        settings_row.addWidget(self._lbl_me)
        self._me_spin = QSpinBox()
        self._me_spin.setRange(0, 10)
        self._me_spin.setValue(0)
        settings_row.addWidget(self._me_spin)

        self._lbl_te = QLabel("TE:")
        settings_row.addWidget(self._lbl_te)
        self._te_spin = QSpinBox()
        self._te_spin.setRange(0, 20)
        self._te_spin.setValue(0)
        settings_row.addWidget(self._te_spin)

        self._lbl_tax = QLabel("税%:")
        settings_row.addWidget(self._lbl_tax)
        self._tax_spin = QDoubleSpinBox()
        self._tax_spin.setRange(0, 100)
        self._tax_spin.setSuffix("%")
        self._tax_spin.setValue(0)
        settings_row.addWidget(self._tax_spin)

        settings_row.addStretch()

        self._compare_btn = QPushButton("开始对比")
        self._compare_btn.clicked.connect(self._on_compare)
        settings_row.addWidget(self._compare_btn)

        self._export_btn = QPushButton("导出CSV")
        self._export_btn.clicked.connect(self._on_export_csv)
        self._export_btn.setEnabled(False)
        settings_row.addWidget(self._export_btn)

        main_layout.addLayout(settings_row)

        # ── 进度条 ──
        self._progress = QProgressBar()
        self._progress.setFixedHeight(3)
        self._progress.setVisible(False)
        main_layout.addWidget(self._progress)

        # ── 对比表格 ──
        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setDefaultSectionSize(26)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(True)
        self._model = CompareTableModel()
        self._table.setModel(self._model)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        main_layout.addWidget(self._table, 1)

        # ── 状态栏 ──
        self._status = QLabel("就绪")
        main_layout.addWidget(self._status)

    def _scroll_to_bottom(self):
        self._item_list.scrollToBottom()

    # ── 搜索与添加 ──

    def _on_search(self):
        q = self._search_input.text().strip()
        if not q:
            return
        self._search_results = _search_items(q)
        if self._search_results:
            first = self._search_results[0]
            name = first.get("zh_name") or first.get("en_name") or str(first["type_id"])
            self._status.setText(f"找到 {len(self._search_results)} 条，首个: {name}")
        else:
            self._status.setText("未找到匹配物品")

    def _on_add_first_match(self):
        """添加搜索结果中的第一个匹配项"""
        q = self._search_input.text().strip()
        if not q:
            return
        results = _search_items(q)
        if not results:
            self._status.setText("未找到匹配物品")
            return
        first = results[0]
        self._add_item(first["type_id"], first.get("zh_name") or first.get("en_name") or str(first["type_id"]))
        self._search_input.clear()
        self._search_results = []

    def _add_item(self, type_id: int, name: str):
        """添加物品到对比列表"""
        if any(it["type_id"] == type_id for it in self._selected_items):
            self._status.setText(f"已添加: {name}")
            return
        self._selected_items.append({"type_id": type_id, "name": name})
        self._refresh_item_list()
        self._status.setText(f"已添加: {name} (共 {len(self._selected_items)} 项)")

    def _refresh_item_list(self):
        """刷新已添加物品列表"""
        self._item_list.clear()
        for i, item in enumerate(self._selected_items):
            name = item.get("name") or _item_name(item["type_id"])
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(4, 2, 4, 2)
            layout.setSpacing(4)

            lbl = QLabel(f"{i + 1}. {name}")
            lbl.setStyleSheet(f"color:{theme.TEXT_PRIMARY};font-size:11px;")
            layout.addWidget(lbl, 1)

            del_btn = QPushButton("✕")
            del_btn.setFixedSize(18, 18)
            del_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{theme.ACCENT_RED};"
                f"border:none;border-radius:9px;font-size:10px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{theme.ACCENT_RED};color:{theme.TEXT_ON_PRIMARY};}}"
            )
            del_btn.clicked.connect(lambda _, idx=i: self._remove_item(idx))
            layout.addWidget(del_btn)

            list_item = QListWidgetItem()
            list_item.setSizeHint(widget.sizeHint())
            self._item_list.addItem(list_item)
            self._item_list.setItemWidget(list_item, widget)

    def _remove_item(self, index: int):
        """删除指定索引的物品"""
        if 0 <= index < len(self._selected_items):
            removed = self._selected_items.pop(index)
            self._refresh_item_list()
            self._status.setText(f"已移除: {removed.get('name', '')} (共 {len(self._selected_items)} 项)")

    def _on_clear_items(self):
        """清空所有物品"""
        self._selected_items.clear()
        self._refresh_item_list()
        self._results.clear()
        self._model.set_rows([])
        self._export_btn.setEnabled(False)
        self._status.setText("已清空")

    # ── 模式切换 ──

    def _on_mode_changed(self, index: int):
        """模式切换时更新列"""
        mode = ["mfg", "trade", "reaction"][index]
        self._model.set_mode(mode)
        # ME/TE 仅制造模式可见
        is_mfg = mode in ("mfg", "reaction")
        self._me_spin.setVisible(is_mfg)
        self._te_spin.setVisible(is_mfg)
        self._lbl_me.setVisible(is_mfg)
        self._lbl_te.setVisible(is_mfg)
        # 如果有结果，重新计算
        if self._results:
            self._on_compare()

    # ── 对比计算 ──

    def _on_compare(self):
        """开始对比计算"""
        if not self._selected_items:
            self._status.setText("请先添加物品")
            return
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)

        mode_index = self._mode_combo.currentIndex()
        mode = ["mfg", "trade", "reaction"][mode_index]
        mode_names = ["制造评分", "贸易评分", "反应评分"]

        cfg = {
            "hub": self._hub_combo.currentText(),
            "char": self._char_combo.currentText(),
            "tax": self._tax_spin.value(),
            "me": self._me_spin.value(),
            "te": self._te_spin.value(),
            # 贸易模式额外参数
            "bh": self._hub_combo.currentText(),
            "sh": self._hub_combo.currentText(),
            "bs": "sell",
            "ss": "sell",
        }

        self._compare_btn.setEnabled(False)
        self._export_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(self._selected_items))
        self._progress.setValue(0)
        self._status.setText(f"正在计算 {mode_names[mode_index]}...")

        self._worker = CompareWorker(self._selected_items, mode, cfg, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, current: int, total: int):
        self._progress.setValue(current)
        self._status.setText(f"计算中 {current}/{total}...")

    def _on_done(self, results: list[dict]):
        self._results = results
        self._model.set_rows(results)
        self._progress.setVisible(False)
        self._compare_btn.setEnabled(True)
        self._export_btn.setEnabled(True)

        # 统计
        valid = [r for r in results if not r.get("status")]
        if valid:
            mode = ["mfg", "trade", "reaction"][self._mode_combo.currentIndex()]
            if mode == "trade":
                best = max(valid, key=lambda x: x.get("gross_profit", 0))
                best_profit = best.get("gross_profit", 0)
            else:
                best = max(valid, key=lambda x: x.get("profit", 0))
                best_profit = best.get("profit", 0)
            self._status.setText(
                f"完成 {len(results)} 项 | 有效 {len(valid)} 项 | "
                f"最佳: {best.get('name', '')} ({_format_isk(best_profit)} ISK)"
            )
        else:
            self._status.setText(f"完成 {len(results)} 项 | 无有效结果")

    # ── 右键菜单 ──

    def _show_context_menu(self, pos):
        """表格右键菜单"""
        index = self._table.indexAt(pos)
        if not index.isValid():
            return

        menu = theme.themed_menu(self._table)
        row_data = self._model.data(index, Qt.ItemDataRole.UserRole)

        # 复制行数据
        copy_row_action = menu.addAction("复制行数据")
        copy_row_action.triggered.connect(lambda: self._copy_row(row_data))

        # 复制全部
        copy_all_action = menu.addAction("复制全部 (CSV)")
        copy_all_action.triggered.connect(self._copy_all_as_csv)

        menu.addSeparator()

        # 在新窗口查看此物品
        if row_data and row_data.get("type_id"):
            tid = row_data["type_id"]
            view_action = menu.addAction(f"查看物品 {row_data.get('name', tid)}")
            view_action.triggered.connect(lambda _, t=tid: self._open_item_detail(t))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _copy_row(self, row_data: dict):
        """将选中行数据复制为制表符分隔文本"""
        if not row_data:
            return
        parts = []
        for _, _, key in self._model._cols:
            val = row_data.get(key)
            if val is None:
                parts.append("")
            else:
                parts.append(str(val))
        QApplication.clipboard().setText("\t".join(parts))
        self._status.setText("已复制行数据到剪贴板")

    def _copy_all_as_csv(self):
        """将整个对比结果复制为 CSV"""
        data = self._model.get_export_data()
        lines = [",".join(str(cell) for cell in row) for row in data]
        QApplication.clipboard().setText("\n".join(lines))
        self._status.setText(f"已复制 {len(data) - 1} 行数据到剪贴板")

    def _open_item_detail(self, type_id: int):
        """打开该物品的评分弹窗"""
        mode_index = self._mode_combo.currentIndex()
        mode = ["mfg", "trade", "reaction"][mode_index]
        if mode == "trade":
            from ui_pyside6.views.score_dialogs import TradeDlg

            cfg = {
                "hub": self._hub_combo.currentText(),
                "char": self._char_combo.currentText(),
                "tax": self._tax_spin.value(),
            }
            dlg = TradeDlg(cfg, parent=self)
            dlg.setWindowTitle(f"贸易评分 — {_item_name(type_id)}")
            dlg.exec()
        else:
            from ui_pyside6.views.score_dialogs import MfgDlg

            cfg = {
                "hub": self._hub_combo.currentText(),
                "char": self._char_combo.currentText(),
                "tax": self._tax_spin.value(),
            }
            dlg = MfgDlg(cfg, parent=self)
            dlg.setWindowTitle(f"制造评分 — {_item_name(type_id)}")
            dlg.exec()

    # ── 导出 ──

    def _on_export_csv(self):
        """导出为 CSV 文件"""
        if not self._results:
            self._status.setText("无数据可导出")
            return

        try:
            from PySide6.QtWidgets import QFileDialog

            path, _ = QFileDialog.getSaveFileName(
                self, "导出对比结果", "compare_result.csv", "CSV Files (*.csv);;All Files (*)"
            )
            if not path:
                return

            data = self._model.get_export_data()
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                for row in data:
                    writer.writerow(row)

            self._status.setText(f"已导出: {path}")
        except Exception as e:
            self._status.setText(f"导出失败: {e}")


# ═══════════════════════════════════════════
#  便捷入口函数
# ═══════════════════════════════════════════


def open_compare_dialog(
    parent=None,
    initial_items: list[dict] | None = None,
):
    """打开批量对比对话框"""
    dlg = CompareDialog(initial_items=initial_items, parent=parent)
    dlg.show()
    return dlg
