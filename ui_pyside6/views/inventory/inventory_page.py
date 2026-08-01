"""
仓库页面 — 主容器（Tab 切换 + 机库选择）

机库的增删改（新建/重命名/删除/设置星系）统一收拢到底部「机库设置」对话框，
本页仅保留机库选择器用于切换查看内容。
"""

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.container import get_container
from services.inventory_manager import (
    get_hangars,
    init_db,
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
        # 机库所在星系名映射（用于下拉显示）
        sys_names = self._system_names([h["solar_system_id"] for h in hs if h.get("solar_system_id")])
        self._hangar_combo.blockSignals(True)
        self._hangar_combo.clear()
        for h in hs:
            label = h["name"]
            sid = h.get("solar_system_id")
            if sid and sid in sys_names:
                label = f"{label} ({sys_names[sid]})"
            self._hangar_combo.addItem(label, h["id"])
        self._hangar_combo.blockSignals(False)
        if hs:
            self._current_hangar_id = hs[0]["id"]
            self._hangar_combo.setCurrentIndex(0)

    def _system_names(self, solar_system_ids: list[int]) -> dict[int, str]:
        """批量查询星系名 {solar_system_id: 名称}；星系数据未加载时返回空。"""
        if not solar_system_ids:
            return {}
        try:
            with get_container().db.connect("ref") as conn:
                placeholders = ",".join("?" * len(solar_system_ids))
                rows = conn.execute(
                    f"SELECT solar_system_id, solar_system_name FROM solar_system"
                    f" WHERE solar_system_id IN ({placeholders})",
                    solar_system_ids,
                ).fetchall()
                return {int(r[0]): r[1] for r in rows}
        except Exception:
            return {}

    def _on_hangar_changed(self, idx):
        if idx < 0:
            return
        self._current_hangar_id = self._hangar_combo.itemData(idx)
        self._hangar_tab._refresh()
        self._blueprint_tab._load_blueprints()

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
