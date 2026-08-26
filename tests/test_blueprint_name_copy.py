"""产线小助手复制蓝图名 — resolve_plan_blueprint_name 纯服务解析。

覆盖：蓝图 id 直取 → 产物反查蓝图 → 不可制造回退产物名 → 空计划。
"""

import sqlite3

from services.database_manager import DB_PATH_MAP
from services.ui_data_service import resolve_plan_blueprint_name


def _seed_blueprint_item_names():
    """在临时 reference.db 补蓝图 type_id 的 item 名称（默认 fixture 库不含蓝图条目）。"""
    conn = sqlite3.connect(DB_PATH_MAP["ref"])
    conn.executescript(
        """
        INSERT INTO item (type_id, zh_name, en_name) VALUES
            (3001, '渡鸦级蓝图', 'Raven Blueprint'),
            (3002, '无人机蓝图', 'Drone Blueprint');
        """
    )
    conn.commit()
    conn.close()


class TestResolvePlanBlueprintName:
    def test_direct_blueprint_type_id(self, temp_db):
        """计划已有 blueprint_type_id → 返回蓝图的 item 名。"""
        _seed_blueprint_item_names()
        plan = {"blueprint_type_id": 3002, "product_type_id": 2002, "product_name": "无人机"}
        assert resolve_plan_blueprint_name(plan, db=temp_db) == "无人机蓝图"

    def test_reverse_map_when_bpid_missing(self, temp_db):
        """blueprint_type_id 缺失（未绑定 BPC）但产物可制造 → 反查蓝图名。"""
        _seed_blueprint_item_names()
        plan = {"blueprint_type_id": None, "product_type_id": 2001, "product_name": "渡鸦级"}
        assert resolve_plan_blueprint_name(plan, db=temp_db) == "渡鸦级蓝图"

    def test_non_manufacturable_falls_back_to_product(self, temp_db):
        """产物无制造蓝图（如矿物）→ 回退产物名（保留旧行为，不复制产物名当蓝图名以外场景）。"""
        plan = {"product_type_id": 1001, "product_name": "三钛合金"}
        assert resolve_plan_blueprint_name(plan, db=temp_db) == "三钛合金"

    def test_empty_plan(self, temp_db):
        assert resolve_plan_blueprint_name({}, db=temp_db) == ""
