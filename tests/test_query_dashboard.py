"""物品查询页空闲态仪表盘桥的契约测试。

对照 `ui_qml/views/industry/production_launcher.py` 的占用算法与
`ui_qml/bridge/price_chart_bridge.py` 的几何纯函数 —— 桥只做整形，但**整形得对不对**
必须锁住，否则查询页的仪表盘会和产线小助手对不上。

并行交付的两个服务模块（`services.asset_snapshot_service` / `services.order_export`）
与 user.db 在这里全部用替身顶掉：本文件的观察点是**桥自己的行为**
（指纹幂等、区间裁剪、几何、挂单导入与订单变动分类 / 钱包增减），不是那两个模块。
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import pytest

import ui_qml.bridge.query_dashboard_bridge as qdb
from ui_qml.bridge.query_dashboard_bridge import QueryDashboardBridge

pytestmark = pytest.mark.fast

_CHAR = "人物A"
_SKILLS = {"高级量产技术": 5, "批量生产学": 5}  # 制造线满级 = 11
_HANGAR = 7


# ════════════════════════════════════════════════════════════
#  替身
# ════════════════════════════════════════════════════════════


class _FakeAsset:
    """替 `services.asset_snapshot_service`。"""

    def __init__(self, series: list[dict] | None = None, wallet: float | None = None) -> None:
        self.series = [dict(r) for r in (series or [])]
        self.wallet = wallet
        self.snapshots: list[float | None] = []
        self.days_requested: list[int] = []

    def load_series(self, days: int = 90) -> list[dict]:
        self.days_requested.append(int(days))
        return [dict(r) for r in self.series]

    def record_snapshot(self, wallet: float | None = None) -> None:
        self.snapshots.append(wallet)

    def get_wallet_balance(self) -> float | None:
        return self.wallet

    def set_wallet_balance(self, value: float) -> None:
        self.wallet = float(value)

    def adjust_wallet_balance(self, delta: float) -> float:
        self.wallet = float(self.wallet or 0.0) + float(delta)
        return self.wallet


class _FakeOrderSvc:
    """替 `services.order_export`。"""

    def __init__(self) -> None:
        self.path: str | None = None
        self.rows: list[dict] = []
        self.unparsed = 0
        self.dirs: list[str | None] = []
        self.raws: list[str] = []

    def find_latest_export(self, directory: str | None = None) -> str | None:
        self.dirs.append(directory)
        return self.path

    def parse_order_export(self, raw: str) -> tuple[list[dict], int]:
        self.raws.append(raw)
        return [dict(r) for r in self.rows], self.unparsed

    def read_export_text(self, path: str) -> str:
        """读文件的编码分档（BOM/UTF-16）走**真实现**：假实现不该在这层分叉，
        否则「测试里读得动、真环境读不动」这种差异就测不出来。"""
        from services.order_export import read_export_text as real_read_export_text

        return real_read_export_text(path)


class _ChangeDialog:
    """替 `_open_change_dialog`：记录被问了什么，按 `answer` 决定是否应用。

    默认 `answer=False`（用户点了取消）—— 绝大多数用例只想验导入本身，
    不想让钱包被悄悄改掉。
    """

    def __init__(self, answer: bool = False, choices: dict[int, int] | None = None) -> None:
        self.answer = answer
        self.choices = dict(choices or {})
        self.calls: list[tuple[list[dict], float]] = []
        self.ledger_only: list[bool] = []

    def __call__(
        self, rows: list[dict], parent: object, wallet: float, ledger_only: bool = False
    ) -> tuple[list[dict], bool]:
        """与真弹窗同口径：**选择只决定记账，不决定挂单还在不在**。

        `new_remain` 一律原样带出（部分成交 → 回写剩余量、整笔消失 → None → 删行），
        所以「手动撤销」不会把仍在导出文件里的挂单删掉。
        """
        self.calls.append(([dict(r) for r in rows], float(wallet)))
        self.ledger_only.append(bool(ledger_only))
        outcomes = [
            {
                "order_id": int(row["order_id"]),
                "outcome": "filled" if self.choices.get(index, 0) == 0 else "cancelled",
                "is_buy": int(row["is_buy"]),
                "price": float(row["price"]),
                "volume": int(row["volume"]),
                "delta": float(row["delta"]) if self.choices.get(index, 0) == 0 else 0.0,
                "new_remain": row.get("new_remain"),
            }
            for index, row in enumerate(rows)
        ]
        return outcomes, self.answer


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE asset_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snap_date TEXT UNIQUE, total REAL, orders REAL, inventory REAL,
            line_value REAL, wallet REAL, created_at TEXT
        );
        CREATE TABLE open_orders (
            order_id INTEGER PRIMARY KEY, is_buy INTEGER, price REAL,
            volume_total INTEGER, volume_remain INTEGER, location_id INTEGER,
            location_name TEXT, type_id INTEGER, type_name TEXT, issued TEXT,
            duration INTEGER, char_id INTEGER DEFAULT 0, is_corp INTEGER DEFAULT 0,
            imported_at TEXT
        );
        CREATE TABLE order_events (
            order_id INTEGER NOT NULL, applied_at TEXT NOT NULL, outcome TEXT DEFAULT '',
            is_buy INTEGER DEFAULT 0, price REAL DEFAULT 0, volume INTEGER DEFAULT 0,
            delta REAL DEFAULT 0, PRIMARY KEY (order_id, applied_at)
        );
        """
    )
    return conn


def _orders_in(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM open_orders ORDER BY order_id").fetchall()]


def _events_in(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM order_events ORDER BY order_id").fetchall()]


def _order(
    order_id: int,
    *,
    is_buy: bool = True,
    price: float = 100.0,
    remain: int = 10,
    total: int | None = None,
    location_id: int = 60003760,
    location_name: str = "Jita IV-4",
    type_name: str = "三钛合金",
    char_id: int = 0,
    is_corp: bool = False,
) -> dict:
    return {
        "order_id": order_id,
        "is_buy": is_buy,
        "price": price,
        "volume_total": total if total is not None else remain,
        "volume_remain": remain,
        "location_id": location_id,
        "location_name": location_name,
        "type_id": 1001,
        "type_name": type_name,
        "char_id": char_id,
        "is_corp": is_corp,
    }


def _plan(
    plan_id: int,
    *,
    status: str = "pending",
    product: str = "",
    parallels: int = 1,
    mat_hangar_id: int | None = _HANGAR,
    category: str = "manufacturing",
) -> dict:
    return {
        "id": plan_id,
        "status": status,
        "char_name": _CHAR,
        "parallels": parallels,
        "runs": 1,
        "me_level": 0,
        "category": category,
        "mat_hangar_id": mat_hangar_id,
        "product_name": product or f"产物{plan_id}",
        "product_type_id": 2000 + plan_id,
    }


class _Harness:
    def __init__(self) -> None:
        self.conn = _make_db()
        self.assets = _FakeAsset()
        self.orders = _FakeOrderSvc()
        self.change_dialog = _ChangeDialog()
        self.plans: list[dict] = []
        #: 上次 ESI 同步挂单的时刻（默认空 = 从没同步过 → 不挡任何日志导入）
        self.esi_synced_at = ""

    @contextlib.contextmanager
    def user_conn(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
        except Exception:
            self.conn.rollback()
            raise
        self.conn.commit()

    def bridge(self) -> QueryDashboardBridge:
        return QueryDashboardBridge()


@pytest.fixture
def h(monkeypatch) -> _Harness:
    harness = _Harness()
    monkeypatch.setattr(qdb, "_user_conn", harness.user_conn)
    monkeypatch.setattr(qdb, "_asset_svc", lambda: harness.assets)
    monkeypatch.setattr(qdb, "_order_svc", lambda: harness.orders)
    monkeypatch.setattr(qdb, "_open_change_dialog", harness.change_dialog)
    # ESI 同步时刻（真实现写 settings.json；测试里换成内存值，别碰用户的配置）
    monkeypatch.setattr(qdb, "get_esi_orders_synced_at", lambda: harness.esi_synced_at)
    monkeypatch.setattr(qdb, "set_esi_orders_synced_at", lambda value: setattr(harness, "esi_synced_at", str(value)))
    monkeypatch.setattr(qdb, "load_plans_for_wizard", lambda: [dict(p) for p in harness.plans])
    monkeypatch.setattr(qdb, "get_character_list", lambda: [_CHAR])
    monkeypatch.setattr(qdb, "load_all_data", lambda: {"characters": {_CHAR: {"skills": dict(_SKILLS)}}})
    # `_line_value()`（服务侧）会经评分链路读材料需求 / 机库库存；本文件只验桥的整形，
    # 把它顶成「没有制造中产线」即可（`_FakeAsset` 的快照数据已给定 line_value）。
    monkeypatch.setattr("services.plan_service.load_plans_for_wizard", lambda: [])
    return harness


@contextlib.contextmanager
def _warnings() -> Iterator[list[logging.LogRecord]]:
    """抓 `core.logger` 的记录（不依赖 caplog 的传播链，直接挂到它的 logger 上）。"""
    records: list[logging.LogRecord] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Handler()
    logger = logging.getLogger("eve-assistant")
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


def _snapshots(days: int = 3, *, total: float = 1000.0, wallet: float = 1_000_000_000.0) -> list[dict]:
    """最近 `days` 天的快照（升序，最后一条是今天）。"""
    today = date.today()
    return [
        {
            "date": (today - timedelta(days=days - 1 - i)).isoformat(),
            "total": total + i,
            "orders": 100.0 + i,
            "inventory": 200.0 + i,
            "line_value": 50.0 + i,
            "wallet": wallet + i,
        }
        for i in range(days)
    ]


# ════════════════════════════════════════════════════════════
#  产线详情
# ════════════════════════════════════════════════════════════


def test_occupancy_rows_shape_matches_launcher(h):
    h.plans = [_plan(1, status="in_progress", parallels=2)]
    bridge = h.bridge()
    bridge.refresh()

    rows = bridge.occupancyRows
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"name", "nameWidth", "lines", "statusText", "statusColor", "slotTotal"}
    assert row["name"] == _CHAR  # ⚠️ 键名是 name（QML 里 charName: modelData.name）
    assert row["slotTotal"] == 13  # 制造 11 + 科研 1 + 反应 1

    lines = row["lines"]
    assert [line["label"] for line in lines] == ["制造", "科研", "反应"]
    for line in lines:
        assert set(line) == {"label", "color", "active", "max", "cap"}
    assert [line["active"] for line in lines] == [2, 0, 0]  # parallels=2 占满制造线两格
    assert [line["max"] for line in lines] == [11, 1, 1]

    assert bridge.occupancySummary == "1 人物 · 占用 2/13"


def test_occupancy_status_texts(h):
    """空闲 → 无占用；parallels 超全部线型容量之和（11+1+1）→ 超员并给出超出数。"""
    h.plans = [_plan(1, status="completed")]
    bridge = h.bridge()
    bridge.refresh()
    assert bridge.occupancyRows[0]["statusText"] == "空闲"

    h.plans = [_plan(2, status="in_progress", parallels=20)]
    bridge.refresh()
    assert bridge.occupancyRows[0]["statusText"] == "超员 +7"


def test_occupancy_empty_without_characters(h, monkeypatch):
    monkeypatch.setattr(qdb, "get_character_list", lambda: [])
    monkeypatch.setattr(qdb, "load_all_data", lambda: {"characters": {}})
    bridge = h.bridge()
    bridge.refresh()
    assert bridge.occupancyRows == []
    assert "无人物配置" in bridge.occupancySummary


def test_occupancy_lists_characters_seen_only_in_plans(h):
    """人物配置里没有、但计划里有的角色也要出行（与产线小助手同口径）。"""
    h.plans = [_plan(1, status="running")]
    h.plans[0]["char_name"] = "临时人物"
    bridge = h.bridge()
    bridge.refresh()
    assert [row["name"] for row in bridge.occupancyRows] == [_CHAR, "临时人物"]


def test_occupancy_by_char_shape_and_hints(h):
    """仪表盘左栏的形状：**每人物一块、块内制造/科研/反应三行**，并给出「待下线 N」。

    - `readyText` = 该人物该线型下 `status=='ready'` 的计划数（用户明确要的提示）
    - `freeN` = 还能再上几条线（上限 − 已占）
    - `cap` = 该线型各人物上限中的**最大值**（所有人共用同一个分母 → 条子等长可比，
      且某人物跑满自己的上限就占满整条）
    """
    h.plans = [
        _plan(1, status="in_progress", parallels=2),
        _plan(2, status="ready", category="manufacturing"),
        _plan(3, status="ready", category="copying"),  # copying → 科研线
    ]
    bridge = h.bridge()
    bridge.refresh()

    blocks = bridge.occupancyByChar
    assert [block["name"] for block in blocks] == [_CHAR]
    block = blocks[0]
    assert set(block) == {"name", "statusText", "statusColor", "lines"}

    lines = block["lines"]
    assert [line["label"] for line in lines] == ["制造", "科研", "反应"]
    assert [line["key"] for line in lines] == ["manufacturing", "research", "reaction"]
    for line in lines:
        assert set(line) == {
            "key",
            "label",
            "color",
            "active",
            "max",
            "cap",
            "readyN",
            "readyText",
            "freeN",
            "detailText",
        }
    assert [line["active"] for line in lines] == [2, 0, 0]
    assert [line["max"] for line in lines] == [11, 1, 1]
    assert [line["readyN"] for line in lines] == [1, 1, 0], "one manufacturing ready + one copying(→科研) ready"
    assert lines[0]["readyText"] == "待下线 1"
    assert lines[2]["readyText"] == "", "没有待下线就不给提示（QML 那一列恒定预留宽度）"
    assert [line["freeN"] for line in lines] == [9, 1, 1]
    assert "制造 已占 2 / 上限 11" in lines[0]["detailText"]


def test_occupancy_by_char_cap_is_shared_denominator(h, monkeypatch):
    """`cap` 取该线型**各人物上限中的最大值**（不是之和 —— 回归：取之和时，
    单人跑满自己那 11 条线，条子只点亮整条的一半，因为分母是 11 + 1 = 12）。"""
    monkeypatch.setattr(qdb, "get_character_list", lambda: [_CHAR, "人物B"])
    monkeypatch.setattr(
        qdb,
        "load_all_data",
        lambda: {"characters": {_CHAR: {"skills": dict(_SKILLS)}, "人物B": {"skills": {}}}},
    )
    h.plans = [_plan(1, status="in_progress", parallels=11)]
    bridge = h.bridge()
    bridge.refresh()

    blocks = bridge.occupancyByChar
    assert [block["name"] for block in blocks] == [_CHAR, "人物B"]
    manufacturing = [block["lines"][0] for block in blocks]
    assert [line["max"] for line in manufacturing] == [11, 1]
    assert [line["cap"] for line in manufacturing] == [11, 11]
    assert [line["freeN"] for line in manufacturing] == [0, 1]


def test_occupancy_by_char_empty_without_characters(h, monkeypatch):
    monkeypatch.setattr(qdb, "get_character_list", lambda: [])
    monkeypatch.setattr(qdb, "load_all_data", lambda: {"characters": {}})
    bridge = h.bridge()
    bridge.refresh()
    assert bridge.occupancyByChar == []


# ════════════════════════════════════════════════════════════
#  折线几何
# ════════════════════════════════════════════════════════════


def test_asset_plot_empty_state(h):
    bridge = h.bridge()
    bridge.refresh()
    assert bridge.assetPlot == {"isEmpty": True, "count": 0, "series": [], "xTicks": [], "yTicks": []}
    assert all(row["latestText"] == "" for row in bridge.assetSeries)
    assert [row["valueText"] for row in bridge.assetSummaryRows] == ["", "", "", "", ""]
    assert [row["deltaText"] for row in bridge.assetSummaryRows] == ["—", "—", "—", "—", "—"]


def test_asset_series_includes_line_value(h):
    """第 5 条线「运行中产线价值」在线表里、且颜色与其它线不同。"""
    h.assets.series = _snapshots(3)
    bridge = h.bridge()
    bridge.refresh()

    series = bridge.assetSeries
    assert [row["key"] for row in series] == ["total", "orders", "inventory", "line_value", "wallet"]
    assert series[3]["label"] == "运行中产线价值"
    assert series[3]["latestText"] == "52.00"  # _snapshots 的 line_value = 50 + i
    colors = {row["color"] for row in series}
    assert len(colors) == len(series), "五条线的颜色必须互不相同"


def test_reload_assets_forces_reread(h):
    """「刷新」按钮：即便快照行数没变也要重读一次服务，并写一条状态。"""
    h.assets.series = _snapshots(2)
    bridge = h.bridge()
    bridge.refresh()
    assert h.assets.days_requested == [qdb._RANGE_ALL_DAYS]

    h.assets.series = _snapshots(2)  # 数据没变
    bridge.reloadAssets()
    assert h.assets.days_requested == [qdb._RANGE_ALL_DAYS, qdb._RANGE_ALL_DAYS], "强制重读"
    assert "资产已刷新" in bridge.statusText


def test_asset_series_names_colors_and_order(h):
    h.assets.series = _snapshots(3)
    bridge = h.bridge()
    bridge.refresh()

    series = bridge.assetSeries
    assert [row["key"] for row in series] == ["total", "orders", "inventory", "line_value", "wallet"]
    assert all(row["visible"] for row in series)
    assert series[0]["latestText"] == "1,002.00"

    # 画布上的每条线必须带与图例同一个色（QML 不许自己读 Theme）
    plot_colors = {entry["key"]: entry["color"] for entry in bridge.assetPlot["series"]}
    assert plot_colors["total"] == series[0]["color"]


def test_asset_plot_geometry(h):
    h.assets.series = _snapshots(3)
    bridge = h.bridge()
    bridge.refresh()

    plot = bridge.assetPlot
    assert plot["isEmpty"] is False
    assert plot["count"] == 3
    assert len(plot["series"]) == 5
    for entry in plot["series"]:
        points = entry["points"]
        assert len(points) == 3
        assert [point["x"] for point in points] == [0.0, 0.5, 1.0]  # 下标均分，首尾 0/1
        assert all(0.0 <= point["y"] <= 1.0 for point in points)
    # 轴刻度：x 用日期、y 按量级自适应单位（K/M/B）
    assert [tick["label"] for tick in plot["xTicks"]] == [row["date"] for row in _snapshots(3)]
    assert plot["yTicks"] and all(tick["label"].endswith(("K", "M", "B", "0", "5")) for tick in plot["yTicks"])


def test_format_axis_value_units():
    assert qdb.format_axis_value(0) == "0"
    assert qdb.format_axis_value(999) == "999"
    assert qdb.format_axis_value(1_500) == "1.5K"
    assert qdb.format_axis_value(1_234_567) == "1.23M"
    assert qdb.format_axis_value(1_230_000_000) == "1.23B"
    assert qdb.format_axis_value(-2_000_000) == "-2M"
    assert qdb.format_axis_value(2_000_000_000) == "2B"


def test_axis_range_follows_visible_series(h):
    """钱包量级远大于其它线：点掉它之后总资产的起伏才看得出来（刻意行为）。"""
    h.assets.series = _snapshots(3, total=1000.0, wallet=1_000_000_000.0)
    bridge = h.bridge()
    bridge.refresh()

    def _spread():
        points = next(e for e in bridge.assetPlot["series"] if e["key"] == "total")["points"]
        ys = [point["y"] for point in points]
        return max(ys) - min(ys)

    squashed = _spread()
    ticks_before = [tick["label"] for tick in bridge.assetPlot["yTicks"]]

    bridge.toggleSeries(4)  # 关掉「钱包余额」
    assert _spread() > squashed
    assert [tick["label"] for tick in bridge.assetPlot["yTicks"]] != ticks_before


def test_toggle_series_flips_and_keeps_one_visible(h):
    h.assets.series = _snapshots(3)
    bridge = h.bridge()
    bridge.refresh()

    bridge.toggleSeries(0)
    assert bridge.assetSeries[0]["visible"] is False
    assert [e["key"] for e in bridge.assetPlot["series"]] == ["orders", "inventory", "line_value", "wallet"]

    bridge.toggleSeries(0)
    assert bridge.assetSeries[0]["visible"] is True

    # 全关：最后一次关闭被忽略（并记一条 warning）
    for index in range(4):
        bridge.toggleSeries(index)
    with _warnings() as records:
        bridge.toggleSeries(4)
    assert any("至少保留一条可见线" in record.getMessage() for record in records)
    assert bridge.assetSeries[4]["visible"] is True
    assert len(bridge.assetPlot["series"]) == 1


def test_toggle_series_ignores_out_of_range(h):
    h.assets.series = _snapshots(3)
    bridge = h.bridge()
    bridge.refresh()
    bridge.toggleSeries(99)
    bridge.toggleSeries(-1)
    assert all(row["visible"] for row in bridge.assetSeries)


def test_asset_summary_rows_delta(h):
    today = date.today()
    h.assets.series = [
        {
            "date": (today - timedelta(days=1)).isoformat(),
            "total": 1000.0,
            "orders": 0.0,
            "inventory": 0.0,
            "wallet": 0.0,
        },
        {"date": today.isoformat(), "total": 1032.0, "orders": 0.0, "inventory": 0.0, "wallet": 0.0},
    ]
    bridge = h.bridge()
    bridge._all_series_rows = [dict(r) for r in h.assets.series]
    bridge._apply_range()

    rows = bridge.assetSummaryRows
    assert rows[0]["valueText"] == "1,032.00"
    assert rows[0]["deltaText"] == "+32.00 (+3.2%)"
    assert rows[0]["deltaPos"] is True
    assert rows[1]["deltaText"] == "+0.00"  # 有两点但没变化：给 0 而不是「—」
    assert rows[1]["valueText"] == "0.00"

    # 单点（无历史可比）也给「—」
    h.assets.series = h.assets.series[:1]
    bridge._all_series_rows = [dict(r) for r in h.assets.series]
    bridge._apply_range()
    assert bridge.assetSummaryRows[0]["deltaText"] == "—"
    assert bridge.assetSummaryRows[0]["valueText"] == "1,000.00"


def test_asset_summary_baseline_sits_before_the_window(h):
    """涨跌基准取**档位起点之前**最近的一条快照 —— 「近 7 天」要跟 7 天前那条比。

    回归：早先拿的是**区间内首个点**（今天 − 6 天），于是用户选「近 7 天」看到的
    其实是 6 天的涨跌；窗口里缺天时更短。构造 9 天数据（今天 − 8 … 今天，每天 +100），
    区间起点 = 今天 − 6，基准必须落在 今天 − 7 而不是今天 − 6。
    """
    today = date.today()
    h.assets.series = [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "total": 1000.0 + 100.0 * (8 - offset),
            "orders": 0.0,
            "inventory": 0.0,
            "wallet": 0.0,
        }
        for offset in range(8, -1, -1)  # 今天−8 … 今天
    ]
    bridge = h.bridge()
    bridge._all_series_rows = [dict(r) for r in h.assets.series]
    bridge._apply_range()

    assert bridge._baseline_row["date"] == (today - timedelta(days=7)).isoformat()
    row = bridge.assetSummaryRows[0]
    assert row["valueText"] == "1,800.00"
    assert row["deltaText"] == "+700.00 (+63.6%)"


def test_asset_summary_baseline_falls_back_to_earliest(h):
    """窗口之前一条快照都没有（数据还没攒够）→ 退回区间内最早那条，照常给数字。"""
    today = date.today()
    h.assets.series = [
        {
            "date": (today - timedelta(days=1)).isoformat(),
            "total": 100.0,
            "orders": 0.0,
            "inventory": 0.0,
            "wallet": 0.0,
        },
        {"date": today.isoformat(), "total": 150.0, "orders": 0.0, "inventory": 0.0, "wallet": 0.0},
    ]
    bridge = h.bridge()
    bridge._all_series_rows = [dict(r) for r in h.assets.series]
    bridge._apply_range()

    assert bridge._baseline_row["date"] == (today - timedelta(days=1)).isoformat()
    assert bridge.assetSummaryRows[0]["deltaText"] == "+50.00 (+50.0%)"


# ════════════════════════════════════════════════════════════
#  区间档位（自然月 / 自然年）
# ════════════════════════════════════════════════════════════


def test_range_window_natural_boundaries():
    ref = date(2026, 3, 5)
    assert qdb.range_window(0, ref) == (7, date(2026, 2, 27))
    assert qdb.range_window(1, ref) == (5, date(2026, 3, 1))  # 当月天数 = 自然月起点到今天
    assert qdb.range_window(2, ref) == (64, date(2026, 1, 1))  # 当年天数 = 1/1 到今天（31+28+5）
    assert qdb.range_window(3, ref) == (3650, None)


def test_range_window_handles_month_and_year_start():
    assert qdb.range_window(1, date(2026, 1, 1)) == (1, date(2026, 1, 1))
    assert qdb.range_window(2, date(2026, 1, 1)) == (1, date(2026, 1, 1))
    assert qdb.range_window(2, date(2026, 12, 31))[0] == 365


def test_trim_from_keeps_unparseable_dates():
    rows = [
        {"date": "2026-01-01"},
        {"date": "2026-02-01"},
        {"date": ""},
        {"date": "不是日期"},
    ]
    kept = qdb.trim_from(rows, date(2026, 2, 1))
    assert kept == [{"date": "2026-02-01"}, {"date": ""}, {"date": "不是日期"}]


def test_set_range_index_trims_by_natural_window(h):
    today = date.today()
    h.assets.series = _snapshots(90)
    bridge = h.bridge()
    bridge.refresh()
    assert bridge.rangeIndex == 0
    assert bridge.rangeLabels == ["近 7 天", "本月", "本年", "总"]
    assert bridge.assetPlot["count"] == 7

    bridge.setRangeIndex(1)  # 本月：自然月起点到今天
    month_start = today.replace(day=1)
    expected_month = sum(1 for row in h.assets.series if date.fromisoformat(row["date"]) >= month_start)
    assert bridge.assetPlot["count"] == expected_month

    bridge.setRangeIndex(2)  # 本年：自然年起点到今天
    year_start = today.replace(month=1, day=1)
    expected_year = sum(1 for row in h.assets.series if date.fromisoformat(row["date"]) >= year_start)
    assert bridge.assetPlot["count"] == expected_year

    bridge.setRangeIndex(3)  # 总
    assert bridge.assetPlot["count"] == 90

    bridge.setRangeIndex(99)  # 越界忽略
    assert bridge.rangeIndex == 3


# ════════════════════════════════════════════════════════════
#  钱包
# ════════════════════════════════════════════════════════════


def test_wallet_text_roundtrip(h):
    bridge = h.bridge()
    bridge.setWalletText("1,234,567.89")
    assert bridge.walletText == "1,234,567.89"
    assert h.assets.wallet == pytest.approx(1234567.89)
    assert h.assets.snapshots == [pytest.approx(1234567.89)]  # 记了一条快照
    assert "资产快照" in bridge.statusText


def test_wallet_text_invalid_keeps_old_value(h):
    h.assets.wallet = 500.0
    bridge = h.bridge()
    bridge.setWalletText("不是数字")
    assert bridge.walletText == "500.00"
    assert h.assets.snapshots == []
    assert "不是有效金额" in bridge.statusText


def test_wallet_text_loaded_lazily(h):
    h.assets.wallet = 42.5
    bridge = h.bridge()
    assert bridge.walletText == "42.50"


# ════════════════════════════════════════════════════════════
#  挂单
# ════════════════════════════════════════════════════════════


def test_read_orders_reports_missing_file(h):
    h.orders.path = None
    bridge = h.bridge()
    bridge.readOrders()
    assert "没找到订单导出文件" in bridge.statusText
    assert "当前目录" in bridge.statusText
    assert bridge.buyOrderRows == [] and bridge.sellOrderRows == []  # 不清空、不抛异常
    assert h.orders.dirs == [None]  # 目录固定默认 → 把 None 交给服务


def _write_export(tmp_path, name: str = "My Orders - 2026.09.16 213000.txt") -> str:
    """真的落一个文件 —— 桥是读文件的（不是读剪贴板），路径不存在时它会走报错分支。"""
    path = tmp_path / name
    path.write_text("Order ID\tItem\n", encoding="utf-8")
    return str(path)


def test_read_orders_imports_and_records_snapshot(h, tmp_path):
    h.orders.path = _write_export(tmp_path)
    h.orders.rows = [_order(11, is_buy=True, price=100.0, remain=10), _order(12, is_buy=False, price=2.5, remain=4)]
    h.orders.unparsed = 2
    h.assets.series = _snapshots(2)
    bridge = h.bridge()
    bridge.readOrders()

    assert len(_orders_in(h.conn)) == 2
    assert h.assets.snapshots == [None]  # record_snapshot() 回写一条资产快照
    assert "跳过 2 行" in bridge.statusText  # 解析器报的跳过行数要透出来

    # 单元格格式化：物品 / 价格 / 剩余÷总量 / 位置 / 角色（**没有方向列** —— 表本身就是方向）
    # 这份导出没带 charID → 归属列显示「—」，而不是「#0」
    assert [cell["text"] for cell in bridge.sellOrderRows[0]["cells"]] == ["三钛合金", "2.50", "4/4", "Jita IV-4", "—"]
    assert [cell["text"] for cell in bridge.buyOrderRows[0]["cells"]] == [
        "三钛合金",
        "100.00",
        "10/10",
        "Jita IV-4",
        "—",
    ]
    assert bridge.buyOrderCount == 1
    assert bridge.sellOrderCount == 1

    # 汇总：买卖单计数与挂单总额都是算出来的
    assert bridge.openOrderSummary.startswith("2 笔挂单 · 卖单 1 · 买单 1 · 挂单总额 1,010.00 ISK")


def test_read_orders_falls_back_to_location_id_and_name_backfill(h, tmp_path, monkeypatch):
    """`location_name` 空 → 用 `location_id` 去空间站表补；补不到才显示 `#<id>`。"""

    def _no_station(location_ids: set[int]) -> dict[int, tuple[str, str]]:
        return {}

    def _one_station(location_ids: set[int]) -> dict[int, tuple[str, str]]:
        return {60003760: ("Jita IV-4", "Jita")}

    h.orders.path = _write_export(tmp_path)
    h.orders.rows = [_order(21, location_name="", location_id=60003760, type_name="")]
    monkeypatch.setattr("services.npc_seller.resolve_stations_by_ids", _no_station)
    bridge = h.bridge()
    bridge.readOrders()
    cells = [cell["text"] for cell in bridge.buyOrderRows[0]["cells"]]
    assert cells[0] == "#1001"  # 物品名缺失 → #type_id
    assert cells[3] == "#60003760"  # 补不到空间站名 → #location_id

    # 补得到时用真名（补名发生在解析器之外）
    monkeypatch.setattr("services.npc_seller.resolve_stations_by_ids", _one_station)
    h.orders.rows = [_order(22, location_name="", location_id=60003760)]
    bridge.readOrders()
    assert [cell["text"] for cell in bridge.buyOrderRows[0]["cells"]][3] == "Jita IV-4"


def test_read_orders_uses_default_dir_always(h, tmp_path):
    """导出目录**固定**用游戏默认目录（自定义目录那一行已按用户要求删掉）。"""
    h.orders.path = None
    bridge = h.bridge()
    bridge.readOrders()
    assert h.orders.dirs == [None], "应把 None 交给 order_export.find_latest_export（它自己用默认目录）"


def test_read_orders_reports_empty_after_list_stays(h):
    """找不到文件时**不清空**已有列表，也不抛。"""
    with h.user_conn() as conn:
        conn.execute(
            "INSERT INTO open_orders (order_id, is_buy, price, volume_total, volume_remain, imported_at) "
            "VALUES (7, 0, 1.0, 1, 1, '2026-09-16 10:00:00')"
        )
    h.orders.path = None
    bridge = h.bridge()
    bridge.readOrders()
    assert bridge.sellOrderRows and len(bridge.sellOrderRows) == 1


def test_read_orders_is_idempotent(h, tmp_path):
    """同一份文件重导：order_id 主键 → 不翻倍，也**不产生变动**（钱包不动、不弹框）。"""
    h.orders.path = _write_export(tmp_path)
    h.orders.rows = [_order(31), _order(32)]
    bridge = h.bridge()
    bridge.readOrders()
    bridge.readOrders()
    assert len(_orders_in(h.conn)) == 2
    assert h.change_dialog.calls == [], "同一份文件重导没有变动 → 不弹确认框"
    assert bridge.previewOrderChanges() == []
    assert h.assets.wallet in (None, 0.0)


# ── 订单变动弹窗（在桥里弹，QML 不参与）──────────────────────


def _import_twice(h, tmp_path, monkeypatch, bridge: QueryDashboardBridge, *, second_remain: int | None = None) -> None:
    """导入两次造出变动：第一次 41 + 42；第二次 41（42 消失；`second_remain` 给定时 41 数量变少）。

    「当前时间」固定且两次落在不同秒 —— `imported_at` 是全秒精度的，撞车会让
    变动分类（按 order_id 比对前后快照）之外的日志时间戳不好读（本用例不依赖它，但保持一致）。
    """
    clock = {"now": datetime(2026, 9, 16, 10, 0, 0)}

    class _Clock:
        def now(self) -> datetime:
            return clock["now"]

    monkeypatch.setattr(qdb, "datetime", _Clock())
    h.orders.path = _write_export(tmp_path, "a.txt")
    h.orders.rows = [_order(41, is_buy=False, price=10.0, remain=5), _order(42, is_buy=False, price=2.0, remain=3)]
    bridge.readOrders()

    clock["now"] = datetime(2026, 9, 16, 10, 5, 0)
    if second_remain is None:
        h.orders.rows = [_order(41, is_buy=False, price=10.0, remain=5)]
    else:
        h.orders.rows = [_order(41, is_buy=False, price=10.0, remain=second_remain)]
    bridge.readOrders()


def test_order_change_dialog_asks_only_when_changes(h, tmp_path, monkeypatch):
    """有变动才弹；用户点「取消」→ 什么都不做（挂单原样留着、钱包不动）。"""
    bridge = h.bridge()
    _import_twice(h, tmp_path, monkeypatch, bridge)

    assert len(h.change_dialog.calls) == 1, "第一次导入没有变动 → 只在第二次弹"
    rows, wallet = h.change_dialog.calls[0]
    assert [row["order_id"] for row in rows] == [42], "只有消失的那笔算变动"
    assert rows[0]["kind"] == "gone"
    assert rows[0]["volume"] == 3  # 原剩余量
    assert wallet == 0.0

    assert [row["order_id"] for row in _orders_in(h.conn)] == [41, 42], "取消 → 不自动删"
    assert "未处理" in bridge.statusText
    assert bridge.previewOrderChanges()[0]["order_id"] == 42  # 变动留着，下次导入重新提示


def test_order_change_filled_credits_wallet(h, tmp_path, monkeypatch):
    """卖单判定「卖完了」→ 钱包 +价格×剩余量；挂单行从列表移除；落一条台账。"""
    h.change_dialog.answer = True
    h.assets.wallet = 1000.0
    bridge = h.bridge()
    _import_twice(h, tmp_path, monkeypatch, bridge)

    assert h.assets.wallet == pytest.approx(1000.0 + 3 * 2.0), "卖出 3 件 × 2.0"
    assert [row["order_id"] for row in _orders_in(h.conn)] == [41]
    events = _events_in(h.conn)
    assert len(events) == 1
    assert events[0]["outcome"] == "filled"
    assert events[0]["delta"] == pytest.approx(6.0)
    assert "钱包 +6.00 ISK" in bridge.statusText
    assert h.assets.snapshots, "处理完要重记一条资产快照"


def test_order_change_cancelled_leaves_wallet_alone(h, tmp_path, monkeypatch):
    """判成「手动撤销」→ 不动钱包；但那一单本来就在导出文件里消失了（`new_remain` 为 None），
    所以照旧从挂单列表移除 —— 撤单在游戏里同样不再挂单。"""
    h.change_dialog.answer = True
    h.change_dialog.choices = {0: 1}  # 第 0 行选「手动撤销」
    h.assets.wallet = 1000.0
    bridge = h.bridge()
    _import_twice(h, tmp_path, monkeypatch, bridge)

    assert h.assets.wallet == pytest.approx(1000.0)
    assert [row["order_id"] for row in _orders_in(h.conn)] == [41]
    events = _events_in(h.conn)
    assert events[0]["outcome"] == "cancelled" and events[0]["delta"] == 0.0
    assert "钱包 +0.00 ISK" in bridge.statusText


def test_order_change_cancelled_on_partial_keeps_order(h, tmp_path, monkeypatch):
    """部分成交那笔选「手动撤销」：**这笔不入账、但挂单也留着**（它还在本次导出里）。

    这里锁住「选择只决定记账」这条契约 —— 早先的实现把「撤销」当成删除，
    会把仍在挂单里的行抹掉。

    导入阶段先让弹窗回答「取消」（变动原样留着），再按设定重放一次。
    """
    bridge = h.bridge()
    _import_twice(h, tmp_path, monkeypatch, bridge, second_remain=2)

    # 变动顺序按库里的 order_id：0 = 41（partial，卖了 3 件 ×10）、1 = 42（gone，卖了 3 件 ×2）
    rows, _wallet = h.change_dialog.calls[0]
    partial_index = next(i for i, row in enumerate(rows) if row["order_id"] == 41)
    h.change_dialog.answer = True
    h.change_dialog.choices = {partial_index: 1}
    h.assets.wallet = 500.0
    bridge._review_changes("重放")

    assert h.assets.wallet == pytest.approx(506.0), "只有 42 那笔 +6 入账，41 撤销不入账"
    remaining = {row["order_id"]: row["volume_remain"] for row in _orders_in(h.conn)}
    assert remaining == {41: 2}, "41 仍在挂单里且数量回写成成交后剩下的 2"


def test_order_change_partial_keeps_order_and_credits_sold_volume(h, tmp_path, monkeypatch):
    """数量变少（部分成交）：条目 `kind=='partial'`、数量是**减少量**，成交后挂单行仍在。"""
    h.change_dialog.answer = True
    h.assets.wallet = 0.0
    bridge = h.bridge()
    _import_twice(h, tmp_path, monkeypatch, bridge, second_remain=2)

    rows, _wallet = h.change_dialog.calls[0]
    kinds = {row["order_id"]: (row["kind"], row["volume"]) for row in rows}
    assert kinds == {42: ("gone", 3), 41: ("partial", 3)}, "41 从 5 变 2 → 卖了 3"
    assert h.assets.wallet == pytest.approx(3 * 2.0 + 3 * 10.0), "两笔都成交：6 + 30"
    assert [row["order_id"] for row in _orders_in(h.conn)] == [41]


def test_apply_order_changes_without_dialog(h):
    """无弹窗路径（测试 / 无 GUI）：一律按默认（成交）落账。"""
    h.assets.wallet = 0.0
    bridge = h.bridge()
    bridge._pending_changes = [
        {
            "order_id": 5,
            "name": "三钛合金",
            "is_buy": 0,
            "price": 4.0,
            "volume": 10,
            "delta": 40.0,
            "kind": "gone",
        }
    ]
    with h.user_conn() as conn:
        conn.execute(
            "INSERT INTO open_orders (order_id, is_buy, price, volume_total, volume_remain, imported_at) "
            "VALUES (5, 0, 4.0, 10, 10, '2026-09-16 10:00:00')"
        )
    bridge.applyOrderChanges()

    assert h.assets.wallet == pytest.approx(40.0)
    assert _orders_in(h.conn) == []
    assert bridge.previewOrderChanges() == []
    assert "已处理 1 笔订单变动" in bridge.statusText


def test_apply_order_changes_empty_is_noop(h):
    bridge = h.bridge()
    bridge.applyOrderChanges()
    assert "没有需要应用的订单变动" in bridge.statusText


def test_read_orders_does_not_ask_when_no_changes(h, tmp_path, monkeypatch):
    """首次导入（库里原本没有挂单）→ 没有「消失的旧单」→ 不弹框。"""
    h.orders.path = _write_export(tmp_path)
    h.orders.rows = [_order(51)]
    bridge = h.bridge()
    bridge.readOrders()
    assert h.change_dialog.calls == []


def test_read_orders_does_not_ask_on_failure(h, tmp_path, monkeypatch):
    bridge = h.bridge()

    h.orders.path = None  # 找不到导出文件
    bridge.readOrders()
    assert h.change_dialog.calls == []
    assert "没找到订单导出文件" in bridge.statusText

    def _boom(raw: str) -> tuple[list[dict], int]:
        raise ValueError("坏文件")

    h.orders.path = _write_export(tmp_path)
    monkeypatch.setattr(h.orders, "parse_order_export", _boom)
    bridge.readOrders()
    assert h.change_dialog.calls == []
    assert "订单解析失败" in bridge.statusText

    # 解析出 0 笔（空文件）也不弹
    monkeypatch.setattr(h.orders, "parse_order_export", lambda raw: ([], 3))
    bridge.readOrders()
    assert h.change_dialog.calls == []
    assert "未从" in bridge.statusText


def test_read_orders_only_compares_orders_of_the_same_owner(h, tmp_path):
    """回归：导入某一角色的**个人单**，不能把库里其他角色 / 军团单判成「已成交」。

    挂单有两个来源（游戏日志 / ESI），一个账号还能绑多个角色，而「个人订单-…」与
    「军团订单-…」是两份独立导出。变动识别原先是拿**全表**和本次文件做差 ——
    别的组的挂单会被判成「消失」→ 误判成交 → **错误增减钱包**。
    修复：按 `(char_id, is_corp)` 分组比较。
    """
    with h.conn:
        h.conn.executemany(
            "INSERT INTO open_orders"
            " (order_id, is_buy, price, volume_total, volume_remain, char_id, is_corp, imported_at)"
            " VALUES (?, 0, 100.0, 10, 10, ?, ?, '2026-09-19 10:00:00')",
            [(1, 111, 0), (2, 222, 0), (3, 111, 1)],
        )
    h.assets.wallet = 500.0

    h.orders.path = _write_export(tmp_path)
    # 本次只导入「角色 111 的个人单」，且与库里那条逐字一致 → 组内无变动
    h.orders.rows = [_order(1, is_buy=False, char_id=111, is_corp=False)]
    bridge = h.bridge()
    bridge.readOrders()

    assert {r["order_id"] for r in _orders_in(h.conn)} == {1, 2, 3}, "别的归属组被动了"
    assert h.change_dialog.calls == [], "把别的角色/军团单判成了已成交"
    assert h.assets.wallet == 500.0, "钱包被错误增减"


def test_esi_sync_clears_legacy_unknown_owner_rows(h):
    """回归：ESI 同步要清掉 `char_id=0` 的历史行，否则它们永远是幽灵卖单。

    加列迁移给存量行补的 0，不属于任何角色组 —— 桥按组替换**永远碰不到它们**，
    表现是「老的卖单一直留在列表上」。仍然开着的那些会被主键 `INSERT OR REPLACE`
    改写成真归属；不在 ESI 返回集里的就是真的结束了，该删。
    """
    with h.conn:
        h.conn.executemany(
            "INSERT INTO open_orders"
            " (order_id, is_buy, price, volume_total, volume_remain, char_id, is_corp, imported_at)"
            " VALUES (?, 0, 100.0, 1, 1, ?, ?, '2026-09-20 14:26:46')",
            [(901, 0, 0), (902, 111, 0)],
        )
    h.assets.wallet = 500.0

    h.bridge()._on_esi_pulled(
        {
            "orders": [_order(902, is_buy=False, char_id=111)],
            "wallet_total": 111.0,
            "corp_total": None,
            "include_corp": False,
            "groups": [[111, 0], [111, 1]],
            "chars": 1,
            "errors": [],
        }
    )

    assert {r["order_id"] for r in _orders_in(h.conn)} == {902}, "无归属的历史行没被清掉"
    assert h.assets.wallet == 111.0, "ESI 的钱包是绝对覆盖，不是增减"


def test_read_orders_skips_export_older_than_last_esi_sync(h, tmp_path):
    """回归：比上次 ESI 同步还旧的导出文件**不许覆盖**。

    用旧的盖新的不只是显示问题：变动识别会拿旧文件和新数据做差，把 ESI 拉到的挂单
    判成「已成交」→ **误动钱包**。
    """
    path = _write_export(tmp_path)
    stale = (datetime.now() - timedelta(days=3)).timestamp()
    os.utime(path, (stale, stale))
    h.esi_synced_at = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    h.orders.path = path
    h.orders.rows = [_order(1)]

    with h.conn:
        h.conn.execute(
            "INSERT INTO open_orders (order_id, is_buy, price, volume_total, volume_remain,"
            " char_id, is_corp, imported_at) VALUES (7, 0, 1.0, 1, 1, 111, 1, '2026-09-20 22:27:47')"
        )

    bridge = h.bridge()
    bridge.readOrders()

    assert "已跳过" in bridge.statusText
    assert {r["order_id"] for r in _orders_in(h.conn)} == {7}, "ESI 的行被旧文件盖掉了"
    assert h.change_dialog.calls == [], "旧文件不该产生任何变动"

    # 反过来：比同步时刻新的文件照常导入（否则守卫就成了永久禁用日志导入）
    fresh = (datetime.now() + timedelta(minutes=1)).timestamp()
    os.utime(path, (fresh, fresh))
    bridge.readOrders()
    assert {r["order_id"] for r in _orders_in(h.conn)} == {1, 7}


def test_esi_sync_detects_fills_but_leaves_wallet_alone(h):
    """两次 ESI 同步之间要算得出「卖出 / 买到」，但**不能动钱包**。

    ESI 给的是绝对余额，再按成交加减一次会算两遍 —— 所以那一路只落台账。
    """
    with h.conn:
        h.conn.executemany(
            "INSERT INTO open_orders (order_id, is_buy, price, volume_total, volume_remain,"
            " char_id, is_corp, imported_at)"
            " VALUES (?, 0, 100.0, 10, ?, 111, 0, '2026-09-20 22:00:00')",
            [(1, 10), (2, 4)],
        )
    h.assets.wallet = 500.0
    h.change_dialog.answer = True  # 用户点了「应用变动」

    h.bridge()._on_esi_pulled(
        {
            # 1 号整笔消失、2 号 4 → 2（部分成交）
            "orders": [_order(2, is_buy=False, remain=2, char_id=111)],
            "wallet_total": 777.0,
            "corp_total": None,
            "include_corp": False,
            "groups": [[111, 0], [111, 1]],
            "chars": 1,
            "errors": [],
        }
    )

    assert len(h.change_dialog.calls) == 1, "两次 ESI 之间没算出变动"
    # 钱包断言放前面：它是这条用例真正的钱账守卫（放后面会被 ledger_only 那条挡住）
    assert h.assets.wallet == 777.0, "钱包应保持 ESI 给的绝对值，不能再按成交加减"
    assert h.change_dialog.ledger_only == [True], "ESI 路径必须只记台账"
    assert _events_in(h.conn), "变动没落台账"


# ════════════════════════════════════════════════════════════
#  订单变动的纯函数分类
# ════════════════════════════════════════════════════════════


def test_classify_order_changes_kinds_and_signs(h):
    """消失 → gone（数量=原剩余）；变少 → partial（数量=减少量）；变多/新增不算变动。"""
    before = {
        1: {"volume_remain": 5, "price": 10.0, "is_buy": 0, "type_name": "卖单"},
        2: {"volume_remain": 8, "price": 3.0, "is_buy": 1, "type_name": "买单"},
        3: {"volume_remain": 4, "price": 1.0, "is_buy": 0, "type_name": "没动"},
        4: {"volume_remain": 2, "price": 1.0, "is_buy": 0, "type_name": "变多了"},
        5: {"volume_remain": 0, "price": 1.0, "is_buy": 0, "type_name": "本来就空了"},
    }
    after = {
        2: {"volume_remain": 5, "price": 3.0, "is_buy": 1},
        3: {"volume_remain": 4, "price": 1.0, "is_buy": 0},
        4: {"volume_remain": 9, "price": 1.0, "is_buy": 0},
        5: {"volume_remain": 0, "price": 1.0, "is_buy": 0},
    }

    changes = {row["order_id"]: row for row in qdb.classify_order_changes(before, after)}

    assert set(changes) == {1, 2}
    assert changes[1]["kind"] == "gone"
    assert changes[1]["volume"] == 5
    assert changes[1]["delta"] == 50.0  # 卖出 → 钱包 +
    assert changes[2]["kind"] == "partial"
    assert changes[2]["volume"] == 3
    assert changes[2]["delta"] == -9.0  # 买入 → 钱包 −
    assert changes[1]["name"] == "卖单"


def test_classify_order_changes_ignores_new_orders(h):
    """本次新挂出去的单不算变动（挂单时钱包就已经变过了）。"""
    after = {9: {"volume_remain": 1, "price": 1.0, "is_buy": 1, "type_name": "新单"}}
    assert qdb.classify_order_changes({}, after) == []


# ════════════════════════════════════════════════════════════
#  刷新生命周期
# ════════════════════════════════════════════════════════════


def _counting(bridge: QueryDashboardBridge) -> list[int]:
    counter: list[int] = []
    bridge.changed.connect(lambda: counter.append(1))
    return counter


def test_refresh_is_idempotent(h):
    """指纹没变 → 不重算、不发 changed（否则 QML 每 tick 重绘）。"""
    h.plans = [_plan(1, status="in_progress", parallels=1)]
    h.assets.series = _snapshots(3)
    bridge = h.bridge()
    counter = _counting(bridge)

    bridge.refresh()
    first = len(counter)
    assert first > 0

    bridge.refresh()
    assert len(counter) == first


def test_refresh_recomputes_when_plans_change(h):
    """计划状态变了 → 指纹变 → 必须重算（占用块与「待下线 N」都要跟着动）。"""
    h.plans = [_plan(1, status="in_progress")]
    bridge = h.bridge()
    counter = _counting(bridge)
    bridge.refresh()
    first = len(counter)

    h.plans = [_plan(1, status="ready")]  # 待下线了 → 占用少一条、提示多一条
    bridge.refresh()
    assert len(counter) > first
    assert bridge.occupancyByChar[0]["lines"][0]["readyText"] == "待下线 1"


def test_refresh_recomputes_when_orders_change(h):
    bridge = h.bridge()
    counter = _counting(bridge)
    bridge.refresh()
    first = len(counter)

    with h.user_conn() as conn:
        conn.execute(
            "INSERT INTO open_orders (order_id, is_buy, price, volume_total, volume_remain, imported_at) "
            "VALUES (99, 1, 10.0, 1, 1, '2026-09-16 10:00:00')"
        )
    bridge.refresh()
    assert len(counter) > first  # 挂单表变了 → 必须重算
    assert bridge.openOrderSummary.startswith("1 笔挂单")
