"""
搜索组件 — 表格模型、后台 Worker、候选弹窗、搜索辅助函数
"""

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
)

import ui_pyside6.icons as icons
from core.container import get_container

# ═══════════════════════════════════════
#  Data model
# ═══════════════════════════════════════


# ═══════════════════════════════════════
#  Suggestion popup
# ═══════════════════════════════════════


class SuggestionPopup(QDialog):
    """悬浮候选列表 — 出现在搜索框下方"""

    item_selected = Signal(int, str)  # type_id, zh_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._list = QListWidget()
        self._list.setObjectName("suggest_list")
        self._list.itemClicked.connect(self._on_clicked)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list)
        self._list.installEventFilter(self)

    def show_suggestions(self, items: list, pos: QPoint, width: int):
        self._list.clear()
        for tid, display, zh_name in items:
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, tid)
            item.setData(Qt.ItemDataRole.UserRole + 1, zh_name)
            self._list.addItem(item)
        h = min(len(items) * 28 + 8, 220)
        self._list.setFixedHeight(h)
        self.setFixedSize(width, h)
        self.move(pos)
        self.show()

    def show_history(self, history: list, pos: QPoint, width: int):
        self._list.clear()
        for h in history[:8]:
            q = h["query"]
            item = QListWidgetItem(f" {q}")
            item.setIcon(icons.themed_icon("clock", 16))
            item.setData(Qt.ItemDataRole.UserRole, q)
            self._list.addItem(item)
        h = min((len(history) + 2) * 28 + 8, 220)
        self._list.setFixedHeight(h)
        self.setFixedSize(width, h)
        self.move(pos)
        self.show()

    def _on_clicked(self, item: QListWidgetItem):
        tid = item.data(Qt.ItemDataRole.UserRole)
        name = item.data(Qt.ItemDataRole.UserRole + 1) or item.data(Qt.ItemDataRole.UserRole) or ""
        self.hide()
        self.item_selected.emit(tid, name)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and obj is self._list:
            key = event.key()
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                current = self._list.currentItem()
                if current:
                    self._on_clicked(current)
                return True
            elif key == Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, event)


# ═══════════════════════════════════════
#  搜索历史辅助函数
# ═══════════════════════════════════════


def show_context_menu(page, pos):
    """显示表右键菜单"""
    index = page._table.indexAt(pos)
    if not index.isValid():
        return

    row_data = page._model.get_row(index.row())
    if not row_data:
        return

    type_id = row_data["type_id"]
    zh_name = row_data.get("zh", "")
    en_name = row_data.get("en", "")
    buy_price = row_data.get("buy_str", "—")
    sell_price = row_data.get("sell_str", "—")

    menu = QMenu(page)
    menu.setObjectName("view_menu")

    # ── 复制组 ──
    copy_name = QAction(f"复制名称: {zh_name or en_name}", page)
    copy_name.triggered.connect(lambda: _copy_to_clipboard(page, zh_name or en_name or str(type_id)))
    menu.addAction(copy_name)

    copy_id = QAction(f"复制 Type ID: {type_id}", page)
    copy_id.triggered.connect(lambda: _copy_to_clipboard(page, str(type_id)))
    menu.addAction(copy_id)

    if buy_price != "—":
        copy_buy = QAction(f"复制买单价格: {buy_price.split(' (')[0]} ISK", page)
        copy_buy.triggered.connect(lambda: _copy_to_clipboard(page, buy_price.split(" (")[0]))
        menu.addAction(copy_buy)

    if sell_price != "—":
        copy_sell = QAction(f"复制卖单价格: {sell_price.split(' (')[0]} ISK", page)
        copy_sell.triggered.connect(lambda: _copy_to_clipboard(page, sell_price.split(" (")[0]))
        menu.addAction(copy_sell)

    menu.addSeparator()

    # ── 操作组 ──
    view_orders = QAction("查看实时订单", page)
    from ui_qml.bridge.order_popup_bridge import do_load_orders

    view_orders.triggered.connect(lambda: do_load_orders(page, type_id))
    menu.addAction(view_orders)

    view_manufacturing = QAction("查看制造配方", page)
    view_manufacturing.triggered.connect(lambda: _view_manufacturing(page, type_id))
    menu.addAction(view_manufacturing)

    menu.addSeparator()

    # ── 快捷操作 ──
    copy_all = QAction("复制整行 (TSV)", page)
    copy_all.triggered.connect(lambda: _copy_row_tsv(page, row_data))
    menu.addAction(copy_all)

    menu.exec(page._table.viewport().mapToGlobal(pos))


def _copy_to_clipboard(page, text: str):
    QApplication.clipboard().setText(text)
    page._status_label.setText(f"已复制: {text}")


def _copy_row_tsv(page, row_data: dict):
    parts = [
        str(row_data.get("type_id", "")),
        row_data.get("zh", ""),
        row_data.get("en", ""),
        row_data.get("group", ""),
        row_data.get("buy_str", "—"),
        row_data.get("sell_str", "—"),
        row_data.get("avg_price_str", "—"),
        row_data.get("vol_str", "—"),
    ]
    text = "\t".join(parts)
    QApplication.clipboard().setText(text)
    page._status_label.setText("已复制整行数据 (TSV 格式)")


def _view_manufacturing(page, type_id: int):
    """切换到工业页查看制造配方"""
    page._main._nav_tree.setCurrentItem(page._main._nav_items[1])  # industry
    page._status_label.setText(f"切换到工业页查看 Type ID: {type_id}")


def do_add_to_plan(page, type_id: int, product_name: str):
    """从上下文菜单添加到生产计划"""
    from PySide6.QtWidgets import QDialog, QMessageBox

    from ui_pyside6.dialogs.industry_dialogs import AddPlanDialog
    from ui_qml.workers.industry_workers import ScoreWorker

    # 检查是否有蓝图（走 repository）
    has_bp = get_container().blueprint_repo.get_blueprint_for_product(type_id) is not None

    if not has_bp:
        QMessageBox.information(page, "提示", f"「{product_name}」无制造配方")
        return

    # 计算评分（强引用挂到 page，防局部 QThread 被 GC 闪退）
    from services.inventory_manager import get_default_mat_hangar_system_id

    page._add_plan_worker = ScoreWorker(
        type_id=type_id,
        bp_me=0,
        bp_te=0,
        mat_hub="Jita",
        sell_hub="Jita",
        tax=0.0,
        system_id=get_default_mat_hangar_system_id(),
        parent=page,
    )
    worker = page._add_plan_worker

    def _on_score(result: dict):
        try:
            dlg = AddPlanDialog(product_name, result, page)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            data = dlg.result_data()
            if not data:
                return
            from services import inventory_manager, user_settings
            from services.plan_service import insert_plan

            mat_hangar_id, solar_system_id = inventory_manager.get_default_mat_hangar_and_system()
            iskph = result.get("isk_per_hour", 0) or result.get("breakdown", {}).get("isk_per_hour", 0)
            mat_cost = result.get("breakdown", {}).get("material_cost", 0)
            metrics = {
                "profit": result.get("profit_per_run", 0) or 0,
                "margin": result.get("margin_pct", 0) or 0,
                "score": result.get("score", 0) or 0,
                "iskph": iskph,
                "material_cost": mat_cost,
                "calculated_time": (result.get("hours_per_run", 0) or 0) * 3600,
                "daily_output": 0,
            }
            insert_plan(
                type_id,
                product_name,
                data,
                mat_hub="Jita",
                sell_hub="Jita",
                facility=data["fac"],
                solar_system_id=solar_system_id,
                mat_hangar_id=mat_hangar_id,
                deposit_hangar_id=user_settings.get_default_hangar_id("default_deposit_hangar_id"),
                metrics=metrics,
            )
            QMessageBox.information(page, "成功", f"已添加到计划: {product_name}")
        finally:
            page._add_plan_worker = None  # 释放强引用

    worker.finished_signal.connect(_on_score)
    worker.start()
