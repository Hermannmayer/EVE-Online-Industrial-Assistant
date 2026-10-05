"""关注（价格监控）Tab 的 bridge —— QML 与 `services.watchlist_manager` 之间的唯一通道。

对照的 Widgets 版是 `ui_pyside6/views/watchlist_view.py`（已随批次 7.5 删除）。

页面结构（见 `docs/dev/market-monitor-plan.md` 4.2）：**左窄列表 + 右详情**。
本桥提供两块数据：

1. 列表侧：`model` / `columns` / `sortOptions` / `sortIndex`（排序 + 既有增删改阈值）；
2. 详情侧：`detail`（价格对比表）+ `priceSeries` / `volumeSeries` / `chartLabels`（主物品折线）
   + `materialRows` / `materialSeries`（勾选「显示制造材料」后的 BOM 展开与归一化折线）。

**折线的时间粒度**（`rangeLabels` / `rangeIndex` / `setRangeIndex`）：近 7/30/90/180 天，
默认 180。切粒度**只切已装配好的点**（`chart_points` 的交易日切尾 + 材料序列切尾），
不重读 DB、不发 ESI —— 用户口径：「如果我想看近 7 日或者近 30 天的，这个时间粒度没有筛选」。
粒度状态由本桥自己持有（与 `market_pulse_bridge` 同构但互不相干，**不 import 它的常量**）。

**阈值设置改在 QML 里做**：原版为它内联了一个 `QDialog`（`_set_threshold`），
迁到 QML 后由页面里的小弹层 + `setThreshold(row, kind, value)` 承担 ——
比让 QML 去调一个 Widgets 对话框干净，也少一个阶段 4 的对话框。
值 ≤ 0 表示清除该阈值（与原版 `value if value > 0 else None` 一致）。

**口径（贯穿本文件，UI 上要标出来）**：

- 「当前 / 加入时」= **挂单价**（`market_prices.sell_price` / `watchlist_items.added_price`）；
- 「30/90/180 天前」= **成交均价**（`price_history.average`）——
  这两列口径不同，涨跌幅只作参照，页面上有说明文字；
- 制造材料只有 **挂单价**（`market_volume_snapshots.sell_price`，每次「更新价格」写一条当日快照），
  材料折线与材料表都用它，本物品在材料图里也用同一口径，好让归一化后的相对走势可比。

**缺数据一律 `—`，不用 0 冒充**（0 在挂单价里的含义是「没有挂单」）。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core.constants import HUB_NAMES, TRADE_HUB_IDS
from ui_qml.models.watchlist_qml_model import DASH, WatchlistQmlModel
from ui_qml.theme import registry as theme

__all__ = [
    "DEFAULT_RANGE_INDEX",
    "HISTORY_OFFSETS",
    "MAX_MATERIAL_SERIES",
    "RANGE_LABELS",
    "RANGE_OPTIONS",
    "SORT_MODES",
    "WatchlistBridge",
    "bom_nodes",
    "chart_points",
    "comparison_rows",
    "load_materials",
    "nearest_price",
    "read_history",
    "read_snapshots",
    "rise_pct",
    "sort_rows",
]

#: 价格变化的轮询间隔（对齐 Widgets 版的 60s）
CHECK_INTERVAL_MS = 60_000

_HUBS = list(TRADE_HUB_IDS.keys())

#: 左侧列表的排序模式（`sortIndex` 的取值，QML 直接显示）
SORT_MODES = ("添加时间", "涨幅", "阈值触发")

#: 右侧对比表的历史档位（**日历天**；不做「1 年前」——写入按 180 天裁剪）
HISTORY_OFFSETS = (30, 90, 180)

#: 档位取数容差：目标日 ± 这么多天内有记录才算「那天前后有价」。
#: 冷门物品几个月没成交时，不拿更早的记录冒充「30 天前」——那会算出一个假跌幅。
HISTORY_TOLERANCE_DAYS = 15

#: 折线窗口（天）
CHART_DAYS = 180

#: 折线图的时间粒度（`rangeIndex` 的下标）。与大盘页（`market_pulse_bridge`）同构，
#: 但**本桥自己持有**这份状态，不 import 它的常量 —— 两个页面的粒度互不影响。
#: 切粒度只切已装配好的点，不重读 DB、不发 ESI。
RANGE_OPTIONS: tuple[int, ...] = (7, 30, 90, CHART_DAYS)
RANGE_LABELS: tuple[str, ...] = ("近 7 天", "近 30 天", "近 90 天", "近 180 天")
#: 默认 180 天（与 `CHART_DAYS` 的加载窗口一致）
DEFAULT_RANGE_INDEX = 3

#: BOM 逐级展开的默认层级（0 = 本物品，1 = 直接材料，2 = 二级材料）
MATERIAL_DEPTH = 2

#: 材料折线最多画几条（表里不受限，折线多了读不出来）
MAX_MATERIAL_SERIES = 8

#: 材料折线调色板 —— 只从 theme registry 取（铁律：颜色不许写字面量）
_SERIES_TOKENS = (
    "ACCENT_ORANGE",
    "ACCENT_GREEN",
    "ACCENT_PURPLE",
    "ACCENT_RED",
    "ACCENT_YELLOW",
    "ACCENT_CYAN",
)

#: 一次 SQL 里 `IN (...)` 的参数个数上限（SQLite 变量上限的保守取值，与 price_history 同口径）
_SQL_PARAM_CHUNK = 900


# ════════════════════════════════════════════════════════════
#  纯函数（排序 / 对比表 / 折线取点）—— 无 DB、无 Qt，可直接测
# ════════════════════════════════════════════════════════════


def _num(value: Any) -> float | None:
    """价格取数：None / 非数 / ≤0 都算「没有」。

    挂单价 0 的含义是**没有挂单**，不是「卖 0 ISK」，所以按缺失处理（显示 `—`）。
    """
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _fmt_price(value: float | None) -> str:
    return DASH if value is None else f"{value:,.2f}"


def _fmt_delta(value: float | None) -> str:
    return DASH if value is None else f"{value:+,.2f}"


def _fmt_pct(value: float | None) -> str:
    return DASH if value is None else f"{value:+.1f}%"


def _tid(row: dict[str, Any]) -> int:
    try:
        return int(row.get("type_id") or 0)
    except (TypeError, ValueError):
        return 0


def rise_pct(row: dict[str, Any]) -> float | None:
    """「加入以来涨幅」（%）：当前卖挂单价相对 `added_price` 的变化。

    任一缺失 → None（显示 `—`）。`added_price` 是 WP1 迁移加的列；迁移还没跑、
    或加入时价格库里没有该物品 → 该键为 None，**不拿 0 冒充**。
    """
    cur = _num(row.get("sell_price"))
    base = _num(row.get("added_price"))
    if cur is None or base is None:
        return None
    return (cur - base) / base * 100.0


def _triggered(row: dict[str, Any]) -> bool:
    """阈值是否触发（与模型行底色、状态栏计数同口径）。"""
    buy_thresh = row.get("buy_threshold")
    sell_thresh = row.get("sell_threshold")
    buy_price = row.get("buy_price")
    sell_price = row.get("sell_price")
    return bool(
        (buy_thresh is not None and buy_price and buy_price <= buy_thresh)
        or (sell_thresh is not None and sell_price and sell_price >= sell_thresh)
    )


def sort_rows(
    rows: list[dict[str, Any]],
    mode: int,
    rise: dict[int, float | None] | None = None,
) -> list[dict[str, Any]]:
    """左列表的三种排序；**稳定排序**，键缺失的一律排最后并保持原有相对顺序。

    - `0` 添加时间（新 → 旧；`created_at` 缺失视为最早）
    - `1` 涨幅（高 → 低；涨幅来自 `rise` = `{type_id: pct}`，算不出排最后）
    - `2` 阈值触发（触发的在前，组内按添加时间新 → 旧）
    """
    items = list(rows)
    index = int(mode)
    if index == 1:
        table = rise or {}

        def _rise_key(row: dict[str, Any]) -> tuple[bool, float]:
            value = table.get(_tid(row))
            return (value is None, -(value if value is not None else 0.0))

        return sorted(items, key=_rise_key)
    if index == 2:
        # 两趟稳定排序：先按时间新→旧，再把触发的整组提到前面（组内保持时间序）
        by_time = sorted(items, key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return sorted(by_time, key=lambda r: not _triggered(r))
    return sorted(items, key=lambda r: str(r.get("created_at") or ""), reverse=True)


def nearest_price(
    points: Iterable[tuple[str, float]],
    offset: int,
    today: date | None = None,
) -> float | None:
    """序列里「`offset` 天前 ± `HISTORY_TOLERANCE_DAYS` 天」内**离目标最近**的一条价。

    窗口里没有记录 → None（显示 `—`）。
    """
    target = (today or date.today()) - timedelta(days=int(offset))
    best: tuple[int, float] | None = None
    for day, value in points:
        try:
            day_date = date.fromisoformat(str(day)[:10])
        except ValueError:
            continue
        gap = abs((day_date - target).days)
        if gap <= HISTORY_TOLERANCE_DAYS and (best is None or gap < best[0]):
            best = (gap, float(value))
    return best[1] if best else None


def history_anchors(
    points: list[tuple[str, float, int]],
    today: date | None = None,
) -> dict[int, float | None]:
    """`{档位: 该档位的成交均价}` —— 取 `price_history` 里各档位的最近记录。

    查不到 → None（`—`）。
    """
    pairs = [(str(day), float(average)) for day, average, _volume in points]
    return {offset: nearest_price(pairs, offset, today) for offset in HISTORY_OFFSETS}


def comparison_rows(
    cur: float | None,
    added: float | None,
    ago: dict[int, float | None],
) -> list[dict[str, Any]]:
    """价格对比表的 5 行：当前 / 加入时 / 30 / 90 / 180 天前。

    每行给 `text`（价格）+ `deltaText`（相对**当前**的绝对值）+ `pctText`（相对当前的 %）。
    「当前」行自身、以及任一缺失的单元格一律 `—`（**不用 0 冒充**）。
    """
    items: list[dict[str, Any]] = [
        {"label": "当前", "caliber": "挂单价", "price": cur},
        {"label": "加入时", "caliber": "挂单价", "price": added},
    ]
    items += [
        {"label": f"{offset} 天前", "caliber": "成交均价", "price": ago.get(offset)} for offset in HISTORY_OFFSETS
    ]
    rows: list[dict[str, Any]] = []
    for item in items:
        price = item["price"]
        delta: float | None = None
        pct: float | None = None
        if price is not None and cur is not None and price != cur:
            delta = cur - price
            pct = delta / price * 100.0
        rows.append(
            {
                **item,
                "text": _fmt_price(price),
                "deltaText": _fmt_delta(delta),
                "pctText": _fmt_pct(pct),
                # 数值一并给 QML：涨跌染色要判正负（字符串判号是坏味道）
                "delta": delta,
                "pct": pct,
            }
        )
    return rows


def _points_view(
    rows: Iterable[tuple[str, float, int]],
) -> tuple[list[str], list[dict[str, float]], list[dict[str, float]]]:
    """`(横轴日期, 成交均价点, 成交量点)` —— 同一批记录，两条线共用一个横轴。

    `x` 是序号：`FLineChart` 按序号均匀铺开（不看 x 的值）。
    """
    labels: list[str] = []
    price: list[dict[str, float]] = []
    volume: list[dict[str, float]] = []
    for day, average, vol in rows:
        index = len(labels)
        labels.append(str(day)[:10])
        price.append({"x": index, "y": float(average)})
        volume.append({"x": index, "y": float(vol or 0)})
    return labels, price, volume


def chart_points(
    points: list[tuple[str, float, int]],
    days: int = CHART_DAYS,
    today: date | None = None,
) -> tuple[list[str], list[dict[str, float]], list[dict[str, float]]]:
    """`(横轴日期, 成交均价点, 成交量点)` —— 同一批记录，两条线共用一个横轴。

    两段窗口，**顺序不能反**：

    1. 先按 `CHART_DAYS` 天（**日历天**）裁掉更早的记录 —— 折线的加载窗口；
    2. 再取最后 `days` 个**交易日**（= 有记录的日子）—— 时间粒度「近 7/30/90/180 天」的口径。

    第 2 步按点数、不按日历天：冷门物品几个月才有一条记录，按日历天切会把「近 7 天」
    切成 0~1 个点，图上看不出走势（材料快照更是只有「更新价格」那天才有）。
    """
    end = today or date.today()
    start = (end - timedelta(days=CHART_DAYS - 1)).isoformat()
    stop = end.isoformat()
    window = [row for row in points if start <= str(row[0])[:10] <= stop]
    return _points_view(window[-max(1, int(days)) :])


def bom_nodes(tree: Any, max_depth: int = MATERIAL_DEPTH) -> list[dict[str, Any]]:
    """`services.bom_expander.expand_bom` 的树 → `[{typeId, name, level, qty}]`（广序）。

    `level`：0 = 本物品本身，1 = 直接材料，2 = 二级材料。

    BOM 是 DAG（同一物品在多个父项/层级下出现），这里**按 typeId 合并**：
    取最浅的层级、数量求和 —— 表格与折线都按物品聚合，不按出现次数重复。
    """
    if tree is None:
        return []
    merged: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    queue: deque[Any] = deque([tree])
    while queue:
        node = queue.popleft()
        level = int(getattr(node, "depth", 0) or 0)
        if level > int(max_depth):
            continue
        type_id = int(getattr(node, "type_id", 0) or 0)
        quantity = float(getattr(node, "quantity", 0.0) or 0.0)
        if type_id:
            item = merged.get(type_id)
            if item is None:
                merged[type_id] = {
                    "typeId": type_id,
                    "name": str(getattr(node, "name", "") or ""),
                    "level": level,
                    "qty": quantity,
                }
                order.append(type_id)
            else:
                item["level"] = min(int(item["level"]), level)
                item["qty"] = float(item["qty"]) + quantity
        for child in getattr(node, "children", None) or []:
            queue.append(child)
    return [merged[tid] for tid in order]


# ════════════════════════════════════════════════════════════
#  读库（market.db 只读；表不存在 / 查不到一律 `[]`）
# ════════════════════════════════════════════════════════════


def _market_db():
    from core.container import get_container

    return get_container().db


def read_history(type_id: int, region_id: int) -> list[tuple[str, float, int]]:
    """`price_history` 的 `(date, average, volume)` 升序；表不存在 / 查不到 → `[]`。"""
    with _market_db().connect("mkt") as conn:
        # 只读路径不做 DDL：表还没建（从没更新过价格）就是没有数据
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='price_history'").fetchone():
            return []
        rows = conn.execute(
            "SELECT date, average, volume FROM price_history WHERE type_id = ? AND region_id = ? ORDER BY date",
            (int(type_id), int(region_id)),
        ).fetchall()
    return [(str(r[0]), float(r[1] or 0.0), int(r[2] or 0)) for r in rows]


def read_snapshots(
    type_ids: Iterable[int],
    region_id: int,
    days: int = CHART_DAYS,
    today: date | None = None,
) -> dict[int, list[tuple[str, float]]]:
    """`{type_id: [(date, 挂单价)]}` —— 来自 `market_volume_snapshots`（升序）。

    材料在 `price_history` 里多半没有记录（只有被拉取过的产物/材料才进那里），
    所以材料走势统一走这张表的 `sell_price`。**只保留 > 0 的日子**：
    没有挂单的那天没有价格，塞 0 会把归一化曲线的基期打成 0。
    """
    ids = sorted({int(t) for t in type_ids if t})
    out: dict[int, list[tuple[str, float]]] = {}
    if not ids:
        return out
    end = (today or date.today()).isoformat()
    start = ((today or date.today()) - timedelta(days=max(1, int(days)) - 1)).isoformat()
    with _market_db().connect("mkt") as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_volume_snapshots'"
        ).fetchone():
            return out
        for offset in range(0, len(ids), _SQL_PARAM_CHUNK):
            chunk = ids[offset : offset + _SQL_PARAM_CHUNK]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT type_id, date, sell_price FROM market_volume_snapshots "
                f"WHERE region_id = ? AND type_id IN ({placeholders}) "
                f"AND date >= ? AND date <= ? ORDER BY type_id, date",
                (int(region_id), *chunk, start, end),
            ).fetchall()
            for type_id, day, price in rows:
                value = _num(price)
                if value is None:
                    continue
                out.setdefault(int(type_id), []).append((str(day)[:10], value))
    return out


def load_materials(
    type_id: int,
    region_id: int,
    max_depth: int = MATERIAL_DEPTH,
    today: date | None = None,
) -> dict[str, Any]:
    """BOM 逐级展开（默认 2 级）+ 材料挂单价 → 材料表与归一化折线的载荷。

    返回 `{"rows": [...], "series": [...], "hint": str}`：

    - `rows`：**全部**节点（本物品 + 各级材料），供右侧表格显示绝对值；
    - `series`：最多 `MAX_MATERIAL_SERIES` 条，供 `FLineChart` 以 `normalize: true` 叠加
      （归一化在组件里做，见 `FLineChart.valuesOf`），排序为「本物品在前，其余按用量 × 挂单价降序」；
    - 每个 `series[i].points[k]` 的 `y` 是**绝对值挂单价**（基期 100 由组件算），`x` 是序号。

    ⚠️ **有意同步执行**：2 级展开只有几十个节点，`expand_bom` 的定价查询很轻；
    真正贵的「拉历史」不在页面里做（在「更新价格」流程里）。
    """
    from services.bom_expander import expand_bom

    expanded = expand_bom(
        type_id=int(type_id),
        quantity=1,
        bp_me=0,
        # `expand_bom` 要的是贸易中心名（不是 region_id）；查不到就退回列表第一个（Jita）
        price_hub=HUB_NAMES.get(int(region_id), _HUBS[0]),
        price_type="sell",
        max_depth=max(1, int(max_depth)),
    )
    nodes = bom_nodes(expanded.get("tree"), max_depth)
    snaps = read_snapshots([node["typeId"] for node in nodes], region_id, today=today)

    picked: list[dict[str, Any]] = []
    for node in nodes:
        points = snaps.get(int(node["typeId"])) or []
        price = points[-1][1] if points else None
        picked.append(
            {
                "node": node,
                "points": points,
                "price": price,
                "ago": nearest_price(points, 30, today),
            }
        )

    rows: list[dict[str, Any]] = []
    for item in picked:
        price = item["price"]
        ago = item["ago"]
        pct = (price - ago) / ago * 100.0 if price is not None and ago else None
        rows.append(
            {
                "name": item["node"]["name"],
                "typeId": int(item["node"]["typeId"]),
                "level": int(item["node"]["level"]),
                "indent": int(item["node"]["level"]) * 12,
                "qtyText": f"{float(item['node']['qty']):,.0f}",
                "priceText": _fmt_price(price),
                "agoText": _fmt_price(ago),
                "pctText": _fmt_pct(pct),
                "pct": pct,
                "caliber": "挂单价",
            }
        )

    chartable = [item for item in picked if item["points"]]
    # 本物品先（level 0），其余按「用量 × 挂单价」降序：钱最多的先画
    chartable.sort(
        key=lambda item: (
            int(item["node"]["level"]) != 0,
            -float(item["price"] or 0.0) * float(item["node"]["qty"]),
        )
    )
    shown = chartable[:MAX_MATERIAL_SERIES]
    series: list[dict[str, Any]] = []
    for index, item in enumerate(shown):
        token = "PRIMARY" if int(item["node"]["level"]) == 0 else _SERIES_TOKENS[(index - 1) % len(_SERIES_TOKENS)]
        series.append(
            {
                "label": str(item["node"]["name"]),
                "color": theme.token_color(token),
                "points": [{"x": k, "y": float(value)} for k, (_day, value) in enumerate(item["points"])],
            }
        )

    omitted = len(chartable) - len(shown)
    hint = f"口径：挂单价（market_volume_snapshots 当日快照）。BOM 逐级展开 {int(max_depth)} 级，共 {len(rows)} 项"
    if omitted > 0:
        hint += f"；折线只画 {len(shown)} 条（用量 × 挂单价前 {MAX_MATERIAL_SERIES}），其余 {omitted} 项见下表"
    if not chartable:
        hint += "；本地还没有这些物品的挂单快照（先「更新价格」）"
    return {"rows": rows, "series": series, "hint": hint}


# ════════════════════════════════════════════════════════════
#  桥
# ════════════════════════════════════════════════════════════


class WatchlistBridge(QObject):
    """关注（价格监控）Tab 的 QML 后端。"""

    rowsChanged = Signal()
    suggestChanged = Signal()
    editorChanged = Signal()  # 顶部「搜索物品 / 备注 / 区域」这一组
    detailChanged = Signal()  # 右侧详情（选中行 + 对比表 + 主物品折线）
    materialsChanged = Signal()  # 右侧「显示制造材料」的表与归一化折线
    sortChanged = Signal()
    rangeChanged = Signal()  # 折线图时间粒度（近 7/30/90/180 天）

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        from services.watchlist_manager import init_db

        init_db()
        self._shell = shell
        self._model = WatchlistQmlModel()
        self._price_changes: dict[int, dict] = {}

        self._search_text = ""
        self._suggestions: list[dict] = []
        self._selected_type_id: int | None = None
        self._selected_name = ""
        self._region_index = 0
        self._note = ""

        # ── 右详情侧状态 ──
        self._sort_index = 0
        self._selected_row = -1
        #: 选中项的 `watchlist_items.id` —— 刷新/排序后按它重新定位（行号会变）
        self._selected_id: int | None = None
        self._detail: dict[str, Any] = {"valid": False, "rows": []}
        self._chart_labels: list[str] = []
        self._price_series: list[dict] = []
        self._volume_series: list[dict] = []
        #: 折线图时间粒度（下标进 `RANGE_OPTIONS`）+ **已装配好的**历史点
        #: （切粒度只在这上面切尾，不重读 `price_history`）
        self._range_index = DEFAULT_RANGE_INDEX
        self._history_points: list[tuple[str, float, int]] = []
        self._base_note = ""
        self._show_materials = False
        self._material_rows: list[dict] = []
        self._material_series: list[dict] = []
        #: 材料序列的原始（绝对值）形态 —— 切粒度只切它，不重跑 BOM 展开/取价
        self._material_series_raw: list[dict] = []
        self._material_base_note = ""
        self._material_hint = ""

        self._suggest_worker: QObject | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.checkPriceChanges)
        self._timer.start(CHECK_INTERVAL_MS)
        #: 关机收尾标记（见 `shutdown`）：已排队的 timeout 事件可能还会到，到了就跳过
        self._shutting_down = False

        self._remove_theme_listener = theme.add_theme_listener(self._on_theme_changed)
        # 归属：页面 bridge 没有 QObject 父对象，外壳 `deleteLater()` 带不走它 —— 把
        # 「外壳析构」也接成收尾触发点。两条都要接：`build_qml_page` 接的是**页面 Item**
        # 销毁，而外壳析构时子对象的销毁顺序并不保证在 bridge 死之前
        # （2026-10-05 整档实测：外壳的 `ShellWindowBridge` 已析构、本桥还在轮询）。
        if isinstance(shell, QObject):
            shell.destroyed.connect(self.shutdown)
        self.refresh()

    # ── 关机收尾 ──────────────────────────────────────────────

    def shutdown(self) -> None:
        """页面/外壳销毁时收尾 —— **必须有**，否则本桥的常驻定时器会打已销毁的外壳。

        为什么会有这个坑：页面 bridge 是 `registry.build_qml_page` 造出来直接塞进 QML
        context 的，**没有 QObject 父对象**（context property 不接管所有权，同
        `PageHost` 里那段说明）。于是外壳被 `deleteLater()` 掉时它不会跟着死，而
        `self._timer` 每 60 秒就会 `checkPriceChanges → refresh → _push_status` →
        `shell.set_status(...)` —— 外壳的 `ShellWindowBridge` 已经随窗口析构了，于是：

            RuntimeError: Signal source has been deleted   （随后访问违例）

        2026-10-05 整档 `-m ui` 就是这么崩的。触发点由 `build_qml_page` 统一接在
        页面 Item 的 `destroyed` 上（`ShellWindow.closeEvent` 那条路只覆盖「关窗」，
        覆盖不到 `deleteLater()`）。
        """
        self._shutting_down = True
        self._timer.stop()
        remover = getattr(self, "_remove_theme_listener", None)
        if callable(remover):
            remover()
            self._remove_theme_listener = None
        worker = self._suggest_worker
        if worker is not None:
            from ui_qml.workers.lifecycle import drop_worker

            drop_worker(worker)
            self._suggest_worker = None

    # ── 列表 ──────────────────────────────────────────────────

    model = Property(QObject, lambda self: self._model, constant=True)

    @Property(list, constant=True)
    def columns(self) -> list[dict]:
        """列定义（标题 + 宽度）—— 单一来源在 `watchlist_view.COLUMNS`。"""
        from ui_qml.models.watchlist_models import COLUMNS

        return [{"title": title, "width": width} for title, width in COLUMNS]

    countText = Property(str, lambda self: f"共 {self._model.rowCount()} 项", notify=rowsChanged)

    #: 左侧窄列表的行卡片（`ListView` 用 JS 数组模型 —— 本仓既有做法）；
    #: 每次求值现算，`rowsChanged`（刷新/排序/换主题）一响 QML 就会重读
    listRows = Property(list, lambda self: self._model.list_rows(), notify=rowsChanged)

    @Property(list, constant=True)
    def sortOptions(self) -> list[str]:
        return list(SORT_MODES)

    sortIndex = Property(int, lambda self: self._sort_index, notify=sortChanged)

    def _row(self, row: int) -> dict[str, Any] | None:
        items = self._model._rows
        if not 0 <= int(row) < len(items):
            return None
        return items[int(row)]

    @Slot()
    def refresh(self) -> None:
        from services.watchlist_manager import get_watchlist

        rows = get_watchlist()
        # 涨幅按 `added_price` 算好塞进行里：左列表的「涨幅」列与排序共用同一份，不两处各算
        rise = {_tid(row): rise_pct(row) for row in rows}
        for row in rows:
            row["rise_text"] = _fmt_pct(rise.get(_tid(row)))
        self._model.set_rows(sort_rows(rows, self._sort_index, rise))
        self.rowsChanged.emit()
        self._reselect()
        self.detailChanged.emit()
        self._push_status()

    def _reselect(self) -> None:
        """刷新（含 60 秒轮询、排序、增删）后按 watch id 重新定位选中行。

        **按 id 不按行号**：排序一换、轮询一刷，行号就变了。
        """
        row = -1
        if self._selected_id is not None:
            for index, item in enumerate(self._model._rows):
                if item.get("id") == self._selected_id:
                    row = index
                    break
        self._selected_row = row
        if row < 0:
            self._selected_id = None
            self._clear_detail()
        else:
            self._load_detail()

    @Slot(int)
    def selectRow(self, row: int) -> None:
        """选中左列表某一行 → 加载右侧详情（对比表 + 主物品折线）。"""
        item = self._row(row)
        self._selected_row = -1 if item is None else int(row)
        self._selected_id = None if item is None else int(item.get("id") or 0)
        self._load_detail()
        # 勾着「显示制造材料」时换物品要跟着换材料；没勾就什么都不做（省一次 BOM 展开）
        self._load_materials()
        self.detailChanged.emit()

    @Slot(int)
    def setSortIndex(self, index: int) -> None:
        index = int(index)
        if not 0 <= index < len(SORT_MODES) or index == self._sort_index:
            return
        self._sort_index = index
        self.sortChanged.emit()
        self.refresh()

    def _push_status(self) -> None:
        # 已收尾（页面/外壳销毁）就什么都不做：排队的 timeout 可能比 `stop()` 晚到
        if self._shutting_down:
            return
        setter = getattr(self._shell, "set_status", None)
        if not callable(setter):
            return
        count = self._model.rowCount()
        triggered = 0
        for row in self._model._rows:
            buy_thresh = row.get("buy_threshold")
            sell_thresh = row.get("sell_threshold")
            buy_price = row.get("buy_price")
            sell_price = row.get("sell_price")
            if buy_thresh is not None and buy_price and buy_price <= buy_thresh:
                triggered += 1
            elif sell_thresh is not None and sell_price and sell_price >= sell_thresh:
                triggered += 1
        msg = f"关注列表: {count} 项"
        if triggered:
            msg += f", {triggered} 项触发提醒"
        if self._price_changes:
            msg += f", {len(self._price_changes)} 项价格变化"
        setter(msg)

    # ── 顶部编辑器 ────────────────────────────────────────────

    searchText = Property(str, lambda self: self._search_text, notify=editorChanged)
    selectedName = Property(str, lambda self: self._selected_name, notify=editorChanged)
    regions = Property(list, lambda self: list(_HUBS), constant=True)
    regionIndex = Property(int, lambda self: self._region_index, notify=editorChanged)
    note = Property(str, lambda self: self._note, notify=editorChanged)
    suggestions = Property(list, lambda self: self._suggestions, notify=suggestChanged)

    @Slot(str)
    def onSearchChanged(self, text: str) -> None:
        self._search_text = str(text)
        if len(text) < 1:
            self._suggestions = []
            self.suggestChanged.emit()
            return

        from ui_qml.workers.watchlist_workers import SuggestionWorker

        worker = SuggestionWorker(text, self)
        self._suggest_worker = worker
        worker.finished_signal.connect(self._on_suggestions)
        worker.start()

    def _on_suggestions(self, items: list) -> None:
        self._suggestions = [{"typeId": int(tid), "text": str(display)} for tid, display in items or []]
        self.suggestChanged.emit()

    @Slot(int)
    def pickSuggestion(self, index: int) -> None:
        if not 0 <= index < len(self._suggestions):
            return
        item = self._suggestions[index]
        self._selected_type_id = int(item["typeId"])
        self._selected_name = str(item["text"])
        self._search_text = self._selected_name
        self._suggestions = []
        self.suggestChanged.emit()
        self.editorChanged.emit()

    @Slot(int)
    def setRegionIndex(self, index: int) -> None:
        if 0 <= index < len(_HUBS) and index != self._region_index:
            self._region_index = index
            self.editorChanged.emit()

    @Slot(str)
    def setNote(self, text: str) -> None:
        self._note = str(text)

    @Slot(result=bool)
    def add(self) -> bool:
        """添加关注。没选物品时返回 False，由 QML 提示（与 Widgets 版的 warning 对应）。"""
        if self._selected_type_id is None:
            return False
        from services.watchlist_manager import add_to_watchlist

        result = add_to_watchlist(
            type_id=self._selected_type_id,
            region_id=TRADE_HUB_IDS[_HUBS[self._region_index]],
            note=self._note.strip(),
        )
        if result <= 0:
            return False

        self._search_text = ""
        self._selected_type_id = None
        self._selected_name = ""
        self._note = ""
        self._suggestions = []
        self.suggestChanged.emit()
        self.editorChanged.emit()
        self.refresh()
        return True

    # ── 删除 / 阈值 / 备注 ────────────────────────────────────

    @Slot(int)
    def removeRow(self, row: int) -> None:
        from services.watchlist_manager import remove_from_watchlist

        item = self._row(row)
        if item is None:
            return
        item_id = int(item.get("id") or 0)
        if item_id == self._selected_id:
            self._selected_row = -1
            self._selected_id = None
        remove_from_watchlist(item_id)
        self.refresh()

    @Slot(int, str, float)
    def setThreshold(self, row: int, kind: str, value: float) -> None:
        """设置买/卖价阈值；value ≤ 0 表示清除（与原版一致）。"""
        from services.watchlist_manager import update_watchlist_item

        item = self._row(row)
        if item is None:
            return
        threshold = value if value > 0 else None
        if kind == "buy":
            update_watchlist_item(item["id"], buy_threshold=threshold)
        else:
            update_watchlist_item(item["id"], sell_threshold=threshold)
        self.refresh()

    @Slot(str)
    def setRowNote(self, text: str) -> None:
        """改**选中项**的备注。

        原版只能在「添加关注」时写备注（`setNote` 那条路），事后改不了；
        右详情面板给了一个编辑框，这里补上写库。
        """
        from services.watchlist_manager import update_watchlist_item

        item = self._row(self._selected_row)
        if item is None:
            return
        update_watchlist_item(int(item.get("id") or 0), note=str(text))
        self.refresh()

    @Slot(int, result=dict)
    def rowInfo(self, row: int) -> dict:
        """给阈值弹层/右键菜单/右详情用的行信息。"""
        item = self._row(row)
        if item is None:
            return {"valid": False}
        return {
            "valid": True,
            "name": item.get("zh_name") or item.get("en_name") or "",
            "buyThreshold": item.get("buy_threshold") or 0.0,
            "sellThreshold": item.get("sell_threshold") or 0.0,
            "typeId": _tid(item),
            "note": item.get("note") or "",
        }

    # ── 右详情：价格对比表 + 主物品折线 ───────────────────────

    selectedRow = Property(int, lambda self: self._selected_row, notify=detailChanged)
    detail = Property(dict, lambda self: self._detail, notify=detailChanged)
    chartLabels = Property(list, lambda self: self._chart_labels, notify=detailChanged)
    priceSeries = Property(list, lambda self: self._price_series, notify=detailChanged)
    volumeSeries = Property(list, lambda self: self._volume_series, notify=detailChanged)
    #: 折线图时间粒度：`rangeLabels` 给 QML 画分段按钮，`rangeIndex` 是当前选项
    rangeLabels = Property(list, lambda self: list(RANGE_LABELS), constant=True)
    rangeIndex = Property(int, lambda self: self._range_index, notify=rangeChanged)
    #: 图上写出来的口径 + 粒度说明（主物品这两条线是**绝对值**，材料叠加图才归一化）
    baseNote = Property(str, lambda self: self._base_note, notify=detailChanged)

    @Slot(int)
    def setRangeIndex(self, index: int) -> None:
        """切折线图的时间粒度（近 7/30/90/180 天）—— **只切已装配好的点**。

        用户口径：「如果我想看近 7 日或者近 30 天的，这个时间粒度没有筛选」。
        这里不重读 `price_history`、不重跑 BOM 展开、不发 ESI：历史点在 `_load_detail`
        里、材料序列在 `_load_materials` 里已经装配好，切粒度只是按点数切尾 + 重发信号。
        """
        index = int(index)
        if not 0 <= index < len(RANGE_OPTIONS) or index == self._range_index:
            return
        self._range_index = index
        self.rangeChanged.emit()
        self._rebuild_charts()
        self.detailChanged.emit()
        self._rebuild_material_series()
        self.materialsChanged.emit()

    def _clear_detail(self) -> None:
        self._detail = {"valid": False, "rows": []}
        self._chart_labels = []
        self._price_series = []
        self._volume_series = []
        self._history_points = []
        self._base_note = ""

    def _load_detail(self) -> None:
        """按选中行**读一次** `price_history`，装配对比表与折线（切粒度不再读库）。"""
        item = self._row(self._selected_row)
        if item is None:
            self._clear_detail()
            return
        type_id = _tid(item)
        region_id = int(item.get("region_id") or 0)
        self._history_points = read_history(type_id, region_id)
        self._rebuild_charts()
        self._detail = {
            "valid": True,
            "name": str(item.get("zh_name") or item.get("en_name") or type_id),
            "typeId": type_id,
            "note": str(item.get("note") or ""),
            "rows": comparison_rows(
                _num(item.get("sell_price")), _num(item.get("added_price")), history_anchors(self._history_points)
            ),
            "hasHistory": bool(self._chart_labels),
            "hint": "「加入时 / 当前」＝挂单价；「30/90/180 天前」＝成交均价（口径不同，涨跌仅作参照）",
        }

    def _rebuild_charts(self) -> None:
        """按当前**粒度**切已加载的点（不读库）→ 主物品两条折线 + 图上说明。"""
        days = RANGE_OPTIONS[self._range_index]
        labels, price, volume = chart_points(self._history_points, days)
        self._chart_labels = labels
        self._price_series = [{"label": "成交均价", "color": theme.token_color("ACCENT_CYAN"), "points": price}]
        self._volume_series = [{"label": "成交量", "color": theme.token_color("ACCENT_ORANGE"), "points": volume}]
        # 这两条线**没有归一化**（`FLineChart.normalize` 默认 false，纵轴是绝对值）——
        # 图上不许写「基期 = 100」：那是材料叠加图与大盘页的口径（如实写，别编）。
        self._base_note = f"纵轴为绝对值（未归一化）· 当前显示最近 {days} 个交易日"

    # ── 右详情：制造材料（BOM 展开 + 归一化折线） ──────────────

    showMaterials = Property(bool, lambda self: self._show_materials, notify=materialsChanged)
    materialRows = Property(list, lambda self: self._material_rows, notify=materialsChanged)
    materialSeries = Property(list, lambda self: self._material_series, notify=materialsChanged)
    materialHint = Property(str, lambda self: self._material_hint, notify=materialsChanged)
    #: 材料叠加图是**归一化**的：`FLineChart` 按每条线自己的首个（显示中的）点归一到 100
    materialBaseNote = Property(str, lambda self: self._material_base_note, notify=materialsChanged)

    @Slot(bool)
    def setShowMaterials(self, shown: bool) -> None:
        shown = bool(shown)
        if shown == self._show_materials:
            return
        self._show_materials = shown
        self._load_materials()
        self.materialsChanged.emit()

    def _load_materials(self) -> None:
        item = self._row(self._selected_row) if self._selected_row >= 0 else None
        if not self._show_materials or item is None:
            self._material_rows = []
            self._material_series = []
            self._material_series_raw = []
            self._material_base_note = ""
            self._material_hint = ""
            return
        try:
            payload = load_materials(_tid(item), int(item.get("region_id") or 0), MATERIAL_DEPTH)
        except Exception:  # 展开/取价是外部依赖（ref/bp 库、定价服务），失败不该掀翻页面
            from core.logger import log

            log.exception("BOM 材料展开失败")
            payload = {"rows": [], "series": [], "hint": "材料展开失败（详见日志）"}
        self._material_rows = list(payload.get("rows") or [])
        self._material_series_raw = list(payload.get("series") or [])
        self._rebuild_material_series()
        self._material_hint = str(payload.get("hint") or "")

    def _rebuild_material_series(self) -> None:
        """按当前**粒度**切材料序列（只切已装配的点，不重读库、不重跑 BOM 展开）。"""
        days = RANGE_OPTIONS[self._range_index]
        series: list[dict] = []
        for line in self._material_series_raw:
            points = list(line.get("points") or [])[-days:]
            # 切完重新编号：`x` 与数组下标保持一致（`FLineChart` 按序号铺开）
            series.append({**line, "points": [{"x": i, "y": float(point["y"])} for i, point in enumerate(points)]})
        self._material_series = series
        # 基期如实写：归一化用的是**每条线自己的首个显示点**，不是「加入时」价 —— 切粒度会
        # 换掉那个点，所以说明里只能写「首个显示点」，写「加入时」就是编。
        self._material_base_note = f"各线按自身首个显示点 = 100 归一化 · 当前显示最近 {days} 个交易日"

    # ── 价格变化轮询 ──────────────────────────────────────────

    @Slot()
    def checkPriceChanges(self) -> None:
        """定时检查价格变化（原版 `_on_price_check_timer`）。"""
        try:
            from services.watchlist_manager import check_price_changes

            changes = check_price_changes()
            self._price_changes = {c["type_id"]: c for c in changes}
            self._model.set_price_changes(self._price_changes)
            self.refresh()
        except Exception:
            from core.logger import log

            log.exception("价格变化检测失败")

    def _on_theme_changed(self) -> None:
        self._model.refresh_colors()
        self.rowsChanged.emit()
        # 折线颜色是建 series 时从主题取好的字符串，切主题后必须重建
        if self._selected_row >= 0:
            self._load_detail()
            self.detailChanged.emit()
        if self._show_materials:
            self._load_materials()
            self.materialsChanged.emit()
