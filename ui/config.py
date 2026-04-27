"""
全局配置：字体、ESI 配置

路径管理请使用 core.paths 模块。
"""
from core.paths import DB_PATH, ICON_DIR

# ── Flet 字体（Windows 下使用微软雅黑） ──
CJK_FONT = "Microsoft YaHei UI"
MONO_FONT = "Consolas"

# ── ESI 配置 ──
ESI_BASE_URL = "https://esi.evetech.net/latest"
REGION_ID = 10000002  # 伏尔戈（The Forge）

# ── 图标配置 ──
ICON_SIZE = 48
