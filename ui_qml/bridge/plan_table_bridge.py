"""生产计划表的 Python ↔ QML 桥。

**只做转发**：所有业务动作（启动/下线/删行/拆解/落库…）仍留在
`ui_pyside6/views/industry/plan_table.py` 的 `PlanTable` 里，本类只把 QML 的
调用翻译成对它的方法调用并把结果整形回去。这样迁移期只有一个业务副本，
QML 与 Widgets 两条路径不会各写一套逻辑。

QML 侧以 context property `bridge` 注入（见 `ui_qml/host.PageHost`）。

行号语义：QML 传来的一律是**过滤后的行号**（表格里看到的第 N 行），
与 `PlanTableModel.get_plan()` / `_row_map()` 的口径一致。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, QItemSelection, QItemSelectionModel, QObject, Qt, Signal, Slot
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication

from ui_qml.models.industry_models import PlanTableModel
from ui_qml.models.plan_table_constants import (
    COL_PRODUCT,
    FIXED_WIDTHS,
    MAX_CONTENT_WIDTHS,
    NUM_COLUMNS,
)
from ui_qml.theme import registry as theme

if TYPE_CHECKING:
    from ui_qml.models.plan_qml_model import PlanQmlModel

__all__ = ["PlanTableBridge"]

# 产品列最小宽度（「不超过可用空间一半」的上限策略在 QML 侧按视口算）
_PRODUCT_MIN_WIDTH = 120

#: 表头文字两侧的留白（列宽**下限**用）。
#:
#: 表头 delegate 的 Text 左右各留 `6 * fontScale`；当该列正是排序列时，排序箭头
#: （10px）与它左侧的 2px 间隙也占在同一格里 —— 即 6 + 2 + 10 + 6 = 24。
#: 下限按 24 取，「被排序的窄列」表头才不会省略成「…」。
_HEADER_TEXT_MARGIN = 24

#: 数据格文字两侧的留白（列宽按内容撑开时用）。
#:
#: 数据格的 Text 左 8 + 右 6 = 14，且 `elide` 在「文字宽 ≥ 可用宽」时就省略 ——
#: 卡到与文字同宽会出现「最后一个字变省略号」，所以给到 16 留一点余量。
_BODY_TEXT_MARGIN = 16


def _header_metrics() -> QFontMetrics:
    """表头字体（11px）的度量。表头字号与数据格不同，必须分开量。"""
    font = QFont(theme.FONT_FAMILY)
    font.setPixelSize(theme.fs(11))
    return QFontMetrics(font)


def _header_min_width(col: int) -> int:
    """该列的**下限**宽度 = 表头文字宽 + 留白。

    **下限不能再取 `DEFAULT_WIDTHS` 那种「按内容形态拍出来的经验值」**：
    备注列空着也占 130px、蓝图列占 160px，非产品列加起来 1826px ——
    1400px 宽的窗口里根本铺不下，用户看到的就是「后面几列被挤出视口」。
    按表头量出来就够：没内容的列只占表头宽，有内容的列会被实测撑开（见 `autofitWidths`）。
    """
    return _header_metrics().horizontalAdvance(PlanTableModel._HEADERS[col]) + _HEADER_TEXT_MARGIN


def _measured_width(col: int, widest_text: int) -> int:
    """按实测内容算该列宽度（未封顶）。`widest_text` = 该列最宽单元格文字宽。

    宽度 = max(表头所需, 最宽内容 + 文字留白)。**不再取 `DEFAULT_WIDTHS` 当兜底值** ——
    那是「按内容形态拍的经验值」，会把空列撑到 130/160px。

    但下限也不能只按内容给：`elide` 是拿**实际列宽**与文字比，而这里只是 `QFontMetrics`
    的前进宽度估算，两者在「装饰字符 + 居中列」上能差出十几个像素（实测：组号列的
    「0」量出 7px，按它给宽会把数字挤掉）。所以按**最宽内容 + `_BODY_TEXT_MARGIN`**
    留出余量，与表头所需取大者。
    """
    return max(_header_min_width(col), widest_text + _BODY_TEXT_MARGIN)


class PlanTableBridge(QObject):
    """生产计划表桥。`_table` 是 `PlanTable` 实例（避免循环导入用 Any 标注）。"""

    #: 列宽被表头拖拽改变 → QML 侧持久化用
    columnResized = Signal(int, int)
    #: 列可见性变化
    columnVisibilityChanged = Signal(int, bool)
    #: 排序状态变化
    sortChanged = Signal()
    #: 模型实例被换掉（`set_model`）
    modelChanged = Signal()
    #: 模型内容被整体替换（`set_plans` → `beginResetModel/endResetModel`）
    rowsReset = Signal()
    #: 请求 QML 把表格滚到指定纵向位置（恢复页面状态用）
    scrollRestoreRequested = Signal(float)

    def __init__(self, table: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._table = table
        self._hidden_columns: set[int] = set()
        self._widths: dict[int, int] = {}
        self._scroll_y: float = 0.0
        self._observed_model: QObject | None = None
        self._selection: QItemSelectionModel | None = None
        #: Shift 连选的锚点（上次「点中」的行）
        self._anchor_row: int = -1

    # ── 行选中 ────────────────────────────────────────────────
    #
    # **QML `TableView` 内建的点击选中在 Qt 6.11 上不工作，所以选中由本桥自己做。**
    # 实测（最小 QML 复现，与 delegate 有无 handler 无关）：
    #   - 不给 `selectionModel` 时它恒为 null，`selectionMode` 设成 Single/Extended
    #     也不会自建；
    #   - 自己塞一个进去再点击：`currentRow` 会更新（说明按下确实到了 TableView），
    #     但选中集**只被清空、从不写入**；`selectionMode: NoSelection` 时连清空都没有。
    #   - 而程序化调 `selection.select(index, ClearAndSelect|Rows)` 一切正常，
    #     delegate 的 `selected` 会跟着变（高亮自动生效）。
    # 于是：用 `selectionBehavior: TableView.SelectionDisabled` 把 Qt 的内建选中关掉
    # （枚举里没有 `NoSelection`），选中语义在本桥实现，
    # 行为对齐 Widgets 版的 `ExtendedSelection` + `SelectRows`。

    @Property(QObject, notify=modelChanged)
    def selectionModel(self) -> QItemSelectionModel | None:
        """交给 QML 绑到 `TableView.selectionModel` 上的选中模型（模型换了就换一个）。"""
        return self._selection

    def _ensure_selection_model(self) -> QItemSelectionModel | None:
        model = self._table.get_model()
        if model is None:
            self._selection = None
            return None
        if self._selection is None or self._selection.model() is not model:
            # 父对象设为桥：所有权留在 Python 侧，QML 只是引用它
            self._selection = QItemSelectionModel(model, self)
            self._anchor_row = -1
        return self._selection

    @Slot(int)
    def selectRow(self, row: int) -> None:
        """左键点行：普通=只选它，Ctrl=切换该行，Shift=从锚点连选到该行。

        修饰键只能在这里读：QML `TapHandler.singleTapped` 给的 `eventPoint` 是
        `QEventPoint`，**没有** `modifiers` 属性（实测枚举过它的全部属性），
        而 `QGuiApplication.keyboardModifiers()` 在点击时是准的（QTest 注入的
        修饰键同样反映得出来，所以这条路径可测）。
        """
        selection = self._ensure_selection_model()
        index = self._index(row)
        if selection is None or index is None:
            return

        flags = QItemSelectionModel.SelectionFlag
        modifiers = QGuiApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            selection.select(index, flags.Toggle | flags.Rows)
            self._anchor_row = row
        elif modifiers & Qt.KeyboardModifier.ShiftModifier and self._anchor_row >= 0:
            self._select_range(selection, self._anchor_row, row)
        else:
            selection.select(index, flags.ClearAndSelect | flags.Rows)
            self._anchor_row = row

    @Slot(int)
    def ensureRowSelected(self, row: int) -> None:
        """右键落在未选中的行上时，把选中集换成该行（对齐 `QAbstractItemView`：
        点在选中集里则原样保留，于是右键菜单能作用于整个已选集合）。"""
        selection = self._ensure_selection_model()
        index = self._index(row)
        if selection is None or index is None:
            return
        if selection.isSelected(index):
            return
        flags = QItemSelectionModel.SelectionFlag
        selection.select(index, flags.ClearAndSelect | flags.Rows)
        self._anchor_row = row

    def _select_range(self, selection: QItemSelectionModel, anchor: int, row: int) -> None:
        model = self._table.get_model()
        if model is None:
            return
        first, last = sorted((anchor, row))
        span = QItemSelection(model.index(first, 0), model.index(last, 0))
        flags = QItemSelectionModel.SelectionFlag
        # 连选是「整体替换」：先按区间重设，再补上 Rows 让整行高亮
        selection.select(span, flags.ClearAndSelect | flags.Rows)

    def _index(self, row: int):
        model = self._table.get_model()
        if model is None or not 0 <= row < model.rowCount():
            return None
        return model.index(row, 0)

    @Slot(result=list)
    def selectedRows(self) -> list[int]:
        """当前选中的行号（升序）。

        读不到时返回空表，调用方（`rowsForMenu`）会退化成「只操作右键点中的那一行」——
        比批量操作打错目标安全。
        """
        selection = self._selection
        if selection is None:
            return []
        return sorted({int(index.row()) for index in selection.selectedRows(0)})

    # ── 滚动位置（页面状态保存/恢复） ────────────────────────────

    @Property(float, constant=False)
    def scrollY(self) -> float:
        return self._scroll_y

    def scroll_position(self) -> float:
        """给 Python 侧读的普通方法。

        直接读 `self.scrollY` 在 mypy 眼里是 `Property` 描述符而不是 float
        （PySide6 的桩没把描述符协议建模出来），故另给一个直取字段的入口。
        """
        return self._scroll_y

    @Slot(float)
    def reportScroll(self, y: float) -> None:
        """QML 滚动时回报当前位置（`contentY`）。"""
        self._scroll_y = float(y)

    def request_scroll_restore(self, y: float) -> None:
        self._scroll_y = float(y)
        self.scrollRestoreRequested.emit(float(y))

    # ── 模型 ──────────────────────────────────────────────────

    @Property(QObject, notify=modelChanged)
    def model(self) -> PlanQmlModel | None:
        got: PlanQmlModel | None = self._table.get_model()
        return got

    def notify_model_changed(self) -> None:
        """`PlanTable.set_model` 之后调用，让 QML 的 TableView 换绑到新模型。"""
        model = self._table.get_model()
        # 同时盯住模型的**内容重置**：工业页重载计划走的是 `model.set_plans(rows)`
        # （复用同一个模型实例，不换绑），只有 `modelReset` 能让列宽按新数据重量一次。
        # 漏掉这一步的实际表现：首次加载时模型还是空的，列宽就永远停在「只够放表头」
        # 的宽度上，「生产中」被省略成「生产…」（实测踩过）。
        if model is not None and model is not self._observed_model:
            model.modelReset.connect(self._on_model_reset)
            self._observed_model = model
        self._ensure_selection_model()
        self.modelChanged.emit()

    def _on_model_reset(self) -> None:
        """表格整体换数据（`set_plans`）后，Shift 连选的锚点必须失效。

        选中集本身由 `QItemSelectionModel` 跟着 `modelReset` 自己清空，
        但锚点是我们自己存的 —— 不清就会跨到上一个数据集的行号上，
        连选出用户根本没见过的区间。
        """
        self._anchor_row = -1
        self.rowsReset.emit()

    @Property(list, constant=True)
    def columns(self) -> list[dict]:
        """列定义（静态部分）：[{index, title, width, fixed, product, minWidth, maxWidth, visible}]。

        `width` 与 `visible` 是**初始值**：QML 侧自己维护可变副本（拖拽/勾选时改它），
        同时回调 `setColumnWidth` / `setColumnVisible` 让本桥记住，
        这样页面重建（切主题、重挂宿主）后仍能恢复用户调过的列宽/列可见性。

        `width` 初值取「表头宽 + 留白」而不是按内容形态拍的经验值 —— 见 `_header_min_width`。
        """
        out: list[dict] = []
        for i, title in enumerate(PlanTableModel._HEADERS):
            out.append(
                {
                    "index": i,
                    "title": title,
                    "width": self._widths.get(i, FIXED_WIDTHS.get(i, _header_min_width(i))),
                    "fixed": i in FIXED_WIDTHS,
                    "product": i == COL_PRODUCT,
                    "minWidth": _PRODUCT_MIN_WIDTH if i == COL_PRODUCT else 24,
                    "maxWidth": MAX_CONTENT_WIDTHS.get(i, 0),  # 0 = 不封顶
                    "visible": i not in self._hidden_columns,
                }
            )
        return out

    @Property(int, constant=True)
    def columnCount(self) -> int:
        return NUM_COLUMNS

    @Property(int, notify=sortChanged)
    def sortColumn(self) -> int:
        model = self._table.get_model()
        return int(getattr(model, "sort_column", -1)) if model is not None else -1

    @Property(bool, notify=sortChanged)
    def sortAscending(self) -> bool:
        model = self._table.get_model()
        return bool(getattr(model, "sort_ascending", True)) if model is not None else True

    # ── 表头 ─────────────────────────────────────────────────

    @Slot(int)
    def sortBy(self, column: int) -> None:
        """点表头：同列反向、换列从升序开始（与 QTableView 一致）。"""
        from PySide6.QtCore import Qt

        model = self._table.get_model()
        if model is None:
            return
        if model.sort_column == column:
            order = Qt.SortOrder.DescendingOrder if model.sort_ascending else Qt.SortOrder.AscendingOrder
        else:
            order = Qt.SortOrder.AscendingOrder
        model.sort(column, order)
        self.sortChanged.emit()

    @Slot(int, int)
    def setColumnWidth(self, column: int, width: int) -> None:
        self._widths[column] = max(24, int(width))
        self.columnResized.emit(column, self._widths[column])

    @Slot(int, result=bool)
    def isColumnWidthUserSet(self, column: int) -> bool:
        """该列宽度是否被用户拖过 —— 拖过的列不再被内容自适应覆盖。"""
        return column in self._widths

    @Slot(int, bool)
    def setColumnVisible(self, column: int, visible: bool) -> None:
        """切换列可见性；至少保留 1 列（与 Widgets 版 `_toggle_column` 同规则）。"""
        if not visible:
            remaining = [c for c in range(NUM_COLUMNS) if c != column and c not in self._hidden_columns]
            if not remaining:
                return
        if visible:
            self._hidden_columns.discard(column)
        else:
            self._hidden_columns.add(column)
        self.columnVisibilityChanged.emit(column, visible)

    @Slot(int, result=bool)
    def columnVisible(self, column: int) -> bool:
        return column not in self._hidden_columns

    @Slot(result=list)
    def autofitWidths(self) -> list:
        """按**表头 + 实际内容**实测每列宽度；不参与自适应的列返回 0。

        替代旧实现的 `QTableView.resizeColumnsToContents()` + `MAX_CONTENT_WIDTHS` 封顶：
        QML 的 `TableView` 没有按内容自适应的能力，只有 `columnWidthProvider`，
        所以宽度必须在这里量好。

        用 `QFontMetrics` 而不是「字数 × 字号」估算，因为字号能被用户调到 2 倍，
        而且量到多少就是多少（实测 QML `Text.implicitWidth` 与 `QFontMetrics` 一致）。

        **下限 = 表头文字宽 + 留白**（`_header_min_width`），不是 `DEFAULT_WIDTHS`。
        旧下限是「按内容形态拍的经验值」（备注 130 / 蓝图 160 / 解码器 110…），
        于是**空列也占一大片**，非产品列加起来 1826px —— 1400px 的窗口里铺不下，
        用户看到的正是「后面几列被挤出视口」。按表头量下限后没内容的列只占表头宽。

        每列宽度 = `max(表头所需, 最宽内容 + 文字留白)`，再按 `MAX_CONTENT_WIDTHS` 封顶
        （见 `_measured_width`）。**模型为空时只剩表头所需** —— 首帧模型还没装数据也不会
        量出一排装不下表头的窄列。
        """
        model = self._table.get_model()
        if model is None:
            return []

        body_font = QFont(theme.FONT_FAMILY)
        body_font.setPixelSize(theme.fs(12))
        body_metrics = QFontMetrics(body_font)

        rows = model.rowCount()
        text_role = Qt.ItemDataRole.UserRole + 1  # PlanQmlModel 的 `text` 角色

        out: list[int] = []
        for col in range(NUM_COLUMNS):
            if col == COL_PRODUCT or col in FIXED_WIDTHS:
                out.append(0)  # 0 = 保持原值（固定窄列 / 产品列 Stretch）
                continue
            widest = 0
            for row in range(rows):
                text = model.data(model.index(row, col), text_role)
                if text:
                    widest = max(widest, body_metrics.horizontalAdvance(str(text)))
            width = _measured_width(col, widest)
            cap = MAX_CONTENT_WIDTHS.get(col)
            out.append(min(width, cap) if cap else width)
        return out

    # ── 单元格交互 ────────────────────────────────────────────

    @Slot(int, int)
    def activate(self, row: int, column: int) -> None:
        """单击单元格：勾选 / 绑蓝图 / 折叠 / 下线（对齐 `_on_cell_clicked`）。"""
        self._table._on_cell_clicked_by_pos(row, column)

    @Slot(int)
    def doubleClick(self, row: int) -> None:
        self._table._edit_plan(row)

    #: `PlanQmlModel.ROLE_NAMES` 里的角色号：text = UserRole+1、editable = UserRole+6。
    #: delegate 里直接读 `model.editable` / `model.text`；点击改到 TableView 层面之后
    #: （见 `FTableClickArea` 的说明），只剩行列号，得回来查这两个角色。
    _ROLE_TEXT = Qt.ItemDataRole.UserRole + 1
    _ROLE_EDITABLE = Qt.ItemDataRole.UserRole + 6

    def _cell_data(self, row: int, column: int, role: int) -> Any:
        model = self._table.get_model()
        if model is None or row < 0 or column < 0:
            return None
        if row >= model.rowCount():
            return None
        return model.data(model.index(row, column), role)

    @Slot(int, int, result=bool)
    def isCellEditable(self, row: int, column: int) -> bool:
        """双击该格是「就地编辑」还是「开编辑对话框」（原读 delegate 的 `editable`）。"""
        return bool(self._cell_data(row, column, self._ROLE_EDITABLE))

    @Slot(int, int, result=str)
    def cellText(self, row: int, column: int) -> str:
        """就地编辑器的初始文本。"""
        return str(self._cell_data(row, column, self._ROLE_TEXT) or "")

    @Slot(int, int, str, result=bool)
    def commitEdit(self, row: int, column: int, text: str) -> bool:
        """单元格内联编辑落库（备注/人物/设施/成功率/解码器）。"""
        return bool(self._table.commit_cell_edit(row, column, text))

    @Slot(int, result=dict)
    def menuState(self, row: int) -> dict:
        """行右键菜单需要的状态：决定哪些项可见、勾选文案。"""
        model = self._table.get_model()
        plan = model.get_plan(row) if model is not None else None
        return {
            "valid": bool(plan),
            "synthetic": bool(plan.get("_synthetic")) if plan else False,
            "status": str((plan or {}).get("status") or "").lower(),
            "materialsReady": bool((plan or {}).get("materials_ready", 0)),
        }

    # ── 菜单动作（逐个具名，避免字符串分发的错别字风险） ──────────

    @Slot("QVariantList")
    def editPlans(self, rows: list) -> None:
        rows = [int(r) for r in rows]
        if len(rows) > 1:
            self._table._batch_edit_plans(rows)
        elif rows:
            self._table._edit_plan(rows[0])

    @Slot(int)
    def bindBlueprint(self, row: int) -> None:
        self._table._show_blueprint_picker(row)

    @Slot(int)
    def viewCostBreakdown(self, row: int) -> None:
        self._table._view_cost_breakdown(row)

    @Slot("QVariantList", int)
    def setMaterialsReady(self, rows: list, value: int) -> None:
        for r in rows:
            self._table._set_materials_ready(int(r), int(value))

    @Slot("QVariantList")
    def startPlans(self, rows: list) -> None:
        for r in rows:
            self._table._start_plan(int(r))

    @Slot("QVariantList")
    def undoStartPlans(self, rows: list) -> None:
        for r in rows:
            self._table._undo_start(int(r))

    @Slot("QVariantList")
    def completePlans(self, rows: list) -> None:
        self._table._complete_rows_with_dialog([int(r) for r in rows])

    @Slot("QVariantList")
    def resetForReusePlans(self, rows: list) -> None:
        for r in rows:
            self._table._reset_for_reuse(int(r))

    @Slot(int)
    def addNotes(self, row: int) -> None:
        self._table._add_notes(row)

    @Slot(int)
    def copyBlueprintName(self, row: int) -> None:
        self._table._copy_blueprint_name(row)

    @Slot("QVariantList")
    def decomposeParent(self, rows: list) -> None:
        self._table._decompose_parent([int(r) for r in rows])

    @Slot("QVariantList")
    def adjustChildren(self, rows: list) -> None:
        self._table._adjust_children([int(r) for r in rows])

    @Slot("QVariantList")
    def massParallel(self, rows: list) -> None:
        self._table._mass_parallel([int(r) for r in rows])

    @Slot("QVariantList")
    def recalcChildren(self, rows: list) -> None:
        self._table._recalc_children([int(r) for r in rows])

    @Slot("QVariantList")
    def deletePlans(self, rows: list) -> None:
        self._table._delete_rows([int(r) for r in rows])

    @Slot()
    def toggleSharedCollapse(self) -> None:
        model = self._table.get_model()
        if model is not None:
            model.toggle_collapse(-1)

    # ── 主题 ─────────────────────────────────────────────────

    @Slot()
    def refreshColors(self) -> None:
        model = self._table.get_model()
        refresh = getattr(model, "refresh_colors", None)
        if callable(refresh):
            refresh()
