"""物品查询页空闲态仪表盘桥的契约测试。

对照 `ui_qml/views/industry/production_launcher.py` 的占用算法与
`ui_qml/bridge/price_chart_bridge.py` 的几何纯函数 —— 桥只做整形，但**整形得对不对**
必须锁住，否则查询页的仪表盘会和产线小助手对不上。

并行交付的两个服务模块（`services.asset_snapshot_service` / `services.order_export`）
与 user.db 在这里全部用替身顶掉：本文件的观察点是**桥自己的行为**
（指纹幂等、区间裁剪、几何、挂单导入与陈旧统计），不是那两个模块。
"""

from __future__ import annotations

import contextlib
import logging
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


class _FakePlanExec:
    """替 `services.plan_execution`（桥只用到这四个入口）。"""

    def __init__(self) -> None:
        self.materials: dict[int, list[dict]] = {}
        self.bp_short: dict[int, str | None] = {}
        self.bp_ready: dict[int, bool] = {}
        self.started: list[int] = []
        self.start_result: dict = {"ok": True, "code": "ok", "message": ""}

    def check_materials(self, plan: dict, mat_hangar_id: int, *, stock: dict | None = None) -> list[dict]:
        return [dict(r) for r in self.materials.get(int(plan.get("id") or 0), [])]

    def binding_shortfall(self, plan_id: int) -> str | None:
        return self.bp_short.get(int(plan_id))

    def plan_blueprint_ready(self, plan: dict) -> bool:
        return self.bp_ready.get(int(plan.get("id") or 0), True)

    def start_plan(self, plan: dict, **kwargs: object) -> dict:
        self.started.append(int(plan.get("id") or 0))
        return dict(self.start_result)


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE asset_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snap_date TEXT UNIQUE, total REAL, orders REAL, inventory REAL,
            wallet REAL, created_at TEXT
        );
        CREATE TABLE open_orders (
            order_id INTEGER PRIMARY KEY, is_buy INTEGER, price REAL,
            volume_total INTEGER, volume_remain INTEGER, location_id INTEGER,
            location_name TEXT, type_id INTEGER, type_name TEXT, issued TEXT,
            duration INTEGER, imported_at TEXT
        );
        """
    )
    return conn


def _orders_in(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM open_orders ORDER BY order_id").fetchall()]


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
        self.exec = _FakePlanExec()
        self.plans: list[dict] = []
        self.stock: dict[int, dict[int, int]] = {_HANGAR: {1001: 500}}

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
    monkeypatch.setattr(qdb, "load_plans_for_wizard", lambda: [dict(p) for p in harness.plans])
    monkeypatch.setattr(qdb, "get_character_list", lambda: [_CHAR])
    monkeypatch.setattr(qdb, "load_all_data", lambda: {"characters": {_CHAR: {"skills": dict(_SKILLS)}}})
    monkeypatch.setattr(qdb, "plan_execution", harness.exec)
    # 库存/默认机库走真实 inventory_manager 会打到真实库，这里一并顶掉
    monkeypatch.setattr(
        "services.inventory_manager.get_hangar_stock", lambda hangar_id: dict(harness.stock.get(int(hangar_id), {}))
    )
    monkeypatch.setattr("services.inventory_manager.get_default_mat_hangar_and_system", lambda: (_HANGAR, 30000142))
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


class _Confirm:
    """替掉桥里的确认框，记录被问了什么。"""

    def __init__(self, answer: bool = True) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def question(self, parent: object, title: str, text: str, *, default_yes: bool = True) -> bool:
        self.calls.append((title, text))
        return self.answer


def _snapshots(days: int = 3, *, total: float = 1000.0, wallet: float = 1_000_000_000.0) -> list[dict]:
    """最近 `days` 天的快照（升序，最后一条是今天）。"""
    today = date.today()
    return [
        {
            "date": (today - timedelta(days=days - 1 - i)).isoformat(),
            "total": total + i,
            "orders": 100.0 + i,
            "inventory": 200.0 + i,
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
    assert row["nameWidth"] == 76  # 固定 76（原实现按字体量宽）
    assert row["slotTotal"] == 13  # 制造 11 + 科研 1 + 反应 1

    lines = row["lines"]
    assert [line["label"] for line in lines] == ["制造", "科研", "反应"]
    for line in lines:
        assert set(line) == {"label", "color", "active", "max", "cap"}
        assert line["color"].startswith("#") and len(line["color"]) == 7
    assert [line["active"] for line in lines] == [2, 0, 0]
    assert [line["max"] for line in lines] == [11, 1, 1]

    assert row["statusText"] == "生产中"
    assert row["statusColor"].startswith("#")
    assert bridge.occupancySummary == "1 人物 · 占用 2/13"


def test_occupancy_status_texts(h):
    """空闲 / 生产中 / 超员（文案与产线小助手逐字一致）。"""
    h.plans = [_plan(1, status="completed")]
    bridge = h.bridge()
    bridge.refresh()
    assert bridge.occupancyRows[0]["statusText"] == "空闲"

    # parallels 超过全部线型容量之和（11+1+1）→ 超员
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
    plan = h.plans[0]
    plan["char_name"] = "临时人物"
    bridge = h.bridge()
    bridge.refresh()
    assert [row["name"] for row in bridge.occupancyRows] == [_CHAR, "临时人物"]


# ════════════════════════════════════════════════════════════
#  折线几何
# ════════════════════════════════════════════════════════════


def test_asset_plot_empty_state(h):
    bridge = h.bridge()
    bridge.refresh()
    assert bridge.assetPlot == {"isEmpty": True, "count": 0, "series": [], "xTicks": [], "yTicks": []}
    assert all(row["latestText"] == "" for row in bridge.assetSeries)
    assert [row["valueText"] for row in bridge.assetSummaryRows] == ["", "", "", ""]
    assert [row["deltaText"] for row in bridge.assetSummaryRows] == ["—", "—", "—", "—"]


def test_asset_series_names_colors_and_order(h):
    h.assets.series = _snapshots(3)
    bridge = h.bridge()
    bridge.refresh()

    series = bridge.assetSeries
    assert [row["key"] for row in series] == ["total", "orders", "inventory", "wallet"]
    assert [row["label"] for row in series] == ["总资产", "挂单金额", "库存材料", "钱包余额"]
    assert all(row["visible"] for row in series)
    assert series[0]["color"] == qdb.QueryDashboardBridge._series_color("PRIMARY")
    assert series[1]["color"] == qdb.QueryDashboardBridge._series_color("ACCENT_GREEN")
    assert series[2]["color"] == qdb.QueryDashboardBridge._series_color("ACCENT_ORANGE")
    assert series[3]["color"] == qdb.QueryDashboardBridge._series_color("ACCENT_YELLOW")
    assert series[0]["latestText"] == "1,002.00"

    # 画布上的每条线也带同一个色（QML 不许自己读 Theme）
    plot_colors = {entry["key"]: entry["color"] for entry in bridge.assetPlot["series"]}
    assert plot_colors["total"] == series[0]["color"]


def test_asset_plot_geometry(h):
    h.assets.series = _snapshots(3)
    bridge = h.bridge()
    bridge.refresh()

    plot = bridge.assetPlot
    assert plot["isEmpty"] is False
    assert plot["count"] == 3
    assert len(plot["series"]) == 4
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


def test_asset_empty_text_says_accumulates(h):
    bridge = h.bridge()
    assert bridge.assetPlot["isEmpty"] is True
    assert "资产快照" in bridge.assetEmptyText
    assert "从首次记录开始" in bridge.assetEmptyText


def test_axis_range_follows_visible_series(h):
    """钱包量级远大于其它三条：点掉它之后总资产的起伏才看得出来（刻意行为）。"""
    h.assets.series = _snapshots(3, total=1000.0, wallet=1_000_000_000.0)
    bridge = h.bridge()
    bridge.refresh()

    def _spread():
        points = next(e for e in bridge.assetPlot["series"] if e["key"] == "total")["points"]
        ys = [point["y"] for point in points]
        return max(ys) - min(ys)

    squashed = _spread()
    ticks_before = [tick["label"] for tick in bridge.assetPlot["yTicks"]]

    bridge.toggleSeries(3)  # 关掉「钱包余额」
    assert _spread() > squashed
    assert [tick["label"] for tick in bridge.assetPlot["yTicks"]] != ticks_before


def test_toggle_series_flips_and_keeps_one_visible(h):
    h.assets.series = _snapshots(3)
    bridge = h.bridge()
    bridge.refresh()

    bridge.toggleSeries(0)
    assert bridge.assetSeries[0]["visible"] is False
    assert [e["key"] for e in bridge.assetPlot["series"]] == ["orders", "inventory", "wallet"]

    bridge.toggleSeries(0)
    assert bridge.assetSeries[0]["visible"] is True

    # 全关：最后一次关闭被忽略（并记一条 warning）
    bridge.toggleSeries(0)
    bridge.toggleSeries(1)
    bridge.toggleSeries(2)
    with _warnings() as records:
        bridge.toggleSeries(3)
    assert any("至少保留一条可见线" in record.getMessage() for record in records)
    assert bridge.assetSeries[3]["visible"] is True
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


def test_open_order_heads_and_empty_summary(h):
    bridge = h.bridge()
    assert bridge.openOrderHeads == ["订单ID", "物品", "方向", "价格", "剩余/总量", "位置"]
    assert bridge.openOrderRows == []
    assert bridge.openOrderSummary == qdb._EMPTY_ORDER_SUMMARY


def test_read_orders_reports_missing_file(h):
    h.orders.path = None
    bridge = h.bridge()
    bridge.readOrders()
    assert "没找到订单导出文件" in bridge.statusText
    assert "当前目录" in bridge.statusText
    assert bridge.openOrderRows == []  # 不清空、不抛异常
    assert h.orders.dirs == [None]  # 没设自定义目录 → 交给服务用默认目录


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
    assert "已记入资产快照" in bridge.statusText
    assert "跳过 2 行" in bridge.statusText

    rows = bridge.openOrderRows
    assert [cell["text"] for cell in rows[0]["cells"]] == ["12", "三钛合金", "卖", "2.50", "4/4", "Jita IV-4"]
    assert rows[0]["cells"][2]["color"] == qdb.QueryDashboardBridge._series_color("ACCENT_RED")
    assert rows[1]["cells"][2]["color"] == qdb.QueryDashboardBridge._series_color("ACCENT_GREEN")

    summary = bridge.openOrderSummary
    assert summary.startswith("2 笔挂单 · 卖单 1 · 买单 1 · 挂单总额 1,010.00 ISK")
    assert "本次导入" in summary
    assert "没出现的旧订单" not in summary  # 首次导入没有陈旧行


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
    cells = [cell["text"] for cell in bridge.openOrderRows[0]["cells"]]
    assert cells[1] == "#1001"  # 物品名缺失 → #type_id
    assert cells[5] == "#60003760"  # 补不到空间站名 → #location_id

    # 补得到时用真名（补名发生在解析器之外）
    monkeypatch.setattr("services.npc_seller.resolve_stations_by_ids", _one_station)
    h.orders.rows = [_order(22, location_name="", location_id=60003760)]
    bridge.readOrders()
    assert [cell["text"] for cell in bridge.openOrderRows[0]["cells"]][5] == "Jita IV-4"


def test_read_orders_is_idempotent(h, tmp_path):
    h.orders.path = _write_export(tmp_path)
    h.orders.rows = [_order(31), _order(32)]
    bridge = h.bridge()
    bridge.readOrders()
    bridge.readOrders()
    assert len(_orders_in(h.conn)) == 2  # order_id 主键 → 重复导入不翻倍
    assert len(h.assets.snapshots) == 2
    assert "本次文件里没出现的旧订单" not in bridge.openOrderSummary


def test_stale_orders_counted_and_dropped_on_demand(h, tmp_path, monkeypatch):
    bridge = h.bridge()

    class _Clock:
        """固定「当前时间」——两次导入必须落在不同秒，否则 imported_at 撞车、陈旧判定失效。"""

        def __init__(self, text: str) -> None:
            self._value = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")

        def now(self) -> datetime:
            return self._value

    monkeypatch.setattr(qdb, "datetime", _Clock("2026-09-16 10:00:00"))

    # 第一次导出：两笔
    h.orders.path = _write_export(tmp_path, "a.txt")
    h.orders.rows = [_order(41, type_name="三钛合金"), _order(42, type_name="类银超金属")]
    bridge.readOrders()
    assert len(_orders_in(h.conn)) == 2

    # 第二次导出：只剩 41（42 可能已成交/撤单）
    monkeypatch.setattr(qdb, "datetime", _Clock("2026-09-16 10:05:00"))
    h.orders.rows = [_order(41, type_name="三钛合金")]
    bridge.readOrders()
    assert len(_orders_in(h.conn)) == 2  # 不自动删
    assert "本次文件里没出现的旧订单 1 笔" in bridge.openOrderSummary
    assert "本次导入 2026-09-16 10:05:00" in bridge.openOrderSummary

    review = bridge.pendingReview()
    assert review["count"] == 1
    assert review["staleCount"] == 1
    assert review["staleNames"] == ["类银超金属"]
    assert "类银超金属" in review["message"]

    bridge.dropStaleOrders()
    assert [row["order_id"] for row in _orders_in(h.conn)] == [41]
    assert "已结束 1 笔陈旧挂单" in bridge.statusText
    assert "没出现的旧订单" not in bridge.openOrderSummary
    # 删完再问一次：没有陈修行了
    bridge.dropStaleOrders()
    assert "没有需要结束的陈旧挂单" in bridge.statusText


def test_pending_review_without_import(h):
    bridge = h.bridge()
    review = bridge.pendingReview()
    assert review["count"] == 0
    assert review["staleCount"] == 0
    assert review["staleNames"] == []
    assert "还没有导入" in review["message"]


def test_export_dir_roundtrip(h, tmp_path):
    h.orders.path = None
    bridge = h.bridge()
    assert bridge.exportDir == ""

    target = str(tmp_path / "logs")
    bridge.setExportDir(target)
    assert bridge.exportDir == target
    assert h.orders.dirs[-1] == target  # 改完立刻按新目录重读一次

    bridge.setExportDir("")
    assert bridge.exportDir == ""
    assert h.orders.dirs[-1] is None


# ════════════════════════════════════════════════════════════
#  快捷产线
# ════════════════════════════════════════════════════════════


def test_quick_rows_include_soft_blocked_and_ready(h):
    h.plans = [
        _plan(1, status="pending", product="可启动的"),
        _plan(2, status="pending", product="缺料的"),
        _plan(3, status="pending", product="缺蓝图的"),
        _plan(4, status="ready", product="待下线的"),
        _plan(5, status="completed", product="已完成的"),
    ]
    h.exec.materials = {2: [{"type_id": 1001, "missing": 5}]}  # 2 缺料（软阻塞）
    h.exec.bp_ready = {3: False}  # 3 缺输入蓝图（硬阻塞）
    bridge = h.bridge()
    bridge.refresh()

    rows = bridge.quickRows
    assert [(r["planId"], r["action"], r["actionText"], r["statusText"]) for r in rows] == [
        (1, "start", "启动", "可启动"),
        (2, "start", "启动", "材料不够"),  # 软阻塞仍可点，与产线小助手同口径
        (4, "complete", "下线", "待下线"),
    ]
    assert all(set(r) == {"planId", "name", "action", "actionText", "statusText"} for r in rows)


def test_quick_rows_caps_at_eight_each(h):
    h.plans = [_plan(i, status="pending") for i in range(1, 13)] + [
        _plan(100 + i, status="ready") for i in range(1, 13)
    ]
    bridge = h.bridge()
    bridge.refresh()
    rows = bridge.quickRows
    assert len(rows) == 16
    assert sum(1 for r in rows if r["action"] == "start") == 8
    assert sum(1 for r in rows if r["action"] == "complete") == 8


def test_quick_action_start_asks_and_executes(h, monkeypatch):
    h.plans = [_plan(1, status="pending", product="可启动的")]
    confirm = _Confirm(True)
    monkeypatch.setattr(qdb, "FMessageDialog", confirm)
    bridge = h.bridge()
    bridge.refresh()

    bridge.quickAction(0)
    assert confirm.calls and confirm.calls[0][0] == "确认启动"
    assert "可启动的" in confirm.calls[0][1]
    assert h.exec.started == [1]
    assert "已启动" in bridge.statusText


def test_quick_action_start_cancelled_by_confirm(h, monkeypatch):
    h.plans = [_plan(1, status="pending")]
    confirm = _Confirm(False)
    monkeypatch.setattr(qdb, "FMessageDialog", confirm)
    bridge = h.bridge()
    bridge.refresh()

    bridge.quickAction(0)
    assert h.exec.started == []
    assert "已取消启动" in bridge.statusText


def test_quick_action_start_blocked_does_not_execute(h, monkeypatch):
    """行建好之后计划变成硬阻塞（例如蓝图被解绑）：槽内必须重新判定并拒绝执行。"""
    h.plans = [_plan(1, status="pending")]
    confirm = _Confirm(True)
    monkeypatch.setattr(qdb, "FMessageDialog", confirm)
    bridge = h.bridge()
    bridge.refresh()
    assert bridge.quickRows[0]["statusText"] == "可启动"

    bridge._plans[0]["status"] = "completed"  # 行建好之后计划被改了状态（硬阻塞）
    bridge.quickAction(0)
    assert h.exec.started == []
    assert "无法启动" in bridge.statusText


def test_quick_action_start_failure_writes_reason(h, monkeypatch):
    h.plans = [_plan(1, status="pending")]
    monkeypatch.setattr(qdb, "FMessageDialog", _Confirm(True))
    h.exec.start_result = {"ok": False, "code": "material_short", "message": "材料不足 2 种"}
    bridge = h.bridge()
    bridge.refresh()

    bridge.quickAction(0)
    assert h.exec.started == [1]
    assert "启动失败" in bridge.statusText and "材料不足 2 种" in bridge.statusText


def test_quick_action_complete_uses_single_row_entry(h, monkeypatch):
    h.plans = [_plan(1, status="ready", product="待下线的")]
    monkeypatch.setattr(qdb, "FMessageDialog", _Confirm(True))
    calls: list[tuple[object, int]] = []

    def _fake_complete(parent: object, plan: dict) -> dict:
        calls.append((parent, int(plan["id"])))
        return {"completed": [1]}

    monkeypatch.setattr(qdb, "_complete_one_plan", _fake_complete)
    bridge = h.bridge()
    bridge.refresh()

    bridge.quickAction(0)
    assert calls == [(None, 1)]
    assert "已下线" in bridge.statusText

    # 返回 None（用户取消 / 已弹过失败告警）→ 文案不能写成成功
    monkeypatch.setattr(qdb, "_complete_one_plan", lambda parent, plan: None)
    bridge.quickAction(0)
    assert "已取消下线" in bridge.statusText


def test_quick_action_out_of_range(h):
    bridge = h.bridge()
    bridge.quickAction(0)
    assert "已失效" in bridge.statusText


def test_refresh_quick_only_recomputes_rows(h):
    h.plans = [_plan(1, status="pending")]
    bridge = h.bridge()
    bridge.refreshQuick()
    assert [r["planId"] for r in bridge.quickRows] == [1]
    h.plans = [_plan(2, status="ready")]
    bridge.refreshQuick()
    assert [(r["planId"], r["action"]) for r in bridge.quickRows] == [(2, "complete")]


# ════════════════════════════════════════════════════════════
#  刷新生命周期
# ════════════════════════════════════════════════════════════


def _counting(bridge: QueryDashboardBridge) -> list[int]:
    counter: list[int] = []
    bridge.changed.connect(lambda: counter.append(1))
    return counter


def test_init_does_not_touch_services(h):
    """构造期不起线程、不查库（本仓硬约束）。"""
    bridge = QueryDashboardBridge()
    assert h.assets.days_requested == []
    assert h.assets.snapshots == []
    assert bridge.occupancyRows == [] and bridge.quickRows == []
    assert bridge.statusText == "就绪"


def test_construction_follows_query_bridge_wiring(h):
    """`query_bridge` 的接法是 `QueryDashboardBridge(self)` —— 第一个位置参数是 shell，不是 parent。"""

    class _FakeBridge:
        _shell = None

    bridge = QueryDashboardBridge(_FakeBridge())
    assert bridge.statusText == "就绪"
    assert bridge._host_widget() is None  # 拿不到真窗口时退化为无 parent，不抛


def test_refresh_is_idempotent(h):
    h.plans = [_plan(1, status="in_progress", parallels=1)]
    h.assets.series = _snapshots(3)
    bridge = h.bridge()
    counter = _counting(bridge)

    bridge.refresh()
    first = len(counter)
    assert first > 0

    bridge.refresh()  # 内容没变 → 不重算、不发 changed
    assert len(counter) == first


def test_refresh_recomputes_when_stock_changes(h):
    h.plans = [_plan(1, status="pending")]
    bridge = h.bridge()
    counter = _counting(bridge)
    bridge.refresh()
    first = len(counter)

    h.stock[_HANGAR] = {1001: 1}  # 库存变了
    bridge.refresh()
    assert len(counter) > first


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
    assert len(counter) > first
    assert bridge.openOrderSummary.startswith("1 笔挂单")
