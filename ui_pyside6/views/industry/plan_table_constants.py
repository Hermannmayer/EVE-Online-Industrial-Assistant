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
# 图标/类别列按**表头文字宽**取整（"图标" 在 11px 下约 22px + 左右内边距），
# 写死 32 会让表头被省略成「…」
FIXED_WIDTHS = {COL_CHECKBOX: 34, COL_ICON: 40, COL_CATEGORY: 40}

# 其余列的默认宽度（px）。QML 的 TableView **没有** resizeColumnsToContents，
# 宽度只能由 provider 逐列给死，故按各列实际内容形态标定：
#   - 表头文字宽（11px 下 "市场利润率%" ≈ 66px + 内边距 + 排序箭头）
#   - 内容形态（金额 10 位数 / "10-20没图 差2张" / "剩余 1d10h0m" / 状态 4 个汉字）
# 这些是**下限**：`PlanTableBridge.autofitWidths()` 量到更宽的内容时只会加宽。
# 产品列不在此表内 —— 它是 Stretch，宽度吃满视口剩余空间。
DEFAULT_WIDTHS = {
    COL_NOTES: 130,
    COL_GROUP: 56,
    COL_CHILD_LEVEL: 56,
    COL_STATUS: 96,
    COL_CHAR_NAME: 96,
    COL_RUNS: 80,
    COL_BLUEPRINT: 160,
    COL_TIME: 110,
    COL_OUTPUT_RATE: 90,
    COL_FACILITY: 100,
    COL_OUTPUT: 100,
    COL_COST: 110,
    COL_PROFIT: 110,
    COL_MARKET_MARGIN: 106,
    COL_PERSONAL_MARGIN: 106,
    COL_SUCCESS_RATE: 96,
    COL_DECRYPTOR: 110,
}


# 文本易过长的列：resizeColumnsToContents() 后按此封顶，
# 否则长备注/蓝图名会把整张表推到远超窗口宽度（产品列为 Stretch，由视口兜底，无需封顶）
MAX_CONTENT_WIDTHS = {
    COL_NOTES: 160,
    COL_BLUEPRINT: 160,
    COL_FACILITY: 120,
    COL_OUTPUT: 120,
    COL_DECRYPTOR: 130,
}
