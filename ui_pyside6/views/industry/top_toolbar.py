"""Top toolbar for the industry plan view — blueprint import, price source, character & filter."""

from __future__ import annotations

import json
import os

from PySide6.QtCore import QStringListModel, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QCompleter,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QWidget,
)

import ui_pyside6.theme as theme
from core.paths import data_dir
from services import inventory_manager
from ui_pyside6.views.compare.compare_chart import search_items
from ui_pyside6.views.industry.flow_layout import FlowLayout
from ui_pyside6.views.industry.price_source_widget import DualPriceSourceWidget


class TopToolbar(QWidget):
    """水平工具栏：蓝图导入 | 材料/成品价格设置 | 筛选/操作"""

    plan_add_requested = Signal(str)
    manufacturable_browser_requested = Signal()
    hangar_changed = Signal(str)
    filter_changed = Signal(str)
    refresh_requested = Signal()
    view_changed = Signal(str)
    price_setting_changed = Signal()  # 任何价格设置变化

    HANGARS: list[dict] = []
    FILTERS = ["全部", "待排", "运行中", "待下线", "已完成"]

    # 搜索候选防抖延迟 (ms)
    _SEARCH_DEBOUNCE_MS = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()
        self._apply_style()
        theme.add_theme_listener(self._on_theme_changed)
        self._load_hangars()
        self._load_price_settings()

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self):
        root = FlowLayout(self, margin=6, h_spacing=8, v_spacing=6)
        root.setContentsMargins(6, 4, 6, 4)

        # ── 从全物品添加 ──
        self._btn_all_items = QPushButton("从全物品添加")
        root.addWidget(self._btn_all_items)

        root.addWidget(self._make_separator())

        # ── 蓝图输入区（含搜索候选） ──
        root.addWidget(QLabel("蓝图"))
        self._blueprint_input = QLineEdit()
        self._blueprint_input.setPlaceholderText("蓝图 粘贴板切导入")
        self._blueprint_input.setMinimumWidth(200)
        root.addWidget(self._blueprint_input)

        self._btn_add = QPushButton("添加")
        root.addWidget(self._btn_add)

        root.addWidget(self._make_separator())

        # ── 双行价格来源设置（材料 + 成品） ──
        self._price_widget = DualPriceSourceWidget()
        root.addWidget(self._price_widget)

        root.addWidget(self._make_separator())

        # ── 机库 ──
        root.addWidget(QLabel("机库"))
        self._hangar_combo = QComboBox()
        self._hangar_combo.setMinimumWidth(90)
        root.addWidget(self._hangar_combo)

        root.addWidget(self._make_separator())

        # ── 视图切换 + 筛选 + 刷新 ──
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
        self._filter_combo.setToolTip("按计划状态筛选")
        root.addWidget(self._filter_combo)

        self._btn_refresh = QPushButton("刷新")
        root.addWidget(self._btn_refresh)

    # ── 搜索候选（QCompleter + 防抖） ──────────────────────────

    def _setup_search_suggestions(self) -> None:
        """为蓝图输入框设置搜索候选自动补全。"""
        self._completer = QCompleter(self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setMaxVisibleItems(12)
        self._completer_model = QStringListModel()
        self._completer.setModel(self._completer_model)

        # 选中候选 → 提取物品名 → 触发添加
        self._completer.activated.connect(self._on_completer_activated)

        self._blueprint_input.setCompleter(self._completer)

        # 防抖搜索定时器
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search_suggestions)

        self._blueprint_input.textChanged.connect(self._on_search_text_changed)

    def _on_search_text_changed(self, text: str) -> None:
        """输入框文本变化 → 重启防抖定时器。"""
        text = text.strip()
        if not text:
            popup = self._completer.popup()
            if popup:
                popup.hide()
            self._completer_model.setStringList([])
            self._search_timer.stop()
            return
        # 少于 2 个字不搜索
        if len(text) < 2:
            popup = self._completer.popup()
            if popup:
                popup.hide()
            self._completer_model.setStringList([])
            self._search_timer.stop()
            return
        self._search_timer.start(self._SEARCH_DEBOUNCE_MS)

    def _do_search_suggestions(self) -> None:
        """执行搜索并更新候选列表。"""
        text = self._blueprint_input.text().strip()
        if not text or len(text) < 2:
            return
        items = search_items(text)
        if not items:
            popup = self._completer.popup()
            if popup:
                popup.hide()
            self._completer_model.setStringList([])
            return
        # 显示 "中文名 (EnglishName)" 格式
        suggestions = [f"{i['zh_name']} ({i['en_name']})" if i["zh_name"] else i["en_name"] for i in items]
        self._completer_model.setStringList(suggestions)
        # 主动触发候选弹出（QCompleter 不会自动弹出）
        self._completer.complete()

    def _on_completer_activated(self, text: str) -> None:
        """从搜索候选中选择 → 提取物品名 → 直接触发添加。"""
        # "中文名 (EnglishName)" → 取中文名；仅有英文名则直接取
        if " (" in text:
            text = text.split(" (")[0]
        elif "（" in text:
            text = text.split("（")[0]
        name = text.strip()
        if name:
            self._blueprint_input.setText(name)
            # 直接触发添加（选完候选自动添加，不用再点按钮）
            self._on_add()

    # ── 机库 / 设置加载 ─────────────────────────────────────

    def _load_hangars(self):
        try:
            hangars = inventory_manager.get_hangars()
            self._hangar_combo.clear()
            self._hangar_combo.addItem("不自动入库", -1)
            for h in hangars:
                self._hangar_combo.addItem(h["name"], h["id"])
            try:
                settings_path = os.path.join(data_dir(), "settings.json")
                if os.path.exists(settings_path):
                    with open(settings_path, encoding="utf-8") as f:
                        s = json.load(f)
                    saved_id = s.get("default_deposit_hangar_id")
                    if saved_id is not None:
                        idx = self._hangar_combo.findData(saved_id)
                        if idx >= 0:
                            self._hangar_combo.setCurrentIndex(idx)
            except Exception:
                pass
        except Exception:
            if self._hangar_combo.count() == 0:
                self._hangar_combo.addItem("不自动入库", -1)
        self._hangar_combo.currentIndexChanged.connect(self._save_hangar_setting)

    def _load_price_settings(self) -> None:
        """从 settings.json 恢复上次的价格设置。"""
        try:
            settings_path = os.path.join(data_dir(), "settings.json")
            if not os.path.exists(settings_path):
                return
            with open(settings_path, encoding="utf-8") as f:
                s = json.load(f)
            price_settings = s.get("price_settings")
            if price_settings:
                self._price_widget.set_settings(price_settings)
        except Exception:
            pass

    def _save_hangar_setting(self):
        hangar_id = self._hangar_combo.currentData()
        if hangar_id is None or hangar_id == -1:
            return
        try:
            settings_path = os.path.join(data_dir(), "settings.json")
            data = {}
            if os.path.exists(settings_path):
                with open(settings_path, encoding="utf-8") as f:
                    data = json.load(f)
            data["default_deposit_hangar_id"] = hangar_id
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _save_price_settings(self) -> None:
        """将当前价格设置持久化到 settings.json。"""
        try:
            settings_path = os.path.join(data_dir(), "settings.json")
            data = {}
            if os.path.exists(settings_path):
                with open(settings_path, encoding="utf-8") as f:
                    data = json.load(f)
            data["price_settings"] = self._price_widget.get_settings()
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_hangar_id(self) -> int | None:
        return self._hangar_combo.currentData() if self._hangar_combo.count() > 0 else None

    def _on_hangar_changed(self, hangar: str):
        self.hangar_changed.emit(hangar)

    def get_hangar(self) -> int:
        return self._hangar_combo.currentData() if self._hangar_combo.count() > 0 else -1  # type: ignore[no-any-return]

    def get_hangar_name(self) -> str:
        return self._hangar_combo.currentText() if self._hangar_combo.count() > 0 else ""  # type: ignore[no-any-return]

    def get_char_name(self) -> str:
        """返回默认角色名（人物选择已移除，固定返回 main）"""
        return "main"

    def get_price_settings(self) -> dict[str, str | float]:
        """返回当前材料/成品价格设置。"""
        return self._price_widget.get_settings()  # type: ignore[no-any-return]

    def _make_separator(self) -> QLabel:
        sep = QLabel("│")
        sep.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 14px; padding: 0 2px;")
        return sep

    # ── 信号连接 ──────────────────────────────────────────────

    def _connect_signals(self):
        self._btn_all_items.clicked.connect(self._on_all_items_clicked)
        self._btn_add.clicked.connect(self._on_add)
        self._filter_combo.currentTextChanged.connect(self.filter_changed)
        self._btn_refresh.clicked.connect(self.refresh_requested)
        self._view_data.toggled.connect(self._on_view_toggled)

        # 搜索候选
        self._setup_search_suggestions()

        # 价格设置变化 → 持久化 + 通知
        self._price_widget.mat_hub_changed.connect(self._on_price_setting_changed)
        self._price_widget.mat_price_type_changed.connect(self._on_price_setting_changed)
        self._price_widget.mat_mult_changed.connect(self._on_price_setting_changed)
        self._price_widget.prod_hub_changed.connect(self._on_price_setting_changed)
        self._price_widget.prod_price_type_changed.connect(self._on_price_setting_changed)
        self._price_widget.prod_mult_changed.connect(self._on_price_setting_changed)

    # ── 槽函数 ──────────────────────────────────────────────

    def _on_all_items_clicked(self):
        self.manufacturable_browser_requested.emit()

    def _on_add(self):
        text = self._blueprint_input.text().strip()
        if text:
            self.plan_add_requested.emit(text)
            self._blueprint_input.clear()
        else:
            QMessageBox.information(self, "提示", "请输入蓝图名称或粘贴蓝图信息")

    def get_filter(self) -> str:
        return self._filter_combo.currentText()  # type: ignore[no-any-return]

    def _on_price_setting_changed(self):
        """价格设置变化 → 持久化 + 通知外部。"""
        self._save_price_settings()
        self.price_setting_changed.emit()

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
            f"  selection-background-color: {theme.PRIMARY};"
            f"  outline: none; }}"
            f"QRadioButton {{ color: {theme.TEXT_SECONDARY}; background: transparent; font-size: 12px; spacing: 4px; }}"
            f"QRadioButton:hover {{ color: {theme.PRIMARY}; }}"
            f"QRadioButton:checked {{ color: {theme.TEXT_BRIGHT}; font-weight: bold; }}"
            f"QRadioButton::indicator {{ width: 14px; height: 14px; }}"
            f"QRadioButton::indicator:checked {{ background-color: {theme.PRIMARY}; border-radius: 7px; border: 2px solid {theme.PRIMARY}; }}"
            f"QRadioButton::indicator:unchecked {{ border: 2px solid {theme.BORDER}; border-radius: 7px; background: transparent; }}"
        )

    def _on_theme_changed(self):
        self._apply_style()
