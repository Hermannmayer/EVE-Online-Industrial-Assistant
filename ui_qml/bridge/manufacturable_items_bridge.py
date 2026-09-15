"""可制造物品浏览器的桥（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/manufacturable_items_dialog.py::ManufacturableItemsDialog`：
工具栏（刷新计算 / 设置 / 批量对比 / 导出 / 钉）→ 筛选行（搜索 + 类别 + 状态）→
3px 进度条 → 左「可制造分类树」右「表单（基础列 + 制造列）」。

**取数、筛选、评分、导出格式一行都没搬过来**：分类树走原文件里的 `MfgTreeW`，
物品/搜索走 `ui_pyside6/workers/all_items_workers` 的 `ItemsW` / `SearchItemsW`，
评分走 `ui_pyside6/views/score_dialogs.ScoreW`，表格展示与排序仍是
`ui_pyside6/models/all_items_models.py` 的 `AModel` / `Proxy`。桥只做状态搬运。

与 `all_items_bridge.py` 共用的部分直接引用，不复制：分类树的扁平化
（`market_tree_rows` / `visible_tree_rows` / `subtree_ids`）、线程收尾（`drop_worker`）、
「加入制造列表」落库（`insert_plan_from_score`）以及「制造材料」明细对话框（`MatQmlDialog`）。
这两个桥**必须**同批迁移：本窗口双击物品行弹的正是那个明细，
右键「加入制造列表」弹的也是同一族对话框。

三处需要留意的接线：

1. **后台线程必须在关窗前收尾**（`stop()` → `drop_worker`），理由见 `all_items_bridge`。
2. **分类树点击有 200ms 防抖**（原版 `_tree_debounce`）：`selectTreeNode` 只记下标并起表，
   真正的加载在 `_on_tree_delayed()`。展开箭头则即时生效，不走防抖。
3. **换 ItemsW 前先断开旧 worker 的 `done`**（原版 `_on_tree_delayed` 里显式
   `disconnect()`）：否则很快地点两棵树时，先发出的那次结果会覆盖后一次的数据。
"""

from __future__ import annotations

import json
import os
from typing import Any

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QMessageBox

from core.cache import TtlLRUCache
from core.container import get_container
from core.logger import log
from core.paths import data_dir
from ui_pyside6.models.all_items_models import BCOLS, DASH, MCOLS, Proxy
from ui_pyside6.views.all_items_view import MFG_CATEGORIES
from ui_pyside6.views.manufacturable_items_dialog import MfgTreeW
from ui_pyside6.views.score_dialogs import ScoreW
from ui_pyside6.workers.all_items_workers import JITA_RID, ItemsW, SearchItemsW
from ui_qml.bridge.all_items_bridge import (
    drop_worker,
    insert_plan_from_score,
    market_tree_rows,
    subtree_ids,
    visible_tree_rows,
)
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.models.all_items_qml_model import AllItemsQmlModel

__all__ = ["ManufacturableItemsBridge", "ManufacturableItemsQmlDialog", "breakdown_text"]

_QML_FILE = "dialogs/ManufacturableItemsDialog.qml"

#: 搜索 / 树节点点击的防抖（原版两个 `QTimer` 都是 200ms）
_DEBOUNCE_MS = 200

_EXPORT_DEFAULT = "manufacturable_items.csv"
_EXPORT_FILTER = "CSV (*.csv);;Excel (*.xlsx)"


def breakdown_text(r: dict) -> str:
    """制造核算明细的正文 —— 逐字照搬 `ManufacturableItemsDialog._ds`。

    与 `all_items_bridge.breakdown_text(r, True)` 不是同一份文案：这个窗口只做制造，
    写的是「评分 / 每小时利润 / 运行成本」那一组，状态码也少了 `no_depth`。
    两边各自忠于各自的 Widgets 实现，不强行合并。
    """
    b = r.get("breakdown", {})
    st = r.get("status", "")
    if st:
        tips = {"no_blueprint": "此物品没有制造蓝图", "no_price": "查不到价格数据", "no_mats": "蓝图无材料数据"}
        return f"状态: {tips.get(st, st)}"
    lines = [
        f"评分: {r.get('score', 0):.0f}",
        f"单批利润: {r.get('profit_per_run', 0):,.0f} ISK",
        f"利润率: {r.get('margin_pct', 0):.1f}%",
        f"每小时利润: {r.get('isk_per_hour', 0):,.0f} ISK",
        f"材料成本: {b.get('material_cost', 0):,.0f} ISK",
    ]
    run_cost = b.get("run_cost", 0)
    if run_cost:
        lines.append(f"运行成本: {run_cost:,.0f} ISK")
    install = b.get("install_fee", 0)
    if install:
        lines.append(f"安装费: {install:,.0f} ISK")
    broker = b.get("broker_fee", 0)
    if broker:
        lines.append(f"经纪人费: {broker:,.0f} ISK")
    sales_tax = b.get("sales_tax", 0)
    if sales_tax:
        lines.append(f"销售税: {sales_tax:,.0f} ISK")
    return "\n".join(lines)


def _copy_line(cols: list[tuple], row: dict) -> str:
    """一行的制表符文本（原 `_copy_selection`：图标列换成 type_id）。"""
    parts = []
    for _title, _width, key in cols:
        parts.append(str(row.get("id", "")) if key == "i" else str(row.get(key, "")))
    return "\t".join(parts)


def _export_table(cols: list[tuple], rows: list[dict]) -> tuple[list[str], list[list[str]]]:
    """导出用的表头与二维表（口径与 `ManufacturableItemsDialog._export_data` 逐字一致：
    浮点两位小数、整数按原样、图标列跳过）。"""
    headers = [c[0] for c in cols if c[2] != "i"]
    out: list[list[str]] = []
    for row in rows:
        line: list[str] = []
        for _title, _width, key in cols:
            if key == "i":
                continue
            value = row.get(key)
            if value is None:
                line.append("")
            elif isinstance(value, float):
                line.append(f"{value:.2f}")
            else:
                line.append(str(value))
        out.append(line)
    return headers, out


class ManufacturableItemsBridge(DialogBridge):
    """可制造物品浏览器的 QML 后端。"""

    #: 状态行 / 进度 / 列 / 分类下标 / 选中行 / 钉住
    stateChanged = Signal()
    treeChanged = Signal()
    searchChanged = Signal()
    sortChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.set_title("可制造物品")

        self._categories: list[str] = list(MFG_CATEGORIES)
        self._cat_index = 0
        self._data: list[dict] = []
        self._filt: list[dict] = []
        self._mfg: dict[str, Any] = {"hub": "Jita", "char": "main", "tax": 0}
        self._load_settings()

        self._col_specs: list[tuple] = list(BCOLS)
        self._status = "请选择分类或搜索物品"
        self._progress_visible = False
        self._progress_value = 0
        self._progress_max = 0
        self._search_text = ""
        self._selected_row = -1
        self._selected_tree_id = -1
        self._pinned = False
        self._sort_column = -1
        self._sort_ascending = True

        self._tree_all: list[dict] = []
        self._tree_visible: list[dict] = []
        self._expanded: set[Any] = set()
        self._pending_tree_index = -1

        #: 与 Widgets 版同参的评分缓存。**两边都只读不写**，保留是为了让
        #: 「命中缓存才显示核算明细」这条判断逐字不变。
        self._cache = TtlLRUCache(max_size=5000, ttl_seconds=1800)

        self._model = AllItemsQmlModel()
        self._proxy = Proxy(self)
        self._proxy.setSourceModel(self._model)

        self._tw: Any = None
        self._iw: Any = None
        self._sw: Any = None
        self._wp: Any = None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._do_search)
        self._tree_debounce = QTimer(self)
        self._tree_debounce.setSingleShot(True)
        self._tree_debounce.timeout.connect(self._on_tree_delayed)

    # ── 启动 ─────────────────────────────────────────────────

    def start(self) -> None:
        """开窗时加载可制造分类树（原版在 `__init__` 末尾起 `MfgTreeW`）。"""
        self._tw = MfgTreeW(self)
        self._tw.done.connect(self._on_tree_data)
        self._tw.start()

    # ── 给 QML 读 ────────────────────────────────────────────

    model = Property(QObject, lambda self: self._proxy, constant=True)
    columns = Property(
        list, lambda self: [{"title": t, "width": w} for t, w, _k in self._col_specs], notify=stateChanged
    )
    categories = Property(list, lambda self: list(self._categories), constant=True)
    statusText = Property(str, lambda self: self._status, notify=stateChanged)
    categoryIndex = Property(int, lambda self: self._cat_index, notify=stateChanged)
    selectedRow = Property(int, lambda self: self._selected_row, notify=stateChanged)
    selectedTreeId = Property(int, lambda self: self._selected_tree_id, notify=stateChanged)
    searchText = Property(str, lambda self: self._search_text, notify=searchChanged)
    progressVisible = Property(bool, lambda self: self._progress_visible, notify=stateChanged)
    progressValue = Property(int, lambda self: self._progress_value, notify=stateChanged)
    progressMax = Property(int, lambda self: self._progress_max, notify=stateChanged)
    rowCount = Property(int, lambda self: self._proxy.rowCount(), notify=stateChanged)
    treeRows = Property(list, lambda self: list(self._tree_visible), notify=treeChanged)
    pinned = Property(bool, lambda self: self._pinned, notify=stateChanged)
    #: 「钉」按钮的文案：原版按下之后把标题从「钉」改成「已钉」
    pinLabel = Property(str, lambda self: "已钉" if self._pinned else "钉", notify=stateChanged)
    sortColumn = Property(int, lambda self: self._sort_column, notify=sortChanged)
    sortAscending = Property(bool, lambda self: self._sort_ascending, notify=sortChanged)

    # ── 顶栏 / 筛选 ──────────────────────────────────────────

    @Slot(str)
    def setSearchText(self, text: str) -> None:
        self._search_text = str(text)
        self._debounce.start(_DEBOUNCE_MS)

    @Slot(int)
    def setCategoryIndex(self, index: int) -> None:
        if 0 <= index < len(self._categories) and index != self._cat_index:
            self._cat_index = index
            self._apply()

    @Slot()
    def refreshScores(self) -> None:
        """「刷新计算」（原 `_on_mfg`）：先确认库里有价格，没有就保留现状。"""
        if not self._filt:
            return
        # 单条 SQL 确认 market_prices 是否有数据，避免 N 次 get_price 调用
        if get_container().market_repo.has_any_prices():
            # 清缓存（清后会惰性重建）→ 用最新价格重算
            self._cache.invalidate()
            self._set_status("重新计算中...")
            self._calc()
        else:
            self._set_status("暂无价格数据，请先在主界面更新价格")

    @Slot()
    def openMfgSettings(self) -> None:
        """「设置」（原 `_smfg`）：只有区域变了才重下列（重算代价大）。"""
        from ui_qml.bridge.score_dialogs_bridge import MfgQmlDialog

        dlg = MfgQmlDialog(self._mfg, self.host_widget())
        if dlg.exec():
            before_hub = self._mfg.get("hub", "Jita")
            self._mfg.update(dlg.get())
            self._save_settings()
            if before_hub != self._mfg.get("hub", "Jita"):
                self._upd()

    @Slot()
    def openCompare(self) -> None:
        """批量对比 —— 只带**当前选中行**（原版取 `selectionModel().selectedRows()`）。"""
        from ui_qml.bridge.compare_bridge import CompareQmlDialog

        items: list[dict] = []
        row = self._row_at(self._selected_row)
        if row and row.get("id"):
            items.append({"type_id": row["id"], "name": row.get("z", "")})
        dlg = CompareQmlDialog(initial_items=items, parent=self.host_widget())
        dlg.show()

    @Slot()
    def exportData(self) -> None:
        from ui_pyside6.views.export_helper import export_to_csv, export_to_excel, get_save_filename

        if self._proxy.rowCount() == 0:
            self._set_status("没有数据可导出")
            return
        try:
            path = get_save_filename(self.host_widget(), _EXPORT_DEFAULT, _EXPORT_FILTER)
            if not path:
                return
            headers, rows = _export_table(self._col_specs, self._filt)
            if path.endswith(".xlsx"):
                export_to_excel(headers, rows, path)
            else:
                export_to_csv(headers, rows, path)
            self._set_status(f"已导出 {len(rows)} 行")
        except Exception as e:  # 磁盘满 / 权限 / 占用 —— 只把原因写进状态行，不打断对话框
            log.exception("导出可制造物品失败")
            self._set_status(f"导出失败: {e}")

    # ── 分类树 ───────────────────────────────────────────────

    def _on_tree_data(self, items: list[dict]) -> None:
        self._tree_all = market_tree_rows(items)
        self._expanded.clear()
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        self._tree_visible = visible_tree_rows(self._tree_all, self._expanded)
        self.treeChanged.emit()

    @Slot(int)
    def toggleTreeNode(self, index: int) -> None:
        if not 0 <= index < len(self._tree_visible):
            return
        row = self._tree_visible[index]
        if not row["hasChildren"]:
            return
        node_id = row["id"]
        if node_id in self._expanded:
            self._expanded.discard(node_id)
        else:
            self._expanded.add(node_id)
        self._refresh_tree()

    @Slot(int)
    def selectTreeNode(self, index: int) -> None:
        """点分类：只记下标 + 起防抖表（原 `_on_tree` → `_on_tree_delayed`）。"""
        if not 0 <= index < len(self._tree_visible):
            return
        self._pending_tree_index = index
        self._tree_debounce.start(_DEBOUNCE_MS)

    def _on_tree_delayed(self) -> None:
        index = self._pending_tree_index
        if not 0 <= index < len(self._tree_visible):
            return
        node_id = self._tree_visible[index]["id"]
        ids = subtree_ids(self._tree_all, node_id)
        if not ids:
            return

        self._selected_tree_id = int(node_id)
        # 原版 `self._search_input.clear()`
        self._search_text = ""
        self.searchChanged.emit()
        self._data = []
        self._reload_items(sorted(ids))
        self.stateChanged.emit()

    def _reload_items(self, ids: list[Any] | None) -> None:
        # 断开旧 worker 的 `done` 再换新：否则先发出的那次结果会覆盖后一次的数据
        old = self._iw
        if old is not None:
            try:
                old.done.disconnect()
            except (TypeError, RuntimeError):
                pass
            drop_worker(old)

        worker = ItemsW(ids, rid=JITA_RID, parent=self)
        worker.done.connect(self._on_items)
        worker.start()
        self._iw = worker

    def _on_items(self, rows: list[dict]) -> None:
        self._data = rows
        has_price = any(r.get("bp") or r.get("sp") for r in rows[:100])
        self._set_status(f"共 {len(rows)} 条" if has_price else "暂无价格，请先在主界面更新")
        self._apply()

    # ── 搜索 ─────────────────────────────────────────────────

    def _do_search(self) -> None:
        query = self._search_text.strip()
        if not query:
            return
        drop_worker(self._sw)
        self._set_status("搜索中...")
        worker = SearchItemsW(query, JITA_RID, self)
        worker.done.connect(self._on_search_done)
        worker.start()
        self._sw = worker

    def _on_search_done(self, rows: list[dict]) -> None:
        self._data = rows
        self._apply()

    # ── 筛选与列 ─────────────────────────────────────────────

    def _apply(self) -> None:
        data = self._data
        cat = self._cat_index
        if data:
            repo = get_container().blueprint_repo
            bp_ids: set[int]
            if cat == 0:
                bp_ids = set(repo.get_all_product_ids("manufacturing"))
            elif cat == 1:
                bp_ids = repo.get_t1_manufacturable_product_ids()
            elif cat == 2:
                bp_ids = repo.get_t2_manufacturable_product_ids()
            elif cat == 3:
                bp_ids = repo.get_faction_manufacturable_product_ids()
            else:
                bp_ids = set(repo.get_all_product_ids("reaction"))
            data = [r for r in data if r["id"] in bp_ids]
        self._filt = data
        self._upd()

    def _set_columns(self, cols: list[tuple]) -> None:
        self._col_specs = list(cols)
        self._model.set_cols(list(cols))
        self._reapply_sort()
        self.stateChanged.emit()

    def _set_rows(self, rows: list[dict]) -> None:
        self._model.set_rows(rows)
        self._reapply_sort()
        self.stateChanged.emit()

    def _upd(self) -> None:
        """始终显示 基础列 + 制造列，数据先落表再异步算分（原 `_upd`）。"""
        cols = list(BCOLS)
        cols[3] = (f"买价（{self._mfg['hub']}）", 100, "bp")
        cols[4] = (f"卖价（{self._mfg['hub']}）", 100, "sp")
        cols.extend(MCOLS)
        self._set_columns(cols)
        if self._filt:
            self._set_rows(self._filt)
            self._set_status(f"共 {len(self._filt)} 条 | 计算评分中...")
            self._calc()
        else:
            self._set_rows([])
            self._set_status("无数据")

    # ── 评分 ─────────────────────────────────────────────────

    def _calc(self) -> None:
        # 原版这里要断旧 worker 的 progress/done 再换新（否则旧回调会覆盖新结果）；
        # `drop_worker` 一并把线程收尾 —— 正在跑的 QThread 被连带析构会中止进程
        drop_worker(self._wp)
        self._progress_visible = True
        self._progress_max = len(self._filt)
        self._progress_value = 0
        self._set_status("计算评分中...")

        worker = ScoreW(list(self._filt), True, self._mfg, self)
        worker.progress.connect(self._on_score_progress)
        worker.done.connect(self._on_scored)
        worker.start()
        self._wp = worker

    def _on_score_progress(self, current: int, _total: int) -> None:
        self._progress_value = current
        self.stateChanged.emit()

    def _on_scored(self, rows: list[dict]) -> None:
        self._filt = rows
        self._set_rows(rows)
        self._progress_visible = False
        self._set_status(f"共 {len(self._filt)} 条 | 评分已计算")

    # ── 表头排序 ─────────────────────────────────────────────

    @Slot(int)
    def sortByColumn(self, column: int) -> None:
        if not 0 <= column < len(self._col_specs):
            return
        if self._sort_column == column:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_column = column
            self._sort_ascending = True
        self._reapply_sort()
        self.sortChanged.emit()

    def _reapply_sort(self) -> None:
        if 0 <= self._sort_column < len(self._col_specs):
            order = Qt.SortOrder.AscendingOrder if self._sort_ascending else Qt.SortOrder.DescendingOrder
            self._proxy.sort(self._sort_column, order)

    # ── 表格行操作 ───────────────────────────────────────────

    def _row_at(self, row: int) -> dict | None:
        if not 0 <= row < self._proxy.rowCount():
            return None
        data = self._proxy.data(self._proxy.index(row, 0), Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _mfg_key(self, type_id: int) -> str:
        return f"{type_id}|mfg|{self._mfg['hub']}|{self._mfg['char']}"

    @Slot(int, result=dict)
    def rowInfo(self, row: int) -> dict:
        empty = {"valid": False, "typeId": 0, "name": "", "hasMfgDetail": False}
        data = self._row_at(row)
        if not data or not data.get("id"):
            return empty
        type_id = int(data["id"])
        return {
            "valid": True,
            "typeId": type_id,
            "name": data.get("z", "") or data.get("e", "") or str(type_id),
            "hasMfgDetail": bool(self._cache.get(self._mfg_key(type_id))),
        }

    @Slot(int, int)
    def clickCell(self, row: int, column: int) -> None:
        """单击单元格：选中该行并把这格文本复制到剪贴板（原 `_clk`）。"""
        if not 0 <= row < self._proxy.rowCount():
            return
        self._selected_row = row
        self.stateChanged.emit()
        data = self._row_at(row)
        if not data or not 0 <= column < len(self._col_specs):
            return
        value = data.get(self._col_specs[column][2])
        if value is None or str(value) == DASH or not str(value).strip():
            return
        QGuiApplication.clipboard().setText(str(value))

    @Slot()
    def copySelection(self) -> None:
        """Ctrl+C：复制当前行（原 `_copy_selection`）。"""
        data = self._row_at(self._selected_row)
        if data is None:
            self._set_status("没有选中行")
            return
        QGuiApplication.clipboard().setText(_copy_line(self._col_specs, data))
        self._set_status("已复制 1 行")

    @Slot()
    def copyAll(self) -> None:
        """Ctrl+A：整表复制（原版是「全选 + 复制」；QML 表只有单行选中，
        直接复制整表是同一件事的超集）。"""
        rows = [self._row_at(i) for i in range(self._proxy.rowCount())]
        lines = [_copy_line(self._col_specs, r) for r in rows if r]
        if not lines:
            self._set_status("没有选中行")
            return
        QGuiApplication.clipboard().setText("\n".join(lines))
        self._set_status(f"已复制 {len(lines)} 行")

    @Slot(int)
    def openMaterials(self, row: int) -> None:
        """双击物品行 → 制造材料明细（原 `_dbl` → `MatDlg`）。"""
        from ui_qml.bridge.all_items_bridge import MatQmlDialog

        data = self._row_at(row)
        if not data or not data.get("id"):
            return
        MatQmlDialog(int(data["id"]), self.host_widget()).exec()

    @Slot(int)
    def showBreakdown(self, row: int) -> None:
        """制造核算明细弹窗（原 `_ctx` 里的 `QMessageBox.information`）。"""
        data = self._row_at(row)
        if not data or not data.get("id"):
            return
        cached = self._cache.get(self._mfg_key(int(data["id"])))
        if cached:
            QMessageBox.information(self.host_widget(), "制造核算明细", breakdown_text(cached))

    @Slot(int)
    def addToPlan(self, row: int) -> None:
        """「加入制造列表」（原 `_ctx._do_add_plan`）。"""
        info = self.rowInfo(row)
        if not info["valid"]:
            return
        type_id = int(info["typeId"])
        name = str(info["name"])
        score = self._cache.get(self._mfg_key(type_id)) or {}

        from ui_qml.bridge.industry_dialogs_bridge import AddPlanDialogQmlDialog

        dlg = AddPlanDialogQmlDialog(name, score, self.host_widget())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data:
            return
        insert_plan_from_score(type_id, name, score, data, self._mfg)
        QMessageBox.information(self.host_widget(), "提示", f"已加入制造列表: {name}")

    # ── 置顶 ─────────────────────────────────────────────────

    @Slot(bool)
    def setPinned(self, pinned: bool) -> None:
        """「钉」按钮（原 `_on_pin_toggled`）—— 逻辑与 `all_items_bridge.setPinned` 同源。"""
        self._pinned = bool(pinned)
        host = self.host_widget()
        if host is not None:
            flags = host.windowFlags()
            if self._pinned:
                host.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
            else:
                host.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
            host.show()
        self.stateChanged.emit()

    # ── 设置 ─────────────────────────────────────────────────

    def _settings_path(self) -> str:
        return os.path.join(data_dir(), "mfg_browser_settings.json")

    def _load_settings(self) -> None:
        path = self._settings_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self._mfg.update(saved.get("mfg", {}))
        except Exception:
            # 原版这里是一段裸 `except: pass`；本仓禁止，改为记日志后按默认值继续
            log.exception("读取可制造物品设置失败 path=%s", path)

    def _save_settings(self) -> None:
        path = self._settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"mfg": self._mfg}, f, ensure_ascii=False, indent=2)
        except Exception:
            log.exception("保存可制造物品设置失败 path=%s", path)

    # ── 关窗收尾 ─────────────────────────────────────────────

    def stop(self) -> None:
        self._debounce.stop()
        self._tree_debounce.stop()
        for worker in (self._tw, self._iw, self._sw, self._wp):
            drop_worker(worker)

    def _set_status(self, text: str) -> None:
        self._status = str(text)
        self.stateChanged.emit()


class ManufacturableItemsQmlDialog(QmlDialog):
    """QML 版「可制造物品」。

    `ManufacturableItemsDialog(parent)` 的调用方把类名换掉即可 —— 构造签名逐字一致
    （含照常吃 parent：原版就是 `super().__init__(parent)` 的子窗口）。
    """

    def __init__(self, parent: Any = None) -> None:
        bridge = ManufacturableItemsBridge()
        super().__init__(_QML_FILE, bridge, parent=parent, size=(1100, 680))
        self._mfg_bridge = bridge
        self.setMinimumSize(800, 400)
        bridge.start()
