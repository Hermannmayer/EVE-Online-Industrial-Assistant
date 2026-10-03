"""库存剪贴板导入的后台线程 —— 解析/取数与落库/差异汇总都不再压主线程。

用户报障：「库存修正会导致整个软件**卡死**并进行计算。这个计算应该放在后台，不应该阻塞主界面。」

主线程原先同步做完这些活（整仓粘贴时都是秒级）：
1. ``parse_clipboard(raw)`` → ``search_item_type_ids_batch``（几百行名字批量匹配）+ 蓝图行过滤；
2. ``get_items(hangar, include_derived=False)`` 的导入前快照（名称 JOIN + 排序）；
3. 预览对话框里的整库现存量与整仓卖价取数；
4. 确认后的 ``apply_inventory_import``（几百行一个事务）+ 导入后快照 + ``compute_import_diff``。

现在 1–3 走 `InventoryImportFetchWorker`、4 走 `InventoryImportApplyWorker`：
主线程只负责弹预览/汇总对话框与忙碌光标，DB 与解析全在 worker 线程里跑。

**为什么用「起线程 + 等结果」而不是像蓝图那样 fire-and-forget**：两个现成调用方
（``ui_qml/bridge/inventory_bridge.py::runClipboardImport``、``ui_qml/views/procurement_tab.py``）
都在 ``run_clipboard_import(...)`` 返回后紧接着刷新自己的列表，即**依赖它是同步返回**的。
改成完全异步就得让调用方在回调里刷新，而那两个文件不在本任务的写范围里；
``review_bridge._wait_worker`` 用嵌套 ``QEventLoop`` 等 worker 结束（不是
``processEvents()`` 硬撑）—— UI 仍能重绘/响应定时器，只是本函数要到整个导入流程结束才返回，
调用方语义与改动前一字不差。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread, Signal

from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.logger import log
from services.inventory_clipboard_service import parse_clipboard
from services.inventory_import import compute_import_diff
from services.inventory_manager import apply_inventory_import, get_items


def item_display_name(item: dict) -> str:
    """统一显示名：display_name（terminology 覆盖优先）→ zh → en → str(type_id)。

    与预览行（``review_bridge.review_row``）同一口径；放这里是为了让 worker 与桥共用一份
    （桥原先自己有一份，改后台后两处都要用）。
    """
    return str(item.get("display_name") or item.get("zh_name") or item.get("en_name") or item.get("type_id", ""))


def snapshot_hangar(hangar_id: int) -> tuple[dict[int, tuple[int, float]], dict[int, str]]:
    """机库快照：``({type_id: (数量, 成本价)}, {type_id: 显示名})``。

    只取基础字段（``include_derived=False``）—— 预览/差异汇总都用不到计划占用与价格列。
    """
    items = get_items(hangar_id, include_derived=False)
    qty_cost = {int(it["type_id"]): (int(it["quantity"]), float(it.get("cost_price") or 0)) for it in items}
    names = {int(it["type_id"]): item_display_name(it) for it in items}
    return qty_cost, names


def build_import_preview(raw: str, target_hangar_id: int) -> dict:
    """解析剪贴板 + 取预览所需的全部数据（**阻塞活，只许在 worker 线程里调**）。

    返回 ``{parsed, filtered, existing_qty, hangar_names, sell_prices, before, names_before}``：
    - ``parsed`` / ``filtered``：``parse_clipboard`` 的结果；
    - ``existing_qty``：目标机库**整库** ``{type_id: 数量}`` —— 预览行用它显示现存量，
      全量同步的反向差集也用它（「库里有、剪贴板没有」= 待清零项）；
    - ``hangar_names``：整库显示名（待清零行要显示名称）；
    - ``sell_prices``：剪贴板涉及物品在当前贸易中心的卖单价（预览「成本价」列）；
    - ``before`` / ``names_before``：导入前快照，供导入后的变动汇总对比。
    """
    parsed, filtered = parse_clipboard(raw)
    before, hangar_names = snapshot_hangar(target_hangar_id) if target_hangar_id else ({}, {})
    existing_qty = {tid: qty for tid, (qty, _cost) in before.items()}
    type_ids = sorted({int(it["type_id"]) for it in parsed if it.get("type_id")})
    sell_prices = get_container().market_repo.get_sell_prices(type_ids, TRADE_HUB_IDS["Jita"]) if type_ids else {}
    return {
        "parsed": parsed,
        "filtered": filtered,
        "existing_qty": existing_qty,
        "hangar_names": hangar_names,
        "sell_prices": sell_prices,
        "before": before,
        "names_before": hangar_names,
    }


def apply_import_and_diff(
    hangar_id: int,
    data: list[tuple[int, int, float, int | None]],
    mode: str,
    targets: dict[int, int] | None,
    clear_missing: dict[int, int] | None,
    before: dict[int, tuple[int, float]],
    names_before: dict[int, str],
) -> dict:
    """落库 + 导入后快照 + 变动对比（**阻塞活，只许在 worker 线程里调**）。

    返回 ``{added, moved, changes}``；``changes`` 为 ``compute_import_diff`` 的行列表
    （含「只在 before」的零清行，见 ``run_clipboard_import`` 的 ``type_ids`` 拼接）。
    """
    added, moved = apply_inventory_import(hangar_id, data, mode, targets, clear_missing=clear_missing)
    after, names_after = snapshot_hangar(hangar_id)
    type_ids = list(dict.fromkeys([*before, *after]))
    names = {**names_before, **names_after}
    return {"added": added, "moved": moved, "changes": compute_import_diff(before, after, names, type_ids)}


class InventoryImportFetchWorker(QThread):
    """后台线程：解析剪贴板 + 取预览所需数据（见 ``build_import_preview``）。"""

    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, raw: str, target_hangar_id: int, parent: Any = None) -> None:
        super().__init__(parent)
        self._raw = raw
        self._target_hangar_id = int(target_hangar_id)

    def run(self) -> None:
        try:
            payload = build_import_preview(self._raw, self._target_hangar_id)
        except Exception as exc:
            log.exception("解析剪贴板/读取库存失败")
            self.error_signal.emit(str(exc) or exc.__class__.__name__)
            return
        self.finished_signal.emit(payload)


class InventoryImportApplyWorker(QThread):
    """后台线程：落库 + 导入后快照 + 变动对比（见 ``apply_import_and_diff``）。"""

    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(
        self,
        hangar_id: int,
        data: list[tuple[int, int, float, int | None]],
        mode: str,
        targets: dict[int, int] | None,
        clear_missing: dict[int, int] | None,
        before: dict[int, tuple[int, float]],
        names_before: dict[int, str],
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._args = (hangar_id, data, mode, targets, clear_missing, before, names_before)

    def run(self) -> None:
        try:
            result = apply_import_and_diff(*self._args)
        except Exception as exc:
            log.exception("应用库存导入失败")
            self.error_signal.emit(str(exc) or exc.__class__.__name__)
            return
        self.finished_signal.emit(result)
