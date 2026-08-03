"""
统一术语服务 — 加载 terminology.yaml 提供游戏术语查询。

职责:
  1. 蓝图活动名 (activity) 中文化
  2. 物品名/分组名覆盖 (SDE 翻译不对时手动修正)
  3. UI 标签统一
  4. 技能/属性别名

用法:
  from services.terminology import term

  term.activity("manufacturing")        # → "制造"
  term.translate("材料", "ui_labels")    # → "材料" (自身)
  term.resolve_name(34)                  # → "三钛合金" (若在 item_overrides 中)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

_DATA_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "data"
_TERM_FILE = _DATA_DIR / "terminology.json"


class Terminology:
    """单例术语表，线程安全（只读加载后不变）。"""

    def __init__(self) -> None:
        self._data: dict = {}
        self._loaded = False

    def _ensure(self) -> None:
        if self._loaded:
            return
        if _TERM_FILE.exists():
            with open(_TERM_FILE, encoding="utf-8") as f:
                self._data = json.load(f)
        else:
            self._data = {}
        self._loaded = True

    # ── 蓝图活动名 ──

    def activity(self, key: str) -> str:
        """蓝图活动名英译中，未知 key 返回原文。"""
        self._ensure()
        return cast(str, self._data.get("activities", {}).get(key, key))

    # ── 物品名覆盖 ──

    def item_override(self, type_id: int) -> str | None:
        self._ensure()
        overrides = self._data.get("item_overrides") or {}
        return overrides.get(str(type_id))

    # ── 分组名覆盖 ──

    def group_override(self, group_id: int) -> str | None:
        self._ensure()
        overrides = self._data.get("group_overrides") or {}
        return overrides.get(str(group_id))

    # ── UI 标签 ──

    def label(self, key: str) -> str:
        """UI 标签翻译。"""
        self._ensure()
        return cast(str, self._data.get("ui_labels", {}).get(key, key))

    # ── 市场分类 ──

    def market_category(self, key: str) -> str:
        self._ensure()
        return cast(str, self._data.get("market_categories", {}).get(key, key))

    # ── 技能别名 ──

    def skill_alias(self, en_name: str) -> str | None:
        self._ensure()
        return cast(str | None, self._data.get("skill_aliases", {}).get(en_name))

    # ── 技能名（正式注册表） ──

    def skill_name(self, en_name: str) -> str | None:
        """获取技能官方中文名。

        优先查 skill_names 注册表，fallback 到 skill_aliases，再 fallback 到原文。
        """
        self._ensure()
        names = self._data.get("skill_names", {})
        if en_name in names:
            return cast(str, names[en_name])
        # fallback: skill_aliases 兼容旧引用
        aliases = self._data.get("skill_aliases", {})
        return cast(str | None, aliases.get(en_name))

    # ── 星系中文名（常用星系对照表） ──

    def system_name(self, en_name: str) -> str | None:
        """星系中文名（按英文名查表）。未知返回 None，显示层回退英文名。

        对照表仅内置常用星系（见 terminology.json system_names），其余回退英文。
        """
        self._ensure()
        return cast(str | None, self._data.get("system_names", {}).get(en_name))

    def search_system_names(self, keyword: str) -> list[str]:
        """按中文名关键词反查星系英文名（用于星系搜索对话框中文输入）。"""
        self._ensure()
        return [
            en
            for en, zh in self._data.get("system_names", {}).items()
            if keyword in zh
        ]

    # ── 结构改件类别标签 ──

    def rig_category(self, key: str) -> str | None:
        """结构改件制造类别标签（me_research→材料效率研究 等）。未知返回 None。"""
        self._ensure()
        return cast(str | None, self._data.get("rig_categories", {}).get(key))

    # ── 重载 ──

    def reload(self) -> None:
        self._loaded = False


# 模块级单例
term = Terminology()
