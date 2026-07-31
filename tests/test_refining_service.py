"""测试精炼价值计算 — RefiningService 全链路（含材料表名断言）"""

import pytest

from services.refining_service import RefiningService


class FakeDB:
    """最小 DatabaseManager 替身：connect("ref") 返回内存连接（含 reprocessing_materials）"""

    def __init__(self):
        import sqlite3

        self._conn = sqlite3.connect(":memory:")
        self._conn.execute(
            "CREATE TABLE reprocessing_materials (type_id INTEGER, material_type_id INTEGER, quantity REAL)"
        )
        self._conn.execute("CREATE TABLE item (type_id INTEGER, zh_name TEXT, en_name TEXT, volume REAL)")
        self._conn.executemany(
            "INSERT INTO item (type_id, zh_name, en_name, volume) VALUES (?, ?, ?, ?)",
            [(34, "三钛合金", "Tritanium", 0.01), (1230, "凡晶石", "Veldspar", 0.1)],
        )
        self._conn.commit()

    def connect(self, *_names):
        """返回 sqlite3 连接（与 DatabaseManager.connect 上下文语义一致）"""
        return self._conn


class FakePricing:
    """价格替身：固定返回"""

    def __init__(self, prices: dict[int, float]):
        self._prices = prices

    def get_price(self, type_id: int, *_args, **_kwargs) -> float | None:
        return self._prices.get(type_id)


def _make_service():
    db = FakeDB()
    db._conn.executemany(
        "INSERT INTO reprocessing_materials (type_id, material_type_id, quantity) VALUES (?, ?, ?)",
        [(1230, 34, 100.0)],  # 凡晶石 → 100 单位三钛合金
    )
    db._conn.commit()
    svc = RefiningService(db, pricing_service=FakePricing({34: 5.0, 1230: 100.0}))
    return svc


def test_calc_value_full_chain():
    """全链路：产率 → 查材料 → 计价 → 利润"""
    svc = _make_service()
    result = svc.calc_value(1230, quantity=10, skills={"提炼学概论": 5, "提炼效率理论": 5})

    assert result["output"], "应查询到 reprocessing_materials 材料"
    assert result["output"][0]["type_id"] == 34
    assert result["output"][0]["name"] == "三钛合金"
    assert result["output"][0]["price"] == 5.0

    yield_rate = result["yield_rate"]
    expected_qty = round(100.0 * yield_rate * 10, 2)
    assert result["output"][0]["qty"] == expected_qty

    # 产物总价值 = qty × 5.0；投入价值 = 100 × 10
    assert result["total_value"] == round(expected_qty * 5.0, 2)
    assert result["input_value"] == 1000.0
    assert result["margin_pct"] == round((result["total_value"] - 1000.0) / 1000.0 * 100, 2)


def test_uses_reprocessing_materials_table():
    """必须查询 reprocessing_materials（非 type_materials）— 回归：审计发现查错表导致精炼恒为空"""
    svc = _make_service()  # FakeDB 只有 reprocessing_materials 表，若代码查 type_materials 会抛 OperationalError
    result = svc.calc_value(1230)
    assert result["output"], "reprocessing_materials 中存在材料但返回空"


def test_no_materials_returns_empty():
    """无材料数据 → 空输出 + 全 0"""
    db = FakeDB()  # 未插入 reprocessing_materials 行
    svc = RefiningService(db, pricing_service=FakePricing({34: 5.0, 1230: 100.0}))
    result = svc.calc_value(1230)
    assert result["output"] == []
    assert result["total_value"] == 0
    assert result["profit"] == 0


def test_yield_rate_and_ore_skill():
    """产率 = 基础（无技能 0.5）+ 矿石专精 2%/级（≤0.85）"""
    db = FakeDB()
    svc = RefiningService(db, pricing_service=FakePricing({34: 1.0, 1230: 1.0}))
    result = svc.calc_value(1230, ore_skill=5)
    assert result["yield_rate"] == pytest.approx(min(0.5 + 0.10, 0.85), abs=1e-4)
    assert result["yield_rate"] <= 0.85
