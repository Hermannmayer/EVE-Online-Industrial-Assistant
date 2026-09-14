"""仓库页 bridge —— QML 与既有服务 / worker 之间的唯一通道。

覆盖两个 Tab（机库管理 / 蓝图管理），对照的 Widgets 版是
`ui_pyside6/views/inventory/{inventory_page,hangar_tab,blueprint_tab}.py`。

**多选在本桥里实现**：机库页的批量删除/移库/改成本价、蓝图页的批量操作都靠多选，
而 QML `TableView` 的内建选中在 Qt 6.11 上不工作（见 `PlanTableBridge` 的说明）。
这里用「行号集合 + 修订号」自建：
  - QML 的 delegate 读 `selectionRevision` 触发重算（`var` 集合变化不会自己通知）；
  - 修饰键在 Python 侧读 —— QML 的 `TapHandler` 拿不到（`QEventPoint` 没有
    `modifiers`），而 `QGuiApplication.keyboardModifiers()` 在点击时是准的。

**对话框仍是 Widgets**（阶段 4 迁移）：本桥只负责「凑齐参数 → 打开对话框 → 落地 → 刷新」，
计算与落库全部走既有 service。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

from core.constants import TRADE_HUB_IDS
from ui_qml.models.inventory_qml_models import BlueprintQmlModel, InvQmlModel

__all__ = ["InventoryBridge"]

_TYPE_FILTERS = ["全部", "蓝图原图", "蓝图拷贝", "反应公式"]
_TECH_FILTERS = ["全部", "T1", "T2", "T3"]


class InventoryBridge(QObject):
    """仓库页（机库 + 蓝图）的 QML 后端。"""

    hangarChanged = Signal()  # 机库列表 / 当前机库
    itemsChanged = Signal()  # 机库物品表 + 统计
    blueprintsChanged = Signal()  # 蓝图表 + 统计 + 过滤器
    selectionChanged = Signal()  # 选中集（含修订号）

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        from services.inventory_manager import init_db

        init_db()
        self._shell = shell

        # ── 机库 ──
        self._hangars: list[dict] = []
        self._hangar_index = 0
        self._current_hangar_id: int | None = None
        self._items = InvQmlModel()
        self._items_count = ""
        self._items_total = "按卖单价格: -- ISK"
        self._item_selection: set[int] = set()

        # ── 蓝图 ──
        self._blueprints = BlueprintQmlModel()
        self._bp_all_rows: list[dict] = []
        self._bp_count = ""
        self._bp_type_index = 0
        self._bp_tech_index = 0
        self._bp_market_index = 0
        self._bp_search = ""
        self._bp_selection: set[int] = set()
        self._bp_categories: list[dict] = []
        self._bp_tech_levels: dict[int, int] = {}
        self._bp_reaction_ids: set[int] = set()
        self._selection_revision = 0

        self._reload_hangars()
        self.refreshItems()  # 构造时就把当前机库的物品表填上（否则首次进页面是空的）
        self._load_market_categories()
        self.loadBlueprints()

    # ═══════════════════════════════════════════════════════════
    #  选中集（两个 Tab 共用一套实现，各自持一份）
    # ═══════════════════════════════════════════════════════════

    selectionRevision = Property(int, lambda self: self._selection_revision, notify=selectionChanged)

    #: 选中集整批给出。
    #:
    #: 别让 delegate 逐格调 `itemRowSelected(row)`：一张 8 列 × 25 行的表，每次选中
    #: 变化就是 **200 次跨 QML/Python 调用**（实测），点一下就能感觉到卡。
    #: QML 侧读一次列表再 `indexOf` 判断，一次选中变化只剩 1 次跨边界。
    selectedItemRows = Property(list, lambda self: sorted(self._item_selection), notify=selectionChanged)
    selectedBlueprintRows = Property(list, lambda self: sorted(self._bp_selection), notify=selectionChanged)

    @Slot(int)
    def selectItemRow(self, row: int) -> None:
        """机库表：普通=只选它，Ctrl=切换，Shift=区间。"""
        self._item_selection = self._apply_selection(
            self._item_selection, row, self._items.rowCount(), anchor_attr="_item_anchor"
        )

    @Slot(int)
    def selectBlueprintRow(self, row: int) -> None:
        self._bp_selection = self._apply_selection(
            self._bp_selection, row, self._blueprints.rowCount(), anchor_attr="_bp_anchor"
        )

    def _modifiers(self) -> Qt.KeyboardModifier:
        """当前修饰键。**留成方法是为了可测**：PySide6 的 `QGuiApplication` 是 C++ 类型，
        测试里 `monkeypatch.setattr` 它不生效（静默失败），只能从这一层注入。
        """
        return QGuiApplication.keyboardModifiers()

    def _apply_selection(self, current: set[int], row: int, total: int, *, anchor_attr: str) -> set[int]:
        """普通=只选它，Ctrl=切换，Shift=从锚点连选到该行（对齐计划表的选中语义）。

        锚点**两张表各存一份**：共用会让「机库表 Shift 连选」被蓝图表的点击带偏。
        """
        if not 0 <= row < total:
            return current
        anchor = int(getattr(self, anchor_attr, -1))
        modifiers = self._modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            result = set(current)
            result.symmetric_difference_update({row})
        elif modifiers & Qt.KeyboardModifier.ShiftModifier and current:
            first, last = sorted((anchor if anchor >= 0 else row, row))
            result = set(range(first, last + 1))
        else:
            result = {row}
        setattr(self, anchor_attr, row)
        self._selection_revision += 1
        self.selectionChanged.emit()
        return result

    _item_anchor = -1
    _bp_anchor = -1

    @Slot(int, result=list)
    def itemsForMenu(self, row: int) -> list[int]:
        """右键作用的行集：点中的行不在选中集里就只作用于它（对齐 QAbstractItemView）。"""
        if row in self._item_selection:
            return sorted(self._item_selection)
        self._item_selection = {row}
        self._selection_revision += 1
        self.selectionChanged.emit()
        return [row]

    @Slot(int, result=list)
    def blueprintsForMenu(self, row: int) -> list[int]:
        if row in self._bp_selection:
            return sorted(self._bp_selection)
        self._bp_selection = {row}
        self._selection_revision += 1
        self.selectionChanged.emit()
        return [row]

    @Slot(int, result=bool)
    def itemRowSelected(self, row: int) -> bool:
        return row in self._item_selection

    @Slot(int, result=bool)
    def blueprintRowSelected(self, row: int) -> bool:
        return row in self._bp_selection

    @Slot()
    def clearItemSelection(self) -> None:
        self._item_selection = set()
        self._selection_revision += 1
        self.selectionChanged.emit()

    @Slot()
    def clearBlueprintSelection(self) -> None:
        self._bp_selection = set()
        self._selection_revision += 1
        self.selectionChanged.emit()

    # ═══════════════════════════════════════════════════════════
    #  Tab 1：机库管理
    # ═══════════════════════════════════════════════════════════

    itemModel = Property(QObject, lambda self: self._items, constant=True)

    @Property(list, constant=True)
    def itemColumns(self) -> list[dict]:
        """机库表列定义（标题 + 初始宽度）。"""
        from ui_pyside6.views.inventory.inventory_helpers import InvTableModel

        widths = (36, 220, 90, 110, 80, 80, 120, 120)
        return [{"title": title, "width": width} for title, width in zip(InvTableModel._HEADERS, widths, strict=True)]

    itemCountText = Property(str, lambda self: self._items_count, notify=itemsChanged)
    itemTotalText = Property(str, lambda self: self._items_total, notify=itemsChanged)
    #: 行数（表格点击区用它把「最后一行以下」判成空白）
    itemCount = Property(int, lambda self: self._items.rowCount(), notify=itemsChanged)

    hangarNames = Property(list, lambda self: [h.get("label", "") for h in self._hangars], notify=hangarChanged)
    hangarIndex = Property(int, lambda self: self._hangar_index, notify=hangarChanged)

    @Slot(int)
    def setHangarIndex(self, index: int) -> None:
        if 0 <= index < len(self._hangars) and index != self._hangar_index:
            self._hangar_index = index
            self._current_hangar_id = self._hangars[index]["id"]
            self._item_selection = set()
            self._bp_selection = set()
            self.hangarChanged.emit()
            self.refreshItems()
            self.loadBlueprints()

    def _reload_hangars(self) -> None:
        from services.inventory_manager import get_hangars
        from services.name_resolver import resolve_system_display_names_batch

        hangars = get_hangars()
        systems = resolve_system_display_names_batch(
            [h["solar_system_id"] for h in hangars if h.get("solar_system_id")]
        )
        self._hangars = []
        for hangar in hangars:
            label = hangar["name"]
            sid = hangar.get("solar_system_id")
            if sid and sid in systems:
                label = f"{label} ({systems[sid]})"
            self._hangars.append({**hangar, "label": label})
        if self._hangars:
            self._hangar_index = min(self._hangar_index, len(self._hangars) - 1)
            self._current_hangar_id = self._hangars[self._hangar_index]["id"]
        else:
            self._hangar_index = 0
            self._current_hangar_id = None
        self.hangarChanged.emit()

    def _current_hangar_label(self) -> str:
        if 0 <= self._hangar_index < len(self._hangars):
            return str(self._hangars[self._hangar_index].get("label", ""))
        return ""

    @Slot()
    def refreshItems(self) -> None:
        from services.inventory_manager import get_items

        if self._current_hangar_id is None:
            self._items.set_rows([])
            self._items_count = ""
            self._items_total = "按卖单价格: -- ISK"
            self.itemsChanged.emit()
            return

        items = get_items(self._current_hangar_id)
        self._items.set_rows(items)
        self._items_count = f"共 {len(items)} 项"
        total = sum((it["quantity"] * (it.get("sell_price") or 0)) for it in items if it.get("sell_price"))
        self._items_total = f"按卖单价格: {total:,.0f} ISK"
        self.itemsChanged.emit()

    @Slot(int, result=dict)
    def itemMenuState(self, row: int) -> dict:
        """右键菜单要的状态：单行才给「编辑数量」，并给出可移动的目标机库。"""
        rows = self.itemsForMenu(row)
        targets = [h for h in self._hangars if h["id"] != self._current_hangar_id]
        return {
            "valid": bool(rows),
            "count": len(rows),
            "single": len(rows) == 1,
            "moveTargets": [{"id": h["id"], "name": h["label"]} for h in targets],
        }

    # ── 机库：按钮动作（对话框仍是 Widgets）────────────────────

    @Slot(str)
    def runClipboardImport(self, mode: str) -> None:
        """库存修正（full）/ 增量粘贴（incremental）—— 走既有的审阅对话框。"""
        if self._current_hangar_id is None:
            return
        from ui_pyside6.views.inventory.review_dialog import run_clipboard_import

        run_clipboard_import(
            self._current_hangar_id,
            self._current_hangar_label(),
            self._shell if isinstance(self._shell, QWidget) else None,
            mode=mode,
        )
        self.refreshItems()

    @Slot()
    def transferFromClipboard(self) -> None:
        """移库：读剪贴板 → 选来源机库 → 把数量搬到当前机库。"""
        if self._current_hangar_id is None:
            return
        clipboard = QApplication.clipboard()
        raw = clipboard.text().strip() if clipboard is not None else ""
        if not raw:
            self._set_items_hint("剪贴板为空，请先在游戏中复制物品（Ctrl+C）")
            return

        parsed, filtered = self._parse_clipboard(raw)
        if not parsed:
            if filtered:
                self._set_items_hint(f"剪贴板中的 {filtered} 行都是蓝图，材料仓库只导入材料，已全部过滤")
            return

        from ui_pyside6.views.inventory.transfer_dialog import HangarTransferDialog

        parent = self._shell if isinstance(self._shell, QWidget) else None
        dialog = HangarTransferDialog(
            parsed,
            self._current_hangar_id,
            self._current_hangar_label(),
            parent,
            filtered_note=filtered,
        )
        from PySide6.QtWidgets import QDialog

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refreshItems()

    @staticmethod
    def _parse_clipboard(raw: str) -> tuple[list[dict], int]:
        from services.inventory_clipboard_service import parse_clipboard

        return parse_clipboard(raw)

    @Slot()
    def openMaterialCoverage(self) -> None:
        if self._current_hangar_id is None:
            return
        from ui_pyside6.views.inventory.material_coverage_dialog import MaterialCoverageDialog

        parent = self._shell if isinstance(self._shell, QWidget) else None
        MaterialCoverageDialog(self._current_hangar_id, self._current_hangar_label(), parent).exec()

    @Slot()
    def addItemManually(self) -> None:
        if self._current_hangar_id is None:
            return
        from PySide6.QtWidgets import QDialog

        from services.inventory_manager import add_item
        from ui_pyside6.dialogs.hangar_dialogs import AddItemDialog

        parent = self._shell if isinstance(self._shell, QWidget) else None
        dialog = AddItemDialog(self._current_hangar_label(), parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()
        if not data:
            return
        type_id, quantity, cost = data
        if add_item(self._current_hangar_id, type_id, quantity, cost) == -1:
            self._set_items_hint("添加失败")
            return
        self.refreshItems()

    @Slot(int)
    def editItemQuantity(self, row: int) -> None:
        from PySide6.QtWidgets import QDialog

        from services.inventory_manager import update_quantity
        from ui_pyside6.dialogs.hangar_dialogs import EditQtyDialog

        item = self._items.item_at(row)
        if not item:
            return
        parent = self._shell if isinstance(self._shell, QWidget) else None
        dialog = EditQtyDialog(self._item_name(item), item["quantity"], parent)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.quantity() >= 0:
            update_quantity(item["id"], dialog.quantity())
            self.refreshItems()

    @Slot("QVariantList")
    def deleteItems(self, rows: list) -> None:
        from services.inventory_manager import remove_item

        for row in rows:
            item = self._items.item_at(int(row))
            if item:
                remove_item(item["id"])
        self.refreshItems()

    @Slot("QVariantList", int)
    def moveItems(self, rows: list, target_id: int) -> None:
        from services.inventory_manager import move_items

        ids = []
        for row in rows:
            item = self._items.item_at(int(row))
            if item:
                ids.append(item["id"])
        if ids:
            move_items(ids, target_id)
            self.refreshItems()

    @Slot("QVariantList")
    def editItemsCost(self, rows: list) -> None:
        """批量设置成本价：吉他卖价/买价/均价 × 材料倍率，或手动输入。"""
        from PySide6.QtWidgets import QDialog

        from services.inventory_manager import update_cost_price
        from ui_pyside6.dialogs.hangar_dialogs import BatchCostPriceDialog

        items: list[dict] = []
        for row in rows:
            item = self._items.item_at(int(row))
            if item:
                items.append(item)
        if not items:
            return

        parent = self._shell if isinstance(self._shell, QWidget) else None
        dialog = BatchCostPriceDialog(parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        source = dialog.price_type()
        updated = 0
        skipped: list[str] = []
        if source == "manual":
            manual = dialog.manual_price()
            for item in items:
                update_cost_price(item["id"], manual)
                updated += 1
        else:
            discount = dialog.discount()
            prices = dict(
                self._market_repo().get_prices_by_region([it["type_id"] for it in items], TRADE_HUB_IDS["Jita"], source)
            )
            for item in items:
                base = prices.get(item["type_id"])
                if base is None:
                    skipped.append(self._item_name(item))
                    continue
                update_cost_price(item["id"], round(base * discount, 2))
                updated += 1

        self.refreshItems()
        message = f"已更新 {updated} 项成本价"
        if skipped:
            shown = "、".join(skipped[:3])
            if len(skipped) > 3:
                shown += " 等"
            message += f"；{len(skipped)} 项无市场价未更新（{shown}）"
        self._set_items_hint(message)

    @Slot("QVariantList")
    def copyItemNames(self, rows: list) -> None:
        names = [self._item_name(self._items.item_at(int(r)) or {}) for r in rows]
        self._copy("\n".join(n for n in names if n))

    @Slot("QVariantList")
    def copyItemTypeIds(self, rows: list) -> None:
        ids = []
        for row in rows:
            item = self._items.item_at(int(row))
            if item:
                ids.append(str(item["type_id"]))
        self._copy("\n".join(ids))

    @staticmethod
    def _item_name(item: dict) -> str:
        return str(item.get("display_name") or item.get("zh_name") or item.get("en_name") or item.get("type_id", ""))

    def _set_items_hint(self, text: str) -> None:
        self._items_count = text
        self.itemsChanged.emit()

    # ═══════════════════════════════════════════════════════════
    #  Tab 2：蓝图管理
    # ═══════════════════════════════════════════════════════════

    blueprintModel = Property(QObject, lambda self: self._blueprints, constant=True)

    @Property(list, constant=True)
    def blueprintColumns(self) -> list[dict]:
        """蓝图表列定义（固定宽度，避免按内容扫描全表卡顿 —— 与 Widgets 版同款）。"""
        from ui_pyside6.views.inventory.inventory_helpers import BlueprintTableModel

        widths = (28, 160, 90, 60, 60, 130, 90, 70, 100, 100, 80)
        return [
            {"title": title, "width": width} for title, width in zip(BlueprintTableModel._HEADERS, widths, strict=True)
        ]

    blueprintCountText = Property(str, lambda self: self._bp_count, notify=blueprintsChanged)
    #: 行数（同上，表格点击区用）
    blueprintCount = Property(int, lambda self: self._blueprints.rowCount(), notify=blueprintsChanged)
    typeFilters = Property(list, lambda self: list(_TYPE_FILTERS), constant=True)
    techFilters = Property(list, lambda self: list(_TECH_FILTERS), constant=True)
    marketCategories = Property(list, lambda self: self._bp_categories, notify=blueprintsChanged)
    typeFilterIndex = Property(int, lambda self: self._bp_type_index, notify=blueprintsChanged)
    techFilterIndex = Property(int, lambda self: self._bp_tech_index, notify=blueprintsChanged)
    marketFilterIndex = Property(int, lambda self: self._bp_market_index, notify=blueprintsChanged)
    searchText = Property(str, lambda self: self._bp_search, notify=blueprintsChanged)

    @Slot(int)
    def setTypeFilterIndex(self, index: int) -> None:
        if 0 <= index < len(_TYPE_FILTERS) and index != self._bp_type_index:
            self._bp_type_index = index
            self.applyBlueprintFilter()

    @Slot(int)
    def setTechFilterIndex(self, index: int) -> None:
        if 0 <= index < len(_TECH_FILTERS) and index != self._bp_tech_index:
            self._bp_tech_index = index
            self.applyBlueprintFilter()

    @Slot(int)
    def setMarketFilterIndex(self, index: int) -> None:
        if 0 <= index < len(self._bp_categories) and index != self._bp_market_index:
            self._bp_market_index = index
            self.applyBlueprintFilter()

    @Slot(str)
    def setBlueprintSearch(self, text: str) -> None:
        self._bp_search = str(text)
        self.applyBlueprintFilter()

    def _load_market_categories(self) -> None:
        from core.container import get_container

        self._bp_categories = [{"name": "全部", "id": None}]
        try:
            for mgid, name in get_container().item_repo.get_root_market_categories():
                if name:
                    self._bp_categories.append({"name": name, "id": mgid})
        except Exception:
            from core.logger import log

            log.exception("加载市场分类失败")
        self.blueprintsChanged.emit()

    @Slot()
    def loadBlueprints(self) -> None:
        """从 user_blueprints 载入蓝图并算好经济指标（占用标记、产物信息、成本/收入/利润率）。"""
        from core.container import get_container
        from services.inventory_manager import (
            get_blueprint_product_info_batch,
            get_blueprint_tech_levels,
            get_blueprints,
        )

        if not self._bp_tech_levels:
            self._bp_tech_levels = get_blueprint_tech_levels()
        if not self._bp_reaction_ids:
            from services.inventory_manager import get_blueprint_reaction_ids

            self._bp_reaction_ids = get_blueprint_reaction_ids()

        blueprints = get_blueprints(self._current_hangar_id)
        try:
            from services.plan_execution import get_occupied_blueprint_ids

            occupied = get_occupied_blueprint_ids()
        except Exception:
            occupied = set()

        product_info = get_blueprint_product_info_batch([bp["blueprint_type_id"] for bp in blueprints])

        rows: list[dict] = []
        for bp in blueprints:
            bp["occupied"] = bp["id"] in occupied
            bpid = bp["blueprint_type_id"]
            info = product_info.get(bpid)
            if info:
                bp["product_type_id"] = info["product_type_id"]
                bp["product_name"] = info["product_name"]
                bp["product_quantity"] = info["product_quantity"]
                bp["base_time"] = info["base_time"]
            else:
                bp["product_type_id"] = None
                bp["product_name"] = "-"
                bp["product_quantity"] = 1
                bp["base_time"] = 0
            if not bp.get("zh_name") and bp.get("product_name") and bp["product_name"] != "-":
                bp["display_name"] = bp["product_name"].replace(" II", "蓝图 II").replace(" I", "蓝图 I")
            bp["tech_level"] = self._bp_tech_levels.get(bpid, 1)
            bp["is_reaction"] = bpid in self._bp_reaction_ids
            rows.append(bp)

        self._bp_all_rows = rows
        self._calc_economics()
        self.applyBlueprintFilter()
        _ = get_container  # 保持导入（供子类/后续使用）

    def _calc_economics(self) -> None:
        """批量算材料成本 / 销售收入 / 利润率（原来的 1300 次逐条查询已批量化）。"""
        if not self._bp_all_rows:
            return
        from services.inventory_manager import get_blueprint_materials_batch

        bp_materials = get_blueprint_materials_batch([r["blueprint_type_id"] for r in self._bp_all_rows])

        material_ids: set[int] = set()
        for mats in bp_materials.values():
            for mid, _ in mats:
                material_ids.add(mid)
        product_ids: set[int] = {r["product_type_id"] for r in self._bp_all_rows if r.get("product_type_id")}

        prices: dict[int, float] = {}
        all_ids = material_ids | product_ids
        if all_ids:
            prices = dict(self._market_repo().get_sell_prices(list(all_ids), 10000002))

        for row in self._bp_all_rows:
            materials = bp_materials.get(row["blueprint_type_id"], [])
            total_cost = sum(qty * prices[mid] for mid, qty in materials if prices.get(mid))
            product_id = row.get("product_type_id")
            product_price = prices.get(product_id) if product_id else None

            row["material_cost"] = total_cost if total_cost > 0 else None
            row["revenue"] = (product_price * row.get("product_quantity", 1)) if product_price else None
            cost, revenue = row["material_cost"], row["revenue"]
            row["margin"] = ((revenue - cost) / cost * 100) if (cost and revenue) else None

    @Slot()
    def refreshEconomics(self) -> None:
        self._calc_economics()
        self.applyBlueprintFilter()

    @Slot()
    def applyBlueprintFilter(self) -> None:
        """类型 / 科技等级 / 市场分类 / 搜索 —— 全部在已载入的行上过滤。"""
        rows = self._bp_all_rows
        type_sel = _TYPE_FILTERS[self._bp_type_index]
        if type_sel == "蓝图原图":
            rows = [r for r in rows if r.get("is_bpo") and not r.get("is_reaction")]
        elif type_sel == "蓝图拷贝":
            rows = [r for r in rows if not r.get("is_bpo") and not r.get("is_reaction")]
        elif type_sel == "反应公式":
            rows = [r for r in rows if r.get("is_reaction")]

        tech_sel = _TECH_FILTERS[self._bp_tech_index]
        if tech_sel != "全部":
            target = int(tech_sel[1])
            rows = [r for r in rows if r.get("tech_level") == target]

        market_id = self._bp_categories[self._bp_market_index]["id"] if self._bp_categories else None
        if market_id is not None:
            matching = self._market_descendants(int(market_id))
            rows = [r for r in rows if r.get("product_type_id") in matching]

        search = self._bp_search.strip().lower()
        if search:
            rows = [
                r
                for r in rows
                if search in (r.get("zh_name") or "").lower()
                or search in (r.get("en_name") or "").lower()
                or search in (r.get("product_name") or "").lower()
                or search in str(r.get("blueprint_type_id", ""))
            ]

        self._blueprints.set_rows(rows)
        self._bp_count = f"共 {len(rows)} 个蓝图"
        self.blueprintsChanged.emit()

    def _market_descendants(self, market_group_id: int) -> set[int]:
        from core.container import get_container

        try:
            return set(get_container().item_repo.get_market_descendants(market_group_id))
        except Exception:
            from core.logger import log

            log.exception("获取市场分类后代失败")
            return set()

    @Slot(int, result=dict)
    def blueprintMenuState(self, row: int) -> dict:
        rows = self.blueprintsForMenu(row)
        return {"valid": bool(rows), "count": len(rows), "single": len(rows) == 1}

    @Slot(int)
    def copyBlueprintCell(self, row: int) -> None:
        """单击单元格即复制该格文本（对齐 Widgets 版的 `_on_cell_clicked`）。"""
        item = self._blueprints.row_at(row)
        if item:
            self._copy(self._blueprints._name(item))

    # ── 蓝图：菜单动作（对话框仍是 Widgets）────────────────────

    @Slot("QVariantList")
    def _blueprints_at(self, rows: list) -> list[dict]:
        out = []
        for row in rows:
            item = self._blueprints.row_at(int(row))
            if item:
                out.append(item)
        return out

    @Slot("QVariantList")
    def deleteBlueprints(self, rows: list) -> None:
        from services.inventory_manager import delete_blueprint

        for bp in self._blueprints_at(rows):
            delete_blueprint(bp["id"])
        self.loadBlueprints()

    @Slot("QVariantList")
    def moveBlueprints(self, rows: list) -> None:
        """修改蓝图所在机库（弹出机库选择框）。"""
        from PySide6.QtWidgets import QInputDialog

        from services.inventory_manager import move_blueprints_to_hangar

        blueprints = self._blueprints_at(rows)
        if not blueprints:
            return
        targets = [h for h in self._hangars if h["id"] != self._current_hangar_id]
        if not targets:
            self._set_bp_hint("没有其他机库可移动")
            return
        parent = self._shell if isinstance(self._shell, QWidget) else None
        name, ok = QInputDialog.getItem(parent, "移动到", "目标机库:", [h["label"] for h in targets], 0, False)
        if ok and name:
            target_id = next(h["id"] for h in targets if h["label"] == name)
            move_blueprints_to_hangar([bp["id"] for bp in blueprints], target_id)
            self.loadBlueprints()

    @Slot("QVariantList")
    def setBlueprintCostPerRun(self, rows: list) -> None:
        from PySide6.QtWidgets import QInputDialog

        from services.inventory_manager import update_blueprints_batch

        blueprints = self._blueprints_at(rows)
        if not blueprints:
            return
        parent = self._shell if isinstance(self._shell, QWidget) else None
        value, ok = QInputDialog.getDouble(parent, "每流程成本", "ISK:", float(blueprints[0].get("cost_per_run") or 0))
        if ok:
            update_blueprints_batch([bp["id"] for bp in blueprints], cost_per_run=float(value))
            self.loadBlueprints()

    @Slot("QVariantList")
    def autoFillCostPerRun(self, rows: list) -> None:
        """自动填写每流程成本（T2 发明）：走既有的批量计算 worker。"""
        from ui_qml.bridge.blueprint_actions import auto_fill_cost_per_run

        auto_fill_cost_per_run(self, self._blueprints_at(rows), self._current_hangar_id)

    @Slot("QVariantList")
    def editBlueprintLevels(self, rows: list) -> None:
        self._edit_numeric(rows, "me_level", "修改蓝图等级")

    @Slot("QVariantList")
    def editBlueprintRuns(self, rows: list) -> None:
        self._edit_numeric(rows, "runs", "修改流程数")

    def _edit_numeric(self, rows: list, field: str, title: str) -> None:
        from PySide6.QtWidgets import QInputDialog

        from services.inventory_manager import update_blueprints_batch

        blueprints = self._blueprints_at(rows)
        if not blueprints:
            return
        parent = self._shell if isinstance(self._shell, QWidget) else None
        value, ok = QInputDialog.getInt(parent, title, "数值:", int(blueprints[0].get(field) or 0), 0, 100)
        if ok:
            update_blueprints_batch([bp["id"] for bp in blueprints], **{field: value})
            self.loadBlueprints()

    @Slot("QVariantList")
    def showResearchAnalysis(self, rows: list) -> None:
        blueprints = self._blueprints_at(rows)
        if not blueprints:
            return
        from core.container import get_container
        from ui_qml.bridge.research_cost_bridge import ResearchCostQmlDialog as ResearchCostDialog

        bp = blueprints[0]
        name = bp.get("display_name") or bp.get("zh_name") or str(bp["blueprint_type_id"])
        ResearchCostDialog(get_container().db, int(bp["blueprint_type_id"]), name, parent=self._dialog_parent()).exec()

    @Slot("QVariantList")
    def addToManufacturingPlan(self, rows: list) -> None:
        """加入制造业规划：调既有的批量入计划编排。"""
        from ui_qml.bridge.blueprint_actions import add_blueprints_to_plan

        add_blueprints_to_plan(self, self._blueprints_at(rows))

    @Slot("QVariantList")
    def addCopyPlan(self, rows: list) -> None:
        from ui_qml.bridge.blueprint_actions import add_research_plan

        add_research_plan(self, self._blueprints_at(rows), "copy")

    @Slot("QVariantList")
    def addInventionPlan(self, rows: list) -> None:
        from ui_qml.bridge.blueprint_actions import add_research_plan

        add_research_plan(self, self._blueprints_at(rows), "invention")

    @Slot("QVariantList")
    def addResearchPlan(self, rows: list) -> None:
        from ui_qml.bridge.blueprint_actions import add_research_plan

        add_research_plan(self, self._blueprints_at(rows), "research")

    @Slot()
    def pasteBlueprints(self) -> None:
        """粘贴导入蓝图（剪贴板 → 审阅对话框）。"""
        from ui_qml.bridge.blueprint_actions import paste_blueprints

        paste_blueprints(self, self._current_hangar_id, self._current_hangar_label())

    def _dialog_parent(self) -> QWidget | None:
        """Widgets 对话框的父窗口（阶段 4 迁移完就不需要了）。"""
        return self._shell if isinstance(self._shell, QWidget) else None

    def _set_bp_hint(self, text: str) -> None:
        self._bp_count = text
        self.blueprintsChanged.emit()

    # ── 公共 ──────────────────────────────────────────────────

    def _market_repo(self) -> Any:
        from core.container import get_container

        return get_container().market_repo

    def _copy(self, text: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    @Slot()
    def refreshAll(self) -> None:
        self._reload_hangars()
        self.refreshItems()
        self.loadBlueprints()
