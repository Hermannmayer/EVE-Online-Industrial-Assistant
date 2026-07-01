"""Top toolbar for the industry plan view — blueprint import, hub/pricing, character & filter."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from ui_pyside6.theme import (
    BORDER,
    PRIMARY,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    add_theme_listener,
)


class TopToolbar(QWidget):
    """水平工具栏：蓝图导入 | Hub/倍率 | 人物/筛选/操作"""

    plan_add_requested = Signal(str)
    batch_add_requested = Signal()
    hub_changed = Signal(str)
    sell_mult_changed = Signal(float)
    buy_mult_changed = Signal(float)
    char_changed = Signal(str)
    filter_changed = Signal(str)
    refresh_requested = Signal()

    HUBS = ["Jita", "Amarr", "Dodixie", "Rens", "Hek"]
    CHARS = ["main(技能全5)", "alt(技能全4)", "自定义"]
    FILTERS = ["全部", "待排", "运行中", "已完成"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()
        self._apply_style()
        add_theme_listener(self._on_theme_changed)

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(8)

        # ── 左侧：蓝图导入区 ──
        root.addWidget(QLabel("蓝图"))
        self._blueprint_input = QLineEdit()
        self._blueprint_input.setPlaceholderText("蓝图 粘贴板切导入")
        self._blueprint_input.setMinimumWidth(200)
        root.addWidget(self._blueprint_input)

        self._btn_add = QPushButton("添加")
        root.addWidget(self._btn_add)

        self._btn_from_list = QPushButton("+ 从蓝图列表")
        root.addWidget(self._btn_from_list)

        root.addWidget(self._make_separator())

        # ── 中间：材料/价格设置区 ──
        root.addWidget(QLabel("Hub"))
        self._hub_combo = QComboBox()
        self._hub_combo.addItems(self.HUBS)
        self._hub_combo.setMinimumWidth(90)
        root.addWidget(self._hub_combo)

        root.addWidget(QLabel("卖出倍率"))
        self._sell_mult = QDoubleSpinBox()
        self._sell_mult.setRange(0.1, 10.0)
        self._sell_mult.setSingleStep(0.05)
        self._sell_mult.setValue(1.00)
        self._sell_mult.setDecimals(2)
        self._sell_mult.setFixedWidth(70)
        root.addWidget(self._sell_mult)

        root.addWidget(QLabel("买入倍率"))
        self._buy_mult = QDoubleSpinBox()
        self._buy_mult.setRange(0.1, 10.0)
        self._buy_mult.setSingleStep(0.05)
        self._buy_mult.setValue(1.00)
        self._buy_mult.setDecimals(2)
        self._buy_mult.setFixedWidth(70)
        root.addWidget(self._buy_mult)

        root.addWidget(self._make_separator())

        # ── 右侧：人物 + 筛选 + 操作 ──
        root.addWidget(QLabel("人物"))
        self._char_combo = QComboBox()
        self._char_combo.addItems(self.CHARS)
        self._char_combo.setMinimumWidth(130)
        root.addWidget(self._char_combo)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(self.FILTERS)
        self._filter_combo.setMinimumWidth(80)
        root.addWidget(self._filter_combo)

        self._btn_optimize = QPushButton("预默认/小部节接")
        root.addWidget(self._btn_optimize)

        self._btn_refresh = QPushButton("刷新")
        root.addWidget(self._btn_refresh)

        root.addStretch(1)

    def _make_separator(self) -> QLabel:
        sep = QLabel("│")
        sep.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px; padding: 0 2px;")
        return sep

    # ── 信号连接 ──────────────────────────────────────────────

    def _connect_signals(self):
        self._btn_add.clicked.connect(self._on_add)
        self._btn_from_list.clicked.connect(self.batch_add_requested)
        self._hub_combo.currentTextChanged.connect(self.hub_changed)
        self._sell_mult.valueChanged.connect(self.sell_mult_changed)
        self._buy_mult.valueChanged.connect(self.buy_mult_changed)
        self._char_combo.currentTextChanged.connect(self.char_changed)
        self._filter_combo.currentTextChanged.connect(self.filter_changed)
        self._btn_refresh.clicked.connect(self.refresh_requested)
        self._btn_optimize.clicked.connect(self._on_optimize)

    # ── 槽函数 ──────────────────────────────────────────────

    def _on_add(self):
        text = self._blueprint_input.text().strip()
        if text:
            self.plan_add_requested.emit(text)
            self._blueprint_input.clear()

    def _on_optimize(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "功能开发中")

    # ── 样式 ──────────────────────────────────────────────────

    def _apply_style(self):
        self.setStyleSheet(
            f"QLabel {{ color: {TEXT_PRIMARY}; background: transparent; font-size: 12px; }}"
            f"QPushButton {{ padding: 4px 10px; border: 1px solid {BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {TEXT_PRIMARY}; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}"
            f"QLineEdit {{ padding: 4px 8px; border: 1px solid {BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {TEXT_PRIMARY}; font-size: 12px; }}"
            f"QComboBox {{ padding: 4px 8px; border: 1px solid {BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {TEXT_PRIMARY}; font-size: 12px; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox QAbstractItemView {{ background: transparent; color: {TEXT_PRIMARY}; }}"
            f"QDoubleSpinBox {{ padding: 4px 6px; border: 1px solid {BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {TEXT_PRIMARY}; font-size: 12px; }}"
        )

    def _on_theme_changed(self):
        self._apply_style()
