"""角色配置文件校验和迁移"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
#  默认配置
# ═══════════════════════════════════════════

DEFAULT_CHAR_CONFIG: dict[str, Any] = {
    "current": "main",
    "characters": {
        "main": {
            "skills": {
                "工业理论": 5,
                "高级工业理论": 5,
                "工业配置学": 5,
                "高级工业配置学": 5,
                "批量生产技术": 5,
                "经纪人关系学": 5,
                "高级经纪人关系学": 5,
                "会计学": 5,
                "科学原理": 5,
                "Mass Production": 5,
                "Advanced Mass Production": 5,
            },
            "market": {
                "jita": {"faction_standing": 6.7, "corp_standing": 5.0},
                "amarr": {"faction_standing": 3.0, "corp_standing": 3.0},
                "dodixie": {"faction_standing": 3.0, "corp_standing": 3.0},
                "rens": {"faction_standing": 3.0, "corp_standing": 3.0},
            },
            "implants": [None, None, None],
        }
    },
}

# 期望的顶层字段和类型
TOP_LEVEL_SCHEMA = {
    "current": str,
    "characters": dict,
}

# 角色数据的期望字段和类型
CHARACTER_SCHEMA = {
    "skills": dict,
    "implants": list,
    "market": dict,
}

# 市场数据的期望字段
MARKET_HUBS = ["jita", "amarr", "dodixie", "rens"]

# 声望值范围
STANDING_MIN = -10.0
STANDING_MAX = 10.0

# 技能等级范围
SKILL_LEVEL_MIN = 0
SKILL_LEVEL_MAX = 5


def validate_char_config(data: dict) -> dict:
    """
    校验角色配置的结构和类型是否正确。

    返回:
        {"valid": bool, "errors": [str], "warnings": [str]}
    """
    errors = []
    warnings = []

    # 检查 data 是否为字典
    if not isinstance(data, dict):
        return {"valid": False, "errors": ["配置文件格式错误：应为 JSON 对象"], "warnings": []}

    # 检查顶层字段类型
    for field, expected_type in TOP_LEVEL_SCHEMA.items():
        if field not in data:
            errors.append(f"缺少顶层字段: {field}")
        elif not isinstance(data[field], expected_type):
            errors.append(f"字段 '{field}' 类型错误：期望 {expected_type.__name__}，实际 {type(data[field]).__name__}")

    # 检查 current 字段
    if "current" in data and isinstance(data["current"], str):
        if "characters" in data and isinstance(data["characters"], dict):
            if data["current"] not in data["characters"]:
                warnings.append(f"当前角色 '{data['current']}' 不存在于 characters 中")
    elif "current" in data and not isinstance(data["current"], str):
        pass  # 已在上面的类型检查中报告

    # 检查 characters 字段
    if "characters" in data and isinstance(data["characters"], dict):
        for char_name, char_data in data["characters"].items():
            if not isinstance(char_data, dict):
                errors.append(f"角色 '{char_name}' 数据格式错误：应为 JSON 对象")
                continue

            # 检查角色数据的期望字段
            for field, expected_type in CHARACTER_SCHEMA.items():
                if field not in char_data:
                    warnings.append(f"角色 '{char_name}' 缺少字段: {field}，将使用默认值")
                elif not isinstance(char_data[field], expected_type):
                    errors.append(f"角色 '{char_name}' 的 '{field}' 类型错误：期望 {expected_type.__name__}")

            # 检查技能值范围
            if "skills" in char_data and isinstance(char_data["skills"], dict):
                for skill_name, level in char_data["skills"].items():
                    if not isinstance(level, int) or not (SKILL_LEVEL_MIN <= level <= SKILL_LEVEL_MAX):
                        warnings.append(
                            f"角色 '{char_name}' 技能 '{skill_name}' 等级无效：{level}，"
                            f"有效范围 {SKILL_LEVEL_MIN}-{SKILL_LEVEL_MAX}"
                        )

            # 检查市场数据
            if "market" in char_data and isinstance(char_data["market"], dict):
                for hub in MARKET_HUBS:
                    if hub in char_data["market"]:
                        hub_data = char_data["market"][hub]
                        if not isinstance(hub_data, dict):
                            errors.append(f"角色 '{char_name}' 交易中心 '{hub}' 数据格式错误")
                            continue

                        # 检查声望值范围
                        for standing_key in ["faction_standing", "corp_standing"]:
                            if standing_key in hub_data:
                                val = hub_data[standing_key]
                                if not isinstance(val, int | float):
                                    errors.append(f"角色 '{char_name}' {hub}.{standing_key} 类型错误：期望数字")
                                elif not (STANDING_MIN <= val <= STANDING_MAX):
                                    warnings.append(
                                        f"角色 '{char_name}' {hub}.{standing_key} 值超出范围：{val}，"
                                        f"有效范围 {STANDING_MIN}-{STANDING_MAX}"
                                    )

            # 检查增效体列表
            if "implants" in char_data and isinstance(char_data["implants"], list):
                if len(char_data["implants"]) > 3:
                    warnings.append(f"角色 '{char_name}' 增效体数量超过 3 个，将截断")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def migrate_char_config(data: dict) -> dict:
    """
    迁移旧配置到新格式。添加缺失的默认字段。

    此操作是幂等的：多次运行同一结果。
    不会删除用户已有的配置项。
    """
    if not isinstance(data, dict):
        logger.warning("配置数据格式错误，返回默认配置")
        return dict(DEFAULT_CHAR_CONFIG)

    result = dict(data)

    # 确保顶层字段存在
    if "current" not in result:
        result["current"] = DEFAULT_CHAR_CONFIG["current"]

    if "characters" not in result:
        result["characters"] = DEFAULT_CHAR_CONFIG["characters"].copy()
    elif not isinstance(result["characters"], dict):
        result["characters"] = DEFAULT_CHAR_CONFIG["characters"].copy()

    # 迁移每个角色的数据
    for _char_name, char_data in result["characters"].items():
        if not isinstance(char_data, dict):
            continue

        # 确保 skills 字段存在
        if "skills" not in char_data:
            char_data["skills"] = {}
        elif not isinstance(char_data["skills"], dict):
            char_data["skills"] = {}

        # 确保 implants 字段存在
        if "implants" not in char_data:
            char_data["implants"] = [None, None, None]
        elif not isinstance(char_data["implants"], list):
            char_data["implants"] = [None, None, None]
        elif len(char_data["implants"]) > 3:
            # 截断到最多 3 个
            char_data["implants"] = char_data["implants"][:3]

        # 确保 market 字段存在
        if "market" not in char_data:
            char_data["market"] = {}
        elif not isinstance(char_data["market"], dict):
            char_data["market"] = {}

        # 确保所有交易中心存在并有正确的子字段
        default_market = DEFAULT_CHAR_CONFIG["characters"]["main"]["market"]  # type: ignore[index]
        for hub in MARKET_HUBS:
            if hub not in char_data["market"]:
                char_data["market"][hub] = dict(default_market[hub])
            elif not isinstance(char_data["market"][hub], dict):
                char_data["market"][hub] = dict(default_market[hub])
            else:
                # 确保子字段存在
                hub_data = char_data["market"][hub]
                for key in ["faction_standing", "corp_standing"]:
                    if key not in hub_data:
                        hub_data[key] = default_market[hub][key]
                    elif not isinstance(hub_data[key], int | float):
                        hub_data[key] = default_market[hub][key]

    return result


def load_char_config(path: str) -> dict:
    """
    读取、校验、迁移一站式函数。

    如果 JSON 损坏，返回默认配置并在日志中记录。
    如果格式有问题，尝试迁移修复。
    """
    if not os.path.exists(path):
        logger.info("配置文件不存在: %s，使用默认配置", path)
        return dict(DEFAULT_CHAR_CONFIG)

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error("配置文件 JSON 解析失败: %s, 错误: %s", path, e)
        return dict(DEFAULT_CHAR_CONFIG)
    except Exception as e:
        logger.error("读取配置文件失败: %s, 错误: %s", path, e)
        return dict(DEFAULT_CHAR_CONFIG)

    # 校验配置
    validation = validate_char_config(data)
    if validation["errors"]:
        for error in validation["errors"]:
            logger.warning("配置校验错误: %s", error)
    if validation["warnings"]:
        for warning in validation["warnings"]:
            logger.info("配置校验警告: %s", warning)

    # 迁移配置
    migrated = migrate_char_config(data)

    return migrated
