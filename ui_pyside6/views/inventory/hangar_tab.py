"""
仓库页面 — 机库管理 Tab
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.eve_formulas import resolve_item_name
from services.inventory_import import split_clipboard_lines
from services.inventory_manager import (
    add_item,
    get_hangars,
    get_items,
    move_items,
    remove_item,
    set_item_quantity,
    update_cost_price,
    update_quantity,
)
from services.name_resolver import search_item_type_id
from ui_pyside6.dialogs.hangar_dialogs import (
    AddItemDialog,
    BatchCostPriceDialog,
    EditQtyDialog,
)

from .inventory_helpers import InvTableModel


class HangarTab(QWidget):
    """机库管理 — 多机库库存管理"""

    def __init__(self, inventory_page):
        super().__init__()
        self._page = inventory_page
        self.setObjectName("hangar_tab")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._build_action_bar(layout)

        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSortingEnabled(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.verticalHeader().setDefaultSectionSize(32)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)

        self._model: InvTableModel | None = None
        self._refresh()
        self._apply_header_style()

    def _build_action_bar(self, layout):
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self._adjust_btn = QPushButton("库存修正")
        self._adjust_btn.clicked.connect(self._on_adjust_inventory)
        bar.addWidget(self._adjust_btn)

        self._transfer_btn = QPushButton("移库")
        self._transfer_btn.clicked.connect(self._on_transfer)
        bar.addWidget(self._transfer_btn)

        self._cov_btn = QPushButton("查看规划缺失材料")
        self._cov_btn.clicked.connect(self._on_material_coverage)
        bar.addWidget(self._cov_btn)

        self._add_btn = QPushButton("手动添加物品")
        self._add_btn.clicked.connect(self._on_add_item)
        bar.addWidget(self._add_btn)

        bar.addStretch()

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        bar.addWidget(self._count_label)

        layout.addLayout(bar)

        self._total_label = QLabel("按卖单价格: -- ISK")
        self._total_label.setStyleSheet(f"font-weight: bold; color: {theme.PRIMARY}; font-size: 13px;")
        layout.addWidget(self._total_label)

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式表"""
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        self._total_label.setStyleSheet(f"font-weight: bold; color: {theme.PRIMARY}; font-size: 13px;")
        self._apply_header_style()

    # ── 列布局 ──

    def _apply_column_layout(self):
        """列宽自适应：图标列 Fixed，其余内容自适应 + 最小宽度兜底 + 名称列上限。

        顺序仿工业制造 PlanTable：全部 ResizeToContents → resizeColumnsToContents
        → 再 re-fix 图标列（resize 会无视 Fixed 重置宽度，顺序不能反）。
        """
        if self._model is None:
            return
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(24)
        ncols = len(InvTableModel._HEADERS)
        for col in range(ncols):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.resizeColumnsToContents()
        # 图标列收紧
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 36)
        # 名称列：最小 120，最大不超过可用宽度一半，允许手动调整
        avail = max(header.width(), 800)
        name_w = min(max(header.sectionSize(1), 120), avail // 2)
        header.resizeSection(1, name_w)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        # 其余数字列最小宽度兜底（内容过窄时）
        for col, min_w in {2: 70, 3: 90, 4: 70, 5: 70, 6: 100, 7: 100}.items():
            if header.sectionSize(col) < min_w:
                header.resizeSection(col, min_w)

    def _apply_header_style(self):
        """表头紧凑 QSS（仿工业制造 PlanTable），避免「图标」等短表头撑宽列。

        作用在 horizontalHeader 上，不覆盖整表主题样式。
        """
        self._table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{ background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f" border: 1px solid {theme.BORDER}; padding: 2px 4px; font-size: 11px; }}"
        )

    # ── 剪贴板导入 ──

    def _parse_clipboard(self, raw: str) -> list[dict]:
        """解析 EVE 剪贴板 → list[{type_id|None, raw_name, zh_name, en_name, qty, status}]

        名称匹配走 search_item_type_id（精确 → 模糊 → 引号归一化 → terminology 反向）；
        未命中 item 的行保留为 status='unmatched'（type_id=None），供弹窗手动映射。
        """
        rows: list[dict] = []
        with get_container().db.connect("ref") as conn:
            for entry in split_clipboard_lines(raw):
                name = entry["name"]
                type_id = search_item_type_id(conn, name)
                if type_id:
                    nm = resolve_item_name(conn, type_id)
                    rows.append(
                        {
                            "type_id": type_id,
                            "raw_name": name,
                            "zh_name": nm if not nm.isdigit() else name,
                            "en_name": "" if nm.isdigit() else nm,
                            "qty": entry["qty"],
                            "status": "matched",
                        }
                    )
                else:
                    rows.append(
                        {
                            "type_id": None,
                            "raw_name": name,
                            "zh_name": "",
                            "en_name": "",
                            "qty": entry["qty"],
                            "status": "unmatched",
                        }
                    )
        return rows

    def _on_adjust_inventory(self):
        """库存修正 — 游戏全选复制 → 比对剪贴板与库存 → 逐物品确认增减/成本/是否变更。"""
        from services.inventory_import import compute_import_diff

        from .review_dialog import ImportChangeDialog, ImportReviewDialog

        if not self._page.hangar_id():
            return
        hid = self._page.hangar_id()
        # 自动读取剪贴板
        raw = QApplication.clipboard().text().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "剪贴板为空，请先在游戏中复制物品（Ctrl+C）")
            return
        parsed = self._parse_clipboard(raw)
        if not parsed:
            return
        hangar_name = self._page._hangar_combo.currentText()
        # 导入前快照（数量+成本），供全量同步差异对比
        before_items = get_items(hid)
        before = {it["type_id"]: (it["quantity"], it.get("cost_price") or 0) for it in before_items}
        names_before = {it["type_id"]: self._item_name(it) for it in before_items}

        # 库存修正默认全量同步（以游戏剪贴板为权威覆盖）
        dlg = ImportReviewDialog(parsed, hangar_name, hid, self, default_mode="full")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_import_data()
        if not data:
            return
        mode = dlg.mode()
        added = 0
        moved = 0
        if mode == "full":
            # 全量同步：以剪贴板为权威覆盖（增/减/归零删除）；跨机库行保持移动语义
            targets = dlg.get_sync_targets()
            for type_id, _delta, price, src_hangar in data:
                if src_hangar is not None:
                    if self._move_from_hangar(src_hangar, type_id):
                        moved += 1
                    continue
                final_qty = targets.get(type_id)
                if final_qty is None:
                    continue
                if set_item_quantity(hid, type_id, final_qty, price):
                    added += 1
        else:
            # 增量累加：delta>0 累加；跨机库行移动
            for type_id, delta, price, src_hangar in data:
                if delta <= 0:
                    continue
                if src_hangar is not None:
                    if self._move_from_hangar(src_hangar, type_id):
                        moved += 1
                else:
                    rid = add_item(hid, type_id, delta, price)
                    if rid != -1:
                        added += 1
        self._refresh()
        # 导入后快照 → 差异对比 → 变动弹窗（原「成功导入 N 条」信息并入其中）
        after_items = get_items(hid)
        after = {it["type_id"]: (it["quantity"], it.get("cost_price") or 0) for it in after_items}
        names_after = {it["type_id"]: self._item_name(it) for it in after_items}
        type_ids = list(dict.fromkeys(list(before) + list(after)))
        names = {**names_before, **names_after}
        changes = compute_import_diff(before, after, names, type_ids)
        ImportChangeDialog(changes, added, moved, hangar_name, self).exec()

    def _on_transfer(self):
        """移库 — 游戏全选复制源机库 → 选择来源机库 → 按剪贴板数量移到当前机库。"""
        if not self._page.hangar_id():
            return
        raw = QApplication.clipboard().text().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "剪贴板为空，请先在游戏中复制物品（Ctrl+C）")
            return
        parsed = self._parse_clipboard(raw)
        if not parsed:
            return
        from .transfer_dialog import HangarTransferDialog

        dlg = HangarTransferDialog(
            parsed, self._page.hangar_id(), self._page._hangar_combo.currentText(), self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh()

    def _move_from_hangar(self, src_hangar: int, type_id: int) -> bool:
        """从源机库找到该物品并整体移动到当前机库，返回是否移动。"""
        src_item = next((it for it in get_items(src_hangar) if it["type_id"] == type_id), None)
        if src_item:
            move_items([src_item["id"]], self._page.hangar_id())
            return True
        return False

    # ── 移动 ──

    def _on_move_items(self):
        if not self._page.hangar_id() or not self._model:
            return
        sel = self._table.selectionModel().selectedRows()
        if not sel:
            QMessageBox.information(self, "提示", "请先选中要移动的物品")
            return
        ids = [self._model.item_at(r.row())["id"] for r in sel]
        hangars = get_hangars()
        targets = [h for h in hangars if h["id"] != self._page.hangar_id()]
        if not targets:
            QMessageBox.information(self, "提示", "没有其他机库可移动")
            return
        names = [h["name"] for h in targets]
        name, ok = QInputDialog.getItem(self, "移动到", "目标机库:", names, 0, False)
        if ok and name:
            target_id = next(h["id"] for h in targets if h["name"] == name)
            move_items(ids, target_id)
            self._refresh()

    # ── 右键菜单 ──

    def _selected_rows(self) -> list[int]:
        """当前选中行号（升序）"""
        return sorted({idx.row() for idx in self._table.selectionModel().selectedRows()})

    def _on_context_menu(self, pos):
        if not self._model:
            return
        # 多行选择：右键到选中区外则只操作该行
        rows = self._selected_rows()
        idx = self._table.indexAt(pos)
        if idx.isValid() and idx.row() not in rows:
            rows = [idx.row()]
        if not rows:
            return
        items = [self._model.item_at(r) for r in rows if self._model.item_at(r)]
        if not items:
            return
        n = len(items)

        menu = QMenu(self)

        # 编辑数量：仅单行生效（批量数量编辑语义不明确）
        if n == 1:
            edit_act = QAction("编辑数量", self)
            edit_act.triggered.connect(lambda: self._on_edit_qty(items[0]))
            menu.addAction(edit_act)

        # 批量编辑成本价：吉他卖价/买价/均价 × 折扣率，或手动输入数字
        cost_act = QAction("编辑成本价", self)
        cost_act.triggered.connect(lambda: self._on_edit_cost_batch(items))
        menu.addAction(cost_act)

        # 批量删除
        del_act = QAction(f"删除 ({n})" if n > 1 else "删除", self)
        del_act.triggered.connect(lambda: self._on_del_items(items))
        menu.addAction(del_act)

        # 批量移动到
        move_menu = menu.addMenu(f"移动到 ({n})" if n > 1 else "移动到")
        ids = [it["id"] for it in items]
        for h in get_hangars():
            if h["id"] != self._page.hangar_id():
                act = QAction(h["name"], self)
                act.triggered.connect(lambda checked, hid=h["id"], ids_=ids: self._on_move_batch(ids_, hid))
                move_menu.addAction(act)

        menu.addSeparator()
        # 复制名称 / type_id（多行时换行拼接）
        copy_name = QAction("复制名称", self)
        copy_name.triggered.connect(
            lambda: QApplication.instance().clipboard().setText("\n".join(self._item_name(it) for it in items))
        )
        menu.addAction(copy_name)

        copy_id = QAction("复制 type_id", self)
        copy_id.triggered.connect(
            lambda: QApplication.instance().clipboard().setText("\n".join(str(it["type_id"]) for it in items))
        )
        menu.addAction(copy_id)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    @staticmethod
    def _item_name(item: dict) -> str:
        """统一显示名：display_name（terminology 覆盖优先）→ zh → en → str(id)"""
        return item.get("display_name") or item.get("zh_name") or item.get("en_name") or str(item.get("type_id", ""))

    def _on_edit_qty(self, item: dict):
        dlg = EditQtyDialog(self._item_name(item), item["quantity"], self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            qty = dlg.quantity()
            if qty >= 0:
                update_quantity(item["id"], qty)
                self._refresh()

    def _on_del_item(self, item: dict):
        name = self._item_name(item)
        if (
            QMessageBox.question(
                self, "确认", f"删除 {name}？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            == QMessageBox.StandardButton.Yes
        ):
            remove_item(item["id"])
            self._refresh()

    def _on_edit_cost_batch(self, items: list[dict]):
        """批量设置成本价：吉他卖价/买价/均价 × 折扣率，或手动输入数字。"""
        dlg = BatchCostPriceDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        source = dlg.price_type()
        updated = 0
        skipped: list[str] = []
        if source == "manual":
            manual = dlg.manual_price()
            for it in items:
                update_cost_price(it["id"], manual)
                updated += 1
        else:
            discount = dlg.discount()
            prices = self._fetch_market_prices([it["type_id"] for it in items], source)
            for it in items:
                base = prices.get(it["type_id"])
                if base is None:
                    skipped.append(self._item_name(it))
                    continue
                update_cost_price(it["id"], round(base * discount, 2))
                updated += 1
        self._refresh()
        msg = f"已更新 {updated} 项成本价"
        if skipped:
            shown = "、".join(skipped[:3])
            if len(skipped) > 3:
                shown += " 等"
            msg += f"；{len(skipped)} 项无市场价未更新（{shown}）"
        QMessageBox.information(self, "完成", msg)

    def _fetch_market_prices(self, type_ids: list[int], price_type: str) -> dict[int, float]:
        """批量查询吉他(Jita)市场价格 {type_id: 卖价/买价/均价}。"""
        tids = list(dict.fromkeys(type_ids))
        if not tids:
            return {}
        result: dict[int, float] = {}
        placeholders = ",".join("?" * len(tids))
        with get_container().db.connect("mkt") as conn:
            c = conn.cursor()
            if price_type == "avg":
                c.execute(
                    f"SELECT type_id, sell_price, buy_price FROM market_prices"
                    f" WHERE type_id IN ({placeholders}) AND region_id = ?",
                    (*tids, TRADE_HUB_IDS["Jita"]),
                )
                for tid, sell, buy in c.fetchall():
                    if sell and buy:
                        result[tid] = (sell + buy) / 2
                    elif sell or buy:
                        result[tid] = sell or buy
            else:
                col = "sell_price" if price_type == "sell" else "buy_price"
                c.execute(
                    f"SELECT type_id, {col} FROM market_prices"
                    f" WHERE type_id IN ({placeholders}) AND region_id = ?",
                    (*tids, TRADE_HUB_IDS["Jita"]),
                )
                for tid, price in c.fetchall():
                    if price is not None:
                        result[tid] = float(price)
        return result

    def _on_del_items(self, items: list[dict]):
        """批量删除（含单行）"""
        if len(items) == 1:
            self._on_del_item(items[0])
            return
        names = "、".join(self._item_name(it) for it in items[:3])
        if len(items) > 3:
            names += f" 等 {len(items)} 项"
        if (
            QMessageBox.question(
                self, "确认", f"删除 {names}？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            == QMessageBox.StandardButton.Yes
        ):
            for it in items:
                remove_item(it["id"])
            self._refresh()

    def _on_move_batch(self, item_ids: list[int], target_id: int):
        """批量移动到目标机库"""
        move_items(item_ids, target_id)
        self._refresh()

    def _on_add_item(self):
        if not self._page.hangar_id():
            return
        hangar_name = self._page._hangar_combo.currentText()
        dlg = AddItemDialog(hangar_name, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data:
            return
        type_id, qty, cost = data
        rid = add_item(self._page.hangar_id(), type_id, qty, cost)
        if rid == -1:
            QMessageBox.warning(self, "提示", "添加失败")
            return
        self._refresh()

    def _on_material_coverage(self):
        if not self._page.hangar_id():
            return
        hangar_name = self._page._hangar_combo.currentText()
        from .material_coverage_dialog import MaterialCoverageDialog

        MaterialCoverageDialog(self._page.hangar_id(), hangar_name, self).exec()

    # ── 刷新 ──

    def _refresh(self):
        if not self._page.hangar_id():
            return
        items = get_items(self._page.hangar_id())
        self._model = InvTableModel(items)
        self._table.setModel(self._model)
        self._apply_column_layout()
        self._count_label.setText(f"共 {len(items)} 项")

        # 计算总价
        total = sum((it["quantity"] * (it.get("sell_price") or 0)) for it in items if it.get("sell_price"))
        self._total_label.setText(f"按卖单价格: {total:,.0f} ISK")
