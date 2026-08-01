"""库存管理 —— 3 个基础 CRUD 测试，使用临时 SQLite 数据库"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from services.inventory_manager import (
    SCHEMA,
    add_item,
    create_hangar,
    delete_hangar,
    get_hangar_config,
    get_hangar_system_id,
    get_hangars,
    set_item_quantity,
    update_cost_price,
    update_hangar_config,
    update_hangar_system,
)


@pytest.fixture
def inv_db():
    """创建临时 user.db，注入到 inventory_manager 模块"""
    import services.inventory_manager as im
    from services.database_manager import DB_PATH_MAP, DatabaseManager

    tmpdir = Path(tempfile.mkdtemp(prefix="inv_test_"))
    user_db = tmpdir / "user.db"

    conn = sqlite3.connect(str(user_db))
    conn.executescript(SCHEMA)
    conn.close()

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP["user"] = str(user_db)

    db = DatabaseManager()
    orig = im.db
    im.db = db

    yield tmpdir

    im.db = orig
    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    import shutil

    shutil.rmtree(str(tmpdir), ignore_errors=True)


class TestHangarBasicCRUD:
    """机库基础 CRUD —— 使用真实 SQLite 临时数据库"""

    def test_create_hangar(self, inv_db):
        """创建机库应插入记录并返回正整数 id"""
        hid = create_hangar("主仓库")
        assert isinstance(hid, int) and hid > 0

        conn = sqlite3.connect(str(inv_db / "user.db"))
        row = conn.execute("SELECT name FROM hangars WHERE id = ?", (hid,)).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "主仓库"

    def test_get_hangars(self, inv_db):
        """查询机库列表应返回所有已有记录"""
        create_hangar("矿仓")
        create_hangar("组件仓")

        hangars = get_hangars()
        assert len(hangars) == 2
        names = [h["name"] for h in hangars]
        assert "矿仓" in names
        assert "组件仓" in names
        for h in hangars:
            assert "id" in h
            assert "name" in h
            assert "notes" in h

    def test_delete_hangar(self, inv_db):
        """删除机库应移除记录并返回 True"""
        hid = create_hangar("待删机库")
        assert delete_hangar(hid) is True

        conn = sqlite3.connect(str(inv_db / "user.db"))
        row = conn.execute("SELECT COUNT(*) FROM hangars WHERE id = ?", (hid,)).fetchone()
        conn.close()
        assert row[0] == 0


class TestHangarSolarSystem:
    """机库所在星系字段 CRUD"""

    def test_create_hangar_with_solar_system(self, inv_db):
        """带星系创建机库"""
        hid = create_hangar("主仓库", solar_system_id=30000142)
        assert isinstance(hid, int) and hid > 0
        hs = get_hangars()
        assert hs[0]["solar_system_id"] == 30000142

    def test_get_hangars_include_solar_system_key(self, inv_db):
        """get_hangars 返回 solar_system_id 键（默认 None）"""
        create_hangar("矿仓")
        h = get_hangars()[0]
        assert "solar_system_id" in h
        assert h["solar_system_id"] is None

    def test_update_hangar_system(self, inv_db):
        """update_hangar_system 置值/清除"""
        hid = create_hangar("主仓库")
        assert update_hangar_system(hid, 30000150) is True
        assert get_hangar_system_id(hid) == 30000150
        assert update_hangar_system(hid, None) is True
        assert get_hangar_system_id(hid) is None

    def test_get_hangar_system_id_none(self, inv_db):
        """无机库/无效 id 返回 None"""
        assert get_hangar_system_id(None) is None
        assert get_hangar_system_id(0) is None


class TestSetItemQuantity:
    """set_item_quantity 全量同步"""

    def test_set_new_item(self, inv_db):
        """新物品带成本写入"""
        hid = create_hangar("仓")
        item_id = set_item_quantity(hid, 1001, 50, cost_price=5.0)
        assert item_id > 0
        conn = sqlite3.connect(str(inv_db / "user.db"))
        row = conn.execute("SELECT quantity, cost_price FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        conn.close()
        assert row == (50, 5.0)

    def test_overwrite_keep_cost(self, inv_db):
        """覆盖数量、未传成本时保留现值"""
        hid = create_hangar("仓")
        set_item_quantity(hid, 1001, 50, cost_price=5.0)
        set_item_quantity(hid, 1001, 30)
        conn = sqlite3.connect(str(inv_db / "user.db"))
        row = conn.execute(
            "SELECT quantity, cost_price FROM inventory_items WHERE hangar_id = ? AND type_id = ?",
            (hid, 1001),
        ).fetchone()
        conn.close()
        assert row == (30, 5.0)

    def test_zero_deletes_row(self, inv_db):
        """数量归零删除行"""
        hid = create_hangar("仓")
        set_item_quantity(hid, 1001, 10)
        set_item_quantity(hid, 1001, 0)
        conn = sqlite3.connect(str(inv_db / "user.db"))
        row = conn.execute(
            "SELECT COUNT(*) FROM inventory_items WHERE hangar_id = ? AND type_id = ?",
            (hid, 1001),
        ).fetchone()
        conn.close()
        assert row[0] == 0

    def test_negative_rejected(self, inv_db):
        """负数拒绝"""
        hid = create_hangar("仓")
        assert set_item_quantity(hid, 1001, -5) == 0


class TestUpdateCostPrice:
    """update_cost_price 覆盖单位成本"""

    def test_update(self, inv_db):
        hid = create_hangar("仓")
        item_id = add_item(hid, 1001, 10, 3.0)
        assert update_cost_price(item_id, 7.5) is True
        conn = sqlite3.connect(str(inv_db / "user.db"))
        cost = conn.execute("SELECT cost_price FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        conn.close()
        assert cost[0] == 7.5

    def test_miss(self, inv_db):
        """不存在的 item_id 返回 False"""
        assert update_cost_price(999999, 1.0) is False


@pytest.fixture
def full_db(temp_db):
    """temp_db（4 库）+ patch inventory_manager.db + user 库补 production_plans 空表"""
    import services.inventory_manager as im

    with temp_db.connect("user") as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS production_plans (
                id INTEGER PRIMARY KEY,
                product_type_id INTEGER,
                blueprint_type_id INTEGER,
                runs INTEGER DEFAULT 1,
                parallels INTEGER DEFAULT 1,
                status TEXT DEFAULT 'pending'
            )
            """
        )
    orig = im.db
    im.db = temp_db
    yield temp_db
    im.db = orig


class TestGetItemsDisplayName:
    """get_items display_name 统一名称解析（Bug2 防回归）"""

    def test_mineral_uses_terminology_override(self, full_db):
        """基础矿物 type_id=34 无 item 行 → terminology override「三钛合金」"""
        import services.inventory_manager as im

        im.init_db()
        hid = im.create_hangar("测试仓")
        im.add_item(hid, 34, 10)
        items = im.get_items(hid)
        assert len(items) == 1
        assert items[0]["display_name"] == "三钛合金"

    def test_unknown_id_fallback(self, full_db):
        """未知 type_id → 回退 str(id)"""
        import services.inventory_manager as im

        im.init_db()
        hid = im.create_hangar("测试仓")
        im.add_item(hid, 99999, 5)
        items = im.get_items(hid)
        assert items[0]["display_name"] == "99999"

    def test_item_table_name(self, full_db):
        """item 表有 zh_name → 用之"""
        import services.inventory_manager as im

        im.init_db()
        hid = im.create_hangar("测试仓")
        im.add_item(hid, 1001, 10)
        items = im.get_items(hid)
        assert items[0]["display_name"] == "三钛合金"

    def test_plan_active_counts_in_progress(self, full_db):
        """in_progress 计划计入 plan_active，pending 计入 plan_usage"""
        import services.inventory_manager as im

        im.init_db()
        hid = im.create_hangar("测试仓")
        im.add_item(hid, 1001, 10000)
        with full_db.connect("user") as conn:
            conn.execute(
                "INSERT INTO production_plans (product_type_id, blueprint_type_id, runs, parallels, status)"
                " VALUES (2001, 3001, 2, 3, 'in_progress')"
            )
        items = im.get_items(hid)
        target = next(it for it in items if it["type_id"] == 1001)
        assert target["plan_active"] == 6000  # 1000 × runs2 × parallels3
        assert target["plan_usage"] == 0


class TestHangarIndustryConfig:
    """机库工业配置（设施类型/设施税/改件）CRUD"""

    def test_get_hangars_include_config_keys(self, inv_db):
        """get_hangars 返回设施配置键（默认 None）"""
        create_hangar("仓")
        h = get_hangars()[0]
        for k in ("facility_type", "facility_tax", "rigs"):
            assert k in h
            assert h[k] is None

    def test_update_hangar_config(self, inv_db):
        """update_hangar_config 写入设施类型/税/改件 JSON"""
        hid = create_hangar("仓")
        assert update_hangar_config(hid, "raitaru", 0.5, [43920, 37160]) is True
        cfg = get_hangar_config(hid)
        assert cfg["facility_type"] == "raitaru"
        assert cfg["facility_tax"] == 0.5
        assert cfg["rigs"] == [43920, 37160]

    def test_get_hangar_config_default(self, inv_db):
        """无机库/未配置返回默认"""
        assert get_hangar_config(None) == {"facility_type": None, "facility_tax": None, "rigs": []}
        hid = create_hangar("仓")
        assert get_hangar_config(hid)["rigs"] == []

    def test_get_hangar_config_invalid_json(self, inv_db):
        """rigs 列非法 JSON 容错为 []"""
        hid = create_hangar("仓")
        conn = sqlite3.connect(str(inv_db / "user.db"))
        conn.execute("UPDATE hangars SET rigs='{bad json' WHERE id=?", (hid,))
        conn.commit()
        conn.close()
        assert get_hangar_config(hid)["rigs"] == []

    def test_update_hangar_config_clear(self, inv_db):
        """清除配置（None）"""
        hid = create_hangar("仓")
        update_hangar_config(hid, "azbel", 0.3, [37170])
        assert update_hangar_config(hid, None, None, None) is True
        assert get_hangar_config(hid) == {"facility_type": None, "facility_tax": None, "rigs": []}
