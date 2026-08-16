"""
搜索组件 — 表格模型、后台 Worker、候选弹窗、搜索辅助函数
"""

import json
import time as _time
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QEvent, QPoint, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.container import get_container
from core.paths import search_history_file
from ui_pyside6.icon_cache import load_item_icon

ICON_SIZE = 32
HISTORY_FILE = Path(search_history_file())
MAX_HISTORY = 20
DEFAULT_REGION_ID = 10000002

_COLUMNS = [
    ("图标", 50),
    ("中文名", 140),
    ("英文名", 170),
    ("类别", 100),
    ("买单 ↓", 120),
    ("卖单 ↑", 120),
    ("均价", 90),
    ("体积 m³", 80),
]

_SORT_KEYS = [None, "zh", "en", "group", "buy_val", "sell_val", "avg_price_val", "vol_val"]


# ═══════════════════════════════════════
#  Data model
# ═══════════════════════════════════════


class QueryTableModel(QAbstractTableModel):
    """查询结果表格模型"""

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []
        self._sort_col: int = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self._sort_col = -1
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self._rows)

    def columnCount(self, parent=None):
        return len(_COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return ""
            return self._get_display(row, col)

        elif role == Qt.ItemDataRole.DecorationRole:
            if col == 0:
                pix = load_item_icon(row.get("type_id"), size=ICON_SIZE)
                if pix is not None:
                    return pix
            return None

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (1, 4, 5, 6, 7):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 4:
                return QColor(theme.GREEN) if row.get("buy_str") != "—" else QColor(theme.TEXT_SECONDARY)
            elif col == 5:
                return QColor(theme.RED) if row.get("sell_str") != "—" else QColor(theme.TEXT_SECONDARY)
            elif col == 6:
                return QColor(theme.GREEN) if row.get("avg_price_str") != "—" else QColor(theme.TEXT_SECONDARY)

        elif role == Qt.ItemDataRole.BackgroundRole:
            if row.get("is_inverted"):
                return QColor(theme.BG_HOVER)
            if index.row() % 2 == 0:
                return QColor(theme.BG_SURFACE)
            return QColor(theme.BG_DARK)

        elif role == Qt.ItemDataRole.FontRole:
            if col in (1, 4, 5, 6, 7):
                font = QFont("Consolas", 10)
                return font

        elif role == Qt.ItemDataRole.UserRole:
            return row

        return None

    def _get_display(self, row: dict, col: int) -> str:
        if col == 1:
            return row.get("zh", "")  # type: ignore[no-any-return]
        elif col == 2:
            return row.get("en", "")  # type: ignore[no-any-return]
        elif col == 3:
            return row.get("group", "")  # type: ignore[no-any-return]
        elif col == 4:
            return row.get("buy_str", "—")  # type: ignore[no-any-return]
        elif col == 5:
            return row.get("sell_str", "—")  # type: ignore[no-any-return]
        elif col == 6:
            return row.get("avg_price_str", "—")  # type: ignore[no-any-return]
        elif col == 7:
            return row.get("vol_str", "—")  # type: ignore[no-any-return]
        return ""

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            label = _COLUMNS[section][0]
            if section == self._sort_col:
                arrow = " ▲" if self._sort_order == Qt.SortOrder.AscendingOrder else " ▼"
                label = label.rstrip(" ↓↑") + arrow
            return label
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        sk = _SORT_KEYS[column] if column < len(_SORT_KEYS) else None
        if sk is None:
            return

        self.beginResetModel()
        reverse = order == Qt.SortOrder.DescendingOrder

        if sk in ("buy_val", "sell_val", "avg_price_val", "vol_val", "type_id"):
            self._rows.sort(key=lambda r: r.get(sk, 0) or 0, reverse=reverse)
        else:
            self._rows.sort(key=lambda r: (r.get(sk, "") or "").lower(), reverse=reverse)

        self._sort_col = column
        self._sort_order = order
        self.endResetModel()

    def get_row(self, row_idx: int) -> dict | None:
        if 0 <= row_idx < len(self._rows):
            return self._rows[row_idx]
        return None


# ═══════════════════════════════════════
#  Workers
# ═══════════════════════════════════════


class SearchWorker(QThread):
    """后台数据库搜索"""

    finished_signal = Signal(list, bool)  # rows, is_fallback
    error_signal = Signal(str)

    def __init__(self, query: str, all_groups: list, region_id: int = 10000002, parent=None):
        super().__init__(parent)
        self._query = query
        self._region_id = region_id
        self._all_groups = all_groups

    def run(self):
        try:
            rows = self._db_search(self._query)
            self.finished_signal.emit(rows, False)
        except Exception as e:
            try:
                rows = self._db_search_basic(self._query)
                self.finished_signal.emit(rows, True)
            except Exception:
                self.error_signal.emit(str(e))

    def _db_search(self, query: str):
        with get_container().db.connect("ref", "mkt") as conn:
            c = conn.cursor()
            like = f"%{query}%"
            group_match = None
            for gid, en, zh in self._all_groups:
                if (zh and query in zh) or (en and query in en):
                    group_match = gid
                    break

            if query.isdigit():
                c.execute(
                    """
                    SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
                           mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                    FROM item i
                    LEFT JOIN mkt.market_prices mp ON i.type_id = mp.type_id AND mp.region_id = ?
                        AND mp.fetch_time = (SELECT MAX(fetch_time) FROM mkt.market_prices WHERE type_id = i.type_id AND region_id = ?)
                    WHERE i.type_id = ? OR i.en_name LIKE ? OR i.zh_name LIKE ?
                    ORDER BY i.type_id LIMIT 300
                """,
                    (self._region_id, self._region_id, int(query), like, like),
                )
            elif group_match is not None:
                c.execute(
                    """
                    SELECT sub.type_id, sub.zh_name, sub.en_name, sub.en_group_name, sub.zh_group_name, sub.volume,
                           mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                    FROM (
                        SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume
                        FROM item i WHERE i.group_id = ?
                        UNION
                        SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume
                        FROM item i WHERE (i.en_name LIKE ? OR i.zh_name LIKE ?)
                    ) sub
                    LEFT JOIN mkt.market_prices mp ON sub.type_id = mp.type_id AND mp.region_id = ?
                        AND mp.fetch_time = (SELECT MAX(fetch_time) FROM mkt.market_prices WHERE type_id = sub.type_id AND region_id = ?)
                    ORDER BY sub.type_id LIMIT 300
                """,
                    (self._region_id, self._region_id, group_match, like, like),
                )
            else:
                c.execute(
                    """
                    SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
                           mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                    FROM item i
                    LEFT JOIN mkt.market_prices mp ON i.type_id = mp.type_id AND mp.region_id = ?
                        AND mp.fetch_time = (SELECT MAX(fetch_time) FROM mkt.market_prices WHERE type_id = i.type_id AND region_id = ?)
                    WHERE i.en_name LIKE ? OR i.zh_name LIKE ?
                    ORDER BY i.type_id LIMIT 300
                """,
                    (self._region_id, self._region_id, like, like),
                )
            return c.fetchall()

    def _db_search_basic(self, query: str):
        with get_container().db.connect("ref") as conn:
            c = conn.cursor()
            if query.isdigit():
                c.execute(
                    "SELECT type_id, zh_name, en_name, zh_group_name, en_group_name, volume"
                    " FROM item WHERE type_id = ?",
                    (int(query),),
                )
            else:
                c.execute(
                    "SELECT type_id, zh_name, en_name, zh_group_name, en_group_name, volume"
                    " FROM item WHERE en_name LIKE ? OR zh_name LIKE ? LIMIT 100",
                    (f"%{query}%", f"%{query}%"),
                )
            return c.fetchall()


class SuggestionWorker(QThread):
    """后台候选搜索"""

    finished_signal = Signal(list)  # list of (type_id, display, zh_name)

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self._query = query

    def run(self):
        with get_container().db.connect("ref") as conn:
            c = conn.cursor()
            q = self._query
            if q.isdigit():
                c.execute(
                    "SELECT type_id, en_name, zh_name FROM item "
                    "WHERE type_id = ? OR en_name LIKE ? OR zh_name LIKE ? "
                    "ORDER BY CASE WHEN type_id = ? THEN 0 ELSE 1 END, LENGTH(en_name), type_id LIMIT 10",
                    (int(q), f"%{q}%", f"%{q}%", int(q)),
                )
            else:
                c.execute(
                    "SELECT type_id, en_name, zh_name FROM item "
                    "WHERE en_name LIKE ? OR zh_name LIKE ? "
                    "ORDER BY CASE WHEN en_name LIKE ? THEN 0"
                    " WHEN zh_name LIKE ? THEN 1 ELSE 2 END,"
                    " LENGTH(en_name), type_id LIMIT 10",
                    (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"),
                )
            result = []
            for tid, en, zh in c.fetchall():
                zh_name = zh or en or str(tid)
                display = f"[{tid}] {zh or ''} ({en or ''})" if zh and en else f"[{tid}] {zh or en or 'Unknown'}"
                result.append((tid, display, zh_name))
            self.finished_signal.emit(result)


class GroupLoadWorker(QThread):
    """加载类别列表"""

    finished_signal = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            with get_container().db.connect("ref") as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT DISTINCT e.group_id, e.en_group_name, e.zh_group_name"
                    " FROM item e WHERE e.group_id IS NOT NULL"
                    " ORDER BY e.zh_group_name, e.en_group_name"
                )
                result = c.fetchall()
                self.finished_signal.emit(result)
        except Exception:
            self.finished_signal.emit([])


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
            item = QListWidgetItem(f"🕐  {q}")
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


def add_search_history(query: str):
    """保存搜索历史到文件"""
    try:
        history = []
        if HISTORY_FILE.exists():
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        history = [h for h in history if h.get("query") != query]
        history.insert(0, {"query": query, "time": _time.time()})
        if len(history) > MAX_HISTORY:
            history = history[:MAX_HISTORY]
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def load_search_history() -> list:
    """从文件加载搜索历史"""
    try:
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except Exception:
        pass
    return []


def clear_search_history():
    """清空搜索历史文件"""
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text("[]", encoding="utf-8")
    except Exception:
        pass


# ═══════════════════════════════════════
#  搜索结果格式化
# ═══════════════════════════════════════


def format_search_rows(rows: list, is_fallback: bool) -> list[dict]:
    """将数据库返回的行格式化为表格模型所需的字典列表"""
    parsed = []
    for row in rows:
        if is_fallback:
            tid, zh, en, zhg, eng, vol = row[:6]
            buy_p = sell_p = None
            buy_v = sell_v = 0
        else:
            tid, zh, en, en_group, zh_group, volume, buy_p, sell_p, buy_v, sell_v = row
            buy_v = buy_v or 0
            sell_v = sell_v or 0
            vol = volume or 0.0

        group = (zh_group or en_group or "—") if not is_fallback else (zhg or eng or "—")

        buy_str = "—"
        if buy_p is not None and buy_v > 0:
            buy_str = f"{buy_p:,.2f} ({buy_v:,})"
        elif buy_p is not None:
            buy_str = f"{buy_p:,.2f}"

        sell_str = "—"
        if sell_p is not None and sell_v > 0:
            sell_str = f"{sell_p:,.2f} ({sell_v:,})"
        elif sell_p is not None:
            sell_str = f"{sell_p:,.2f}"

        avg_price_str = "—"
        avg_price_val = 0.0
        if buy_p is not None and sell_p is not None:
            avg_price_val = (buy_p + sell_p) / 2
            avg_price_str = f"{avg_price_val:,.2f}"
        elif buy_p is not None:
            avg_price_val = buy_p
            avg_price_str = f"{buy_p:,.2f}"
        elif sell_p is not None:
            avg_price_val = sell_p
            avg_price_str = f"{sell_p:,.2f}"

        buy_val = buy_p if buy_p is not None else 0.0
        sell_val = sell_p if sell_p is not None else 0.0
        is_inverted = buy_p is not None and sell_p is not None and buy_p > sell_p

        parsed.append(
            {
                "type_id": tid,
                "zh": zh or "",
                "en": en or "",
                "group": group,
                "buy_str": buy_str,
                "sell_str": sell_str,
                "buy_val": buy_val,
                "sell_val": sell_val,
                "avg_price_str": avg_price_str,
                "avg_price_val": avg_price_val,
                "vol_str": f"{vol:,.2f}" if vol > 0 else "—",
                "vol_val": vol,
                "is_inverted": is_inverted,
            }
        )
    return parsed


# ═══════════════════════════════════════
#  上下文菜单辅助
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
    from ui_pyside6.views.query.query_order_popup import do_load_orders

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
    from ui_pyside6.workers.industry_workers import ScoreWorker

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
            from services import inventory_manager
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
                metrics=metrics,
            )
            QMessageBox.information(page, "成功", f"已添加到计划: {product_name}")
        finally:
            page._add_plan_worker = None  # 释放强引用

    worker.finished.connect(_on_score)
    worker.start()
