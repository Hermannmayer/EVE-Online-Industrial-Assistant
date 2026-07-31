"""
角色配置统一解析 — 四种来源合并，消除对 UI 层的反依赖。

来源优先级：skills 参数 > char_data 参数 > char_name → char_config.json → 默认技能

本模块同时提供 char_config.json 的读写入口（原 ui_pyside6.views.char_settings_view
中的薄封装），使 services 层可直接使用，不再反向 import UI 层。
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable

from core.paths import data_dir
from services.char_config_validator import load_char_config

logger = logging.getLogger(__name__)

DEFAULT_SKILLS = {"工业理论": 5, "高级工业理论": 5}


def char_config_path() -> str:
    """char_config.json 文件路径"""
    return os.path.join(data_dir(), "char_config.json")


def load_all_data() -> dict:
    """加载完整角色配置"""
    return load_char_config(char_config_path())


def save_all_data(data: dict) -> None:
    """保存完整角色配置"""
    path = char_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_character(name: str) -> dict | None:
    """获取指定角色的完整配置"""
    data = load_all_data()
    return data.get("characters", {}).get(name)  # type: ignore[no-any-return]


def get_character_list() -> list[str]:
    """获取所有角色名列表"""
    data = load_all_data()
    return list(data.get("characters", {}).keys())


class CharConfigResolver:
    """角色配置解析器 — 注入回调避免反依赖 UI 层"""

    def __init__(self, char_data_provider: Callable[[str], dict | None] | None = None):
        self._char_data_provider = char_data_provider

    def resolve(
        self,
        char_name: str | None = None,
        char_data: dict | None = None,
        skills: dict | None = None,
    ) -> dict:
        """返回保证包含 'skills' 和 'market' 键的配置 dict"""
        if skills is not None:
            return {"skills": dict(skills), "market": {}}
        if char_data is not None and char_data:
            return dict(char_data) if isinstance(char_data, dict) else {"skills": {}, "market": {}}
        if char_name is not None and self._char_data_provider is not None:
            try:
                result = self._char_data_provider(char_name)
                if result:
                    return dict(result)
            except Exception:
                logger.exception("角色配置解析失败: %s", char_name)
        # 最终 fallback
        return {"skills": dict(DEFAULT_SKILLS), "market": {}}


# 默认实例（由 AppContainer 注册时注入回调）
_default_resolver: CharConfigResolver | None = None


def get_default_resolver() -> CharConfigResolver:
    global _default_resolver
    if _default_resolver is None:
        _default_resolver = CharConfigResolver(char_data_provider=get_character)
    return _default_resolver


def resolve_char_config(
    char_name: str | None = None,
    char_data: dict | None = None,
    skills: dict | None = None,
) -> dict:
    """模块级便利函数（向后兼容），使用默认解析器"""
    return get_default_resolver().resolve(char_name=char_name, char_data=char_data, skills=skills)
