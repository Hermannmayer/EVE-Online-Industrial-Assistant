"""主窗口导航与页面注册 Mixin。"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.logger import log

NAV_TREE = [
    ("__section__", "⚡ 核心功能"),
    ("estimate", "估价", "💰"),
    ("query", "物品查询", "🔍"),
    ("industry", "工业制造", "🏭"),
    ("trade", "市场贸易", "📊"),
    ("watchlist", "价格监控", "🔔"),
    ("contract", "合同市场", "📄"),
    ("storage", "仓库管理", "📦"),
]


class MainWindowNavMixin:
    """主窗口左侧导航与页面注册。"""

    def _build_nav_tree(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("nav_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(0)

        tree = QTreeWidget()
        tree.setObjectName("nav_tree")
        tree.setHeaderHidden(True)
        tree.setIndentation(0)
        tree.setRootIsDecorated(False)

        self._nav_tree = tree
        self._nav_items: list[QTreeWidgetItem] = []

        header = QTreeWidgetItem(["EVE 商人助手"])
        header.setFlags(Qt.ItemFlag.NoItemFlags)
        font = QFont()
        font.setBold(True)
        font.setPointSize(12)
        header.setFont(0, font)
        header.setForeground(0, QColor(theme.PRIMARY))
        header.setSizeHint(0, QSize(header.sizeHint(0).width(), 32))
        tree.addTopLevelItem(header)

        spacer = QTreeWidgetItem([""])
        spacer.setFlags(Qt.ItemFlag.NoItemFlags)
        spacer.setSizeHint(0, QSize(spacer.sizeHint(0).width(), 8))
        tree.addTopLevelItem(spacer)

        for entry in NAV_TREE:
            if entry[0] == "__section__":
                sec = QTreeWidgetItem([entry[1]])
                sec.setFlags(Qt.ItemFlag.NoItemFlags)
                sec.setForeground(0, QColor(theme.TEXT_SECONDARY))
                f = QFont()
                f.setBold(True)
                f.setPointSize(10)
                sec.setFont(0, f)
                sec.setSizeHint(0, QSize(sec.sizeHint(0).width(), 24))
                tree.addTopLevelItem(sec)
            else:
                key, label, icon = entry[0], entry[1], entry[2]
                item = QTreeWidgetItem([f" {icon}  {label}"])
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                item.setSizeHint(0, QSize(item.sizeHint(0).width(), 28))
                self._nav_items.append(item)
                tree.addTopLevelItem(item)

        tree.currentItemChanged.connect(self._on_nav_changed)
        layout.addWidget(tree)

        layout.addStretch()

        bottom_btn_layout = QHBoxLayout()
        bottom_btn_layout.setContentsMargins(4, 4, 4, 4)
        bottom_btn_layout.setSpacing(6)

        self._hangar_settings_btn = QPushButton()
        self._hangar_settings_btn.setObjectName("hangar_settings_btn")
        self._hangar_settings_btn.setToolTip("机库设置：所在星系 / 设施类型 / 改装件 / 设施税 / 默认机库")
        self._hangar_settings_btn.setFixedSize(36, 36)
        self._hangar_settings_btn.setIcon(self._create_hangar_icon())
        self._hangar_settings_btn.setIconSize(QSize(20, 20))
        self._hangar_settings_btn.clicked.connect(self._show_hangar_settings)

        self._char_settings_btn = QPushButton()
        self._char_settings_btn.setObjectName("char_settings_btn")
        self._char_settings_btn.setToolTip("人物设置")
        self._char_settings_btn.setFixedSize(36, 36)
        self._char_settings_btn.setIcon(self._create_person_icon())
        self._char_settings_btn.setIconSize(QSize(20, 20))
        self._char_settings_btn.clicked.connect(self._show_char_settings)

        self._sys_settings_btn = QPushButton()
        self._sys_settings_btn.setObjectName("sys_settings_btn")
        self._sys_settings_btn.setToolTip("系统设置")
        self._sys_settings_btn.setFixedSize(36, 36)
        self._sys_settings_btn.setIcon(self._create_settings_icon())
        self._sys_settings_btn.setIconSize(QSize(20, 20))
        self._sys_settings_btn.clicked.connect(self._show_sys_settings)

        bottom_btn_layout.addStretch()
        bottom_btn_layout.addWidget(self._hangar_settings_btn)
        bottom_btn_layout.addWidget(self._char_settings_btn)
        bottom_btn_layout.addWidget(self._sys_settings_btn)

        layout.addLayout(bottom_btn_layout)
        return panel

    def _on_nav_changed(self, current: QTreeWidgetItem, previous: QTreeWidgetItem):
        if current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if key is None:
            return
        page = self._pages.get(key)
        if page and self.content_stack.indexOf(page) >= 0:
            self.content_stack.setCurrentWidget(page)
            if hasattr(page, "update_status_bar"):
                page.update_status_bar()
            if key == "watchlist" and hasattr(page, "trigger_price_check"):
                page.trigger_price_check()

    def _register_pages(self):
        import sqlite3

        from ui_pyside6.views.contract_view import ContractPage
        from ui_pyside6.views.estimate_view import EstimatePage
        from ui_pyside6.views.industry_view import IndustryPage
        from ui_pyside6.views.inventory.inventory_page import InventoryPage
        from ui_pyside6.views.query import QueryPage
        from ui_pyside6.views.trade_view import TradePage
        from ui_pyside6.views.watchlist_view import WatchlistPage

        def _try_create(key, cls, *args, **kwargs):
            try:
                page = cls(*args, **kwargs)
                self._pages[key] = page
                return page
            except sqlite3.OperationalError:
                placeholder = QWidget()
                layout = QVBoxLayout(placeholder)
                layout.addWidget(QLabel("数据未初始化，请先通过 初始化 下载数据"))
                layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._pages[key] = placeholder
                return placeholder
            except Exception as e:
                log.exception("页面创建失败 %s: %s", key, e)
                import traceback

                traceback.print_exc()
                placeholder = QWidget()
                layout = QVBoxLayout(placeholder)
                layout.addWidget(QLabel(f"页面加载失败: {e}"))
                layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._pages[key] = placeholder
                return placeholder

        _try_create("estimate", EstimatePage, self)
        _try_create("query", QueryPage, self)
        _try_create("industry", IndustryPage, self)
        _try_create("trade", TradePage, self)
        _try_create("watchlist", WatchlistPage, self)
        _try_create("contract", ContractPage, self)
        _try_create("storage", InventoryPage, self)

        for key in ["estimate", "query", "industry", "trade", "watchlist", "contract", "storage"]:
            self.content_stack.addWidget(self._pages[key])
