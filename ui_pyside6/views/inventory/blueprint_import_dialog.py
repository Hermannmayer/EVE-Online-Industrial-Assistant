"""
仓库页面 — 蓝图粘贴导入预览对话框（BlueprintImportReviewDialog）

对齐材料导入流程：解析 → 预览（增量/全量模式 + 逐行勾选）→ 确认 → 应用 → 变动汇总。
"""

from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme


class BlueprintImportReviewDialog(QDialog):
    """蓝图粘贴导入预览 — 模式（增量/全量）+ 逐行勾选 + 增删预览"""

    _COL_CHECK = 0
    _COL_NAME = 1  # 蓝图名
    _COL_ATTR = 2  # 原图/拷贝 + ME/TE/流程
    _COL_CURRENT = 3  # 库中现有
    _COL_CLIP = 4  # 剪贴板
    _COL_DELTA = 5  # 本次增减（全量 = clip - current；增量 = clip）
    _COL_FINAL = 6  # 最终数量（全量模式可编辑）
    _HEADERS = ["", "蓝图", "属性", "现有", "剪贴板", "增减", "最终"]

    def __init__(
        self,
        diff_rows: list[dict],
        hangar_name: str,
        parent=None,
        *,
        default_mode: str = "full",
        filtered_note: int = 0,
        unresolved_note: int = 0,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"蓝图导入预览 → {hangar_name}")
        self.setMinimumSize(720, 400)
        self.resize(820, 480)
        # [{blueprint_type_id, is_bpo, me, te, clip_runs, existing_rows, qty, existing_qty, name}]
        self._diff_rows = diff_rows
        self._filtered_note = max(int(filtered_note or 0), 0)  # 剪贴板里被过滤的材料行数
        self._unresolved_note = max(int(unresolved_note or 0), 0)  # 结构完整但认不出蓝图的行数
        self._mode = default_mode
        self._updating = False
        # 切换导入模式会重建表格，勾选与手改的「最终」值必须先记住再恢复
        self._checked_state: dict[int, bool] = {}
        self._final_state: dict[int, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 工具栏：导入模式 + 全选/取消全选 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("导入模式:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("增量累加", "incremental")
        self._mode_combo.addItem("全量同步", "full")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self._mode_combo)
        self._mode_combo.setCurrentIndex(0 if default_mode == "incremental" else 1)

        toolbar.addStretch()

        self._select_all_btn = QPushButton("全选")
        self._select_all_btn.clicked.connect(self._on_select_all)
        toolbar.addWidget(self._select_all_btn)

        self._deselect_all_btn = QPushButton("取消全选")
        self._deselect_all_btn.clicked.connect(self._on_deselect_all)
        toolbar.addWidget(self._deselect_all_btn)

        layout.addLayout(toolbar)

        # ── 表格 ──
        self._table = QTableWidget(len(diff_rows), len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.verticalHeader().setVisible(False)
        self._table.itemChanged.connect(self._on_final_changed)
        layout.addWidget(self._table, 1)

        # ── 统计栏 ──
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.fs(11)}px;")
        layout.addWidget(self._summary_label)

        # ── 底部按钮 ──
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("确定导入")
        btn.accepted.connect(self._on_accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        self._populate_rows()

    # ── 填充 ──

    @staticmethod
    def _attr_text(row: dict) -> str:
        kind = "原图" if row["is_bpo"] else "拷贝"
        text = f"{kind}  ME{row['me']}  TE{row['te']}"
        values = BlueprintImportReviewDialog._runs_values(row)
        if not row["is_bpo"] and values:
            text += f"  流程{values[0]}" if len(values) == 1 else f"  流程{values[0]}~{values[-1]}"
        return text

    @staticmethod
    def _runs_values(row: dict) -> list[int]:
        """现有与剪贴板两侧出现过的流程数（去重升序）——原图无流程数概念。"""
        return sorted(
            {int(u) for u in row.get("clip_runs") or []}
            | {int(r.get("runs") or 0) for r in row.get("existing_rows") or []}
        )

    @staticmethod
    def _runs_differ(row: dict) -> bool:
        """张数没变但流程数变了（BPC 被消耗、原图归一）→ 仍需原地更新。"""
        old = sorted(
            int(r.get("runs") or 0)
            for r in row.get("existing_rows") or []
            for _ in range(max(int(r.get("quantity") or 1), 0))
        )
        return old != sorted(int(u) for u in row.get("clip_runs") or [])

    def _default_checked(self, row: dict, delta: int) -> bool:
        """默认勾选策略：新增/更新默认勾选，**纯删除默认不勾选**。

        删除是唯一不可逆的动作，且会经 delete_blueprint 静默解除活跃计划的绑定；
        若默认勾上，用户直接点确定就会把「剪贴板没覆盖到的蓝图」清掉。
        """
        if delta < 0:
            return False
        if delta > 0:
            return True
        return self._runs_differ(row)

    def _populate_rows(self):
        table = self._table
        self._updating = True
        try:
            table.setRowCount(len(self._diff_rows))
            for r, row in enumerate(self._diff_rows):
                current = int(row.get("existing_qty", 0))
                clip = int(row.get("qty", 0))
                if self._mode == "full":
                    delta = clip - current
                    final = clip
                else:
                    delta = clip
                    final = current + clip
                # 重建时恢复用户手改过的「最终」值（仅全量模式可编辑）
                if self._mode == "full" and self._final_state.get(r) is not None:
                    final = self._final_state[r]

                # 列0：勾选（新增/更新默认勾选；纯删除默认不勾选）
                cb = QCheckBox()
                cb.setChecked(self._checked_state.get(r, self._default_checked(row, delta)))
                cb_w = QWidget()
                cb_l = QHBoxLayout(cb_w)
                cb_l.setContentsMargins(0, 0, 0, 0)
                cb_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cb_l.addWidget(cb)
                table.setCellWidget(r, self._COL_CHECK, cb_w)

                # 列1：蓝图名
                name_item = QTableWidgetItem(row.get("name") or f"ID:{row['blueprint_type_id']}")
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                name_item.setData(Qt.ItemDataRole.UserRole, r)
                table.setItem(r, self._COL_NAME, name_item)

                # 列2：属性
                attr_item = QTableWidgetItem(self._attr_text(row))
                attr_item.setFlags(attr_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                attr_item.setForeground(QColor(theme.TEXT_SECONDARY))
                table.setItem(r, self._COL_ATTR, attr_item)

                # 列3：现有
                cur_item = QTableWidgetItem(f"{current}")
                cur_item.setFlags(cur_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                cur_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(r, self._COL_CURRENT, cur_item)

                # 列4：剪贴板
                clip_item = QTableWidgetItem(f"{clip}")
                clip_item.setFlags(clip_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                clip_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(r, self._COL_CLIP, clip_item)

                # 列5：增减
                delta_item = QTableWidgetItem(f"+{delta}" if delta > 0 else f"{delta}")
                delta_item.setFlags(delta_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                delta_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if delta > 0:
                    delta_item.setForeground(QColor(theme.ACCENT_GREEN))
                elif delta < 0:
                    delta_item.setForeground(QColor(theme.ACCENT_RED))
                else:
                    delta_item.setForeground(QColor(theme.TEXT_SECONDARY))
                table.setItem(r, self._COL_DELTA, delta_item)

                # 列6：最终数量（仅全量模式可编辑）
                final_item = QTableWidgetItem(f"{final}")
                final_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if self._mode != "full":
                    final_item.setFlags(final_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(r, self._COL_FINAL, final_item)

                cb.toggled.connect(lambda: self._update_summary())
        finally:
            self._updating = False

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setColumnWidth(self._COL_CHECK, 28)
        for col, min_w in [(self._COL_NAME, 200), (self._COL_ATTR, 150), (self._COL_FINAL, 60)]:
            if table.columnWidth(col) < min_w:
                table.setColumnWidth(col, min_w)

        self._update_summary()

    # ── 交互 ──

    def _on_mode_changed(self, idx: int):
        self._snapshot_state()
        self._mode = cast(str, self._mode_combo.itemData(idx))
        if not hasattr(self, "_table"):
            return
        self._populate_rows()

    def _snapshot_state(self):
        """重建表格前记住勾选与「最终」值 —— 切换模式不得把用户的取舍清零。

        旧行为是重建复选框为「有变化即勾选」，用户逐个取消的删除勾选会在
        切换模式的瞬间全部复活。
        """
        if not hasattr(self, "_table"):
            return
        self._checked_state = {}
        self._final_state = {}
        for r in range(self._table.rowCount()):
            w = self._table.cellWidget(r, self._COL_CHECK)
            cb = w.findChild(QCheckBox) if w else None
            if cb is not None:
                self._checked_state[r] = cb.isChecked()
            if self._mode == "full":
                val = self._final_value(r)
                if val is not None:
                    self._final_state[r] = val

    def _final_value(self, r: int) -> int | None:
        """「最终」列的合法取值；空/非数字/负数一律返回 None（调用方据此拦截）。"""
        item = self._table.item(r, self._COL_FINAL)
        if item is None:
            return None
        try:
            val = int(item.text().replace(",", "").strip())
        except ValueError:
            return None
        return val if val >= 0 else None

    def _checked_rows(self) -> list[int]:
        rows = []
        for r in range(self._table.rowCount()):
            w = self._table.cellWidget(r, self._COL_CHECK)
            cb = w.findChild(QCheckBox) if w else None
            if cb is not None and cb.isChecked():
                rows.append(r)
        return rows

    def _on_final_changed(self, item):
        """最终数量列被编辑（全量模式）：重算 delta 并刷新颜色；非法值标红拦下。"""
        if self._updating or item.column() != self._COL_FINAL:
            return
        r = item.row()
        val = self._final_value(r)
        if val is None:
            # 既不静默丢弃该行（旧行为会让用户以为已应用），也不放行非法值
            item.setForeground(QColor(theme.ACCENT_RED))
            return
        item.setForeground(QBrush())  # 空画刷 = 恢复默认（跟随主题 QSS，不硬编码颜色）
        cur_item = self._table.item(r, self._COL_CURRENT)
        current = int(cur_item.text()) if cur_item else 0
        delta = val - current
        delta_item = self._table.item(r, self._COL_DELTA)
        if delta_item:
            delta_item.setText(f"+{delta}" if delta > 0 else f"{delta}")
            if delta > 0:
                delta_item.setForeground(QColor(theme.ACCENT_GREEN))
            elif delta < 0:
                delta_item.setForeground(QColor(theme.ACCENT_RED))
            else:
                delta_item.setForeground(QColor(theme.TEXT_SECONDARY))
        self._update_summary()

    def _on_select_all(self):
        self._set_all_checked(True)

    def _on_deselect_all(self):
        self._set_all_checked(False)

    def _set_all_checked(self, checked: bool):
        for r in range(self._table.rowCount()):
            w = self._table.cellWidget(r, self._COL_CHECK)
            if w:
                cb = w.findChild(QCheckBox)
                if cb:
                    cb.setChecked(checked)

    def _update_summary(self):
        checked = 0
        total_delta = 0
        for r in self._checked_rows():
            checked += 1
            delta_item = self._table.item(r, self._COL_DELTA)
            if delta_item:
                try:
                    total_delta += int(delta_item.text().replace(",", "").replace("+", ""))
                except ValueError:
                    pass
        text = f"已勾选 {checked} 项 / 总计 {self._table.rowCount()} 项 / 蓝图增减 {total_delta:+d}"
        if self._mode == "full":
            text += "  ｜ 全量同步以剪贴板为准：未出现在剪贴板中的蓝图会被删除，删除项默认不勾选"
        if self._filtered_note:
            text = f"[已过滤 {self._filtered_note} 行材料] {text}"
        if self._unresolved_note:
            text = f"[未识别 {self._unresolved_note} 行蓝图] {text}"
        self._summary_label.setText(text)

    def _on_accept(self):
        checked_rows = self._checked_rows()
        if not checked_rows:
            QMessageBox.warning(self, "提示", "没有勾选的蓝图，无法导入")
            return
        if self._mode == "full":
            invalid = [r for r in checked_rows if self._final_value(r) is None]
            if invalid:
                QMessageBox.warning(
                    self,
                    "提示",
                    f"有 {len(invalid)} 行的「最终」数量不是合法的非负整数，请修正后再导入",
                )
                return
            deletions = [
                r
                for r in checked_rows
                if int(self._diff_rows[r].get("existing_qty", 0)) > int(self._final_value(r) or 0)
            ]
            if deletions and not self._confirm_deletions(deletions):
                return
        self.accept()

    def _confirm_deletions(self, rows: list[int]) -> bool:
        """全量同步的删除二次确认 —— 删行不可逆，且会解除活跃计划对该蓝图的绑定。"""
        lines = []
        total = 0
        for r in rows:
            row = self._diff_rows[r]
            gone = int(row.get("existing_qty", 0)) - int(self._final_value(r) or 0)
            total += gone
            name = row.get("name") or f"ID:{row['blueprint_type_id']}"
            lines.append(f"  {name}（{self._attr_text(row)}）: 删除 {gone} 张")
        detail = "\n".join(lines[:10])
        if len(lines) > 10:
            detail += f"\n  …等共 {len(lines)} 项"
        ret = QMessageBox.warning(
            self,
            "确认删除蓝图",
            f"以下 {total} 张蓝图不在剪贴板中，全量同步将把它们从本机库删除：\n\n{detail}\n\n"
            "删除不可撤销，且会同时解除相关生产计划对该蓝图的绑定。确认删除？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return ret == QMessageBox.StandardButton.Yes

    def mode(self) -> str:
        """当前导入模式："incremental" 增量累加 | "full" 全量同步"""
        return self._mode

    def get_applied_rows(self) -> list[dict]:
        """返回勾选行的最终应用参数 [{diff_row..., target_qty}]。

        全量模式：target_qty = 最终数量（增删差额应用）。
        增量模式：target_qty = 现有 + 剪贴板（只增不减）。
        """
        result = []
        for r in self._checked_rows():
            diff = dict(self._diff_rows[r])
            if self._mode == "full":
                final = self._final_value(r)
                if final is None:  # 非法值已在 _on_accept 拦下，这里兜底为「不动」
                    continue
            else:
                final = int(diff.get("existing_qty", 0)) + int(diff.get("qty", 0))
            result.append({**diff, "target_qty": final})
        return result

    def showEvent(self, event):
        """显示前重新应用主题样式"""
        super().showEvent(event)
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.fs(11)}px;")


# ════════════════════════════════════════════════════
#  Dialog: 蓝图导入完成变动汇总
# ════════════════════════════════════════════════════


class BlueprintImportChangeDialog(QDialog):
    """蓝图导入完成后的变动汇总 — 蓝图名/属性 数量前→后。

    增量行绿色、减量行红色；顶部汇总含新增/删除条数。
    """

    _HEADERS = ["蓝图", "属性", "数量（前 → 后）"]

    def __init__(self, changes: list[dict], added: int, removed: int, hangar_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"蓝图导入完成 — {hangar_name}")
        self.setMinimumSize(540, 380)
        self.resize(640, 460)
        self._changes = changes

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._summary_label = QLabel(self._build_summary(changes, added, removed))
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.fs(11)}px;")
        layout.addWidget(self._summary_label)

        self._table = QTableWidget(len(changes), 3)
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        for row, ch in enumerate(changes):
            name_item = QTableWidgetItem(ch["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, name_item)

            attr_item = QTableWidgetItem(ch.get("attr", ""))
            attr_item.setFlags(attr_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            attr_item.setForeground(QColor(theme.TEXT_SECONDARY))
            self._table.setItem(row, 1, attr_item)

            qty_item = QTableWidgetItem(f"{ch['qty_before']} → {ch['qty_after']}")
            qty_item.setFlags(qty_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if ch["qty_delta"] > 0:
                qty_item.setForeground(QColor(theme.ACCENT_GREEN))
            elif ch["qty_delta"] < 0:
                qty_item.setForeground(QColor(theme.ACCENT_RED))
            self._table.setItem(row, 2, qty_item)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(0, 200)
        self._table.setColumnWidth(1, 150)
        self._table.setColumnWidth(2, 100)
        layout.addWidget(self._table, 1)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        theme.add_theme_listener(self._on_theme_changed)

    @staticmethod
    def _build_summary(changes: list[dict], added: int, removed: int) -> str:
        """汇总文案：共 N 项变化（增加/减少）+ 新增/删除条数。"""
        if not changes:
            return f"新增 {added} 条，删除 {removed} 条，无属性变化"
        inc = sum(1 for c in changes if c["qty_delta"] > 0)
        dec = sum(1 for c in changes if c["qty_delta"] < 0)
        parts = [f"共 {len(changes)} 项变化"]
        if inc:
            parts.append(f"增加 {inc}")
        if dec:
            parts.append(f"减少 {dec}")
        if added:
            parts.append(f"新增 {added} 张")
        if removed:
            parts.append(f"删除 {removed} 张")
        return "，".join(parts)

    def _on_theme_changed(self):
        """主题切换时重设增量/减量前景色（跟随主题）"""
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.fs(11)}px;")
        for row, ch in enumerate(self._changes):
            qty_item = self._table.item(row, 2)
            if qty_item is None:
                continue
            if ch["qty_delta"] > 0:
                qty_item.setForeground(QColor(theme.ACCENT_GREEN))
            elif ch["qty_delta"] < 0:
                qty_item.setForeground(QColor(theme.ACCENT_RED))
