"""机库页两个对话框的桥（阶段 4b）：编辑数量 / 批量成本价。

对照旧 Widgets 版。两个类都保持原 API
（构造 → `exec()` → 读 accessor），所以调用点只换类名。

**顺带删掉了 `PasteImportDialog`**：它在 Widgets 版里就是死代码（除了
`views/__init__.py` 的再导出与一个测试，全仓零实例化），迁移不必带着它走。

复用情况：
- 编辑数量 —— 直接复用 `InputQmlDialog`（整数形态），连 QML 文件都不用新写
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from core.constants import TRADE_HUBS
from services.user_settings import get_material_price_mult, get_price_settings, set_material_price_mult
from ui_qml.bridge.input_dialog import MODE_INT, InputBridge, InputQmlDialog
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = [
    "BatchCostPriceBridge",
    "BatchCostPriceQmlDialog",
    "EditQtyBridge",
    "EditQtyQmlDialog",
]

_BATCH_QML = "dialogs/BatchCostPriceDialog.qml"

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

#: 价格来源：值 → 显示名（与 Widgets 版同一份）。
#: **不再带「吉他」前缀**：贸易中心改由同一行的下拉选（见 `BatchCostPriceBridge.hubs`）。
_SOURCES: list[tuple[str, str]] = [
    ("sell", "卖价"),
    ("buy", "买价"),
    ("avg", "均价"),
    ("manual", "手动输入价格"),
]


class BatchCostPriceBridge(DialogBridge):
    """批量成本价：**指定贸易中心**的市场价 × 材料倍率，或手动输入一个数字。

    贸易中心早先写死在吉他上（来源下拉直接叫「吉他卖价/吉他买价/吉他均价」），
    用户报「没法设置其他贸易中心的价格」—— 用户实测指的就是这个窗口
    （机库表右键「编辑成本价」弹的就是它）。现在：
      - 初值跟随「材料价格来源」的 `mat_hub`（生产规划页工具栏 / 仓库页蓝图表
        是同一份设置），认不出的 hub 名回落列表首项（Jita）；
      - 用户在窗口里改选只作用于**这一次批量设置**，不写回设置（设置页那边有它的入口）。
    """

    stateChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.set_title("批量设置成本价")
        self._source_index = 0
        #: 与生产规划页工具栏「材料倍率」共用同一个设置（settings.json price_settings.mat_mult）
        self._multiplier = float(get_material_price_mult())
        self._manual = 0.0
        configured_hub = str(get_price_settings().get("mat_hub") or "")
        self._hub_index = TRADE_HUBS.index(configured_hub) if configured_hub in TRADE_HUBS else 0

    @Property(list, constant=True)
    def sources(self) -> list[dict]:
        return [{"label": label} for _value, label in _SOURCES]

    #: 可选的贸易中心（顺序即下拉项顺序，与工具栏「区域」一致）
    hubs = Property(list, lambda self: list(TRADE_HUBS), constant=True)

    @Property(int, notify=stateChanged)
    def hubIndex(self) -> int:
        return self._hub_index

    @Slot(int)
    def setHubIndex(self, index: int) -> None:
        if not 0 <= index < len(TRADE_HUBS):
            return
        self._hub_index = index
        self.stateChanged.emit()

    def hub_name(self) -> str:
        """这次批量取价用哪个贸易中心（调用方拿它查 `TRADE_HUB_IDS`）。"""
        return TRADE_HUBS[self._hub_index]

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
        super().__init__(_BATCH_QML, bridge, parent=parent, size=(560, 260))
        self._batch_bridge = bridge

    def price_type(self) -> str:
        return self._batch_bridge.price_type()

    def discount(self) -> float:
        return self._batch_bridge.discount()

    def manual_price(self) -> float:
        return self._batch_bridge.manual_price()

    def hub_name(self) -> str:
        """这次批量取价用的贸易中心名（调用方查 `core.constants.TRADE_HUB_IDS`）。"""
        return self._batch_bridge.hub_name()
