"""生产计划表格列常量。"""

# ── 列索引常量（与 PlanTableModel._HEADERS 对齐） ────────────
COL_CHECKBOX = 0
COL_CATEGORY = 1
COL_ICON = 2
COL_PRODUCT = 3
COL_NOTES = 4
COL_GROUP = 5
COL_CHILD_LEVEL = 6
COL_STATUS = 7
COL_CHAR_NAME = 8
COL_RUNS = 9
COL_BLUEPRINT = 10
COL_TIME = 11
COL_OUTPUT_RATE = 12
COL_FACILITY = 13
COL_OUTPUT = 14
COL_COST = 15
COL_PROFIT = 16
COL_MARKET_MARGIN = 17
COL_PERSONAL_MARGIN = 18

NUM_COLUMNS = 19

# 固定窄列宽度（px）：备料勾选列需容纳 8px padding + 16px 复选框 + 余量；图标列适配 32px 图标；
# 类别列仅显示 16px 自绘图标，与图标列同一逻辑（窄列不被内容/表头撑宽）
# 图标/类别列按**表头文字宽**取整（"图标" 在 11px 下约 22px + 左右内边距），
# 写死 32 会让表头被省略成「…」
FIXED_WIDTHS = {COL_CHECKBOX: 34, COL_ICON: 40, COL_CATEGORY: 40}

# 其余列的宽度**不在这里写死**：由 `PlanTableBridge.autofitWidths()` 用 `QFontMetrics`
# 按「表头宽」为下限、按实际内容实测（封顶见 `MAX_CONTENT_WIDTHS`）。
#
# 历史上这里有一张 `DEFAULT_WIDTHS`（备注 130 / 蓝图 160 / 解码器 110…，按内容形态拍的
# 经验值），并把它当自适应的**下限** —— 结果**空的备注列也占 130px**，非产品列加起来
# 1826px，1400px 宽的窗口里后几列直接被挤出视口（用户反馈「列显示不全」）。
# 已删除。产品列本来就不在此表内 —— 它是 Stretch，宽度吃满视口剩余空间。


# 文本易过长的列：实测宽度按此封顶，
# 否则长备注/蓝图名会把整张表推到远超窗口宽度（产品列为 Stretch，由视口兜底，无需封顶）
MAX_CONTENT_WIDTHS = {
    COL_NOTES: 160,
    COL_BLUEPRINT: 160,
    COL_FACILITY: 120,
    COL_OUTPUT: 120,
}
