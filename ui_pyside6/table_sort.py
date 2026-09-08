"""表头排序保持工具 —— 堵住 Qt「排序箭头还在、行序却回退」的坑。

两个实测过的 Qt 行为（合起来解释了本模块存在的理由）：

1. `QTableView.setModel()` 只换模型，**不会**对新模型调用 `sort()`：
   排序箭头仍留在表头，行序却回退为模型的原始顺序；
2. `QHeaderView.setSortIndicator()` 在列/方向未变时**不发** `sortIndicatorChanged`，
   因此也不触发排序 —— 重建模型后用它在原列上「重放」排序是无效的。

所以重放必须走 `QTableView.sortByColumn()`（它无条件调用 `model.sort()`）。
"""

from PySide6.QtCore import QAbstractItemModel, Qt
from PySide6.QtWidgets import QTableView, QWidget


def init_sorting(table: QTableView) -> None:
    """开启表头点击排序，并清掉 Qt 默认的 (第 0 列, 降序) 假排序箭头。

    `setSortingEnabled(True)` 会把指示器置为 (0, 降序) 并显示箭头，但数据并没有排序 ——
    表头在说谎，也让「有没有排过序」无法从指示器判断。清成 -1 后：有箭头 == 真的排过序。
    """
    table.setSortingEnabled(True)
    table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)


class SortPreservingTableView(QTableView):
    """重建模型后自动重放表头排序的 QTableView（构造即 `init_sorting()`）。

    换模型是常态（刷新/过滤/换计划），逐调用点包一层「重建后重放」靠自觉、新增调用点会静默复发；
    这里统一在 `setModel` 内重放，调用方只需换控件类。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        init_sorting(self)

    def setModel(self, model: QAbstractItemModel | None) -> None:  # Qt 的驼峰命名，跟随父类
        header = self.horizontalHeader()
        column, order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        super().setModel(model)
        # 未排过序（-1）或清空模型时无需重放；setModel 不重置指示器，故 column 仍是用户选的那列
        if model is not None and column >= 0:
            self.sortByColumn(column, order)
