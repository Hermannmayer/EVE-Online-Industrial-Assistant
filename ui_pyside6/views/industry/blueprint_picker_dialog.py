"""蓝图选择弹窗 — 单击计划蓝图列 / 右键「绑定库存蓝图」时弹出。

一条产线（parallels 之一）独占一张库存蓝图：parallels 条产线需勾选 parallels 张蓝图，
每张可用流程 ≥ runs（该产线串行轮数）。用复选框多选，勾选/取消即实时写入绑定
（勾选集 = 最终绑定集，全量替换）；底部状态栏常显「已选 X / 需 Y 张」，不足提示还差几张。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from services import plan_execution
from services.industry_dialog_queries import get_blueprint_picker_data

_COL_CHECK = 0
_COL_TYPE = 1
_COL_ME = 2
_COL_TE = 3
_COL_AVAIL = 4
_COL_HANGAR = 5

_BIG_INFINITY = 10**15


def _available_runs(opt: dict) -> int:
    """BPC 可用流程 = quantity×runs；BPO 视为无限。"""
    if opt.get("is_bpo"):
        return _BIG_INFINITY
    return int(opt.get("available_runs") or 0)


class BlueprintPickerDialog(QDialog):
    """蓝图多选绑定弹窗 — 一条产线一张蓝图，复选框即绑即生效"""

    _HEADERS = ["勾选", "类型", "ME", "TE", "可用流程", "机库"]

    def __init__(self, plan: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._plan = plan
        self.selected_blueprint_ids: list[int] = []  # 确认后的绑定集合
        self.need_count: int = 1  # 需要的产线条数（parallels）
        self._options: list[dict] = []
        self._loading = True  # 构建期屏蔽 _reconcile 的即时绑定

        self.setWindowTitle(f"绑定库存蓝图 - {plan.get('product_name', '')}")
        self.setMinimumSize(680, 480)
        self._build_ui()
        self._load()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        self._need_label = QLabel("")
        root.addWidget(self._need_label)

        self._table = QTableWidget()
        self._table.setColumnCount(len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_HANGAR, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._table, 1)

        self._status_label = QLabel("")
        root.addWidget(self._status_label)

        self._empty_hint = QLabel("")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._empty_hint)

        btn_layout = QHBoxLayout()
        npc_btn = QPushButton("查看NPC卖家")
        npc_btn.clicked.connect(self._on_npc_seller)
        btn_layout.addWidget(npc_btn)
        btn_layout.addStretch(1)
        done_btn = QPushButton("完成")
        done_btn.clicked.connect(self._on_done)
        btn_layout.addWidget(done_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        root.addLayout(btn_layout)

    # ── 数据加载 ──────────────────────────────────────────────

    def _load(self) -> None:
        plan_id = self._plan.get("id")
        product_type_id = self._plan.get("product_type_id")
        runs = max(int(self._plan.get("runs", 1)), 1)

        # 以 DB 权威值为准读取当前绑定与产线数
        state: dict = (
            plan_execution.get_plan_binding_state(plan_id)
            if plan_id
            else {"bound": [], "need": int(self._plan.get("parallels") or 1), "runs": runs}
        )
        bound_ids = list(state.get("bound") or [])
        need = max(int(state.get("need") or 1), 1)
        db_runs = max(int(state.get("runs") or 1), 1)
        self.need_count = need

        self._need_label.setText(
            f"产品 {self._plan.get('product_name', '')}  需 {need} 张蓝图（{need} 条并行产线）× 每条 {db_runs} 流程"
        )

        blueprint_type_id, options = get_blueprint_picker_data(get_container().db, int(product_type_id or 0))
        self._blueprint_type_id = blueprint_type_id
        if blueprint_type_id is None:
            self._empty_hint.setText("无法确定该产品的蓝图类型")
            self._table.setEnabled(False)
            self._loading = False
            return
        self._options = options
        if not options:
            self._empty_hint.setText("库存中没有该蓝图。可通过「查看NPC卖家」购买原图，或从游戏粘贴导入。")
            self._table.setEnabled(False)
            self._loading = False
            return

        # 占用校正：排除本计划自身占用（自己已绑定的 BPC 显示可用、默认勾选）
        occupied_others = plan_execution.get_occupied_blueprint_ids(get_container().db, exclude_plan_id=plan_id)
        bound_set = set(bound_ids)

        self._table.setRowCount(len(options))
        self._checkboxes: list[QCheckBox] = []
        for i, opt in enumerate(options):
            is_self = opt["id"] in bound_set
            occupied = is_self or (opt.get("occupied") or opt["id"] in occupied_others)
            # 只有被其他活跃计划占用的行禁勾选；流程不足仅黄字提示但仍可勾选
            disabled = occupied and not is_self
            avail = _available_runs(opt)
            runs_short = not opt.get("is_bpo") and avail < db_runs

            cb = QCheckBox()
            cb.setEnabled(not disabled)
            cb.setChecked(is_self)
            cb.toggled.connect(self._on_toggled)
            self._table.setCellWidget(i, _COL_CHECK, self._centered(cb))
            self._checkboxes.append(cb)

            bp_type = "原图" if opt.get("is_bpo") else "拷贝"
            avail_text = "无限" if opt.get("is_bpo") else f"{avail:,}"
            status = "占用中" if occupied and not is_self else ("流程不足" if runs_short else "可用")
            cells = [
                bp_type,
                str(opt.get("me_level", 0)),
                str(opt.get("te_level", 0)),
                avail_text,
                opt.get("hangar_name", "") or "-",
                status,
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if disabled:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self._table.setItem(i, c + 1, item)  # 0 列是复选框，文本列从 1 起

        self._loading = False
        self._reconcile()

    # ── 交互 ──────────────────────────────────────────────────

    @staticmethod
    def _centered(w: QWidget) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(w)
        return wrap

    def _on_toggled(self, _checked: bool) -> None:
        if self._loading:
            return
        need = max(int(self.need_count), 1)
        # 一条产线一张蓝图：最多勾 need 张，满额后新增勾选回滚并提示，
        # 保证绑定的就是用户亲手勾选的那几张（无静默截断）。
        if need and self._count_checked() > need:
            cb = self.sender()
            if isinstance(cb, QCheckBox):
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
            self._refresh_status(truncated=True)
            return
        self._reconcile()

    def _count_checked(self) -> int:
        return sum(1 for cb in self._checkboxes if cb.isChecked() and cb.isEnabled())

    # ── 多选 + 右键批量勾选 ─────────────────────────────────

    def _show_context_menu(self, pos) -> None:
        """右键菜单：对多选行批量勾选/取消勾选（而非逐个点复选框）。"""
        indexes = self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        sel_rows = {idx.row() for idx in indexes}
        # 右键未落在选中集时，补入右键所在行
        hit = self._table.indexAt(pos)
        if hit.isValid():
            sel_rows.add(hit.row())
        # 过滤掉 disabled 行（被其他计划占用不可勾选）
        enabled_rows = [r for r in sel_rows if r < len(self._checkboxes) and self._checkboxes[r].isEnabled()]
        if not enabled_rows:
            return
        menu = QMenu(self)
        any_checked = any(self._checkboxes[r].isChecked() for r in enabled_rows)
        menu.addAction("勾选所选蓝图", lambda: self._set_selected_checked(enabled_rows, True))
        menu.addAction(
            "取消勾选所选蓝图" if any_checked else "取消勾选所选蓝图",
            lambda: self._set_selected_checked(enabled_rows, False),
        )
        menu.addSeparator()
        if any_checked:
            menu.addAction("仅保留所选（取消其他）", lambda: self._set_only_checked(enabled_rows))
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _set_selected_checked(self, rows: list[int], checked: bool) -> None:
        self._loading = True  # 批量设值期间屏蔽逐次 reconcile（统一收尾一次写入）
        try:
            for r in rows:
                if 0 <= r < len(self._checkboxes):
                    self._checkboxes[r].setChecked(checked)
        finally:
            self._loading = False
        self._reconcile()

    def _set_only_checked(self, rows: list[int]) -> None:
        keep = set(rows)
        self._loading = True
        try:
            for r, cb in enumerate(self._checkboxes):
                if cb.isEnabled():
                    cb.setChecked(r in keep)
        finally:
            self._loading = False
        self._reconcile()

    def _reconcile(self) -> None:
        """收集勾选集 → 全量替换写入绑定 → 刷新状态栏。"""
        plan_id = self._plan.get("id")
        checked: list[int] = []
        for i, cb in enumerate(self._checkboxes):
            if cb.isEnabled() and cb.isChecked() and i < len(self._options):
                checked.append(int(self._options[i]["id"]))
        # 一条产线一张蓝图：最多绑 need 张（多余截断，避免用户误以为多绑了）
        # 选项已按 BPO 优先排序，截断自然优先保留原图
        need = max(int(self.need_count), 1)
        truncated = len(checked) > need
        if truncated:
            checked = checked[:need]

        if plan_id:
            if not plan_execution.bind_blueprints(plan_id, checked):
                # 竞态：刚被其他计划占用 → 还原勾选并重载占用
                state = plan_execution.get_plan_binding_state(plan_id)
                valid = set(state["bound"])
                for i, cb in enumerate(self._checkboxes):
                    if i >= len(self._options):
                        continue
                    cb.blockSignals(True)
                    cb.setChecked(self._options[i]["id"] in valid)
                    cb.blockSignals(False)
                QMessageBox.warning(self, "绑定失败", "所选蓝图刚被其他活跃计划占用，请重新勾选")
                checked = [int(self._options[i]["id"]) for i, cb in enumerate(self._checkboxes) if cb.isChecked()]

        self.selected_blueprint_ids = checked
        self._refresh_status(truncated=truncated)

    def _refresh_status(self, *, truncated: bool = False) -> None:
        count = len(self.selected_blueprint_ids)
        need = max(int(self.need_count), 1)
        if truncated:
            self._status_label.setText(f"一条产线一张蓝图：已按需取前 {need} 张兑现（勾选 {count + 0} → 绑 {need} 张）")
            self._status_label.setStyleSheet(f"color: {theme.ACCENT_ORANGE}; font-weight: 600; font-size: 12px;")
        elif count >= need:
            self._status_label.setText(f"已选 {count} / 需 {need} 张 ✔")
            self._status_label.setStyleSheet(f"color: {theme.GREEN}; font-weight: 600; font-size: 12px;")
        else:
            self._status_label.setText(f"已选 {count} / 需 {need} 张 — 还差 {need - count} 张蓝图")
            self._status_label.setStyleSheet(f"color: {theme.ACCENT_RED}; font-weight: 600; font-size: 12px;")

    def _on_done(self) -> None:
        count = len(self.selected_blueprint_ids)
        if count < self.need_count:
            ret = QMessageBox.question(
                self,
                "绑定不足",
                f"当前仅绑定 {count}/{self.need_count} 条产线的蓝图，不足部分完成后无法启动。仍要关闭吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
        self.accept()

    def _on_npc_seller(self) -> None:
        from ui_pyside6.dialogs.npc_seller_dialog import NpcSellerDialog

        bp_id = self._blueprint_type_id if hasattr(self, "_blueprint_type_id") else None
        if bp_id is None:
            return
        name = self._plan.get("product_name", str(bp_id))
        dlg = NpcSellerDialog(bp_id, name, self)
        dlg.exec()

    # ── 主题 ──────────────────────────────────────────────────

    def _on_theme_changed(self) -> None:
        self.setStyleSheet(
            f"QDialog {{ background-color: {theme.BG_DARK}; color: {theme.TEXT_PRIMARY}; }}"
            f"QLabel {{ color: {theme.TEXT_PRIMARY}; background: transparent; font-size: 12px; }}"
            f"QTableWidget {{ background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f" border: 1px solid {theme.BORDER}; border-radius: 4px; gridline-color: {theme.BORDER}; }}"
            f"QHeaderView::section {{ background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};"
            f" border: 1px solid {theme.BORDER}; padding: 3px 6px; }}"
            f"QTableWidget::item:selected {{ background: {theme.PRIMARY}; color: {theme.TEXT_BRIGHT}; }}"
            f"QPushButton {{ padding: 4px 16px; border: 1px solid {theme.BORDER}; border-radius: 4px;"
            f" background: transparent; color: {theme.TEXT_PRIMARY}; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {theme.PRIMARY}; color: {theme.PRIMARY}; }}"
        )
        if hasattr(self, "_status_label"):
            self._refresh_status()
