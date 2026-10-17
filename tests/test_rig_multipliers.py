"""结构改件成本属性（01-13 剩余）与「蓝图类别 → rig」映射的回归测试。

覆盖两件事（判定表：数据解析边界 1 条 + 纯映射 1 条参数化）：
1. `services/importers/getrigdata.py` 的成本属性解析（ESI `attributeEngRigCostBonus=2595`）
   与旧缓存库兼容：旧 `structure_rigs` 无 `cost_bonus` 列时，`init_db` 补列、
   `resolve_rig_cost_multiplier` 返回 1.0（零漂移）；补列拉取后成本倍率生效。
2. `domain/rigs.py` 的 SDE category/group → rig 类别映射（含 XL 宽口径覆盖），
   映射不到的类别必须返回 None（不猜、不加成）。
"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager

import pytest

from domain.rigs import rig_category_applies, rig_category_for_product
from services import hangar_industry_config as hic
from services.importers import getrigdata


class _FakeDb:
    """最小 DatabaseManager 替身：`connect()` 返回同一个 sqlite 连接的上下文。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def connect(self, *aliases: str):
        @contextmanager
        def _cm():
            yield self._conn

        return _cm()


class _FakeClient:
    def __init__(self, payloads: dict[int, dict | None]) -> None:
        self._payloads = payloads

    async def fetch(self, url: str):
        type_id = int(url.split("/universe/types/")[1].split("/")[0])
        return self._payloads.get(type_id)


def _attrs(**kwargs: float) -> dict:
    return {"dogma_attributes": [{"attribute_id": int(k), "value": v} for k, v in kwargs.items()]}


def test_rig_cost_attr_parsing_and_old_cache_degradation(tmp_path):
    # ── 1) ESI 解析：有 2595 取成本；没有该属性 = 真实 0；请求失败 = None ──
    client = _FakeClient(
        {
            43884: _attrs(**{"2594": 0, "2593": 0, "2595": -12}),
            37154: _attrs(**{"2594": -2, "2593": 0}),
            99999: None,
        }
    )
    cost_rig = asyncio.run(getrigdata.fetch_rig_bonuses(client, 43884))
    mat_rig = asyncio.run(getrigdata.fetch_rig_bonuses(client, 37154))
    failed = asyncio.run(getrigdata.fetch_rig_bonuses(client, 99999))
    assert cost_rig == {"type_id": 43884, "mat_bonus": 0.0, "time_bonus": 0.0, "cost_bonus": -12.0}
    assert mat_rig is not None and mat_rig["cost_bonus"] == 0.0  # 无该属性 ≠ 未拉取
    assert failed is None

    # ── 2) 旧缓存库（没 cost_bonus 列）：init_db 补列；补列后旧行为零漂移 ──
    db_path = tmp_path / "reference.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE structure_rigs (
            type_id INTEGER PRIMARY KEY,
            mat_bonus REAL DEFAULT 0.0,
            time_bonus REAL DEFAULT 0.0,
            fetch_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE item (type_id INTEGER PRIMARY KEY, group_id INTEGER, category_id INTEGER);
        CREATE TABLE hangars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            facility_type TEXT DEFAULT NULL,
            facility_tax REAL DEFAULT NULL,
            rigs TEXT DEFAULT NULL
        );
        INSERT INTO structure_rigs (type_id, mat_bonus, time_bonus) VALUES (43920, -2.0, -20.0);
        INSERT INTO hangars (id, name, facility_type, facility_tax, rigs)
        VALUES (1, '制造仓', 'raitaru', 0.5, '[43920]');
        """
    )
    conn.commit()
    getrigdata.init_db(str(db_path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(structure_rigs)")}
    assert "cost_bonus" in cols
    assert (
        conn.execute("SELECT cost_bonus FROM structure_rigs WHERE type_id=43920").fetchone()[0] is None
    )  # NULL=待重拉

    fake_db = _FakeDb(conn)
    assert hic.resolve_rig_multipliers([43920], _db=fake_db) == (0.98, 0.8)  # 原有 mat/time 不变
    assert hic.resolve_rig_cost_multiplier([43920], _db=fake_db) == 1.0  # 缺失列 → 成本零漂移

    # ── 3) 补列拉取后：成本 -12% → 0.88，且只对匹配类别的改件生效 ──
    conn.execute("UPDATE structure_rigs SET cost_bonus = -12.0 WHERE type_id = 43920")
    conn.execute(
        "INSERT INTO item (type_id, group_id, category_id) VALUES (43920, 1816, 66)"  # 组 1816 equipment
    )
    conn.commit()
    assert hic.resolve_rig_cost_multiplier([43920], activity="manufacturing", _db=fake_db) == 0.88
    # 科研活动不该吃到 manufacturing 类别改件的加成（类别不匹配）
    assert hic.resolve_rig_cost_multiplier([43920], activity="invention", _db=fake_db) == 1.0

    # ── 3b) 生产入口按蓝图产物类别细分改件（01-13 剩余缺口）──
    conn.executescript(
        """
        INSERT INTO item (type_id, group_id, category_id) VALUES (587, 25, 6);      -- 裂谷级（舰船）
        INSERT INTO item (type_id, group_id, category_id) VALUES (22542, 546, 7);   -- 采矿激光器提升器（装备）
        """
    )
    conn.commit()
    # 舰船产品：equipment 类改件不适用 → 只有结构本体基数
    ship_cfg = hic.resolve_hangar_industry_config(1, activity="manufacturing", product_type_id=587, _db=fake_db)
    assert ship_cfg["structure_mat_saving"] == 0.99
    # 装备产品：equipment 类改件适用 → 0.99 × 0.98
    module_cfg = hic.resolve_hangar_industry_config(1, activity="manufacturing", product_type_id=22542, _db=fake_db)
    assert module_cfg["structure_mat_saving"] == pytest.approx(0.99 * 0.98, abs=1e-6)
    # 不给产物（旧调用方）：退回旧行为（不按类别筛，改件全算）
    legacy_cfg = hic.resolve_hangar_industry_config(1, activity="manufacturing", _db=fake_db)
    assert legacy_cfg["structure_mat_saving"] == pytest.approx(0.99 * 0.98, abs=1e-6)

    # ── 4) XL 实验室优化改件（组 1870 laboratory）：发明/拷贝/ME/TE 都该吃到时间+成本 ──
    conn.execute(
        "INSERT INTO structure_rigs (type_id, mat_bonus, time_bonus, cost_bonus) VALUES (37182, 0.0, -20.0, -10.0)"
    )
    conn.execute("INSERT INTO item (type_id, group_id) VALUES (37182, 1870)")
    conn.commit()
    assert hic.resolve_rig_cost_multiplier([37182], activity="invention", _db=fake_db) == 0.9
    assert hic.resolve_rig_multipliers([37182], activity="copying", _db=fake_db) == (1.0, 0.8)
    assert hic.resolve_rig_cost_multiplier([37182], activity="manufacturing", _db=fake_db) == 1.0


@pytest.mark.parametrize(
    ("category_id", "group_id", "expected", "broad_rigs"),
    [
        (6, 25, "basic_small_ship", ("ship",)),  # Frigate
        (6, 324, "advanced_small_ship", ("ship",)),  # Assault Frigate
        (6, 485, "capital_ship", ("ship",)),  # Dreadnought
        (6, 963, "advanced_medium_ship", ("ship",)),  # Strategic Cruiser
        (6, 1972, None, ()),  # Flag Cruiser：tech 口径不确定 → 不猜
        (7, 587, "equipment", ("equipment_consumable",)),
        (8, 648, "ammunition", ("equipment_consumable",)),
        (18, 100, "drone_fighter", ()),
        (17, 873, "basic_capital_component", ("structure_component",)),
        (17, 913, "advanced_component", ("structure_component",)),
        (17, 334, None, ()),  # T1 Construction Components：rig 描述未提及
        (65, 1657, "structure", ("structure_component",)),
        (32, 954, "advanced_medium", ()),  # Subsystem
        (4, 1136, "structure", ("structure_component",)),  # Fuel Block
        (4, 18, None, ()),  # Mineral（非 rig 覆盖的材料产物）
    ],
)
def test_rig_category_for_product(category_id, group_id, expected, broad_rigs):
    got = rig_category_for_product(category_id=category_id, group_id=group_id)
    assert got == expected
    if expected:
        assert rig_category_applies(expected, expected) is True
        for rig in broad_rigs:
            assert rig_category_applies(rig, expected) is True, f"{rig} 应覆盖 {expected}"
        # 非宽口径/非同类 rig 不得误匹配
        assert rig_category_applies("equipment", expected) is (expected == "equipment")
    else:
        assert rig_category_applies("equipment", None) is False
