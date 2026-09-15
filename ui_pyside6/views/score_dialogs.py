"""
评分弹窗与评分 Worker — 从 all_items_view.py 拆分而来
"""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
)

from core.constants import TRADE_HUBS
from core.container import get_container
from ui_pyside6.icon_cache import load_item_icon
from ui_pyside6.views.char_settings_view import get_character_list

REGIONS = TRADE_HUBS


def _icon_label(type_id: int, size: int = 32) -> QLabel | None:
    """创建物品图标标签，无图标时返回 None"""
    pix = load_item_icon(type_id, size=size)
    if pix is None:
        return None
    lbl = QLabel()
    lbl.setPixmap(pix)
    return lbl


class MfgDlg(QDialog):
    def __init__(self, current: dict | None = None, parent=None, type_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("制造评分设置")
        self.setMinimumWidth(260)
        form = QFormLayout(self)
        form.setSpacing(4)

        # 物品图标（如果有 type_id）
        if type_id is not None:
            icon = _icon_label(type_id)
            if icon:
                icon_row = QHBoxLayout()
                icon_row.addStretch()
                icon_row.addWidget(icon)
                icon_row.addStretch()
                form.addRow(icon_row)
            # 在标题中显示物品名
            try:
                name = get_container().item_repo.get_name(type_id)
                if name and name != str(type_id):
                    self.setWindowTitle(f"制造评分 — {name}")
            except Exception:
                pass

        cur = current or {}
        self.h = QComboBox()
        self.h.addItems(REGIONS)
        self.h.setCurrentText(cur.get("hub", "Jita"))
        form.addRow("中心:", self.h)
        self.c = QComboBox()
        cs = get_character_list()
        self.c.addItems(cs if cs else ["main"])
        self.c.setCurrentText(cur.get("char", "main") if cur.get("char") in cs else "main")
        form.addRow("人物:", self.c)
        self.t = QDoubleSpinBox()
        self.t.setRange(0, 100)
        self.t.setSuffix(" %")
        self.t.setValue(cur.get("tax", 0))
        form.addRow("设施税:", self.t)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)

    def get(self):
        c = self.c.currentText()
        return {
            "hub": self.h.currentText(),
            "char": c if c in get_character_list() else "main",
            "tax": self.t.value(),
        }


class TradeDlg(QDialog):
    def __init__(self, current: dict | None = None, parent=None, type_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("贸易评分设置")
        self.setMinimumWidth(260)
        form = QFormLayout(self)
        form.setSpacing(4)

        # 物品图标（如果有 type_id）
        if type_id is not None:
            icon = _icon_label(type_id)
            if icon:
                icon_row = QHBoxLayout()
                icon_row.addStretch()
                icon_row.addWidget(icon)
                icon_row.addStretch()
                form.addRow(icon_row)
            # 在标题中显示物品名
            try:
                name = get_container().item_repo.get_name(type_id)
                if name and name != str(type_id):
                    self.setWindowTitle(f"贸易评分 — {name}")
            except Exception:
                pass

        cur = current or {}
        self.bh = QComboBox()
        self.bh.addItems(REGIONS)
        self.bh.setCurrentText(cur.get("bh", "Jita"))
        form.addRow("买入:", self.bh)
        self.sh = QComboBox()
        self.sh.addItems(REGIONS)
        self.sh.setCurrentText(cur.get("sh", "Jita"))
        form.addRow("卖出:", self.sh)
        self.bs = QComboBox()
        self.bs.addItems(["卖单", "买单"])
        self.bs.setCurrentText("卖单" if cur.get("bs", "sell") == "sell" else "买单")
        form.addRow("买价:", self.bs)
        self.ss = QComboBox()
        self.ss.addItems(["卖单", "买单"])
        self.ss.setCurrentText("卖单" if cur.get("ss", "sell") == "sell" else "买单")
        form.addRow("卖价:", self.ss)
        self.c = QComboBox()
        cs = get_character_list()
        self.c.addItems(cs if cs else ["main"])
        self.c.setCurrentText(cur.get("char", "main") if cur.get("char") in cs else "main")
        form.addRow("人物:", self.c)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)

    def get(self):
        c = self.c.currentText()
        return {
            "bh": self.bh.currentText(),
            "sh": self.sh.currentText(),
            "bs": "sell" if self.bs.currentIndex() == 0 else "buy",
            "ss": "sell" if self.ss.currentIndex() == 0 else "buy",
            "char": c if c in get_character_list() else "main",
        }
