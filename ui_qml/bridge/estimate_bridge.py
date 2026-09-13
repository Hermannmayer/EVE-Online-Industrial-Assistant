"""估价页 bridge —— QML 与既有服务/worker 之间的唯一通道。

职责边界：**所有业务逻辑仍在 services / workers 里**，本类只做三件事：
把请求转发给既有实现、把结果整理成 QML 好用的形状、把状态回传给外壳状态栏。
不复制任何计算逻辑。

对照的 Widgets 版是 `ui_pyside6/views/estimate_view.py`，行为逐项对齐。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from core.constants import TRADE_HUB_IDS
from core.container import get_container
from ui_pyside6.workers.estimate_workers import ClipboardParseWorker, _search_item_by_name
from ui_pyside6.workers.refine_worker import RefineWorker
from ui_qml.models import EstimateQmlModel

__all__ = ["EstimateBridge"]

# QComboBox 的选项在 Widgets 版里是硬编码的中文，这里保持一致
_PRICE_TYPES = ("卖价", "买价", "均价")
_PRICE_TYPE_KEYS = ("sell", "buy", "avg")
_REFINE_MODES = ("人物", "设施")
_SKILL_PRESETS = ("技能全5", "当前人物", "技能全0")

_SKILL_ALL5 = {"提炼学概论": 5, "提炼效率理论": 5}
_SKILL_ALL0 = {"提炼学概论": 0, "提炼效率理论": 0}


class EstimateBridge(QObject):
    """估价页的 QML 后端。"""

    statusChanged = Signal(str)
    summaryChanged = Signal()
    hangarsChanged = Signal()
    busyChanged = Signal()
    priceTypeChanged = Signal()
    hubChanged = Signal()
    discountChanged = Signal()
    refineResult = Signal(dict)

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell
        self._hub = "Jita"
        self._price_type = "sell"
        self._discount = 1.0
        self._busy = False
        self._model = EstimateQmlModel()
        self._model.dataChanged.connect(lambda *_: self.summaryChanged.emit())
        self._model.rowsRemoved.connect(lambda *_: self.summaryChanged.emit())
        self._model.modelReset.connect(lambda: self.summaryChanged.emit())
        self._worker: QObject | None = None
        self._refine_worker: QObject | None = None

    # ── 模型 ──

    def _get_model(self) -> EstimateQmlModel:
        return self._model

    model = Property(QObject, _get_model, constant=True)

    # ── 选项列表（静态）──

    priceTypes = Property(list, lambda self: list(_PRICE_TYPES), constant=True)
    refineModes = Property(list, lambda self: list(_REFINE_MODES), constant=True)
    skillPresets = Property(list, lambda self: list(_SKILL_PRESETS), constant=True)
    hubs = Property(list, lambda self: list(TRADE_HUB_IDS.keys()), constant=True)

    @Slot(result=list)
    def hangars(self) -> list[dict]:
        """机库列表（每次调用重查，保证与「机库设置」的改动同步）。"""
        from services.inventory_manager import create_hangar, get_hangars

        result = get_hangars()
        if not result:
            create_hangar("默认机库")
            result = get_hangars()
        return [{"id": h["id"], "name": h["name"]} for h in result]

    # ── 设置项 ──

    def _get_price_type(self) -> str:
        return self._price_type

    def _set_price_type(self, value: str) -> None:
        if value not in _PRICE_TYPE_KEYS or value == self._price_type:
            return
        self._price_type = value
        self._rebuild_unit_prices()
        self.priceTypeChanged.emit()

    priceType = Property(str, _get_price_type, _set_price_type, notify=priceTypeChanged)

    def _get_hub(self) -> str:
        return self._hub

    def _set_hub(self, value: str) -> None:
        if not value or value == self._hub:
            return
        self._hub = value
        self.hubChanged.emit()
        self.refreshPrices()

    hub = Property(str, _get_hub, _set_hub, notify=hubChanged)

    def _get_discount(self) -> float:
        return self._discount

    def _set_discount(self, value: float) -> None:
        value = float(value)
        if value == self._discount:
            return
        self._discount = value
        self._model.set_discount(value)
        self._rebuild_unit_prices()
        self.summaryChanged.emit()
        self.discountChanged.emit()

    discount = Property(float, _get_discount, _set_discount, notify=discountChanged)

    def _get_busy(self) -> bool:
        return self._busy

    def _set_busy(self, value: bool) -> None:
        if value != self._busy:
            self._busy = value
            self.busyChanged.emit()

    busy = Property(bool, _get_busy, notify=busyChanged)

    def _get_summary(self) -> dict[str, Any]:
        rows = self._model._rows
        total_vol = sum(r.get("volume", 0) or 0 for r in rows)
        total_sell = sum(r.get("sell_total", 0) or 0 for r in rows)
        total_buy = sum(r.get("buy_total", 0) or 0 for r in rows)
        total_avg = (total_sell + total_buy) / 2 if (total_sell or total_buy) else 0
        return {
            "volume": f"{total_vol:,.1f} m³",
            "sell": f"{total_sell:,.0f} ISK",
            "buy": f"{total_buy:,.0f} ISK",
            "avg": f"{total_avg:,.0f} ISK",
            "rowCount": len(rows),
        }

    summary = Property(dict, _get_summary, notify=summaryChanged)

    # ── 状态回传 ──

    def _status(self, message: str) -> None:
        self.statusChanged.emit(message)

    # ── 剪贴板导入 ──

    @Slot()
    def paste(self) -> None:
        from PySide6.QtWidgets import QApplication

        text = QApplication.clipboard().text()
        if not text.strip():
            self._status("剪贴板为空")
            return

        self._set_busy(True)
        self._status("正在解析剪贴板...")
        worker = ClipboardParseWorker(text, self._price_type, self._hub, self)
        self._worker = worker
        worker.result_signal.connect(self._on_parse_done)
        worker.status_signal.connect(self._status)
        worker.finished.connect(lambda: self._set_busy(False))
        worker.start()

    def _on_parse_done(self, rows: list[dict]) -> None:
        self._model.set_rows(rows)
        self._model.set_discount(self._discount)
        self._rebuild_unit_prices()
        self.summaryChanged.emit()

    @Slot(str)
    def addItem(self, name: str) -> None:
        name = (name or "").strip()
        if not name:
            return
        item = _search_item_by_name(name)
        if item is None:
            self._status(f"未找到物品: {name}")
            return

        display_name = item["zh_name"] or item["en_name"] or name
        pricing = get_container().pricing_service
        self._model.add_row(
            {
                "type_id": item["type_id"],
                "name": display_name,
                "qty": 1,
                "sell_price": pricing.get_price(item["type_id"], "sell", self._hub) or 0,
                "buy_price": pricing.get_price(item["type_id"], "buy", self._hub) or 0,
                "unit_price": 0,
                "sell_total": 0,
                "buy_total": 0,
                "volume": 0,
                "_volume": item["volume"],
                "bp_me": 0,
                "bp_te": 0,
            }
        )
        self._model.set_discount(self._discount)
        self.summaryChanged.emit()
        self._status(f"已添加: {display_name}")

    # ── 价格 ──

    def _rebuild_unit_prices(self) -> None:
        """切换价格类型/折扣后重算单价列（与 Widgets 版同逻辑）。"""
        rows = self._model._rows
        for row in rows:
            sell = row.get("sell_price", 0) or 0
            buy = row.get("buy_price", 0) or 0
            if self._price_type == "sell":
                row["unit_price"] = sell * self._discount
            elif self._price_type == "buy":
                row["unit_price"] = buy * self._discount
            else:
                row["unit_price"] = ((sell + buy) / 2) * self._discount if (sell or buy) else 0
        if rows:
            self._model.dataChanged.emit(self._model.index(0, 3), self._model.index(len(rows) - 1, 3), [])

    @Slot()
    def refreshPrices(self) -> None:
        rows = self._model._rows
        if not rows:
            return
        self._status("正在刷新价格...")
        pricing = get_container().pricing_service
        for row in rows:
            tid = row.get("type_id")
            if not tid:
                continue
            row["sell_price"] = pricing.get_price(tid, "sell", self._hub) or 0
            row["buy_price"] = pricing.get_price(tid, "buy", self._hub) or 0
        self._model.set_discount(self._discount)
        self._rebuild_unit_prices()
        self.summaryChanged.emit()
        self._status("价格已刷新")

    @Slot(str)
    def copyTotals(self, mode: str) -> None:
        """复制总价到剪贴板（纯数字，无单位）——与 Widgets 版一致。"""
        from PySide6.QtWidgets import QApplication

        key = "sell_total" if mode == "sell" else "buy_total"
        total = sum(r.get(key, 0) or 0 for r in self._model._rows)
        QApplication.clipboard().setText(f"{total:,.0f}")
        label = "卖价" if mode == "sell" else "买价"
        self._status(f"已复制总{label} {total:,.0f} ISK 到剪贴板")

    @Slot(str)
    def copyText(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)

    # ── 行操作（右键菜单）──

    @Slot(int, result=dict)
    def rowAt(self, row_index: int) -> dict:
        """取某行的原始数据（供右键菜单显示名称/Type ID）。"""
        rows = self._model._rows
        if 0 <= row_index < len(rows):
            row = rows[row_index]
            return {"name": row.get("name", "?"), "typeId": row.get("type_id") or 0, "qty": row.get("qty", 1)}
        return {}

    @Slot(int, int)
    def setQty(self, row_index: int, qty: int) -> None:
        rows = self._model._rows
        if not (0 <= row_index < len(rows)) or qty <= 0:
            return
        rows[row_index]["qty"] = int(qty)
        self._model._recalc_totals()
        self._rebuild_unit_prices()
        self._model.dataChanged.emit(self._model.index(row_index, 2), self._model.index(row_index, 6), [])
        self.summaryChanged.emit()

    @Slot(int, float)
    def multiplyQty(self, row_index: int, factor: float) -> None:
        rows = self._model._rows
        if not (0 <= row_index < len(rows)):
            return
        rows[row_index]["qty"] = max(1, round(rows[row_index].get("qty", 1) * float(factor)))
        self._model._recalc_totals()
        self._rebuild_unit_prices()
        self._model.dataChanged.emit(self._model.index(row_index, 2), self._model.index(row_index, 6), [])
        self.summaryChanged.emit()

    @Slot(int, int, int)
    def setBlueprint(self, row_index: int, me: int, te: int) -> None:
        rows = self._model._rows
        if not (0 <= row_index < len(rows)):
            return
        rows[row_index]["bp_me"] = int(me)
        rows[row_index]["bp_te"] = int(te)
        self._status(f"蓝图: ME={me} TE={te}")

    @Slot(int, result=dict)
    def blueprintOf(self, row_index: int) -> dict:
        rows = self._model._rows
        if 0 <= row_index < len(rows):
            row = rows[row_index]
            return {"me": row.get("bp_me", 0), "te": row.get("bp_te", 0), "name": row.get("name", "?")}
        return {"me": 0, "te": 0, "name": ""}

    @Slot(int)
    def removeRow(self, row_index: int) -> None:
        self._model.remove_row(row_index)
        self.summaryChanged.emit()

    @Slot()
    def clearAll(self) -> None:
        self._model.clear_all()
        self.summaryChanged.emit()

    # ── 机库 ──

    @Slot(int)
    def addToHangar(self, hangar_id: int) -> None:
        if not hangar_id:
            self._status("请先选择机库")
            return

        from services.inventory_manager import add_item

        count = 0
        for row in self._model._rows:
            tid = row.get("type_id")
            if not tid:
                continue
            qty = row.get("qty", 0)
            if qty > 0:
                add_item(hangar_id, tid, qty, (row.get("buy_price", 0) or 0) * self._discount)
                count += 1
        self._status(f"已添加 {count} 种物品到机库")

    # ── 精炼 ──

    def _current_skills(self) -> dict[str, int]:
        """「当前人物」预设：从主窗口的 char_config 取，取不到按技能全5。"""
        char_config = getattr(self._shell, "_current_char", None)
        if isinstance(char_config, dict) and "skills" in char_config:
            return dict(char_config["skills"])  # type: ignore[return-value]
        return dict(_SKILL_ALL5)

    @Slot(str, str, float, bool)
    def refine(self, mode: str, skill_preset: str, gas_rate: float, residual: bool) -> None:
        rows = self._model.get_rows()
        if not rows:
            self._status("表格中没有数据")
            return

        if skill_preset == "技能全5":
            skills = dict(_SKILL_ALL5)
        elif skill_preset == "技能全0":
            skills = dict(_SKILL_ALL0)
        else:
            skills = self._current_skills()

        items = [{"type_id": r["type_id"], "qty": r.get("qty", 1), "name": r.get("name", "")} for r in rows]
        model_items = get_container().refining_service.filter_refinable(items)
        if not model_items:
            self._status("表格中没有可精炼的物品（矿石/冰矿/残骸）")
            return

        self._set_busy(True)
        self._status(f"正在精炼 {len(model_items)} 项物品...")
        worker = RefineWorker(
            model_items,
            skills=skills,
            is_player_facility=(mode == "设施"),
            price_hub=self._hub,
            gas_rate=float(gas_rate or 0),
            residual=residual,
            parent=self,
        )
        self._refine_worker = worker
        worker.status_signal.connect(self._status)
        worker.result_signal.connect(self._on_refine_done)
        worker.finished.connect(lambda: self._set_busy(False))
        worker.start()

    def _on_refine_done(self, result: dict) -> None:
        self._status(f"精炼完成: {result['item_count']} 项")
        self.refineResult.emit(result)
