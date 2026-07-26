"""
角色配置统一解析 — 四种来源合并，消除对 UI 层的反依赖。

来源优先级：skills 参数 > char_data 参数 > char_name → char_config.json → 默认技能
"""

from __future__ import annotations

from collections.abc import Callable

DEFAULT_SKILLS = {"工业理论": 5, "高级工业理论": 5}


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
                pass
        # 最终 fallback
        return {"skills": dict(DEFAULT_SKILLS), "market": {}}


# 默认实例（由 AppContainer 注册时注入 UI 层的回调）
_default_resolver: CharConfigResolver | None = None


def get_default_resolver() -> CharConfigResolver:
    global _default_resolver
    if _default_resolver is None:
        _default_resolver = CharConfigResolver()
    return _default_resolver


def resolve_char_config(
    char_name: str | None = None,
    char_data: dict | None = None,
    skills: dict | None = None,
) -> dict:
    """模块级便利函数（向后兼容），使用默认解析器"""
    return get_default_resolver().resolve(char_name=char_name, char_data=char_data, skills=skills)
