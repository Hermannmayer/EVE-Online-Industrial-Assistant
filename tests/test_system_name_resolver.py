"""星系名解析测试 — name_resolver.resolve_system_name / terminology 星系中文名。

覆盖:
  - terminology.system_name / search_system_names（星系中文名查表 + 中文反查）
  - terminology.rig_category（改件类别标准术语：me_research→材料效率研究）
  - name_resolver.resolve_system_name / resolve_system_names_batch（中英对照显示）
"""

from services import name_resolver
from services.terminology import term


def _add_solar_systems(db_manager):
    """在 reference.db 建 solar_system 表并插入测试星系（Jita 有中文 + Maire 无中文）。"""
    with db_manager.connect("ref") as conn:
        conn.execute(
            "CREATE TABLE solar_system (solar_system_id INTEGER PRIMARY KEY, solar_system_name TEXT, security REAL)"
        )
        conn.execute(
            "INSERT INTO solar_system (solar_system_id, solar_system_name, security) VALUES (?, ?, ?)",
            (30000142, "Jita", 0.9),
        )
        conn.execute(
            "INSERT INTO solar_system (solar_system_id, solar_system_name, security) VALUES (?, ?, ?)",
            (30000143, "Maire", 0.6),
        )
    return db_manager


class TestTerminologySystemName:
    def test_known_system(self):
        assert term.system_name("Jita") == "吉他"

    def test_unknown_returns_none(self):
        assert term.system_name("Maire") is None

    def test_search_by_zh(self):
        assert "Jita" in term.search_system_names("吉他")

    def test_search_no_match(self):
        assert term.search_system_names("不存在星系XYZ") == []


class TestTerminologyRigCategory:
    def test_me_research_standard_term(self):
        """科研改件类别使用标准术语，而非 ME/TE 简称"""
        assert term.rig_category("me_research") == "材料效率研究"

    def test_te_research_standard_term(self):
        assert term.rig_category("te_research") == "生产效率研究"

    def test_invention_term(self):
        assert term.rig_category("invention") == "发明"

    def test_unknown_returns_none(self):
        assert term.rig_category("nope") is None


class TestResolveSystemName:
    def test_zh_en_pair(self, db_manager):
        """有中英对照 → 「中文 (英文)」"""
        _add_solar_systems(db_manager)
        with db_manager.connect("ref") as conn:
            assert name_resolver.resolve_system_name(conn, 30000142) == "吉他 (Jita)"

    def test_en_only_fallback(self, db_manager):
        """未注册中文 → 回退英文名"""
        _add_solar_systems(db_manager)
        with db_manager.connect("ref") as conn:
            assert name_resolver.resolve_system_name(conn, 30000143) == "Maire"

    def test_unknown_id_fallback(self, db_manager):
        """表中无此星系 → 回退字符串 id（不再出现纯编号显示问题）"""
        _add_solar_systems(db_manager)
        with db_manager.connect("ref") as conn:
            assert name_resolver.resolve_system_name(conn, 99999999) == "99999999"


class TestResolveSystemNamesBatch:
    def test_batch_zh_en(self, db_manager):
        _add_solar_systems(db_manager)
        with db_manager.connect("ref") as conn:
            result = name_resolver.resolve_system_names_batch(conn, [30000142, 30000143])
        assert result == {30000142: "吉他 (Jita)", 30000143: "Maire"}

    def test_empty(self, db_manager):
        with db_manager.connect("ref") as conn:
            assert name_resolver.resolve_system_names_batch(conn, []) == {}
