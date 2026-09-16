"""批量对比对话框的桥（阶段 4b）。

对照 Widgets 版 `ui_pyside6/views/compare/compare_dialog.py::CompareDialog`。

**计算一行都没搬过来**：对比仍走 `compare_chart.CompareWorker`（后台线程，
按模式调 `scoring_service`），物品搜索仍走 `compare_chart.search_items`，
表格的展示规则仍走 `compare_models.CompareTableModel`（经 `CompareQmlModel`
补命名角色）。支撑模块一个字没动，桥只做「界面状态 ↔ 属性/槽」。

三处需要留意的接线：

1. **后台线程必须在关窗前收尾**。`QmlDialog._stop_bridge` 会调 `stop()`，
   里面 `cancel()` + `wait()`。不收尾的后果是硬崩：线程是桥的子对象，
   桥随对话框销毁时 `QThread` 若仍在运行，Qt 直接 `abort()`
   （本仓实测：退出码 127、一行日志都没有）。
2. **「查看物品」弹的是本次一并迁走的 `MfgQmlDialog` / `TradeQmlDialog`**，
   parent 用 `DialogBridge.host_widget()` —— 不能自己存宿主引用（环引用会先
   没掉 C++ 窗口，详见 `dialog_host` 里的说明）。
3. **导出文件走 `ui_qml.file_dialogs.get_save_filename`**：它内部仍是原生
   `QFileDialog`（操作系统文件选择器，不参与本应用主题，且保持同步语义），
   与 `all_items_bridge` / `manufacturable_items_bridge` 的导出收敛到同一入口；
   parent 取 `host_widget()`。
"""

from __future__ import annotations

import csv
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

from core.constants import TRADE_HUBS
from core.logger import log
from services import char_config_resolver
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.models.compare_models import _format_isk
from ui_qml.models.compare_qml_model import CompareQmlModel
from ui_qml.workers.compare_chart import CompareWorker, item_name, search_items

__all__ = ["CompareBridge", "CompareQmlDialog", "open_compare_qml_dialog"]

_QML_FILE = "dialogs/CompareDialog.qml"

#: 模式 key（与 Worker 的 `mode` 参数同口径）。**只是桥的内部索引**，
#: 不是 UI 文案 —— 文案见 `_MODE_NAMES`。
_MODES = ["mfg", "trade", "reaction"]

#: 模式下拉的文案。照抄 Widgets 版：这三个是**本应用的评分模式名**，
#: 不是蓝图活动（`term.activity("trade")` 只会把 "trade" 原样吐回来），
#: 所以走不了术语中心，与原版一样就地写死。
_MODE_NAMES = ["制造评分", "贸易评分", "反应评分"]

_HUBS: list[str] = list(TRADE_HUBS)

_READY_TEXT = "就绪"

#: 已添加物品列表的高度上限（原 `QListWidget.setMaximumHeight(90)`）
_ITEM_LIST_MAX_HEIGHT = 90


class CompareBridge(DialogBridge):
    """批量对比的 QML 后端。"""

    #: 通用界面状态（模式 / 参数 / 进度 / 状态行）
    stateChanged = Signal()
    #: 已添加物品列表
    itemsChanged = Signal()
    #: 列定义（换模式时换一套列）
    columnsChanged = Signal()

    def __init__(self, initial_items: list[dict] | None = None) -> None:
        super().__init__()
        self.set_title("批量对比")

        self._selected_items: list[dict] = []
        self._results: list[dict] = []
        self._search_text = ""
        self._worker: Any = None
        self._mode_index = 0
        self._hub_index = 0
        self._characters = list(char_config_resolver.get_character_list()) or ["main"]
        self._char_index = 0
        self._me = 0
        self._te = 0
        self._tax = 0.0
        self._progress_visible = False
        self._progress_value = 0
        self._progress_max = 0
        #: 是否正在算。**不能**用 `worker.isRunning()` 代替：`done` 是在 `run()` 结尾
        #: emit 的，那一刻线程还没退出，isRunning() 仍为 True 且之后不再发通知，
        #: 按钮会永远停在禁用态（原版也是在 `_on_done` 里显式 setEnabled(True)）。
        self._comparing = False
        self._status = _READY_TEXT
        #: 复用既有表格模型：展示规则（ISK 缩写 / 状态中文 / 正负染色）只有那一份
        self._model = CompareQmlModel(_MODES[0])

        if initial_items:
            for item in initial_items:
                if any(it["type_id"] == item["type_id"] for it in self._selected_items):
                    continue
                name = item.get("name") or item_name(item["type_id"])
                self._selected_items.append({"type_id": item["type_id"], "name": name})

    # ── 给 QML 读的属性 ───────────────────────────────────────

    model = Property(QObject, lambda self: self._model, constant=True)

    modeNames = Property(list, lambda self: list(_MODE_NAMES), constant=True)

    @Property(list, constant=True)
    def hubs(self) -> list[str]:
        return list(_HUBS)

    @Property(list, constant=True)
    def characters(self) -> list[str]:
        return list(self._characters)

    @Property(int, notify=stateChanged)
    def modeIndex(self) -> int:
        return self._mode_index

    @Property(bool, notify=stateChanged)
    def showMeTe(self) -> bool:
        """ME / TE 只对制造与反应有意义（贸易无 ME/TE —— 对齐原版 `_on_mode_changed`）。"""
        return _MODES[self._mode_index] in ("mfg", "reaction")

    @Property(int, notify=stateChanged)
    def hubIndex(self) -> int:
        return self._hub_index

    @Property(int, notify=stateChanged)
    def charIndex(self) -> int:
        return self._char_index

    @Property(int, notify=stateChanged)
    def me(self) -> int:
        return self._me

    @Property(int, notify=stateChanged)
    def te(self) -> int:
        return self._te

    @Property(float, notify=stateChanged)
    def tax(self) -> float:
        return self._tax

    @Property(str, notify=stateChanged)
    def searchText(self) -> str:
        return self._search_text

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status

    @Property(bool, notify=stateChanged)
    def progressVisible(self) -> bool:
        return self._progress_visible

    @Property(int, notify=stateChanged)
    def progressValue(self) -> int:
        return self._progress_value

    @Property(int, notify=stateChanged)
    def progressMax(self) -> int:
        return self._progress_max

    @Property(bool, notify=stateChanged)
    def canCompare(self) -> bool:
        return not self._comparing

    @Property(bool, notify=stateChanged)
    def exportEnabled(self) -> bool:
        """有结果**且**不在算 —— 原版在开始算时就把导出按钮禁掉了。"""
        return bool(self._results) and not self._comparing

    @Property(list, notify=itemsChanged)
    def items(self) -> list[dict]:
        return [{"name": it.get("name") or it.get("type_id")} for it in self._selected_items]

    @Property(bool, notify=itemsChanged)
    def hasItems(self) -> bool:
        return bool(self._selected_items)

    @Property(list, notify=columnsChanged)
    def columns(self) -> list[dict]:
        """列定义 `[{title, width}]` —— 直接读模型的当前列（单一来源）。

        宽度是**最小宽**：QML 那边让「物品」列吃掉剩余空间。Widgets 版是
        `setStretchLastSection(True)`，被拉伸的是最窄的「状态」列（90px 的列
        占满右侧空白、真正长的物品名反而被截断）—— 与 `ContractDetailBridge`
        同一处修正，列名/顺序/宽度一字未改。
        """
        return [{"title": title, "width": width} for title, width, _key in self._model._cols]

    @Property(int, constant=True)
    def itemListHeight(self) -> int:
        return _ITEM_LIST_MAX_HEIGHT

    # ── 搜索与添加 ────────────────────────────────────────────

    @Slot(str)
    def setSearchText(self, text: str) -> None:
        self._search_text = str(text)

    @Slot()
    def runSearch(self) -> None:
        """回车/点搜索：只回报找到了几条（原 `_on_search`），不动已添加列表。"""
        query = self._search_text.strip()
        if not query:
            return
        results = search_items(query)
        if results:
            first = results[0]
            name = first.get("zh_name") or first.get("en_name") or str(first["type_id"])
            self._set_status(f"找到 {len(results)} 条，首个: {name}")
        else:
            self._set_status("未找到匹配物品")

    @Slot()
    def addFirstMatch(self) -> None:
        """「添加」：取搜索结果的**第一个**匹配项（原 `_on_add_first_match`）。

        与 `runSearch` 分开是原版就有的行为：添加不依赖上一次的搜索缓存，
        而是拿当前输入重新查一次，避免「改了输入但没回车，加进去的是旧结果」。
        """
        query = self._search_text.strip()
        if not query:
            return
        results = search_items(query)
        if not results:
            self._set_status("未找到匹配物品")
            return
        first = results[0]
        self._add_item(
            int(first["type_id"]),
            first.get("zh_name") or first.get("en_name") or str(first["type_id"]),
        )
        # 与原版一致：添加成功后清空搜索框与结果
        self._search_text = ""
        self.stateChanged.emit()

    def _add_item(self, type_id: int, name: str) -> None:
        if any(it["type_id"] == type_id for it in self._selected_items):
            self._set_status(f"已添加: {name}")
            return
        self._selected_items.append({"type_id": type_id, "name": name})
        self.itemsChanged.emit()
        self._set_status(f"已添加: {name} (共 {len(self._selected_items)} 项)")

    @Slot(int)
    def removeItem(self, index: int) -> None:
        if not 0 <= index < len(self._selected_items):
            return
        removed = self._selected_items.pop(index)
        self.itemsChanged.emit()
        self._set_status(f"已移除: {removed.get('name', '')} (共 {len(self._selected_items)} 项)")

    @Slot()
    def clearItems(self) -> None:
        self._selected_items.clear()
        self.itemsChanged.emit()
        self._results = []
        self._model.set_rows([])
        self._set_status("已清空")

    # ── 参数 ──────────────────────────────────────────────────

    @Slot(int)
    def setModeIndex(self, index: int) -> None:
        """换模式：换一套列、重算可见性；已有结果就按新模式重算（原 `_on_mode_changed`）。"""
        if not 0 <= index < len(_MODES) or index == self._mode_index:
            return
        self._mode_index = index
        self._model.set_mode(_MODES[index])
        self.columnsChanged.emit()
        self.stateChanged.emit()
        if self._results:
            self.compare()

    @Slot(int)
    def setHubIndex(self, index: int) -> None:
        if 0 <= index < len(_HUBS):
            self._hub_index = index
            self.stateChanged.emit()

    @Slot(int)
    def setCharIndex(self, index: int) -> None:
        if 0 <= index < len(self._characters):
            self._char_index = index
            self.stateChanged.emit()

    @Slot(int)
    def setMe(self, value: int) -> None:
        self._me = max(0, min(10, int(value)))
        self.stateChanged.emit()

    @Slot(int)
    def setTe(self, value: int) -> None:
        self._te = max(0, min(20, int(value)))
        self.stateChanged.emit()

    @Slot(float)
    def setTax(self, value: float) -> None:
        self._tax = min(100.0, max(0.0, float(value)))
        self.stateChanged.emit()

    # ── 对比计算 ──────────────────────────────────────────────

    @Slot()
    def compare(self) -> None:
        if not self._selected_items:
            self._set_status("请先添加物品")
            return
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(2000)

        hub = _HUBS[self._hub_index]
        cfg = {
            "hub": hub,
            "char": self._characters[self._char_index],
            "tax": self._tax,
            "me": self._me,
            "te": self._te,
            # 贸易模式用买入/卖出区域；原版把两者都指向同一个下拉
            "bh": hub,
            "sh": hub,
            "bs": "sell",
            "ss": "sell",
        }

        self._progress_visible = True
        self._progress_max = len(self._selected_items)
        self._progress_value = 0
        self._comparing = True
        self._set_status(f"正在计算 {_MODE_NAMES[self._mode_index]}...")

        worker = CompareWorker(list(self._selected_items), _MODES[self._mode_index], cfg, self)
        self._worker = worker
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_done)
        worker.start()

    @Slot(int, int)
    def _on_progress(self, current: int, total: int) -> None:
        self._progress_value = current
        self._set_status(f"计算中 {current}/{total}...")

    @Slot(list)
    def _on_done(self, results: list[dict]) -> None:
        self._results = list(results)
        self._model.set_rows(self._results)
        self._progress_visible = False
        self._progress_value = 0
        self._comparing = False

        valid = [r for r in self._results if not r.get("status")]
        if not valid:
            self._set_status(f"完成 {len(self._results)} 项 | 无有效结果")
            return
        if _MODES[self._mode_index] == "trade":
            best = max(valid, key=lambda x: x.get("gross_profit", 0) or 0)
            best_profit = best.get("gross_profit", 0)
        else:
            best = max(valid, key=lambda x: x.get("profit", 0) or 0)
            best_profit = best.get("profit", 0)
        self._set_status(
            f"完成 {len(self._results)} 项 | 有效 {len(valid)} 项 | "
            f"最佳: {best.get('name', '')} ({_format_isk(best_profit or 0)} ISK)"
        )

    def stop(self) -> None:
        """关窗收尾：让在跑的后台线程结束（`QmlDialog._stop_bridge` 调它）。见模块 docstring 第 1 条。"""
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.requestInterruption()
            worker.wait(2000)

    # ── 表格行操作（右键菜单 / 双击）──────────────────────────

    @Slot(int, result=dict)
    def rowInfo(self, row: int) -> dict:
        """一行的关键信息，供右键菜单决定要不要给「查看物品」。"""
        if not 0 <= row < len(self._results):
            return {"valid": False, "typeId": 0, "name": ""}
        data = self._results[row]
        return {
            "valid": True,
            "typeId": int(data.get("type_id") or 0),
            "name": str(data.get("name") or ""),
        }

    @Slot(int)
    def openItemDetail(self, row: int) -> None:
        """「查看物品」：按当前模式弹该物品的评分设置（原 `_open_item_detail`）。"""
        info = self.rowInfo(row)
        if not info["valid"] or not info["typeId"]:
            return
        from ui_qml.bridge.score_dialogs_bridge import MfgQmlDialog, TradeQmlDialog

        cfg = {
            "hub": _HUBS[self._hub_index],
            "char": self._characters[self._char_index],
            "tax": self._tax,
        }
        parent = self.host_widget()
        if _MODES[self._mode_index] == "trade":
            dlg: QmlDialog = TradeQmlDialog(cfg, parent=parent)
            dlg.setWindowTitle(f"贸易评分 — {item_name(info['typeId'])}")
        else:
            dlg = MfgQmlDialog(cfg, parent=parent)
            dlg.setWindowTitle(f"制造评分 — {item_name(info['typeId'])}")
        dlg.exec()

    @Slot(int)
    def copyRow(self, row: int) -> None:
        """把该行按列拼成制表符分隔文本（列顺序取自模型的当前列）。"""
        if not 0 <= row < len(self._results):
            return
        data = self._results[row]
        parts = []
        for _title, _width, key in self._model._cols:
            val = data.get(key)
            parts.append(str(val) if val is not None else "")
        QGuiApplication.clipboard().setText("\t".join(parts))
        self._set_status("已复制行数据到剪贴板")

    @Slot()
    def copyAllCsv(self) -> None:
        """整表复制为 CSV 文本（原 `_copy_all_as_csv`）。"""
        data = self._model.get_export_data()
        lines = [",".join(str(cell) for cell in row) for row in data]
        QGuiApplication.clipboard().setText("\n".join(lines))
        self._set_status(f"已复制 {len(data) - 1} 行数据到剪贴板")

    @Slot()
    def exportCsv(self) -> None:
        """导出为 CSV 文件（原 `_on_export_csv`）。"""
        if not self._results:
            self._set_status("无数据可导出")
            return
        try:
            from ui_qml.file_dialogs import get_save_filename

            path = get_save_filename(
                self.host_widget(),
                "compare_result.csv",
                "CSV Files (*.csv);;All Files (*)",
            )
            if not path:
                return
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                for row in self._model.get_export_data():
                    writer.writerow(row)
            self._set_status(f"已导出: {path}")
        except Exception as e:
            # 原版就是把异常文本摆在状态行里（`导出失败: {e}`），这里照抄并额外记一条日志
            log.exception("导出对比结果失败")
            self._set_status(f"导出失败: {e}")

    def _set_status(self, text: str) -> None:
        self._status = str(text)
        self.stateChanged.emit()


class CompareQmlDialog(QmlDialog):
    """QML 版「批量对比」。

    `CompareDialog(initial_items, parent)` 的调用方把类名换成 `CompareQmlDialog`
    即可 —— 构造签名逐字一致。
    """

    def __init__(self, initial_items: list[dict] | None = None, parent: Any = None) -> None:
        bridge = CompareBridge(initial_items)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(1000, 620))
        self._compare_bridge = bridge


def open_compare_qml_dialog(parent: Any = None, initial_items: list[dict] | None = None) -> CompareQmlDialog:
    """打开批量对比对话框 —— 与 Widgets 版的 `open_compare_dialog` 逐字对应。

    调用点只需把 `open_compare_dialog(...)` 换成 `open_compare_qml_dialog(...)`。
    """
    dlg = CompareQmlDialog(initial_items=initial_items, parent=parent)
    dlg.show()
    return dlg
