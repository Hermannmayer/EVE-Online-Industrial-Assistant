"""`services.blueprint_reader` 契约测试（05-4）：配方去歧义 + 材料查询。"""

from __future__ import annotations

import sqlite3

import pytest

from domain.formulas import DEFAULT_WASTEFACTOR
from services.blueprint_reader import get_blueprint_materials, get_blueprint_products, get_blueprint_type_for_product

pytestmark = pytest.mark.fast


def _conn() -> sqlite3.Connection:
    """产物 16672 挂测试蓝图 45732（20/轮）+ 真实配方 46207（10000/轮）；26842 只有测试蓝图 26843。"""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE blueprint_products (
            blueprint_type_id INTEGER, activity TEXT, product_type_id INTEGER, quantity INTEGER);
        CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time INTEGER);
        CREATE TABLE blueprint_materials (
            blueprint_type_id INTEGER, activity TEXT, material_type_id INTEGER, quantity INTEGER, wastefactor INTEGER);
        CREATE TABLE item (type_id INTEGER PRIMARY KEY, en_name TEXT, zh_name TEXT);
        INSERT INTO blueprint_products VALUES
            (45732, 'reaction', 16672, 20), (46207, 'reaction', 16672, 10000), (26843, 'manufacturing', 26842, 1);
        INSERT INTO blueprint_activities VALUES
            (45732, 'reaction', 100), (46207, 'reaction', 200), (26843, 'manufacturing', 3600);
        INSERT INTO blueprint_materials VALUES (46207, 'reaction', 34, 100, NULL), (46207, 'reaction', 35, 50, 5);
        INSERT INTO item VALUES
            (45732, 'Test Reaction Blueprint', '测试反应堆蓝图'),
            (46207, 'Tungsten Carbide Reaction Formula', '碳化钨反应配方'),
            (26843, '…TEST Blueprint', '…测试蓝图');
        """
    )
    return conn


def test_test_blueprint_never_beats_real_recipe():
    assert get_blueprint_products(_conn(), 16672, "reaction") == (46207, 10000, 200)


def test_product_with_only_a_test_blueprint_is_still_returned():
    assert get_blueprint_type_for_product(_conn(), 26842) == 26843


def test_materials_default_wastefactor_and_activity_filter():
    conn = _conn()
    assert get_blueprint_materials(conn, 46207, "reaction") == [(34, 100, DEFAULT_WASTEFACTOR), (35, 50, 5)]
    assert get_blueprint_materials(conn, 46207) == []  # 无 manufacturing 材料
