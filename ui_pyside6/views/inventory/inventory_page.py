"""
仓库页面 — 主容器（Tab 切换 + 机库选择）
"""

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from services.inventory_manager import (
    create_hangar,
    delete_hangar,
    get_hangars,
    init_db,
    rename_hangar,
)

from .blueprint_tab import BlueprintTab
from .hangar_tab import HangarTab


class InventoryPage(QWidget):
    """仓库管理 — 机库管理 + 蓝图管理"""

    def __init__(self, main_window):
        super().__init__()
        self._main = main_window
        init_db()
        self.setObjectName("inventory_page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 0)
        layout.setSpacing(6)

        # ── 共享机库选择器 ──
        hangar_bar = QHBoxLayout()
        hangar_bar.addWidget(QLabel("机库:"))
        self._hangar_combo = QComboBox()
        self._hangar_combo.setMinimumWidth(140)
        hangar_bar.addWidget(self._hangar_combo)

        self._new_h_btn = QPushButton("+新建")
        self._new_h_btn.clicked.connect(self._on_new_hangar)
        hangar_bar.addWidget(self._new_h_btn)

        self._rename_h_btn = QPushButton("重命名")
        self._rename_h_btn.clicked.connect(self._on_rename_hangar)
        hangar_bar.addWidget(self._rename_h_btn)

        self._del_h_btn = QPushButton("删除")
        self._del_h_btn.clicked.connect(self._on_del_hangar)
        hangar_bar.addWidget(self._del_h_btn)

        hangar_bar.addStretch()
        layout.addLayout(hangar_bar)

        self._current_hangar_id: int | None = None
        self._load_hangars()

        self._tabs = QTabWidget()
        self._tabs.setObjectName("storage_tabs")

        self._hangar_tab = HangarTab(self)
        self._blueprint_tab = BlueprintTab(self)

        self._tabs.addTab(self._hangar_tab, "机库管理")
        self._tabs.addTab(self._blueprint_tab, "蓝图管理")

        layout.addWidget(self._tabs)

        self._hangar_combo.currentIndexChanged.connect(self._on_hangar_changed)

        import ui_pyside6.theme as theme

        theme.add_theme_listener(self._on_theme_changed)

    def _on_theme_changed(self):
        """主题切换时重新应用内联样式表"""
        self._hangar_tab._on_theme_changed()
        self._blueprint_tab._on_theme_changed()

    def hangar_id(self) -> int | None:
        return self._current_hangar_id

    def _load_hangars(self):
        hs = get_hangars()
        self._hangar_combo.blockSignals(True)
        self._hangar_combo.clear()
        for h in hs:
            self._hangar_combo.addItem(h["name"], h["id"])
        self._hangar_combo.blockSignals(False)
        if hs:
            self._current_hangar_id = hs[0]["id"]
            self._hangar_combo.setCurrentIndex(0)

    def _on_hangar_changed(self, idx):
        if idx < 0:
            return
        self._current_hangar_id = self._hangar_combo.itemData(idx)
        self._hangar_tab._refresh()
        self._blueprint_tab._load_blueprints()

    def _on_new_hangar(self):
        name, ok = QInputDialog.getText(self, "新建机库", "机库名:")
        if ok and name.strip():
            rid = create_hangar(name.strip())
            if rid == -1:
                QMessageBox.warning(self, "提示", "机库名已存在")
            else:
                self._load_hangars()
                for i in range(self._hangar_combo.count()):
                    if self._hangar_combo.itemData(i) == rid:
                        self._hangar_combo.setCurrentIndex(i)
                        break

    def _on_rename_hangar(self):
        if not self._current_hangar_id:
            return
        old = self._hangar_combo.currentText()
        name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=old)
        if ok and name.strip() and name != old:
            rename_hangar(self._current_hangar_id, name.strip())
            self._load_hangars()

    def _on_del_hangar(self):
        if not self._current_hangar_id:
            return
        name = self._hangar_combo.currentText()
        reply = QMessageBox.question(
            self,
            "确认",
            f"删除机库「{name}」及其所有物品？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_hangar(self._current_hangar_id)
            self._load_hangars()

    def refresh_display(self):
        self._hangar_tab._refresh()

    def save_state(self) -> dict:
        data = {"tab_index": self._tabs.currentIndex()}
        if self._hangar_combo.count() > 0:
            data["hangar_index"] = self._hangar_combo.currentIndex()
        return data

    def restore_state(self, data: dict) -> None:
        if not data:
            return
        tab_index = data.get("tab_index", 0)
        if 0 <= tab_index < self._tabs.count():
            self._tabs.setCurrentIndex(tab_index)
        hangar_index = data.get("hangar_index")
        if hangar_index is not None and 0 <= hangar_index < self._hangar_combo.count():
            self._hangar_combo.setCurrentIndex(hangar_index)
