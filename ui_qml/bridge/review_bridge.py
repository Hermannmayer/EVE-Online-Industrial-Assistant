"""剪贴板导入审阅链路的 QML 版（阶段 4b-3）。

对照旧 Widgets 版审阅对话框，一次迁三样：

- `ImportReviewDialog`  → `ImportReviewBridge` + `ImportReviewQmlDialog`
- `ImportChangeDialog`  → `ImportChangeBridge` + `ImportChangeQmlDialog`（复用汇总表骨架）
- `run_clipboard_import` → 同名同签名的编排函数（换的只是对话框实现）

外加原文件里 `_add_from_hangar` 现搭的那个「选择要移动的物品」QDialog —— 它是
「来自其他机库」右键项的第二级弹出，不迁就会从 QML 对话框里冒出一个纯 Widgets 窗口，
所以一并做成 `HangarPickBridge` + `HangarPickQmlDialog`。

**业务逻辑只有一份**：增减计算 `compute_row_delta`、导入前后对比 `compute_import_diff`、
剪贴板解析 `parse_clipboard`、落库 `apply_inventory_import`、市价取数 `market_repo` —— 全部
调用既有 services，桥只负责「取数 + 整形成 QML 能画的行/状态」。原类留在原文件里不动，
等调用点由主流程切过来后随该文件一并删除。

与原版的**刻意差异**（其余逐条对齐）：
- 预览表的**勾选态不重建行模型**（2026-09-27）：勾选只改行字典里的 `checked` 位 + 打一次
  `checkRevisionChanged` 心跳，统计行走 `statusChanged`；`stateChanged` 留给真正改了行结构
  的路径（装载 / 切模式 / 改「最终」/ 删行）。原实现每次勾选都发 `stateChanged`，而它正是
  `rows` 的通知信号 → QML 的行区 `Repeater` 整体重建、正在处理信号的 delegate 被同步销毁。
  详见 `ImportReviewBridge` 的类 docstring（含探针实测数字）。
- 表格列宽由「ResizeToContents + 最小宽」改为固定宽 + 名称列吃满 —— QML 这边
  表格是自绘的，没有 QHeaderView 的自动量宽；列宽单点放在桥的 `columns` 里便于断言。
- 「变化」列在有值时是 `FSpinBox`：输入不出非法值。原版是可编辑单元格，非数字
  在 `_on_final_changed` 里被 `except ValueError: return` 吞掉（保持原值不变），
  这里等价于「根本输入不进去」。
- 「来自其他机库」子菜单与它前面的分隔线**恒显示**：`FMenu` 没有「不可见即压高度」
  的兄弟组件（`FMenuItem` / `FMenuSeparator` 才有），空列表时是一个空子菜单。
  原版是无其他机库时整块不出现（`get_hangars()` 只排除目标机库，实际基本非空）。
- 4 处消息框改走 `FMessageDialog`（自绘 QML，批次 7.1）：
  「没有勾选」「N 行未匹配」「无物品」「无价格数据」。前两条**尤其不能**改成桥的
  `error` 通道 —— 原版是弹完继续 `accept()`／`return`，走 error 通道会在
  「确定导入」关窗后无人看见。
- **导入链路的耗时活全部移到后台线程**（2026-10-03，用户报「库存修正导致整个软件卡死」）：
  解析剪贴板 / 整库快照 / 整仓卖价 / 落库 / 导入后快照与差异对比走
  `ui_qml/workers/inventory_import_worker.py` 的两个 QThread（`_wait_worker` 用嵌套
  `QEventLoop` 等结果、忙碌光标做非阻塞反馈）。主线程只弹预览/汇总两个对话框；
  `run_clipboard_import` 的**返回时机**与改动前一致（两个现成调用方都在它返回后刷新列表，
  且它们不在本任务的写范围里）。
- **预览默认只显示有变更的行**（2026-10-03，用户报「几百行里看不出哪几行变了」）：
  `_all_rows` 是提交真源（勾选/改值/汇总/`get_import_data`/`get_sync_targets` 全按它），
  `_rows` 只是**可见视图**（`setOnlyChanged` + `_row_changed`）；未匹配行与跨机库移动行
  恒显示。行号类操作（勾选/改值/右键/删除/搜索匹配）走可见下标，靠行上的 `itemIndex`
  映射回 `_items`。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QEventLoop, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QDialog

from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.logger import log
from services.inventory_clipboard_service import parse_purchase_clipboard
from services.inventory_import import compute_missing_in_hangar, compute_row_delta, merge_same_type_rows
from services.inventory_manager import apply_inventory_import, get_hangars, get_items
from services.user_settings import get_material_price_mult, set_material_price_mult
from ui_qml.bridge.message_dialog import FMessageDialog
from ui_qml.bridge.summary_dialog import SummaryTableBridge, SummaryTableQmlDialog, cell
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.icon_cache import icon_url as _png_url
from ui_qml.workers.inventory_import_worker import (
    InventoryImportApplyWorker,
    InventoryImportFetchWorker,
    item_display_name,
)

__all__ = [
    "HangarPickBridge",
    "HangarPickQmlDialog",
    "ImportChangeBridge",
    "ImportChangeQmlDialog",
    "ImportReviewBridge",
    "ImportReviewQmlDialog",
    "choose_hangar",
    "missing_row",
    "review_row",
    "run_clipboard_import",
    "run_purchase_import",
]

_REVIEW_QML = "dialogs/ImportReviewDialog.qml"
_CHANGE_QML = "dialogs/ImportChangeDialog.qml"
_HANGAR_PICK_QML = "dialogs/HangarPickDialog.qml"

#: 忙碌光标嵌套深度（`_set_busy` 用引用计数，避免内层提前复位）
_BUSY_DEPTH = 0
#: 正在跑的导入 worker —— **强引用保活**（调用方传的 `parent` 可能是 `None`，
#: 见 `inventory_bridge.runClipboardImport`；局部 QThread 被 GC 会 abort 进程）
_ACTIVE_WORKERS: set[Any] = set()
#: 导入进行中标记 —— 这条路径会写用户库存，嵌套事件循环期间再被触发就直接挡掉
_IMPORT_IN_FLIGHT = False

#: 贸易中心（顺序与 Widgets 版的 combo 一致）
_HUB_ORDER = ["Jita", "Amarr", "Dodixie", "Rens"]
#: 贸易中心英文 → 中文（原 `ImportReviewDialog._HUB_NAMES`）
_HUB_NAMES = {"Jita": "吉他", "Amarr": "艾玛", "Dodixie": "多迪", "Rens": "伦斯"}

#: 导入模式：值 → 下拉显示名（原 combo 的两项）
_MODES: list[tuple[str, str]] = [("incremental", "增量累加"), ("full", "全量同步")]

#: 预览表列定义。width = 0 表示吃满剩余空间（与 `FSummaryTable` 同一约定）。
#: 标题照抄原 `_HEADERS`；勾选列在 QML 里是复选框、图标列是图片，标题留空/「图标」。
_REVIEW_COLUMNS = [
    {"title": "", "width": 30},
    {"title": "图标", "width": 46},
    {"title": "名称", "width": 0},
    {"title": "数量", "width": 92},
    {"title": "比原纪录", "width": 92},
    {"title": "变化", "width": 116},
    {"title": "成本价", "width": 132},
]

_CHANGE_COLUMNS = [
    {"title": "名称", "width": 0},
    {"title": "数量（前 → 后）", "width": 170},
    {"title": "成本（前 → 后）", "width": 170},
]

#: 数量/价格控件上限（原 `QDoubleSpinBox.setRange(0, 1e12)`）
_MAX_PRICE = 1e12
_MAX_QTY = 2_000_000_000


def _delta_token(delta: int) -> str:
    """增减着色：正绿负红，0 用默认前景色（原版 0 时不设 `ForegroundRole`）。"""
    if delta > 0:
        return "ACCENT_GREEN"
    if delta < 0:
        return "ACCENT_RED"
    return ""


def review_row(
    item: dict,
    *,
    current: int,
    sell_price: float,
    mode: str,
    source_hangar_id: int | None,
) -> dict:
    """一行预览数据 → QML 行字典（纯函数，便于单测）。

    Args:
        item: 解析后的一行 `{type_id|None, zh_name, en_name, qty, raw_name...}`
        current: 目标机库现有数量
        sell_price: 当前贸易中心的卖单价
        mode: 该行生效的导入模式（跨机库移动行恒为 ``incremental``）
        source_hangar_id: 该行的来源机库 id（非空 = 跨机库移动行）
    """
    type_id = item.get("type_id")
    if not type_id:
        raw = item.get("raw_name") or item.get("zh_name") or item.get("en_name") or "?"
        return {
            "typeId": None,
            "name": f"{raw}（未匹配）",
            "iconUrl": "",
            "current": 0,
            "currentText": "0",
            "delta": 0,
            "deltaText": "0",
            "deltaToken": "TEXT_SECONDARY",
            "final": 0,
            "price": 0.0,
            "checked": False,
            "checkable": False,
            "unmatched": True,
        }
    delta, final = compute_row_delta(mode, int(item.get("qty") or 0), int(current))
    merged = [int(x) for x in (item.get("merged") or [])]
    return {
        "typeId": int(type_id),
        "name": str(item.get("display_name") or item.get("zh_name") or item.get("en_name") or f"ID:{type_id}"),
        #: 同名多堆合并的提示（空串 = 单堆）。合并是**必须**的：full 模式按 type_id 覆盖写，
        #: 不合并就只有最后一堆生效（实测莫尔石 2999+184+176 只写进了 176）。
        #: 这里把每一堆都列出来，让用户看得见「这次到底加了几笔」。
        "mergedText": f"（{' + '.join(f'{q:,}' for q in merged)} = {sum(merged):,}，{len(merged)} 堆合并）"
        if len(merged) > 1
        else "",
        "merged": merged,
        "iconUrl": _png_url(type_id),
        "current": int(current),
        "currentText": f"{int(current):,}",
        "delta": delta,
        "deltaText": f"+{delta:,}" if delta >= 0 else f"{delta:,}",
        "deltaToken": _delta_token(delta),
        "final": final,
        "price": float(sell_price or 0.0),
        "checked": True,
        "checkable": True,
        "unmatched": False,
    }


def missing_row(type_id: int, name: str, current: int, sell_price: float = 0.0) -> dict:
    """全量同步的**待清零行**（库里有、剪贴板没有）→ QML 行字典（纯函数，便于单测）。

    形状与 `review_row` 完全一致，只多一个 `missing` 标记（供 `deleteRows` 区分合成行、
    供统计文案计数）。`final` 固定初值 0 = 清零（`set_item_quantity` 见 0 就删行），
    `checked=True` = 默认勾选、用户可取消；用户也可以把「变化」列改成 N 表示「保留/设为 N」。
    """
    current = int(current)
    return {
        "typeId": int(type_id),
        "name": str(name or f"ID:{type_id}"),
        "iconUrl": _png_url(int(type_id)),
        "current": current,
        "currentText": f"{current:,}",
        "delta": -current,
        "deltaText": f"{-current:,}",
        "deltaToken": _delta_token(-current),
        "final": 0,
        "price": float(sell_price or 0.0),
        "checked": True,
        "checkable": True,
        "unmatched": False,
        "missing": True,
    }


def change_rows(changes: list[dict]) -> list[dict]:
    """变动汇总 → 单元格行（纯函数，便于单测）。

    数量列按增减染绿/红（与 `ImportChangeDialog` 逐条对齐），成本列不染色。
    """
    rows: list[dict] = []
    for ch in changes:
        delta = int(ch["qty_delta"])
        token = "ACCENT_GREEN" if delta > 0 else ("ACCENT_RED" if delta < 0 else "")
        rows.append(
            {
                "cells": [
                    cell(ch["name"]),
                    cell(f"{ch['qty_before']:,} → {ch['qty_after']:,}", token),
                    cell(f"{ch['cost_before']:,.2f} → {ch['cost_after']:,.2f}"),
                ]
            }
        )
    return rows


def change_summary(changes: list[dict], added: int, moved: int) -> str:
    """汇总文案（原 `ImportChangeDialog._build_summary`，逐字对齐）。"""
    if not changes:
        return f"成功导入 {added} 条，数量/成本均无变化"
    inc = sum(1 for c in changes if c["qty_delta"] > 0)
    dec = sum(1 for c in changes if c["qty_delta"] < 0)
    parts = [f"共 {len(changes)} 项变化"]
    if inc:
        parts.append(f"增加 {inc}")
    if dec:
        parts.append(f"减少 {dec}")
    if added:
        parts.append(f"成功导入 {added} 条")
    if moved:
        parts.append(f"跨机库移动 {moved} 条")
    return "，".join(parts)


# ══════════════════════════════════════════════════════════════
#  选择要移动的物品（原 `ImportReviewDialog._add_from_hangar` 现搭的那个对话框）
# ══════════════════════════════════════════════════════════════


class HangarPickBridge(DialogBridge):
    """另一机库的物品清单 —— 勾选要移入的物品。

    **勾选态与行数据分离**（2026-09-27，照 `ui_qml/bridge/blueprint_picker_bridge.py`）：
    勾选只改桥单独持有的 `_checked`，再打一次 `checkRevisionChanged` 心跳让 QML 的复选框
    回读；**不重建 `rows`**。原先 `setChecked()` 把结果写回行字典后发 `stateChanged`，而
    `stateChanged` 正是 `rows` 的通知信号 —— QML 的 `model` 是普通 var 列表 →
    `ListView` 整体重建 → **滚动位置回顶**：滑到中段点一格，列表直接跳回最顶端。

    `stateChanged` 这一条通知**保持原样**（`rows` 仍归它管，只是它不再承载勾选态，
    勾选也就不会再触发它）。
    """

    stateChanged = Signal()
    #: 勾选态心跳：QML 的每个复选框靠它把自己拉回与桥一致
    checkRevisionChanged = Signal()

    def __init__(self, source_items: list[dict]) -> None:
        super().__init__()
        self.set_title("选择要移动的物品")
        self._rows: list[dict] = [
            {
                "typeId": int(it["type_id"]),
                "name": str(it.get("display_name") or it.get("zh_name") or it.get("en_name") or f"ID:{it['type_id']}"),
                "qtyText": f"{int(it['quantity']):,}",
                "qty": int(it["quantity"]),
                #: **只是 QML 打开那一刻的初值**：勾选态的真身是下面的 `_checked`
                "checked": True,  # 原版新勾选框默认全选
            }
            for it in source_items
        ]
        self._checked: list[bool] = [True] * len(self._rows)  # 同上：默认全选
        self._check_revision = 0

    @Property(list, notify=stateChanged)
    def rows(self) -> list[dict]:
        return list(self._rows)

    #: 勾选态心跳（自增）—— 勾选**不发** `stateChanged`：发它 QML 会重读 `rows`
    #: （普通 var 列表）→ ListView 重建 → 滚动回顶
    @Property(int, notify=checkRevisionChanged)
    def checkRevision(self) -> int:
        return self._check_revision

    @Slot(int, bool)
    def setChecked(self, row: int, checked: bool) -> None:
        """勾选一行：只改勾选位 + 打心跳，**不重建 `rows`**（重建 = ListView 回顶）。"""
        if not 0 <= row < len(self._checked):
            return
        self._checked[row] = bool(checked)
        self._check_revision += 1
        self.checkRevisionChanged.emit()

    @Slot(int, result=bool)
    def isChecked(self, row: int) -> bool:
        """某行当前是否勾选 —— QML 的复选框靠它回读。"""
        if not 0 <= row < len(self._checked):
            return False
        return bool(self._checked[row])

    def selected_items(self) -> list[tuple[int, int]]:
        """勾选的 `(type_id, 数量)`；没勾任何一项返回空表（调用方据此决定要不要重填）。"""
        picked: list[tuple[int, int]] = []
        for i, row in enumerate(self._rows):
            if self._checked[i]:
                picked.append((int(row["typeId"]), int(row["qty"])))
        return picked


class HangarPickQmlDialog(QmlDialog):
    """QML 版「选择要移动的物品」。"""

    def __init__(self, source_items: list[dict], parent: Any = None) -> None:
        bridge = HangarPickBridge(source_items)
        super().__init__(_HANGAR_PICK_QML, bridge, parent=parent, size=(500, 380))
        self._pick_bridge = bridge

    def selected_items(self) -> list[tuple[int, int]]:
        return self._pick_bridge.selected_items()


# ══════════════════════════════════════════════════════════════
#  导入预览
# ══════════════════════════════════════════════════════════════


class ImportReviewBridge(DialogBridge):
    """粘贴导入预览的 QML 后端：勾选 / 改数量 / 改成本价 / 右键批量。

    **勾选态不重建行模型**（2026-09-27，照 `ui_qml/bridge/blueprint_picker_bridge.py` 的手法）：
    勾选只改行字典里的 `checked` 位，再打一次 `checkRevisionChanged` 心跳让 QML 的复选框回读；
    统计行另走 `statusChanged`。原先 `setChecked()` / `setAllChecked()` 都发 `stateChanged`，
    而它正是 `rows` 的通知信号 —— QML 那边的 `model` 是普通 var 列表（不是
    `QAbstractItemModel`）→ 行区 `Repeater` 整体重建。

    这不是「多刷一次表」那么轻：探针实测（QQuickView + 真鼠标点击），只要 `setChecked()` 仍发
    `stateChanged`，点一下复选框就把 **60/60 个行代理在它自己的 `onToggled` 处理器里同步销毁**，
    QML 当场在回读那一行报 `ReferenceError: frame is not defined`（那句踩的是已销毁对象，
    Python 侧拿到的是 `Internal C++ object already deleted`）—— 与 `pickSystem()` 记的
    qFatal 家族同源，只是这条路径上没有嵌套事件循环兜着。ListView 版的对话框（见
    `BlueprintPickerDialog.qml` 头部）还会连滚动位置一起顶回顶部。

    `stateChanged` 这条通知**不降级**：它仍是 `rows` / 模式 / 贸易中心 / 倍率的通知，
    只是不再承载勾选态（`setFinal` 改的是行里的显示口径，仍走它 —— 理由见该方法）。
    """

    #: `rows` / 模式 / 贸易中心 / 倍率的通知 —— 只在**装载 / 切模式 / 改「最终」/ 删行**时发
    stateChanged = Signal()
    #: 底部统计行（`summaryText`）—— 勾选要刷它，但**不能**顺带让 QML 重读 `rows`（= 整表重建）
    statusChanged = Signal()
    #: 勾选态心跳：QML 的每个复选框靠它把自己拉回与桥一致（全选 / 取消全选也走这条）
    checkRevisionChanged = Signal()

    #: 宿主窗口 —— 二级弹出（搜索匹配 / 选物品）与消息框都拿它当父窗口。
    #: 由宿主在 `super().__init__()` **之后**写入（同 `parent_decompose_bridge` 的做法）：
    #: 那之前 QDialog 的 C++ 对象还没建出来，把半成品 QObject 挂到别的 QObject 上会挂死。

    def __init__(
        self,
        items: list[dict],
        hangar_name: str,
        target_hangar_id: int,
        *,
        default_mode: str = "full",
        filtered_note: int = 0,
        prefetched: dict | None = None,
    ) -> None:
        super().__init__()
        self.set_title(f"导入预览 → {hangar_name}")
        self._items = merge_same_type_rows(items)  # 工作副本（同名多堆合并，见该函数）
        self._filtered_note = max(int(filtered_note or 0), 0)
        self._target_hangar_id = int(target_hangar_id)
        self._region_id = TRADE_HUB_IDS["Jita"]
        self._hub_index = 0
        self._sell_prices: dict[int, float] = {}
        self._existing_qty: dict[int, int] = {}
        #: 全量模式：目标机库的**整库**快照 `{type_id: 数量}` 与显示名 —— 反向差集要用
        #: （「库里有、剪贴板没有」= 待清零项），见 `_fetch_existing_inventory`
        self._hangar_qty: dict[int, int] = {}
        self._hangar_names: dict[int, str] = {}
        #: 后台线程预取的数据（`inventory_import_worker.build_import_preview`）——
        #: 给了就不再在主线程查库/取价，见 `_fetch_existing_inventory` / `_fetch_sell_prices`
        self._prefetched: dict | None = dict(prefetched) if prefetched else None
        self._source_hangar: dict[int, int] = {}
        self._mode = default_mode if default_mode in {value for value, _ in _MODES} else "full"
        self._discount = float(get_material_price_mult())
        #: **提交真源**：剪贴板行 + （full 模式）待清零合成行，与过滤无关。
        #: `get_import_data` / `get_sync_targets` / 汇总 / 全选 / 过滤无变化 都走它。
        self._all_rows: list[dict] = []
        #: **可见视图**：`_all_rows` 过滤后的子集（同一批 dict 对象，勾选/改值双向可见）。
        #: 行号类操作（勾选、改值、右键、删除）都按这个列表的下标。
        self._rows: list[dict] = []
        #: 「只看有变更的行」开关，默认开（用户报的「一屏几百行看不出哪几行变了」）
        self._only_changed = True
        self._summary = ""
        self._menu_rows: list[int] = []
        self._check_revision = 0

        # 预加载数据（顺序同原 `__init__`）。有预取数据时这两步都是内存读，不碰 DB。
        self._fetch_existing_inventory()
        self._fetch_sell_prices()
        self._populate_rows()

    # ── QML 读的属性 ──────────────────────────────────────────

    modes = Property(list, lambda self: [{"label": label} for _value, label in _MODES], constant=True)
    hubs = Property(
        list,
        lambda self: [{"label": f"{h} ({_HUB_NAMES[h]})"} for h in _HUB_ORDER],
        constant=True,
    )
    columns = Property(list, lambda self: [dict(c) for c in _REVIEW_COLUMNS], constant=True)
    #: 成本价 / 数量控件上限（写死不在 QML：测试要断言，也只有一个来源）
    maxPrice = Property(float, lambda self: _MAX_PRICE, constant=True)
    maxQty = Property(int, lambda self: _MAX_QTY, constant=True)
    discountMin = Property(float, lambda self: 0.1, constant=True)
    discountMax = Property(float, lambda self: 10.0, constant=True)

    rows = Property(list, lambda self: list(self._rows), notify=stateChanged)
    #: 统计行走 `statusChanged` 而不是 `stateChanged`：勾选要刷新它，但**不能**顺带让 QML
    #: 重读 `rows`（普通 var 列表，重读 = 行区整体重建），见类 docstring
    summaryText = Property(str, lambda self: self._summary, notify=statusChanged)

    @Property(bool, notify=stateChanged)
    def onlyChanged(self) -> bool:
        """「只看有变更的行」开关（默认 True）—— 只影响显示，见 `setOnlyChanged`。"""
        return self._only_changed

    @Property(int, notify=stateChanged)
    def modeIndex(self) -> int:
        return next((i for i, (value, _label) in enumerate(_MODES) if value == self._mode), 0)

    @Property(int, notify=stateChanged)
    def hubIndex(self) -> int:
        return self._hub_index

    @Property(float, notify=stateChanged)
    def discount(self) -> float:
        return self._discount

    @Property(int, notify=checkRevisionChanged)
    def checkRevision(self) -> int:
        """勾选态心跳（自增），见 `checkRevisionChanged`。"""
        return self._check_revision

    # ── QML 写回来的槽 ────────────────────────────────────────

    @Slot(int)
    def setModeIndex(self, index: int) -> None:
        """导入模式切换：整表重算（原 `_on_mode_changed`）。

        切到 full 要重取**整库**快照（反向差集用），切回 incremental 只取剪贴板涉及的
        物品 —— 所以重取放在重算之前，而不是只在 `__init__` 里取一次。
        """
        if not 0 <= index < len(_MODES):
            return
        self._mode = _MODES[index][0]
        self._fetch_existing_inventory()
        self._populate_rows()

    @Slot(int)
    def setHubIndex(self, index: int) -> None:
        """换贸易中心：重取卖单价并刷进各行成本价（原 `_on_hub_changed`）。"""
        if not 0 <= index < len(_HUB_ORDER):
            return
        self._hub_index = index
        self._region_id = TRADE_HUB_IDS.get(_HUB_ORDER[index], TRADE_HUB_IDS["Jita"])
        self._sell_prices = {}
        self._fetch_sell_prices()
        for row in self._all_rows:
            type_id = row["typeId"]
            if type_id:
                row["price"] = float(self._sell_prices.get(type_id, 0.0))
        self._update_summary()
        self.stateChanged.emit()

    @Slot(float)
    def setDiscount(self, value: float) -> None:
        """材料倍率（与生产规划页工具栏同一个设置，确认时写回）。"""
        self._discount = float(value)

    @Slot(bool)
    def setOnlyChanged(self, checked: bool) -> None:
        """「只看有变更的行」开关：**只换可见视图**，不动 `_all_rows`。

        勾选态/手改的数量都挂在同一批 row dict 上，所以隐藏/显示来回切不会丢失用户取舍；
        提交内容（`get_import_data` / `get_sync_targets`）与汇总口径也一律按 `_all_rows`，
        不会因为过滤而少提交或多报。
        """
        value = bool(checked)
        if value == self._only_changed:
            return
        self._only_changed = value
        self._rows = [r for r in self._all_rows if self._row_changed(r)] if value else list(self._all_rows)
        self._update_summary()
        self.stateChanged.emit()

    def _row_changed(self, row: dict) -> bool:
        """这一行本次导入会不会改变库存（「只看有变更的」唯一判据）。

        - 待清零合成行（`missing`，「库里有、剪贴板没有」）/ **未匹配**行 / **跨机库移动**行
          一律算「要显示」—— 前两类是本次导入的真实变更，未匹配与移动行必须让用户看见
          （认不出的行被藏起来最危险）；
        - `full`：最终数量 ≠ 机库现值（`final` 由剪贴板数量或用户手改而来）；
        - `incremental`：增量 ≠ 0（只增不减，qty>0 才有变更）。
        """
        if row.get("missing") or not row["typeId"] or row["typeId"] in self._source_hangar:
            return True
        if self._mode == "full":
            return int(row["final"]) != int(row["current"])
        return int(row["delta"]) != 0

    @Slot(int, bool)
    def setChecked(self, row: int, checked: bool) -> None:
        """勾选一行：只改勾选位 + 打心跳，**不重建 `rows`**（重建 = 整表重来，见类 docstring）。"""
        if not 0 <= row < len(self._rows) or not self._rows[row]["checkable"]:
            return
        self._rows[row]["checked"] = bool(checked)
        self._sync_checks()

    @Slot(int, result=bool)
    def isChecked(self, row: int) -> bool:
        """某行当前是否勾选 —— QML 的复选框靠它回读（全选 / 取消全选也要同步回去）。"""
        if not 0 <= row < len(self._rows):
            return False
        return bool(self._rows[row]["checked"])

    @Slot(bool)
    def setAllChecked(self, checked: bool) -> None:
        """全选 / 取消全选（未匹配行的勾选框是禁用的，跳过）—— 批量同样只打心跳。

        作用于**全部行**（含被「只看有变更的」藏起来的那些）：全选是提交语义，
        不能因为当前视图过滤而少勾。
        """
        for row in self._all_rows:
            if row["checkable"]:
                row["checked"] = bool(checked)
        self._sync_checks()

    @Slot(int, int)
    def setFinal(self, row: int, value: int) -> None:
        """「变化」列被改：重算该行增减并着色（原 `_on_final_changed`）。

        **这条仍然发 `stateChanged`（= 重建 `rows`）**：改的是行里的显示口径
        （`delta` / `deltaText` / `deltaToken` / `final`），而 QML 只从 `modelData` 读它们。
        探针实测（QTest 点上箭头 → `onValueModified` → 这里）：只改行字典 + 发 `statusChanged`
        的话，「比原纪录」列**留在旧值**（文本还是改之前那个数）；发 `stateChanged` 才跟着变，
        底部统计行则两条路都能刷。

        代价：这一行的 delegate（含刚点的那颗微调框）会在它自己的 QML 处理器里被销毁重建 ——
        与 `setRigChecked` 同形（那条要避免，因为紧接着还有一句回读，且模型重建本身在勾选这种
        连续操作里不可接受）。这里后面没有回读、也没嵌套事件循环，所以只是静默重建一次；
        给这几个字段单开一条按行的心跳（再配几个回读槽）比它值的钱贵，而这里是用户对某一行的
        **一次刻意提交**（点上箭头 / 回车 / 失焦），不是逐格勾选那种连续操作。
        """
        if not 0 <= row < len(self._rows):
            return
        target = self._rows[row]
        if target["unmatched"]:
            return
        final = int(value)
        delta = final - int(target["current"])
        target["final"] = final
        target["delta"] = delta
        target["deltaText"] = f"+{delta:,}" if delta >= 0 else f"{delta:,}"
        # 原版手改后 delta == 0 用次要色（与整表重填时的「默认前景」不同，这里照做）
        target["deltaToken"] = _delta_token(delta) or "TEXT_SECONDARY"
        self._update_summary()
        self.stateChanged.emit()

    @Slot(int, float)
    def setPrice(self, row: int, value: float) -> None:
        if not 0 <= row < len(self._rows):
            return
        self._rows[row]["price"] = float(value)
        self._update_summary()
        self.stateChanged.emit()

    @Slot(list, int, int, result=dict)
    def updateSelection(self, rows: list, row: int, anchor: int) -> dict:
        """表行选中：普通=只选它，Ctrl=切换，Shift=从锚点连选到该行（原版 QTableWidget 的语义）。

        返回 `{"rows": sorted(选中行), "anchor": 新锚点}` —— 锚点由 QML 侧持有（它是纯 UI 状态），
        但**语义算在桥里**：QML 只负责把上一步的结果原样带回来，不做任何分支。

        - Ctrl：`row` 在选中集里就摘掉、不在就加上；**锚点不动**（连选起点不该被点选打断）
        - Shift：从锚点连选到 `row`，返回**区间内的全部行号**（不与原选中集并集 —— 原版
          `QTableWidget` 在 `ExtendedSelection` 下也是这个口径）；锚点 <0 时（还没点过任何行）
          以 `row` 当锚点，于是退化成只选这一行
        - 其余：只选 `row`
        - Shift / 普通点击都把锚点更新成 `row`，Ctrl 不更新（与
          `ui_qml/bridge/inventory_bridge.py::_apply_selection` 的既有语义一致）

        修饰键从下面的 `_modifiers()` 读，不读 QML 传来的值：`FTableClickArea` 只发行列号。
        """
        if not 0 <= row < len(self._rows):
            return {"rows": sorted(int(r) for r in rows), "anchor": int(anchor)}
        modifiers = self._modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            picked = {int(r) for r in rows}
            picked.symmetric_difference_update({row})
            new_anchor = int(anchor)
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            first, last = sorted((anchor if anchor >= 0 else row, row))
            picked = set(range(first, last + 1))
            new_anchor = row
        else:
            picked = {row}
            new_anchor = row
        return {"rows": sorted(picked), "anchor": new_anchor}

    def _modifiers(self) -> Qt.KeyboardModifier:
        """当前修饰键。**留成方法是为了可测**：PySide6 的 `QGuiApplication` 是 C++ 类型，
        测试里 `monkeypatch.setattr` 它不生效（静默失败），只能从这一层注入。
        """
        return QApplication.keyboardModifiers()

    # ── 右键菜单 ──────────────────────────────────────────────

    @Slot(list)
    def openMenu(self, rows: list[int]) -> None:
        """记录菜单作用行（QML 的选中集传进来）—— 原版是读表格的 selectionModel。"""
        self._menu_rows = [int(r) for r in rows]

    @Slot(list, result=dict)
    def menuState(self, rows: list[int]) -> dict:
        """右键菜单状态（对齐 `inventory_bridge.itemMenuState` 的形状：槽返回、QML 赋给 state）。"""
        other = [h for h in get_hangars() if h["id"] != self._target_hangar_id]
        return {
            "count": len(rows),
            "single": len(rows) == 1,
            "canSearchMatch": len(rows) == 1 and self._is_unmatched(int(rows[0])),
            "hangars": [{"id": h["id"], "name": h["name"]} for h in other],
            "discountText": f"{self._discount:.0%}",
        }

    @Slot(str)
    def setPriceFromMarket(self, price_type: str) -> None:
        """右键「设置为卖价/买价/均价」：逐行取所选区域市价（原 `_batch_set_price`）。

        原 `_set_price_from_market` 的 avg 分支与 else 分支做的事完全相同（都是
        `get_price_by_region`），这里合成一条；取不到价时逐行提示，与原来一致。
        """
        repo = get_container().market_repo
        for row in self._menu_rows:
            target = self._row(row)
            if target is None or not target["typeId"]:
                continue
            price = repo.get_price_by_region(target["typeId"], price_type, self._region_id)
            if price is None:
                FMessageDialog.information(self.host_widget(), "提示", "未找到该物品在所选区域的价格数据")
            else:
                target["price"] = float(price)
        self._update_summary()
        self.stateChanged.emit()

    @Slot(str)
    def applyDiscount(self, price_type: str) -> None:
        """右键「卖价/买价 × 倍率」：先取市价再乘系数（原 disc_sell / disc_buy 分支）。"""
        self.setPriceFromMarket(price_type)
        for row in self._menu_rows:
            target = self._row(row)
            if target is not None:
                target["price"] = round(float(target["price"]) * self._discount, 2)
        self._update_summary()
        self.stateChanged.emit()

    @Slot()
    def deleteRows(self) -> None:
        """删除右键选中的行（表与数据同步删，倒序以免下标位移）。

        **合成行（`missing=True`）不对应 `_items` 里的行** —— 它们排在剪贴板行之后，
        按下标一起删会删错剪贴板行（甚至越界），所以只从 `_items` 删非合成行。
        """
        for visible_row in sorted(set(self._menu_rows), reverse=True):
            if not 0 <= visible_row < len(self._rows):
                continue
            target = self._rows[visible_row]
            # 可见下标可能被「只看有变更的」搬过 → 只能用行上记的 `itemIndex` 找 `_items`
            item_index = target.get("itemIndex")
            if item_index is not None and 0 <= item_index < len(self._items):
                del self._items[item_index]
                for row in self._all_rows:  # 后面的源下标整体左移
                    if row.get("itemIndex") is not None and row["itemIndex"] > item_index:
                        row["itemIndex"] -= 1
            self._all_rows = [r for r in self._all_rows if r is not target]
            self._rows = [r for r in self._rows if r is not target]
        self._menu_rows = []
        self._update_summary()
        self.stateChanged.emit()

    @Slot()
    def filterNoChange(self) -> None:
        """取消勾选「比原纪录」为 0 的行（原 `_filter_no_change`）。

        **保留原版的口径**：未匹配行的增量也是 "0"，它们本就未勾选、`setChecked(False)`
        是空操作，但原版照样计入「已过滤 N 项」——这里同样计入，避免文案悄悄变样。

        勾选（这里是批量取消）只走心跳、**不发 `stateChanged`** —— 它同样会让 QML 重读
        `rows`、把整张表（含右键点中的那一行）重建一遍，与 `setChecked` 是同一个缺陷。
        """
        filtered = 0
        for row in self._all_rows:  # 全部行：藏起来的「无变化」行也要一并取消勾选
            if row["delta"] != 0:
                continue
            if row["checkable"] and row["checked"]:
                row["checked"] = False
            filtered += 1
        suffix = f"  [已过滤 {filtered} 项无变化]" if filtered else ""
        self._sync_checks(suffix)

    def _sync_checks(self, suffix: str = "") -> None:
        """勾选态变化的统一出口：刷统计行 + 打心跳。**不碰 `rows`**（见类 docstring）。"""
        self._update_summary()
        if suffix:
            self._summary += suffix
            self.statusChanged.emit()
        self._check_revision += 1
        self.checkRevisionChanged.emit()

    @Slot()
    def searchMatch(self) -> None:
        """未匹配行手动搜索匹配：搜到后重取库存/市价并整表重填（原 `_search_match`）。"""
        if len(self._menu_rows) != 1:
            return
        row = self._menu_rows[0]
        if not self._is_unmatched(row):
            return

        from ui_qml.bridge.item_search_bridge import ItemSearchQmlDialog

        dlg = ItemSearchQmlDialog(self.host_widget(), title="搜索匹配物品")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sel = dlg.selected_item()
        if not sel:
            return
        # 可见下标 ≠ `_items` 下标（「只看有变更的」会过滤）→ 用行上记的 `itemIndex`
        item_index = self._rows[row].get("itemIndex") if 0 <= row < len(self._rows) else None
        if item_index is None or not 0 <= item_index < len(self._items) or self._items[item_index].get("type_id"):
            return
        self._items[item_index].update(
            {
                "type_id": sel["type_id"],
                "zh_name": sel["zh_name"],
                "en_name": sel["en_name"],
                "status": "matched",
            }
        )
        # 搜索匹配引入了新 type_id（预取快照里没有）→ 强制查库
        self._fetch_existing_inventory(prefer_prefetch=False)
        self._fetch_sell_prices()
        self._populate_rows()

    @Slot(int)
    def addFromHangar(self, source_hangar_id: int) -> None:
        """从其他机库移入：勾选后按增量语义加入列表（原 `_add_from_hangar`）。"""
        source_items = get_items(source_hangar_id)
        if not source_items:
            FMessageDialog.information(self.host_widget(), "提示", "该机库中无物品")
            return

        dlg = HangarPickQmlDialog(source_items, self.host_widget())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        added = 0
        for type_id, qty in dlg.selected_items():
            name = next((it for it in source_items if it["type_id"] == type_id), {}).get("zh_name") or ""
            self._items.append({"type_id": type_id, "zh_name": name, "en_name": "", "qty": qty})
            self._source_hangar[type_id] = source_hangar_id
            added += 1

        if added:
            # 移入的是**别的机库**的物品（预取快照里没有）→ 强制查库
            self._fetch_existing_inventory(prefer_prefetch=False)
            self._fetch_sell_prices()
            self._populate_rows()

    # ── 确认 ──────────────────────────────────────────────────

    @Slot()
    def accept(self) -> None:
        """确定导入：先校验（两个消息框），再把倍率写回共享设置。

        校验按**全部行**（过滤只影响显示）——「只看有变更的」开着时藏起来的未匹配行
        同样要提示，不能因为没显示就当作没有。
        """
        checked = [row for row in self._all_rows if row["checked"]]
        if not checked:
            FMessageDialog.warning(self.host_widget(), "提示", "没有勾选的物品，无法导入")
            return
        unmatched = sum(1 for row in checked if not row["typeId"])
        if unmatched:
            FMessageDialog.information(
                self.host_widget(),
                "提示",
                f"{unmatched} 行未匹配物品未指定 type_id，导入时将跳过（可右键搜索匹配）",
            )
        # 倍率写回共享设置（与生产规划页工具栏同一个值），下次打开仍是它
        set_material_price_mult(self._discount)
        self.accepted.emit()

    # ── 给调用方取值（名字与原版一致）────────────────────────

    def mode(self) -> str:
        """当前导入模式："incremental" 增量累加 | "full" 全量同步"""
        return self._mode

    def get_import_data(self) -> list[tuple[int, int, float, int | None]]:
        """最终导入数据 list[(type_id, delta_qty, cost_price, source_hangar_id)]。

        **按全部行**取（与是否过滤显示无关）：提交内容不能因为「只看有变更的」而变。
        """
        result: list[tuple[int, int, float, int | None]] = []
        for row in self._all_rows:
            if not row["checked"] or not row["typeId"]:
                continue
            type_id = int(row["typeId"])
            result.append((type_id, int(row["delta"]), float(row["price"]), self._source_hangar.get(type_id)))
        return result

    def get_sync_targets(self) -> dict[int, int]:
        """全量模式下 {type_id: 目标数量}；跨机库移动行不参与全量 set。**按全部行**取。"""
        targets: dict[int, int] = {}
        for row in self._all_rows:
            type_id = row["typeId"]
            if not row["checked"] or not type_id or type_id in self._source_hangar:
                continue
            targets[int(type_id)] = int(row["final"])
        return targets

    def get_clear_missing(self) -> dict[int, int]:
        """全量模式的**反向差集**（已勾选、且用户没改过「变化」列的待清零行）
        → `{type_id: 该行现有数量}`，喂给 `apply_inventory_import(..., clear_missing=...)`。

        只含勾选行 → 用户取消勾选就等于「这一项不要清零」。默认 `final=0` 即清零删行；
        用户在「变化」列把它改成 N>0 就表示「设为 N 而不是删」—— 那种行走
        `get_sync_targets()`（服务端与 `targets` 撞车时会跳过清零，见
        `apply_inventory_import`），所以这里不再列它。
        `incremental` 模式没有合成行，恒空（只增不减的语义一字不变）。
        """
        return {int(row["typeId"]): int(row["current"]) for row in self._missing_to_clear()}

    def clear_missing_text(self) -> str:
        """待清零项的确认文案（最多列 10 项）；没有待清零项时返回空串。

        由调用方（`run_clipboard_import`）拿去弹二次确认 —— 删行不可撤销，必须在
        用户点「确定导入」之后再确认一次，不能静默清库。
        """
        checked = self._missing_to_clear()
        if not checked:
            return ""
        lines = [f"  {row['name']}：现有 {int(row['current']):,} → 清零（删行）" for row in checked]
        detail = "\n".join(lines[:10])
        if len(lines) > 10:
            detail += f"\n  …等共 {len(lines)} 项"
        return (
            f"以下 {len(checked)} 项在你的机库里、但不在本次剪贴板中。\n"
            "全量同步以剪贴板为准，会把它们清零（数量归零 = 从机库删除）：\n\n"
            f"{detail}\n\n"
            "删除不可撤销。确认继续？\n"
            "（要保留某一项，请回到预览表取消它的勾选）"
        )

    def _missing_to_clear(self) -> list[dict]:
        """已勾选、目标为 0 的待清零行（`get_clear_missing` 与确认文案的唯一口径）。

        按**全部行**取 —— 清零清单与确认文案不能因为视图过滤而漏项。
        """
        return [
            row
            for row in self._all_rows
            if row.get("missing") and row["checked"] and row["typeId"] and int(row["final"]) == 0
        ]

    # ── 内部 ──────────────────────────────────────────────────

    def _row(self, index: int) -> dict | None:
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def _is_unmatched(self, index: int) -> bool:
        row = self._row(index)
        return bool(row and row["unmatched"])

    def _fetch_existing_inventory(self, *, prefer_prefetch: bool = True) -> None:
        """查询剪贴板涉及物品在目标机库里的现存量（只取基础字段）。

        `get_items` 默认还会算研究成本 / 计划占用 / 价格列，预览一个都不用 —— 走
        `include_derived=False` + `need_ids` 避免打开对话框时白算一整库。

        **全量模式例外**：反向差集要「库里有、剪贴板没有」的整份清单，`need_ids` 恰好会把
        要清零的行滤掉 —— 所以 full 模式取**整库**（仍走 `include_derived=False`），
        数量与显示名一并留下。

        **预取优先**：后台线程（`inventory_import_worker.build_import_preview`）已经把整库
        快照算好了，`prefer_prefetch=True` 时直接用内存里的那份，不在主线程查库。
        `searchMatch` / `addFromHangar` 会引入**新的** type_id（别的机库/搜索选中），
        那份快照里没有 → 它们传 `prefer_prefetch=False` 强制查库。
        """
        prefetched = self._prefetched if prefer_prefetch else None
        try:
            need = {int(it["type_id"]) for it in self._items if it.get("type_id")}
            if prefetched:
                self._existing_qty.update({int(k): int(v) for k, v in prefetched["existing_qty"].items()})
                self._hangar_qty = {int(k): int(v) for k, v in prefetched["existing_qty"].items()}
                self._hangar_names = {int(k): str(v) for k, v in prefetched["hangar_names"].items()}
                for tid in need:
                    self._existing_qty.setdefault(tid, 0)
                return
            if self._mode == "full":
                items = get_items(self._target_hangar_id, include_derived=False)
                self._hangar_qty = {int(it["type_id"]): int(it["quantity"]) for it in items}
                self._hangar_names = {int(it["type_id"]): item_display_name(it) for it in items}
                for tid, qty in self._hangar_qty.items():
                    self._existing_qty[tid] = qty
                for tid in need:  # 剪贴板里有、库里没有 → 现存量 0
                    self._existing_qty.setdefault(tid, 0)
                return
            self._hangar_qty = {}
            self._hangar_names = {}
            for it in get_items(self._target_hangar_id, include_derived=False, need_ids=need):
                self._existing_qty[it["type_id"]] = it["quantity"]
        except Exception:
            log.exception("获取现有库存失败")

    def _fetch_sell_prices(self) -> None:
        """预加载所有物品在当前贸易中心的卖单价（预取数据优先，见 `_fetch_existing_inventory`）。"""
        if self._prefetched:
            self._sell_prices = {int(k): float(v) for k, v in self._prefetched["sell_prices"].items()}
            return
        type_ids = list({it["type_id"] for it in self._items if it.get("type_id")})
        if not type_ids:
            return
        self._sell_prices = get_container().market_repo.get_sell_prices(type_ids, self._region_id)

    def _populate_rows(self) -> None:
        """按当前模式 / 库存 / 市价重算所有行（原 `_populate_rows`）。

        原版在这里重建整张表：勾选全部回到 True、手改的数量与价格被市价覆盖。
        `_on_mode_changed` 与「搜索匹配」都依赖这一重置行为，故照做。

        **全量模式**在剪贴板行之后追加「库里有、剪贴板没有」的**待清零行**
        （`missing_row`，默认勾选）—— 这是本缺陷的修复点：原先这些行既不在 `data`
        也不在 `targets` 里，于是永远不动、数量原样残留。
        """
        rows: list[dict] = []
        for index, item in enumerate(self._items):
            # 未匹配行的 type_id 是 None —— 归一到 0 只为了查表（`existing_qty` / `source_hangar`
            # 里不会有 0 号物品），行的分支由 `review_row` 按 type_id 真假决定
            tid = int(item["type_id"]) if item.get("type_id") else 0
            # 跨机库移动行始终按增量语义（不参与全量 set）；其余按当前导入模式
            row_mode = "incremental" if tid in self._source_hangar else self._mode
            row = review_row(
                item,
                current=self._existing_qty.get(tid, 0),
                sell_price=self._sell_prices.get(tid, 0.0),
                mode=row_mode,
                source_hangar_id=self._source_hangar.get(tid),
            )
            # 行号类操作（右键搜索匹配 / 删除）要能找回 `_items` 里的源行 ——
            # 「只看有变更的」开着时可见下标 ≠ `_items` 下标，不能再按下标硬对。
            row["itemIndex"] = index
            rows.append(row)
        if self._mode == "full":
            clipboard_ids = {int(it["type_id"]) for it in self._items if it.get("type_id")}
            for tid, qty in compute_missing_in_hangar(self._hangar_qty, clipboard_ids).items():
                rows.append(
                    missing_row(
                        tid,
                        self._hangar_names.get(tid, f"ID:{tid}"),
                        qty,
                        self._sell_prices.get(tid, 0.0),
                    )
                )
        self._all_rows = rows
        self._rebuild_visible_rows()
        self._update_summary()
        self.stateChanged.emit()

    def _rebuild_visible_rows(self) -> None:
        """按开关重算可见视图（`_only_changed` 关 → 全部行；开 → 只留有变更的）。"""
        self._rows = [r for r in self._all_rows if self._row_changed(r)] if self._only_changed else list(self._all_rows)

    def _update_summary(self) -> None:
        """统计行（原 `_update_summary`，含「已过滤 N 行蓝图」前缀）。

        自己发 `statusChanged`（而不是让每个调用点记着发）：这条通知**不带着 `rows` 一起变**
        （见类 docstring），漏发的表现是统计行停在上一次的数字上。
        """
        checked = 0
        total_delta = 0
        total_value = 0.0
        for row in self._all_rows:
            if not row["checked"]:
                continue
            checked += 1
            total_delta += int(row["delta"])
            total_value += float(row["price"]) * int(row["delta"])
        text = (
            f"已勾选 {checked} 项 / 总计 {len(self._all_rows)} 项 / "
            f"总增减 {total_delta:,} / 预估成本 {total_value:,.0f} ISK"
        )
        if self._only_changed:
            hidden = len(self._all_rows) - len(self._rows)
            if hidden:
                text += f"  ｜ 已隐藏 {hidden} 行无变化（取消勾选「只看有变更的行」可核对）"
        if self._mode == "full":
            missing = sum(1 for row in self._all_rows if row.get("missing"))
            if missing:
                text += f"  ｜ 全量同步：库里有 {missing} 项不在剪贴板中，勾选后将清零（默认勾选，可取消）"
        if self._filtered_note:
            text = f"[已过滤 {self._filtered_note} 行蓝图] {text}"
        self._summary = text
        self.statusChanged.emit()


class ImportReviewQmlDialog(QmlDialog):
    """QML 版「粘贴导入预览」。

    `ImportReviewDialog(items, hangar_name, target_hangar_id, parent, default_mode=…, filtered_note=…)`
    的调用方原样可用。
    """

    def __init__(
        self,
        items: list[dict],
        hangar_name: str,
        target_hangar_id: int,
        parent: Any = None,
        *,
        default_mode: str = "full",
        filtered_note: int = 0,
        prefetched: dict | None = None,
    ) -> None:
        bridge = ImportReviewBridge(
            items,
            hangar_name,
            target_hangar_id,
            default_mode=default_mode,
            filtered_note=filtered_note,
            prefetched=prefetched,
        )
        super().__init__(_REVIEW_QML, bridge, parent=parent, size=(900, 560))
        # 桥的 `dialog` 必须在 `super().__init__()` **之后**才写：那之前 QDialog 的
        # C++ 对象还没建出来，挂上去会挂死（同 `parent_decompose_bridge` 的踩坑记录）
        self._review_bridge = bridge

    def mode(self) -> str:
        return self._review_bridge.mode()

    def get_import_data(self) -> list[tuple[int, int, float, int | None]]:
        return self._review_bridge.get_import_data()

    def get_sync_targets(self) -> dict[int, int]:
        return self._review_bridge.get_sync_targets()

    def get_clear_missing(self) -> dict[int, int]:
        """全量模式下「库里有、剪贴板没有」的勾选项 → {type_id: 目标数量（0=清零）}。"""
        return self._review_bridge.get_clear_missing()

    def clear_missing_text(self) -> str:
        """待清零项的确认文案；无待清零项时为空串。"""
        return self._review_bridge.clear_missing_text()


# ══════════════════════════════════════════════════════════════
#  导入完成变动汇总
# ══════════════════════════════════════════════════════════════


class ImportChangeBridge(SummaryTableBridge):
    """导入完成后的变动汇总 —— 只读表 + 汇总行（复用汇总表骨架，本类只负责算）。"""

    def __init__(self, changes: list[dict], added: int, moved: int, hangar_name: str) -> None:
        super().__init__(title=f"导入完成 — {hangar_name}", columns=[dict(c) for c in _CHANGE_COLUMNS])
        self._changes = list(changes)
        self._summary = change_summary(self._changes, int(added), int(moved))
        self.set_empty_text("数量/成本均无变化" if not self._changes else "没有数据")

    @Slot()
    def reload(self) -> None:
        # 汇总文案放说明行（`headerText`）；状态行留空 —— 原版就是把汇总放在表格上方
        self.set_content(change_rows(self._changes), "", self._summary)


class ImportChangeQmlDialog(SummaryTableQmlDialog):
    """QML 版「导入完成变动汇总」。`ImportChangeDialog(changes, added, moved, hangar_name, parent)` 原样可用。"""

    def __init__(
        self,
        changes: list[dict],
        added: int,
        moved: int,
        hangar_name: str,
        parent: Any = None,
    ) -> None:
        super().__init__(
            ImportChangeBridge(changes, added, moved, hangar_name),
            parent=parent,
            size=(620, 460),
            qml_file=_CHANGE_QML,
        )


# ══════════════════════════════════════════════════════════════
#  剪贴板导入正式编排（仓库 / 采购共用）
# ══════════════════════════════════════════════════════════════


def _set_busy(on: bool) -> None:
    """忙碌光标（非阻塞反馈）。

    解析/取数/落库都在后台线程跑，主线程只等结果 —— 光标是「正在算」的可见信号，
    不弹模态框、不用 `processEvents()` 硬撑。用引用计数避免嵌套调用提前复位。
    """
    global _BUSY_DEPTH
    if on:
        _BUSY_DEPTH += 1
        if _BUSY_DEPTH == 1:
            QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        return
    _BUSY_DEPTH = max(_BUSY_DEPTH - 1, 0)
    if _BUSY_DEPTH == 0:
        QApplication.restoreOverrideCursor()


def _wait_worker(worker: InventoryImportFetchWorker | InventoryImportApplyWorker, parent: Any, what: str) -> Any:
    """起线程 + 嵌套事件循环等它结束，返回结果（`None` = 失败，已弹提示）。

    **不是 `processEvents()` 硬撑**：`QEventLoop.exec()` 期间 UI 照常重绘、定时器照常跑，
    只是本函数要到 worker 结束才返回 —— 调用方（`inventory_bridge` / `procurement_tab`）
    依赖 `run_clipboard_import` 同步返回后刷新列表，所以保持返回时机不变。
    `_ACTIVE_WORKERS` 是强引用保活（调用方传的 `parent` 可能是 `None`，见
    `inventory_bridge.runClipboardImport`）。
    """
    loop = QEventLoop()
    result: dict[str, Any] = {}

    def _done(payload: dict) -> None:
        result["payload"] = payload
        loop.quit()

    def _failed(message: str) -> None:
        result["error"] = message
        loop.quit()

    worker.finished_signal.connect(_done)
    worker.error_signal.connect(_failed)
    worker.finished.connect(loop.quit)  # worker 线程异常退出兜底，别把主线程挂死
    _ACTIVE_WORKERS.add(worker)
    try:
        worker.start()
        loop.exec()
    finally:
        _ACTIVE_WORKERS.discard(worker)
        worker.wait(5000)
    if "error" in result:
        FMessageDialog.warning(parent, "导入失败", f"{what}失败：{result['error']}\n（详见日志，库存未被修改）")
        return None
    if "payload" not in result:
        FMessageDialog.warning(parent, "导入失败", f"{what}未完成（后台线程异常退出），库存未被修改")
        return None
    return result["payload"]


def run_clipboard_import(
    target_hangar_id: int,
    hangar_name: str,
    parent: Any,
    *,
    mode: str = "incremental",
) -> None:
    """读剪贴板 → **后台**解析/取数 → 导入预览 → **后台**落库/算差异 → 变动汇总。

    仓库/采购共用入口。剪贴板为空 / 无有效行 / 用户取消 → 静默返回；蓝图行被过滤
    （材料仓库只导入材料），全部被过滤时提示一次。

    **全量同步是以剪贴板为准的双向比对**：预览行里除了剪贴板物品，还追加「库里有、
    剪贴板没有」的待清零行（默认勾选、可取消），并做一次二次确认（`default_yes=False`）
    才落库 —— 单向 set 会让上一份清单里的物品永久残留（用户报的「库里没有那 6 个电池」）。

    **耗时活全在 worker 线程**（`ui_qml/workers/inventory_import_worker.py`）：解析剪贴板、
    整库快照、整仓卖价、落库、导入后快照与差异对比。主线程只弹两个对话框 + 忙碌光标 ——
    用户报的「库存修正导致整个软件卡死」就是这么消掉的。

    **重入挡掉**：本函数会写用户库存，而等待 worker 时用的是嵌套事件循环（理论上期间可被
    再次触发）→ 已在导入中就直接提示并返回，绝不套第二个事件循环、更不会写两遍。
    """
    global _IMPORT_IN_FLIGHT
    if _IMPORT_IN_FLIGHT:
        FMessageDialog.information(parent, "提示", "正在导入库存，请稍候……")
        return
    _IMPORT_IN_FLIGHT = True
    try:
        _run_clipboard_import(target_hangar_id, hangar_name, parent, mode=mode)
    finally:
        _IMPORT_IN_FLIGHT = False


def _run_clipboard_import(
    target_hangar_id: int,
    hangar_name: str,
    parent: Any,
    *,
    mode: str,
) -> None:
    """`run_clipboard_import` 的实际流程（重入守卫的 `try/finally` 之外，见那边 docstring）。"""
    clipboard = QApplication.clipboard()
    raw = clipboard.text().strip() if clipboard is not None else ""
    if not raw:
        FMessageDialog.warning(parent, "提示", "剪贴板为空，请先在游戏中复制物品（Ctrl+C）")
        return

    _set_busy(True)
    try:
        payload = _wait_worker(InventoryImportFetchWorker(raw, target_hangar_id, parent), parent, "解析剪贴板")
    finally:
        _set_busy(False)
    if payload is None:
        return
    parsed = payload["parsed"]
    filtered = payload["filtered"]
    if not parsed:
        if filtered:
            FMessageDialog.information(
                parent,
                "提示",
                f"剪贴板中的 {filtered} 行都是蓝图，材料仓库只导入材料，已全部过滤",
            )
        return

    # 预览所需的现存量/整库快照/卖价都是 worker 预取的，这里不再查库
    dlg = ImportReviewQmlDialog(
        parsed,
        hangar_name,
        target_hangar_id,
        parent,
        default_mode=mode,
        filtered_note=filtered,
        prefetched=payload,
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    data = dlg.get_import_data()
    actual_mode = dlg.mode()
    # 全量同步的反向差集：用户取消勾选的项不进这里；incremental 恒空（只增不减）
    clear_missing = dlg.get_clear_missing() if actual_mode == "full" else {}
    if not data and not clear_missing:
        return
    if clear_missing and not FMessageDialog.question(
        parent, "全量同步 — 清零确认", dlg.clear_missing_text(), default_yes=False
    ):
        # 删行不可撤销：用户点「否」→ 一行都不写
        return
    targets = dlg.get_sync_targets() if actual_mode == "full" else None

    _set_busy(True)
    try:
        result = _wait_worker(
            InventoryImportApplyWorker(
                target_hangar_id,
                data,
                actual_mode,
                targets,
                clear_missing or None,
                payload["before"],
                payload["names_before"],
                parent,
            ),
            parent,
            "写入库存",
        )
    finally:
        _set_busy(False)
    if result is None:
        return
    ImportChangeQmlDialog(result["changes"], result["added"], result["moved"], hangar_name, parent).exec()


# ══════════════════════════════════════════════════════════════
#  钱包交易记录导入（仓库 / 采购共用）
# ══════════════════════════════════════════════════════════════


def _hangar_choices(default_hangar_id: int | None) -> tuple[list[str], list[int], int]:
    """机库下拉的 (标签, id, 默认下标)。标签口径与 `inventory_bridge._reload_hangars` 一致。"""
    from services.name_resolver import resolve_system_display_names_batch

    hangars = get_hangars()
    systems = resolve_system_display_names_batch([h["solar_system_id"] for h in hangars if h.get("solar_system_id")])
    labels: list[str] = []
    for hangar in hangars:
        sid = hangar.get("solar_system_id")
        labels.append(f"{hangar['name']} ({systems[sid]})" if sid in systems else str(hangar["name"]))
    ids = [int(h["id"]) for h in hangars]
    index = ids.index(int(default_hangar_id)) if default_hangar_id in ids else 0
    return labels, ids, index


def _purchase_summary(imported: int, unmatched: int, stats: dict) -> str:
    """导入结果一行汇总 —— **跳过项都要报数**，不然用户以为全进去了。"""
    parts = [f"已入库 {imported} 项"]
    if unmatched:
        parts.append(f"{unmatched} 条物品名未匹配已跳过")
    if stats.get("sales"):
        parts.append(f"{stats['sales']} 条卖出行已跳过")
    if stats.get("unparsed"):
        parts.append(f"{stats['unparsed']} 行认不出已跳过")
    return "，".join(parts)


def choose_hangar(default_hangar_id: int | None, parent: Any) -> tuple[int, str] | None:
    """现选一个入库机库 → `(机库 id, 下拉里那个显示名)`；没有机库 / 用户取消 → None。

    默认预选 `default_hangar_id`（取不到就是第一项）。「仓库管理」与「采购小助手」的
    入库入口共用它 —— 各写一份就会出现「一个入口让你选机库、另一个直接塞进默认机库」，
    新建的机库在后者里根本没得选（用户 2026-10-06 报）。标签口径见 `_hangar_choices`。
    """
    labels, ids, index = _hangar_choices(default_hangar_id)
    if not ids:
        FMessageDialog.warning(parent, "提示", "还没有机库，请先在「机库设置」里建一个")
        return None
    from ui_qml.bridge.input_dialog import InputQmlDialog

    name, ok = InputQmlDialog.get_item(parent, "入库机库", "目标机库:", labels, index)
    if not ok or name not in labels:
        return None
    return ids[labels.index(name)], name


def run_purchase_import(default_hangar_id: int | None, parent: Any) -> str | None:
    """读剪贴板里的「钱包 → 交易记录」→ 选机库 → 按粘贴的单价入库。仓库/采购共用入口。

    只吃**金额为负**的行（你付出 ISK = 买入）；卖出（正）与认不出的行统计后跳过。
    成本按记录里的**单价**写入，同物品多行进 `add_item` 加权平均（`apply_inventory_import`
    整批一个事务，失败整体回滚）。

    Returns:
        一行汇总文案；剪贴板为空 / 一条买入行都没有 / 用户取消机库选择 → None
        （前两种已弹提示）。
    """
    raw = QApplication.clipboard().text().strip()
    if not raw:
        FMessageDialog.warning(parent, "提示", "剪贴板为空，请先在游戏「钱包 → 交易记录」里 Ctrl+A/C 复制购买记录")
        return None
    rows, stats = parse_purchase_clipboard(raw)
    if not rows:
        FMessageDialog.information(parent, "提示", _purchase_summary(0, 0, stats))
        return None

    chosen = choose_hangar(default_hangar_id, parent)
    if chosen is None:
        return None
    hangar_id, _label = chosen

    matched = [r for r in rows if r.get("type_id")]
    data: list[tuple[int, int, float, int | None]] = [
        (int(r["type_id"]), int(r["qty"]), float(r["unit_price"]), None) for r in matched
    ]
    if data:
        apply_inventory_import(hangar_id, data, "incremental")
    return _purchase_summary(len(matched), len(rows) - len(matched), stats)
