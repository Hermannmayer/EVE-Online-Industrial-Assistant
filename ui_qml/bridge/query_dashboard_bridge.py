"""物品查询页 · 空闲态仪表盘的桥（第 3 步）。

四块内容，全部同步取数（**构造期不起任何线程**，硬约束见
`ui_qml/bridge/query_bridge.py:221-237`：桥一旦生命周期短，线程还没结束进程就退不出去）：

1. **产线详情** `occupancyRows()` —— 与 `LauncherBridge.occupancyRows` **同形状**
   （键名 `name`，不是 `charName`），QML 直接喂给 `components/FCapacityRow.qml`。
   算法复刻 `ui_qml/views/industry/production_launcher.py::_refresh_occupancy`
   （该文件被另一会话占用，**只读不改**），底层同样是
   `services.char_capacity.active_lines_by_category` + `max_lines_for_category`。
   `nameWidth` 是个例外：原实现用 `QFontMetrics` 量文字宽度，本面板固定 `76`
   （`FCapacityRow.qml` 的 `nameWidth` 默认值）—— 桥里量字体需要 `QGuiApplication`，
   而本桥在无 GUI 的测试里也要能跑。
   另有 `quickRows` 给出「可启动 / 可下线」快捷行，`quickAction(index)` 执行
   （**确认框在桥里弹**，走 `FMessageDialog.question`，与 `char_settings_bridge` 同口径）。

2. **资产折线图** `assetPlot` / `assetSeries` —— 数据源 `services.asset_snapshot_service`。
   几何全部复用 `ui_qml/bridge/price_chart_bridge.py` 的纯函数
   （`nice_range` / `axis_values` / `map_values` / `pick_indices`），与 `plot_model` 同口径：
   x 按**下标均分**，y 用**筛选后可见线**的合并最值，下界**不贴 0**
   （资产不从 0 起，贴 0 会把波动压平）。颜色在 **Python 侧**算好（过
   `ensure_contrast`）随 `series[].color` 一起下发 —— QML 不准自己读 `Theme` 取折线色。

3. **资产表** `assetSummaryRows` —— 4 行「最新值 + 相对区间首点的变化量/百分比」。

4. **挂单列表** `openOrderRows` / `readOrders` / `pendingReview` / `dropStaleOrders` ——
   读游戏内「钱包 → 订单 → 导出」写出的本地文件（`Documents\\EVE\\logs\\Marketlogs\\`），
   解析走 `services.order_export`，落 `user.db.open_orders`（`INSERT OR REPLACE`，order_id
   主键 → 重复导入幂等），并回写一条资产快照。**过期行不自动删**：`pendingReview()` 交给
   QML 弹确认框，用户点头才 `dropStaleOrders()`。

刷新生命周期：**本桥不自建定时器**。QML 空闲态可见时调一次 `refresh()`，另有一个只在
可见时运行的 60s `Timer` 也调它 —— 因此 `refresh()` 必须幂等且便宜：先算一份
「计划字段集 + 机库库存 + 角色技能 + 快照/挂单行数 + 本桥本地状态」的指纹，
**指纹没变就直接返回，不重算、不发 `changed`**（照抄 `industry_view.py` 的材料状态刷新思路）。
指纹本身要读一次计划与库存（那已经是最便宜的一档），变与不变都只走这一档；
只有变了才做逐条 pending 计划的评分（材料缺口）与几何重算。

**数据一律 `Property`，动作才是 `Slot`**：QML 的绑定不追踪 Slot 内部的属性读取，
把 `occupancyRows` / `assetPlot` 这类数据写成 Slot 调用，面板就不会随 `changed` 刷新
（本仓既有教训，见 `query_bridge.py` 的 `sortColumn` 注释）。
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWidgets import QWidget

import ui_qml.theme.registry as theme
from core.container import get_container
from core.logger import log
from domain.theme_contrast import ensure_contrast
from services import plan_execution
from services.char_capacity import (
    CAPACITY_LINE_MANUFACTURING,
    CAPACITY_LINE_REACTION,
    CAPACITY_LINE_RESEARCH,
    active_lines_by_category,
    line_label,
    max_lines_for_category,
)
from services.char_config_resolver import get_character_list, load_all_data
from services.plan_service import load_plans_for_wizard
from services.plan_start_check import plan_start_block
from services.user_settings import load_settings, save_settings
from ui_qml.bridge.message_dialog import FMessageDialog
from ui_qml.bridge.price_chart_bridge import axis_values, map_values, nice_range, pick_indices
from ui_qml.bridge.summary_dialog import cell

__all__ = [
    "QueryDashboardBridge",
    "asset_plot",
    "format_axis_value",
    "parse_amount",
    "range_window",
    "split_series",
    "trim_from",
]

# ── 产线详情（与生产启动小助手同口径）─────────────────────────
_LINE_TYPES = (CAPACITY_LINE_MANUFACTURING, CAPACITY_LINE_RESEARCH, CAPACITY_LINE_REACTION)
_LINE_COLORS = {
    CAPACITY_LINE_MANUFACTURING: "ACCENT_GREEN",
    CAPACITY_LINE_RESEARCH: "ACCENT_CYAN",
    CAPACITY_LINE_REACTION: "ACCENT_PURPLE",
}
#: 角色名列宽。原实现按字体量宽（`QFontMetrics`），本面板固定为
#: `FCapacityRow.qml` 的 `nameWidth` 默认值 76 —— 量字体要 `QGuiApplication`，
#: 而桥要能在无 GUI 的测试里跑。
_NAME_W = 76

# ── 资产折线 ────────────────────────────────────────────────
#: (key, 中文标签, 主题色 token)。四条线的颜色**不新增 token**，只复用现有强调色。
_SERIES: tuple[tuple[str, str, str], ...] = (
    ("total", "总资产", "PRIMARY"),
    ("orders", "挂单金额", "ACCENT_GREEN"),
    ("inventory", "库存材料", "ACCENT_ORANGE"),
    ("wallet", "钱包余额", "ACCENT_YELLOW"),
)
_MAX_X_TICKS = 6
_MAX_Y_TICKS = 5
#: 「总」档的取数天数（10 年，等价于「全部历史」）
_RANGE_ALL_DAYS = 3650
_RANGE_LABELS: tuple[str, ...] = ("近 7 天", "本月", "本年", "总")
_RANGE_ALL_INDEX = 3
#: 折线图空态：QML 只看 `isEmpty`
_EMPTY_PLOT: dict = {"isEmpty": True, "count": 0, "series": [], "xTicks": [], "yTicks": []}
#: 空态占位文案。**必须写清「从首次记录开始累积」**：本功能刚上线时只有零星几个点，
#: 不写用户会以为坏了。
_EMPTY_ASSET_TEXT = "还没有资产快照 —— 数据从首次记录开始按天累积，导入一次挂单或填写钱包余额即可记下今天这一天。"

# ── 快捷产线 ────────────────────────────────────────────────
_QUICK_LIMIT = 8
#: 最多评估多少条 pending 候选（每条候选要跑一次材料缺口评分，扫描无上限会把
#: 主线程拖住；超过这一档的候选只能等用户在计划表里处理）。
_QUICK_SCAN_LIMIT = 32
#: 「软阻塞」= 缺料 / 蓝图流程不足：仍给可点的「启动」（与产线小助手同口径，
#: 见 `docs/dev/ui-blueprint.md` 的「缺料是软阻塞」），其余阻塞直接不给。
_SOFT_BLOCKS = frozenset({"material_short", "blueprint_short"})
#: 软阻塞的短标签（与 `production_launcher._BLOCK_SHORT_LABELS` 同文案）。
#: 不直接 import 那张表：那个模块属于另一个工作流、而且拉起来就是一整扇窗口。
_SOFT_BLOCK_TEXT = {"material_short": "材料不够", "blueprint_short": "缺蓝图"}

# ── 挂单 ────────────────────────────────────────────────────
_ORDER_HEADS_LIST: tuple[str, ...] = ("订单ID", "物品", "方向", "价格", "剩余/总量", "位置")
_ORDER_DB_COLUMNS: tuple[str, ...] = (
    "order_id",
    "is_buy",
    "price",
    "volume_total",
    "volume_remain",
    "location_id",
    "location_name",
    "type_id",
    "type_name",
    "issued",
    "duration",
    "imported_at",
)
_TOKEN_PLAIN = "TEXT_PRIMARY"
_TOKEN_BUY = "ACCENT_GREEN"
_TOKEN_SELL = "ACCENT_RED"
_SETTING_EXPORT_DIR = "order_export_dir"
_DEFAULT_EXPORT_DIR_TEXT = "默认目录（我的文档\\EVE\\logs\\Marketlogs）"
_EMPTY_ORDER_SUMMARY = "暂无挂单记录，点「读取订单」从游戏「钱包 → 订单」的导出文件导入"

#: 惰性导入失败只提示一次（每 60s 刷一次也不刷屏）
_MISSING_LOGGED: set[str] = set()


# ════════════════════════════════════════════════════════════
#  惰性服务入口（并行工作流交付，缺失时不崩）
# ════════════════════════════════════════════════════════════


def _asset_svc() -> Any | None:
    """`services.asset_snapshot_service`（缺失返回 None）。"""
    try:
        from services import asset_snapshot_service
    except ImportError:
        if "asset_snapshot_service" not in _MISSING_LOGGED:
            _MISSING_LOGGED.add("asset_snapshot_service")
            log.warning("services.asset_snapshot_service 不可用：资产折线图与快照将为空")
        return None
    return asset_snapshot_service


def _order_svc() -> Any | None:
    """`services.order_export`（缺失返回 None）。"""
    try:
        from services import order_export
    except ImportError:
        if "order_export" not in _MISSING_LOGGED:
            _MISSING_LOGGED.add("order_export")
            log.warning("services.order_export 不可用：挂单导入已停用")
        return None
    return order_export


def _complete_one_plan(parent: Any, plan: dict) -> dict | None:
    """单行下线入口（惰性导入；`ui_qml.views.industry` 会拉起 QtWidgets 与若干桥）。

    直接复用 `ui_qml/views/industry/complete_plans_dialog.py::complete_one_plan`：
    它自带产出机库选择与失败告警，返回 None = 用户取消或已弹过失败提示
    （**不能当成失败结果**去改本地状态）。
    """
    from ui_qml.views.industry.complete_plans_dialog import complete_one_plan

    return complete_one_plan(parent, plan)


def _user_conn() -> Any:
    """user.db 连接上下文（测试替换点）。"""
    return get_container().db.connect("user")


def _configured_export_dir() -> str:
    """`settings.json` 里的自定义订单导出目录（空串 = 用游戏默认目录）。"""
    try:
        return str(load_settings().get(_SETTING_EXPORT_DIR, "") or "").strip()
    except Exception:
        log.exception("读取订单导出目录失败")
        return ""


# ════════════════════════════════════════════════════════════
#  纯函数（可脱离 Qt 单测）
# ════════════════════════════════════════════════════════════


def _as_float(value: Any) -> float:
    """尽力转 float（容忍千分位/空格/下划线），失败给 0.0。"""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("_", "").replace(" ", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _as_int(value: Any) -> int:
    return int(_as_float(value))


def _as_buy(value: Any) -> bool:
    """买/卖标记 → bool（解析器给 bool / 0·1 / "buy"·"买" 都认）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "buy", "买", "买单", "yes"}


def format_axis_value(value: float) -> str:
    """金额刻度文案：按量级自适应单位（K/M/B，如 `1.23B`）。

    对应标注图里的「金额（根据筛选的金额自适应单位和刻度）」——轴上限可能从几千块
    跳到上亿，固定 `,.0f` 会把刻度写成一长串数字、挤掉绘图区。
    """
    magnitude = abs(float(value))
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if magnitude >= limit:
            return f"{value / limit:.2f}".rstrip("0").rstrip(".") + suffix
    return f"{value:,.0f}"


def parse_amount(text: Any) -> float | None:
    """用户手填的金额文本 → float；非法/空给 None（调用方据此给中文提示）。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    cleaned = raw.replace(",", "").replace("_", "").replace(" ", "").replace("isk", "").replace("ISK", "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def range_window(index: int, today: date | None = None) -> tuple[int, date | None]:
    """区间档位 → (向 `load_series` 要的天数, 裁剪起点)。

    「本月」「本年」按**自然月/自然年起点**裁，不是「最近 N 天」——
    起点日期一并返回，由 `trim_from` 再切一刀，免得依赖 `load_series` 的
    边界口径（含不含今天）与这里猜的一致。
    """
    ref = today or date.today()
    if index == 0:
        return 7, ref - timedelta(days=6)
    if index == 1:
        start = ref.replace(day=1)
        return (ref - start).days + 1, start
    if index == 2:
        start = ref.replace(month=1, day=1)
        return (ref - start).days + 1, start
    return _RANGE_ALL_DAYS, None


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def trim_from(rows: Sequence[Mapping[str, Any]], start: date | None) -> list[Mapping[str, Any]]:
    """裁掉早于 `start` 的行；日期解析不出来的行**保留**（宁可多画一个点）。"""
    if start is None:
        return list(rows)
    kept: list[Mapping[str, Any]] = []
    for row in rows:
        parsed = _parse_date(row.get("date"))
        if parsed is None or parsed >= start:
            kept.append(row)
    return kept


def split_series(rows: Sequence[Mapping[str, Any]]) -> tuple[list[str], dict[str, list[float]]]:
    """快照行 → (日期列表, {线 key: 值列表})。非 Mapping / 值非数字一律按 0 补齐。"""
    dates: list[str] = []
    values: dict[str, list[float]] = {key: [] for key, _label, _token in _SERIES}
    for entry in rows:
        if not isinstance(entry, Mapping):
            continue
        dates.append(str(entry.get("date", "")))
        for key, _label, _token in _SERIES:
            values[key].append(_as_float(entry.get(key)))
    return dates, values


def asset_plot(
    rows: Sequence[Mapping[str, Any]],
    visible: Mapping[str, bool],
    colors: Mapping[str, str] | None = None,
) -> dict:
    """资产快照 → 画布模型（纯函数）。

    形状与 `price_chart_bridge.plot_model` 同族：
        {isEmpty, count,
         series: [{label, key, color, points: [{x, y}]}],
         xTicks / yTicks: [{pos, label}]}

    - `series` **只含当前可见的线**，y 轴量程也只看这些线 —— 切换显示时刻度会跟着变，
      这是刻意行为（用户点掉「钱包余额」后不该被它的数量级压扁其它线）。
    - x 按**下标均分**（与 `plot_model` 同口径：快照是逐日的，按日期算还要处理缺日）。
    - 下界**不贴 0**：资产不从 0 起，贴 0 会把日常波动压成一条直线。
    """
    palette = dict(colors or {})
    dates, values = split_series(rows)
    count = len(dates)
    if count == 0:
        return dict(_EMPTY_PLOT)

    shown = [key for key, _label, _token in _SERIES if visible.get(key, True)]
    if not shown:  # 兜底：全关时按全可见画（正常路径由 toggle_series 拦住最后一次关闭）
        shown = [key for key, _label, _token in _SERIES]

    merged = [value for key in shown for value in values[key]]
    lo, hi, step = nice_range(min(merged), max(merged), _MAX_Y_TICKS)

    xs = [i / (count - 1) if count > 1 else 0.5 for i in range(count)]
    series: list[dict] = []
    for key, label, _token in _SERIES:
        if key not in shown:
            continue
        ys = map_values(values[key], lo, hi)
        series.append(
            {
                "label": label,
                "key": key,
                "color": palette.get(key, ""),
                "points": [{"x": x, "y": y} for x, y in zip(xs, ys, strict=True)],
            }
        )

    tick_values = axis_values(lo, hi, step)
    return {
        "isEmpty": False,
        "count": count,
        "series": series,
        "xTicks": [{"pos": xs[i], "label": dates[i]} for i in pick_indices(count, _MAX_X_TICKS)],
        "yTicks": [
            {"pos": pos, "label": format_axis_value(value)}
            for value, pos in zip(tick_values, map_values(tick_values, lo, hi), strict=True)
        ],
    }


# ════════════════════════════════════════════════════════════
#  桥
# ════════════════════════════════════════════════════════════


class QueryDashboardBridge(QObject):
    """物品查询页空闲态仪表盘的后端。"""

    #: 单一通知源：所有 `notify` 都挂它（QML 侧一次重读全部属性）
    changed = Signal()

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        #: 外壳（弹确认框时当 parent，口径同 `query_bridge.openAllItems`）
        self._shell = shell
        # ⚠️ 构造期不起任何线程、也不查库：属性第一次被读时才做一次惰性加载
        #    （见 `_ensure_orders` / `_ensure_wallet`），刷新由 QML 的空闲态驱动。
        self._plans: list[dict] = []
        self._occupancy_rows: list[dict] = []
        self._occupancy_by_line: list[dict] = []
        self._occupancy_summary = ""
        self._quick_rows: list[dict] = []
        self._series_rows: list[dict] = []  # 当前区间内的快照行
        self._all_series_rows: list[dict] = []  # 全量快照行（切区间时不重查）
        self._plot: dict = dict(_EMPTY_PLOT)
        self._visible: dict[str, bool] = {key: True for key, _label, _token in _SERIES}
        self._range_index = 0
        self._wallet_text = ""
        self._wallet_loaded = False
        self._order_records: list[dict] = []
        self._order_rows: list[dict] = []
        self._orders_loaded = False
        self._last_import_at = ""
        self._last_import_count = 0
        self._stale_records: list[dict] = []
        self._busy = False
        self._status = "就绪"
        # 指纹缓存（refresh 幂等：没变就不重算、不发 changed）
        self._fingerprint: tuple | None = None
        self._stock_cache: dict[int, dict[int, int]] = {}
        # 昂贵计算的每轮缓存
        self._shortfall_cache: dict[int, int] = {}
        self._bp_short_cache: dict[int, str | None] = {}
        self._bp_ready_cache: dict[int, bool] = {}

    # ── 产线详情 ──────────────────────────────────────────────

    @Property(list, notify=changed)
    def occupancyRows(self) -> list[dict]:
        """每角色一行的占用数据（形状与 `launcher_bridge.occupancyRows` **逐字一致**）。

        `[{"name", "nameWidth", "lines": [{"label", "color", "active", "max", "cap"}],
        "statusText", "statusColor", "slotTotal"}]` —— QML 里
        `FCapacityRow { charName: modelData.name; ... }`。

        **必须是 Property 而不是 Slot**：QML 的绑定不追踪 Slot 内部的属性读取，
        写成 `occupancyRows()` 调用的话面板不会随 `changed` 自动刷新
        （本仓既有教训，见 `query_bridge.py` 的 `sortColumn` 注释）。
        """
        return [dict(row) for row in self._occupancy_rows]

    @Property(str, notify=changed)
    def occupancySummary(self) -> str:
        return self._occupancy_summary

    @Property(list, notify=changed)
    def occupancyByLine(self) -> list[dict]:
        """**按产线类型**分行的占用数据（仪表盘左栏用，见 `_build_occupancy_by_line`）。

        `[{"key", "label", "color", "active", "cap",
           "chars": [{"name", "active", "max"}], "detailText"}]`
        """
        return [dict(row) for row in self._occupancy_by_line]

    @Property(list, notify=changed)
    def quickRows(self) -> list[dict]:
        """快捷产线行：`{planId, name, action("start"|"complete"), actionText, statusText}`。"""
        return [dict(row) for row in self._quick_rows]

    @Slot(int)
    def quickAction(self, index: int) -> None:
        """执行 `quickRows[index]` 的动作（**确认框在桥里弹**）。

        确认走 `ui_qml/bridge/message_dialog.py::FMessageDialog.question`（本仓弹确认框的
        既有做法，先例见 `char_settings_bridge.py::deleteCharacter`）；QML 只负责调本槽。
        """
        rows = self._quick_rows
        if not 0 <= int(index) < len(rows):
            self._status = "快捷操作已失效，请刷新后再试"
            self.changed.emit()
            return
        item = rows[int(index)]
        plan = next((p for p in self._plans if int(p.get("id") or 0) == int(item["planId"])), None)
        if plan is None:
            self._status = f"「{item['name']}」已不在计划表中，请刷新"
            self.changed.emit()
            return

        verb = "启动" if item["action"] == "start" else "下线"
        if not self._confirm(f"确认{verb}", f"{verb}「{item['name']}」？\n{item['statusText']}"):
            self._status = f"已取消{verb}「{item['name']}」"
            self.changed.emit()
            return

        if item["action"] == "complete":
            self._quick_complete(plan)
        else:
            self._quick_start(plan)
        # 动作改了库 → 指纹作废并整体重算（状态列/占用条都要跟着动）
        self._fingerprint = None
        self.refresh()
        self.changed.emit()

    def _confirm(self, title: str, text: str) -> bool:
        """确认框（`parent` 口径同 `query_bridge.openAllItems`）。弹不出来时按「否」处理。"""
        try:
            return bool(FMessageDialog.question(self._host_widget(), title, text, default_yes=True))
        except Exception:
            log.exception("确认框弹出失败，按「否」处理")
            return False

    def _host_widget(self) -> QWidget | None:
        """弹框的 parent：本桥的 `shell`；若接到的其实是另一个桥（`QueryBridge(self)` 的既有接法），
        就再往下取它自己的 `_shell` —— 两种接法都能拿到真窗口，拿不到就给 None。"""
        candidate: Any = self._shell
        for _ in range(2):
            if isinstance(candidate, QWidget):
                return candidate
            candidate = getattr(candidate, "_shell", None)
        return None

    @Slot()
    def refreshQuick(self) -> None:
        """只重算 `quickRows`（QML 在列表滚动/定时器里按需调）。"""
        try:
            plans = list(load_plans_for_wizard() or [])
        except Exception:
            log.exception("快捷产线刷新失败：计划加载异常")
            self._status = "快捷产线刷新失败：计划加载异常，详见日志"
            self.changed.emit()
            return
        self._plans = plans
        rows = self._build_quick_rows(plans)
        if rows != self._quick_rows:
            self._quick_rows = rows
            self.changed.emit()

    # ── 资产折线图 ────────────────────────────────────────────

    @Property(dict, notify=changed)
    def assetPlot(self) -> dict:
        return self._plot

    @Property(str, notify=changed)
    def assetEmptyText(self) -> str:
        """折线图无数据时的占位文案（写清「从首次记录开始累积」）。"""
        return _EMPTY_ASSET_TEXT

    @Property(list, notify=changed)
    def assetSeries(self) -> list[dict]:
        """`[{key, label, color, visible, latestText}]`。

        `latestText` = 该线**当前区间内**最新一天的值（千分位两位小数），无数据时空串；
        `color` 与 `assetPlot.series[].color` 是同一个值（都在 Python 侧算好）。
        """
        _dates, values = split_series(self._series_rows)
        rows: list[dict] = []
        for key, label, token in _SERIES:
            series_values = values.get(key, [])
            latest = series_values[-1] if series_values else None
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "color": self._series_color(token),
                    "visible": bool(self._visible.get(key, True)),
                    "latestText": "" if latest is None else f"{latest:,.2f}",
                }
            )
        return rows

    @Property(list, notify=changed)
    def assetSummaryRows(self) -> list[dict]:
        """「资产（表格显示）」4 行：最新值 + 相对**区间首点**的变化量与百分比。"""
        _dates, values = split_series(self._series_rows)
        rows: list[dict] = []
        for key, label, token in _SERIES:
            series_values = values.get(key, [])
            latest = series_values[-1] if series_values else None
            if latest is None:
                delta_text, delta_pos = "—", True
            elif len(series_values) < 2:
                delta_text, delta_pos = "—", True
            else:
                delta = latest - series_values[0]
                base = series_values[0]
                delta_text = f"{delta:+,.2f} ({delta / base * 100:+.1f}%)" if base else f"{delta:+,.2f}"
                delta_pos = delta >= 0
            rows.append(
                {
                    "label": label,
                    "valueText": "" if latest is None else f"{latest:,.2f}",
                    "deltaText": delta_text,
                    "deltaPos": delta_pos,
                    "colorToken": token,
                    "color": self._series_color(token),
                }
            )
        return rows

    @Property(list, constant=True)
    def rangeLabels(self) -> list[str]:
        return list(_RANGE_LABELS)

    @Property(int, notify=changed)
    def rangeIndex(self) -> int:
        return self._range_index

    @Slot(int)
    def setRangeIndex(self, index: int) -> None:
        value = int(index)
        if not 0 <= value < len(_RANGE_LABELS):
            return
        if value == self._range_index:
            return
        self._range_index = value
        self._apply_range()
        self.changed.emit()

    @Slot(int)
    def toggleSeries(self, index: int) -> None:
        """翻转某条线的显隐。**至少保留一条可见**：全关时忽略本次并记 warning。"""
        keys = [key for key, _label, _token in _SERIES]
        if not 0 <= int(index) < len(keys):
            return
        key = keys[int(index)]
        if self._visible.get(key, True) and sum(1 for k in keys if self._visible.get(k, True)) <= 1:
            log.warning("资产折线图：至少保留一条可见线，忽略对 %s 的关闭", key)
            return
        self._visible[key] = not self._visible.get(key, True)
        self._plot = asset_plot(self._series_rows, self._visible, self._series_colors())
        self.changed.emit()

    # ── 钱包（手填）───────────────────────────────────────────

    @Property(str, notify=changed)
    def walletText(self) -> str:
        self._ensure_wallet()
        return self._wallet_text

    @Slot(str)
    def setWalletText(self, text: str) -> None:
        """手填钱包余额：落 `settings.json` 并写一条资产快照（失败给中文提示，不抛）。"""
        value = parse_amount(text)
        if value is None:
            self._status = f"钱包余额「{text}」不是有效金额（可带千分位，如 1,234,567.89）"
            self.changed.emit()
            return
        text_value = f"{value:,.2f}"
        svc = _asset_svc()
        if svc is None:
            self._status = "资产快照模块不可用：钱包余额未保存"
            self.changed.emit()
            return
        try:
            svc.set_wallet_balance(value)
            snapshot_ok = self._record_snapshot(wallet=value)
        except Exception:
            log.exception("钱包余额保存失败 value=%s", value)
            self._status = "钱包余额保存失败，详见日志"
            self.changed.emit()
            return
        self._wallet_text = text_value
        self._wallet_loaded = True
        self._refresh_snapshots()
        tail = "并写入资产快照" if snapshot_ok else "（资产快照写入失败，详见日志）"
        self._status = f"已记录钱包余额 {text_value} ISK {tail}"
        self.changed.emit()

    # ── 挂单 ──────────────────────────────────────────────────

    @Property(list, constant=True)
    def openOrderHeads(self) -> list[str]:
        return list(_ORDER_HEADS_LIST)

    @Property(list, notify=changed)
    def openOrderRows(self) -> list[dict]:
        self._ensure_orders()
        return [dict(row) for row in self._order_rows]

    @Property(str, notify=changed)
    def openOrderSummary(self) -> str:
        self._ensure_orders()
        if not self._order_records:
            return _EMPTY_ORDER_SUMMARY
        buy = sum(1 for r in self._order_records if r["is_buy"])
        sell = len(self._order_records) - buy
        total = sum(float(r["price"]) * int(r["volume_remain"]) for r in self._order_records)
        parts = [
            f"{len(self._order_records)} 笔挂单",
            f"卖单 {sell}",
            f"买单 {buy}",
            f"挂单总额 {total:,.2f} ISK",
        ]
        if self._last_import_at:
            parts.append(f"本次导入 {self._last_import_at}")
        if self._stale_records:
            parts.append(f"本次文件里没出现的旧订单 {len(self._stale_records)} 笔（可能已成交/撤单）")
        return " · ".join(parts)

    @Property(str, notify=changed)
    def exportDir(self) -> str:
        """用户自定义的订单导出目录（空串 = 用游戏默认目录）。

        Property 而不是 Slot：QML 的「导出目录」输入框直接绑它，Slot 调用不进绑定追踪
        （同 `occupancyRows` 的理由）。
        """
        return _configured_export_dir()

    @Slot(str)
    def setExportDir(self, path: str) -> None:
        """改自定义导出目录（落 `settings.json`），并立刻按新目录重读一次。"""
        cleaned = str(path or "").strip()
        try:
            save_settings({_SETTING_EXPORT_DIR: cleaned})
        except Exception:
            log.exception("订单导出目录保存失败 path=%s", cleaned)
            self._status = "导出目录保存失败，详见日志"
            self.changed.emit()
            return
        self.readOrders()

    @Slot()
    def readOrders(self) -> None:
        """读游戏导出的订单文件 → 写 `open_orders` → 回写一条资产快照。

        找不到文件只给中文提示，**不抛异常、不清空已有列表**（用户可能只是还没导出）。
        """
        svc = _order_svc()
        if svc is None:
            self._status = "订单解析模块不可用（services/order_export.py 缺失）"
            self.changed.emit()
            return
        directory = _configured_export_dir()
        try:
            path = svc.find_latest_export(directory or None)
        except Exception:
            log.exception("订单导出文件查找失败 dir=%s", directory)
            self._status = f"订单导出文件查找失败，详见日志；当前目录 {self._dir_display()}"
            self.changed.emit()
            return
        if not path:
            self._status = f"没找到订单导出文件：请先在游戏「钱包 → 订单」里点导出；当前目录 {self._dir_display()}"
            self.changed.emit()
            return

        name = Path(str(path)).name
        try:
            # 走 `order_export.read_export_text`：真实导出是 **UTF-8 带 BOM**，
            # 直接 `encoding="utf-8"` 读会让首列表头变成 `﻿orderID`、整份退化成启发式解析
            raw = svc.read_export_text(path)
        except (OSError, AttributeError):
            log.exception("订单导出文件读取失败 path=%s", path)
            self._status = f"订单导出文件读取失败：{name}"
            self.changed.emit()
            return
        try:
            parsed, unparsed = svc.parse_order_export(raw)
        except Exception:
            log.exception("订单导出解析失败 path=%s", path)
            self._status = f"订单解析失败：{name} 不是有效的订单导出文件"
            self.changed.emit()
            return

        records = [_normalize_order(r) for r in parsed if isinstance(r, Mapping)]
        records = [r for r in records if r["order_id"]]
        if not records:
            self._status = f"未从 {name} 解析出挂单（跳过 {int(unparsed)} 行）"
            self.changed.emit()
            return

        self._fill_location_names(records)
        self._fill_type_names(records)
        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._write_orders(records, imported_at)
        except sqlite3.Error:
            log.exception("挂单写入 user.db 失败 count=%s", len(records))
            self._status = "挂单写入本地库失败，详见日志"
            self.changed.emit()
            return

        self._last_import_at = imported_at
        self._last_import_count = len(records)
        self._ensure_orders(force=True)
        self._stale_records = self._load_stale(imported_at)
        snapshot_ok = self._record_snapshot()
        self._refresh_snapshots()
        skipped = f"，跳过 {int(unparsed)} 行" if unparsed else ""
        tail = "已记入资产快照" if snapshot_ok else "资产快照写入失败，详见日志"
        self._status = f"已从「{name}」导入 {len(records)} 笔挂单{skipped}，{tail}"
        self.changed.emit()

    @Slot(result=dict)
    def pendingReview(self) -> dict:
        """导入后的审阅信息：本次导入笔数 + 「可能已成交/撤单」的陈旧订单。

        交给 QML 弹确认框；**删除只在用户点头后由 `dropStaleOrders()` 执行**——
        用户可能只是导出了另一个角色的订单，不能自动清。
        """
        count = int(self._last_import_count)
        stale = list(self._stale_records)
        return {
            "count": count,
            "staleCount": len(stale),
            "staleNames": [str(r.get("type_name") or r.get("type_id") or "") for r in stale],
            "message": self._review_message(count, stale),
        }

    @Slot()
    def dropStaleOrders(self) -> None:
        """把「本次导出文件里没出现」的订单标记为已结束（从 `open_orders` 删掉）。"""
        stale = list(self._stale_records)
        if not stale:
            self._status = "没有需要结束的陈旧挂单"
            self.changed.emit()
            return
        try:
            with _user_conn() as conn:
                conn.executemany(
                    "DELETE FROM open_orders WHERE order_id = ?",
                    [(int(r["order_id"]),) for r in stale],
                )
        except sqlite3.Error:
            log.exception("陈旧挂单删除失败 count=%s", len(stale))
            self._status = "陈旧挂单删除失败，详见日志"
            self.changed.emit()
            return
        self._stale_records = []
        self._ensure_orders(force=True)
        snapshot_ok = self._record_snapshot()
        self._refresh_snapshots()
        tail = "并记入资产快照" if snapshot_ok else "，但资产快照写入失败，详见日志"
        self._status = f"已结束 {len(stale)} 笔陈旧挂单{tail}"
        self.changed.emit()

    # ── 状态 ──────────────────────────────────────────────────

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=changed)
    def statusText(self) -> str:
        return self._status

    # ════════════════════════════════════════════════════════
    #  刷新（QML 空闲态可见时调一次 + 60s 定时器调）
    # ════════════════════════════════════════════════════════

    @Slot()
    def refresh(self) -> None:
        """整体重算。**幂等且便宜**：指纹没变就直接返回，不重算也不发 `changed`。"""
        try:
            plans = list(load_plans_for_wizard() or [])
        except Exception:
            log.exception("仪表盘刷新失败：计划加载异常")
            self._status = "仪表盘刷新失败：计划加载异常，详见日志"
            self.changed.emit()
            return
        fingerprint = self._probe(plans)
        if fingerprint == self._fingerprint:
            return
        self._busy = True
        self.changed.emit()
        try:
            self._plans = plans
            self._refresh_occupancy(plans)
            self._quick_rows = self._build_quick_rows(plans)
            self._refresh_snapshots(force=True)
            self._ensure_orders(force=True)
            self._ensure_wallet(force=True)
            self._fingerprint = fingerprint
        except Exception:
            log.exception("仪表盘刷新失败")
            self._status = "仪表盘刷新失败，详见日志"
        finally:
            self._busy = False
            self.changed.emit()

    def _probe(self, plans: list[dict]) -> tuple:
        """便宜档指纹：计划字段集 + 机库库存 + 角色技能 + 快照/挂单行数 + 本地状态。

        库存顺带存进 `_stock_cache`，`_build_quick_rows` 直接复用、不重复查库。
        """
        self._stock_cache.clear()
        stock_sig: list[tuple[int, frozenset]] = []
        for hangar_id in sorted({int(p.get("mat_hangar_id") or 0) for p in plans if p.get("mat_hangar_id")}):
            stock = self._hangar_stock(hangar_id)
            stock_sig.append((hangar_id, frozenset(stock.items())))
        return (
            tuple(
                sorted(
                    (
                        int(p.get("id") or 0),
                        str(p.get("status") or ""),
                        int(p.get("runs") or 0),
                        int(p.get("parallels") or 0),
                        int(p.get("me_level") or 0),
                        int(p.get("mat_hangar_id") or 0),
                        str(p.get("char_name") or ""),
                    )
                    for p in plans
                )
            ),
            tuple(stock_sig),
            self._char_signature(),
            self._snapshot_signature(),
            self._orders_signature(),
            self._wallet_text,
            self._range_index,
            tuple(sorted(self._visible.items())),
        )

    @staticmethod
    def _char_signature() -> tuple:
        """角色列表 + 各自技能（决定产线容量）。读的是 char_config.json，不查库。"""
        try:
            chars = get_character_list()
            data = (load_all_data() or {}).get("characters", {}) or {}
        except Exception:
            log.exception("角色配置读取失败")
            return ()
        return tuple(
            sorted(
                (
                    str(name),
                    tuple(sorted((str(k), str(v)) for k, v in ((data.get(name) or {}).get("skills") or {}).items())),
                )
                for name in chars
            )
        )

    def _snapshot_signature(self) -> tuple:
        """快照行数 + 最新日期（只读 user.db，最便宜的一查）。"""
        try:
            with _user_conn() as conn:
                if not _table_exists(conn, "asset_snapshots"):
                    return ()
                row = conn.execute("SELECT COUNT(*), COALESCE(MAX(snap_date), '') FROM asset_snapshots").fetchone()
        except sqlite3.Error:
            log.exception("资产快照指纹读取失败")
            return ()
        return (int(row[0]), str(row[1])) if row else ()

    def _orders_signature(self) -> tuple:
        """挂单行数 + 最近导入时间（同样是便宜的一查）。"""
        try:
            with _user_conn() as conn:
                if not _table_exists(conn, "open_orders"):
                    return ()
                row = conn.execute("SELECT COUNT(*), COALESCE(MAX(imported_at), '') FROM open_orders").fetchone()
        except sqlite3.Error:
            log.exception("挂单指纹读取失败")
            return ()
        return (int(row[0]), str(row[1])) if row else ()

    # ── 产线详情 ──────────────────────────────────────────────

    def _refresh_occupancy(self, plans: list[dict]) -> None:
        """复刻 `production_launcher._refresh_occupancy` 的行几何（新文件里重写，不改原文件）。"""
        usage = active_lines_by_category(plans)
        chars_data = (load_all_data() or {}).get("characters", {}) or {}
        chars = list(get_character_list())
        for char in usage:
            if char and char not in chars:
                chars.append(char)

        if not chars:
            self._occupancy_summary = "（无人物配置，请在人物设置中添加）"
            self._occupancy_rows = []
            self._occupancy_by_line = []
            return

        per_char: list[tuple[str, dict[str, tuple[int, int]]]] = []
        line_caps: dict[str, int] = dict.fromkeys(_LINE_TYPES, 0)
        active_total = 0
        max_total = 0
        for char in chars:
            skills = (chars_data.get(char, {}) or {}).get("skills", {}) or {}
            char_usage = usage.get(char or "", {})
            per_line: dict[str, tuple[int, int]] = {}
            for line in _LINE_TYPES:
                maximum = max_lines_for_category(char, line, skills=skills)
                active = int(char_usage.get(line, 0))
                per_line[line] = (active, maximum)
                line_caps[line] = max(line_caps[line], maximum)
                active_total += active
                max_total += maximum
            per_char.append((char, per_line))

        slot_total = max(sum(line_caps.values()), 1)
        rows: list[dict] = []
        for char, per_line in per_char:
            lines_data = [
                {
                    "label": line_label(line),
                    "color": self._series_color(_LINE_COLORS[line]),
                    "active": int(per_line[line][0]),
                    "max": int(per_line[line][1]),
                    "cap": int(line_caps[line]),
                }
                for line in _LINE_TYPES
            ]
            status_text, status_token = self._char_status(per_line)
            rows.append(
                {
                    "name": char or "(未分配)",
                    "nameWidth": _NAME_W,
                    "lines": lines_data,
                    "statusText": status_text,
                    "statusColor": self._series_color(status_token),
                    "slotTotal": slot_total,
                }
            )
        self._occupancy_rows = rows
        self._occupancy_summary = f"{len(chars)} 人物 · 占用 {active_total}/{max_total}"
        self._occupancy_by_line = self._build_occupancy_by_line(per_char)

    def _build_occupancy_by_line(
        self, per_char: list[tuple[str, dict[str, tuple[int, int]]]]
    ) -> list[dict]:
        """**转置**成「每种产线类型一行」—— 空闲态仪表盘的产线详情用这个形状。

        为什么不用 `occupancy_rows` 的按人物分行：那个形状是给**产线启动小助手**的宽面板用的
        （60px 名字列 + 三类产线各自的标签与格子 + 状态徽章，实测要 450px 才不重叠）。
        仪表盘左栏只有 260px 左右，按人物分行必然把格子压到标签上。
        人物本来就没几个，转置过来每类产线只占一行，占地小得多。

        每行的 `chars` 保留**逐人物**的占用与上限，QML 据此画「一个角色一段」的容量条；
        `cap` 是各人物上限之和（=该类型总槽位数），`active` 是各人物已用之和。
        `detailText` 给 tooltip，宽度不够时界面也不会丢信息。
        """
        by_line: list[dict] = []
        for line in _LINE_TYPES:
            chars_detail: list[dict[str, Any]] = [
                {
                    "name": char or "(未分配)",
                    "active": int(per_line.get(line, (0, 0))[0]),
                    "max": int(per_line.get(line, (0, 0))[1]),
                }
                for char, per_line in per_char
            ]
            active = sum(int(c["active"]) for c in chars_detail)
            cap = sum(int(c["max"]) for c in chars_detail)
            by_line.append(
                {
                    "key": str(line),
                    "label": line_label(line),
                    "color": self._series_color(_LINE_COLORS[line]),
                    "active": active,
                    "cap": cap,
                    "chars": chars_detail,
                    "detailText": " · ".join(f"{c['name']} {c['active']}/{c['max']}" for c in chars_detail),
                }
            )
        return by_line

    @staticmethod
    def _char_status(per_line: dict[str, tuple[int, int]]) -> tuple[str, str]:
        """(状态文本, 语义色 token) —— 超员 / 空闲 / 生产中（文案与产线小助手逐字一致）。"""
        active_total = sum(per_line.get(line, (0, 0))[0] for line in _LINE_TYPES)
        max_total = sum(per_line.get(line, (0, 0))[1] for line in _LINE_TYPES)
        if active_total > max_total:
            return f"超员 +{active_total - max_total}", "ACCENT_RED"
        if active_total == 0:
            return "空闲", "ACCENT_GREEN"
        return "生产中", "PRIMARY"

    def _build_quick_rows(self, plans: list[dict]) -> list[dict]:
        """可启动（含软阻塞）/ 可下线各最多 8 条。

        先跑**便宜**的阻塞判定（状态 / 材料机库 / 蓝图 / 子项），只有过了这一关的候选才
        做材料缺口评分 —— 否则大计划表会为了填 8 行把主线程拖住。候选扫描上限
        `_QUICK_SCAN_LIMIT`。
        """
        self._shortfall_cache.clear()
        self._bp_short_cache.clear()
        self._bp_ready_cache.clear()
        starts: list[dict] = []
        completes: list[dict] = []
        scanned = 0
        for plan in plans:
            status = str(plan.get("status") or "").lower()
            if status == "ready":
                if len(completes) < _QUICK_LIMIT:
                    completes.append(self._quick_item(plan, "complete", "下线", "待下线"))
            elif status == "pending":
                if len(starts) >= _QUICK_LIMIT:
                    continue
                code, reason = self._cheap_block(plan, plans)
                if code is not None and code not in _SOFT_BLOCKS:
                    continue
                if scanned >= _QUICK_SCAN_LIMIT:
                    continue
                scanned += 1
                code, reason = self._block_state(plan, plans)
                if code is None:
                    starts.append(self._quick_item(plan, "start", "启动", "可启动"))
                elif code in _SOFT_BLOCKS:
                    starts.append(
                        self._quick_item(plan, "start", "启动", _SOFT_BLOCK_TEXT.get(code, reason or "材料不够"))
                    )
            if len(starts) >= _QUICK_LIMIT and len(completes) >= _QUICK_LIMIT:
                break
        return starts + completes

    @staticmethod
    def _quick_item(plan: dict, action: str, action_text: str, status_text: str) -> dict:
        return {
            "planId": int(plan.get("id") or 0),
            "name": str(plan.get("product_name") or f"ID:{plan.get('product_type_id', '')}"),
            "action": action,
            "actionText": action_text,
            "statusText": status_text,
        }

    def _default_mat_hangar(self) -> int | None:
        try:
            from services import inventory_manager

            return inventory_manager.get_default_mat_hangar_and_system()[0]
        except Exception:
            log.exception("默认材料机库读取失败")
            return None

    def _cheap_block(self, plan: dict, all_plans: list[dict]) -> tuple[str | None, str | None]:
        """不做材料评分、不查库存的阻塞判定（缺口按 0 计）—— 用来快速筛掉硬阻塞的候选。

        蓝图就绪仍走真实判定（一次 DB 查询 + 指纹缓存）：按 `has_image` 的粗推断会
        把「已绑定蓝图但计划里没有该字段」的正常计划误判成缺蓝图。
        """
        block = plan_start_block(
            plan,
            plan.get("mat_hangar_id") or self._default_mat_hangar(),
            all_plans,
            blueprint_ready=self._blueprint_ready(plan),
        )
        return block if block else (None, None)

    def _block_state(self, plan: dict, all_plans: list[dict]) -> tuple[str | None, str | None]:
        """完整阻塞判定（含材料缺口与蓝图流程），返回 (类别码, 原因文案)。"""
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar()
        block = plan_start_block(
            plan,
            mat,
            all_plans,
            shortfall_count=self._shortfall_count(plan, mat),
            bp_short=self._bp_short(plan),
            blueprint_ready=self._blueprint_ready(plan),
        )
        return block if block else (None, None)

    def _hangar_stock(self, hangar_id: int) -> dict[int, int]:
        stock = self._stock_cache.get(hangar_id)
        if stock is None:
            try:
                from services import inventory_manager

                stock = inventory_manager.get_hangar_stock(hangar_id)
            except Exception:
                log.exception("机库库存读取失败 hangar_id=%s", hangar_id)
                stock = {}
            self._stock_cache[hangar_id] = stock
        return stock

    def _shortfall_count(self, plan: dict, mat: int | None) -> int:
        """材料缺口种数（每轮每计划只算一次：缺口判定要跑一次评分）。"""
        if not mat or str(plan.get("status") or "").lower() != "pending":
            return 0
        plan_id = int(plan.get("id") or 0)
        if plan_id in self._shortfall_cache:
            return self._shortfall_cache[plan_id]
        count = 0
        try:
            stock = self._hangar_stock(int(mat))
            count = sum(
                1
                for row in plan_execution.check_materials(plan, int(mat), stock=stock)
                if int(row.get("missing") or 0) > 0
            )
        except Exception:
            log.exception("材料缺口计算失败 plan_id=%s", plan_id)
            count = 0
        self._shortfall_cache[plan_id] = count
        return count

    def _bp_short(self, plan: dict) -> str | None:
        plan_id = int(plan.get("id") or 0)
        if plan_id not in self._bp_short_cache:
            try:
                self._bp_short_cache[plan_id] = plan_execution.binding_shortfall(plan_id)
            except Exception:
                log.exception("蓝图流程预检失败 plan_id=%s", plan_id)
                self._bp_short_cache[plan_id] = None
        return self._bp_short_cache[plan_id]

    def _blueprint_ready(self, plan: dict) -> bool:
        plan_id = int(plan.get("id") or 0)
        if plan_id not in self._bp_ready_cache:
            try:
                self._bp_ready_cache[plan_id] = bool(plan_execution.plan_blueprint_ready(plan))
            except Exception:
                log.exception("输入蓝图就绪检查失败 plan_id=%s", plan_id)
                self._bp_ready_cache[plan_id] = True
        return self._bp_ready_cache[plan_id]

    def _quick_start(self, plan: dict) -> None:
        """启动一条计划。**先过 `plan_start_block`**：阻塞时只写状态、不执行。"""
        name = str(plan.get("product_name") or plan.get("id"))
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar()
        code, reason = self._block_state(plan, self._plans)
        if code is not None and code not in _SOFT_BLOCKS:
            self._status = f"「{name}」无法启动：{reason}"
            return
        allow_short = code in _SOFT_BLOCKS
        try:
            result = plan_execution.start_plan(
                plan,
                mat_hangar_id=mat,
                allow_short=allow_short,
                allow_bp_short=allow_short,
                char_name=plan.get("char_name") or None,
                facility=plan.get("facility") or None,
            )
        except Exception:
            log.exception("快捷启动失败 plan_id=%s", plan.get("id"))
            self._status = f"启动失败：「{name}」执行异常，详见日志"
            return
        if result.get("ok"):
            self._status = f"已启动「{name}」"
        else:
            self._status = f"启动失败：「{name}」{result.get('message') or result.get('code') or '未知原因'}"

    def _quick_complete(self, plan: dict) -> None:
        """下线一条计划（单行下线入口自带产出机库选择与失败告警）。"""
        name = str(plan.get("product_name") or plan.get("id"))
        try:
            result = _complete_one_plan(None, plan)
        except Exception:
            log.exception("快捷下线失败 plan_id=%s", plan.get("id"))
            self._status = f"下线失败：「{name}」执行异常，详见日志"
            return
        self._status = f"已下线「{name}」" if result else f"已取消下线「{name}」"

    # ── 资产折线 ──────────────────────────────────────────────

    def _series_colors(self) -> dict[str, str]:
        return {key: self._series_color(token) for key, _label, token in _SERIES}

    @staticmethod
    def _series_color(token: str) -> str:
        """主题 token → 经对比度校正的 hex（token 缺失时返回原样，不抛）。"""
        raw = str(getattr(theme, token, "") or "")
        if not raw.startswith("#"):
            return raw
        return ensure_contrast(raw, theme.BG_DARK)

    def _refresh_snapshots(self, force: bool = False) -> None:
        """读全量快照 → 按当前区间裁剪 → 重算几何。"""
        if force or not self._all_series_rows:
            svc = _asset_svc()
            rows: list[dict] = []
            if svc is not None:
                try:
                    rows = [dict(r) for r in (svc.load_series(days=_RANGE_ALL_DAYS) or []) if isinstance(r, Mapping)]
                except Exception:
                    log.exception("资产快照读取失败")
                    rows = []
            self._all_series_rows = rows
        self._apply_range()

    def _apply_range(self) -> None:
        """按 `rangeIndex` 的自然月/自然年起点裁剪，再喂几何函数。"""
        try:
            days, start = range_window(self._range_index)
        except Exception:
            log.exception("区间档位计算失败 index=%s", self._range_index)
            days, start = _RANGE_ALL_DAYS, None
        # 取数时已按「最近的 N 天」拿过（N ≥ 本档所需），这里再按自然起点精确裁一刀
        trimmed = trim_from(self._all_series_rows, start) if start else list(self._all_series_rows)
        if len(trimmed) > days:
            trimmed = trimmed[-days:]
        self._series_rows = [dict(row) for row in trimmed]
        self._plot = asset_plot(self._series_rows, self._visible, self._series_colors())

    def _ensure_wallet(self, force: bool = False) -> None:
        if self._wallet_loaded and not force:
            return
        self._wallet_loaded = True
        svc = _asset_svc()
        if svc is None:
            return
        try:
            value = svc.get_wallet_balance()
        except Exception:
            log.exception("钱包余额读取失败")
            return
        if value is None:
            self._wallet_text = ""
            return
        self._wallet_text = f"{float(value):,.2f}"

    def _record_snapshot(self, wallet: float | None = None) -> bool:
        """回写一条资产快照（「通过记录联动资产记录」）。服务缺失/失败时返回 False。

        返回值给调用方决定 `statusText` 怎么写 —— 快照没写成就别声称「已记入资产快照」。
        """
        svc = _asset_svc()
        if svc is None:
            return False
        try:
            if wallet is None:
                svc.record_snapshot()
            else:
                svc.record_snapshot(wallet=wallet)
        except TypeError:
            log.warning("record_snapshot 不接受 wallet 参数，退回无参调用")
            try:
                svc.record_snapshot()
            except Exception:
                log.exception("资产快照记录失败")
                return False
        except Exception:
            log.exception("资产快照记录失败")
            return False
        return True

    # ── 挂单 ──────────────────────────────────────────────────

    def _dir_display(self) -> str:
        return _configured_export_dir() or _DEFAULT_EXPORT_DIR_TEXT

    def _ensure_orders(self, force: bool = False) -> None:
        if self._orders_loaded and not force:
            return
        self._orders_loaded = True
        try:
            with _user_conn() as conn:
                if not _table_exists(conn, "open_orders"):
                    self._order_records = []
                    self._order_rows = []
                    return
                raw = conn.execute(
                    f"SELECT {', '.join(_ORDER_DB_COLUMNS)} FROM open_orders ORDER BY order_id DESC"
                ).fetchall()
        except sqlite3.Error:
            log.exception("挂单列表读取失败")
            return
        self._order_records = [_normalize_order(_row_to_dict(row)) for row in raw]
        self._order_records = [r for r in self._order_records if r["order_id"]]
        self._order_rows = self._order_cell_rows(self._order_records)
        imported = [str(r["imported_at"]) for r in self._order_records if r["imported_at"]]
        self._last_import_at = max(imported) if imported else ""

    def _write_orders(self, records: list[dict], imported_at: str) -> None:
        """`INSERT OR REPLACE`（order_id 主键 → 重复导入同一份文件是幂等的）。"""
        placeholders = ", ".join("?" for _ in _ORDER_DB_COLUMNS)
        sql = f"INSERT OR REPLACE INTO open_orders ({', '.join(_ORDER_DB_COLUMNS)}) VALUES ({placeholders})"
        rows = [
            tuple(imported_at if column == "imported_at" else record[column] for column in _ORDER_DB_COLUMNS)
            for record in records
        ]
        with _user_conn() as conn:
            conn.executemany(sql, rows)

    def _load_stale(self, imported_at: str) -> list[dict]:
        """库里 `imported_at` 不等于本次导入时间的行 = 本次导出文件里没出现的订单。

        **只统计、不删除**：用户可能只是导出了另一个角色的订单。
        """
        try:
            with _user_conn() as conn:
                if not _table_exists(conn, "open_orders"):
                    return []
                raw = conn.execute(
                    f"SELECT {', '.join(_ORDER_DB_COLUMNS)} FROM open_orders WHERE imported_at IS NOT ? OR imported_at = ''",
                    (imported_at,),
                ).fetchall()
        except sqlite3.Error:
            log.exception("陈旧挂单统计失败")
            return []
        records = [_normalize_order(_row_to_dict(row)) for row in raw]
        return [r for r in records if r["order_id"]]

    def _fill_location_names(self, records: list[dict]) -> None:
        """`location_name` 为空的，用 `location_id` 去本地空间站表补（解析器不碰这件事）。"""
        missing = {int(r["location_id"]) for r in records if not r["location_name"] and r["location_id"]}
        if not missing:
            return
        names: dict[int, tuple[str, str]] = {}
        try:
            from services.npc_seller import resolve_stations_by_ids

            names = resolve_stations_by_ids(missing)
        except Exception:
            log.exception("空间站名补全失败 count=%s", len(missing))
            return
        for record in records:
            if record["location_name"] or not record["location_id"]:
                continue
            found = names.get(int(record["location_id"]))
            if found and found[0]:
                record["location_name"] = str(found[0])

    def _fill_type_names(self, records: list[dict]) -> None:
        """`type_name` 为空的，用 `type_id` 去 SDE（reference.db `item`）补中文名。

        **必须补**：真实导出文件里只有 ``typeID``、**没有物品名列**（实测表头
        ``orderID,typeID,charID,…``），不补的话「物品」整列是空的。
        """
        missing = {int(r["type_id"]) for r in records if not r["type_name"] and r["type_id"]}
        if not missing:
            return
        names: dict[int, str] = {}
        try:
            with get_container().db.connect("ref") as conn:
                marks = ",".join("?" * len(missing))
                rows = conn.execute(
                    f"SELECT type_id, zh_name FROM item WHERE type_id IN ({marks})", tuple(missing)
                ).fetchall()
            names = {int(r[0]): str(r[1] or "") for r in rows}
        except sqlite3.Error:
            log.exception("物品名补全失败 count=%s", len(missing))
            return
        for record in records:
            if record["type_name"] or not record["type_id"]:
                continue
            found = names.get(int(record["type_id"]))
            if found:
                record["type_name"] = found

    @staticmethod
    def _order_cell_rows(records: Sequence[Mapping[str, Any]]) -> list[dict]:
        """挂单 → 单元格行（形状同 `order_popup_bridge.order_rows`，QML 侧表组件直接吃）。"""
        rows: list[dict] = []
        for record in records:
            is_buy = bool(record["is_buy"])
            location = str(record["location_name"] or "")
            if not location:
                location = f"#{int(record['location_id'])}" if record["location_id"] else "—"
            name = str(record["type_name"] or "") or (f"#{int(record['type_id'])}" if record["type_id"] else "—")
            rows.append(
                {
                    "cells": [
                        cell(str(int(record["order_id"])), _TOKEN_PLAIN),
                        cell(name, _TOKEN_PLAIN),
                        cell("买" if is_buy else "卖", _TOKEN_BUY if is_buy else _TOKEN_SELL),
                        cell(f"{float(record['price']):,.2f}", _TOKEN_PLAIN),
                        cell(f"{int(record['volume_remain']):,}/{int(record['volume_total']):,}", _TOKEN_PLAIN),
                        cell(location, _TOKEN_PLAIN),
                    ]
                }
            )
        return rows

    @staticmethod
    def _review_message(count: int, stale: Sequence[Mapping[str, Any]]) -> str:
        if not count:
            return "还没有导入订单导出文件 —— 先在游戏「钱包 → 订单」里点导出，再点「读取订单」。"
        if not stale:
            return f"本次导入 {count} 笔挂单，没有发现可能已成交/撤单的旧订单。"
        names = "、".join(str(r.get("type_name") or r.get("type_id") or "") for r in stale[:5])
        more = "…" if len(stale) > 5 else ""
        return (
            f"本次导入 {count} 笔挂单；库中有 {len(stale)} 笔订单没出现在本次文件里"
            f"（可能已卖出成交或已取消挂单）：{names}{more}。"
            "要把它们标记为已结束（从列表移除）吗？选「否」则原样保留。"
        )


# ════════════════════════════════════════════════════════════
#  小工具
# ════════════════════════════════════════════════════════════


def _normalize_order(row: Mapping[str, Any]) -> dict:
    """任意来源（解析器 / DB 行）→ 本模块统一口径的记录 dict（全部字段都强制有值）。"""
    return {
        "order_id": _as_int(row.get("order_id")),
        "is_buy": 1 if _as_buy(row.get("is_buy")) else 0,
        "price": _as_float(row.get("price")),
        "volume_total": _as_int(row.get("volume_total")),
        "volume_remain": _as_int(row.get("volume_remain")),
        "location_id": _as_int(row.get("location_id")),
        "location_name": str(row.get("location_name") or ""),
        "type_id": _as_int(row.get("type_id")),
        "type_name": str(row.get("type_name") or ""),
        "issued": str(row.get("issued") or ""),
        "duration": _as_int(row.get("duration")),
        "imported_at": str(row.get("imported_at") or ""),
    }


def _row_to_dict(row: Any) -> dict[str, Any]:
    """sqlite3.Row / tuple → dict（列名按 `_ORDER_DB_COLUMNS` 顺序兜底）。"""
    if isinstance(row, Mapping):
        return dict(row)
    try:
        return dict(row)  # sqlite3.Row 支持 keys()/__getitem__
    except (TypeError, ValueError):
        return dict(zip(_ORDER_DB_COLUMNS, tuple(row), strict=False))


def _table_exists(conn: Any, name: str) -> bool:
    """表在不在（`open_orders` / `asset_snapshots` 由 schema 迁移 #17 建）。

    迁移还没跑到的库上，读这两张表会直接抛 `no such table` —— 先问一句更省事。
    """
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None
