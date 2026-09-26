"""人物产线容量 — 由角色技能（高级量产技术）决定最大并行产线条数。

一条计划占用 `parallels` 条产线（`runs` 为每条线的流程数，不占额外线）。
最大产线 = 1 + 高级量产技术等级（基础 1 条，每级 +1）。

新：三类产线容量（制造/科研/反应），每类由两个技能叠加：
  制造 = 1 + 高级量产技术 + 批量生产学
  科研 = 1 + 实验室运作理论 + 高级实验室运作理论
  反应 = 1 + 大规模反应理论 + 高级大规模反应理论
满级（技能各 5）→ 1+5+5 = 11 条。
计划按 `category`（services.plan_category 推导）归类到三类线型。
"""

from __future__ import annotations

from core.container import get_container
from services.char_config_resolver import get_character_list, load_all_data, resolve_char_config
from services.terminology import term

# 三类产线常量
CAPACITY_LINE_MANUFACTURING = "manufacturing"
CAPACITY_LINE_RESEARCH = "research"
CAPACITY_LINE_REACTION = "reaction"

#: 三类线型的**展示顺序**（制造 / 科研 / 反应）—— 占用面板逐行按它排
LINE_TYPES: tuple[str, ...] = (CAPACITY_LINE_MANUFACTURING, CAPACITY_LINE_RESEARCH, CAPACITY_LINE_REACTION)

#: 「正在生产」—— 产线小助手 / 查询页仪表盘的口径：只有真在跑的计划占线
RUNNING_STATUSES: tuple[str, ...] = ("in_progress", "running")
#: 「已规划」—— 工业页「人物占用情况」的口径：还在排产（待生产）的计划也先把线占上，
#: 外加待下线的（成品没下线之前那条线也腾不出来）。「已完成 / 已下线」不占。
PLANNED_STATUSES: tuple[str, ...] = ("pending", "in_progress", "running", "ready")

_LINE_LABELS = {
    CAPACITY_LINE_MANUFACTURING: "制造",
    CAPACITY_LINE_RESEARCH: "科研",
    CAPACITY_LINE_REACTION: "反应",
}

# 线型 → 容量技能（中文名，与 char_config.json 的 skills key 一致）
_CATEGORY_SKILLS: dict[str, tuple[str, str]] = {
    CAPACITY_LINE_MANUFACTURING: ("高级量产技术", "批量生产学"),
    CAPACITY_LINE_RESEARCH: ("实验室运作理论", "高级实验室运作理论"),
    CAPACITY_LINE_REACTION: ("大规模反应理论", "高级大规模反应理论"),
}

# 计划 category（plan_category）→ 线型：拷贝/发明/ME-TE 研究都占科研线
_RESEARCH_CATEGORIES = {"copying", "invention", "research"}


def capacity_line_for_category(category: str) -> str:
    """计划 category → 容量线型（copying/invention→research，未知→manufacturing）。"""
    if category in _RESEARCH_CATEGORIES:
        return CAPACITY_LINE_RESEARCH
    if category == "reaction":
        return CAPACITY_LINE_REACTION
    return CAPACITY_LINE_MANUFACTURING


def line_label(line: str) -> str:
    """线型 → 中文标签（占用区展示）。"""
    return _LINE_LABELS.get(line, line)


def _sum_skill_levels(skills: dict, names: tuple[str, ...]) -> int:
    """纯函数：多个技能等级之和（缺省 0）。"""
    total = 0
    for name in names:
        try:
            total += int(skills.get(name, 0) or 0)
        except (TypeError, ValueError):
            pass
    return max(total, 0)


def max_lines_for_category(char_name: str | None, line: str, *, skills: dict | None = None) -> int:
    """某线型最大产线条数 = 1 + Σ(该线型技能等级)。满级（两技能各 5）= 11。

    skills 注入时纯逻辑；否则经 resolve_char_config 读取（char_name 为空 → 默认无该类技能 → 1）。
    """
    names = _CATEGORY_SKILLS.get(line, ())
    if skills is None:
        cfg = resolve_char_config(char_name=char_name) or {}
        skills = cfg.get("skills", {}) or {}
    return 1 + _sum_skill_levels(skills, names)


def active_lines_by_category(
    plans: list[dict], *, statuses: tuple[str, ...] = RUNNING_STATUSES
) -> dict[str, dict[str, int]]:
    """从已 enrich category 的活跃计划行聚合 {char_name(''=未分配): {线型: SUM(parallels)}}。

    `statuses` 决定「哪些计划算占着线」—— 两个口径，别混：
    `RUNNING_STATUSES`（默认，产线小助手 / 仪表盘）只算正在跑的，
    `PLANNED_STATUSES`（工业页「人物占用情况」）把待生产的也算上。
    纯函数（无 DB）。
    """
    result: dict[str, dict[str, int]] = {}
    for p in plans:
        if (p.get("status") or "").lower() not in statuses:
            continue
        char = (p.get("char_name") or "").strip() or ""
        line = capacity_line_for_category(str(p.get("category") or ""))
        bucket = result.setdefault(char, {})
        bucket[line] = bucket.get(line, 0) + max(int(p.get("parallels") or 0), 0)
    return result


def char_line_usage(
    plans: list[dict], *, statuses: tuple[str, ...] = RUNNING_STATUSES
) -> tuple[list[tuple[str, dict[str, tuple[int, int]]]], dict[str, int]]:
    """[(角色名, {线型: (已占, 上限)})]，外加各线型「所有人上限里的最大值」。

    角色顺序 = `char_config.json` 里登记的**全部**角色（没排产的人也留一行、条子归零），
    再补「有计划但没登记进配置」的角色 —— 否则那些人的占用会凭空消失。
    上限由技能算（`max_lines_for_category`）。

    第二个返回值是**统一分母**：某线型下各人物上限的最大值。占用面板用它把所有人的
    条子画得一样长，才比得出谁快满了（早先取的是各人之和，单人跑满自己的线只点亮半条）。
    """
    usage = active_lines_by_category(plans, statuses=statuses)
    chars_data = (load_all_data() or {}).get("characters", {}) or {}
    chars = list(get_character_list())
    for char in usage:
        if char and char not in chars:
            chars.append(char)

    per_char: list[tuple[str, dict[str, tuple[int, int]]]] = []
    line_caps: dict[str, int] = dict.fromkeys(LINE_TYPES, 0)
    for char in chars:
        skills = (chars_data.get(char, {}) or {}).get("skills", {}) or {}
        char_usage = usage.get(char or "", {})
        per_line: dict[str, tuple[int, int]] = {}
        for line in LINE_TYPES:
            maximum = max_lines_for_category(char, line, skills=skills)
            per_line[line] = (int(char_usage.get(line, 0)), maximum)
            line_caps[line] = max(line_caps[line], maximum)
        per_char.append((char, per_line))
    return per_char, line_caps


def _skill_key() -> str:
    """ "高级量产技术"（skill_names 注册；未命中时兜底中文名）。惰性求值，避免 import 时加载术语表。"""
    return term.skill_name("Advanced Mass Production") or "高级量产技术"


def max_production_lines(char_name: str | None) -> int:
    """人物最大并行产线条数 = 1 + 高级量产技术等级（默认 0 → 1 条）。"""
    if not char_name:
        return 1
    skills = (resolve_char_config(char_name=char_name) or {}).get("skills", {}) or {}
    level = int(skills.get(_skill_key(), 0) or 0)
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
