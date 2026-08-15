"""
批量对比对话框 — CompareDialog 主 UI 容器
"""

import csv

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUBS
from ui_pyside6.views.char_settings_view import get_character_list
from ui_pyside6.views.compare.compare_chart import CompareWorker, item_name, search_items
from ui_pyside6.views.compare.compare_models import CompareTableModel as _CompareTableModel
from ui_pyside6.views.compare.compare_models import (
    _format_isk,
    build_clear_btn_stylesheet,
    build_combo_stylesheet,
    build_compare_btn_stylesheet,
    build_dialog_stylesheet,
    build_export_btn_stylesheet,
    build_item_list_stylesheet,
    build_label_stylesheet,
    build_primary_btn_stylesheet,
    build_progress_stylesheet,
    build_search_input_stylesheet,
    build_spin_stylesheet,
    build_status_stylesheet,
    build_table_stylesheet,
)


class CompareDialog(QDialog):
    """批量对比模式 — 多物品同屏对比利润和评分"""

    def __init__(self, initial_items: list[dict] | None = None, parent=None):
        """
        initial_items: 预选物品列表 [{"type_id": int, "name": str}, ...]
        """
        super().__init__(parent)
        self.setWindowTitle("批量对比")
        self.setMinimumSize(900, 560)
        self.resize(1000, 620)

        self._selected_items: list[dict] = []
        self._search_results: list[dict] = []
        self._worker: CompareWorker | None = None
        self._results: list[dict] = []

        self._build_ui()

        if initial_items:
            for item in initial_items:
                if not any(it["type_id"] == item["type_id"] for it in self._selected_items):
                    name = item.get("name") or item_name(item["type_id"])
                    self._selected_items.append({"type_id": item["type_id"], "name": name})
            self._refresh_item_list()

        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.requestInterruption()
            self._worker.wait(2000)
        super().closeEvent(event)

    def _on_theme_changed(self):
        """主题切换时重新应用样式"""
        self.setStyleSheet(build_dialog_stylesheet())
        self._search_input.setStyleSheet(build_search_input_stylesheet())
        self._add_btn.setStyleSheet(build_primary_btn_stylesheet())
        self._item_list.setStyleSheet(build_item_list_stylesheet())
        self._mode_combo.setStyleSheet(build_combo_stylesheet())
        self._hub_combo.setStyleSheet(build_combo_stylesheet())
        self._char_combo.setStyleSheet(build_combo_stylesheet())
        self._me_spin.setStyleSheet(build_spin_stylesheet())
        self._te_spin.setStyleSheet(build_spin_stylesheet())
        self._tax_spin.setStyleSheet(build_spin_stylesheet())
        self._compare_btn.setStyleSheet(build_compare_btn_stylesheet())
        self._export_btn.setStyleSheet(build_export_btn_stylesheet())
        self._status.setStyleSheet(build_status_stylesheet())
        self._progress.setStyleSheet(build_progress_stylesheet())
        for lbl in [
            self._lbl_hub,
            self._lbl_mode,
            self._lbl_char,
            self._lbl_me,
            self._lbl_te,
            self._lbl_tax,
            self._lbl_items,
        ]:
            lbl.setStyleSheet(build_label_stylesheet())
        self._clear_btn.setStyleSheet(build_clear_btn_stylesheet())
        self._table.setStyleSheet(build_table_stylesheet())

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ── 搜索添加区 ──
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索物品名称或ID...")
        self._search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_input, 1)

        self._add_btn = QPushButton("添加")
        self._add_btn.clicked.connect(self._on_add_first_match)
        search_row.addWidget(self._add_btn)
        main_layout.addLayout(search_row)

        # ── 已添加物品列表 ──
        items_header = QHBoxLayout()
        self._lbl_items = QLabel("已添加:")
        items_header.addWidget(self._lbl_items)
        self._clear_btn = QPushButton("清空")
        self._clear_btn.clicked.connect(self._on_clear_items)
        items_header.addWidget(self._clear_btn)
        items_header.addStretch()
        main_layout.addLayout(items_header)

        self._item_list = QListWidget()
        self._item_list.setMaximumHeight(90)
        self._item_list.model().rowsInserted.connect(self._scroll_to_bottom)
        main_layout.addWidget(self._item_list)

        # ── 参数设置 ──
        settings_row = QHBoxLayout()
        settings_row.setSpacing(6)

        self._lbl_mode = QLabel("类型:")
        settings_row.addWidget(self._lbl_mode)
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["制造评分", "贸易评分", "反应评分"])
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        settings_row.addWidget(self._mode_combo)

        self._lbl_hub = QLabel("区域:")
        settings_row.addWidget(self._lbl_hub)
        self._hub_combo = QComboBox()
        self._hub_combo.addItems(TRADE_HUBS)
        settings_row.addWidget(self._hub_combo)

        self._lbl_char = QLabel("角色:")
        settings_row.addWidget(self._lbl_char)
        self._char_combo = QComboBox()
        chars = get_character_list()
        self._char_combo.addItems(chars if chars else ["main"])
        settings_row.addWidget(self._char_combo)

        self._lbl_me = QLabel("ME:")
        settings_row.addWidget(self._lbl_me)
        self._me_spin = QSpinBox()
        self._me_spin.setRange(0, 10)
        self._me_spin.setValue(0)
        settings_row.addWidget(self._me_spin)

        self._lbl_te = QLabel("TE:")
        settings_row.addWidget(self._lbl_te)
        self._te_spin = QSpinBox()
        self._te_spin.setRange(0, 20)
        self._te_spin.setValue(0)
        settings_row.addWidget(self._te_spin)

        self._lbl_tax = QLabel("税%:")
        settings_row.addWidget(self._lbl_tax)
        self._tax_spin = QDoubleSpinBox()
        self._tax_spin.setRange(0, 100)
        self._tax_spin.setSuffix("%")
        self._tax_spin.setValue(0)
        settings_row.addWidget(self._tax_spin)

        settings_row.addStretch()

        self._compare_btn = QPushButton("开始对比")
        self._compare_btn.clicked.connect(self._on_compare)
        settings_row.addWidget(self._compare_btn)

        self._export_btn = QPushButton("导出CSV")
        self._export_btn.clicked.connect(self._on_export_csv)
        self._export_btn.setEnabled(False)
        settings_row.addWidget(self._export_btn)

        main_layout.addLayout(settings_row)

        # ── 进度条 ──
        self._progress = QProgressBar()
        self._progress.setFixedHeight(3)
        self._progress.setVisible(False)
        main_layout.addWidget(self._progress)

        # ── 对比表格 ──
        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setDefaultSectionSize(26)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(True)
        self._model = _CompareTableModel()
        self._table.setModel(self._model)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        main_layout.addWidget(self._table, 1)

        # ── 状态栏 ──
        self._status = QLabel("就绪")
        main_layout.addWidget(self._status)

    def _scroll_to_bottom(self):
        self._item_list.scrollToBottom()

    # ── 搜索与添加 ──

    def _on_search(self):
        q = self._search_input.text().strip()
        if not q:
            return
        self._search_results = search_items(q)
        if self._search_results:
            first = self._search_results[0]
            name = first.get("zh_name") or first.get("en_name") or str(first["type_id"])
            self._status.setText(f"找到 {len(self._search_results)} 条，首个: {name}")
        else:
            self._status.setText("未找到匹配物品")

    def _on_add_first_match(self):
        """添加搜索结果中的第一个匹配项"""
        q = self._search_input.text().strip()
        if not q:
            return
        results = search_items(q)
        if not results:
            self._status.setText("未找到匹配物品")
            return
        first = results[0]
        self._add_item(first["type_id"], first.get("zh_name") or first.get("en_name") or str(first["type_id"]))
        self._search_input.clear()
        self._search_results = []

    def _add_item(self, type_id: int, name: str):
        """添加物品到对比列表"""
        if any(it["type_id"] == type_id for it in self._selected_items):
            self._status.setText(f"已添加: {name}")
            return
        self._selected_items.append({"type_id": type_id, "name": name})
        self._refresh_item_list()
        self._status.setText(f"已添加: {name} (共 {len(self._selected_items)} 项)")

    def _refresh_item_list(self):
        """刷新已添加物品列表"""
        self._item_list.clear()
        for i, item in enumerate(self._selected_items):
            name = item.get("name") or item_name(item["type_id"])
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(4, 2, 4, 2)
            layout.setSpacing(4)

            lbl = QLabel(f"{i + 1}. {name}")
            lbl.setStyleSheet(f"color:{theme.TEXT_PRIMARY};font-size:11px;")
            layout.addWidget(lbl, 1)

            del_btn = QPushButton("✕")
            del_btn.setFixedSize(18, 18)
            del_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{theme.ACCENT_RED};"
                f"border:none;border-radius:9px;font-size:10px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{theme.ACCENT_RED};color:{theme.TEXT_ON_PRIMARY};}}"
            )
            del_btn.clicked.connect(lambda checked, idx=i: self._remove_item(idx))
            layout.addWidget(del_btn)

            list_item = QListWidgetItem()
            list_item.setSizeHint(widget.sizeHint())
            self._item_list.addItem(list_item)
            self._item_list.setItemWidget(list_item, widget)

    def _remove_item(self, index: int):
        """删除指定索引的物品"""
        if 0 <= index < len(self._selected_items):
            removed = self._selected_items.pop(index)
            self._refresh_item_list()
            self._status.setText(f"已移除: {removed.get('name', '')} (共 {len(self._selected_items)} 项)")

    def _on_clear_items(self):
        """清空所有物品"""
        self._selected_items.clear()
        self._refresh_item_list()
        self._results.clear()
        self._model.set_rows([])
        self._export_btn.setEnabled(False)
        self._status.setText("已清空")

    # ── 模式切换 ──

    def _on_mode_changed(self, index: int):
        """模式切换时更新列"""
        mode = ["mfg", "trade", "reaction"][index]
        self._model.set_mode(mode)
        is_mfg = mode in ("mfg", "reaction")
        self._me_spin.setVisible(is_mfg)
        self._te_spin.setVisible(is_mfg)
        self._lbl_me.setVisible(is_mfg)
        self._lbl_te.setVisible(is_mfg)
        if self._results:
            self._on_compare()

    # ── 对比计算 ──

    def _on_compare(self):
        """开始对比计算"""
        if not self._selected_items:
            self._status.setText("请先添加物品")
            return
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)

        mode_index = self._mode_combo.currentIndex()
        mode = ["mfg", "trade", "reaction"][mode_index]
        mode_names = ["制造评分", "贸易评分", "反应评分"]

        cfg = {
            "hub": self._hub_combo.currentText(),
            "char": self._char_combo.currentText(),
            "tax": self._tax_spin.value(),
            "me": self._me_spin.value(),
            "te": self._te_spin.value(),
            "bh": self._hub_combo.currentText(),
            "sh": self._hub_combo.currentText(),
            "bs": "sell",
            "ss": "sell",
        }

        self._compare_btn.setEnabled(False)
        self._export_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(self._selected_items))
        self._progress.setValue(0)
        self._status.setText(f"正在计算 {mode_names[mode_index]}...")

        self._worker = CompareWorker(self._selected_items, mode, cfg, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, current: int, total: int):
        self._progress.setValue(current)
        self._status.setText(f"计算中 {current}/{total}...")

    def _on_done(self, results: list[dict]):
        self._results = results
        self._model.set_rows(results)
        self._progress.setVisible(False)
        self._compare_btn.setEnabled(True)
        self._export_btn.setEnabled(True)

        valid = [r for r in results if not r.get("status")]
        if valid:
            mode = ["mfg", "trade", "reaction"][self._mode_combo.currentIndex()]
            if mode == "trade":
                best = max(valid, key=lambda x: x.get("gross_profit", 0))
                best_profit = best.get("gross_profit", 0)
            else:
                best = max(valid, key=lambda x: x.get("profit", 0))
                best_profit = best.get("profit", 0)
            self._status.setText(
                f"完成 {len(results)} 项 | 有效 {len(valid)} 项 | "
                f"最佳: {best.get('name', '')} ({_format_isk(best_profit)} ISK)"
            )
        else:
            self._status.setText(f"完成 {len(results)} 项 | 无有效结果")

    # ── 右键菜单 ──

    def _show_context_menu(self, pos):
        """表格右键菜单"""
        index = self._table.indexAt(pos)
        if not index.isValid():
            return

        menu = theme.themed_menu(self._table)
        row_data = self._model.data(index, Qt.ItemDataRole.UserRole)

        copy_row_action = menu.addAction("复制行数据")
        copy_row_action.triggered.connect(lambda: self._copy_row(row_data))

        copy_all_action = menu.addAction("复制全部 (CSV)")
        copy_all_action.triggered.connect(self._copy_all_as_csv)

        menu.addSeparator()

        if row_data and row_data.get("type_id"):
            tid = row_data["type_id"]
            view_action = menu.addAction(f"查看物品 {row_data.get('name', tid)}")
            view_action.triggered.connect(lambda checked, t=tid: self._open_item_detail(t))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _copy_row(self, row_data: dict):
        """将选中行数据复制为制表符分隔文本"""
        if not row_data:
            return
        parts = []
        for _, _, key in self._model._cols:
            val = row_data.get(key)
            parts.append(str(val) if val is not None else "")
        QApplication.clipboard().setText("\t".join(parts))
        self._status.setText("已复制行数据到剪贴板")

    def _copy_all_as_csv(self):
        """将整个对比结果复制为 CSV"""
        data = self._model.get_export_data()
        lines = [",".join(str(cell) for cell in row) for row in data]
        QApplication.clipboard().setText("\n".join(lines))
        self._status.setText(f"已复制 {len(data) - 1} 行数据到剪贴板")

    def _open_item_detail(self, type_id: int):
        """打开该物品的评分弹窗"""
        mode_index = self._mode_combo.currentIndex()
        mode = ["mfg", "trade", "reaction"][mode_index]
        cfg = {
            "hub": self._hub_combo.currentText(),
            "char": self._char_combo.currentText(),
            "tax": self._tax_spin.value(),
        }
        dlg: QDialog
        if mode == "trade":
            from ui_pyside6.views.score_dialogs import TradeDlg

            dlg = TradeDlg(cfg, parent=self)
            dlg.setWindowTitle(f"贸易评分 — {item_name(type_id)}")
            dlg.exec()
        else:
            from ui_pyside6.views.score_dialogs import MfgDlg

            dlg = MfgDlg(cfg, parent=self)
            dlg.setWindowTitle(f"制造评分 — {item_name(type_id)}")
            dlg.exec()

    # ── 导出 ──

    def _on_export_csv(self):
        """导出为 CSV 文件"""
        if not self._results:
            self._status.setText("无数据可导出")
            return
        try:
            from PySide6.QtWidgets import QFileDialog

            path, _ = QFileDialog.getSaveFileName(
                self, "导出对比结果", "compare_result.csv", "CSV Files (*.csv);;All Files (*)"
            )
            if not path:
                return

            data = self._model.get_export_data()
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                for row in data:
                    writer.writerow(row)

            self._status.setText(f"已导出: {path}")
        except Exception as e:
            self._status.setText(f"导出失败: {e}")


def open_compare_dialog(parent=None, initial_items: list[dict] | None = None):
    """打开批量对比对话框"""
    dlg = CompareDialog(initial_items=initial_items, parent=parent)
    dlg.show()
    return dlg
