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
# 科研作业列（仅拷贝/发明/研究行有值；其余行显示 —）
COL_SUCCESS_RATE = 19
COL_DECRYPTOR = 20

NUM_COLUMNS = 21

# 固定窄列宽度（px）：备料勾选列需容纳 8px padding + 16px 复选框 + 余量；图标列适配 32px 图标；
# 类别列仅显示 16px 自绘图标，与图标列同一逻辑（窄列不被内容/表头撑宽）
FIXED_WIDTHS = {COL_CHECKBOX: 34, COL_ICON: 36, COL_CATEGORY: 32}

# 文本易过长的列：resizeColumnsToContents() 后按此封顶，
# 否则长备注/蓝图名会把整张表推到远超窗口宽度（产品列为 Stretch，由视口兜底，无需封顶）
MAX_CONTENT_WIDTHS = {
    COL_NOTES: 160,
    COL_BLUEPRINT: 160,
    COL_FACILITY: 120,
    COL_OUTPUT: 120,
    COL_DECRYPTOR: 130,
}
