"""角色配置校验器测试 — 纯逻辑，无 Qt/DB 依赖"""

import json
import os
import tempfile

from services.char_config_validator import (
    DEFAULT_CHAR_CONFIG,
    load_char_config,
    migrate_char_config,
    validate_char_config,
)


def _make_valid_config() -> dict:
    return {
        "current": "main",
        "characters": {
            "main": {
                "skills": {"工业理论": 5, "会计学": 5},
                "market": {"jita": {"faction_standing": 6.7, "corp_standing": 5.0}},
                "implants": [None, None, None],
            }
        },
    }


# ═══════════════════════════════════════════
#  validate_char_config
# ═══════════════════════════════════════════


def test_valid_config():
    """完整角色配置通过验证"""
    result = validate_char_config(_make_valid_config())
    assert result["valid"] is True
    assert result["errors"] == []


def test_missing_skills_warning():
    """缺少 skills 字段产生警告"""
    config = _make_valid_config()
    del config["characters"]["main"]["skills"]
    result = validate_char_config(config)
    assert result["valid"] is True
    warnings = [w for w in result["warnings"] if "缺少字段" in w and "skills" in w]
    assert len(warnings) == 1


def test_invalid_skill_level_warning():
    """技能等级超出 0-5 范围产生警告"""
    config = _make_valid_config()
    config["characters"]["main"]["skills"]["会计学"] = 99
    result = validate_char_config(config)
    assert result["valid"] is True
    warnings = [w for w in result["warnings"] if "等级无效" in w]
    assert len(warnings) == 1
    assert "99" in warnings[0]


def test_missing_top_level_current_error():
    """缺少顶层 current 字段时报错"""
    config = _make_valid_config()
    del config["current"]
    result = validate_char_config(config)
    assert result["valid"] is False
    errors = [e for e in result["errors"] if "current" in e]
    assert len(errors) >= 1


def test_wrong_top_level_type_error():
    """顶层字段类型错误时报错"""
    config = _make_valid_config()
    config["characters"] = "not_a_dict"
    result = validate_char_config(config)
    assert result["valid"] is False
    errors = [e for e in result["errors"] if "characters" in e and "类型错误" in e]
    assert len(errors) >= 1


def test_invalid_standing_range_warning():
    """声望值超出 -10~10 范围产生警告"""
    config = _make_valid_config()
    config["characters"]["main"]["market"]["jita"]["faction_standing"] = 99.9
    result = validate_char_config(config)
    assert result["valid"] is True
    warnings = [w for w in result["warnings"] if "值超出范围" in w]
    assert len(warnings) == 1
    assert "99.9" in warnings[0]


def test_current_char_not_found_warning():
    """current 角色不在 characters 中产生警告"""
    config = _make_valid_config()
    config["current"] = "nonexistent"
    result = validate_char_config(config)
    assert result["valid"] is True
    warnings = [w for w in result["warnings"] if "不存在" in w and "nonexistent" in w]
    assert len(warnings) == 1


def test_implants_too_many_warning():
    """超过 3 个增效体产生警告"""
    config = _make_valid_config()
    config["characters"]["main"]["implants"] = [1, 2, 3, 4]
    result = validate_char_config(config)
    assert result["valid"] is True
    warnings = [w for w in result["warnings"] if "增效体数量超过" in w]
    assert len(warnings) == 1


def test_standing_type_error():
    """声望值类型错误时报错"""
    config = _make_valid_config()
    config["characters"]["main"]["market"]["jita"]["faction_standing"] = "not_a_number"
    result = validate_char_config(config)
    assert result["valid"] is False
    errors = [e for e in result["errors"] if "类型错误" in e]
    assert len(errors) >= 1


def test_validate_non_dict_input():
    """非 dict 输入直接返回错误"""
    result = validate_char_config("not a dict")
    assert result["valid"] is False
    assert len(result["errors"]) > 0


# ═══════════════════════════════════════════
#  migrate_char_config
# ═══════════════════════════════════════════


def test_migrate_adds_missing_fields():
    """迁移函数为缺失的字段补充默认值"""
    result = migrate_char_config({"current": "main", "characters": {"alt": {"skills": {}}}})
    assert "implants" in result["characters"]["alt"]
    assert result["characters"]["alt"]["implants"] == [None, None, None]
    assert "market" in result["characters"]["alt"]
    assert "jita" in result["characters"]["alt"]["market"]
    assert result["characters"]["alt"]["market"]["jita"]["faction_standing"] == 6.7


def test_migrate_preserves_existing_values():
    """迁移函数不覆盖已有用户配置"""
    config = {
        "current": "miner",
        "characters": {
            "miner": {
                "skills": {"采矿技术": 4},
                "implants": [None],
                "market": {"jita": {"faction_standing": 5.0, "corp_standing": 3.0}},
            }
        },
    }
    result = migrate_char_config(config)
    assert result["current"] == "miner"
    assert result["characters"]["miner"]["skills"]["采矿技术"] == 4


def test_migrate_truncates_implants():
    """超过 3 个的增效体被截断"""
    config = {
        "current": "main",
        "characters": {
            "main": {
                "skills": {},
                "implants": [1, 2, 3, 4],
            }
        },
    }
    result = migrate_char_config(config)
    assert len(result["characters"]["main"]["implants"]) == 3


def test_migrate_non_dict_returns_default():
    """非 dict 输入返回默认配置"""
    result = migrate_char_config("not a dict")
    assert result["current"] == DEFAULT_CHAR_CONFIG["current"]
    assert "main" in result["characters"]


# ═══════════════════════════════════════════
#  load_char_config
# ═══════════════════════════════════════════


def test_load_config_file_not_found():
    """配置文件不存在时返回默认配置"""
    result = load_char_config("/nonexistent/path/config.json")
    assert result["current"] == DEFAULT_CHAR_CONFIG["current"]
    assert "main" in result["characters"]


def test_load_config_invalid_json():
    """损坏的 JSON 返回默认配置"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("not valid json{")
        tmp_path = f.name
    try:
        result = load_char_config(tmp_path)
        assert result["current"] == DEFAULT_CHAR_CONFIG["current"]
        assert "main" in result["characters"]
    finally:
        os.unlink(tmp_path)


def test_load_config_migrates_on_load():
    """load 时自动迁移缺失字段"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"current": "main", "characters": {"pilot": {"skills": {}}}}, f)
        tmp_path = f.name
    try:
        result = load_char_config(tmp_path)
        assert "implants" in result["characters"]["pilot"]
        assert "market" in result["characters"]["pilot"]
    finally:
        os.unlink(tmp_path)
