"""汇总类对话框的通用骨架（阶段 4）。

「产出总表」「人物占用」「材料总表」形状一致：**只读表格 + 一行状态文案 + 关闭**。
与其把同一套渲染写三遍，不如这里给出通用的桥与 QML，各对话框只负责
「把行算出来」。

行以**单元格列表**给出（`[{text, color}]`），而不是拼成字符串：
颜色是「利润为正染绿 / 状态按语义染色 / 有溢出标橙」这类规则算出来的，
留在 Python 侧与 Widgets 版逐条对齐，QML 只负责画。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.theme import registry as theme

__all__ = ["SummaryTableBridge", "SummaryTableQmlDialog", "cell", "fmt_isk"]

_QML_FILE = "dialogs/SummaryTableDialog.qml"


def fmt_isk(value: float) -> str:
    """大额 ISK 用 B/M/K 缩写（原本在 output/materials/research_cost 各抄了一份）。"""
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def cell(text: Any, token: str = "") -> dict:
    """一个单元格：文本 + 可选的主题色 token 名（空 = 用默认前景色）。"""
    color = str(getattr(theme, token, "") or "") if token else ""
    return {"text": str(text), "color": color}


class SummaryTableBridge(DialogBridge):
    """只读汇总表的通用桥。"""

    contentChanged = Signal()

    def __init__(self, *, title: str, columns: list[dict]) -> None:
        super().__init__()
        self._columns = columns
        self._rows: list[dict] = []
        self._status_text = ""
        self._header_text = ""
        self._empty_text = "没有数据"
        self.set_title(title)

    #: 列定义 [{title, width}]；width = 0 表示吃满剩余空间
    columns = Property(list, lambda self: list(self._columns), constant=True)
    #: 行 [{cells: [{text, color}]}]
    rows = Property(list, lambda self: list(self._rows), notify=contentChanged)
    statusText = Property(str, lambda self: self._status_text, notify=contentChanged)
    rowCount = Property(int, lambda self: len(self._rows), notify=contentChanged)
    #: 表格上方的说明行（空串 = 不占位置）。材料覆盖用它放「关联了哪些计划」
    headerText = Property(str, lambda self: self._header_text, notify=contentChanged)
    #: 空表提示。材料覆盖用它替代 Widgets 版另起一个居中 QLabel 的做法
    emptyText = Property(str, lambda self: self._empty_text, notify=contentChanged)

    def set_content(self, rows: list[dict], status_text: str, header_text: str | None = None) -> None:
        """子类在加载完成后调它。

        `header_text` 传 None 表示「保持原样」—— 有些表会分几次填内容
        （先出表头说明、再出数据），不想被后一次覆盖掉。
        """
        self._rows = rows
        self._status_text = status_text
        if header_text is not None:
            self._header_text = header_text
        self.contentChanged.emit()

    def set_empty_text(self, text: str) -> None:
        self._empty_text = str(text)
        self.contentChanged.emit()

    # ── 可选：顶栏动作 + 行内动作列（材料总表用）────────────────

    #: 顶栏动作按钮文案（空 = 不显示）
    topActionText = Property(str, lambda self: getattr(self, "_top_action_text", ""), constant=True)
    #: 是否存在行内动作列（最后一列渲染成按钮而不是文本）
    hasActionColumn = Property(bool, lambda self: getattr(self, "_has_action_column", False), constant=True)

    @Slot()
    def topAction(self) -> None:
        """顶栏动作（默认什么也不做，子类覆写）。"""

    @Slot(int)
    def copyRow(self, row: int) -> None:
        """行内动作（默认什么也不做，子类覆写）。"""

    @Slot(int, int)
    def copyCell(self, row: int, column: int) -> None:
        """双击单元格 → 复制该格文字（全项目统一的「双击 = 复制该格」）。

        复制的是**显示文本**（千分位、`fmt_isk` 缩写、状态词），也就是用户眼睛看到的那一份
        —— 拿它去游戏里搜蓝图/物品名正合适；要原始数值的地方（清单导入之类）另走专用动作。

        空文本与 `—` 占位不复制：它们不是「名字」，写进剪贴板只会把上一次复制的内容冲掉。
        """
        if not 0 <= row < len(self._rows):
            return
        cells = self._rows[row].get("cells") or []
        if not 0 <= column < len(cells):
            return
        text = str(cells[column].get("text", ""))
        if not text or text == "—":
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self.set_error(f"已复制：{text}")

    @Slot()
    def reload(self) -> None:
        """打开 / 刷新时重新取数（默认什么也不做，子类覆写）。"""


class SummaryTableQmlDialog(QmlDialog):
    """通用汇总表的 QML 版宿主。

    `qml_file` 默认为通用的汇总表页面；形状相同但需要额外控件的对话框
    （合同详情 / NPC 卖家）传自己的 QML，表格渲染仍走同一个 `FSummaryTable`。
    """

    def __init__(
        self,
        bridge: SummaryTableBridge,
        parent: Any = None,
        size: tuple[int, int] = (900, 560),
        qml_file: str = _QML_FILE,
        modeless: bool = False,
    ) -> None:
        super().__init__(qml_file, bridge, parent=parent, size=size, modeless=modeless)
        bridge.reload()

    def reload(self) -> None:
        self.bridge.reload()  # type: ignore[no-any-return]
