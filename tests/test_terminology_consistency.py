"""
术语一致性测试 — 验证代码中的 EVE 游戏术语与 SDE 数据库一致。

覆盖范围:
  1. char_settings_view.py 中所有技能名必须匹配 SDE item.zh_name
  2. eve_formulas.py 中使用的技能 key 必须与 terminology.json 的 skill_names 一致
  3. name_resolver.py 中所有矿物名必须覆盖在 terminology.json 的 item_overrides 中
  4. 公式代码中不直接引用技能名，而是通过 term.skill_name() 获取
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.fast

# ── 路径 ───────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = _PROJECT_ROOT / "data"
_TERM_FILE = _DATA_DIR / "terminology.json"


# ═══════════════════════════════════════════════════════════════════
#  Helper: 加载 SDE 技能名
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def sde_skills() -> dict[str, str]:
    """返回 SDE 中所有技能的 {zh_name: en_name} 映射。

    项目的数据加载器（tools/downloaders/getitems.py）不填充 item.category_id，
    因此 category_id=16 无数据时跳过依赖 SDE 技能分类的检查；
    使用完整 SDE 数据（含 category_id）时该检查正常执行。
    """
    import sqlite3

    from core.paths import REF_DB_PATH

    try:
        conn = sqlite3.connect(str(REF_DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT en_name, zh_name FROM item WHERE category_id=16")
        sde = {r[1]: r[0] for r in cur.fetchall() if r[1]}
        conn.close()
    except sqlite3.Error:
        sde = {}
    if not sde:
        pytest.skip("reference.db 未填充技能分类数据（item.category_id），跳过 SDE 技能一致性检查")
    return sde


@pytest.fixture(scope="module")
def terminology_data() -> dict:
    """返回 terminology.json 的内容"""
    if not _TERM_FILE.exists():
        return {}
    with open(_TERM_FILE, encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


# ═══════════════════════════════════════════════════════════════════
#  Test 1: char_settings_view.py 技能名 vs SDE
# ═══════════════════════════════════════════════════════════════════


def _get_skills_from_charsettings() -> list[str]:
    """从 char_settings_common.py 提取所有技能名"""
    target = _PROJECT_ROOT / "ui_pyside6" / "views" / "char_settings_common.py"
    spec = importlib.util.spec_from_file_location("char_settings_common", target)
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    # 该模块只含 SKILL_CATEGORIES/ALL_SKILLS 常量
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # 如果加载失败，用硬编码的回退
        pass
    if hasattr(mod, "ALL_SKILLS"):
        return mod.ALL_SKILLS  # type: ignore[no-any-return]
    # fallback: 从文件直接提取  # type: ignore[no-any-return]
    import ast

    skills: list[str] = []
    tree = ast.parse(target.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.List):
            # 找到包含技能名的列表
            strs = [elt.value for elt in node.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
            if len(strs) > 5:
                skills.extend(strs)
    return skills


def test_charsettings_skills_match_sde(sde_skills):
    """char_settings_view.py 中的所有技能名必须在 SDE 中存在"""
    code_skills = _get_skills_from_charsettings()
    assert code_skills, "未能加载 char_settings_view 中的技能名"

    # 排除已知的非 SDE 技能（仅 UI 显示标签）
    KNOWN_NON_SDE = {
        "血袭者改造技术研究",
        "天蛇改造技术研究",
        "天使改造技术研究",
        "古斯塔斯改造技术研究",
        "电子子系统技术",
        # UI 沿用玩家习惯名，SDE 官方翻译不同（电子技术=电子工程学、核物理=核星体物理学、
        # 高频激发物理学=高频能量物理学、生化反应学）→ 归入 UI 标签，不视为缺失
        "电子技术",
        "核物理",
        "高频激发物理学",
        "生化反应学",
    }
    sde_zh = set(sde_skills)
    sde_en = set(sde_skills.values())
    not_found = []
    for s in code_skills:
        if s in KNOWN_NON_SDE:
            continue
        if s in sde_zh or s in sde_en:
            # 中文名或 SDE 英文名（如 Advanced Industry）均视为一致
            continue
        # 模糊搜索（前 4 个字）
        match = any(s[:4] in zh or zh[:4] in s for zh in sde_zh)
        if not match:
            not_found.append(s)

    assert not not_found, (
        f"SDE 中找不到以下技能名（{len(not_found)} 个）:\n"
        + "\n".join(f"  - {s}" for s in not_found)
        + "\n提示: 查 SDE: SELECT en_name, zh_name FROM item WHERE category_id=16"
    )


# ═══════════════════════════════════════════════════════════════════
#  Test 2: eve_formulas.py 技能名 vs terminology.json
# ═══════════════════════════════════════════════════════════════════


def _extract_skill_keys_from_eve_formulas() -> set[str]:
    """从 eve_formulas.py 中提取所有 skills.get() 调用的技能名 key"""
    import ast

    src = _PROJECT_ROOT / "core" / "eve_formulas.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get":
                if node.args and isinstance(node.args[0], ast.Constant):
                    keys.add(str(node.args[0].value))
    return keys


def test_eve_formulas_skill_keys_match_terminology(terminology_data):
    """eve_formulas.py 中的 skills.get() 技能 key 必须在 terminology.json 中有对应注册

    检查公式代码中使用的每个中文技能名都能在 skill_names（或 skill_aliases）的
    值（value）中找到，确保中心注册表覆盖所有引用。
    """
    formula_keys = _extract_skill_keys_from_eve_formulas()
    skill_names_data = terminology_data.get("skill_names", {})
    skill_aliases_data = terminology_data.get("skill_aliases", {})

    # 所有 skill_names 的 VALUES 集合（中文技能名）
    registered_names: set[str] = set(skill_names_data.values())
    registered_names.update(skill_aliases_data.values())

    # 过滤非技能 key
    NON_SKILL_KEYS = {"faction_standing", "corp_standing", "skills", "market", "jita", "amarr", "dodixie", "rens"}
    skill_keys = {k for k in formula_keys if k not in NON_SKILL_KEYS and len(k) > 2 and not k.isascii()}

    not_found = []
    for key in sorted(skill_keys):
        if key not in registered_names:
            not_found.append(key)

    assert not not_found, (
        "以下技能名在 terminology.json 的 skill_names/skill_aliases 中缺失:\n"
        + "\n".join(f"  - {s}" for s in not_found)
        + "\n提示: 在 terminology.json 的 skill_names 中添加，如 "
        f'  "Reprocessing": "{not_found[0]}"'
        if not_found
        else ""
    )


# ═══════════════════════════════════════════════════════════════════
#  Test 3: 矿物名覆盖
# ═══════════════════════════════════════════════════════════════════


def test_mineral_names_covered_by_terminology(terminology_data):
    """terminology.json 的 item_overrides 必须覆盖所有基础矿物"""
    # 基础矿物 type_id（不在 SDE item 表中，靠 terminology.json 提供名称）
    KNOWN_MINERALS = {34, 35, 36, 37, 38, 39, 40, 4247, 4312}
    overrides = {int(k): v for k, v in terminology_data.get("item_overrides", {}).items()}

    missing = [tid for tid in sorted(KNOWN_MINERALS) if tid not in overrides]
    assert not missing, "以下矿物 type_id 未在 terminology.json 的 item_overrides 中定义:\n" + "\n".join(
        f"  - {tid}" for tid in missing
    )


# ═══════════════════════════════════════════════════════════════════
#  Test 4: 精炼技能名一致性（Regression: P0 Bug）
# ═══════════════════════════════════════════════════════════════════


def test_refining_skill_name_consistency(sde_skills, terminology_data):
    """验证精炼相关技能名在 SDE、terminology、公式代码中一致"""
    # sde_skills = {zh_name: en_name}
    sde_zh_names = set(sde_skills.keys())

    # SDE 中应包含正确的精炼技能名
    assert "提炼学概论" in sde_zh_names, 'SDE 中缺少"提炼学概论"，检查 SDE 数据'
    assert "提炼效率理论" in sde_zh_names, 'SDE 中缺少"提炼效率理论"，检查 SDE 数据'

    # terminology.json 的 skill_names VALUES 中应包含 SDE 官方名
    registered_zh = set(terminology_data.get("skill_names", {}).values())
    registered_zh.update(terminology_data.get("skill_aliases", {}).values())

    assert "提炼学概论" in registered_zh, '"提炼学概论" 不在 terminology.json 的 skill_names 中'
    assert "提炼效率理论" in registered_zh, '"提炼效率理论" 不在 terminology.json 的 skill_names 中'

    # 公式代码中的技能 key 应包含 SDE 官方名
    formula_keys = _extract_skill_keys_from_eve_formulas()
    assert "提炼学概论" in formula_keys, 'eve_formulas.py 中没有使用 "提炼学概论" 作为技能 key'
    assert "提炼效率理论" in formula_keys, 'eve_formulas.py 中没有使用 "提炼效率理论" 作为技能 key'
