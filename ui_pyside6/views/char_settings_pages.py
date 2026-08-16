"""人物设置子页面 — 技能、增效体、市场费率。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from services.implant_loader import load_implants
from ui_pyside6.views.char_settings_common import (
    SKILL_CATEGORIES,
    TRADE_HUBS,
    calc_broker_fee,
    calc_max_orders,
    calc_relist_discount,
    calc_sales_tax,
    format_pct,
)


class SkillSlider(QWidget):
    changed = Signal(str, int)

    def __init__(self, skill_name: str, level: int = 0, parent=None):
        super().__init__(parent)
        self.skill_name = skill_name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        self.name_label = QLabel(skill_name)
        self.name_label.setFixedWidth(180)
        self.name_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 5)
        self.slider.setValue(level)
        self.slider.setFixedWidth(120)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(1)

        self.level_label = QLabel(str(level))
        self.level_label.setFixedWidth(20)
        self.level_label.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 12px; font-weight: bold;")
        self.level_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.slider.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self.name_label)
        layout.addWidget(self.slider)
        layout.addWidget(self.level_label)
        layout.addStretch()

    def _on_value_changed(self, value: int):
        self.level_label.setText(str(value))
        self.changed.emit(self.skill_name, value)

    def set_level(self, level: int):
        self.slider.setValue(level)
        self.level_label.setText(str(level))


class SkillsPage(QWidget):
    def __init__(self, skills_data: dict, parent=None):
        super().__init__(parent)
        self._skill_widgets: dict[str, SkillSlider] = {}
        self._data = dict(skills_data)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._left_panel = QWidget()
        self._left_panel.setFixedWidth(160)
        self._left_panel.setStyleSheet(f"background-color: {theme.BG_SURFACE}; border-radius: 6px;")
        left_layout = QVBoxLayout(self._left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)

        self._cat_label = QLabel("技能分类")
        self._cat_label.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 12px; font-weight: bold; padding: 4px;")
        left_layout.addWidget(self._cat_label)

        self._cat_list = QListWidget()
        self._cat_list.setStyleSheet(f"""
            QListWidget {{
                background-color: transparent; border: none; outline: none;
                color: {theme.TEXT_PRIMARY}; font-size: 12px;
            }}
            QListWidget::item {{ padding: 6px 8px; border-radius: 4px; }}
            QListWidget::item:selected {{ background-color: {theme.BG_SURFACE_LIGHT}; color: {theme.TEXT_BRIGHT}; }}
            QListWidget::item:hover {{ background-color: {theme.BG_HOVER}; }}
        """)
        for cat_name, _ in SKILL_CATEGORIES:
            self._cat_list.addItem(cat_name)
        self._cat_list.currentRowChanged.connect(self._on_category_changed)
        left_layout.addWidget(self._cat_list)
        layout.addWidget(self._left_panel)

        self._right_panel = QWidget()
        self._right_panel.setStyleSheet(f"background-color: {theme.BG_SURFACE}; border-radius: 6px;")
        right_layout = QVBoxLayout(self._right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self._cat_title = QLabel("选择左侧分类")
        self._cat_title.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 14px; font-weight: bold; padding: 4px 0;")
        right_layout.addWidget(self._cat_title)

        self._skill_scroll = QScrollArea()
        self._skill_scroll.setWidgetResizable(True)
        self._skill_scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self._skill_container = QWidget()
        self._skill_container.setStyleSheet("background-color: transparent;")
        self._skill_layout = QVBoxLayout(self._skill_container)
        self._skill_layout.setContentsMargins(0, 0, 0, 0)
        self._skill_layout.setSpacing(2)
        self._skill_layout.addStretch()
        self._skill_scroll.setWidget(self._skill_container)
        right_layout.addWidget(self._skill_scroll)
        layout.addWidget(self._right_panel, 1)

        if self._cat_list.count() > 0:
            self._cat_list.setCurrentRow(0)

    def _on_theme_changed(self):
        self._left_panel.setStyleSheet(f"background-color: {theme.BG_SURFACE}; border-radius: 6px;")
        self._cat_label.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 12px; font-weight: bold; padding: 4px;")
        self._cat_list.setStyleSheet(f"""
            QListWidget {{
                background-color: transparent; border: none; outline: none;
                color: {theme.TEXT_PRIMARY}; font-size: 12px;
            }}
            QListWidget::item {{ padding: 6px 8px; border-radius: 4px; }}
            QListWidget::item:selected {{ background-color: {theme.BG_SURFACE_LIGHT}; color: {theme.TEXT_BRIGHT}; }}
            QListWidget::item:hover {{ background-color: {theme.BG_HOVER}; }}
        """)
        self._right_panel.setStyleSheet(f"background-color: {theme.BG_SURFACE}; border-radius: 6px;")
        self._cat_title.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 14px; font-weight: bold; padding: 4px 0;")

    def _on_category_changed(self, row: int):
        if row < 0 or row >= len(SKILL_CATEGORIES):
            return
        cat_name, skills = SKILL_CATEGORIES[row]
        self._cat_title.setText(cat_name)

        while self._skill_layout.count() > 0:
            item = self._skill_layout.takeAt(0)
            if not item:
                continue
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for skill_name in skills:
            level = self._data.get(skill_name, 0)
            slider = SkillSlider(skill_name, level)
            slider.changed.connect(self._on_skill_changed)
            self._skill_layout.addWidget(slider)
            self._skill_widgets[skill_name] = slider
        self._skill_layout.addStretch()

    def _on_skill_changed(self, skill_name: str, level: int):
        self._data[skill_name] = level

    def get_data(self) -> dict[str, int]:
        return dict(self._data)


class ImplantsPage(QWidget):
    def __init__(self, implant_ids: list, parent=None):
        super().__init__(parent)
        self._implants = load_implants()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        self._implant_title = QLabel("增效体插槽")
        self._implant_title.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 16px; font-weight: bold;")
        layout.addWidget(self._implant_title)

        self._implant_desc = QLabel("选择植入的工业增效体（最多 3 个），每个提供不同的生产/贸易加成")
        self._implant_desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        self._implant_desc.setWordWrap(True)
        layout.addWidget(self._implant_desc)

        self._combos = []
        self._implant_groups = []
        self._bonus_labels = []
        slot_names = ["插槽 A — 生产与研究", "插槽 B — 精炼与采矿", "插槽 C — 通用"]

        for i in range(3):
            group = QGroupBox(slot_names[i])
            group.setStyleSheet(f"""
                QGroupBox {{
                    background-color: {theme.BG_SURFACE};
                    border: 1px solid {theme.BORDER}; border-radius: 6px;
                    margin-top: 12px; padding: 16px 12px 12px 12px;
                    font-size: 12px; color: {theme.TEXT_PRIMARY};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin; subcontrol-position: top left;
                    padding: 2px 8px; color: {theme.PRIMARY};
                }}
            """)
            glayout = QVBoxLayout(group)
            glayout.setSpacing(4)

            combo = QComboBox()
            combo.addItem("-- 无 --", None)
            for imp in self._implants:
                label = f"{imp['zh_name']} ({imp['bonus_desc']})" if imp["bonus_desc"] else imp["zh_name"]
                combo.addItem(label, imp["type_id"])

            saved_id = implant_ids[i] if i < len(implant_ids) else None
            if saved_id is not None:
                idx = combo.findData(saved_id)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

            combo.setStyleSheet(f"""
                QComboBox {{
                    background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY};
                    border: 1px solid {theme.BORDER}; border-radius: 4px;
                    padding: 4px 8px; font-size: 12px;
                }}
                QComboBox:hover {{ border-color: {theme.PRIMARY}; }}
                QComboBox QAbstractItemView {{
                    background-color: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};
                    selection-background-color: {theme.PRIMARY};
                    border: 1px solid {theme.BORDER};
                }}
                QComboBox::drop-down {{ border: none; width: 20px; }}
            """)
            glayout.addWidget(combo)

            bonus_label = QLabel("")
            bonus_label.setStyleSheet(f"color: {theme.ACCENT_GREEN}; font-size: 11px; padding-left: 4px;")
            glayout.addWidget(bonus_label)

            def on_combo_change(idx, lbl=bonus_label, cb=combo):
                data = cb.itemData(idx)
                if data:
                    for imp in self._implants:
                        if imp["type_id"] == data:
                            lbl.setText(f"  {imp['bonus_desc']}" if imp["bonus_desc"] else "")
                            break
                else:
                    lbl.setText("")

            combo.currentIndexChanged.connect(on_combo_change)
            on_combo_change(combo.currentIndex())

            self._combos.append(combo)
            self._implant_groups.append(group)
            self._bonus_labels.append(bonus_label)
            layout.addWidget(group)

        layout.addStretch()

    def _on_theme_changed(self):
        self._implant_title.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 16px; font-weight: bold;")
        self._implant_desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        for group in self._implant_groups:
            group.setStyleSheet(f"""
                QGroupBox {{
                    background-color: {theme.BG_SURFACE};
                    border: 1px solid {theme.BORDER}; border-radius: 6px;
                    margin-top: 12px; padding: 16px 12px 12px 12px;
                    font-size: 12px; color: {theme.TEXT_PRIMARY};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin; subcontrol-position: top left;
                    padding: 2px 8px; color: {theme.PRIMARY};
                }}
            """)
        for combo in self._combos:
            combo.setStyleSheet(f"""
                QComboBox {{
                    background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY};
                    border: 1px solid {theme.BORDER}; border-radius: 4px;
                    padding: 4px 8px; font-size: 12px;
                }}
                QComboBox:hover {{ border-color: {theme.PRIMARY}; }}
                QComboBox QAbstractItemView {{
                    background-color: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};
                    selection-background-color: {theme.PRIMARY};
                    border: 1px solid {theme.BORDER};
                }}
                QComboBox::drop-down {{ border: none; width: 20px; }}
            """)
        for bonus_label in self._bonus_labels:
            bonus_label.setStyleSheet(f"color: {theme.ACCENT_GREEN}; font-size: 11px; padding-left: 4px;")

    def get_data(self) -> list:
        return [c.itemData(c.currentIndex()) for c in self._combos]


class MarketPage(QWidget):
    """市场费率标签页：4 大交易中心，声望输入 + 自动计算"""

    def __init__(self, skills_data: dict, market_data: dict, parent=None):
        super().__init__(parent)
        self._skills_data = skills_data
        self._market_data = dict(market_data)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("市场费率配置")
        title.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("为每个交易中心设置派系声望和军团声望，自动计算经纪人费率和销售税率")
        desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        clayout = QVBoxLayout(container)
        clayout.setContentsMargins(0, 0, 0, 0)
        clayout.setSpacing(12)

        self._hub_widgets = {}

        for hub_key, hub_name, faction_name, corp_name in TRADE_HUBS:
            hub_data = self._market_data.get(hub_key, {"faction_standing": 5.0, "corp_standing": 5.0})

            group = QGroupBox(f"{hub_name}")
            group.setStyleSheet(f"""
                QGroupBox {{
                    background-color: {theme.BG_SURFACE};
                    border: 1px solid {theme.BORDER}; border-radius: 6px;
                    margin-top: 12px; padding: 16px 12px 12px 12px;
                    font-size: 12px; color: {theme.TEXT_PRIMARY};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin; subcontrol-position: top left;
                    padding: 2px 8px; color: {theme.PRIMARY};
                }}
            """)
            glayout = QGridLayout(group)
            glayout.setSpacing(8)

            glayout.addWidget(QLabel(f"派系声望 ({faction_name}):"), 0, 0)
            fs = QDoubleSpinBox()
            fs.setRange(-10.0, 10.0)
            fs.setSingleStep(0.1)
            fs.setValue(hub_data.get("faction_standing", 5.0))
            fs.setStyleSheet(
                f"background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY};"
                f" border: 1px solid {theme.BORDER}; border-radius: 4px;"
                f" padding: 2px 4px;"
            )
            glayout.addWidget(fs, 0, 1)

            glayout.addWidget(QLabel(f"军团声望 ({corp_name}):"), 1, 0)
            cs = QDoubleSpinBox()
            cs.setRange(-10.0, 10.0)
            cs.setSingleStep(0.1)
            cs.setValue(hub_data.get("corp_standing", 5.0))
            cs.setStyleSheet(
                f"background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY};"
                f" border: 1px solid {theme.BORDER}; border-radius: 4px;"
                f" padding: 2px 4px;"
            )
            glayout.addWidget(cs, 1, 1)

            result_label = QLabel("经纪人费率: -- | 销售税率: -- | 改单折扣: -- | 最大订单: --")
            result_label.setStyleSheet(f"color: {theme.ACCENT_GREEN}; font-size: 11px;")
            glayout.addWidget(result_label, 2, 0, 1, 2)

            def make_calc(hk=hub_key, fl=fs, cl=cs, rl=result_label):
                def recalc():
                    skills = self._skills_data
                    bf = calc_broker_fee(skills, fl.value(), cl.value())
                    st = calc_sales_tax(skills)
                    rd = calc_relist_discount(skills)
                    mo = calc_max_orders(skills)
                    rl.setText(
                        f"经纪人费率: {format_pct(bf)} | "
                        f"销售税率: {format_pct(st)} | "
                        f"改单折扣: {rd:.0f}% | "
                        f"最大订单: {mo}"
                    )

                return recalc

            recalc_fn = make_calc()
            fs.valueChanged.connect(recalc_fn)
            cs.valueChanged.connect(recalc_fn)
            recalc_fn()

            self._hub_widgets[hub_key] = (fs, cs)
            clayout.addWidget(group)

        clayout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

    def set_skills_data(self, skills_data: dict):
        self._skills_data = skills_data
        for _hub_key, (fs, _cs) in self._hub_widgets.items():
            fs.valueChanged.emit(fs.value())

    def get_data(self) -> dict:
        result = {}
        for hub_key, (fs, cs) in self._hub_widgets.items():
            result[hub_key] = {
                "faction_standing": fs.value(),
                "corp_standing": cs.value(),
            }
        return result
