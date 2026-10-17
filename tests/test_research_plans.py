"""services/research_plans 纯函数回归（05-3 指出该文件此前测试零引用）。

只测不碰容器/真实库的部分：发明来源反查与 SDE 基础流程数。
"""

from __future__ import annotations

import sqlite3

from services.research_plans import invention_base_runs, resolve_invention_source


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE blueprint_products (
            blueprint_type_id INTEGER, activity TEXT, product_type_id INTEGER,
            probability REAL, quantity INTEGER
        );
        CREATE TABLE blueprint_activities (
            blueprint_type_id INTEGER, activity TEXT, time INTEGER, max_production_limit INTEGER
        );
        CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT);
        -- T1 蓝图 821 发明出 T2 蓝图 2890（基础流程 10，成功率 0.34）
        INSERT INTO blueprint_products VALUES (821, 'invention', 2890, 0.34, 10);
        INSERT INTO blueprint_products VALUES (821, 'invention', 2891, 0.30, 10);
        INSERT INTO blueprint_activities VALUES (821, 'invention', 63900, 30);
        INSERT INTO blueprint_activities VALUES (821, 'copying', 4800, 200);
        INSERT INTO item VALUES (821, '200mm自动加农炮蓝图 I', '200mm AutoCannon Blueprint I');
        INSERT INTO item VALUES (2890, '200mm自动加农炮蓝图 II', '200mm AutoCannon Blueprint II');
        INSERT INTO item VALUES (2891, '另一张 T2 蓝图', 'Another T2 Blueprint');
        """
    )
    return conn


def test_invention_base_runs_reads_sde_quantity():
    """基础流程数取 SDE `blueprint_products.quantity`（不是 min(拷贝上限, 制造上限)）。"""
    assert invention_base_runs(_conn(), 2890, 821) == 10


def test_invention_base_runs_falls_back_to_ten_when_missing():
    assert invention_base_runs(_conn(), 999999, 821) == 10


def test_resolve_invention_source_returns_t1_and_all_outcomes():
    src = resolve_invention_source(_conn(), 2890)
    assert src is not None
    assert src["t1_blueprint_type_id"] == 821
    assert src["t1_name"] == "200mm自动加农炮蓝图 I"
    assert src["t1_copy_limit"] == 200
    # 同一 T1 蓝图的全部产物都要列出来（多产物路径）
    assert [o["blueprint_type_id"] for o in src["outcomes"]] == [2890, 2891]
    assert src["outcomes"][0]["base_probability"] == 0.34


def test_resolve_invention_source_none_for_non_invention_product():
    assert resolve_invention_source(_conn(), 821) is None
