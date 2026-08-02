"""
仓库页面 — 蓝图粘贴导入预览对话框（BlueprintImportReviewDialog）

对齐材料导入流程：解析 → 预览（增量/全量模式 + 逐行勾选）→ 确认 → 应用 → 变动汇总。
"""

from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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
    ):
        super().__init__(parent)
        self.setWindowTitle(f"蓝图导入预览 → {hangar_name}")
        self.setMinimumSize(720, 400)
        self.resize(820, 480)
        self._diff_rows = diff_rows  # [{blueprint_type_id, is_bpo, me, te, runs, qty, existing_qty, row_ids, name}]
        self._mode = default_mode
        self._updating = False

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
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
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
        return f"{kind}  ME{row['me']}  TE{row['te']}  流程{row['runs']}"

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

                # 列0：勾选（有变化的行默认勾选；无变化不勾选）
                cb = QCheckBox()
                cb.setChecked(delta != 0)
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
        self._mode = cast(str, self._mode_combo.itemData(idx))
        if not hasattr(self, "_table"):
            return
        self._populate_rows()

    def _on_final_changed(self, item):
        """最终数量列被编辑（全量模式）：重算 delta 并刷新颜色。"""
        if self._updating or item.column() != self._COL_FINAL:
            return
        r = item.row()
        try:
            final = int(item.text().replace(",", "").replace(" ", ""))
        except ValueError:
            return
        cur_item = self._table.item(r, self._COL_CURRENT)
        current = int(cur_item.text()) if cur_item else 0
        delta = final - current
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
        for r in range(self._table.rowCount()):
            w = self._table.cellWidget(r, self._COL_CHECK)
            if not w:
                continue
            cb = w.findChild(QCheckBox)
            if not cb or not cb.isChecked():
                continue
            checked += 1
            delta_item = self._table.item(r, self._COL_DELTA)
            if delta_item:
                try:
                    total_delta += int(delta_item.text().replace(",", "").replace("+", ""))
                except ValueError:
                    pass
        self._summary_label.setText(
            f"已勾选 {checked} 项 / 总计 {self._table.rowCount()} 项 / 蓝图增减 {total_delta:+d}"
        )

    def _on_accept(self):
        has_checked = False
        for r in range(self._table.rowCount()):
            w = self._table.cellWidget(r, self._COL_CHECK)
            if not w:
                continue
            cb = w.findChild(QCheckBox)
            if cb and cb.isChecked():
                has_checked = True
                break
        if not has_checked:
            QMessageBox.warning(self, "提示", "没有勾选的蓝图，无法导入")
            return
        self.accept()

    def mode(self) -> str:
        """当前导入模式："incremental" 增量累加 | "full" 全量同步"""
        return self._mode

    def get_applied_rows(self) -> list[dict]:
        """返回勾选行的最终应用参数 [{diff_row..., target_qty}]。

        全量模式：target_qty = 最终数量（增删差额应用）。
        增量模式：target_qty = 现有 + 剪贴板（只增不减）。
        """
        result = []
        for r in range(self._table.rowCount()):
            w = self._table.cellWidget(r, self._COL_CHECK)
            if not w:
                continue
            cb = w.findChild(QCheckBox)
            if not cb or not cb.isChecked():
                continue
            diff = dict(self._diff_rows[r])
            final_item = self._table.item(r, self._COL_FINAL)
            try:
                final = int(final_item.text().replace(",", "")) if final_item else 0
            except ValueError:
                continue
            result.append({**diff, "target_qty": final})
        return result

    def showEvent(self, event):
        """显示前重新应用主题样式"""
        super().showEvent(event)
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")


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
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
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
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        for row, ch in enumerate(self._changes):
            qty_item = self._table.item(row, 2)
            if qty_item is None:
                continue
            if ch["qty_delta"] > 0:
                qty_item.setForeground(QColor(theme.ACCENT_GREEN))
            elif ch["qty_delta"] < 0:
                qty_item.setForeground(QColor(theme.ACCENT_RED))
