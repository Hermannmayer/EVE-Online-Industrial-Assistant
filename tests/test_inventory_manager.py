"""库存管理 —— 3 个基础 CRUD 测试，使用临时 SQLite 数据库"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from services.inventory_manager import (
    SCHEMA,
    add_item,
    apply_inventory_import,
    create_hangar,
    delete_hangar,
    get_hangar_config,
    get_hangar_name,
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
    orig = im._default_db
    im._default_db = lambda: db

    yield tmpdir

    im._default_db = orig
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

    def test_get_hangar_name(self, inv_db):
        """读取机库名称；无机库/不存在返回空串"""
        hid = create_hangar("主仓库")
        assert get_hangar_name(hid) == "主仓库"
        assert get_hangar_name(None) == ""
        assert get_hangar_name(99999) == ""

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
    """temp_db（4 库）+ patch inventory_manager._default_db + user 库补 production_plans 空表"""
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
                status TEXT DEFAULT 'pending',
                mat_hangar_id INTEGER,
                deposit_hangar_id INTEGER,
                solar_system_id INTEGER
            )
            """
        )
    orig = im._default_db
    im._default_db = lambda: temp_db
    yield temp_db
    im._default_db = orig


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


@pytest.fixture
def import_db():
    """全套临时库（ref/bp/mkt + user SCHEMA + 最小 production_plans），注入 _default_db。

    apply_inventory_import 的跨机库行走 get_items → 需 production_plans 参与占用聚合。
    """
    import shutil
    import tempfile

    import services.inventory_manager as im
    from services.database_manager import DB_PATH_MAP, DatabaseManager, get_db
    from tests.conftest import _create_temp_databases

    tmpdir = Path(tempfile.mkdtemp(prefix="inv_import_"))
    db_paths = _create_temp_databases(str(tmpdir))
    conn = sqlite3.connect(db_paths["user"])
    conn.executescript(SCHEMA)
    conn.executescript(
        "CREATE TABLE production_plans ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, product_type_id INTEGER,"
        " status TEXT DEFAULT 'pending', runs INTEGER DEFAULT 1, parallels INTEGER DEFAULT 1);"
    )
    conn.close()

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP.update(db_paths)
    db = DatabaseManager()
    orig = im._default_db
    im._default_db = lambda: db
    yield tmpdir
    im._default_db = orig
    db.close_all()
    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    get_db().close_all()
    shutil.rmtree(str(tmpdir), ignore_errors=True)


class TestApplyInventoryImport:
    """apply_inventory_import — 剪贴板导入应用（增量/全量/跨机库移动）"""

    @staticmethod
    def _stock(import_db, hid) -> dict[int, int]:
        conn = sqlite3.connect(str(Path(import_db) / "user.db"))
        rows = conn.execute("SELECT type_id, quantity FROM inventory_items WHERE hangar_id = ?", (hid,)).fetchall()
        conn.close()
        return dict(rows)

    def test_incremental_adds_on_top(self, import_db):
        """增量累加：在现有数量上累加 delta，返回 added 行数"""
        hid = create_hangar("主仓")
        add_item(hid, 1001, 10, 5.0)
        added, moved = apply_inventory_import(hid, [(1001, 5, 5.0, None), (1002, 3, 8.0, None)], "incremental")
        assert (added, moved) == (2, 0)
        assert self._stock(import_db, hid) == {1001: 15, 1002: 3}

    def test_incremental_skips_non_positive_delta(self, import_db):
        """增量只加不减：delta<=0 跳过，库存不变"""
        hid = create_hangar("主仓")
        add_item(hid, 1001, 10, 5.0)
        added, moved = apply_inventory_import(hid, [(1001, 0, 5.0, None), (1001, -3, 5.0, None)], "incremental")
        assert (added, moved) == (0, 0)
        assert self._stock(import_db, hid) == {1001: 10}

    def test_full_sets_target_quantity(self, import_db):
        """全量同步：按 targets 最终数量覆盖（更新既有行 + 插入新行）"""
        hid = create_hangar("主仓")
        add_item(hid, 1001, 10, 5.0)
        added, moved = apply_inventory_import(
            hid, [(1001, 0, 5.0, None), (1002, 0, 8.0, None)], "full", targets={1001: 7, 1002: 4}
        )
        assert (added, moved) == (2, 0)
        assert self._stock(import_db, hid) == {1001: 7, 1002: 4}

    def test_full_zero_removes_row(self, import_db):
        """全量同步归零：目标 0 → 删除行；行仍计入 applied（added），实际增减由变动汇总展示"""
        hid = create_hangar("主仓")
        add_item(hid, 1001, 10, 5.0)
        added, moved = apply_inventory_import(hid, [(1001, 0, 5.0, None)], "full", targets={1001: 0})
        assert (added, moved) == (1, 0)
        assert self._stock(import_db, hid) == {}

    def test_full_clear_missing_zeroes_rows_absent_from_clipboard(self, import_db):
        """全量同步的反向差集：「库里有、剪贴板没有」的行必须清零（删行）。

        回归背景：full 原先只遍历剪贴板行，「库里有、剪贴板里没有的」整类永远不动 ——
        用户改完库存后残留的 `41484=6` 一直在，计划表把不存在的 6 个当可用。
        `clear_missing` 的值是**该行现有数量**（调用方核对用），服务一律清零。
        """
        hid = create_hangar("主仓")
        add_item(hid, 1001, 10, 5.0)  # 剪贴板里有 → 按 7 覆盖
        add_item(hid, 1002, 6, 3.0)  # 剪贴板里没有 → 清零删行
        added, moved = apply_inventory_import(
            hid, [(1001, 0, 5.0, None)], "full", targets={1001: 7}, clear_missing={1002: 6}
        )
        assert (added, moved) == (2, 0)
        assert self._stock(import_db, hid) == {1001: 7}

    def test_full_clear_missing_value_is_informational(self, import_db):
        """`clear_missing` 的值不参与写库：传现有数量也照样清零（不是 set 回原值）。"""
        hid = create_hangar("主仓")
        add_item(hid, 1002, 6, 3.0)
        added, _moved = apply_inventory_import(hid, [], "full", targets={}, clear_missing={1002: 6})
        assert added == 1
        assert self._stock(import_db, hid) == {}

    def test_full_clear_missing_does_not_clobber_clipboard_target(self, import_db):
        """与剪贴板目标撞车时以剪贴板为准 —— 不许把用户刚 set 的值再清掉（删数据兜底）。"""
        hid = create_hangar("主仓")
        add_item(hid, 1001, 10, 5.0)
        _added, _moved = apply_inventory_import(
            hid, [(1001, 0, 5.0, None)], "full", targets={1001: 4}, clear_missing={1001: 10}
        )
        assert self._stock(import_db, hid) == {1001: 4}

    def test_incremental_ignores_clear_missing(self, import_db):
        """incremental 只增不减：clear_missing 一律不生效（语义一字不变）。"""
        hid = create_hangar("主仓")
        add_item(hid, 1001, 10, 5.0)
        add_item(hid, 1002, 6, 3.0)
        added, moved = apply_inventory_import(hid, [(1001, 5, 5.0, None)], "incremental", clear_missing={1002: 0})
        assert (added, moved) == (1, 0)
        assert self._stock(import_db, hid) == {1001: 15, 1002: 6}

    def test_move_from_other_hangar(self, import_db):
        """跨机库行：源机库整体移动到目标，计入 moved"""
        src = create_hangar("源仓")
        dst = create_hangar("目标仓")
        add_item(src, 1001, 20, 5.0)
        added, moved = apply_inventory_import(dst, [(1001, 20, 5.0, src)], "incremental")
        assert (added, moved) == (0, 1)
        assert self._stock(import_db, src) == {}
        assert self._stock(import_db, dst) == {1001: 20}

    def test_move_missing_source_item_skipped(self, import_db):
        """跨机库源库无该物品 → 不移动不报错"""
        src = create_hangar("源仓")
        dst = create_hangar("目标仓")
        added, moved = apply_inventory_import(dst, [(9999, 1, 5.0, src)], "incremental")
        assert (added, moved) == (0, 0)

    def test_failure_rolls_back_whole_batch(self, import_db):
        """整批单事务：中途失败 → 前面已写行一并回滚（不留改了一半的库存）

        回归背景：逐行各自开事务时每行一次 commit（几百行 = 秒级卡顿），改为整批一个
        事务后必须保证失败不落盘 —— 「库存修正」要么全改要么不改。
        """
        import services.inventory_manager as im

        hid = create_hangar("主仓")
        add_item(hid, 1001, 10, 5.0)
        boom = RuntimeError("模拟中途写库失败")
        calls = {"n": 0}
        orig = im.add_item

        def _flaky(hangar_id, type_id, quantity, cost_price=0, *, conn=None):
            calls["n"] += 1
            if calls["n"] == 2:
                raise boom
            return orig(hangar_id, type_id, quantity, cost_price, conn=conn)

        im.add_item = _flaky
        try:
            with pytest.raises(RuntimeError, match="模拟中途写库失败"):
                apply_inventory_import(hid, [(1002, 3, 1.0, None), (1003, 4, 1.0, None)], "incremental")
        finally:
            im.add_item = orig

        assert self._stock(import_db, hid) == {1001: 10}, "失败前写入的行必须回滚"


class TestHangarReferences:
    """删除机库前的引用检查与重指向（回归：悬空引用会导致默认机库设置被静默清空）"""

    def test_no_references(self, full_db):
        import services.inventory_manager as im

        im.init_db()
        hid = im.create_hangar("独立仓")
        assert im.hangar_references(hid) == []

    def test_settings_and_plan_references(self, full_db, monkeypatch):
        import services.inventory_manager as im
        import services.user_settings as us

        im.init_db()
        hid = im.create_hangar("吉他仓库")
        with full_db.connect("user") as conn:
            conn.execute(
                "INSERT INTO production_plans (id, mat_hangar_id, deposit_hangar_id) VALUES (1, ?, ?)", (hid, hid)
            )
            conn.execute("INSERT INTO production_plans (id, mat_hangar_id) VALUES (2, ?)", (hid,))
        monkeypatch.setattr(us, "load_settings", lambda: {"default_mat_hangar_id": hid})

        refs = im.hangar_references(hid)

        assert "默认材料机库" in refs
        assert "2 条计划的材料机库" in refs
        assert "1 条计划的产出机库" in refs

    def test_repoint_updates_settings_plans_and_solar_system(self, full_db, monkeypatch):
        import services.inventory_manager as im
        import services.user_settings as us

        im.init_db()
        old = im.create_hangar("旧仓")
        new = im.create_hangar("新仓")
        im.update_hangar_system(new, 30000142)
        with full_db.connect("user") as conn:
            conn.execute("INSERT INTO production_plans (id, mat_hangar_id, solar_system_id) VALUES (1, ?, 999)", (old,))
            conn.execute("INSERT INTO production_plans (id, deposit_hangar_id) VALUES (2, ?)", (old,))
        saved: dict = {}
        monkeypatch.setattr(us, "load_settings", lambda: {"default_mat_hangar_id": old})
        monkeypatch.setattr(us, "set_default_hangar_id", lambda k, v: saved.__setitem__(k, v))

        changed = im.repoint_hangar_references(old, new)

        assert saved == {"default_mat_hangar_id": new}
        with full_db.connect("user") as conn:
            # 材料机库改指必须同步星系快照，否则 SCI 与设施加成错配
            row = conn.execute("SELECT mat_hangar_id, solar_system_id FROM production_plans WHERE id=1").fetchone()
            assert (row[0], row[1]) == (new, 30000142)
            assert conn.execute("SELECT deposit_hangar_id FROM production_plans WHERE id=2").fetchone()[0] == new
        assert changed == 3  # 1 个设置键 + 2 条计划

    def test_delete_hangar_with_repoint(self, full_db, monkeypatch):
        import services.inventory_manager as im
        import services.user_settings as us

        im.init_db()
        old = im.create_hangar("旧仓")
        new = im.create_hangar("新仓")
        im.add_item(old, 34, 5)
        with full_db.connect("user") as conn:
            conn.execute("INSERT INTO production_plans (id, mat_hangar_id) VALUES (1, ?)", (old,))
        monkeypatch.setattr(us, "load_settings", lambda: {"default_mat_hangar_id": old})
        monkeypatch.setattr(us, "set_default_hangar_id", lambda k, v: None)

        assert im.delete_hangar(old, repoint_to=new) is True

        assert im.get_hangar_name(old) == ""
        with full_db.connect("user") as conn:
            assert conn.execute("SELECT mat_hangar_id FROM production_plans WHERE id=1").fetchone()[0] == new


@pytest.mark.parametrize(
    ("type_ids", "expected"),
    [
        ([1001], {1001: (True, True)}),  # 库中有 + 有挂单同时命中
        ([1003, 1004], {1003: (False, True), 1004: (False, True)}),  # 买单 / 卖单都算
        ([1002, 9999], {}),  # quantity=0、volume_remain=0、查不到 → 不含
        ([], {}),  # 空输入
    ],
)
def test_stock_and_order_flags(inv_db, type_ids, expected):
    """`get_stock_and_order_flags` 的口径必须与仓库页「状态」列逐字一致。

    库中有 = `inventory_items.quantity > 0`（全部机库合计），有挂单 =
    `open_orders.volume_remain > 0` 且**不筛 `is_buy`**（买单也算）；只含命中项。
    """
    import services.inventory_manager as im

    hid = create_hangar("测试仓")
    with im._default_db().connect("user") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS open_orders (type_id INTEGER, volume_remain INTEGER, is_buy INTEGER)")
        conn.execute(
            "INSERT INTO inventory_items (hangar_id, type_id, quantity) VALUES (?, ?, ?), (?, ?, ?)",
            (hid, 1001, 500, hid, 1002, 0),
        )
        conn.execute("INSERT INTO open_orders VALUES (1001, 10, 1), (1002, 0, 0), (1003, 7, 1), (1004, 3, 0)")

    assert im.get_stock_and_order_flags(type_ids) == expected


def test_production_state_flags(db_manager, monkeypatch):
    """「库存/状态」筛选的标记：无蓝图 / 有原图待拷 / 有拷贝待发明 / 在跑的计划。

    这条同时守三个容易错的点（写实现时都踩过或差点踩到）：
    1. **反应产物**也走 `blueprint_products`（`activity IN ('manufacturing','reaction')`）——
       只认 `manufacturing` 会把它们全判成「无蓝图」；
    2. 科研计划（拷贝/发明/研究）的 `product_type_id` 是**蓝图**，不能被算成「正在制造该物品」；
    3. 待排（`pending`）不算在跑。
    """
    import services.inventory_manager as im

    with db_manager.connect("bp") as conn:
        conn.execute(
            "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER, probability REAL)"
        )
        conn.execute(
            "INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1,NULL),"
            "(3001,'invention',9001,1,0.34),"  # 3001 的拷贝可拿去发明
            "(3002,'reaction',2002,1,NULL),"  # 反应产物：同样要能认出来
            "(3003,'manufacturing',2003,1,NULL),"
            "(3004,'manufacturing',2004,1,NULL)"
        )
        conn.execute("CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time REAL)")
        conn.execute(
            "INSERT INTO blueprint_activities VALUES (3001,'manufacturing',100),"
            "(3002,'reaction',100),(3002,'copying',100),"  # 3002 有拷贝活动 → 原图能拷
            "(3003,'manufacturing',100),(3004,'copying',100)"
        )
    with db_manager.connect("user") as conn:
        conn.execute("CREATE TABLE inventory_items (hangar_id INTEGER, type_id INTEGER, quantity INTEGER)")
        conn.execute("INSERT INTO inventory_items VALUES (1, 2001, 100)")
        conn.execute(
            "CREATE TABLE user_blueprints (id INTEGER PRIMARY KEY AUTOINCREMENT, hangar_id INTEGER, "
            "blueprint_type_id INTEGER, is_bpo INTEGER, me_level INTEGER, te_level INTEGER, "
            "runs INTEGER, quantity INTEGER, notes TEXT)"
        )
        conn.execute(
            "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity) "
            "VALUES (1, 3001, 0, 0, 0, 10, 2),"  # 拷贝 ×2 张、每张 10 流程
            "(1, 3002, 1, 0, 0, 0, 1),"  # 原图（不变量：is_bpo=1 ⇒ runs=0）
            "(1, 3004, 1, 0, 0, 0, 1)"
        )
        conn.execute(
            "CREATE TABLE production_plans (id INTEGER PRIMARY KEY, product_type_id INTEGER, "
            "status TEXT, activity TEXT)"
        )
        conn.execute(
            "INSERT INTO production_plans VALUES (1, 2002, 'in_progress', 'manufacturing'),"
            "(2, 3001, 'in_progress', 'copying'),"  # 科研行：产物是蓝图，不该算「正在制造」
            "(3, 2003, 'pending', 'manufacturing')"  # 待排不算
        )

    monkeypatch.setattr(im, "_default_db", lambda: db_manager)

    got = im.get_production_state_flags([2001, 2002, 2003, 2004, 3001])
    assert got[2001] == frozenset({im.STATE_STOCKED, im.STATE_BPC_INVENTABLE})
    assert got[2002] == frozenset({im.STATE_BPO, im.STATE_IN_PLAN}), "反应产物 + 在跑计划"
    assert got[2003] == frozenset({im.STATE_NO_BLUEPRINT}), "SDE 有蓝图但我们没有；pending 不算在跑"
    assert got[2004] == frozenset({im.STATE_BPO})
    assert im.STATE_IN_PLAN not in got[3001], "拷贝计划不能被算成该物品正在制造"
    assert im.get_production_state_flags([]) == {}
