"""Top toolbar for the industry plan view — blueprint import, hub/pricing, character & filter."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QWidget,
)

import ui_pyside6.theme as theme
from ui_pyside6.views.char_settings_view import get_character_list, load_all_data
from ui_pyside6.views.industry.flow_layout import FlowLayout


class TopToolbar(QWidget):
    """水平工具栏：蓝图导入 | Hub/倍率 | 人物/筛选/操作"""

    plan_add_requested = Signal(str)
    batch_add_requested = Signal()
    manufacturable_browser_requested = Signal()
    hub_changed = Signal(str)
    hangar_changed = Signal(str)
    sell_mult_changed = Signal(float)
    buy_mult_changed = Signal(float)
    char_changed = Signal(str)
    filter_changed = Signal(str)
    refresh_requested = Signal()
    view_changed = Signal(str)

    HUBS = ["Jita", "Amarr", "Dodixie", "Rens", "Hek"]
    HUB_DISPLAY = {"Jita": "价格取自（吉他）", "Amarr": "价格取自（艾玛）",
                   "Dodixie": "价格取自（多迪）", "Rens": "价格取自（伦斯）",
                   "Hek": "价格取自（赫克）"}
    HANGARS = ["物品机库", "公司机库1", "公司机库2", "公司机库3",
               "公司机库4", "公司机库5", "公司机库6", "公司机库7"]
    CHARS = []  # 从角色设置加载
    _chars_loaded = False
    FILTERS = ["全部", "待排", "运行中", "已完成"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()
        self._apply_style()
        theme.add_theme_listener(self._on_theme_changed)
        self._load_chars()

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self):
        root = FlowLayout(self, margin=6, h_spacing=8, v_spacing=6)
        root.setContentsMargins(6, 4, 6, 4)

        # ── 左侧：从全物品添加 ──
        self._btn_all_items = QPushButton("从全物品添加")
        root.addWidget(self._btn_all_items)

        root.addWidget(self._make_separator())

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
        self._hub_combo.addItems(self.HUBS_DISPLAY_LIST())
        self._hub_combo.setMinimumWidth(130)
        root.addWidget(self._hub_combo)

        root.addWidget(QLabel("机库"))
        self._hangar_combo = QComboBox()
        self._hangar_combo.addItems(self.HANGARS)
        self._hangar_combo.setMinimumWidth(90)
        root.addWidget(self._hangar_combo)

        root.addWidget(QLabel("卖出倍率"))
        self._sell_mult = QDoubleSpinBox()
        self._sell_mult.setRange(0.1, 10.0)
        self._sell_mult.setSingleStep(0.05)
        self._sell_mult.setValue(1.00)
        self._sell_mult.setDecimals(2)
        self._sell_mult.setFixedWidth(90)
        root.addWidget(self._sell_mult)

        root.addWidget(QLabel("买入倍率"))
        self._buy_mult = QDoubleSpinBox()
        self._buy_mult.setRange(0.1, 10.0)
        self._buy_mult.setSingleStep(0.05)
        self._buy_mult.setValue(1.00)
        self._buy_mult.setDecimals(2)
        self._buy_mult.setFixedWidth(90)
        root.addWidget(self._buy_mult)

        root.addWidget(self._make_separator())

        # ── 右侧：人物 + 视图切换 + 筛选 + 操作 ──
        root.addWidget(QLabel("人物"))
        self._char_combo = QComboBox()
        self._char_combo.addItems(self.CHARS)
        self._char_combo.setMinimumWidth(130)
        root.addWidget(self._char_combo)

        root.addWidget(self._make_separator())

        # ── 视图切换：数据/甘特 ──
        root.addWidget(QLabel("视图:"))
        self._view_data = QRadioButton("数据视图")
        self._view_data.setChecked(True)
        self._view_gantt = QRadioButton("甘特图")
        self._view_group = QButtonGroup(self)
        self._view_group.addButton(self._view_data)
        self._view_group.addButton(self._view_gantt)
        root.addWidget(self._view_data)
        root.addWidget(self._view_gantt)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(self.FILTERS)
        self._filter_combo.setMinimumWidth(80)
        root.addWidget(self._filter_combo)

        self._btn_refresh = QPushButton("刷新")
        root.addWidget(self._btn_refresh)

    def _load_chars(self):
        """从角色设置加载人物列表"""
        try:
            chars = get_character_list()
            if not chars:
                chars = ["main"]
            self._char_combo.clear()
            self._char_combo.addItems(chars)
            top_level = load_all_data().get("current", chars[0])
            idx = self._char_combo.findText(top_level)
            if idx >= 0:
                self._char_combo.setCurrentIndex(idx)
        except Exception:
            # fallback
            if self._char_combo.count() == 0:
                self._char_combo.addItems(["main"])

    def _on_hangar_changed(self, hangar: str):
        self.hangar_changed.emit(hangar)

    def get_hangar(self) -> str:
        return self._hangar_combo.currentText()

    def get_char_name(self) -> str:
        return self._char_combo.currentText()

    def get_hub_name(self) -> str:
        """返回 Hub 英文名（内部使用）"""
        display = self._hub_combo.currentText()
        # 逆查映射
        for eng, disp in self.HUB_DISPLAY.items():
            if disp == display:
                return eng
        return display

    @classmethod
    def HUBS_DISPLAY_LIST(cls) -> list[str]:
        return list(cls.HUB_DISPLAY.values())

    def _make_separator(self) -> QLabel:
        sep = QLabel("│")
        sep.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 14px; padding: 0 2px;")
        return sep

    # ── 信号连接 ──────────────────────────────────────────────

    def _connect_signals(self):
        self._btn_all_items.clicked.connect(self._on_all_items_clicked)
        self._btn_add.clicked.connect(self._on_add)
        self._btn_from_list.clicked.connect(self._on_batch_clicked)
        self._hub_combo.currentTextChanged.connect(self._on_hub_changed)
        self._hangar_combo.currentTextChanged.connect(self.hangar_changed)
        self._sell_mult.valueChanged.connect(self.sell_mult_changed)
        self._buy_mult.valueChanged.connect(self.buy_mult_changed)
        self._char_combo.currentTextChanged.connect(self.char_changed)
        self._filter_combo.currentTextChanged.connect(self.filter_changed)
        self._btn_refresh.clicked.connect(self.refresh_requested)
        self._view_data.toggled.connect(self._on_view_toggled)

    # ── 槽函数 ──────────────────────────────────────────────

    def _on_hub_changed(self, display_text: str):
        """将中文 Hub 名转回英文后发射信号"""
        for eng, disp in self.HUB_DISPLAY.items():
            if disp == display_text:
                self.hub_changed.emit(eng)
                return
        self.hub_changed.emit(display_text)

    def _on_all_items_clicked(self):
        """从全物品列表中选择可制造物品"""
        self.manufacturable_browser_requested.emit()

    def _on_add(self):
        """读取粘贴板/输入框文本，有内容则发射信号并清空，否则提示"""
        text = self._blueprint_input.text().strip()
        if text:
            self.plan_add_requested.emit(text)
            self._blueprint_input.clear()
        else:
            QMessageBox.information(self, "提示", "请输入蓝图名称或粘贴蓝图信息")

    def _on_batch_clicked(self):
        """从蓝图列表批量导入"""
        self.batch_add_requested.emit()

    def get_filter(self) -> str:
        return self._filter_combo.currentText()

    def _on_view_toggled(self, checked: bool):
        if checked:
            self.view_changed.emit("data")
        else:
            self.view_changed.emit("gantt")

    # ── 样式 ──────────────────────────────────────────────────

    def _apply_style(self):
        self.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_PRIMARY}; background: transparent; font-size: 12px; }}"
            f"QPushButton {{ padding: 4px 10px; border: 1px solid {theme.BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {theme.TEXT_PRIMARY}; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {theme.PRIMARY}; color: {theme.PRIMARY}; }}"
            f"QLineEdit {{ padding: 4px 8px; border: 1px solid {theme.BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {theme.TEXT_PRIMARY}; font-size: 12px; }}"
            f"QComboBox {{ padding: 4px 8px; border: 1px solid {theme.BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {theme.TEXT_PRIMARY}; font-size: 12px; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f"  border: 1px solid {theme.BORDER}; border-radius: 4px;"
            f"  selection-background-color: {theme.BG_SURFACE_LIGHT};"
            f"  outline: none; }}"
            f"QDoubleSpinBox {{ padding: 4px 6px; border: 1px solid {theme.BORDER}; border-radius: 4px;"
            f"  background: transparent; color: {theme.TEXT_PRIMARY}; font-size: 12px; }}"
            f"QDoubleSpinBox::up-button {{ width: 14px; border: none;"
            f"  background: transparent; subcontrol-position: top right; }}"
            f"QDoubleSpinBox::down-button {{ width: 14px; border: none;"
            f"  background: transparent; subcontrol-position: bottom right; }}"
            f"QRadioButton {{ color: {theme.TEXT_PRIMARY}; background: transparent; font-size: 12px; }}"
            f"QRadioButton::indicator {{ width: 14px; height: 14px; }}"
        )

    def _on_theme_changed(self):
        self._apply_style()
