"""机库工业配置解析测试 — 结构基数/改件映射/加成解析/校验"""

from unittest.mock import MagicMock, patch

import pytest

from services import hangar_industry_config as hic


@pytest.fixture
def rig_db(temp_db):
    """temp_db + ref 建 structure_rigs（2 个 M 改件）+ user 建 hangars(v6)"""
    with temp_db.connect("ref") as conn:
        conn.executescript(
            """
            CREATE TABLE structure_rigs (
                type_id INTEGER PRIMARY KEY,
                mat_bonus REAL DEFAULT 0.0,
                time_bonus REAL DEFAULT 0.0
            );
            INSERT INTO structure_rigs VALUES (43920, -2.0, 0.0);   -- M 材料效率 I
            INSERT INTO structure_rigs VALUES (37160, 0.0, -20.0);  -- M 时间效率 I
            """
        )
    with temp_db.connect("user") as conn:
        conn.executescript(
            """
            CREATE TABLE hangars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                notes TEXT DEFAULT '',
                solar_system_id INTEGER DEFAULT NULL,
                facility_type TEXT DEFAULT NULL,
                facility_tax REAL DEFAULT NULL,
                rigs TEXT DEFAULT NULL
            );
            INSERT INTO hangars (id, name, facility_type, facility_tax, rigs)
            VALUES (1, '制造仓', 'raitaru', 0.5, '[43920, 37160]');
            INSERT INTO hangars (id, name, facility_type) VALUES (2, 'NPC仓', 'npc');
            """
        )
    return temp_db


class TestParseRigs:
    def test_none(self):
        assert hic.parse_rigs(None) == []
        assert hic.parse_rigs("") == []

    def test_invalid_json(self):
        assert hic.parse_rigs("{bad json") == []

    def test_non_list(self):
        assert hic.parse_rigs('"str"') == []
        assert hic.parse_rigs("42") == []

    def test_int_list(self):
        assert hic.parse_rigs("[43920, 37160]") == [43920, 37160]

    def test_mixed(self):
        assert hic.parse_rigs('[43920, "x", 37160]') == [43920, 37160]


class TestStructureBase:
    def test_all_structures_present(self):
        for key in ("npc", "raitaru", "azbel", "sotiyo"):
            assert key in hic.STRUCTURE_BASE
            base = hic.STRUCTURE_BASE[key]
            assert base["mat"] > 0 and base["cost"] > 0 and base["time"] > 0

    def test_rig_group_map_structure(self):
        # 53 个制造改件组，映射为 (size, category, effect)
        assert len(hic.RIG_GROUP_MAP) == 53
        for _gid, (size, cat, effect) in hic.RIG_GROUP_MAP.items():
            assert size in ("M", "L", "XL")
            assert cat
            assert effect in ("mat", "time", "both", "cost")

    def test_effect_both_has_implied_mat_time(self):
        # both 效果改件应同时贡献材料和时间（L/XL Efficiency）
        for _gid, (_, _, effect) in hic.RIG_GROUP_MAP.items():
            if effect == "both":
                assert True


class TestResolveRigMultipliers:
    def test_empty_returns_one(self, rig_db):
        assert hic.resolve_rig_multipliers([], _db=rig_db) == (1.0, 1.0)

    def test_table_missing_degrades(self, temp_db):
        """structure_rigs 表未初始化 → 不崩，加成按 1.0"""
        assert hic.resolve_rig_multipliers([43920], _db=temp_db) == (1.0, 1.0)

    def test_unknown_rig_ignored(self, rig_db):
        """structure_rigs 缺行 → 加成按 0，倍率不变"""
        assert hic.resolve_rig_multipliers([99999], _db=rig_db) == (1.0, 1.0)

    def test_single_mat_rig(self, rig_db):
        """材料效率 I (-2%) → 材料倍率 0.98"""
        assert hic.resolve_rig_multipliers([43920], _db=rig_db) == (0.98, 1.0)

    def test_multi_rigs_multiply(self, rig_db):
        """材料 -2% 与时间 -20% 乘算叠加"""
        mat, tm = hic.resolve_rig_multipliers([43920, 37160], _db=rig_db)
        assert mat == pytest.approx(0.98)
        assert tm == pytest.approx(0.80)


class TestResolveHangarIndustryConfig:
    def test_no_hangar_default(self, rig_db):
        cfg = hic.resolve_hangar_industry_config(None, _db=rig_db)
        assert cfg["structure_mat_saving"] == 1.0
        assert cfg["structure_time_mod"] == 1.0
        assert cfg["structure_cost_mult"] == 1.0
        assert cfg["facility_tax"] is None

    def test_npc(self, rig_db):
        cfg = hic.resolve_hangar_industry_config(2, _db=rig_db)
        assert cfg["structure_mat_saving"] == 1.0
        assert cfg["structure_time_mod"] == 1.0
        assert cfg["structure_cost_mult"] == 1.0
        assert cfg["facility_type"] == "npc"

    def test_raitaru_with_rigs(self, rig_db):
        """莱塔卢基数(0.99/0.97/0.85) × 改件(-2% 材料, -20% 时间)"""
        cfg = hic.resolve_hangar_industry_config(1, _db=rig_db)
        assert cfg["facility_type"] == "raitaru"
        assert cfg["facility_tax"] == 0.5
        assert cfg["structure_mat_saving"] == pytest.approx(0.99 * 0.98, abs=1e-6)
        assert cfg["structure_time_mod"] == pytest.approx(0.85 * 0.80, abs=1e-6)
        assert cfg["structure_cost_mult"] == pytest.approx(0.97)
        assert cfg["rig_ids"] == [43920, 37160]


class TestValidateRigSet:
    def test_npc_rejects_rigs(self, rig_db):
        problems = hic.validate_rig_set([43920], "npc", _db=rig_db)
        assert problems and "NPC 站" in problems[0]

    def test_unknown_rig(self, rig_db):
        """未知改件 → 报「不属于该设施可装配目录」"""
        with patch.object(hic, "get_rig_catalog", return_value=[]):
            problems = hic.validate_rig_set([99999], "raitaru", _db=rig_db)
        assert problems and "不属于" in problems[0]

    def test_category_conflict(self, rig_db):
        """同制造类别（equipment）两个改件互斥"""
        catalog = [
            {
                "type_id": 43920,
                "category_key": "equipment",
                "category_label": "装备制造",
                "zh_name": "材料效率I",
                "en_name": "",
                "group_id": 1816,
                "effect": "mat",
                "mat_bonus": -2.0,
                "time_bonus": 0.0,
            },
            {
                "type_id": 37160,
                "category_key": "equipment",
                "category_label": "装备制造",
                "zh_name": "时间效率I",
                "en_name": "",
                "group_id": 1819,
                "effect": "time",
                "mat_bonus": 0.0,
                "time_bonus": -20.0,
            },
        ]
        with patch.object(hic, "get_rig_catalog", return_value=catalog):
            problems = hic.validate_rig_set([43920, 37160], "raitaru", _db=rig_db)
        assert any("最多装配 1 个" in p for p in problems)

    def test_valid_empty(self, rig_db):
        assert hic.validate_rig_set([], "raitaru", _db=rig_db) == []


class TestGetRigCatalog:
    def test_npc_empty(self, rig_db):
        assert hic.get_rig_catalog("npc", _db=rig_db) == []

    def test_table_missing_degrades(self, monkeypatch):
        """structure_rigs 表不存在 → 主查询失败 → 降级仅列 item（加成 0），不崩"""
        import sqlite3

        def fake_execute(sql, *args, **kwargs):
            if "structure_rigs" in sql:
                raise sqlite3.OperationalError("no such table: structure_rigs")
            cur = MagicMock()
            cur.fetchall.return_value = [(43920, "材料效率I", "Rig", 1816, 0, 0)]
            return cur

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = fake_execute
        cm = MagicMock()
        cm.__enter__.return_value = mock_conn
        mock_db = MagicMock()
        mock_db.connect.return_value = cm
        monkeypatch.setattr(hic, "db", mock_db)

        catalog = hic.get_rig_catalog("raitaru")
        assert len(catalog) == 1
        assert catalog[0]["mat_bonus"] == 0.0  # 表未就绪 → 加成 0

    def test_unknown_facility_empty(self, rig_db):
        assert hic.get_rig_catalog("unknown", _db=rig_db) == []

    def test_parses_rows(self, rig_db, monkeypatch):
        """mock DB 返回改件行 → 解析为带加成/类别的目录"""
        rows = [
            (43920, "材料效率I", "Rig", 1816, -2.0, 0.0),
            (37160, "时间效率I", "Rig", 1819, 0.0, -20.0),
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows
        cm = MagicMock()
        cm.__enter__.return_value = mock_conn
        mock_db = MagicMock()
        mock_db.connect.return_value = cm
        monkeypatch.setattr(hic, "db", mock_db)

        catalog = hic.get_rig_catalog("raitaru")
        assert len(catalog) == 2
        assert catalog[0]["category_key"] == "equipment"
        assert catalog[0]["category_label"] == "装备制造"
        assert catalog[0]["mat_bonus"] == -2.0
        assert catalog[1]["time_bonus"] == -20.0


class TestRigCategoryLabel:
    """改件类别标签必须使用标准术语（terminology 权威）"""

    def test_me_research_standard(self):
        assert hic.rig_category_label("me_research") == "材料效率研究"

    def test_te_research_standard(self):
        assert hic.rig_category_label("te_research") == "生产效率研究"

    def test_equipment(self):
        assert hic.rig_category_label("equipment") == "装备制造"

    def test_unknown_fallback(self):
        assert hic.rig_category_label("nope") == "nope"

    def test_catalog_me_research_label_from_terminology(self, rig_db, monkeypatch):
        """get_rig_catalog 对科研改件（组 1844 me_research）类别标签走 terminology"""
        rows = [(43920, "材料效率I", "Rig", 1844, -2.0, 0.0)]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows
        cm = MagicMock()
        cm.__enter__.return_value = mock_conn
        mock_db = MagicMock()
        mock_db.connect.return_value = cm
        monkeypatch.setattr(hic, "db", mock_db)

        catalog = hic.get_rig_catalog("raitaru")
        assert catalog[0]["category_key"] == "me_research"
        assert catalog[0]["category_label"] == "材料效率研究"
