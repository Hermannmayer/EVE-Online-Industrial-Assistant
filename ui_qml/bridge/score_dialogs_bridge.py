"""制造 / 贸易评分设置对话框的桥（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/score_dialogs.py` 里的 `MfgDlg` / `TradeDlg`。
两个对话框都是「一组下拉 + 一两个数值 → 点确定 → 调用方读 `get()`」的形状，
桥只负责把控件状态搬进属性、把 `get()` 的返回结构原样保留。

**一个桥服务两个对话框**（`kind` 决定字段与 `get()` 的形状），与
`input_dialog.py` 一份桥服务四种输入形态同一个套路。这不只是为了省行数 ——
**必须**如此：拆成「共用基类 + 子类」时，子类的 Property 一旦拿父类的信号当
`notify`，QML 引擎会在 `setSource` 时直接段错误（实测 PySide6 6.11.1：
两层结构 + `@Property(int, notify=Base.stateChanged)` → `access violation`，
`python -X faulthandler` 定位到 `PageHost.setSource`）。信号与属性声明在
**同一个类**里则一切正常 —— 全仓其它桥都是这个写法。

**同文件的 `ScoreW` 不过桥**：它是 `BaseBatchScoreWorker` 的后台线程，没有一行 UI，
业务实现也只有那一份。原文件按约定不删，`ScoreW` 继续从
`ui_pyside6.views.score_dialogs` 导入。

两处对齐 Widgets 版的细节（都容易被「顺手改对」而改错）：

1. **下拉框找不到值就退回第 0 项**：原版用 `QComboBox.setCurrentText()`，
   非可编辑下拉框遇到不存在的文本**不会**新增条目、也不会改当前项，
   于是停在初始的 index 0。`_combo_index()` 复刻了这个语义。
2. **`get()` 返回的 char 现查现判**：原版在 `get()` 里重新取一次人物列表，
   不在列表里就返回 "main"。这里照做（列表可能已被设置页改动）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from core.constants import TRADE_HUBS
from core.container import get_container
from core.logger import log
from services import char_config_resolver
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.icon_cache import icon_url as _icon_url

__all__ = ["KIND_MFG", "KIND_TRADE", "MfgQmlDialog", "ScoreParamsBridge", "TradeQmlDialog"]

_QML_FILE = "dialogs/ScoreParamsDialog.qml"

KIND_MFG = "mfg"
KIND_TRADE = "trade"

#: 区域下拉的条目（与 Widgets 版的 `REGIONS = TRADE_HUBS` 同一来源）
_REGIONS: list[str] = list(TRADE_HUBS)

#: 买卖价类型下拉：下标 0 = "sell"、1 = "buy"（顺序是原版的下拉顺序）
_SIDES: list[str] = ["卖单", "买单"]


def _character_names() -> list[str]:
    """人物下拉的条目。取不到人物时退化成 `["main"]`（对齐原版 `addItems(cs if cs else ["main"])`）。"""
    names = list(char_config_resolver.get_character_list())
    return names if names else ["main"]


def _combo_index(values: list[str], wanted: str) -> int:
    """`QComboBox.setCurrentText(wanted)` 之后的当前下标。

    找不到 `wanted` 时是 0 而不是 -1：非可编辑下拉框不会因为设了一个不存在的文本
    就清空当前项。原版依赖这个行为兜底（例如配置里的区域已被改名）。
    """
    try:
        return values.index(wanted)
    except ValueError:
        return 0


def _item_title(default_title: str, prefix: str, type_id: int | None) -> str:
    """带 item 的标题：`制造评分设置` → `制造评分 — 渡鸦级`。

    取不到名字（查无此 id / 库不可用）时**保持默认标题**，与原版一致 ——
    原版那里是一段 `except Exception: pass`；本仓禁止裸 pass，改为记日志。
    """
    if type_id is None:
        return default_title
    try:
        name = get_container().item_repo.get_name(int(type_id))
    except Exception:
        log.exception("评分弹窗取物品名失败 type_id=%s", type_id)
        return default_title
    if name and str(name) != str(type_id):
        return f"{prefix} — {name}"
    return default_title


class ScoreParamsBridge(DialogBridge):
    """制造 / 贸易评分设置的 QML 后端。`kind` 决定字段与 `get()` 的形状。"""

    stateChanged = Signal()

    def __init__(
        self,
        kind: str,
        default_title: str,
        prefix: str,
        *,
        type_id: int | None = None,
        hub: str = "Jita",
        sell_hub: str = "Jita",
        buy_side: str = "sell",
        sell_side: str = "sell",
        char: str = "main",
        tax: float = 0.0,
    ) -> None:
        super().__init__()
        self._kind = kind
        self._type_id = type_id
        self._characters = _character_names()
        self._icon_url = _icon_url(type_id)
        self._hub_index = _combo_index(_REGIONS, hub)
        self._sell_hub_index = _combo_index(_REGIONS, sell_hub)
        self._buy_side_index = 0 if buy_side == "sell" else 1
        self._sell_side_index = 0 if sell_side == "sell" else 1
        self._tax = float(tax or 0)
        # 「不在人物列表里就退回 main」是原版 `setCurrentText` 那一行的语义
        wanted_char = char if char in self._characters else "main"
        self._char_index = _combo_index(self._characters, wanted_char)
        self.set_title(_item_title(default_title, prefix, type_id))

    # ── 给 QML 读的属性 ───────────────────────────────────────

    kind = Property(str, lambda self: self._kind, constant=True)
    #: 贸易模式才显示的字段（买入/卖出/买价/卖价）—— 与制造模式的字段互斥
    isTrade = Property(bool, lambda self: self._kind == KIND_TRADE, constant=True)

    @Property(str, constant=True)
    def iconUrl(self) -> str:
        return self._icon_url

    @Property(bool, constant=True)
    def hasIcon(self) -> bool:
        return self._icon_url != ""

    @Property(list, constant=True)
    def hubs(self) -> list[str]:
        return list(_REGIONS)

    @Property(list, constant=True)
    def sides(self) -> list[str]:
        return list(_SIDES)

    @Property(list, constant=True)
    def characters(self) -> list[str]:
        return list(self._characters)

    @Property(int, notify=stateChanged)
    def hubIndex(self) -> int:
        """制造模式是「中心」，贸易模式是「买入」。"""
        return self._hub_index

    @Property(int, notify=stateChanged)
    def sellHubIndex(self) -> int:
        return self._sell_hub_index

    @Property(int, notify=stateChanged)
    def buySideIndex(self) -> int:
        return self._buy_side_index

    @Property(int, notify=stateChanged)
    def sellSideIndex(self) -> int:
        return self._sell_side_index

    @Property(int, notify=stateChanged)
    def charIndex(self) -> int:
        return self._char_index

    @Property(float, notify=stateChanged)
    def tax(self) -> float:
        return self._tax

    # ── QML 写回来的槽 ────────────────────────────────────────

    @Slot(int)
    def setHubIndex(self, index: int) -> None:
        if 0 <= index < len(_REGIONS):
            self._hub_index = index
            self.stateChanged.emit()

    @Slot(int)
    def setSellHubIndex(self, index: int) -> None:
        if 0 <= index < len(_REGIONS):
            self._sell_hub_index = index
            self.stateChanged.emit()

    @Slot(int)
    def setBuySideIndex(self, index: int) -> None:
        if 0 <= index < len(_SIDES):
            self._buy_side_index = index
            self.stateChanged.emit()

    @Slot(int)
    def setSellSideIndex(self, index: int) -> None:
        if 0 <= index < len(_SIDES):
            self._sell_side_index = index
            self.stateChanged.emit()

    @Slot(int)
    def setCharIndex(self, index: int) -> None:
        if 0 <= index < len(self._characters):
            self._char_index = index
            self.stateChanged.emit()

    @Slot(float)
    def setTax(self, value: float) -> None:
        """再钳一次范围（QML 侧的值可以被脚本直接设进来）。口径同原版 `setRange(0, 100)`。"""
        self._tax = min(100.0, max(0.0, float(value)))
        self.stateChanged.emit()

    # ── 给调用方取值 ──────────────────────────────────────────

    def _char_value(self) -> str:
        """当前人物名；它若已不在人物列表里就返回 "main"（原版 `get()` 的现查现判）。"""
        name = self._characters[self._char_index]
        return name if name in char_config_resolver.get_character_list() else "main"

    def get(self) -> dict:
        if self._kind == KIND_TRADE:
            return {
                "bh": _REGIONS[self._hub_index],
                "sh": _REGIONS[self._sell_hub_index],
                "bs": "sell" if self._buy_side_index == 0 else "buy",
                "ss": "sell" if self._sell_side_index == 0 else "buy",
                "char": self._char_value(),
            }
        return {
            "hub": _REGIONS[self._hub_index],
            "char": self._char_value(),
            "tax": self._tax,
        }


class MfgQmlDialog(QmlDialog):
    """QML 版「制造评分设置」。

    `MfgDlg(current, parent, type_id)` 的调用方把类名换成 `MfgQmlDialog` 即可 ——
    构造签名与 `get()` 与原版逐字一致。
    """

    def __init__(self, current: dict | None = None, parent: Any = None, type_id: int | None = None) -> None:
        cur = current or {}
        bridge = ScoreParamsBridge(
            KIND_MFG,
            "制造评分设置",
            "制造评分",
            type_id=type_id,
            hub=cur.get("hub", "Jita"),
            char=cur.get("char", "main"),
            tax=cur.get("tax", 0),
        )
        super().__init__(_QML_FILE, bridge, parent=parent, size=(320, 270))
        self._score_bridge = bridge

    def get(self) -> dict:
        return self._score_bridge.get()


class TradeQmlDialog(QmlDialog):
    """QML 版「贸易评分设置」。构造签名与 `get()` 与原版逐字一致。"""

    def __init__(self, current: dict | None = None, parent: Any = None, type_id: int | None = None) -> None:
        cur = current or {}
        bridge = ScoreParamsBridge(
            KIND_TRADE,
            "贸易评分设置",
            "贸易评分",
            type_id=type_id,
            hub=cur.get("bh", "Jita"),
            sell_hub=cur.get("sh", "Jita"),
            buy_side=cur.get("bs", "sell"),
            sell_side=cur.get("ss", "sell"),
            char=cur.get("char", "main"),
        )
        super().__init__(_QML_FILE, bridge, parent=parent, size=(320, 330))
        self._score_bridge = bridge

    def get(self) -> dict:
        return self._score_bridge.get()
