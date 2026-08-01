"""
仓库页面 — 蓝图管理 Tab
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from core.logger import log
from services.inventory_manager import (
    delete_blueprints_batch,
    get_blueprint_materials_batch,
    get_blueprint_product_info_batch,
    get_blueprint_reaction_ids,
    get_blueprint_tech_levels,
    get_blueprints,
    get_hangars,
    move_blueprints_to_hangar,
    update_blueprints_batch,
)

from .blueprint_import_worker import _BlueprintImportWorker
from .inventory_helpers import BlueprintTableModel


class BlueprintTab(QWidget):
    """蓝图管理 — 管理用户拥有的蓝图"""

    def __init__(self, inventory_page):
        super().__init__()
        self._page = inventory_page
        self.setObjectName("blueprint_tab")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 工具栏 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        paste_btn = QPushButton("粘贴导入蓝图")
        paste_btn.clicked.connect(self._on_paste_blueprint)
        toolbar.addWidget(paste_btn)

        self._refresh_econ_btn = QPushButton("刷新计算")
        self._refresh_econ_btn.clicked.connect(self._on_refresh_economics)
        toolbar.addWidget(self._refresh_econ_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # ── 过滤器 ──
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        filter_bar.addWidget(QLabel("类型:"))
        self._type_filter = QComboBox()
        self._type_filter.addItems(["全部", "蓝图原图", "蓝图拷贝", "反应公式"])
        self._type_filter.currentIndexChanged.connect(self._on_search)
        filter_bar.addWidget(self._type_filter)

        filter_bar.addWidget(QLabel("科技等级:"))
        self._tech_filter = QComboBox()
        self._tech_filter.addItems(["全部", "T1", "T2", "T3"])
        self._tech_filter.currentIndexChanged.connect(self._on_search)
        filter_bar.addWidget(self._tech_filter)

        filter_bar.addWidget(QLabel("市场分类:"))
        self._market_filter = QComboBox()
        self._market_filter.addItem("全部", None)
        self._market_filter.currentIndexChanged.connect(self._on_search)
        filter_bar.addWidget(self._market_filter, 1)

        layout.addLayout(filter_bar)

        # ── 搜索栏 ──
        search_bar = QHBoxLayout()
        search_bar.setSpacing(6)
        search_bar.addWidget(QLabel("搜索:"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("输入蓝图/产物名称...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search)
        search_bar.addWidget(self._search_input, 1)
        layout.addLayout(search_bar)

        # ── 蓝图列表 ──
        self._bp_table = QTableView()
        self._bp_table.setAlternatingRowColors(True)
        self._bp_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._bp_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._bp_table.horizontalHeader().setStretchLastSection(True)
        self._bp_table.setSortingEnabled(True)
        self._bp_table.verticalHeader().setDefaultSectionSize(32)
        self._bp_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._bp_table.customContextMenuRequested.connect(self._on_context_menu)
        self._bp_table.clicked.connect(self._on_cell_clicked)
        # 固定列宽（避免 ResizeToContents 扫描全表 O(n) 卡顿）
        hdr = self._bp_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, w in {0: 28, 1: 140, 2: 70, 3: 60, 4: 60, 5: 120, 6: 80, 7: 65, 8: 90, 9: 90, 10: 70}.items():
            self._bp_table.setColumnWidth(col, w)
        layout.addWidget(self._bp_table, 1)

        # ── 状态栏 ──
        status_bar = QHBoxLayout()
        self._bp_count_label = QLabel("")
        self._bp_count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        status_bar.addWidget(self._bp_count_label)
        status_bar.addStretch()
        layout.addLayout(status_bar)

        self._bp_model: BlueprintTableModel | None = None
        self._all_rows: list[dict] = []
        self._tech_levels: dict[int, int] = {}
        self._reaction_ids: set[int] = set()

        self._load_market_categories()
        self._load_blueprints()

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式表"""
        self._bp_count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")

    def _load_market_categories(self):
        """加载根级市场分类到下拉框"""
        with get_container().db.connect("ref") as conn:
            c = conn.cursor()
            c.execute("SELECT market_group_id, zh_name FROM market_tree WHERE parent_group_id IS NULL ORDER BY zh_name")
            for mgid, name in c.fetchall():
                if name:
                    self._market_filter.addItem(name, mgid)

    def _load_blueprints(self):
        """从 user_blueprints 加载用户拥有的蓝图"""
        if not self._tech_levels:
            self._tech_levels = get_blueprint_tech_levels()
        if not self._reaction_ids:
            self._reaction_ids = get_blueprint_reaction_ids()

        rows = []
        bps = get_blueprints(self._page.hangar_id())

        # 标记被活跃生产计划占用的蓝图（占用中显示橙色）
        try:
            from services.plan_execution import get_occupied_blueprint_ids

            occupied = get_occupied_blueprint_ids()
        except Exception:
            occupied = set()
        for bp in bps:
            bp["occupied"] = bp["id"] in occupied

        # 批量获取产物信息（1300 次 DB → 1 次）
        bp_ids = [bp["blueprint_type_id"] for bp in bps]
        prod_info_map = get_blueprint_product_info_batch(bp_ids)

        for bp in bps:
            bpid = bp["blueprint_type_id"]
            prod_info = prod_info_map.get(bpid)
            if prod_info:
                bp["product_type_id"] = prod_info["product_type_id"]
                bp["product_name"] = prod_info["product_name"]
                bp["product_quantity"] = prod_info["product_quantity"]
                bp["base_time"] = prod_info["base_time"]
            else:
                bp["product_type_id"] = None
                bp["product_name"] = "-"
                bp["product_quantity"] = 1
                bp["base_time"] = 0
            # T2 蓝图缺名时从产物名推导
            if not bp.get("zh_name") and bp.get("product_name") and bp["product_name"] != "-":
                bp["display_name"] = bp["product_name"].replace(" II", "蓝图 II").replace(" I", "蓝图 I")
            bp["tech_level"] = self._tech_levels.get(bpid, 1)
            bp["is_reaction"] = bpid in self._reaction_ids
            rows.append(bp)

        self._all_rows = rows
        self._calc_economics()
        self._apply_filter()

    def _calc_economics(self):
        """批量计算所有蓝图的经济指标"""
        if not self._all_rows:
            return

        bp_ids = [r["blueprint_type_id"] for r in self._all_rows]
        bp_materials = get_blueprint_materials_batch(bp_ids)

        mat_ids: set[int] = set()
        for mats in bp_materials.values():
            for mid, _ in mats:
                mat_ids.add(mid)

        prod_ids: set[int] = {r["product_type_id"] for r in self._all_rows if r.get("product_type_id")}

        # 批量查价格
        prices: dict[int, float] = {}
        all_ids = mat_ids | prod_ids
        if all_ids:
            with get_container().db.connect("mkt") as conn:
                c = conn.cursor()
                placeholders = ",".join("?" * len(all_ids))
                c.execute(
                    f"SELECT type_id, sell_price FROM market_prices"
                    f" WHERE type_id IN ({placeholders}) AND region_id = 10000002",
                    tuple(all_ids),
                )
                for tid, price in c.fetchall():
                    if price:
                        prices[tid] = price

        # 计算每行
        for row in self._all_rows:
            bpid = row["blueprint_type_id"]
            mats = bp_materials.get(bpid, [])
            total_cost = 0.0
            for mid, qty in mats:
                p = prices.get(mid)
                if p:
                    total_cost += qty * p

            prod_id = row.get("product_type_id")
            prod_qty = row.get("product_quantity", 1)
            prod_price = prices.get(prod_id) if prod_id else None

            row["material_cost"] = total_cost if total_cost > 0 else None
            if prod_price:
                row["revenue"] = prod_price * prod_qty
            else:
                row["revenue"] = None

            cost = row["material_cost"]
            rev = row["revenue"]
            if cost and rev:
                row["margin"] = (rev - cost) / cost * 100
            else:
                row["margin"] = None

    def _on_refresh_economics(self):
        self._refresh_econ_btn.setEnabled(False)
        self._refresh_econ_btn.setText("计算中...")
        self._calc_economics()
        self._apply_filter()
        self._refresh_econ_btn.setEnabled(True)
        self._refresh_econ_btn.setText("刷新计算")

    def _apply_filter(self):
        search = self._search_input.text().strip().lower() if self._search_input else ""
        type_sel = self._type_filter.currentText()
        tech_sel = self._tech_filter.currentText()
        market_id = self._market_filter.currentData()

        filtered = self._all_rows

        # 类型过滤
        if type_sel == "蓝图原图":
            filtered = [r for r in filtered if r.get("is_bpo") and not r.get("is_reaction")]
        elif type_sel == "蓝图拷贝":
            filtered = [r for r in filtered if not r.get("is_bpo") and not r.get("is_reaction")]
        elif type_sel == "反应公式":
            filtered = [r for r in filtered if r.get("is_reaction")]

        # 科技等级过滤
        if tech_sel != "全部":
            target = int(tech_sel[1])  # "T1" → 1
            filtered = [r for r in filtered if r.get("tech_level") == target]

        # 市场分类过滤（按产物所属分类）
        if market_id is not None:
            matching_ids = self._get_market_descendants(market_id)
            filtered = [r for r in filtered if r.get("product_type_id") in matching_ids]

        if search:
            filtered = [
                r
                for r in filtered
                if search in (r.get("zh_name") or "").lower()
                or search in (r.get("en_name") or "").lower()
                or search in (r.get("product_name") or "").lower()
                or search in str(r.get("blueprint_type_id", ""))
            ]

        self._bp_model = BlueprintTableModel(filtered)
        self._bp_table.setModel(self._bp_model)
        self._bp_count_label.setText(f"共 {len(filtered)} 个蓝图")

    def _get_market_descendants(self, market_group_id: int) -> set[int]:
        """递归获取指定市场分类下所有物品 type_id"""
        try:
            with get_container().db.connect("ref") as conn:
                c = conn.cursor()
                c.execute(
                    """
                    WITH RECURSIVE sub AS (
                        SELECT market_group_id FROM market_tree WHERE market_group_id = ?
                        UNION ALL
                        SELECT m.market_group_id FROM market_tree m JOIN sub ON m.parent_group_id = sub.market_group_id
                    )
                    SELECT DISTINCT i.type_id FROM item i
                    WHERE i.market_group_id IN (SELECT market_group_id FROM sub)
                """,
                    (market_group_id,),
                )
                return {r[0] for r in c.fetchall()}
        except Exception:
            log.exception("获取市场分类后代失败")
            return set()

    def _on_search(self):
        self._apply_filter()

    def _on_cell_clicked(self, idx):
        if not idx.isValid() or not self._bp_model or idx.column() == 0:
            return
        text = self._bp_model.data(idx, Qt.ItemDataRole.DisplayRole)
        if text and text not in ("", "-"):
            QApplication.clipboard().setText(str(text))

    def _on_context_menu(self, pos):
        sel_rows = {idx.row() for idx in self._bp_table.selectionModel().selectedRows()}
        idx = self._bp_table.indexAt(pos)
        if idx.isValid() and idx.row() not in sel_rows:
            sel_rows = {idx.row()}
        if not sel_rows or not self._bp_model:
            return
        selected = [self._bp_model.row_at(r) for r in sorted(sel_rows)]
        selected = [bp for bp in selected if bp]
        if not selected:
            return
        bp_ids = [bp["id"] for bp in selected]

        menu = QMenu(self)

        research = menu.addAction("研究分析")
        menu.addSeparator()
        del_action = menu.addAction("删除行" if len(bp_ids) == 1 else f"删除行 ({len(bp_ids)})")
        menu.addSeparator()
        move_action = menu.addAction("修改蓝图所在机库")
        cost_action = menu.addAction("修改蓝图每流程成本")
        auto_cost = menu.addAction("自动填写每流程成本(T2发明)")
        menu.addSeparator()
        add_plan = menu.addAction("加入制造业规划")
        menu.addSeparator()
        edit_level = menu.addAction("修改蓝图等级")
        edit_runs = menu.addAction("修改流程数")
        add_research = menu.addAction("加入效率研究规划")

        action = menu.exec(self._bp_table.viewport().mapToGlobal(pos))

        if action == del_action:
            self._delete_blueprints(selected)
        elif action == move_action:
            self._move_blueprints(bp_ids)
        elif action == cost_action:
            self._set_cost_per_run(bp_ids)
        elif action == edit_level:
            self._edit_levels(bp_ids)
        elif action == edit_runs:
            self._edit_runs(bp_ids)
        elif action in (research, auto_cost, add_plan, add_research):
            QMessageBox.information(self, "提示", "此功能即将上线")

    def _delete_blueprints(self, selected: list[dict]):
        n = len(selected)
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除 {n} 行蓝图吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        ids = [bp["id"] for bp in selected]
        delete_blueprints_batch(ids)
        self._load_blueprints()

    def _move_blueprints(self, bp_ids: list[int]):
        hangars = get_hangars()
        names = [h["name"] for h in hangars]
        name, ok = QInputDialog.getItem(self, "修改蓝图所在机库", "目标机库:", names, 0, False)
        if ok and name:
            target_id = next(h["id"] for h in hangars if h["name"] == name)
            move_blueprints_to_hangar(bp_ids, target_id)
            self._load_blueprints()

    def _set_cost_per_run(self, bp_ids: list[int]):
        val, ok = QInputDialog.getDouble(self, "修改每流程成本", "成本 (ISK):", 0, 0, 1e12, 2)
        if ok:
            update_blueprints_batch(bp_ids, cost_per_run=val)
            self._load_blueprints()

    def _edit_levels(self, bp_ids: list[int]):
        dlg = QDialog(self)
        dlg.setWindowTitle("修改蓝图等级")
        fl = QFormLayout(dlg)
        me = QDoubleSpinBox()
        me.setRange(0, 10)
        me.setDecimals(0)
        te = QDoubleSpinBox()
        te.setRange(0, 10)
        te.setDecimals(0)
        fl.addRow("材料等级:", me)
        fl.addRow("时间等级:", te)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(dlg.accept)
        btn.rejected.connect(dlg.reject)
        fl.addRow(btn)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            update_blueprints_batch(bp_ids, me_level=int(me.value()), te_level=int(te.value()))
            self._load_blueprints()

    def _edit_runs(self, bp_ids: list[int]):
        val, ok = QInputDialog.getInt(self, "修改流程数", "流程数:", 1, -1, 99999, 1)
        if ok:
            update_blueprints_batch(bp_ids, runs=val)
            self._load_blueprints()

    def _on_paste_blueprint(self):
        if not self._page.hangar_id():
            return
        raw = QApplication.clipboard().text().strip()
        if not raw:
            return

        main_win = self._page._main
        main_win.show_progress("正在导入蓝图...", 0)
        self._worker = _BlueprintImportWorker(raw, self._page.hangar_id())
        self._worker.progress.connect(lambda cur, total, text: main_win.update_progress(cur, text) if total else None)
        self._worker.finished.connect(self._on_import_done)
        self._worker.start()

    def _on_import_done(self, added: int, removed: int, total: int):
        self._page._main.hide_progress(f"共 {total} 条蓝图")
        if added == 0 and removed == 0:
            self._bp_count_label.setText("蓝图库无变化")
        else:
            parts = [f"共 {total} 条"]
            if added:
                parts.append(f"新增 {added}")
            if removed:
                parts.append(f"删除 {removed}")
            self._bp_count_label.setText("，".join(parts))
        self._load_blueprints()
        self._worker = None
