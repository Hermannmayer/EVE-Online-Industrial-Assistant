"""技能键（中文名）常量 —— `core/` 与 `domain/` 层技能名的**唯一来源**。

为什么放在 `core/` 而不是 `services/terminology.py`：
    - `domain/` 是纯函数层，禁止 import `services/`（分层铁律）；
    - 但制造/科研/贸易/精炼公式都要按**中文技能名**从 `char_config.json` 的
      `skills` 字典取值（例如 `skills.get("工业理论")`）。这些中文名原本散落在
      domain/core 各处硬编码，改名/新增技能时容易漏改一处就静默取到 0 级。

分层口径（不要反过来）：
    - `core/` / `domain/`：本模块的中文常量，只做「取值键」；不查 DB、不查术语服务。
    - `services/terminology.py` + `data/terminology.json`：UI/查询层的术语来源
      （英文名 ↔ 中文名映射）。本模块的每个中文名都必须在 `terminology.json` 的
      `skill_names` 里注册 —— 由 `tests/test_skill_keys.py` 护栏保证。
    - UI 层仍然走 `services.terminology`，**不要**从 QML/桥里 import 本模块。

取值契约：常量值就是 `char_config.json` 里 `skills` 字典的键，必须与 SDE
`item.zh_name`（CCP 官方中文名）一致；`tests/test_skill_keys.py` 同时校验
「在 terminology.json 注册」与「取值为非空、互不重复」。
"""

from __future__ import annotations

from typing import Final

# ── 制造 / 科研（domain/formulas.py、domain/research.py、domain/scoring.py）──
INDUSTRY: Final[str] = "工业理论"  # Industry（3380）制造时间 -4%/级
ADVANCED_INDUSTRY: Final[str] = "高级工业理论"  # Advanced Industry（3388）制造/研究 -3%/级
SCIENCE: Final[str] = "科学原理"  # Science（3402）拷贝速度 +5%/级
RESEARCH: Final[str] = "研究概论"  # Research（3403）TE 研究速度 +5%/级
METALLURGY: Final[str] = "冶金学"  # Metallurgy（3409）ME 研究速度 +5%/级
REACTIONS: Final[str] = "反应理论"  # Reactions（45746）反应时间 -4%/级

# ── 科研/工程技能（发明成功率取两个科学技能；蓝图所需技能的「每级 -1%」判定）──
HIGH_ENERGY_PHYSICS: Final[str] = "高能物理学"  # High Energy Physics
PLASMA_PHYSICS: Final[str] = "等离子物理学"  # Plasma Physics
ELECTROMAGNETIC_PHYSICS: Final[str] = "电磁物理学"  # Electromagnetic Physics
GRAVITON_PHYSICS: Final[str] = "引力子物理学"  # Graviton Physics
NUCLEAR_PHYSICS: Final[str] = "核芯物理学"  # Nuclear Physics
MECHANICAL_ENGINEERING: Final[str] = "机械工程学"  # Mechanical Engineering
ELECTRONIC_ENGINEERING: Final[str] = "电子工程学"  # Electronic Engineering
QUANTUM_PHYSICS: Final[str] = "量子物理学"  # Quantum Physics

# ── 高级船体建造研究（蓝图所需技能；也是 T1 舰船建造链的现行名）──
ADVANCED_SMALL_SHIP_CONSTRUCTION: Final[str] = "高级小型舰船建造研究"  # Advanced Small Ship Construction
ADVANCED_MEDIUM_SHIP_CONSTRUCTION: Final[str] = "高级中型舰船建造研究"  # Advanced Medium Ship Construction
ADVANCED_LARGE_SHIP_CONSTRUCTION: Final[str] = "高级大型舰船建造研究"  # Advanced Large Ship Construction
ADVANCED_INDUSTRIAL_SHIP_CONSTRUCTION: Final[str] = "高级工业舰船建造研究"  # Advanced Industrial Ship Construction

# ── 精炼（core/eve_formulas.py）──
REPROCESSING: Final[str] = "提炼学概论"  # Reprocessing（3385）精炼产出 +3%/级
REPROCESSING_EFFICIENCY: Final[str] = "提炼效率理论"  # Reprocessing Efficiency（3389）+2%/级

# ── 贸易 / 市场（core/eve_formulas.py、core/char_settings_common.py）──
BROKER_RELATIONS: Final[str] = "经纪人关系学"  # Broker Relations
ADVANCED_BROKER_RELATIONS: Final[str] = "高级经纪人关系学"  # Advanced Broker Relations
ACCOUNTING: Final[str] = "会计学"  # Accounting
TRADE: Final[str] = "贸易学"  # Trade（订单数 +4/级）
RETAIL: Final[str] = "零售技巧"  # Retail（订单数 +8/级）
WHOLESALE: Final[str] = "批发技巧"  # Wholesale（订单数 +16/级）
TYCOON: Final[str] = "商业巨头"  # Tycoon（订单数 +32/级）

# ── 产线容量（services/char_capacity.py；同时是 char_config.json 的现行键）──
MASS_PRODUCTION: Final[str] = "批量生产学"  # Mass Production（制造线 +1/级）
ADVANCED_MASS_PRODUCTION: Final[str] = "高级量产技术"  # Advanced Mass Production（制造线 +1/级）
LABORATORY_OPERATION: Final[str] = "实验室运作理论"  # Laboratory Operation（科研线 +1/级）
ADVANCED_LABORATORY_OPERATION: Final[str] = "高级实验室运作理论"  # Advanced Laboratory Operation（科研线 +1/级）
MASS_REACTIONS: Final[str] = "大规模反应理论"  # Mass Reactions（反应线 +1/级）
ADVANCED_MASS_REACTIONS: Final[str] = "高级大规模反应理论"  # Advanced Mass Reactions（反应线 +1/级）

#: 全部常量值 —— 护栏测试遍历用（新增常量记得加进来）。
ALL_SKILL_KEYS: Final[tuple[str, ...]] = (
    INDUSTRY,
    ADVANCED_INDUSTRY,
    SCIENCE,
    RESEARCH,
    METALLURGY,
    REACTIONS,
    HIGH_ENERGY_PHYSICS,
    PLASMA_PHYSICS,
    ELECTROMAGNETIC_PHYSICS,
    GRAVITON_PHYSICS,
    NUCLEAR_PHYSICS,
    MECHANICAL_ENGINEERING,
    ELECTRONIC_ENGINEERING,
    QUANTUM_PHYSICS,
    ADVANCED_SMALL_SHIP_CONSTRUCTION,
    ADVANCED_MEDIUM_SHIP_CONSTRUCTION,
    ADVANCED_LARGE_SHIP_CONSTRUCTION,
    ADVANCED_INDUSTRIAL_SHIP_CONSTRUCTION,
    REPROCESSING,
    REPROCESSING_EFFICIENCY,
    BROKER_RELATIONS,
    ADVANCED_BROKER_RELATIONS,
    ACCOUNTING,
    TRADE,
    RETAIL,
    WHOLESALE,
    TYCOON,
    MASS_PRODUCTION,
    ADVANCED_MASS_PRODUCTION,
    LABORATORY_OPERATION,
    ADVANCED_LABORATORY_OPERATION,
    MASS_REACTIONS,
    ADVANCED_MASS_REACTIONS,
)

__all__ = [
    "ACCOUNTING",
    "ADVANCED_BROKER_RELATIONS",
    "ADVANCED_INDUSTRY",
    "ADVANCED_LABORATORY_OPERATION",
    "ADVANCED_LARGE_SHIP_CONSTRUCTION",
    "ADVANCED_MASS_PRODUCTION",
    "ADVANCED_MASS_REACTIONS",
    "ADVANCED_MEDIUM_SHIP_CONSTRUCTION",
    "ADVANCED_SMALL_SHIP_CONSTRUCTION",
    "ADVANCED_INDUSTRIAL_SHIP_CONSTRUCTION",
    "ALL_SKILL_KEYS",
    "BROKER_RELATIONS",
    "ELECTROMAGNETIC_PHYSICS",
    "ELECTRONIC_ENGINEERING",
    "GRAVITON_PHYSICS",
    "HIGH_ENERGY_PHYSICS",
    "INDUSTRY",
    "LABORATORY_OPERATION",
    "MASS_PRODUCTION",
    "MASS_REACTIONS",
    "MECHANICAL_ENGINEERING",
    "METALLURGY",
    "NUCLEAR_PHYSICS",
    "PLASMA_PHYSICS",
    "QUANTUM_PHYSICS",
    "REACTIONS",
    "REPROCESSING",
    "REPROCESSING_EFFICIENCY",
    "RESEARCH",
    "RETAIL",
    "SCIENCE",
    "TRADE",
    "TYCOON",
    "WHOLESALE",
]
