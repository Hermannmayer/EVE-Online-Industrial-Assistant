"""可制造物品的分类树加载线程（原先在 `ui_pyside6/views/manufacturable_items_dialog.py`）。"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container


class MfgTreeW(QThread):
    """加载可制造物品市场分类树"""

    done = Signal(list)

    def run(self):
        self.done.emit(get_container().blueprint_repo.get_manufacturable_market_tree())
