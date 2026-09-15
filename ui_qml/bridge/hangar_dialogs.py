"""机库页三个对话框的桥（阶段 4b）：编辑数量 / 批量成本价 / 手动添加。

对照 Widgets 版 `ui_pyside6/dialogs/hangar_dialogs.py`。三个类都保持原 API
（构造 → `exec()` → 读 accessor），所以四个调用点只换类名。

**顺带删掉了 `PasteImportDialog`**：它在 Widgets 版里就是死代码（除了
`views/__init__.py` 的再导出与一个测试，全仓零实例化），迁移不必带着它走。

复用情况：
- 编辑数量 —— 直接复用 `InputQmlDialog`（整数形态），连 QML 文件都不用新写
- 手动添加 —— 搜索那一半复用 `ItemSearchBridge`（与物品搜索同一份），只加数量/成本
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from services.inventory_manager import get_item_price
from services.user_settings import get_material_price_mult, set_material_price_mult
from ui_qml.bridge.input_dialog import MODE_INT, InputBridge, InputQmlDialog
from ui_qml.bridge.item_search_bridge import ItemSearchBridge
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = [
    "AddItemBridge",
    "AddItemQmlDialog",
    "BatchCostPriceBridge",
    "BatchCostPriceQmlDialog",
    "EditQtyBridge",
    "EditQtyQmlDialog",
]

_BATCH_QML = "dialogs/BatchCostPriceDialog.qml"
_ADD_QML = "dialogs/AddItemDialog.qml"

#: 数量上限（原 `QSpinBox.setRange(1, 2_000_000_000)`）
_MAX_QTY = 2_000_000_000


# ══════════════════════════════════════════════════════════════
#  编辑数量
# ══════════════════════════════════════════════════════════════


class EditQtyBridge(InputBridge):
    """编辑物品数量 —— 整数形态的取值对话框。"""

    def __init__(self, item_name: str, current_qty: int) -> None:
        super().__init__(
            f"编辑数量 — {item_name}",
            "数量:",
            MODE_INT,
            value=float(current_qty),
            minimum=0.0,
            maximum=float(_MAX_QTY),
        )


class EditQtyQmlDialog(InputQmlDialog):
    """QML 版「编辑数量」。`EditQtyDialog(item_name, qty, parent)` 的调用方原样可用。

    与原版的一点差别：原版是自由文本框，非数字返回 -1、由调用方 `qty >= 0` 兜住；
    这里是整数微调框，**输入不出非法值**，`quantity()` 恒为 0..上限。调用方的
    `>= 0` 判断留着无害。
    """

    def __init__(self, item_name: str, current_qty: int, parent: Any = None) -> None:
        super().__init__(EditQtyBridge(item_name, current_qty), parent=parent, size=(400, 190))

    def quantity(self) -> int:
        """要设置的数量。

        读的是**当前输入框的值**，不是「点确定那一刻的快照」—— 原版是文本框，
        `quantity()` 任何时候读都给你当下填的数；读快照的话，确定之前调用会拿到 0。
        """
        return int(round(self._input_bridge.value_now()))


# ══════════════════════════════════════════════════════════════
#  批量设置成本价
# ══════════════════════════════════════════════════════════════

#: 价格来源：值 → 显示名（与 Widgets 版同一份）
_SOURCES: list[tuple[str, str]] = [
    ("sell", "吉他卖价"),
    ("buy", "吉他买价"),
    ("avg", "吉他均价"),
    ("manual", "手动输入价格"),
]


class BatchCostPriceBridge(DialogBridge):
    """批量成本价：市场价 × 材料倍率，或手动输入一个数字。"""

    stateChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.set_title("批量设置成本价")
        self._source_index = 0
        #: 与生产规划页工具栏「材料倍率」共用同一个设置（settings.json price_settings.mat_mult）
        self._multiplier = float(get_material_price_mult())
        self._manual = 0.0

    @Property(list, constant=True)
    def sources(self) -> list[dict]:
        return [{"label": label} for _value, label in _SOURCES]

    #: 倍率范围与生产规划页工具栏的「材料倍率」一致（可溢价，不只是打折）。
    #: 放在桥里而不是写死在 QML：测试要断言它，也只有一个来源。
    multiplierMin = Property(float, lambda self: 0.1, constant=True)
    multiplierMax = Property(float, lambda self: 10.0, constant=True)
    #: 手动价格上限（原 `QDoubleSpinBox.setRange(0, 1e12)`）
    manualMax = Property(float, lambda self: 1e12, constant=True)

    @Property(int, notify=stateChanged)
    def sourceIndex(self) -> int:
        return self._source_index

    @Property(bool, notify=stateChanged)
    def isManual(self) -> bool:
        """手动输入时隐藏倍率、显示价格框（原 `_on_source_changed` 的搬移）。"""
        return _SOURCES[self._source_index][0] == "manual"

    @Property(float, notify=stateChanged)
    def multiplier(self) -> float:
        return self._multiplier

    @Property(float, notify=stateChanged)
    def manualPrice(self) -> float:
        return self._manual

    @Slot(int)
    def setSourceIndex(self, index: int) -> None:
        if not 0 <= index < len(_SOURCES):
            return
        self._source_index = index
        self.stateChanged.emit()

    @Slot(float)
    def setMultiplier(self, value: float) -> None:
        self._multiplier = float(value)
        self.stateChanged.emit()

    @Slot(float)
    def setManualPrice(self, value: float) -> None:
        self._manual = float(value)
        self.stateChanged.emit()

    @Slot()
    def accept(self) -> None:
        """确认时把倍率写回共享设置 —— 下次打开仍是它，生产规划页也同步。"""
        set_material_price_mult(self._multiplier)
        self.accepted.emit()

    # ── 给调用方取值（名字与原版一致）────────────────────────

    def price_type(self) -> str:
        return _SOURCES[self._source_index][0]

    def discount(self) -> float:
        return self._multiplier

    def manual_price(self) -> float:
        return self._manual


class BatchCostPriceQmlDialog(QmlDialog):
    """QML 版「批量设置成本价」。`BatchCostPriceDialog(parent)` 的调用方原样可用。"""

    def __init__(self, parent: Any = None) -> None:
        bridge = BatchCostPriceBridge()
        super().__init__(_BATCH_QML, bridge, parent=parent, size=(420, 260))
        self._batch_bridge = bridge

    def price_type(self) -> str:
        return self._batch_bridge.price_type()

    def discount(self) -> float:
        return self._batch_bridge.discount()

    def manual_price(self) -> float:
        return self._batch_bridge.manual_price()


# ══════════════════════════════════════════════════════════════
#  手动添加物品
# ══════════════════════════════════════════════════════════════


class AddItemBridge(ItemSearchBridge):
    """手动添加物品 —— 搜索那一半直接复用物品搜索的桥，本类只加数量与成本价。"""

    #: 数量/成本价变化的通知。**不复用父类的 `stateChanged`**：那是搜索结果的通知，
    #: 两者语义不同（改数量不该让 QML 以为结果集换了）；而且子类里也引用不到父类的
    #: 类属性名 —— mypy 会报 `Name "stateChanged" is not defined`。
    fieldsChanged = Signal()

    def __init__(self, hangar_name: str) -> None:
        super().__init__(f"添加物品 → {hangar_name}")
        self._quantity = 1
        self._cost = 0.0

    @Property(int, notify=fieldsChanged)
    def quantity(self) -> int:
        return self._quantity

    @Property(float, notify=fieldsChanged)
    def cost(self) -> float:
        return self._cost

    @Slot(int)
    def setQuantity(self, value: int) -> None:
        self._quantity = int(value)
        self.fieldsChanged.emit()

    @Slot(float)
    def setCost(self, value: float) -> None:
        self._cost = float(value)
        self.fieldsChanged.emit()

    @Slot(int)
    def selectRow(self, row: int) -> None:
        """选中时按市场价带出成本价（原 `_on_row_selected` 里的 `get_item_price`）。"""
        super().selectRow(row)
        item = self.selected_item()
        if item is None:
            return
        price = get_item_price(int(item["type_id"]))
        if price:
            self.setCost(float(price))

    def result_data(self) -> tuple[int, int, float] | None:
        """返回 (type_id, 数量, 成本价)；未选中物品返回 None。"""
        item = self.selected_item()
        if item is None:
            return None
        return (int(item["type_id"]), int(self._quantity), float(self._cost))


class AddItemQmlDialog(QmlDialog):
    """QML 版「手动添加物品」。`AddItemDialog(hangar_name, parent)` 的调用方原样可用。"""

    def __init__(self, hangar_name: str, parent: Any = None) -> None:
        bridge = AddItemBridge(hangar_name)
        super().__init__(_ADD_QML, bridge, parent=parent, size=(620, 520))
        self._add_bridge = bridge

    def result_data(self) -> tuple[int, int, float] | None:
        return self._add_bridge.result_data()
