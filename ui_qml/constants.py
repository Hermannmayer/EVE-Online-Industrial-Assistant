"""两套 UI 共享的展示常量。

这里放「只影响界面怎么分组/怎么显示、不影响业务计算」的常量。**配色不在此列**
—— 颜色一律从 `ui_qml.theme.registry` 取（铁律）。
"""

from services.terminology import term

__all__ = ["CATEGORIES", "MFG_CATEGORIES"]

#: 「全部物品查询」的分类下拉项（含不可制造项）
CATEGORIES = [
    term.market_category("all"),
    term.market_category("unmanufacturable"),
    term.market_category("t1_mfg"),
    term.market_category("t2_invention"),
    term.market_category("faction"),
    term.market_category("reaction"),
    term.market_category("planetary"),
]

#: 同上，但只列可制造项（「可制造物品」对话框与对应桥用）
MFG_CATEGORIES = [
    term.market_category("all_manufacturable"),
    term.market_category("t1_mfg"),
    term.market_category("t2_invention"),
    term.market_category("faction"),
    term.market_category("reaction"),
]
