"""工业制造「加入制造计划」对话框的桥（阶段 4b 收尾）。

对照 Widgets 版 `ui_pyside6/dialogs/industry_dialogs.py` 的 `AddPlanDialog`。
对外契约一致：`exec()` → `result_data()` 返回
`{runs, parallels, me, te, char, fac}`。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from services import inventory_manager
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["AddPlanBridge", "AddPlanDialogQmlDialog"]

_QML_FILE = "dialogs/AddPlanDialog.qml"


def _format_score(score_result: dict) -> str:
    """评分摘要行（逐字对齐原 `AddPlanDialog` 里的那条 QLabel）。"""
    profit = score_result.get("profit_per_run", 0)
    margin = score_result.get("margin_pct", 0)
    score = score_result.get("score", 0)
    return f"{score:.1f} | 利润: {profit:,.0f} ISK | 利润率: {margin:.1f}%"


class AddPlanBridge(DialogBridge):
    """加入制造计划的 QML 后端。"""

    fieldsChanged = Signal()

    def __init__(self, product_name: str, score_result: dict) -> None:
        super().__init__()
        self.set_title(f"加入制造计划 — {product_name}")
        self._product_name = str(product_name)
        self._score_label = _format_score(score_result or {})
        self._result: dict[str, Any] | None = None

        self._runs = 1
        self._parallels = 1
        self._me = 0
        self._te = 0

        self._chars = self._load_chars()
        self._char_index = 0
        # 设施：原版是空的可编辑下拉（currentIndex(-1)），初值空串
        self._facility = ""
        self._facility_options = self._load_facilities()

    @staticmethod
    def _load_chars() -> list[str]:
        """角色下拉；没配角色时退回 "main"（原版 `addItem("main")`）。"""
        from services.char_config_resolver import get_character_list

        chars = list(get_character_list() or [])
        return chars or ["main"]

    @staticmethod
    def _load_facilities() -> list[str]:
        """设施候选 = 机库名；查不到就空表（原版 `try/except pass` 的等价物）。"""
        try:
            return [h.get("name", "") for h in inventory_manager.get_hangars()]
        except Exception:
            return []

    # ── 只读展示 ─────────────────────────────────────────────

    productName = Property(str, lambda self: self._product_name, constant=True)
    scoreLabel = Property(str, lambda self: self._score_label, constant=True)
    charOptions = Property(list, lambda self: list(self._chars), constant=True)
    facilityOptions = Property(list, lambda self: list(self._facility_options), constant=True)

    # ── 可编辑字段 ───────────────────────────────────────────

    runs = Property(int, lambda self: self._runs, notify=fieldsChanged)
    parallels = Property(int, lambda self: self._parallels, notify=fieldsChanged)
    me = Property(int, lambda self: self._me, notify=fieldsChanged)
    te = Property(int, lambda self: self._te, notify=fieldsChanged)
    charIndex = Property(int, lambda self: self._char_index, notify=fieldsChanged)
    facility = Property(str, lambda self: self._facility, notify=fieldsChanged)

    @Slot(int)
    def setRuns(self, value: int) -> None:
        self._runs = max(1, min(10000, int(value)))
        self.fieldsChanged.emit()

    @Slot(int)
    def setParallels(self, value: int) -> None:
        self._parallels = max(1, min(100, int(value)))
        self.fieldsChanged.emit()

    @Slot(int)
    def setMe(self, value: int) -> None:
        self._me = max(0, min(10, int(value)))
        self.fieldsChanged.emit()

    @Slot(int)
    def setTe(self, value: int) -> None:
        self._te = max(0, min(20, int(value)))
        self.fieldsChanged.emit()

    @Slot(int)
    def setCharIndex(self, index: int) -> None:
        if 0 <= index < len(self._chars):
            self._char_index = index
            self.fieldsChanged.emit()

    @Slot(str)
    def setFacility(self, text: str) -> None:
        self._facility = str(text)

    # ── 取值 ─────────────────────────────────────────────────

    def currentChar(self) -> str:
        """当前角色名（`charIndex` 是 Property，mypy 读不出 str，另给直取入口）。"""
        if 0 <= self._char_index < len(self._chars):
            return self._chars[self._char_index]
        return ""

    @Slot()
    def accept(self) -> None:
        self._result = {
            "runs": self._runs,
            "parallels": self._parallels,
            "me": self._me,
            "te": self._te,
            "char": self.currentChar().strip(),
            "fac": self._facility.strip(),
        }
        self.accepted.emit()

    def result_data(self) -> dict[str, Any] | None:
        """确定之后才有值；取消/未点确定 → None（与原版 `_result_data` 一致）。"""
        return self._result


class AddPlanDialogQmlDialog(QmlDialog):
    """QML 版「加入制造计划」。`AddPlanDialog(product_name, score_result, parent)` 的调用方原样可用。"""

    def __init__(self, product_name: str, score_result: dict, parent: Any = None) -> None:
        bridge = AddPlanBridge(product_name, score_result)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(480, 360))
        self._add_bridge = bridge

    def result_data(self) -> dict[str, Any] | None:
        return self._add_bridge.result_data()
