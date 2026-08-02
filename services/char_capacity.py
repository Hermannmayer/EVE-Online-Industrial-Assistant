"""人物产线容量 — 由角色技能（高级量产技术）决定最大并行产线条数。

一条计划占用 `parallels` 条产线（`runs` 为每条线的流程数，不占额外线）。
最大产线 = 1 + 高级量产技术等级（基础 1 条，每级 +1）。
"""

from __future__ import annotations

from core.container import get_container
from services.char_config_resolver import resolve_char_config
from services.terminology import term

# "高级量产技术"（skill_names 注册；未命中时兜底中文名）
_SKILL_KEY = term.skill_name("Advanced Mass Production") or "高级量产技术"


def max_production_lines(char_name: str | None) -> int:
    """人物最大并行产线条数 = 1 + 高级量产技术等级（默认 0 → 1 条）。"""
    if not char_name:
        return 1
    skills = (resolve_char_config(char_name=char_name) or {}).get("skills", {}) or {}
    level = int(skills.get(_SKILL_KEY, 0) or 0)
    return 1 + max(0, level)


def active_production_lines(char_name: str | None) -> int:
    """人物当前占用产线条数 = SUM(parallels)（仅 in_progress/running）。"""
    if char_name:
        sql = (
            "SELECT COALESCE(SUM(parallels),0) FROM production_plans "
            "WHERE char_name = ? AND status IN ('in_progress','running')"
        )
        params: tuple = (char_name,)
    else:
        sql = (
            "SELECT COALESCE(SUM(parallels),0) FROM production_plans "
            "WHERE (char_name IS NULL OR char_name='') "
            "AND status IN ('in_progress','running')"
        )
        params = ()
    with get_container().db.connect("user") as conn:
        row = conn.execute(sql, params).fetchone()
        return int(row[0] if row else 0)


def active_lines_per_character() -> dict[str, int]:
    """全人物占用 {char_name: active}（未分配归空串）。"""
    result: dict[str, int] = {}
    with get_container().db.connect("user") as conn:
        rows = conn.execute(
            "SELECT COALESCE(char_name,''), COALESCE(SUM(parallels),0) "
            "FROM production_plans WHERE status IN ('in_progress','running') "
            "GROUP BY char_name"
        ).fetchall()
    for name, active in rows:
        result[name] = int(active)
    return result


def character_line_usage(char_name: str | None) -> tuple[int, int]:
    """(active, max) 供产线占用条渲染。"""
    return active_production_lines(char_name), max_production_lines(char_name)
