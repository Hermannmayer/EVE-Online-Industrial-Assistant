"""资产快照服务测试 —— services/asset_snapshot_service.py

覆盖：同日 upsert 覆盖（不累积）、total = inventory + orders + wallet、
load_series 升序与按窗口裁剪、空库返回 []、钱包余额读写往返、基线表自举。
"""

import shutil
import sqlite3
import tempfile
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from services import asset_snapshot_service as svc
from services import inventory_manager as im
from services.inventory_manager import SCHEMA as INV_SCHEMA


@pytest.fixture
def snapshot_env(monkeypatch):
    """临时四库 + 注入 container 到 asset_snapshot_service / inventory_manager。

    照抄 tests/test_plan_execution.py 的 user_env 做法：建临时库、patch DB_PATH_MAP、
    造一个 DatabaseManager 再替换模块级 ``_default_db``。
    """
    from services.database_manager import DB_PATH_MAP, DatabaseManager, get_db
    from tests.conftest import _create_temp_databases

    tmpdir = tempfile.mkdtemp(prefix="eve_snap_")
    db_paths = _create_temp_databases(tmpdir)
    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP.update(db_paths)

    db = DatabaseManager()
    with db.connect("user") as conn:
        conn.executescript(INV_SCHEMA)  # hangars / inventory_items / user_blueprints
        conn.executescript(svc.SCHEMA)  # asset_snapshots / open_orders

    monkeypatch.setattr(svc, "_default_db", lambda: db)
    monkeypatch.setattr(im, "_default_db", lambda: db)
    yield SimpleNamespace(db=db, db_paths=db_paths)

    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    get_db().close_all()
    shutil.rmtree(tmpdir, ignore_errors=True)


def _insert_snapshot(db, snap_date, total=0.0, orders=0.0, inventory=0.0, wallet=0.0):
    with db.connect("user") as conn:
        conn.execute(
            "INSERT INTO asset_snapshots (snap_date, total, orders, inventory, wallet) VALUES (?,?,?,?,?)",
            (snap_date, total, orders, inventory, wallet),
        )


def test_record_snapshot_composition(snapshot_env):
    """total = inventory + orders + wallet，且各行来源正确。"""
    im.init_db()  # seed 默认机库
    im.add_item(1, 1001, 10, 0)  # 10 × 卖价 5.0 = 50.0
    with snapshot_env.db.connect("user") as conn:
        conn.execute("INSERT INTO open_orders (order_id, price, volume_remain) VALUES (1, 100.0, 3)")

    snap = svc.record_snapshot()

    assert snap["inventory"] == 50.0
    assert snap["orders"] == 300.0
    assert snap["wallet"] == 0.0
    assert snap["total"] == 350.0
    assert snap["total"] == snap["inventory"] + snap["orders"] + snap["wallet"]
    assert snap["date"], "应从 SQLite 回读 snap_date"


def test_record_snapshot_upserts_same_day(snapshot_env):
    """同一天调两次只有一行，且值被覆盖。"""
    im.init_db()
    im.add_item(1, 1001, 10, 0)  # inventory 50.0

    svc.record_snapshot()
    svc.record_snapshot(wallet=1000.0)

    with snapshot_env.db.connect("user") as conn:
        rows = conn.execute("SELECT snap_date, total, orders, inventory, wallet FROM asset_snapshots").fetchall()

    assert len(rows) == 1, "同一天只应保留一行"
    assert rows[0]["wallet"] == 1000.0
    assert rows[0]["total"] == 1050.0, "值为第二次调用的结果（覆盖非累积）"


def test_load_series_ascending_and_window(snapshot_env):
    """load_series 按日期升序，并按 days 窗口裁剪。"""
    today = date.today()
    for offset in (200, 10, 3, 1):
        _insert_snapshot(snapshot_env.db, (today - timedelta(days=offset)).isoformat(), total=float(offset))

    series = svc.load_series(days=90)
    dates = [r["date"] for r in series]

    assert dates == sorted(dates), "应升序"
    assert len(series) == 3, "200 天前的记录应被窗口裁掉"
    assert (today - timedelta(days=200)).isoformat() not in dates

    recent = svc.load_series(days=2)
    assert len(recent) == 1, "days=2 只保留最近 1 天"


def test_load_series_empty_returns_list(snapshot_env):
    """空库返回 []，不报错。"""
    assert svc.load_series() == []


def test_wallet_roundtrip():
    """set_wallet_balance / get_wallet_balance 往返（settings.json 由 conftest 隔离）。"""
    assert svc.get_wallet_balance() == 0.0
    svc.set_wallet_balance(123.45)
    assert svc.get_wallet_balance() == 123.45


def test_service_bootstraps_missing_tables(monkeypatch, tmp_path):
    """未经迁移的裸 user.db：入口函数自动补建基线表，load_series 返回 []。"""
    from services.database_manager import DB_PATH_MAP, DatabaseManager, get_db

    user_path = tmp_path / "user.db"
    sqlite3.connect(str(user_path)).close()  # 空库，无任何表

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP["user"] = str(user_path)
    db = DatabaseManager()
    monkeypatch.setattr(svc, "_default_db", lambda: db)
    try:
        assert svc.load_series() == []
        with db.connect("user") as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"asset_snapshots", "open_orders"} <= tables
    finally:
        DB_PATH_MAP.clear()
        DB_PATH_MAP.update(saved)
        get_db().close_all()
