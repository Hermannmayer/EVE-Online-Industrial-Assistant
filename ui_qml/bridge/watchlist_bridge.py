"""价格监控页 bridge —— QML 与 `services.watchlist_manager` 之间的唯一通道。

对照的 Widgets 版是 `ui_pyside6/views/watchlist_view.py`。

**阈值设置改在 QML 里做**：原版为它内联了一个 `QDialog`（`_set_threshold`），
迁到 QML 后由页面里的小弹层 + `setThreshold(row, kind, value)` 承担 ——
比让 QML 去调一个 Widgets 对话框干净，也少一个阶段 4 的对话框。
值 ≤ 0 表示清除该阈值（与原版 `value if value > 0 else None` 一致）。
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core.constants import TRADE_HUB_IDS
from ui_qml.models.watchlist_qml_model import WatchlistQmlModel
from ui_qml.theme import registry as theme

__all__ = ["WatchlistBridge"]

#: 价格变化的轮询间隔（对齐 Widgets 版的 60s）
CHECK_INTERVAL_MS = 60_000

_HUBS = list(TRADE_HUB_IDS.keys())


class WatchlistBridge(QObject):
    """价格监控页的 QML 后端。"""

    rowsChanged = Signal()
    suggestChanged = Signal()
    editorChanged = Signal()  # 顶部「搜索物品 / 备注 / 区域」这一组

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        from services.watchlist_manager import init_db

        init_db()
        self._shell = shell
        self._model = WatchlistQmlModel()
        self._price_changes: dict[int, dict] = {}

        self._search_text = ""
        self._suggestions: list[dict] = []
        self._selected_type_id: int | None = None
        self._selected_name = ""
        self._region_index = 0
        self._note = ""

        self._suggest_worker: QObject | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.checkPriceChanges)
        self._timer.start(CHECK_INTERVAL_MS)

        self._remove_theme_listener = theme.add_theme_listener(self._on_theme_changed)
        self.refresh()

    # ── 列表 ──────────────────────────────────────────────────

    model = Property(QObject, lambda self: self._model, constant=True)

    @Property(list, constant=True)
    def columns(self) -> list[dict]:
        """列定义（标题 + 宽度）—— 单一来源在 `watchlist_view.COLUMNS`。"""
        from ui_qml.models.watchlist_models import COLUMNS

        return [{"title": title, "width": width} for title, width in COLUMNS]

    countText = Property(str, lambda self: f"共 {self._model.rowCount()} 项", notify=rowsChanged)

    @Slot()
    def refresh(self) -> None:
        from services.watchlist_manager import get_watchlist

        self._model.set_rows(get_watchlist())
        self.rowsChanged.emit()
        self._push_status()

    def _push_status(self) -> None:
        setter = getattr(self._shell, "set_status", None)
        if not callable(setter):
            return
        count = self._model.rowCount()
        triggered = 0
        for row in self._model._rows:
            buy_thresh = row.get("buy_threshold")
            sell_thresh = row.get("sell_threshold")
            buy_price = row.get("buy_price")
            sell_price = row.get("sell_price")
            if buy_thresh is not None and buy_price and buy_price <= buy_thresh:
                triggered += 1
            elif sell_thresh is not None and sell_price and sell_price >= sell_thresh:
                triggered += 1
        msg = f"关注列表: {count} 项"
        if triggered:
            msg += f", {triggered} 项触发提醒"
        if self._price_changes:
            msg += f", {len(self._price_changes)} 项价格变化"
        setter(msg)

    # ── 顶部编辑器 ────────────────────────────────────────────

    searchText = Property(str, lambda self: self._search_text, notify=editorChanged)
    selectedName = Property(str, lambda self: self._selected_name, notify=editorChanged)
    regions = Property(list, lambda self: list(_HUBS), constant=True)
    regionIndex = Property(int, lambda self: self._region_index, notify=editorChanged)
    note = Property(str, lambda self: self._note, notify=editorChanged)
    suggestions = Property(list, lambda self: self._suggestions, notify=suggestChanged)

    @Slot(str)
    def onSearchChanged(self, text: str) -> None:
        self._search_text = str(text)
        if len(text) < 1:
            self._suggestions = []
            self.suggestChanged.emit()
            return

        from ui_qml.workers.watchlist_workers import SuggestionWorker

        worker = SuggestionWorker(text, self)
        self._suggest_worker = worker
        worker.finished_signal.connect(self._on_suggestions)
        worker.start()

    def _on_suggestions(self, items: list) -> None:
        self._suggestions = [{"typeId": int(tid), "text": str(display)} for tid, display in items or []]
        self.suggestChanged.emit()

    @Slot(int)
    def pickSuggestion(self, index: int) -> None:
        if not 0 <= index < len(self._suggestions):
            return
        item = self._suggestions[index]
        self._selected_type_id = int(item["typeId"])
        self._selected_name = str(item["text"])
        self._search_text = self._selected_name
        self._suggestions = []
        self.suggestChanged.emit()
        self.editorChanged.emit()

    @Slot(int)
    def setRegionIndex(self, index: int) -> None:
        if 0 <= index < len(_HUBS) and index != self._region_index:
            self._region_index = index
            self.editorChanged.emit()

    @Slot(str)
    def setNote(self, text: str) -> None:
        self._note = str(text)

    @Slot(result=bool)
    def add(self) -> bool:
        """添加关注。没选物品时返回 False，由 QML 提示（与 Widgets 版的 warning 对应）。"""
        if self._selected_type_id is None:
            return False
        from services.watchlist_manager import add_to_watchlist

        result = add_to_watchlist(
            type_id=self._selected_type_id,
            region_id=TRADE_HUB_IDS[_HUBS[self._region_index]],
            note=self._note.strip(),
        )
        if result <= 0:
            return False

        self._search_text = ""
        self._selected_type_id = None
        self._selected_name = ""
        self._note = ""
        self._suggestions = []
        self.suggestChanged.emit()
        self.editorChanged.emit()
        self.refresh()
        return True

    # ── 删除 / 阈值 ───────────────────────────────────────────

    @Slot(int)
    def removeRow(self, row: int) -> None:
        from services.watchlist_manager import remove_from_watchlist

        items = self._model._rows
        if not 0 <= row < len(items):
            return
        remove_from_watchlist(items[row]["id"])
        self.refresh()

    @Slot(int, str, float)
    def setThreshold(self, row: int, kind: str, value: float) -> None:
        """设置买/卖价阈值；value ≤ 0 表示清除（与原版一致）。"""
        from services.watchlist_manager import update_watchlist_item

        items = self._model._rows
        if not 0 <= row < len(items):
            return
        item = items[row]
        threshold = value if value > 0 else None
        if kind == "buy":
            update_watchlist_item(item["id"], buy_threshold=threshold)
        else:
            update_watchlist_item(item["id"], sell_threshold=threshold)
        self.refresh()

    @Slot(int, result=dict)
    def rowInfo(self, row: int) -> dict:
        """给阈值弹层/右键菜单用的行信息。"""
        items = self._model._rows
        if not 0 <= row < len(items):
            return {"valid": False}
        item = items[row]
        return {
            "valid": True,
            "name": item.get("zh_name") or item.get("en_name") or "",
            "buyThreshold": item.get("buy_threshold") or 0.0,
            "sellThreshold": item.get("sell_threshold") or 0.0,
        }

    # ── 价格变化轮询 ──────────────────────────────────────────

    @Slot()
    def checkPriceChanges(self) -> None:
        """定时检查价格变化（原版 `_on_price_check_timer`）。"""
        try:
            from services.watchlist_manager import check_price_changes

            changes = check_price_changes()
            self._price_changes = {c["type_id"]: c for c in changes}
            self._model.set_price_changes(self._price_changes)
            self.refresh()
        except Exception:
            from core.logger import log

            log.exception("价格变化检测失败")

    def _on_theme_changed(self) -> None:
        self._model.refresh_colors()
        self.rowsChanged.emit()
