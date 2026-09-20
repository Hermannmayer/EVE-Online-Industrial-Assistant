"""估价页 bridge —— QML 与既有服务/worker 之间的唯一通道。

职责边界：**所有业务逻辑仍在 services / workers 里**，本类只做三件事：
把请求转发给既有实现、把结果整理成 QML 好用的形状、把状态回传给外壳状态栏。
不复制任何计算逻辑。

对照的 Widgets 版是 `ui_pyside6/views/estimate_view.py`，行为逐项对齐。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from core.constants import TRADE_HUB_IDS, TRADE_HUB_SYSTEM_IDS
from core.container import get_container
from core.logger import log
from services.char_config_resolver import load_all_data, resolve_char_config
from services.name_resolver import resolve_system_display_names_batch
from ui_qml.models import EstimateQmlModel
from ui_qml.workers.estimate_workers import ClipboardParseWorker, _search_item_by_name

__all__ = ["EstimateBridge"]

#: 精炼场地（值语义仍是「是不是玩家设施」，标签按玩家说法给）
_REFINE_MODES = ("空间站", "玩家设施")
#: 取价固定用卖价：买/卖的选择已由底部两个「…到剪贴板」按钮承担，不再做价格类型下拉
_PRICE_TYPE = "sell"


class EstimateBridge(QObject):
    """估价页的 QML 后端。"""

    statusChanged = Signal(str)
    summaryChanged = Signal()
    hangarsChanged = Signal()
    busyChanged = Signal()
    hubChanged = Signal()
    discountChanged = Signal()
    characterChanged = Signal()
    refineModeChanged = Signal()

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell
        self._hub = "Jita"
        self._discount = 1.0
        self._busy = False
        self._character = ""  # 惰性取默认（char_config.json 的 current）
        self._refine_mode = _REFINE_MODES[0]
        self._model = EstimateQmlModel()
        self._model.dataChanged.connect(lambda *_: self.summaryChanged.emit())
        self._model.rowsRemoved.connect(lambda *_: self.summaryChanged.emit())
        self._model.modelReset.connect(lambda: self.summaryChanged.emit())
        self._worker: QObject | None = None

    # ── 模型 ──

    def _get_model(self) -> EstimateQmlModel:
        return self._model

    model = Property(QObject, _get_model, constant=True)

    # ── 选项列表（静态）──

    refineModes = Property(list, lambda self: list(_REFINE_MODES), constant=True)

    @Slot(result=list)
    def hubOptions(self) -> list[dict]:
        """贸易中心下拉 → `[{label, value}]`。

        `value` 是取价要的英文中心名（`core.constants.TRADE_HUB_IDS` 的键）；
        `label` 走术语表的中英对照（`resolve_system_display_names_batch` → 「吉他 (Jita)」），
        不在 QML 里硬编码中文。
        """
        system_ids = [sid for hub in TRADE_HUB_IDS if (sid := TRADE_HUB_SYSTEM_IDS.get(hub))]
        names = resolve_system_display_names_batch(system_ids)
        return [{"label": names.get(TRADE_HUB_SYSTEM_IDS.get(hub, 0)) or hub, "value": hub} for hub in TRADE_HUB_IDS]

    def _characters_and_current(self) -> tuple[list[str], str]:
        """角色名列表 + 默认选中项（`char_config.json` 的 `current`，失效则取首项）。"""
        try:
            data = load_all_data()
        except Exception:
            log.exception("读取角色配置失败")
            return [], ""
        names = list((data.get("characters") or {}).keys())
        current = str(data.get("current") or "")
        return names, (current if current in names else (names[0] if names else ""))

    @Property(list, notify=characterChanged)
    def characters(self) -> list[str]:
        return self._characters_and_current()[0]

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

    def _get_hub(self) -> str:
        return self._hub

    def _set_hub(self, value: str) -> None:
        if not value or value == self._hub:
            return
        self._hub = value
        self.hubChanged.emit()
        self.refreshPrices()

    hub = Property(str, _get_hub, _set_hub, notify=hubChanged)

    def _get_character(self) -> str:
        if not self._character:
            self._character = self._characters_and_current()[1]
        return self._character

    def _set_character(self, value: str) -> None:
        value = str(value or "")
        if not value or value == self._get_character():
            return
        self._character = value
        self.characterChanged.emit()
        self._rebuild_refine_values()

    character = Property(str, _get_character, _set_character, notify=characterChanged)

    def _get_refine_mode(self) -> str:
        return self._refine_mode

    def _set_refine_mode(self, value: str) -> None:
        if value not in _REFINE_MODES or value == self._refine_mode:
            return
        self._refine_mode = value
        self.refineModeChanged.emit()
        self._rebuild_refine_values()

    refineMode = Property(str, _get_refine_mode, _set_refine_mode, notify=refineModeChanged)

    def _get_discount(self) -> float:
        return self._discount

    def _set_discount(self, value: float) -> None:
        value = float(value)
        if value == self._discount:
            return
        self._discount = value
        self._model.set_discount(value)
        self._rebuild_unit_prices()
        self._rebuild_refine_values()
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
        worker = ClipboardParseWorker(text, _PRICE_TYPE, self._hub, self)
        self._worker = worker
        worker.result_signal.connect(self._on_parse_done)
        worker.status_signal.connect(self._status)
        worker.finished.connect(lambda: self._set_busy(False))
        worker.start()

    def _on_parse_done(self, rows: list[dict]) -> None:
        self._model.set_rows(rows)
        self._model.set_discount(self._discount)
        self._rebuild_unit_prices()
        self._rebuild_refine_values()
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
        self._rebuild_unit_prices()
        self._rebuild_refine_values()
        self.summaryChanged.emit()
        self._status(f"已添加: {display_name}")

    # ── 价格 ──

    def _rebuild_unit_prices(self) -> None:
        """重算单价列 —— 取价固定用卖价（买/卖的选择归底部两个复制按钮管）。"""
        rows = self._model._rows
        for row in rows:
            row["unit_price"] = (row.get("sell_price", 0) or 0) * self._discount
        if rows:
            self._model.dataChanged.emit(self._model.index(0, 3), self._model.index(len(rows) - 1, 3), [])

    def _rebuild_refine_values(self) -> None:
        """逐行算「精炼价值」列；不可精炼 / 算不出的行留 `None`（QML 显示「—」）。

        口径与原 `RefineWorker.run` 一致：矿石专精技能名由 `ore_skill_info` 按 SDE 组名推，
        等级从当前人物的真实技能表里取。**公式与取价全在 `services/refining_service`**，
        这里只做「遍历行 + 挑字段 + 乘折扣」（折扣与「卖价合计」同口径）。
        """
        rows = self._model._rows
        if not rows:
            return
        svc = get_container().refining_service
        skills = self._current_skills()
        facility = self._refine_mode == _REFINE_MODES[1]
        for row in rows:
            type_id = row.get("type_id")
            if not type_id:
                row["refine_value"] = None
                continue
            try:
                _is_ore, skill_name = svc.ore_skill_info(type_id)
                ore_skill = int(skills.get(skill_name, 0) or 0) if skill_name else 0
                result = svc.calc_value(
                    type_id,
                    quantity=row.get("qty", 1) or 1,
                    skills=skills,
                    is_player_facility=facility,
                    price_hub=self._hub,
                    ore_skill=ore_skill,
                )
            except Exception:
                log.exception("精炼价值计算失败 type_id=%s", type_id)
                row["refine_value"] = None
                continue
            row["refine_value"] = result["total_value"] * self._discount if result["output"] else None
        self._model.dataChanged.emit(
            self._model.index(0, 2), self._model.index(len(rows) - 1, self._model.columnCount() - 1), []
        )

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
        self._rebuild_refine_values()
        self.summaryChanged.emit()
        self._status("价格已更新")

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
        self._rebuild_refine_values()
        self._model.dataChanged.emit(
            self._model.index(row_index, 2), self._model.index(row_index, self._model.columnCount() - 1), []
        )
        self.summaryChanged.emit()

    @Slot(int, float)
    def multiplyQty(self, row_index: int, factor: float) -> None:
        rows = self._model._rows
        if not (0 <= row_index < len(rows)):
            return
        rows[row_index]["qty"] = max(1, round(rows[row_index].get("qty", 1) * float(factor)))
        self._model._recalc_totals()
        self._rebuild_unit_prices()
        self._rebuild_refine_values()
        self._model.dataChanged.emit(
            self._model.index(row_index, 2), self._model.index(row_index, self._model.columnCount() - 1), []
        )
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
        """当前人物的**真实技能表** —— 读 `data/char_config.json`（见 `char_config_resolver`）。

        早先这里是「按技能全5 兜底」的死分支（读 `shell._current_char`，而全库无人给它赋值），
        所以人物下拉形同虚设、精炼产率恒按满技能算。现在只认真实配置：人物没配技能就给空表，
        产率按 0 级算 —— 宁可偏低，也不假装人物满技能。
        """
        name = self._get_character()
        if not name:
            return {}
        try:
            config = resolve_char_config(char_name=name)
        except Exception:
            log.exception("读取人物技能失败 char=%s", name)
            return {}
        skills = config.get("skills") if isinstance(config, dict) else None
        return dict(skills) if isinstance(skills, dict) else {}
