"""技能名防漂移测试 — 角色设置页 / terminology 注册表里的名字必须能在 SDE 命中。

背景：技能名就是 `char_config.json` 的键，`char_capacity` / `scoring` / 发明成功率
全按中文名读。名字失效 → 静默读成 0 级，界面看不出任何异常。
历史上 43 个 UI 技能名里有 17 个是 2014 改名前的老名（实测）。

本测试是回归网：新增技能名后必须同步 SDE 与 terminology 注册表。
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from services.char_config_validator import _LEGACY_SKILL_KEYS

_REPO = Path(__file__).resolve().parent.parent


def _skill_categories() -> list[tuple[str, list[str]]]:
    """从 char_settings_common 读出 SKILL_CATEGORIES（不 import，避免拉起 Qt）。"""
    src = (_REPO / "ui_pyside6" / "views" / "char_settings_common.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "SKILL_CATEGORIES":
            return [(name, list(skills)) for name, _icon, skills in ast.literal_eval(node.value)]
    raise AssertionError("SKILL_CATEGORIES 未找到")


@pytest.fixture
def ref_conn():
    """用真实 reference.db（含 SDE 技能表）只读连接；不可用则跳过。"""
    from core.paths import REF_DB_PATH

    if not Path(REF_DB_PATH).exists():
        pytest.skip("reference.db 不存在")
    conn = sqlite3.connect(f"file:{Path(REF_DB_PATH).as_posix()}?mode=ro", uri=True)
    try:
        try:
            has_data = bool(conn.execute("SELECT 1 FROM item WHERE group_id = 270 LIMIT 1").fetchone())
        except sqlite3.OperationalError:
            has_data = False
        if not has_data:
            pytest.skip("测试库无 SDE 技能数据（reference.db 未初始化）")
        yield conn
    finally:
        conn.close()


def _resolves(conn, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM item WHERE zh_name = ? OR en_name = ? LIMIT 1", (name, name)).fetchone())


class TestUiSkillNames:
    def test_every_ui_skill_name_exists_in_sde(self, ref_conn):
        """角色设置页的每个技能名都要能在 SDE 找到（否则等级读成 0）。"""
        missing: list[str] = []
        for _category, skills in _skill_categories():
            for name in skills:
                if not _resolves(ref_conn, name):
                    missing.append(name)
        assert not missing, (
            f"以下技能名在 SDE 中不存在（改名了或已移除），会导致等级静默读成 0：{missing}；"
            f"若是改名，请同时更新 services/char_config_validator._LEGACY_SKILL_KEYS"
        )

    def test_legacy_rename_source_is_gone(self, ref_conn):
        """_LEGACY_SKILL_KEYS 的**旧名**必须是已失效的名字。"""
        still_valid = [old for old in _LEGACY_SKILL_KEYS if _resolves(ref_conn, old)]
        assert not still_valid, f"这些旧名在 SDE 里仍然有效，不该列为历史名：{still_valid}"

    def test_legacy_rename_target_exists(self, ref_conn):
        """_LEGACY_SKILL_KEYS 的**新名**必须有效（否则搬过去也读不到）。"""
        broken = [new for new in _LEGACY_SKILL_KEYS.values() if not _resolves(ref_conn, new)]
        assert not broken, f"这些新名在 SDE 中不存在：{broken}"


class TestTerminologyRegistry:
    def test_registered_chinese_names_resolve(self, ref_conn):
        """terminology.json 里登记的中文名必须能在 SDE 找到。"""
        import json

        path = _REPO / "data" / "terminology.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        names = {v for v in (data.get("skill_names") or {}).values() if v}
        assert names, "skill_names 不应为空"
        broken = [n for n in names if not _resolves(ref_conn, n)]
        assert not broken, f"terminology.skill_names 中这些中文名在 SDE 找不到：{broken}"


class TestLegacyKeyMigration:
    def test_migrate_moves_level_to_current_name(self):
        """旧名有等级、新名缺失 → 等级搬到新名（旧键保留，不删用户数据）。"""
        from services.char_config_validator import _migrate_legacy_skill_keys

        skills = {"电子技术": 5}
        _migrate_legacy_skill_keys(skills)
        assert skills["电子工程学"] == 5
        assert skills["电子技术"] == 5, "旧键保留（契约：不删除用户已有配置项）"

    def test_migrate_does_not_clobber_existing_new_value(self):
        from services.char_config_validator import _migrate_legacy_skill_keys

        skills = {"机械工程": 2, "机械工程学": 5}
        _migrate_legacy_skill_keys(skills)
        assert skills["机械工程学"] == 5, "新名已有值时不覆盖"

    def test_migrate_is_idempotent(self):
        from services.char_config_validator import _migrate_legacy_skill_keys

        skills = {"量子物理": 3}
        _migrate_legacy_skill_keys(skills)
        _migrate_legacy_skill_keys(skills)
        assert skills["量子物理学"] == 3

    def test_migrate_noop_without_legacy_keys(self):
        from services.char_config_validator import _migrate_legacy_skill_keys

        skills = {"工业理论": 5}
        _migrate_legacy_skill_keys(skills)
        assert skills == {"工业理论": 5}
