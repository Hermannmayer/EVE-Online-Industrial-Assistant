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
