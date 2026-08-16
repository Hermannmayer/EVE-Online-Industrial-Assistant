"""
仓库页面 — 蓝图管理 Tab
"""

from PySide6.QtCore import Qt, QThread, Signal
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

from .blueprint_import_worker import _BlueprintImportWorker, apply_blueprint_diff
from .inventory_helpers import BlueprintTableModel


class _BulkPlanMetricsWorker(QThread):
    """后台批量计算各组合并后的派生指标（评分较重，避免卡死 UI）。"""

    done = Signal(list)

    def __init__(self, group_items: list[list[dict]], product_name: str, char_name: str, parent=None):
        super().__init__(parent)
        self._group_items = group_items
        self._product_name = product_name
        self._char_name = char_name

    def run(self):
        from services import inventory_manager, plan_service, user_settings

        # 价格来源设置（材料/成品 hub）替代硬编码 "Jita"，与单条添加流程口径一致
        settings = user_settings.load_settings()
        price_settings = settings.get("price_settings") or {}
        mat_hub = price_settings.get("mat_hub", "Jita")
        sell_hub = price_settings.get("prod_hub", "Jita")
        # 产出机库默认（机库设置里配置）→ 写入计划，下线时自动入库
        deposit_hangar_id = settings.get("default_deposit_hangar_id")
        # 从默认材料机库带出星系，写入计划（避免空星系 → 回退吉他 SCI）
        mat_hangar_id, solar_system_id = inventory_manager.get_default_mat_hangar_and_system()
        hangar_name = inventory_manager.get_hangar_name(mat_hangar_id)

        rows = []
        for bps in self._group_items:
            parallels = len(bps)
            d = {
                "parallels": parallels,
                "me": bps[0].get("me_level") or 0,
                "te": bps[0].get("te_level") or 0,
                "char": self._char_name,
                "fac": hangar_name,
                "runs": bps[0].get("runs") or 1,
            }
            metrics = plan_service.calculate_plan_metrics(
                {
                    "product_type_id": bps[0]["product_type_id"],
                    "product_name": self._product_name,
                    "runs": d["runs"],
                    "parallels": parallels,
                    "me_level": d["me"],
                    "te_level": d["te"],
                    "mat_hub": mat_hub,
                    "sell_hub": sell_hub,
                    "char_name": d["char"],
                    "facility": hangar_name,
                    "mat_hangar_id": mat_hangar_id,
                    "solar_system_id": solar_system_id,
                },
                char_name=self._char_name,
            )
            rows.append(
                {
                    "type_id": bps[0]["product_type_id"],
                    "product_name": self._product_name,
                    "data": d,
                    "metrics": metrics,
                    "bp_ids": [b["id"] for b in bps],
                    "mat_hangar_id": mat_hangar_id,
                    "solar_system_id": solar_system_id,
                    "deposit_hangar_id": deposit_hangar_id,
                    "mat_hub": mat_hub,
                    "sell_hub": sell_hub,
                }
            )
        self.done.emit(rows)


class BlueprintTab(QWidget):
    """蓝图管理 — 管理用户拥有的蓝图"""

    def __init__(self, inventory_page):
        super().__init__()
        self._page = inventory_page
        self.setObjectName("blueprint_tab")
        # QThread 强引用保活（防局部变量被 GC 导致闪退）
        self._add_plan_bulk: QThread | None = None

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
        self._bp_table.verticalHeader().setVisible(False)
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
        for mgid, name in get_container().item_repo.get_root_market_categories():
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
            prices = get_container().market_repo.get_sell_prices(list(all_ids), 10000002)

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
            return get_container().item_repo.get_market_descendants(market_group_id)
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
        elif action == add_plan:
            self._on_add_to_plan(selected)
        elif action in (research, auto_cost, add_research):
            QMessageBox.information(self, "提示", "此功能即将上线")

    def _on_add_to_plan(self, selected: list[dict]):
        """加入制造业规划：多选蓝图 → 相同(蓝图类型+ME+TE+流程)合并成一行并行 → 后台评分后批量落库绑定。

        整张直接加入，不弹配置对话框：流程/蓝图等级/设施均按蓝图自身属性。
        """
        from services import plan_execution, plan_service

        valid = [bp for bp in selected if bp.get("product_type_id")]
        if not valid:
            QMessageBox.information(self, "提示", "所选蓝图无产物信息")
            return
        # 完全相同（蓝图类型+ME+TE+每张流程）的蓝图合并成一行：parallels=张数, runs=每张流程
        groups: dict[tuple, list[dict]] = {}
        for bp in valid:
            key = (
                bp.get("blueprint_type_id"),
                int(bp.get("me_level") or 0),
                int(bp.get("te_level") or 0),
                int(bp.get("runs") or 1),
            )
            groups.setdefault(key, []).append(bp)

        product_name = valid[0].get("product_name") or valid[0].get("display_name") or "?"
        char_name = ""
        try:
            from services.char_config_resolver import get_character_list

            chars = get_character_list()
            if chars:
                char_name = chars[0]
        except Exception:
            pass

        # 后台线程批量计算各组合并后的派生指标（评分较重，避免卡死 UI）
        bulk = _BulkPlanMetricsWorker(
            list(groups.values()),
            product_name,
            char_name,
            parent=self,
        )
        self._add_plan_bulk = bulk  # 强引用保活，防止局部 QThread 被 GC 导致闪退

        def _on_bulk_done(rows: list):
            # 批量插入 + 批量绑定（一次连接），主线程只做轻量 SQL
            try:
                ids = plan_service.insert_plans_batch(rows)
                bindings = [(pid, r["bp_ids"]) for pid, r in zip(ids, rows, strict=False) if pid and pid > 0]
                if bindings:
                    plan_execution.bind_blueprints_many(bindings)
                QMessageBox.information(
                    self,
                    "完成",
                    f"已加入制造业规划 {len(rows)} 行（{len(valid)} 张蓝图，合并 {len(groups)} 组）",
                )
                self._load_blueprints()
            finally:
                self._add_plan_bulk = None

        bulk.done.connect(_on_bulk_done)
        bulk.start()

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
        """粘贴导入蓝图 — 材料式流程：解析 → 预览确认（增量/全量）→ 应用 → 变动汇总。"""
        if not self._page.hangar_id():
            return
        raw = QApplication.clipboard().text().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "剪贴板为空，请先在游戏中复制蓝图（Ctrl+C）")
            return

        hid = self._page.hangar_id()
        hangar_name = self._page._hangar_combo.currentText() if hasattr(self._page, "_hangar_combo") else ""

        # 导入前快照（供全量同步差异对比）
        before_map: dict[tuple, int] = {}
        for bp in get_blueprints(hid):
            before_map[(bp["blueprint_type_id"], bp["is_bpo"], bp["me_level"], bp["te_level"], bp["runs"])] = (
                before_map.get((bp["blueprint_type_id"], bp["is_bpo"], bp["me_level"], bp["te_level"], bp["runs"]), 0)
                + 1
            )

        main_win = self._page._main
        main_win.show_progress("正在解析蓝图...", 0)
        self._worker = _BlueprintImportWorker(raw, hid, parent=self)
        self._worker.progress.connect(lambda cur, total, text: main_win.update_progress(cur, text) if total else None)
        self._worker.finished.connect(lambda diff: self._on_blueprint_diff_ready(diff, hid, hangar_name, before_map))
        self._worker.start()

    def _on_blueprint_diff_ready(self, diff: list[dict], hid: int, hangar_name: str, before_map: dict[tuple, int]):
        """diff 就绪 → 弹预览对话框 → 确认后应用 → 变动汇总。"""
        from .blueprint_import_dialog import BlueprintImportChangeDialog, BlueprintImportReviewDialog
        from .blueprint_import_worker import build_blueprint_changes

        self._page._main.hide_progress(f"共 {len(diff)} 类蓝图")
        self._worker = None
        if not diff:
            self._bp_count_label.setText("剪贴板无有效蓝图数据")
            return

        dlg = BlueprintImportReviewDialog(diff, hangar_name, self, default_mode="full")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        mode = dlg.mode()
        applied = dlg.get_applied_rows()

        added, removed = apply_blueprint_diff(applied, hid, mode)

        # 导入后快照 → 变动汇总弹窗
        after_map: dict[tuple, int] = {}
        for bp in get_blueprints(hid):
            after_map[(bp["blueprint_type_id"], bp["is_bpo"], bp["me_level"], bp["te_level"], bp["runs"])] = (
                after_map.get((bp["blueprint_type_id"], bp["is_bpo"], bp["me_level"], bp["te_level"], bp["runs"]), 0)
                + 1
            )
        names_map = {
            bp["blueprint_type_id"]: bp["zh_name"] or bp.get("display_name") or f"ID:{bp['blueprint_type_id']}"
            for bp in get_blueprints(hid)
        }
        changes = build_blueprint_changes(before_map, after_map, names_map)
        BlueprintImportChangeDialog(changes, added, removed, hangar_name or "蓝图", self).exec()

        self._load_blueprints()
