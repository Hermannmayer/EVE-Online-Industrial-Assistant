"""
设置对话框 — ESI 与数据 · 外观 · 默认参数 三个标签页

用法:
    from ui_pyside6.views.settings_view import SettingsDialog
    dlg = SettingsDialog(main_window)
    dlg.exec()
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.icons as icons
import ui_pyside6.theme as theme
from ui_pyside6.views.theme_selector import ThemeSelector


class SettingsDialog(QDialog):
    """系统设置对话框（3 标签页）"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self._mw = main_window
        self.setWindowTitle("系统设置")
        self.setMinimumSize(560, 520)
        self.setObjectName("settings_dialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 标签页 ──
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_esi_tab(), "ESI 与数据")
        self._tabs.addTab(self._build_appearance_tab(), "外观")
        self._tabs.addTab(self._build_defaults_tab(), "默认参数")
        layout.addWidget(self._tabs)

        # ── 按钮 ──
        btn_bar = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        btn_bar.accepted.connect(self._on_save)
        btn_bar.rejected.connect(self.reject)
        btn_bar.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._on_apply)
        layout.addWidget(btn_bar)

        # 读取当前设置
        self._load_state()

    # ═══════════════════════════════════════════
    #  标签页 1: ESI 与数据
    # ═══════════════════════════════════════════

    def _build_esi_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        # 更新间隔
        interval_group = QGroupBox("价格更新")
        ig = QFormLayout(interval_group)
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(0, 1440)
        self._interval_spin.setSingleStep(5)
        self._interval_spin.setSuffix(" 分钟")
        self._interval_spin.setSpecialValueText("关闭")
        ig.addRow("更新间隔:", self._interval_spin)

        self._auto_update_cb = QCheckBox("启用自动更新")
        ig.addRow("", self._auto_update_cb)
        layout.addWidget(interval_group)

        layout.addStretch()
        return w

    # ═══════════════════════════════════════════
    #  标签页 2: 外观
    # ═══════════════════════════════════════════

    def _build_appearance_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        # 主题
        theme_group = QGroupBox("主题")
        tg = QVBoxLayout(theme_group)
        self._theme_selector = ThemeSelector()
        tg.addWidget(self._theme_selector)
        layout.addWidget(theme_group)

        # 字体
        font_group = QGroupBox("字体大小")
        fg = QFormLayout(font_group)
        self._font_size = QSpinBox()
        self._font_size.setRange(10, 20)
        self._font_size.setValue(13)
        fg.addRow("全局字号:", self._font_size)
        layout.addWidget(font_group)

        layout.addStretch()
        return w

    # ═══════════════════════════════════════════
    #  标签页 3: 默认参数
    # ═══════════════════════════════════════════

    def _build_defaults_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        # 工具
        tool_group = QGroupBox("工具")
        tgl = QVBoxLayout(tool_group)
        init_btn = QPushButton()
        icons.set_button_icon(init_btn, "package", text="数据初始化")
        init_btn.clicked.connect(self._on_init)
        tgl.addWidget(init_btn)
        about_btn = QPushButton()
        icons.set_button_icon(about_btn, "info", text="关于")
        about_btn.clicked.connect(self._on_about)
        tgl.addWidget(about_btn)
        layout.addWidget(tool_group)

        layout.addStretch()
        return w

    # ═══════════════════════════════════════════
    #  加载/保存
    # ═══════════════════════════════════════════

    def _load_state(self):
        """从 main_window 读取当前设置"""
        if not self._mw:
            return

        interval = getattr(self._mw, "_update_interval_minutes", 0)
        self._interval_spin.setValue(interval)

        auto = getattr(self._mw, "_auto_update_enabled", False)
        self._auto_update_cb.setChecked(auto)

        self._theme_selector.set_current(theme.current_theme())

    def _on_save(self):
        """保存并关闭"""
        self._on_apply()
        self.accept()

    def _on_apply(self):
        """应用设置（不关闭）"""
        if not self._mw:
            return

        # 更新间隔
        if hasattr(self._mw, "_update_interval_minutes"):
            self._mw._update_interval_minutes = self._interval_spin.value()

        # 自动更新
        if hasattr(self._mw, "_auto_update_enabled"):
            self._mw._auto_update_enabled = self._auto_update_cb.isChecked()

        # 主题切换（卡片点击已即时生效，此处仅兜底）
        new_theme = self._theme_selector.current_theme_id()
        if new_theme != theme.current_theme():
            theme.apply_theme(new_theme)
            if hasattr(self._mw, "_on_theme_changed"):
                self._mw._on_theme_changed()

        # 保存到文件
        if hasattr(self._mw, "_save_settings"):
            self._mw._save_settings()

        # 重启定时器
        if self._auto_update_cb.isChecked() and self._interval_spin.value() > 0:
            if hasattr(self._mw, "_start_price_timer"):
                self._mw._start_price_timer()
        else:
            if hasattr(self._mw, "_stop_price_timer"):
                self._mw._stop_price_timer()

        if hasattr(self._mw, "_status_label"):
            self._mw._status_label.setText(f"设置已保存（间隔: {self._interval_spin.value()} 分钟）")

    def _on_init(self):
        """打开数据初始化向导 — 先关设置，再弹向导"""
        if hasattr(self._mw, "_show_init_wizard"):
            self.accept()  # 关闭 SettingsDialog，退出 exec 循环
            # 延迟弹窗：等 exec 返回后，主事件循环恢复再 show
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, lambda: self._mw._show_init_wizard())

    def _on_about(self):
        """打开关于对话框"""
        if hasattr(self._mw, "_show_about"):
            self._mw._show_about()
