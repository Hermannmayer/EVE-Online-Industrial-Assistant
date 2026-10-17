"""护栏：`core/skill_keys.py` 的中文技能名必须在 `data/terminology.json` 注册。

背景（06-6 术语铁律）：`domain/` 不能 import `services/`，但制造/科研/贸易/精炼公式
都要按**中文技能名**从 `char_config.json` 的 `skills` 字典取值。于是取值键集中到
`core/skill_keys.py`；术语的唯一来源仍是 `services.terminology`（数据 = terminology.json）。

两处一旦脱钩就会静默取到 0 级：新增/改名技能常量、却忘了在 terminology.json 的
`skill_names` 注册。本测试把两处钉在一起（新增常量记得同时更新 `ALL_SKILL_KEYS`）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from core.skill_keys import ALL_SKILL_KEYS
from services.terminology import term

TERMINOLOGY_PATH = Path(__file__).resolve().parents[1] / "data" / "terminology.json"


def _skill_names() -> dict[str, str]:
    """terminology.json 的 skill_names：英文名 → 中文名。"""
    data = json.loads(TERMINOLOGY_PATH.read_text(encoding="utf-8"))
    return cast("dict[str, str]", data["skill_names"])


def test_skill_keys_are_non_empty_and_unique():
    assert ALL_SKILL_KEYS, "core/skill_keys.py 的 ALL_SKILL_KEYS 不应为空"
    assert all(key.strip() for key in ALL_SKILL_KEYS), "技能键不应为空串"
    assert len(set(ALL_SKILL_KEYS)) == len(ALL_SKILL_KEYS), "技能键不应重复"


def test_every_skill_key_registered_in_terminology_json():
    registered = set(_skill_names().values())
    missing = [key for key in ALL_SKILL_KEYS if key not in registered]
    assert not missing, f"以下技能键未在 data/terminology.json 的 skill_names 注册：{missing}"


def test_terminology_service_returns_same_chinese_name():
    """按英文名反查中文名必须与常量值一致 —— UI/查询层走的就是这个映射。"""
    english_by_chinese = {zh: en for en, zh in _skill_names().items()}
    for key in ALL_SKILL_KEYS:
        assert term.skill_name(english_by_chinese[key]) == key, f"术语服务反查不一致：{key}"
