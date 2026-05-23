"""
人物设置对话框 — 多角色 / 技能 / 增效体 / 市场费率
"""
import json
import os
import sqlite3
import math
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QLabel, QSlider, QGroupBox, QScrollArea,
    QPushButton, QMessageBox, QGridLayout, QLineEdit,
    QFormLayout, QDoubleSpinBox, QSpinBox, QComboBox,
    QSplitter, QListWidget, QListWidgetItem,
    QCompleter, QFrame,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont

from ui_pyside6.theme import (
    BG_DARK, BG_SURFACE, BG_SURFACE_LIGHT, BG_HOVER,
    PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_BRIGHT, BORDER,
    ACCENT_GREEN, ACCENT_RED, ACCENT_CYAN,
)

from core.paths import DB_PATH

# ═══════════════════════════════════════════
#  游戏公式
# ═══════════════════════════════════════════

def calc_broker_fee(skills: dict, faction_standing: float, corp_standing: float,
                    base_rate: float = 1.0) -> float:
    """
    计算经纪人费率 (%)
    formula: (base_rate - 0.05 * broker_relations_level) / 2^(0.14 * faction + 0.06 * corp)
    """
    broker_rel = skills.get("经纪人关系学", 0)
    standing_factor = 2 ** (0.14 * max(0, faction_standing) + 0.06 * max(0, corp_standing))
    if standing_factor == 0:
        return base_rate
    return max(0.1, (base_rate - 0.05 * broker_rel) / standing_factor)


def calc_relist_discount(skills: dict) -> float:
    """
    计算改单折扣 (%)
    Advanced Broker Relations: 每级 +5%，0级=50%，5级=75%
    """
    adv = skills.get("高级经纪人关系学", 0)
    return 50 + adv * 5


def calc_sales_tax(skills: dict, base_tax: float = 2.0) -> float:
    """计算销售税率 (%)  accounting: 每级 -3%"""
    accounting = skills.get("会计学", 0)
    return base_tax * (1 - 0.03 * accounting)


def calc_max_orders(skills: dict, base_orders: int = 15) -> int:
    """计算最大订单数"""
    trade = skills.get("贸易学", 0)
    retail = skills.get("零售技巧", 0)
    wholesale = skills.get("批发技巧", 0)
    tycoon = skills.get("商业巨头", 0)
    return base_orders + 4 * trade + 8 * retail + 16 * wholesale + 32 * tycoon


def format_pct(value: float) -> str:
    return f"{value:.2f}%"


# ═══════════════════════════════════════════
#  技能数据定义
# ═══════════════════════════════════════════

SKILL_CATEGORIES = [
    ("\U0001f4cb 订单数量", ["批发技巧", "商业巨头", "贸易学", "零售技巧"]),
    ("\U0001f4b0 税费降低", ["高级经纪人关系学", "会计学", "经纪人关系学"]),
    ("\U0001f9ca 冰矿专精", ["冰矿处理技术"]),
    ("\U0001f5d1️ 化垃圾", ["碎铁处理技术"]),
    ("\U0001f527 基础精炼", ["提炼学概论", "提炼效率理论"]),
    ("\U0001f4a8 气云专精", ["气云解压效率"]),
    ("\U0001f319 卫星矿专精", [
        "常见卫星矿石处理技术", "普通卫星矿石处理技术",
        "罕见卫星矿石处理技术", "稀有卫星矿石处理技术",
        "非凡卫星矿石处理技术",
    ]),
    ("\U0001faa8 小行星矿专精", [
        "基腹断岩处理技术", "普通矿石处理技术", "聚合矿石处理技术",
        "斑驳矿石处理技术", "死亡空间矿石处理技术", "深渊矿石处理技术",
    ]),
    ("⚙️ T2 前置", ["机械学", "科学原理", "能量栅格管理学", "CPU管理学"]),
    ("\U0001f52c T3", [
        "防御子系统技术", "核心子系统技术", "电子子系统技术",
        "攻击子系统技术", "推进子系统技术",
    ]),
    ("\U0001f4d6 故事线", ["塔洛迦技术研究", "冬眠者技术研究", "塔克玛技术研究", "殷郡技术研究"]),
    ("\U0001f510 加密原理", [
        "加达里加密技术原理", "米玛塔尔加密技术原理",
        "艾玛加密技术原理", "盖伦特加密技术原理",
    ]),
    ("\U0001f9ea 科学", [
        "高能物理学", "等离子物理学", "纳米工程学", "磁流体物理学",
        "艾玛星舰工程学", "米玛塔尔星舰工程学", "引力子物理学",
        "激光物理学", "电磁物理学", "火箭科学", "盖伦特星舰工程学",
        "核芯物理学", "机械工程学", "电子工程学", "加达里星舰工程学",
        "量子物理学", "分子工程学", "冬眠者加密技术原理",
        "血袭者改造技术研究", "天蛇改造技术研究", "天使改造技术研究",
        "古斯塔斯改造技术研究", "昇威星舰工程学", "突变稳定",
    ]),
    ("\U0001f4d0 蓝图研究加速", ["研究概论", "冶金学"]),
    ("\U0001f300 深渊", ["三神裔量子工程学", "三神裔加密技术原理", "昇威加密技术原理"]),
    ("\U0001f52c 研究线", ["高级实验室运作理论", "实验室运作理论"]),
    ("\U0001f6f8 其他技能", ["气云采集理论", "无人机概论"]),
    ("\U0001f30d 行星基础", ["行星统筹管理学", "指挥中心升级理论", "海关操作专业理论"]),
    ("\U0001f3d7️ T2 制造", [
        "高级小型舰船建造研究", "高级工业舰船建造研究",
        "高级中型舰船建造研究", "高级大型舰船建造研究",
    ]),
    ("⚗️ 反应", ["反应理论"]),
    ("\U0001f9ea 反应线", ["大规模反应理论", "高级大规模反应理论"]),
    ("\U0001f529 改装件", [
        "构件改装技术", "装甲改装技术", "空间航行改装技术",
        "无人机改装技术", "电子优势改装技术", "射弹武器改装技术",
        "能量武器改装技术", "混合武器改装技术", "发射器改装技术",
        "护盾改装技术",
    ]),
    ("\U0001f3ed 工业基础", ["工业理论", "高级工业理论"]),
    ("\U0001f3db️ 建筑制造", ["空间定锚", "哨站建造研究"]),
    ("\U0001f6a2 旗舰制造", ["旗舰级船只建造研究", "高级旗舰建造"]),
    ("\U0001f4e6 生产线", ["高级量产技术", "批量生产学"]),
]

ALL_SKILLS = []
for cat_name, skills in SKILL_CATEGORIES:
    for s in skills:
        ALL_SKILLS.append(s)

# ═══════════════════════════════════════════
#  四大贸易中心定义
# ═══════════════════════════════════════════

TRADE_HUBS = [
    ("jita",    "吉他 Jita",       "加达里 Caldari",       "加达里海军 Caldari Navy"),
    ("amarr",   "艾玛 Amarr",      "艾玛 Amarr",           "皇族 Emperor Family"),
    ("dodixie", "多迪 Dodixie",    "盖伦特 Gallente",      "盖伦特统计局"),
    ("rens",    "伦斯 Rens",       "米玛塔尔 Minmatar",    "米玛塔尔矿业"),
]


# ═══════════════════════════════════════════
#  配置文件路径
# ═══════════════════════════════════════════

def char_config_path() -> str:
    data_dir = os.path.join(os.path.dirname(DB_PATH), "..", "data")
    return os.path.join(os.path.abspath(data_dir), "char_config.json")


def load_all_data() -> dict:
    """加载完整配置"""
    path = char_config_path()
    default = {
        "current": "main",
        "characters": {
            "main": {
                "skills": {},
                "implants": [None, None, None],
                "market": {
                    "jita":  {"faction_standing": 5.0, "corp_standing": 5.0},
                    "amarr": {"faction_standing": 5.0, "corp_standing": 5.0},
                    "dodixie": {"faction_standing": 5.0, "corp_standing": 5.0},
                    "rens":  {"faction_standing": 5.0, "corp_standing": 5.0},
                }
            }
        }
    }
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 合并默认值确保结构完整
                for cname in data.get("characters", {}):
                    c = data["characters"][cname]
                    c.setdefault("skills", {})
                    c.setdefault("implants", [None, None, None])
                    c.setdefault("market", {
                        "jita": {"faction_standing": 5.0, "corp_standing": 5.0},
                        "amarr": {"faction_standing": 5.0, "corp_standing": 5.0},
                        "dodixie": {"faction_standing": 5.0, "corp_standing": 5.0},
                        "rens": {"faction_standing": 5.0, "corp_standing": 5.0},
                    })
                return data
        except Exception:
            pass
    return default


def save_all_data(data: dict):
    path = char_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════
#  植入体数据查询
# ═══════════════════════════════════════════

IMPLANT_CACHE = []


def load_implants() -> list[dict]:
    """从 item_dogma 表加载所有工业植入体"""
    global IMPLANT_CACHE
    if IMPLANT_CACHE:
        return IMPLANT_CACHE

    db_path = DB_PATH
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT i.type_id, i.en_name, i.zh_name, d.dogma_attrs
        FROM item i
        JOIN item_dogma d ON i.type_id = d.type_id
        ORDER BY i.en_name
    """)
    results = []
    for row in cur.fetchall():
        type_id, en_name, zh_name, dogma_json = row
        attrs = json.loads(dogma_json) if dogma_json else []
        # 解析 bonus 描述
        bonus_desc = _parse_implant_bonus(attrs)
        results.append({
            "type_id": type_id,
            "en_name": en_name,
            "zh_name": zh_name or en_name,
            "bonus_desc": bonus_desc,
        })
    conn.close()
    IMPLANT_CACHE = results
    return results


def _parse_implant_bonus(attrs: list) -> str:
    """从 dogma 属性解析人类可读的加成描述"""
    # attribute_id -> (显示名称, 是否减少型)
    # 减少型: 负值=收益 (如 -1% 制造时间)
    # 增加型: 正值=收益 (如 +1% 采矿量)
    KNOWN = {
        440: ("制造时间", True),       # manufacturingTimeBonus
        452: ("复制速度", True),       # copySpeedBonus
        453: ("蓝图制造时间", True),   # blueprintmanufactureTimeBonus
        468: ("材料需求研究", True),   # mineralNeedResearchBonus
        379: ("精炼产出", False),      # refiningYieldMutator
        434: ("采矿量", False),        # miningAmountBonus
        927: ("采矿升级CPU", True),    # miningUpgradeCPUReductionBonus
        780: ("冰矿采集周期", True),   # iceHarvestCycleBonus
        66:  ("循环时间", True),       # durationBonus
    }
    descs = []
    for attr in attrs:
        aid = attr["attribute_id"]
        val = attr["value"]
        if aid in KNOWN:
            name, is_reduction = KNOWN[aid]
            if val != 0:
                if is_reduction:
                    descs.append(f"{name} -{abs(int(val))}%")
                else:
                    descs.append(f"{name} +{int(val)}%")
    return ", ".join(descs) if descs else ""


# ═══════════════════════════════════════════
#  对外查询接口
# ═══════════════════════════════════════════

def get_character_list() -> list[str]:
    """获取所有角色名列表"""
    data = load_all_data()
    return list(data.get("characters", {}).keys())


def get_character(name: str) -> Optional[dict]:
    """获取指定角色的完整配置"""
    data = load_all_data()
    return data.get("characters", {}).get(name)


def get_market_rate(char_name: str, hub: str, skills: dict = None) -> dict:
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
#  技能滑块组件
# ═══════════════════════════════════════════

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
        self.name_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 5)
        self.slider.setValue(level)
        self.slider.setFixedWidth(120)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(1)

        self.level_label = QLabel(str(level))
        self.level_label.setFixedWidth(20)
        self.level_label.setStyleSheet(f"color: {PRIMARY}; font-size: 12px; font-weight: bold;")
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


# ═══════════════════════════════════════════
#  技能页面
# ═══════════════════════════════════════════

class SkillsPage(QWidget):
    def __init__(self, skills_data: dict, parent=None):
        super().__init__(parent)
        self._skill_widgets: dict[str, SkillSlider] = {}
        self._data = dict(skills_data)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 左侧：类别列表
        left_panel = QWidget()
        left_panel.setFixedWidth(160)
        left_panel.setStyleSheet(f"background-color: {BG_SURFACE}; border-radius: 6px;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)

        cat_label = QLabel("技能分类")
        cat_label.setStyleSheet(f"color: {PRIMARY}; font-size: 12px; font-weight: bold; padding: 4px;")
        left_layout.addWidget(cat_label)

        self._cat_list = QListWidget()
        self._cat_list.setStyleSheet(f"""
            QListWidget {{
                background-color: transparent; border: none; outline: none;
                color: {TEXT_PRIMARY}; font-size: 12px;
            }}
            QListWidget::item {{ padding: 6px 8px; border-radius: 4px; }}
            QListWidget::item:selected {{ background-color: {BG_SURFACE_LIGHT}; color: {TEXT_BRIGHT}; }}
            QListWidget::item:hover {{ background-color: {BG_HOVER}; }}
        """)
        for cat_name, _ in SKILL_CATEGORIES:
            self._cat_list.addItem(cat_name)
        self._cat_list.currentRowChanged.connect(self._on_category_changed)
        left_layout.addWidget(self._cat_list)
        layout.addWidget(left_panel)

        # 右侧：技能详情
        right_panel = QWidget()
        right_panel.setStyleSheet(f"background-color: {BG_SURFACE}; border-radius: 6px;")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self._cat_title = QLabel("选择左侧分类")
        self._cat_title.setStyleSheet(f"color: {PRIMARY}; font-size: 14px; font-weight: bold; padding: 4px 0;")
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
        layout.addWidget(right_panel, 1)

        if self._cat_list.count() > 0:
            self._cat_list.setCurrentRow(0)

    def _on_category_changed(self, row: int):
        if row < 0 or row >= len(SKILL_CATEGORIES):
            return
        cat_name, skills = SKILL_CATEGORIES[row]
        self._cat_title.setText(cat_name)

        while self._skill_layout.count() > 0:
            item = self._skill_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

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


# ═══════════════════════════════════════════
#  增效体页面（3插槽下拉）
# ═══════════════════════════════════════════

class ImplantsPage(QWidget):
    def __init__(self, implant_ids: list, parent=None):
        super().__init__(parent)
        self._implants = load_implants()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        title = QLabel("增效体插槽")
        title.setStyleSheet(f"color: {PRIMARY}; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("选择植入的工业增效体（最多 3 个），每个提供不同的生产/贸易加成")
        desc.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self._combos = []
        slot_names = ["插槽 A — 生产与研究", "插槽 B — 精炼与采矿", "插槽 C — 通用"]

        for i in range(3):
            group = QGroupBox(slot_names[i])
            group.setStyleSheet(f"""
                QGroupBox {{
                    background-color: {BG_SURFACE};
                    border: 1px solid {BORDER}; border-radius: 6px;
                    margin-top: 12px; padding: 16px 12px 12px 12px;
                    font-size: 12px; color: {TEXT_PRIMARY};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin; subcontrol-position: top left;
                    padding: 2px 8px; color: {PRIMARY};
                }}
            """)
            glayout = QVBoxLayout(group)
            glayout.setSpacing(4)

            combo = QComboBox()
            combo.addItem("-- 无 --", None)
            for imp in self._implants:
                label = f"{imp['zh_name']} ({imp['bonus_desc']})" if imp['bonus_desc'] else imp['zh_name']
                combo.addItem(label, imp['type_id'])

            # 设置已保存的值
            saved_id = implant_ids[i] if i < len(implant_ids) else None
            if saved_id is not None:
                idx = combo.findData(saved_id)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

            combo.setStyleSheet(f"""
                QComboBox {{
                    background-color: {BG_DARK}; color: {TEXT_PRIMARY};
                    border: 1px solid {BORDER}; border-radius: 4px;
                    padding: 4px 8px; font-size: 12px;
                }}
                QComboBox:hover {{ border-color: {PRIMARY}; }}
                QComboBox QAbstractItemView {{
                    background-color: {BG_SURFACE}; color: {TEXT_PRIMARY};
                    selection-background-color: {BG_SURFACE_LIGHT};
                    border: 1px solid {BORDER};
                }}
                QComboBox::drop-down {{ border: none; width: 20px; }}
            """)
            glayout.addWidget(combo)

            # 显示选中植入体的加成
            bonus_label = QLabel("")
            bonus_label.setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 11px; padding-left: 4px;")
            glayout.addWidget(bonus_label)

            def on_combo_change(idx, lbl=bonus_label, cb=combo):
                data = cb.itemData(idx)
                if data:
                    for imp in self._implants:
                        if imp['type_id'] == data:
                            lbl.setText(f"  {imp['bonus_desc']}" if imp['bonus_desc'] else "")
                            break
                else:
                    lbl.setText("")

            combo.currentIndexChanged.connect(on_combo_change)
            # 初始化显示
            on_combo_change(combo.currentIndex())

            self._combos.append(combo)
            layout.addWidget(group)

        layout.addStretch()

    def get_data(self) -> list:
        return [c.itemData(c.currentIndex()) for c in self._combos]


# ═══════════════════════════════════════════
#  市场费率页面
# ═══════════════════════════════════════════

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
        title.setStyleSheet(f"color: {PRIMARY}; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("为每个交易中心设置派系声望和军团声望，自动计算经纪人费率和销售税率")
        desc.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
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
                    background-color: {BG_SURFACE};
                    border: 1px solid {BORDER}; border-radius: 6px;
                    margin-top: 12px; padding: 16px 12px 12px 12px;
                    font-size: 12px; color: {TEXT_PRIMARY};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin; subcontrol-position: top left;
                    padding: 2px 8px; color: {PRIMARY};
                }}
            """)
            glayout = QGridLayout(group)
            glayout.setSpacing(8)

            # 派系声望
            glayout.addWidget(QLabel(f"派系声望 ({faction_name}):"), 0, 0)
            fs = QDoubleSpinBox()
            fs.setRange(-10.0, 10.0)
            fs.setSingleStep(0.1)
            fs.setValue(hub_data.get("faction_standing", 5.0))
            fs.setStyleSheet(f"background-color: {BG_DARK}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER}; border-radius: 4px; padding: 2px 4px;")
            glayout.addWidget(fs, 0, 1)

            # 军团声望
            glayout.addWidget(QLabel(f"军团声望 ({corp_name}):"), 1, 0)
            cs = QDoubleSpinBox()
            cs.setRange(-10.0, 10.0)
            cs.setSingleStep(0.1)
            cs.setValue(hub_data.get("corp_standing", 5.0))
            cs.setStyleSheet(f"background-color: {BG_DARK}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER}; border-radius: 4px; padding: 2px 4px;")
            glayout.addWidget(cs, 1, 1)

            # 计算结果
            result_label = QLabel("经纪人费率: -- | 销售税率: -- | 改单折扣: -- | 最大订单: --")
            result_label.setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 11px;")
            glayout.addWidget(result_label, 2, 0, 1, 2)

            # 每次值变化时重新计算
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
            recalc_fn()  # 初始计算

            self._hub_widgets[hub_key] = (fs, cs)
            clayout.addWidget(group)

        clayout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

    def set_skills_data(self, skills_data: dict):
        """技能页面切换时更新计算公式"""
        self._skills_data = skills_data
        for hub_key, (fs, cs) in self._hub_widgets.items():
            # 触发重新计算
            fs.valueChanged.emit(fs.value())

    def get_data(self) -> dict:
        result = {}
        for hub_key, (fs, cs) in self._hub_widgets.items():
            result[hub_key] = {
                "faction_standing": fs.value(),
                "corp_standing": cs.value(),
            }
        return result


# ═══════════════════════════════════════════
#  主对话框
# ═══════════════════════════════════════════

class CharSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("人物设置")
        self.setMinimumSize(750, 600)
        self.setStyleSheet(f"background-color: {BG_DARK};")

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
            QTabWidget::pane {{ background-color: {BG_DARK}; border: none; }}
            QTabBar::tab {{
                background-color: {BG_SURFACE}; color: {TEXT_SECONDARY};
                padding: 8px 24px; border: none; border-right: 1px solid {BORDER};
                font-size: 13px;
            }}
            QTabBar::tab:selected {{ background-color: {BG_DARK}; color: {PRIMARY}; font-weight: bold; }}
            QTabBar::tab:hover {{ color: {TEXT_PRIMARY}; }}
        """)

        self._rebuild_pages()
        layout.addWidget(self._tabs)

        # ── 底部按钮 ──
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(12, 8, 12, 8)
        btn_bar.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {BG_SURFACE}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 20px; }}
            QPushButton:hover {{ background-color: {BG_HOVER}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)

        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {PRIMARY}; color: white;
                border: none; border-radius: 6px; padding: 6px 20px; font-weight: bold; }}
            QPushButton:hover {{ background-color: #5199e0; }}
        """)
        save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(save_btn)

        layout.addLayout(btn_bar)

    def _build_char_bar(self, parent_layout):
        """构建顶部角色切换栏"""
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {BG_SURFACE}; border-bottom: 1px solid {BORDER};")
        blayout = QHBoxLayout(bar)
        blayout.setContentsMargins(12, 8, 12, 8)
        blayout.setSpacing(8)

        blayout.addWidget(QLabel("当前人物:"))
        self._char_combo = QComboBox()
        self._char_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {BG_DARK}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER}; border-radius: 4px;
                padding: 4px 8px; min-width: 120px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {BG_SURFACE}; color: {TEXT_PRIMARY};
                selection-background-color: {BG_SURFACE_LIGHT};
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
                background-color: {BG_DARK}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER}; border-radius: 4px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border-color: {PRIMARY}; }}
        """)
        blayout.addWidget(self._char_name_edit)

        add_btn = QPushButton("+ 添加")
        add_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {ACCENT_GREEN}; color: white;
                border: none; border-radius: 4px; padding: 4px 12px; font-size: 12px; }}
            QPushButton:hover {{ background-color: #7ab85e; }}
        """)
        add_btn.clicked.connect(self._on_add_character)
        blayout.addWidget(add_btn)

        del_btn = QPushButton("删除")
        del_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {ACCENT_RED}; color: white;
                border: none; border-radius: 4px; padding: 4px 12px; font-size: 12px; }}
            QPushButton:hover {{ background-color: #d05a5a; }}
            QPushButton:disabled {{ background-color: #555; }}
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
        self._skills_page._skill_widgets  # ensure initialized
        # Connect skill changes to market recalc
        for name, slider in self._skills_page._skill_widgets.items():
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
            }
        }
        self._char_combo.addItem(name, name)
        self._char_combo.setCurrentIndex(self._char_combo.count() - 1)

    def _on_delete_character(self):
        """删除当前角色"""
        if len(self._all_data["characters"]) <= 1:
            return
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除角色「{self._current_char_name}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
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
