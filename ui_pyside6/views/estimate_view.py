"""
估价页面 — 剪贴板粘贴 → Jita 价格查询 → 表格展示
"""

import os

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSize,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.paths import ICON_DIR
from services.scoring import get_price

ICON_SIZE = 32

# ── 表格列定义 ──
_COLUMNS = [
    ("图标", 50),
    ("名字", 160),
    ("数量", 70),
    ("单价", 110),
    ("卖价合计", 120),
    ("买价合计", 120),
    ("体积 m³", 80),
]

_SORT_KEYS = [None, "name", "qty", "unit_price", "sell_total", "buy_total", "volume"]


def _parse_clipboard(text: str) -> list[tuple[str, int, float]]:
    """解析 EVE 剪贴板格式，返回 [(物品名, 数量), ...]

    支持两种格式：
      Tab 分隔：物品名* \\t 数量 \\t 分组* \\t 体积 \\t 估价
      空格分隔：物品名*  数量  分组*  体积  估价
    物品名末尾的 * 会被自动去除。
    """
    results: list[tuple[str, int]] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # 判断分隔符：优先 Tab，其次多空格
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t") if p.strip()]
        else:
            # 空格分隔 — 按 2 个以上空格拆分（避免拆开物品名内部的单空格）
            import re

            parts = [p.strip() for p in re.split(r" {2,}", line) if p.strip()]

        if not parts:
            continue

        # 物品名：去掉末尾的 *（EVE 游戏中表示特殊品质/状态）
        name = parts[0].rstrip("*")

        # 数量：取第一个能解析为整数的字段
        qty = 1
        for p in parts[1:]:
            # 去掉末尾 * 和单位后缀
            token = p.rstrip("*").replace(",", "").replace(" ", "")
            # 跳过明显是体积或价格的字段（含 m3、星币、ISK）
            if any(kw in p.lower() for kw in ("m3", "m³", "星币", "isk", "m³")):
                continue
            try:
                qty = int(token)
                break
            except ValueError:
                continue
        # 体积：从含 m3/m³ 的字段中提取数字
        clip_vol = 0.0
        for p in parts[1:]:
            if "m3" in p.lower() or "m³" in p:
                vol_token = p.rstrip("*").replace("m3", "").replace("m³", "").replace(",", "").strip()
                try:
                    clip_vol = float(vol_token)
                except ValueError:
                    pass
                break

        results.append((name, qty, clip_vol))
    return results


def _search_item_by_name(name: str) -> dict | None:
    """按中文/英文名搜索物品，返回 {type_id, zh_name, en_name, iconID, volume} 或 None"""
    # 规范化引号 → 统一用 % 通配，兼容 ASCII/弯引号
    import re

    fuzzy_name = re.sub(r"[\"\"'']+", "%", name)
    with get_container().db.connect("ref") as conn:
        c = conn.cursor()
        # 精确匹配（原始名）
        c.execute(
            "SELECT type_id, zh_name, en_name, iconID, volume FROM item WHERE zh_name = ? OR en_name = ? LIMIT 1",
            (name, name),
        )
        row = c.fetchone()
        if row:
            return {"type_id": row[0], "zh_name": row[1], "en_name": row[2], "iconID": row[3], "volume": row[4] or 0}
        # 模糊匹配（原始名）
        c.execute(
            "SELECT type_id, zh_name, en_name, iconID, volume FROM item WHERE zh_name LIKE ? OR en_name LIKE ? LIMIT 1",
            (f"%{name}%", f"%{name}%"),
        )
        row = c.fetchone()
        if row:
            return {"type_id": row[0], "zh_name": row[1], "en_name": row[2], "iconID": row[3], "volume": row[4] or 0}
        # 引号归一化模糊匹配（引号 → % 通配符）
        if fuzzy_name != name:
            c.execute(
                "SELECT type_id, zh_name, en_name, iconID, volume FROM item"
                " WHERE zh_name LIKE ? OR en_name LIKE ? LIMIT 1",
                (f"%{fuzzy_name}%", f"%{fuzzy_name}%"),
            )
            row = c.fetchone()
            if row:
                return {
                    "type_id": row[0],
                    "zh_name": row[1],
                    "en_name": row[2],
                    "iconID": row[3],
                    "volume": row[4] or 0,
                }
    return None


# ═══════════════════════════════════════
#  Data model
# ═══════════════════════════════════════


class EstimateTableModel(QAbstractTableModel):
    """估价表格模型"""

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []
        self._sort_col: int = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._discount: float = 1.0

    def set_discount(self, discount: float):
        self._discount = discount
        if self._rows:
            self._recalc_totals()
            top_left = self.index(0, 3)
            bottom_right = self.index(len(self._rows) - 1, 6)
            self.dataChanged.emit(top_left, bottom_right)

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self._sort_col = -1
        self._recalc_totals()
        self.endResetModel()

    def _recalc_totals(self):
        for row in self._rows:
            sell_unit = row.get("sell_price", 0) or 0
            buy_unit = row.get("buy_price", 0) or 0
            qty = row.get("qty", 0)
            row["unit_price"] = sell_unit * self._discount  # 默认显示卖价
            row["sell_total"] = sell_unit * qty * self._discount
            row["buy_total"] = buy_unit * qty * self._discount
            row["volume"] = (row.get("_volume", 0) or 0) * qty

    def add_row(self, row_data: dict):
        idx = len(self._rows)
        self.beginInsertRows(QModelIndex(), idx, idx)
        self._rows.append(row_data)
        self._sort_col = -1
        self.endInsertRows()
        self._recalc_totals()
        top_left = self.index(idx, 0)
        bottom_right = self.index(idx, 6)
        self.dataChanged.emit(top_left, bottom_right)

    def remove_row(self, row_idx: int):
        if 0 <= row_idx < len(self._rows):
            self.beginRemoveRows(QModelIndex(), row_idx, row_idx)
            self._rows.pop(row_idx)
            self.endRemoveRows()

    def clear_all(self):
        self.beginResetModel()
        self._rows.clear()
        self._sort_col = -1
        self.endResetModel()

    def get_rows(self) -> list[dict]:
        return list(self._rows)

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(_COLUMNS)

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if index.column() == 2:  # 数量列可编辑
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != 2:
            return False
        if role == Qt.ItemDataRole.EditRole:
            try:
                qty = int(value)
                if qty <= 0:
                    return False
                self._rows[index.row()]["qty"] = qty
                self._recalc_totals()
                self.dataChanged.emit(index, self.index(index.row(), 6))
                return True
            except (ValueError, TypeError):
                return False
        return False

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._get_display(row, col)

        elif role == Qt.ItemDataRole.DecorationRole:
            if col == 0:
                type_id = row.get("type_id")
                if type_id:
                    icon_path = os.path.join(ICON_DIR, f"{type_id}.png")
                    if os.path.exists(icon_path):
                        pix = QPixmap(icon_path)
                        if not pix.isNull():
                            return pix.scaled(
                                32,
                                32,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
            return None

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (2, 3, 4, 5, 6):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 4:  # 卖价合计 → green
                return QColor(theme.GREEN)
            elif col == 5:  # 买价合计 → red
                return QColor(theme.RED)
            elif col == 3:  # 单价
                return QColor(theme.GREEN)

        elif role == Qt.ItemDataRole.UserRole:
            return row
        return None

    def _get_display(self, row: dict, col: int) -> str:
        if col == 0:
            return ""
        elif col == 1:
            return row.get("name", "?")
        elif col == 2:
            return f"{row.get('qty', 0):,}"
        elif col == 3:
            up = row.get("unit_price", 0) or 0
            return f"{up:,.2f}" if up else "---"
        elif col == 4:
            st = row.get("sell_total", 0) or 0
            return f"{st:,.2f}" if st else "---"
        elif col == 5:
            bt = row.get("buy_total", 0) or 0
            return f"{bt:,.2f}" if bt else "---"
        elif col == 6:
            vol = row.get("volume", 0) or 0
            return f"{vol:,.2f}" if vol else "---"
        return ""

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section < len(_COLUMNS):
                label = _COLUMNS[section][0]
                if section == self._sort_col:
                    arrow = " ↓" if self._sort_order == Qt.SortOrder.DescendingOrder else " ↑"
                    return label + arrow
                return label
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if column < 0 or column >= len(_SORT_KEYS):
            return
        key = _SORT_KEYS[column]
        if key is None:
            return
        self._sort_col = column
        self._sort_order = order
        reverse = order == Qt.SortOrder.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=lambda r: r.get(key, 0) or 0, reverse=reverse)
        self.layoutChanged.emit()


# ═══════════════════════════════════════
#  Clipboard parse worker
# ═══════════════════════════════════════


class ClipboardParseWorker(QThread):
    """后台解析剪贴板并查找物品/价格"""

    result_signal = Signal(list)  # list[dict] rows ready for table
    status_signal = Signal(str)  # status message

    def __init__(self, text: str, price_type: str, hub: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._price_type = price_type  # "sell" / "buy" / "avg"
        self._hub = hub

    def run(self):
        parsed = _parse_clipboard(self._text)
        if not parsed:
            self.status_signal.emit("剪贴板没有识别到有效物品")
            return

        total = len(parsed)
        rows = []
        for i, (name, qty, clip_vol) in enumerate(parsed):
            self.status_signal.emit(f"正在查找... ({i + 1}/{total})")
            item = _search_item_by_name(name)
            if item is None:
                rows.append(
                    {
                        "type_id": None,
                        "name": name,
                        "qty": qty,
                        "sell_price": 0,
                        "buy_price": 0,
                        "unit_price": 0,
                        "sell_total": 0,
                        "buy_total": 0,
                        "volume": 0,
                        "_volume": clip_vol,
                        "bp_me": 0,
                        "bp_te": 0,
                    }
                )
                continue

            display_name = item["zh_name"] or item["en_name"] or name
            sell_p = get_price(item["type_id"], "sell", self._hub) or 0
            buy_p = get_price(item["type_id"], "buy", self._hub) or 0
            item_vol = item["volume"]

            rows.append(
                {
                    "type_id": item["type_id"],
                    "name": display_name,
                    "qty": qty,
                    "sell_price": sell_p,
                    "buy_price": buy_p,
                    "unit_price": 0,
                    "sell_total": 0,
                    "buy_total": 0,
                    "volume": 0,
                    "_volume": item_vol,
                    "bp_me": 0,
                    "bp_te": 0,
                }
            )

        self.result_signal.emit(rows)
        self.status_signal.emit(f"完成 — 共 {len(rows)} 项")


# ═══════════════════════════════════════
#  Main page
# ═══════════════════════════════════════


class EstimatePage(QWidget):
    """估价页面"""

    def __init__(self, main_window=None):
        super().__init__()
        self._mw = main_window
        self._hub = "Jita"
        self._price_type = "sell"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── 行 1: 数据导入 ──
        r1 = self._build_import_bar()
        layout.addWidget(r1)

        # ── 行 2: 精炼占位 ──
        r2 = self._build_refine_bar()
        layout.addWidget(r2)

        # ── 表格 ──
        self._build_table()
        layout.addWidget(self._table, stretch=1)

        # ── 底部操作栏 ──
        r3 = self._build_bottom_bar()
        layout.addWidget(r3)

        # 模型数据变更 → 刷新底部汇总
        self._model.dataChanged.connect(lambda: self._refresh_summary())
        self._model.rowsRemoved.connect(lambda: self._refresh_summary())

        self._refresh_hangar_list()

        theme.add_theme_listener(self._on_theme_changed)

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式表"""
        self._vol_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._total_vol.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 18px; font-weight: bold;")
        self._sell_label.setText(f"<span style='color:{theme.TEXT_SECONDARY};font-size:10px;'>卖价合计</span>")
        self._sum_sell.setStyleSheet(f"color: {theme.GREEN}; font-size: 16px; font-weight: bold;")
        self._buy_label.setText(f"<span style='color:{theme.TEXT_SECONDARY};font-size:10px;'>买价合计</span>")
        self._sum_buy.setStyleSheet(f"color: {theme.RED}; font-size: 16px; font-weight: bold;")
        self._avg_label.setText(f"<span style='color:{theme.TEXT_SECONDARY};font-size:10px;'>买卖均价</span>")
        self._sum_avg.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 16px; font-weight: bold;")
        self._hangar_combo.setStyleSheet("QComboBox { font-weight: bold; }")

    def _build_import_bar(self) -> QWidget:
        w = QWidget()
        bar = QHBoxLayout(w)
        bar.setContentsMargins(8, 6, 8, 2)
        bar.setSpacing(8)

        # 价格取自
        bar.addWidget(QLabel("价格取自"))
        self._price_src = QComboBox()
        self._price_src.addItems(["卖价", "买价", "均价"])
        self._price_src.setCurrentText("卖价")
        self._price_src.currentIndexChanged.connect(self._on_price_src_changed)
        bar.addWidget(self._price_src)

        # 粘贴剪贴板
        self._paste_btn = QPushButton("粘贴剪贴板")
        self._paste_btn.setObjectName("paste_btn")
        self._paste_btn.clicked.connect(self._on_paste)
        bar.addWidget(self._paste_btn)

        # 怎么用
        self._help_btn = QPushButton("怎么用 ▾")
        self._help_btn.setFlat(True)
        self._help_btn.setToolTip("从游戏内复制物品列表（Ctrl+C）\n然后点击「粘贴剪贴板」即可自动估价")
        bar.addWidget(self._help_btn)

        # 地点
        bar.addWidget(QLabel("地点"))
        self._location = QComboBox()
        self._location.addItems(list(TRADE_HUB_IDS.keys()))
        self._location.setCurrentText("Jita")
        self._location.currentTextChanged.connect(self._on_location_changed)
        bar.addWidget(self._location)

        bar.addStretch()

        # 折扣系数
        bar.addWidget(QLabel("折扣"))
        self._discount = QDoubleSpinBox()
        self._discount.setRange(0.01, 10.0)
        self._discount.setValue(1.0)
        self._discount.setSingleStep(0.01)
        self._discount.setDecimals(2)
        self._discount.setFixedWidth(60)
        self._discount.valueChanged.connect(self._on_discount_changed)
        bar.addWidget(self._discount)

        # 搜索 + 添加
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索物品名称...")
        self._search_input.setFixedWidth(200)
        self._search_input.returnPressed.connect(self._on_add_item)
        bar.addWidget(self._search_input)

        self._add_btn = QPushButton("＋")
        self._add_btn.setFixedWidth(32)
        self._add_btn.setToolTip("添加物品到表格")
        self._add_btn.clicked.connect(self._on_add_item)
        bar.addWidget(self._add_btn)

        return w

    def _build_refine_bar(self) -> QWidget:
        w = QWidget()
        bar = QHBoxLayout(w)
        bar.setContentsMargins(8, 2, 8, 2)
        bar.setSpacing(8)

        self._refine_btn = QPushButton("一键精炼")
        self._refine_btn.setEnabled(False)
        self._refine_btn.setToolTip("即将支持")
        bar.addWidget(self._refine_btn)

        self._char_fac_tabs = QComboBox()
        self._char_fac_tabs.addItems(["人物", "设施"])
        self._char_fac_tabs.setEnabled(False)
        bar.addWidget(QLabel("模式"))
        bar.addWidget(self._char_fac_tabs)

        self._skill_preset = QComboBox()
        self._skill_preset.addItem("技能全5")
        self._skill_preset.setEnabled(False)
        bar.addWidget(QLabel("技能"))
        bar.addWidget(self._skill_preset)

        self._gas_rate = QLineEdit("0")
        self._gas_rate.setFixedWidth(50)
        self._gas_rate.setEnabled(False)
        bar.addWidget(QLabel("气云解压率(%)"))
        bar.addWidget(self._gas_rate)

        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self._on_refresh_prices)
        bar.addWidget(self._refresh_btn)

        self._residual_chk = QCheckBox("残余也精炼掉")
        self._residual_chk.setEnabled(False)
        bar.addWidget(self._residual_chk)

        bar.addStretch()
        return w

    def _build_table(self):
        self._model = EstimateTableModel()
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setSortingEnabled(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setDefaultSectionSize(36)
        self._table.setIconSize(QSize(32, 32))

        for i, (_, width) in enumerate(_COLUMNS):
            self._table.setColumnWidth(i, width)

    def _build_bottom_bar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("estimate_bottom")
        bar = QHBoxLayout(w)
        bar.setContentsMargins(12, 8, 12, 8)
        bar.setSpacing(16)

        # ── 左侧：体积 ──
        vol_w = QWidget()
        vol_lay = QVBoxLayout(vol_w)
        vol_lay.setContentsMargins(0, 0, 0, 0)
        vol_lay.setSpacing(2)
        self._vol_label = QLabel("体积（精炼前）")
        self._vol_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._total_vol = QLabel("—")
        self._total_vol.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 18px; font-weight: bold;")
        vol_lay.addWidget(self._vol_label)
        vol_lay.addWidget(self._total_vol)
        bar.addWidget(vol_w)

        bar.addStretch()

        # ── 中间：价格汇总（大字，3行） ──
        price_w = QWidget()
        price_lay = QVBoxLayout(price_w)
        price_lay.setContentsMargins(0, 0, 0, 0)
        price_lay.setSpacing(2)

        self._sum_sell = QLabel("—")
        self._sum_sell.setStyleSheet(f"color: {theme.GREEN}; font-size: 16px; font-weight: bold;")
        self._sum_buy = QLabel("—")
        self._sum_buy.setStyleSheet(f"color: {theme.RED}; font-size: 16px; font-weight: bold;")
        self._sum_avg = QLabel("—")
        self._sum_avg.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 16px; font-weight: bold;")

        self._sell_label = QLabel(f"<span style='color:{theme.TEXT_SECONDARY};font-size:10px;'>卖价合计</span>")
        self._buy_label = QLabel(f"<span style='color:{theme.TEXT_SECONDARY};font-size:10px;'>买价合计</span>")
        self._avg_label = QLabel(f"<span style='color:{theme.TEXT_SECONDARY};font-size:10px;'>买卖均价</span>")
        price_lay.addWidget(self._sell_label)
        price_lay.addWidget(self._sum_sell)
        price_lay.addWidget(self._buy_label)
        price_lay.addWidget(self._sum_buy)
        price_lay.addWidget(self._avg_label)
        price_lay.addWidget(self._sum_avg)

        bar.addWidget(price_w)

        bar.addStretch()

        # ── 右侧：操作按钮 ──
        btn_w = QWidget()
        btn_lay = QVBoxLayout(btn_w)
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(4)

        self._copy_sell_btn = QPushButton("卖价到剪贴板")
        self._copy_sell_btn.clicked.connect(lambda: self._copy_to_clipboard("sell"))
        btn_lay.addWidget(self._copy_sell_btn)

        self._copy_buy_btn = QPushButton("买价到剪贴板")
        self._copy_buy_btn.clicked.connect(lambda: self._copy_to_clipboard("buy"))
        btn_lay.addWidget(self._copy_buy_btn)

        hangar_row = QHBoxLayout()
        hangar_row.addWidget(QLabel("机库"))
        self._to_hangar_btn = QPushButton("添加到机库")
        self._to_hangar_btn.clicked.connect(self._on_add_to_hangar)
        hangar_row.addWidget(self._to_hangar_btn)
        self._hangar_combo = QComboBox()
        self._hangar_combo.setFixedWidth(120)
        self._hangar_combo.setToolTip("选择目标机库")
        self._hangar_combo.setStyleSheet("QComboBox { font-weight: bold; }")
        hangar_row.addWidget(self._hangar_combo)
        btn_lay.addLayout(hangar_row)

        self._update_prices_btn = QPushButton("更新价格")
        self._update_prices_btn.clicked.connect(self._on_refresh_prices)
        btn_lay.addWidget(self._update_prices_btn)

        bar.addWidget(btn_w)

        return w

    def _refresh_summary(self):
        """刷新底部汇总：总体积、卖价合计、买价合计、均价合计"""
        rows = self._model._rows
        total_vol = sum(r.get("volume", 0) or 0 for r in rows)
        total_sell = sum(r.get("sell_total", 0) or 0 for r in rows)
        total_buy = sum(r.get("buy_total", 0) or 0 for r in rows)
        total_avg = (total_sell + total_buy) / 2 if (total_sell or total_buy) else 0

        self._total_vol.setText(f"{total_vol:,.1f} m³")
        self._sum_sell.setText(f"{total_sell:,.0f} ISK")
        self._sum_buy.setText(f"{total_buy:,.0f} ISK")
        self._sum_avg.setText(f"{total_avg:,.0f} ISK")

    # ── signals ──

    def _on_paste(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if not text.strip():
            self._set_status("剪贴板为空")
            return

        self._paste_btn.setEnabled(False)
        self._set_status("正在解析剪贴板...")
        self._worker = ClipboardParseWorker(text, self._price_type, self._hub, self)
        self._worker.result_signal.connect(self._on_parse_done)
        self._worker.status_signal.connect(self._set_status)
        self._worker.finished.connect(lambda: self._paste_btn.setEnabled(True))
        self._worker.start()

    def _on_parse_done(self, rows: list[dict]):
        self._model.set_rows(rows)
        self._model.set_discount(self._discount.value())
        self._rebuild_unit_prices()
        self._refresh_summary()

    def _on_add_item(self):
        name = self._search_input.text().strip()
        if not name:
            return
        item = _search_item_by_name(name)
        if item is None:
            self._set_status(f"未找到物品: {name}")
            return

        display_name = item["zh_name"] or item["en_name"] or name
        sell_p = get_price(item["type_id"], "sell", self._hub) or 0
        buy_p = get_price(item["type_id"], "buy", self._hub) or 0

        self._model.add_row(
            {
                "type_id": item["type_id"],
                "name": display_name,
                "qty": 1,
                "sell_price": sell_p,
                "buy_price": buy_p,
                "unit_price": 0,
                "sell_total": 0,
                "buy_total": 0,
                "volume": 0,
                "_volume": item["volume"],
                "bp_me": 0,
                "bp_te": 0,
            }
        )
        self._model.set_discount(self._discount.value())
        self._search_input.clear()
        self._set_status(f"已添加: {display_name}")
        self._refresh_summary()

    def _on_price_src_changed(self, idx: int):
        mapping = {0: "sell", 1: "buy", 2: "avg"}
        self._price_type = mapping.get(idx, "sell")
        self._rebuild_unit_prices()

    def _rebuild_unit_prices(self):
        """切换价格类型时更新单价列"""
        rows = self._model._rows
        for row in rows:
            if self._price_type == "sell":
                row["unit_price"] = (row.get("sell_price", 0) or 0) * self._discount.value()
            elif self._price_type == "buy":
                row["unit_price"] = (row.get("buy_price", 0) or 0) * self._discount.value()
            else:  # avg
                sp = row.get("sell_price", 0) or 0
                bp = row.get("buy_price", 0) or 0
                row["unit_price"] = ((sp + bp) / 2) * self._discount.value() if (sp or bp) else 0
        if rows:
            top_left = self._model.index(0, 3)
            bottom_right = self._model.index(len(rows) - 1, 3)
            self._model.dataChanged.emit(top_left, bottom_right)

    def _on_location_changed(self, hub: str):
        self._hub = hub
        self._on_refresh_prices()

    def _on_discount_changed(self, val: float):
        self._model.set_discount(val)
        self._rebuild_unit_prices()
        self._refresh_summary()

    def _on_refresh_prices(self):
        rows = self._model._rows
        if not rows:
            return
        self._set_status("正在刷新价格...")
        for i, row in enumerate(rows):
            tid = row.get("type_id")
            if not tid:
                continue
            sell_p = get_price(tid, "sell", self._hub) or 0
            buy_p = get_price(tid, "buy", self._hub) or 0
            row["sell_price"] = sell_p
            row["buy_price"] = buy_p
        self._model.set_discount(self._discount.value())
        self._rebuild_unit_prices()
        if rows:
            top_left = self._model.index(0, 0)
            bottom_right = self._model.index(len(rows) - 1, 6)
            self._model.dataChanged.emit(top_left, bottom_right)
        self._set_status("价格已刷新")
        self._refresh_summary()

    def _on_context_menu(self, pos):
        idx = self._table.indexAt(pos)
        menu = QMenu(self)

        if idx.isValid():
            # 用 UserRole 获取行 dict（排序后 row index 不可靠）
            row = idx.data(Qt.ItemDataRole.UserRole)
            if row is not None:
                name = row.get("name", "?")

                copy_name = menu.addAction(f"复制名称: {name}")
                copy_name.triggered.connect(lambda r=row: self._copy_text(r.get("name", "?")))

                tid = row.get("type_id")
                if tid:
                    copy_tid = menu.addAction(f"复制 Type ID: {tid}")
                    copy_tid.triggered.connect(lambda t=tid: self._copy_text(str(t)))

                menu.addSeparator()

                edit_qty = menu.addAction("修改数量")
                edit_qty.triggered.connect(lambda r=row: self._on_edit_qty(r))

                multiply_qty = menu.addAction("数量翻倍")
                multiply_qty.triggered.connect(lambda r=row: self._on_multiply_qty(r))

                bp_edit = menu.addAction("修改蓝图")
                bp_edit.triggered.connect(lambda r=row: self._on_edit_blueprint(r))

                menu.addSeparator()

                del_row = menu.addAction("删除条目")
                del_row.triggered.connect(lambda r=row: self._remove_row(r))

        clear_all = menu.addAction("清空表格")
        clear_all.triggered.connect(self._model.clear_all)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _row_index(self, row: dict) -> int | None:
        try:
            return self._model._rows.index(row)
        except ValueError:
            return None

    def _remove_row(self, row: dict):
        ri = self._row_index(row)
        if ri is not None:
            self._model.remove_row(ri)
        self._refresh_summary()

    def _on_edit_qty(self, row: dict):
        qty, ok = QInputDialog.getInt(
            self,
            "修改数量",
            f"{row.get('name', '?')} 的数量:",
            value=row.get("qty", 1),
            minValue=1,
            maxValue=999999999,
        )
        if ok:
            row["qty"] = qty
            self._model._recalc_totals()
            self._rebuild_unit_prices()
            self._refresh_summary()
            ri = self._row_index(row)
            if ri is not None:
                self._model.dataChanged.emit(self._model.index(ri, 2), self._model.index(ri, 6))

    def _on_multiply_qty(self, row: dict):
        factor, ok = QInputDialog.getDouble(
            self,
            "数量翻倍",
            f"将 {row.get('name', '?')} 数量乘以:",
            value=2.0,
            minValue=0.01,
            maxValue=1000000.0,
            decimals=2,
        )
        if ok:
            row["qty"] = max(1, round(row.get("qty", 1) * factor))
            self._model._recalc_totals()
            self._rebuild_unit_prices()
            self._refresh_summary()
            ri = self._row_index(row)
            if ri is not None:
                self._model.dataChanged.emit(self._model.index(ri, 2), self._model.index(ri, 6))

    def _on_edit_blueprint(self, row: dict):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"蓝图属性 — {row.get('name', '?')}")
        dlg.setMinimumWidth(280)
        form = QFormLayout(dlg)

        me = QSpinBox()
        me.setRange(0, 10)
        me.setValue(row.get("bp_me", 0))
        form.addRow("材料效率 (ME):", me)

        te = QSpinBox()
        te.setRange(0, 20)
        te.setValue(row.get("bp_te", 0))
        form.addRow("时间效率 (TE):", te)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            row["bp_me"] = me.value()
            row["bp_te"] = te.value()
            self._set_status(f"蓝图: ME={me.value()} TE={te.value()}")

    def _copy_to_clipboard(self, mode: str = "sell"):
        """复制总价到剪贴板（纯数字，无单位）"""
        total = sum(r.get("sell_total" if mode == "sell" else "buy_total", 0) or 0 for r in self._model._rows)
        QApplication.clipboard().setText(f"{total:,.0f}")
        label = "卖价" if mode == "sell" else "买价"
        self._set_status(f"已复制总{label} {total:,.0f} ISK 到剪贴板")

    def _refresh_hangar_list(self):
        from services.inventory_manager import create_hangar, get_hangars

        hangars = get_hangars()
        if not hangars:
            create_hangar("默认机库")
            hangars = get_hangars()
        self._hangar_combo.clear()
        for h in hangars:
            self._hangar_combo.addItem(h["name"], h["id"])

    def _on_add_to_hangar(self):
        """将表格物品添加到选中机库"""
        hid = self._hangar_combo.currentData()
        if not hid:
            self._set_status("请先选择机库")
            return

        from services.inventory_manager import add_item

        count = 0
        for row in self._model._rows:
            tid = row.get("type_id")
            if not tid:
                continue
            qty = row.get("qty", 0)
            cost = (row.get("buy_price", 0) or 0) * self._discount.value()
            if qty > 0:
                add_item(hid, tid, qty, cost)
                count += 1

        name = self._hangar_combo.currentText()
        self._set_status(f"已添加 {count} 种物品到「{name}」")

    def _copy_text(self, text: str):
        QApplication.clipboard().setText(text)

    def _set_status(self, msg: str):
        if self._mw and hasattr(self._mw, "_status_label"):
            self._mw._status_label.setText(msg)
