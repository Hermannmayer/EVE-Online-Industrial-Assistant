"""人物产线容量测试 — services/char_capacity.py"""

from types import SimpleNamespace

import services.char_capacity as cc


def _patch_container(db_manager, monkeypatch):
    monkeypatch.setattr(cc, "get_container", lambda: SimpleNamespace(db=db_manager))


def _init_plans(db_manager):
    with db_manager.connect("user") as conn:
        conn.execute(
            "CREATE TABLE production_plans (id INTEGER PRIMARY KEY, parallels INTEGER DEFAULT 1, "
            "char_name TEXT, status TEXT)"
        )
        for pid, par, char, status in [
            (1, 3, "人物A", "in_progress"),
            (2, 2, "人物A", "running"),
            (3, 1, "人物A", "pending"),
            (4, 5, "人物B", "in_progress"),
            (5, 4, None, "in_progress"),
            (6, 2, None, "completed"),
        ]:
            conn.execute(
                "INSERT INTO production_plans (id, parallels, char_name, status) VALUES (?,?,?,?)",
                (pid, par, char, status),
            )


class TestMaxProductionLines:
    def test_no_character(self):
        assert cc.max_production_lines(None) == 1

    def test_skill_level(self, monkeypatch):
        monkeypatch.setattr(cc, "resolve_char_config", lambda char_name=None: {"skills": {"高级量产技术": 4}})
        assert cc.max_production_lines("人物A") == 5

    def test_no_skill_in_config(self, monkeypatch):
        monkeypatch.setattr(cc, "resolve_char_config", lambda char_name=None: {"skills": {"工业理论": 5}})
        assert cc.max_production_lines("人物A") == 1

    def test_empty_character_name(self, monkeypatch):
        monkeypatch.setattr(cc, "resolve_char_config", lambda char_name=None: {"skills": {"高级量产技术": 3}})
        assert cc.max_production_lines("") == 1  # 空名按未分配


class TestActiveProductionLines:
    def test_sums_parallels_and_filters(self, db_manager, monkeypatch):
        _patch_container(db_manager, monkeypatch)
        _init_plans(db_manager)
        assert cc.active_production_lines("人物A") == 5  # 3+2，pending 不计
        assert cc.active_production_lines("人物B") == 5
        assert cc.active_production_lines("不存在") == 0

    def test_none_char_unassigned(self, db_manager, monkeypatch):
        _patch_container(db_manager, monkeypatch)
        _init_plans(db_manager)
        assert cc.active_production_lines(None) == 4  # id=5 in_progress；id=6 completed 不计

    def test_active_lines_per_character(self, db_manager, monkeypatch):
        _patch_container(db_manager, monkeypatch)
        _init_plans(db_manager)
        usage = cc.active_lines_per_character()
        assert usage["人物A"] == 5
        assert usage["人物B"] == 5
        assert usage[""] == 4

    def test_character_line_usage(self, db_manager, monkeypatch):
        _patch_container(db_manager, monkeypatch)
        _init_plans(db_manager)
        monkeypatch.setattr(cc, "resolve_char_config", lambda char_name=None: {"skills": {"高级量产技术": 3}})
        assert cc.character_line_usage("人物A") == (5, 4)


# ════════════════════════════════════════════════════════════════
#  三类产线容量（制造/科研/反应）
# ════════════════════════════════════════════════════════════════


class TestMaxLinesForCategory:
    def test_full_level_eleven(self):
        skills = {"高级量产技术": 5, "批量生产学": 5}
        assert cc.max_lines_for_category("X", cc.CAPACITY_LINE_MANUFACTURING, skills=skills) == 11

    def test_research_two_skills(self):
        skills = {"高级实验室运作理论": 5, "科学网络学": 5}
        assert cc.max_lines_for_category("X", cc.CAPACITY_LINE_RESEARCH, skills=skills) == 11

    def test_reaction_two_skills(self):
        skills = {"大规模反应理论": 5, "高级大规模反应理论": 5}
        assert cc.max_lines_for_category("X", cc.CAPACITY_LINE_REACTION, skills=skills) == 11

    def test_partial_levels(self):
        skills = {"高级量产技术": 3, "批量生产学": 2}
        assert cc.max_lines_for_category("X", cc.CAPACITY_LINE_MANUFACTURING, skills=skills) == 6

    def test_no_skills_base_one(self):
        assert cc.max_lines_for_category("X", cc.CAPACITY_LINE_MANUFACTURING, skills={}) == 1

    def test_missing_skill_zero(self):
        skills = {"高级量产技术": 5}
        assert cc.max_lines_for_category("X", cc.CAPACITY_LINE_MANUFACTURING, skills=skills) == 6

    def test_resolves_config_when_no_skills(self, monkeypatch):
        monkeypatch.setattr(
            cc,
            "resolve_char_config",
            lambda char_name=None: {"skills": {"高级实验室运作理论": 5, "科学网络学": 5}},
        )
        assert cc.max_lines_for_category("X", cc.CAPACITY_LINE_RESEARCH) == 11

    def test_empty_char_defaults(self, monkeypatch):
        monkeypatch.setattr(cc, "resolve_char_config", lambda char_name=None: {"skills": {}})
        assert cc.max_lines_for_category("", cc.CAPACITY_LINE_MANUFACTURING) == 1


class TestCapacityLineForCategory:
    def test_mapping(self):
        assert cc.capacity_line_for_category("manufacturing") == cc.CAPACITY_LINE_MANUFACTURING
        assert cc.capacity_line_for_category("copying") == cc.CAPACITY_LINE_RESEARCH
        assert cc.capacity_line_for_category("invention") == cc.CAPACITY_LINE_RESEARCH
        assert cc.capacity_line_for_category("reaction") == cc.CAPACITY_LINE_REACTION
        assert cc.capacity_line_for_category("unknown") == cc.CAPACITY_LINE_MANUFACTURING
        assert cc.capacity_line_for_category("") == cc.CAPACITY_LINE_MANUFACTURING


class TestActiveLinesByCategory:
    def test_aggregates_by_char_and_line(self):
        plans = [
            {"char_name": "A", "category": "manufacturing", "parallels": 3, "status": "in_progress"},
            {"char_name": "A", "category": "reaction", "parallels": 2, "status": "running"},
            {"char_name": "", "category": "copying", "parallels": 4, "status": "in_progress"},
            {"char_name": "A", "category": "manufacturing", "parallels": 9, "status": "pending"},
            {"char_name": "A", "category": "manufacturing", "parallels": 1, "status": "completed"},
        ]
        usage = cc.active_lines_by_category(plans)
        assert usage["A"] == {"manufacturing": 3, "reaction": 2}
        assert usage[""] == {"research": 4}

    def test_empty_plans(self):
        assert cc.active_lines_by_category([]) == {}

    def test_pending_excluded(self):
        plans = [{"char_name": "A", "category": "manufacturing", "parallels": 5, "status": "pending"}]
        assert cc.active_lines_by_category(plans) == {}

    def test_null_char_grouped_as_empty(self):
        plans = [{"char_name": None, "category": "reaction", "parallels": 2, "status": "in_progress"}]
        assert cc.active_lines_by_category(plans) == {"": {"reaction": 2}}


class TestLineLabel:
    def test_labels(self):
        assert cc.line_label(cc.CAPACITY_LINE_MANUFACTURING) == "制造"
        assert cc.line_label(cc.CAPACITY_LINE_RESEARCH) == "科研"
        assert cc.line_label(cc.CAPACITY_LINE_REACTION) == "反应"
        assert cc.line_label("bogus") == "bogus"
