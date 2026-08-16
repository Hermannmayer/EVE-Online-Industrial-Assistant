"""
人物设置对话框 — 多角色 / 技能 / 增效体 / 市场费率
"""


from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from services.char_config_resolver import (
    char_config_path as services_char_config_path,
)
from services.char_config_resolver import (
    get_character as services_get_character,
)
from services.char_config_resolver import (
    get_character_list as services_get_character_list,
)
from services.char_config_resolver import (
    load_all_data as services_load_all_data,
)
from services.char_config_resolver import (
    save_all_data as services_save_all_data,
)
from ui_pyside6.views.char_settings_common import (
    calc_broker_fee,
    calc_max_orders,
    calc_relist_discount,
    calc_sales_tax,
)
from ui_pyside6.views.char_settings_pages import ImplantsPage, MarketPage, SkillsPage

# ═══════════════════════════════════════════
#  兼容转发
# ═══════════════════════════════════════════


def char_config_path() -> str:
    return services_char_config_path()


def get_character(name: str):
    return services_get_character(name)


def get_character_list() -> list[str]:
    return services_get_character_list()


def load_all_data() -> dict:
    return services_load_all_data()


def save_all_data(data: dict):
    services_save_all_data(data)


# ═══════════════════════════════════════════
#  游戏公式
# ═══════════════════════════════════════════


def get_market_rate(char_name: str, hub: str, skills: dict | None = None) -> dict:
    """
    获取角色在指定交易中心的完整费率信息
    返回: {broker_fee, sales_tax, relist_discount, max_orders, faction_standing, corp_standing}
    """
    char = get_character(char_name)
    if not char:
        return {}

    if skills is None:
        skills = char.get("skills", {})

    hub_data = char.get("market", {}).get(hub, {})
    faction = hub_data.get("faction_standing", 5.0)
    corp = hub_data.get("corp_standing", 5.0)

    return {
        "broker_fee": calc_broker_fee(skills, faction, corp),
        "sales_tax": calc_sales_tax(skills),
        "relist_discount": calc_relist_discount(skills),
        "max_orders": calc_max_orders(skills),
        "faction_standing": faction,
        "corp_standing": corp,
    }


# ═══════════════════════════════════════════
#  主对话框
# ═══════════════════════════════════════════


class CharSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("人物设置")
        self.setMinimumSize(750, 600)
        self.setStyleSheet(f"background-color: {theme.BG_DARK};")

    def showEvent(self, ev):
        """showEvent 时重新应用当前主题样式表"""
        super().showEvent(ev)
        self.setStyleSheet(f"background-color: {theme.BG_DARK};")

        # 加载所有数据
        self._all_data = load_all_data()
        self._current_char_name = self._all_data.get("current", "main")
        if self._current_char_name not in self._all_data.get("characters", {}):
            self._current_char_name = list(self._all_data["characters"].keys())[0]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── 顶部角色栏 ──
        self._build_char_bar(layout)

        # ── 标签页 ──
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{ background-color: {theme.BG_DARK}; border: none; }}
            QTabBar::tab {{
                background-color: {theme.BG_SURFACE}; color: {theme.TEXT_SECONDARY};
                padding: 8px 24px; border: none; border-right: 1px solid {theme.BORDER};
                font-size: 13px;
            }}
            QTabBar::tab:selected {{ background-color: {theme.BG_DARK}; color: {theme.PRIMARY}; font-weight: bold; }}
            QTabBar::tab:hover {{ color: {theme.TEXT_PRIMARY}; }}
        """)

        self._rebuild_pages()
        layout.addWidget(self._tabs)

        # ── 底部按钮 ──
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(12, 8, 12, 8)
        btn_bar.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 6px 20px; }}
            QPushButton:hover {{ background-color: {theme.BG_HOVER}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)

        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {theme.PRIMARY}; color: {theme.TEXT_ON_PRIMARY};
                border: none; border-radius: 6px; padding: 6px 20px; font-weight: bold; }}
            QPushButton:hover {{ background-color: {theme.BG_HOVER}; }}
        """)
        save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(save_btn)

        layout.addLayout(btn_bar)

    def _build_char_bar(self, parent_layout):
        """构建顶部角色切换栏"""
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {theme.BG_SURFACE}; border-bottom: 1px solid {theme.BORDER};")
        blayout = QHBoxLayout(bar)
        blayout.setContentsMargins(12, 8, 12, 8)
        blayout.setSpacing(8)

        blayout.addWidget(QLabel("当前人物:"))
        self._char_combo = QComboBox()
        self._char_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER}; border-radius: 4px;
                padding: 4px 8px; min-width: 120px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};
                selection-background-color: {theme.PRIMARY};
            }}
        """)
        for cname in self._all_data["characters"].keys():
            self._char_combo.addItem(cname, cname)
        idx = self._char_combo.findData(self._current_char_name)
        if idx >= 0:
            self._char_combo.setCurrentIndex(idx)
        self._char_combo.currentIndexChanged.connect(self._on_char_switch)
        blayout.addWidget(self._char_combo)

        self._char_name_edit = QLineEdit(self._current_char_name)
        self._char_name_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border-color: {theme.PRIMARY}; }}
        """)
        blayout.addWidget(self._char_name_edit)

        add_btn = QPushButton("+ 添加")
        add_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {theme.ACCENT_GREEN}; color: {theme.TEXT_ON_PRIMARY};
                border: none; border-radius: 4px; padding: 4px 12px; font-size: 12px; }}
            QPushButton:hover {{ background-color: {theme.BG_HOVER}; }}
        """)
        add_btn.clicked.connect(self._on_add_character)
        blayout.addWidget(add_btn)

        del_btn = QPushButton("删除")
        del_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {theme.ACCENT_RED}; color: {theme.TEXT_ON_PRIMARY};
                border: none; border-radius: 4px; padding: 4px 12px; font-size: 12px; }}
            QPushButton:hover {{ background-color: {theme.BG_HOVER}; }}
            QPushButton:disabled {{ background-color: {theme.TEXT_SECONDARY}; }}
        """)
        if len(self._all_data["characters"]) <= 1:
            del_btn.setEnabled(False)
        del_btn.clicked.connect(self._on_delete_character)
        blayout.addWidget(del_btn)

        blayout.addStretch()
        parent_layout.addWidget(bar)

    def _rebuild_pages(self):
        """根据当前角色重建所有标签页"""
        # 清除旧 tabs
        while self._tabs.count() > 0:
            self._tabs.removeTab(0)

        char_data = self._all_data["characters"].get(self._current_char_name, {})
        skills_data = char_data.get("skills", {})
        implant_ids = char_data.get("implants", [None, None, None])
        market_data = char_data.get("market", {})

        self._skills_page = SkillsPage(skills_data)
        self._implants_page = ImplantsPage(implant_ids)
        self._market_page = MarketPage(skills_data, market_data)

        self._tabs.addTab(self._skills_page, "技能")
        self._tabs.addTab(self._implants_page, "增效体")
        self._tabs.addTab(self._market_page, "市场费率")

        # 当技能变化时重新计算市场费率
        # 确保通过属性访问触发初始化
        _ = self._skills_page._skill_widgets
        # Connect skill changes to market recalc
        for _name, slider in self._skills_page._skill_widgets.items():
            slider.changed.connect(self._on_skill_for_market)

    def _on_skill_for_market(self, skill_name: str, level: int):
        """技能变化时通知市场页面重新计算"""
        self._market_page.set_skills_data(self._skills_page.get_data())

    def _on_char_switch(self, idx: int):
        """切换角色"""
        if idx < 0:
            return
        name = self._char_combo.itemData(idx)
        if name and name != self._current_char_name:
            self._current_char_name = name
            self._char_name_edit.setText(name)
            self._rebuild_pages()

    def _on_add_character(self):
        """添加新角色"""
        base_name = "新角色"
        name = base_name
        i = 1
        while name in self._all_data["characters"]:
            i += 1
            name = f"{base_name}{i}"

        self._all_data["characters"][name] = {
            "skills": {},
            "implants": [None, None, None],
            "market": {
                "jita": {"faction_standing": 5.0, "corp_standing": 5.0},
                "amarr": {"faction_standing": 5.0, "corp_standing": 5.0},
                "dodixie": {"faction_standing": 5.0, "corp_standing": 5.0},
                "rens": {"faction_standing": 5.0, "corp_standing": 5.0},
            },
        }
        self._char_combo.addItem(name, name)
        self._char_combo.setCurrentIndex(self._char_combo.count() - 1)

    def _on_delete_character(self):
        """删除当前角色"""
        if len(self._all_data["characters"]) <= 1:
            return
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除角色「{self._current_char_name}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del self._all_data["characters"][self._current_char_name]
        idx = self._char_combo.currentIndex()
        self._char_combo.removeItem(idx)

        # 切换到第一个可用角色
        self._current_char_name = self._char_combo.itemData(0)
        self._char_name_edit.setText(self._current_char_name)
        self._rebuild_pages()

    def _on_save(self):
        """保存所有配置"""
        char_data = self._all_data["characters"].setdefault(self._current_char_name, {})
        char_data["skills"] = self._skills_page.get_data()
        char_data["implants"] = self._implants_page.get_data()
        char_data["market"] = self._market_page.get_data()

        self._all_data["current"] = self._current_char_name
        save_all_data(self._all_data)
        QMessageBox.information(self, "保存成功", "角色配置已保存")
        self.accept()
