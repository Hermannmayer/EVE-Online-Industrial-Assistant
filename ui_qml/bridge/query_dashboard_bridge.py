"""物品查询页 · 空闲态仪表盘的桥（第 3 步）。

四块内容，全部同步取数（**构造期不起任何线程**，硬约束见
`ui_qml/bridge/query_bridge.py:221-237`：桥一旦生命周期短，线程还没结束进程就退不出去）：

1. **产线详情** `occupancyByChar` —— **每人物一块，块内制造/科研/反应各一行**。
   块尾给「待下线 N」（该人物该线型的 `status=='ready'` 计划数）与「空 N」（剩余产线）。
   算法底层仍是 `services.char_capacity.active_lines_by_category` + `max_lines_for_category`
   （与产线启动小助手同源），只是**转置方向按人物**（仪表盘左栏要的是「谁在用」）。
   另有 `occupancyRows` 保留 `launcher_bridge.occupancyRows` 的同形状输出（共用契约）。

2. **资产折线图** `assetPlot` / `assetSeries` / `reloadAssets()` —— 数据源
   `services.asset_snapshot_service`（5 条线，含「运行中产线价值」）。
   几何全部复用 `ui_qml/bridge/price_chart_bridge.py` 的纯函数
   （`nice_range` / `axis_values` / `map_values` / `pick_indices`），与 `plot_model` 同口径：
   x 按**下标均分**，y 用**筛选后可见线**的合并最值，下界**不贴 0**
   （资产不从 0 起，贴 0 会把波动压平）。颜色在 **Python 侧**算好（过
   `ensure_contrast`）随 `series[].color` 一起下发 —— QML 不准自己读 `Theme` 取折线色。

3. **资产表** `assetSummaryRows` —— 5 行「最新值 + 相对区间首点的变化量/百分比」。

4. **挂单列表** `buyOrderRows` / `sellOrderRows`（**买单、卖单各一张表**，各带笔数）/
   `readOrders` —— 读游戏内「钱包 → 订单 → 导出」写出的本地文件
   （`Documents\\EVE\\logs\\Marketlogs\\`，**目录固定不设自定义**），解析走
   `services.order_export`，落 `user.db.open_orders`（`INSERT OR REPLACE`，order_id
   主键 → 重复导入幂等）。

   **导入后弹「订单变动」确认框**（`ui_qml.bridge.order_change_bridge`）：列出本次
   消失 / 数量变少的订单，逐条选「买到了 / 卖完了」（默认）或「手动撤销」；
   点应用后由 `applyOrderChanges` 增减钱包余额（卖出 +、买入 −，**不扣税费**）、
   落 `order_events` 台账、清掉已结束的挂单、回写资产快照。

刷新生命周期：**本桥不自建定时器**。QML 空闲态可见时调一次 `refresh()`，另有一个只在
可见时运行的 60s `Timer` 也调它 —— 因此 `refresh()` 必须幂等且便宜：先算一份
「计划字段集 + 机库库存 + 角色技能 + 快照/挂单行数 + 本桥本地状态」的指纹，
**指纹没变就直接返回，不重算、不发 `changed`**（照抄 `industry_view.py` 的材料状态刷新思路）。

**数据一律 `Property`，动作才是 `Slot`**：QML 的绑定不追踪 Slot 内部的属性读取，
把 `occupancyByChar` / `assetPlot` 这类数据写成 Slot 调用，面板就不会随 `changed` 刷新
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
from PySide6.QtWidgets import QApplication, QWidget

import ui_qml.theme.registry as theme
from core.container import get_container
from core.logger import log
from domain.theme_contrast import ensure_contrast
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
from services.user_settings import (
    get_esi_orders_synced_at,
    get_include_corp_wallet,
    set_esi_orders_synced_at,
    set_include_corp_wallet,
)
from services.wallet_import import latest_balance, parse_wallet_journal
from ui_qml.bridge.message_dialog import FMessageDialog
from ui_qml.bridge.price_chart_bridge import axis_values, map_values, nice_range, pick_indices
from ui_qml.bridge.summary_dialog import cell

__all__ = [
    "QueryDashboardBridge",
    "asset_plot",
    "classify_order_changes",
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
#: (key, 中文标签, 主题色 token)。五条线的颜色**不新增 token**，只复用现有强调色。
_SERIES: tuple[tuple[str, str, str], ...] = (
    ("total", "总资产", "PRIMARY"),
    ("orders", "挂单金额", "ACCENT_GREEN"),
    ("inventory", "库存材料", "ACCENT_ORANGE"),
    ("line_value", "运行中产线价值", "ACCENT_CYAN"),
    ("wallet", "钱包余额", "ACCENT_YELLOW"),
)
_MAX_X_TICKS = 6
_MAX_Y_TICKS = 5
#: 「总」档的取数天数（10 年，等价于「全部历史」）
_RANGE_ALL_DAYS = 3650
_RANGE_LABELS: tuple[str, ...] = ("近 7 天", "本月", "本年", "总")
_RANGE_ALL_INDEX = 3
#: 折线图空态：QML 只看 `isEmpty`；`xLines` 必须与正常态同键（否则空态取到 undefined）
_EMPTY_PLOT: dict = {
    "isEmpty": True,
    "count": 0,
    "series": [],
    "xLines": [],
    "xTicks": [],
    "yTicks": [],
}
#: 空态占位文案。**必须写清「从首次记录开始累积」**：本功能刚上线时只有零星几个点，
#: 不写用户会以为坏了。
_EMPTY_ASSET_TEXT = "还没有资产快照 —— 数据从首次记录开始按天累积，导入一次挂单或填写钱包余额即可记下今天这一天。"

# ── 挂单 ────────────────────────────────────────────────────
#: 两张表各自维护表头（**没有「方向」列** —— 表本身就是方向）
#: 「角色」在末尾：ESI 汇总全部已绑定角色，不标归属就分不清挂单是谁的。
_ORDER_HEADS_LIST: tuple[str, ...] = ("物品", "价格", "剩余/总量", "位置", "角色")
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
    "char_id",
    "is_corp",
    "imported_at",
)
_TOKEN_PLAIN = "TEXT_PRIMARY"
_EMPTY_BUY_TEXT = "暂无买单记录"
_EMPTY_SELL_TEXT = "暂无卖单记录"
#: 挂单导出目录**固定用游戏默认目录**（用户要求：不再提供自定义目录输入框）。
#: `settings.json` 里若还留着旧键 `order_export_dir`，本模块已不再读取。
_DEFAULT_EXPORT_DIR_TEXT = "默认目录（我的文档\\EVE\\logs\\Marketlogs）"
_EMPTY_ORDER_SUMMARY = "暂无挂单记录，点「读取订单」从游戏「钱包 → 订单」的导出文件导入"

#: 惰性导入失败只提示一次（每 60s 刷一次也不刷屏）
_MISSING_LOGGED: set[str] = set()


# ════════════════════════════════════════════════════════════
#  惰性服务入口（缺失时不崩）
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


def _char_names() -> dict[int, str]:
    """`char_id` → 角色名（取自 `esi_tokens` 的绑定行），供挂单表标注归属。

    日志导入的 `charID` 若从没绑定过 ESI 就查不到，调用方回退显示 `#<id>`。
    这里的 `except Exception` 吞的是「读绑定表/导入 aiohttp 链路」的失败（表不存在、
    库被占用等）—— 挂单列表不该因为读不到名字就整张画不出来，退化成编号即可。
    """
    try:
        from ui_qml.workers.esi_skill_worker import list_token_rows

        return {int(r["character_id"]): str(r["character_name"] or "") for r in list_token_rows()}
    except Exception:
        log.exception("角色名读取失败（挂单归属列退化为编号）")
        return {}


def _wallet_breakdown(payload: dict) -> str:
    """ESI 同步后的钱包构成文案。

    **必须说清「角色 / 军团」的拆分**：余额看着少的时候（钱在军团账户上），
    用户第一反应就是「是不是没把钱加起来」—— 这句话直接回答它，而不是让他去猜。
    """
    total = payload.get("wallet_total")
    if total is None:
        return "；钱包未更新"
    if payload.get("include_corp"):
        corp = float(payload.get("corp_total") or 0.0)
        return f"；钱包 {float(total):,.2f}（军团 {corp:,.2f} + 角色 {float(total) - corp:,.2f}）"
    return f"；钱包 {float(total):,.2f}（仅角色，未含军团钱包）"


def _open_change_dialog(
    rows: list[dict], parent: Any, wallet: float, ledger_only: bool = False
) -> tuple[list[dict], bool]:
    """弹「订单变动」确认框（模块级薄封装 → 测试可 monkeypatch，不开真窗口）。"""
    from ui_qml.bridge.order_change_bridge import OrderChangeQmlDialog

    return OrderChangeQmlDialog.confirm(parent, rows, wallet=wallet, ledger_only=ledger_only)


def _user_conn() -> Any:
    """user.db 连接上下文（测试替换点）。"""
    return get_container().db.connect("user")


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
         xLines: [{pos}], xTicks / yTicks: [{pos, label}]}

    - `xLines` = **全部**数据点的 x（每点一根竖线）；`xTicks` 采样 ≤ `_MAX_X_TICKS`，**只用于标签**。
      （`pick_indices` 的 `round + set` 去重会漏点：count=7 → 下标 3 无刻度，竖线就少一根。）
    - `count > _MAX_X_TICKS` 时 `xTicks` 的标签缩成 `MM-DD`，避免 7 个全日期标签互相压字。

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
    #: `count > _MAX_X_TICKS` 时标签缩成 MM-DD：7 个全日期（"2026-09-22"）在约 416px 的
    #: 中间面板里会互相压字。**只影响文案**，竖线位置由全量的 `xLines` 给。
    tick_texts = [(text[5:] if len(text) >= 10 else text) if count > _MAX_X_TICKS else text for text in dates]
    return {
        "isEmpty": False,
        "count": count,
        "series": series,
        #: **每一个数据点一根竖线**（`xTicks` 是采样 ≤6，会漏点：count=7 时下标 3 被丢掉，
        #: 用户看到的就是「9月22号那一条的竖线没有了」）。形状与 xTicks 同族，只带位置。
        "xLines": [{"pos": x} for x in xs],
        #: `xTicks` 语义收窄为**只用于标签**（QML 侧不再拿它画竖线）。
        "xTicks": [{"pos": xs[i], "label": tick_texts[i]} for i in pick_indices(count, _MAX_X_TICKS)],
        "yTicks": [
            {"pos": pos, "label": format_axis_value(value)}
            for value, pos in zip(tick_values, map_values(tick_values, lo, hi), strict=True)
        ],
    }


# ════════════════════════════════════════════════════════════
#  订单变动分类（纯函数，可脱离 Qt 单测）
# ════════════════════════════════════════════════════════════


def classify_order_changes(
    before: Mapping[int, Mapping[str, Any]], after: Mapping[int, Mapping[str, Any]]
) -> list[dict]:
    """两次导入的挂单快照 → 变动条目（纯函数）。

    Args:
        before: 本次导入**之前**库里的挂单 `{order_id: 记录}`。
        after: 本次导入**之后**库里的挂单 `{order_id: 记录}`。

    Returns:
        `[{order_id, name, is_buy, price, volume, delta, kind}]`，``kind`` ∈
        ``gone``（老单在本次文件里没了 → 多半成交或撤单，数量 = 原剩余量）、
        ``partial``（还在但剩余量变少 → 部分成交，数量 = 两次之差）。
        **新增的订单不算变动**：那是新挂出去的，钱包在挂单时就已经变过了。

    ``delta`` 是「若判为成交」对钱包的影响：卖出 +金额、买入 −金额，**不扣税费**
    （中介费/销售税在游戏里已经各自结掉了；用户确认口径）。
    """
    changes: list[dict] = []
    for order_id, old in before.items():
        new = after.get(order_id)
        old_remain = int(old.get("volume_remain") or 0)
        price = float(old.get("price") or 0.0)
        is_buy = bool(old.get("is_buy"))
        if new is None:
            if old_remain <= 0:
                continue
            changes.append(_change_row(order_id, old, "gone", old_remain, price, is_buy))
            continue
        new_remain = int(new.get("volume_remain") or 0)
        sold = old_remain - new_remain
        if sold > 0:
            changes.append(_change_row(order_id, old, "partial", sold, price, is_buy, new_remain))
    return changes


def _change_row(
    order_id: int,
    record: Mapping[str, Any],
    kind: str,
    volume: int,
    price: float,
    is_buy: bool,
    new_remain: int | None = None,
) -> dict:
    name = str(record.get("type_name") or "") or (f"#{int(record.get('type_id') or 0)}")
    return {
        "order_id": int(order_id),
        "name": name,
        "is_buy": 1 if is_buy else 0,
        "price": price,
        "volume": int(volume),
        # 成交对钱包的影响：卖出 +、买入 −（不扣税费）
        "delta": round(int(volume) * price * (-1.0 if is_buy else 1.0), 2),
        "kind": kind,
        #: 部分成交后挂单还剩多少（`gone` 为 None → 成交即删行）
        "new_remain": new_remain,
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
        self._occupancy_by_char: list[dict] = []
        self._occupancy_summary = ""
        self._series_rows: list[dict] = []  # 当前区间内的快照行
        self._baseline_row: dict | None = None  # 涨跌基准行（窗口之外紧邻的那条）
        self._all_series_rows: list[dict] = []  # 全量快照行（切区间时不重查）
        self._plot: dict = dict(_EMPTY_PLOT)
        self._visible: dict[str, bool] = {key: True for key, _label, _token in _SERIES}
        self._range_index = 0
        self._wallet_text = ""
        self._wallet_loaded = False
        self._order_records: list[dict] = []
        self._buy_rows: list[dict] = []
        self._sell_rows: list[dict] = []
        self._orders_loaded = False
        self._pending_changes: list[dict] = []  # 最近一次导入产生的变动（待用户确认）
        self._esi_worker: Any = None  # 在途的 ESI 钱包/挂单拉取线程（页面销毁时 shutdown）
        self._busy = False
        self._status = "就绪"
        # 指纹缓存（refresh 幂等：没变就不重算、不发 changed）
        self._fingerprint: tuple | None = None

    # ── 产线详情 ──────────────────────────────────────────────

    @Property(list, notify=changed)
    def occupancyRows(self) -> list[dict]:
        """每角色一行的占用数据（形状与 `launcher_bridge.occupancyRows` **逐字一致**）。

        `[{"name", "nameWidth", "lines": [{"label", "color", "active", "max", "cap"}],
        "statusText", "statusColor", "slotTotal"}]` —— 产线启动小助手那套的共用契约，
        仪表盘不吃它，但保留它成本极低、且是「同一份算法两种形状」的凭证。

        **必须是 Property 而不是 Slot**：QML 的绑定不追踪 Slot 内部的属性读取，
        写成 `occupancyRows()` 调用的话面板不会随 `changed` 自动刷新
        （本仓既有教训，见 `query_bridge.py` 的 `sortColumn` 注释）。
        """
        return [dict(row) for row in self._occupancy_rows]

    @Property(str, notify=changed)
    def occupancySummary(self) -> str:
        return self._occupancy_summary

    @Property(list, notify=changed)
    def occupancyByChar(self) -> list[dict]:
        """**每人物一块**的占用数据（仪表盘左栏用，见 `_build_occupancy_by_char`）。

        `[{"name", "statusText", "statusColor",
           "lines": [{"key", "label", "color", "active", "max", "cap",
                      "readyN", "readyText", "freeN", "detailText"}]}]`

        `cap` 是**各人物该线型上限之和**（进度条分母，让所有人的条子同长可比），
        `max` 是该人物自己的上限；`readyText` 是该人物该线型**待下线**的计划数
        （用户明确要求「提示带下线多少」），`freeN` 是「还能再上几条」（空槽位数）。
        """
        return [dict(row) for row in self._occupancy_by_char]

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
        """「资产（表格显示）」5 行：最新值 + 相对**档位起点之前**最近一条快照的变化量与百分比。

        基准由 `_pick_baseline` 挑（近 7 天 → 7 天前那条、本月 → 上月最后一条、
        本年 → 去年最后一条、总 → 首条）。窗口之前没有快照时退回区间内最早的一条
        （「不满 7 天就有几天算几天」），只有一个点可看时才给「—」。
        """
        _dates, values = split_series(self._series_rows)
        base_row = self._baseline_row
        # 基准就是最新那个点（全部历史只有一个点）→ 没有可比的历史，整列给「—」
        if base_row is not None and base_row.get("date") == (_dates[-1] if _dates else None):
            base_row = None
        rows: list[dict] = []
        for key, label, token in _SERIES:
            series_values = values.get(key, [])
            latest = series_values[-1] if series_values else None
            if latest is None or base_row is None:
                delta_text, delta_pos = "—", True
            else:
                base = _as_float(base_row.get(key))
                delta = latest - base
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

    @Slot()
    def reloadAssets(self) -> None:
        """「刷新」按钮：**强制**重读全部快照并重画（不吃指纹缓存）。

        与定时器的 `refresh()` 分开：`refresh()` 幂等且便宜（指纹没变就什么都不做），
        而这个按钮就是「我现在就要看到最新的」—— 用户手动点了，重算一次是预期行为。
        """
        self._refresh_snapshots(force=True)
        self._ensure_wallet(force=True)
        self._fingerprint = None  # 让下一次 refresh() 重新评估
        self._status = f"资产已刷新（{len(self._series_rows)} 天记录）"
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
        tail = self._save_wallet(value)
        if tail is None:  # `_save_wallet` 已写好失败文案
            self.changed.emit()
            return
        self._status = f"已记录钱包余额 {value:,.2f} ISK {tail}"
        self.changed.emit()

    @Slot()
    def importWalletFromClipboard(self) -> None:
        """剪贴板里的「钱包 → 交易记录」→ 取最新一笔的余额，落库并记快照。

        金额列不是重点，**余额列**才是：它是逐笔累计后的实时余额，所以最新一笔的余额
        就是当前钱包余额。解析与取数见 `services.wallet_import`。
        """
        clipboard = QApplication.clipboard()
        raw = clipboard.text() if clipboard is not None else ""
        rows = parse_wallet_journal(raw)
        latest = latest_balance(rows)
        if latest is None:
            self._status = "剪贴板里没有可识别的交易记录 —— 请在游戏「钱包 → 交易记录」里 Ctrl+A/C 后再点"
            self.changed.emit()
            return
        value, when = latest
        tail = self._save_wallet(value)
        if tail is None:
            self.changed.emit()
            return
        self._status = f"已从剪贴板读取钱包余额 {value:,.2f} ISK（{len(rows)} 条流水，最新 {when}）{tail}"
        self.changed.emit()

    def _save_wallet(self, value: float) -> str | None:
        """落库 + 写资产快照，返回状态文案后缀；失败时返回 None（文案已写好）。"""
        svc = _asset_svc()
        if svc is None:
            self._status = "资产快照模块不可用：钱包余额未保存"
            return None
        try:
            svc.set_wallet_balance(value)
            snapshot_ok = self._record_snapshot(wallet=value)
        except Exception:
            log.exception("钱包余额保存失败 value=%s", value)
            self._status = "钱包余额保存失败，详见日志"
            return None
        self._wallet_text = f"{value:,.2f}"
        self._wallet_loaded = True
        self._refresh_snapshots()
        return "并写入资产快照" if snapshot_ok else "（资产快照写入失败，详见日志）"

    # ── 挂单 ──────────────────────────────────────────────────

    @Property(list, constant=True)
    def openOrderHeads(self) -> list[str]:
        """两张表共用的表头（**没有「方向」列** —— 表本身就是方向）。"""
        return list(_ORDER_HEADS_LIST)

    @Property(list, notify=changed)
    def buyOrderRows(self) -> list[dict]:
        self._ensure_orders()
        return [dict(row) for row in self._buy_rows]

    @Property(list, notify=changed)
    def sellOrderRows(self) -> list[dict]:
        self._ensure_orders()
        return [dict(row) for row in self._sell_rows]

    @Property(int, notify=changed)
    def buyOrderCount(self) -> int:
        self._ensure_orders()
        return sum(1 for r in self._order_records if r["is_buy"])

    @Property(int, notify=changed)
    def sellOrderCount(self) -> int:
        self._ensure_orders()
        return sum(1 for r in self._order_records if not r["is_buy"])

    @Property(str, constant=True)
    def buyEmptyText(self) -> str:
        return _EMPTY_BUY_TEXT

    @Property(str, constant=True)
    def sellEmptyText(self) -> str:
        return _EMPTY_SELL_TEXT

    @Property(str, notify=changed)
    def openOrderSummary(self) -> str:
        self._ensure_orders()
        if not self._order_records:
            return _EMPTY_ORDER_SUMMARY
        sell = self.sellOrderCount
        buy = self.buyOrderCount
        total = sum(float(r["price"]) * int(r["volume_remain"]) for r in self._order_records)
        parts = [
            f"{len(self._order_records)} 笔挂单",
            f"卖单 {sell}",
            f"买单 {buy}",
            f"挂单总额 {total:,.2f} ISK",
        ]
        if self._last_import_at:
            parts.append(f"本次导入 {self._last_import_at}")
        if self._pending_changes:
            parts.append(f"本次变动 {len(self._pending_changes)} 笔待确认")
        return " · ".join(parts)

    @Slot()
    def readOrders(self) -> None:
        """读游戏导出的订单文件 → 写 `open_orders` → 弹「订单变动」确认框 → 回写快照。

        找不到文件只给中文提示，**不抛异常、不清空已有列表**（用户可能只是还没导出）。
        目录**固定用游戏默认目录**（`order_export.find_latest_export(None)`）——
        用户要求去掉自定义目录输入框。
        """
        svc = _order_svc()
        if svc is None:
            self._status = "订单解析模块不可用（services/order_export.py 缺失）"
            self.changed.emit()
            return
        try:
            path = svc.find_latest_export(None)
        except Exception:
            log.exception("订单导出文件查找失败")
            self._status = f"订单导出文件查找失败，详见日志；当前目录 {_DEFAULT_EXPORT_DIR_TEXT}"
            self.changed.emit()
            return
        if not path:
            self._status = f"没找到订单导出文件：请先在游戏「钱包 → 订单」里点导出；当前目录 {_DEFAULT_EXPORT_DIR_TEXT}"
            self.changed.emit()
            return

        name = Path(str(path)).name
        # 比上次 ESI 同步还旧的导出文件**不许覆盖**：ESI 是权威源，用旧的盖新的会让
        # 变动识别拿旧文件和新数据做差 —— 挂单被判成「已成交」，**会误动钱包**。
        synced_at = get_esi_orders_synced_at()
        if synced_at:
            try:
                file_ts = datetime.fromtimestamp(Path(str(path)).stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            except OSError:
                file_ts = ""
            if file_ts and file_ts < synced_at:
                self._status = (
                    f"已跳过「{name}」——导出时间 {file_ts} 比上次 ESI 同步 {synced_at} 还旧，"
                    f"用旧的覆盖会把 ESI 拉到的挂单和成交判断弄错；请在游戏里重新导出"
                )
                self.changed.emit()
                return
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
        # 变动只在「本次覆盖到的归属组」内比较。挂单有两个来源（游戏日志 / ESI），
        # 一个账号还能绑多个角色，个人单与军团单又是两份独立导出 —— 拿全表做差会把
        # 别的组的挂单判成「已成交」，进而**错误增减钱包**。
        covered = {(int(r["char_id"]), int(r["is_corp"])) for r in records}
        # 写库前先取一份「旧快照」—— 变动分类要的正是「写前 / 写后」的差集。
        # **必须仍在 _write_orders 之前取**：写库会把归属列改写成新值，
        # 挪到写库之后取的话过滤条件会对存量行全中，等于没过滤、bug 原样回来。
        before = {
            int(r["order_id"]): r for r in self._snapshot_orders() if (int(r["char_id"]), int(r["is_corp"])) in covered
        }
        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._write_orders(records, imported_at)
        except sqlite3.Error:
            log.exception("挂单写入 user.db 失败 count=%s", len(records))
            self._status = "挂单写入本地库失败，详见日志"
            self.changed.emit()
            return

        after = {int(r["order_id"]): r for r in records}
        # 部分成交那行要留着（回写剩余量），所以 new_remain 随变动一起下发
        self._pending_changes = classify_order_changes(before, after)
        self._ensure_orders(force=True)
        snapshot_ok = self._record_snapshot()
        self._refresh_snapshots()
        skipped = f"，跳过 {int(unparsed)} 行" if unparsed else ""
        tail = "已记入资产快照" if snapshot_ok else "资产快照写入失败，详见日志"
        prefix = f"已从「{name}」导入 {len(records)} 笔挂单{skipped}，{tail}"
        # 有变动才弹「订单变动」确认框（确认框在桥里弹，QML 只调 readOrders）
        self._review_changes(prefix)
        self.changed.emit()

    # ── ESI：钱包余额 + 未结挂单 ──────────────────────────────

    @Slot()
    def syncOrdersFromEsi(self) -> None:
        """从 ESI 拉**全部已绑定角色**的钱包余额与未结挂单 → 写库 → 回写快照。

        与 `readOrders` 的本质区别：**这条路径不做变动推断**。ESI 给的钱包余额是
        绝对值、挂单是「该角色当前未结」的完整集，所以这里是**快照替换** ——
        钱包 `set_wallet_balance(合计)` 绝对覆盖，订单按 `(char_id, is_corp)` 组整体替换。
        **绝不能接 `_apply_outcomes` 的 `adjust_wallet_balance`**：那会把钱算两遍。
        """
        if self._busy:
            return
        from ui_qml.workers.esi_wallet_worker import EsiWalletOrdersWorker

        worker = EsiWalletOrdersWorker(parent=self)
        self._esi_worker = worker
        worker.result_signal.connect(self._on_esi_pulled)
        worker.finished_signal.connect(self._on_esi_finished)
        self._busy = True
        self._status = "正在从 ESI 同步钱包与挂单…"
        self.changed.emit()
        worker.start()

    @Slot(dict)
    def _on_esi_pulled(self, payload: dict) -> None:
        """worker 拉成功 → 落库。整体失败走 `_on_esi_finished`。"""
        records = [_normalize_order(r) for r in payload.get("orders") or []]
        records = [r for r in records if r["order_id"]]
        if records:
            self._fill_location_names(records)
            self._fill_type_names(records)
        covered = {(int(g[0]), int(g[1])) for g in payload.get("groups") or []}
        if not covered:
            self._status = "ESI 没返回任何可同步的角色组，已跳过"
            self.changed.emit()
            return
        # 变动识别：与上一次的结果（ESI 或日志）做差 —— 让「卖出 / 买到」在 ESI 路径
        # 上也不丢。**只认真实角色组**：无归属的历史行（char_id=0）是清理对象、
        # 不是「成交」，算进来会平白报一堆变动。快照必须取在替换**之前**。
        before = {
            int(r["order_id"]): r for r in self._snapshot_orders() if (int(r["char_id"]), int(r["is_corp"])) in covered
        }
        # 替换范围要连无归属的历史行一起清（char_id=0：v19→v20 加列时补的 0，或启发式
        # 解析的旧日志）。**不清就会变成幽灵卖单** —— 它们不属于本次任何角色组，永远
        # 不会被删；仍开着的会被主键 INSERT OR REPLACE 改写成真归属。
        try:
            self._replace_order_groups(covered | {(0, 0)}, records)
        except sqlite3.Error:
            log.exception("ESI 挂单写入 user.db 失败 count=%s", len(records))
            self._status = "ESI 挂单写入本地库失败，详见日志"
            self.changed.emit()
            return

        after = {int(r["order_id"]): r for r in records}
        # 行与钱包都已是 ESI 给的权威值 → 变动只落台账，**不调钱包**（见 ledger_only）
        self._pending_changes = classify_order_changes(before, after)

        wallet_total = payload.get("wallet_total")
        if wallet_total is not None:
            svc = _asset_svc()
            if svc is not None:
                try:
                    svc.set_wallet_balance(float(wallet_total))
                except Exception:
                    log.exception("ESI 钱包余额写入失败")

        self._ensure_orders(force=True)
        self._ensure_wallet(force=True)
        snapshot_ok = self._record_snapshot()
        self._refresh_snapshots()
        # 记下本次同步时刻：日志导入拿它挡住「比 ESI 还旧」的导出文件（见 readOrders）
        set_esi_orders_synced_at(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        tail = "已记入资产快照" if snapshot_ok else "资产快照写入失败，详见日志"
        chars = int(payload.get("chars") or 0)
        prefix = f"已从 ESI 同步 {chars} 个角色、{len(records)} 笔挂单，{tail}"
        prefix += _wallet_breakdown(payload)
        errors = [str(e) for e in payload.get("errors") or []]
        if errors:
            # 部分角色/军团失败：成功的照常写，这里明说哪几块没拉到
            prefix += f"；未同步：{'；'.join(errors)}"
        # 有变动才弹确认框（**只记台账，不动钱包** —— 余额已是 ESI 的绝对值）
        self._review_changes(prefix, ledger_only=True)
        self.changed.emit()

    @Slot(bool, str)
    def _on_esi_finished(self, ok: bool, message: str) -> None:
        self._busy = False
        if not ok:
            self._status = f"ESI 同步失败：{message or '未知错误'}"
        self.changed.emit()

    def _replace_order_groups(self, groups: set[tuple[int, int]], records: list[dict]) -> None:
        """按 `(char_id, is_corp)` 组整体替换：先删该组旧行，再写本次的完整集。

        只 UPSERT 不行：ESI 返回的是「当前未结」的完整集，已成交的旧行会永远留在表里
        （日志路径靠 `_apply_outcomes` 删掉已结束的，这条路径没有确认框）。
        `groups` 里含**同步成功但当前无挂单**的组 —— 少了它就会留下幽灵行。
        """
        if not groups:
            return
        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _user_conn() as conn:
            for char_id, is_corp in sorted(groups):
                conn.execute(
                    "DELETE FROM open_orders WHERE char_id = ? AND is_corp = ?",
                    (int(char_id), int(is_corp)),
                )
        if records:
            self._write_orders(records, imported_at)

    @Slot()
    def shutdown(self) -> None:
        """停掉在途的 ESI 拉取线程。**页面销毁（切页 / 关窗 / 退出）时必须调**。

        为什么必须：ESI 是阻塞式请求（超时 30 秒），本桥被销毁时 Qt 会去析构一个
        还在跑的 QThread —— 那是直接崩，**输出里连一行 traceback 都没有**
        （见 `docs/dev/flows.md` 的「在途取数线程必须在页面销毁时停」）。
        走 `detach_worker`：`requestInterruption()` 对阻塞请求无效，中断不了就摘出
        对话树保活，而不是 `terminate()`（那会连主线程一起锁死）。
        """
        from ui_qml.workers.lifecycle import detach_worker

        worker, self._esi_worker = self._esi_worker, None
        if worker is not None:
            detach_worker(worker)

    @Slot(result=list)
    def previewOrderChanges(self) -> list[dict]:
        """最近一次导入产生的变动（只读，供「重新打开确认框」之类的调用方用）。"""
        return [dict(row) for row in self._pending_changes]

    @Slot()
    def applyOrderChanges(self) -> None:
        """按变动条目的**默认处置**落账：增减钱包 + 落台账 + 清理/回写挂单 + 重记快照。

        与弹窗的配合：弹窗由 `readOrders` 走 `_review_changes` 打开、用户在里面逐条选，
        选定结果经 `_apply_outcomes` 处理；本槽是**没有弹窗时**（测试 / 无 GUI）的等价入口，
        一律按默认（成交）。
        """
        outcomes = [
            {
                "order_id": int(row["order_id"]),
                "outcome": "filled",
                "is_buy": int(row["is_buy"]),
                "price": float(row["price"]),
                "volume": int(row["volume"]),
                "delta": float(row["delta"]),
                "new_remain": row.get("new_remain"),
            }
            for row in self._pending_changes
        ]
        self._apply_outcomes(outcomes)

    def _apply_outcomes(self, outcomes: Sequence[Mapping[str, Any]], *, ledger_only: bool = False) -> None:
        """落账主体：钱包增减 → 台账 → 挂单清理/回写 → 快照。

        只有 ``outcome == "filled"`` 的条目动钱包；``cancelled``（手动撤销）只是把
        这笔从挂单列表里去掉。挂单清理按 ``new_remain`` 分流：

        - ``new_remain`` 有值（**部分成交**）→ 回写剩余量，行留在列表里；
        - ``new_remain`` 为 None（整笔消失）→ 删行。

        ``ledger_only=True``（ESI 同步路径）：**只落台账、不动钱包**。那一路的行与余额
        都已经是 ESI 给的权威值，再按成交加减一次会把钱算两遍。行的清理/回写会跑成
        空操作（组替换时已经写成 ESI 的值），留着不碍事。
        """
        if not outcomes:
            self._status = "没有需要应用的订单变动"
            self.changed.emit()
            return
        wallet_delta = round(sum(float(o.get("delta") or 0.0) for o in outcomes), 2)
        filled = [o for o in outcomes if str(o.get("outcome")) == "filled"]
        try:
            with _user_conn() as conn:
                for outcome in outcomes:
                    order_id = int(outcome["order_id"])
                    remain = outcome.get("new_remain")
                    if remain is None:
                        conn.execute("DELETE FROM open_orders WHERE order_id = ?", (order_id,))
                    else:
                        conn.execute(
                            "UPDATE open_orders SET volume_remain = ? WHERE order_id = ?",
                            (int(remain), order_id),
                        )
        except sqlite3.Error:
            log.exception("订单变动落库失败 count=%s", len(outcomes))
            self._status = "订单变动应用失败（本地库写入异常，详见日志）"
            self.changed.emit()
            return
        self._write_order_events(outcomes)
        if filled and wallet_delta and not ledger_only:
            svc = _asset_svc()
            if svc is not None:
                try:
                    svc.adjust_wallet_balance(wallet_delta)
                    self._wallet_loaded = False  # 让 `walletText` 重读
                except Exception:
                    log.exception("钱包余额按订单变动调整失败 delta=%s", wallet_delta)
                    self._status = "订单变动已应用，但钱包余额调整失败（详见日志）"
                    self._ensure_orders(force=True)
                    self.changed.emit()
                    return
        self._pending_changes = []
        self._ensure_orders(force=True)
        snapshot_ok = self._record_snapshot()
        self._refresh_snapshots(force=True)
        tail = "并重记资产快照" if snapshot_ok else "，但资产快照写入失败，详见日志"
        if ledger_only:
            self._status = (
                f"已把 {len(outcomes)} 笔变动记入台账（成交 {len(filled)} 笔；余额由 ESI 直接给，未加减）{tail}"
            )
        else:
            self._status = (
                f"已处理 {len(outcomes)} 笔订单变动（成交 {len(filled)} 笔，钱包 {wallet_delta:+,.2f} ISK）{tail}"
            )
        self.changed.emit()

    def _write_order_events(self, outcomes: Sequence[Mapping[str, Any]]) -> None:
        """落 `order_events` 台账。**失败只记日志**：台账丢一条不该拦住钱包落账。"""
        applied_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with _user_conn() as conn:
                if not _table_exists(conn, "order_events"):
                    return
                conn.executemany(
                    "INSERT OR REPLACE INTO order_events "
                    "(order_id, applied_at, outcome, is_buy, price, volume, delta) "
                    "VALUES (?,?,?,?,?,?,?)",
                    [
                        (
                            int(o["order_id"]),
                            applied_at,
                            str(o.get("outcome") or ""),
                            int(o.get("is_buy") or 0),
                            float(o.get("price") or 0.0),
                            int(o.get("volume") or 0),
                            float(o.get("delta") or 0.0),
                        )
                        for o in outcomes
                    ],
                )
        except sqlite3.Error:
            log.exception("订单变动台账写入失败 count=%s", len(outcomes))

    def _review_changes(self, prefix: str, *, ledger_only: bool = False) -> None:
        """导入成功后的收尾编排：有变动才弹「订单变动」确认框（**确认框在桥里弹**）。

        没变动（或弹不出来）时只把导入结果写进 `_status`。用户点「取消」= 什么都不做，
        变动条目留在 `_pending_changes` 里，下次导入会重新算。

        `ledger_only=True`（ESI 同步路径）时确认框只把选择记进台账、**不动钱包**。
        """
        rows = list(self._pending_changes)
        if not rows:
            self._status = prefix
            return
        wallet = _asset_svc()
        wallet_value = 0.0
        if wallet is not None:
            try:
                wallet_value = float(wallet.get_wallet_balance() or 0.0)
            except Exception:
                log.exception("钱包余额读取失败（订单变动预计值将按 0 起算）")
        try:
            outcomes, accepted = _open_change_dialog(rows, self._host_widget(), wallet_value, ledger_only)
        except Exception:
            log.exception("订单变动确认框弹出失败，变动已保留待下次确认")
            self._status = f"{prefix} 有 {len(rows)} 笔变动待确认（弹窗失败，详见日志）"
            return
        if not accepted:
            self._status = f"{prefix} 有 {len(rows)} 笔变动未处理（已保留，下次导入会重新提示）"
            return
        self._apply_outcomes(outcomes, ledger_only=ledger_only)
        if self._pending_changes:  # 落账失败时它已写明原因，别覆盖
            return
        self._status = f"{prefix} {self._status}"

    def _snapshot_orders(self) -> list[dict]:
        """当前 `open_orders` 全量行（变动分类的「前 / 后」两份快照都取自它）。"""
        try:
            with _user_conn() as conn:
                if not _table_exists(conn, "open_orders"):
                    return []
                raw = conn.execute(f"SELECT {', '.join(_ORDER_DB_COLUMNS)} FROM open_orders").fetchall()
        except sqlite3.Error:
            log.exception("挂单快照读取失败")
            return []
        return [_normalize_order(_row_to_dict(row)) for row in raw]

    # ── 状态 ──────────────────────────────────────────────────

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=changed)
    def statusText(self) -> str:
        return self._status

    @Property(bool, notify=changed)
    def includeCorpWallet(self) -> bool:
        """ESI 同步是否合计军团钱包（默认关）。

        默认关的两个理由：军团钱包是**共享账户**、不是个人净资产；读它还要角色有
        军团会计类角色（没有就 403），并额外要一个 scope。
        """
        return bool(get_include_corp_wallet())

    @Slot(bool)
    def setIncludeCorpWallet(self, value: bool) -> None:
        """开关「含军团钱包」。**开启后需重新授权一次**（军团钱包是独立 scope）。"""
        set_include_corp_wallet(bool(value))
        self._status = (
            "已开启「含军团钱包」—— 下次同步会要求重新授权（军团钱包是独立权限）"
            if value
            else "已关闭「含军团钱包」，钱包余额只统计角色身上"
        )
        self.changed.emit()

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
        """便宜档指纹：计划字段集 + 角色技能 + 快照/挂单行数 + 本桥本地状态。

        **不再读机库库存**：库存只为原来的「快捷操作」列表服务（判 `material_short`），
        那一块删掉之后没有任何属性依赖它 —— 留着等于每 60s 白跑一遍全机库查询。
        """
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
                        str(p.get("category") or ""),
                    )
                    for p in plans
                )
            ),
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
        """算两份占用数据：`occupancyRows`（按人物，与小助手同形状）与
        `occupancyByChar`（按人物分块 + 每型一行，仪表盘左栏用）。"""
        usage = active_lines_by_category(plans)
        chars_data = (load_all_data() or {}).get("characters", {}) or {}
        chars = list(get_character_list())
        for char in usage:
            if char and char not in chars:
                chars.append(char)

        if not chars:
            self._occupancy_summary = "（无人物配置，请在人物设置中添加）"
            self._occupancy_rows = []
            self._occupancy_by_char = []
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
        self._occupancy_by_char = self._build_occupancy_by_char(per_char, plans)

    def _build_occupancy_by_char(
        self, per_char: list[tuple[str, dict[str, tuple[int, int]]]], plans: list[dict]
    ) -> list[dict]:
        """**每人物一块，块内制造/科研/反应各一行** —— 仪表盘左栏用这个形状。

        用户要求「每个人物都有制造、科研、反应三行，然后提示带下线多少」。
        竖排列出来以后左栏下半的空白就被填满了，人物多了靠外层 ListView 滚动。

        - ``cap``：各人物该线型上限中的**最大值** —— 所有人共用同一个分母（槽位同宽、
          条子等长可比）。早先取的是**之和**，于是单个人物跑满自己那 11 条线时
          只点亮了整条的一半（分母是所有人加起来的 22）。
        - ``max``：该人物自己的上限（上限内的格数）。
        - ``readyN``：该人物该线型下 **待下线**（``status=='ready'``）的计划数，
          取自已加载的计划表（`load_plans_for_wizard` 已 enrich ``category``），不额外查库。
        - ``freeN``：还能再上几条线（上限 − 已占，负数按 0）。
        """
        ready = self._ready_count_by_char_line(plans)
        cap_by_line: dict[str, int] = {
            line: max((int(per_line.get(line, (0, 0))[1]) for _char, per_line in per_char), default=0)
            for line in _LINE_TYPES
        }
        blocks: list[dict] = []
        for char, per_line in per_char:
            status_text, status_token = self._char_status(per_line)
            lines_data: list[dict] = []
            for line in _LINE_TYPES:
                active, maximum = per_line.get(line, (0, 0))
                ready_n = int(ready.get((char or "", line), 0))
                lines_data.append(
                    {
                        "key": str(line),
                        "label": line_label(line),
                        "color": self._series_color(_LINE_COLORS[line]),
                        "active": int(active),
                        "max": int(maximum),
                        "cap": int(cap_by_line.get(line, maximum)),
                        "readyN": ready_n,
                        "readyText": f"待下线 {ready_n}" if ready_n else "",
                        "freeN": max(int(maximum) - int(active), 0),
                        "detailText": f"{line_label(line)} 已占 {int(active)} / 上限 {int(maximum)}"
                        + (f" · 待下线 {ready_n}" if ready_n else "")
                        + f" · 空闲 {max(int(maximum) - int(active), 0)}",
                    }
                )
            blocks.append(
                {
                    "name": char or "(未分配)",
                    "statusText": status_text,
                    "statusColor": self._series_color(status_token),
                    "lines": lines_data,
                }
            )
        return blocks

    @staticmethod
    def _ready_count_by_char_line(plans: list[dict]) -> dict[tuple[str, str], int]:
        """`{(人物, 线型): 待下线计划数}` —— 用计划表自己的 `category` → 线型映射。"""
        from services.char_capacity import capacity_line_for_category

        counts: dict[tuple[str, str], int] = {}
        for plan in plans:
            if str(plan.get("status") or "").lower() != "ready":
                continue
            char = str(plan.get("char_name") or "").strip()
            line = capacity_line_for_category(str(plan.get("category") or ""))
            counts[(char, line)] = counts.get((char, line), 0) + 1
        return counts

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
        self._baseline_row = self._pick_baseline(start)
        self._plot = asset_plot(self._series_rows, self._visible, self._series_colors())

    def _pick_baseline(self, start: date | None) -> dict | None:
        """涨跌基准行 —— **区间起点之前**最近的一条快照。

        「近 7 天」的窗口是「今天往前 7 天」，但窗口**首点**那天只算 6 天前；
        拿它当基准，用户选 7 天看到的却是 6 天的涨跌。所以基准取窗口之外紧邻的那一条：
        近 7 天 → 7 天前那条、本月 → 上月最后一条、本年 → 去年最后一条（「总」没有起点，
        仍取首条）。

        窗口之前一条都没有（新库 / 数据还没攒够）时退回区间内最早的一条 ——
        「不满 7 天就有几天算几天」，由 `assetSummaryRows` 按「基准与最新是不是同一个点」
        决定要不要给「—」。
        """
        if not self._series_rows:
            return None
        if start is not None:
            earlier: list[tuple[date, Mapping[str, Any]]] = []
            for row in self._all_series_rows:
                parsed = _parse_date(row.get("date"))
                if parsed is not None and parsed < start:
                    earlier.append((parsed, row))
            if earlier:
                return dict(max(earlier, key=lambda pair: pair[0])[1])
        return dict(self._series_rows[0])

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

    def _ensure_orders(self, force: bool = False) -> None:
        """读 `open_orders` → 拆成买单 / 卖单两组单元格行（两张表各吃一份）。"""
        if self._orders_loaded and not force:
            return
        self._orders_loaded = True
        try:
            with _user_conn() as conn:
                if not _table_exists(conn, "open_orders"):
                    self._order_records = []
                    self._buy_rows = []
                    self._sell_rows = []
                    return
                raw = conn.execute(
                    f"SELECT {', '.join(_ORDER_DB_COLUMNS)} FROM open_orders ORDER BY order_id DESC"
                ).fetchall()
        except sqlite3.Error:
            log.exception("挂单列表读取失败")
            return
        self._order_records = [_normalize_order(_row_to_dict(row)) for row in raw]
        self._order_records = [r for r in self._order_records if r["order_id"]]
        char_names = _char_names()
        self._buy_rows = self._order_cell_rows((r for r in self._order_records if r["is_buy"]), char_names)
        self._sell_rows = self._order_cell_rows((r for r in self._order_records if not r["is_buy"]), char_names)
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
    def _order_cell_rows(records: Any, char_names: Mapping[int, str] | None = None) -> list[dict]:
        """挂单 → 单元格行（形状同 `order_popup_bridge.order_rows`，QML 侧表组件直接吃）。

        **不含「方向」列**：买单 / 卖单各有一张表，方向由表本身承载。
        `records` 可以是任意可迭代（调用方传的是生成器，一次遍历完）。
        `char_names` 是 `char_id → 角色名`（ESI 汇总多角色时标注归属）；查不到就显示
        `#<id>`，**`char_id` 为 0（老日志的启发式解析）显示「—」而不是「角色 #0」**。
        """
        rows: list[dict] = []
        for record in records:
            location = str(record["location_name"] or "")
            if not location:
                location = f"#{int(record['location_id'])}" if record["location_id"] else "—"
            name = str(record["type_name"] or "") or (f"#{int(record['type_id'])}" if record["type_id"] else "—")
            char_id = int(record.get("char_id") or 0)
            owner = ((char_names or {}).get(char_id) or f"#{char_id}") if char_id else "—"
            rows.append(
                {
                    "cells": [
                        cell(name, _TOKEN_PLAIN),
                        cell(f"{float(record['price']):,.2f}", _TOKEN_PLAIN),
                        cell(f"{int(record['volume_remain']):,}/{int(record['volume_total']):,}", _TOKEN_PLAIN),
                        cell(location, _TOKEN_PLAIN),
                        cell(owner, _TOKEN_PLAIN),
                    ]
                }
            )
        return rows


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
        "char_id": _as_int(row.get("char_id")),
        "is_corp": _as_int(row.get("is_corp")),
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
