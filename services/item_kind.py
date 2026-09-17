"""物品种类判定 — 蓝图 / 材料（供剪贴板导入按仓库类型校验）。

蓝图判定依据 reference.db ``item`` 表的 group 名后缀（实测 database/reference.db
50219 件物品、CCP 分类 9 共 5044 件蓝图：命中 5044，0 误 0 漏）：

- ``en_group_name`` 以 Blueprint(s) / Formula(s) 结尾
- ``zh_group_name`` 以 蓝图 / 公式 / 配方 结尾

不用其它来源的原因：

- ``item.category_id``：**曾经**不可靠 —— 随包 reference.db 该列一度全为 NULL
  （`sde_loader.write_categories` 的后半段没跑完）。2026-09-17 已回填，
  但判定逻辑不依赖它：未重跑 `sde_data` 的老库该列仍是 NULL，
  而 group 名后缀谓词在两种库上都成立。
- ``bp.blueprint_activities/products``：含发明源遗物（如「完整的推进器」）、漏部分
  真实蓝图；且 6 个「屹立…改装件 - 蓝图拷贝优化」名字含「蓝图」却并非蓝图，
  后缀谓词正好把这类名字排除。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from core.logger import log

#: item 表按名称查找所需的索引（名称解析的精确匹配 / item_kind 的材料行判定 / LIKE 回退）
_ITEM_NAME_INDEXES = ("idx_item_zh_name", "idx_item_en_name")
_ITEM_NAME_INDEX_COLUMNS = ("zh_name", "en_name")


def item_name_index_sql() -> list[str]:
    """item 表名称索引的 CREATE 语句（异步写库路径用；同步路径见 `ensure_item_name_indexes`）。"""
    return [
        f"CREATE INDEX IF NOT EXISTS {name} ON item({column})"
        for name, column in zip(_ITEM_NAME_INDEXES, _ITEM_NAME_INDEX_COLUMNS, strict=True)
    ]


# group 名后缀谓词（SQLite LIKE 对 ASCII 大小写不敏感）
_EN_GROUP_SUFFIXES = ("%Blueprint", "%Blueprints", "%Formula", "%Formulas")
_ZH_GROUP_SUFFIXES = ("%蓝图", "%公式", "%配方")
# 名字标记：带这些词的剪贴板行按「蓝图行」对待（反应配方 = 反应类蓝图）
_BLUEPRINT_NAME_MARKERS = ("蓝图", "blueprint", "公式", "配方", "formula")


def ensure_item_name_indexes(conn: sqlite3.Connection) -> int:
    """在 item 表上建 zh_name / en_name 索引（已存在则跳过）。返回本次新建的索引数。

    item 表此前只有主键，按名称查找（剪贴板导入的名称解析、材料行判定）只能全表扫
    5 万行。索引在 SDE item 表建表之后创建（两个 importer 的 ``initialize_database``
    各调一次，先到先建、后到跳过），老库由下次初始化补齐。

    缺列（老库无 ``en_name``）或只读库 → 静默跳过：索引是加速手段，不是正确性依赖。
    """
    created = 0
    for name, sql in zip(_ITEM_NAME_INDEXES, item_name_index_sql(), strict=True):
        try:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()
            if exists:
                continue
            conn.execute(sql)
            created += 1
        except sqlite3.Error:
            log.debug("item 名称索引 %s 未创建（列缺失或库只读），按名称查找将全表扫描", name)
    return created


def looks_like_blueprint_name(name: str | None) -> bool:
    """名字是否带蓝图标记（蓝图 / Blueprint / 公式 / 配方 / Formula，忽略大小写）。"""
    text = (name or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _BLUEPRINT_NAME_MARKERS)


def blueprint_type_ids(
    conn: sqlite3.Connection | sqlite3.Cursor,
    type_ids: Iterable[int | None],
) -> set[int]:
    """从 type_ids 中挑出蓝图 id（单次批量查询）。

    Args:
        conn: reference.db 连接（或已 ATTACH item 表的连接 / cursor）
        type_ids: 待判定 id，None 与 0 自动跳过

    Returns:
        属于蓝图的 id 集合。查询失败（如旧库缺 ``en_group_name`` 列）→ 返回空集合：
        **失败开放**，调用方本次不做过滤，绝不因判定失败阻断导入流程。
    """
    ids = sorted({int(t) for t in type_ids if t})
    if not ids:
        return set()
    placeholders = ",".join("?" * len(ids))
    where = " OR ".join(
        ["en_group_name LIKE ?"] * len(_EN_GROUP_SUFFIXES) + ["zh_group_name LIKE ?"] * len(_ZH_GROUP_SUFFIXES)
    )
    sql = f"SELECT type_id FROM item WHERE type_id IN ({placeholders}) AND ({where})"
    params: list[object] = [*ids, *_EN_GROUP_SUFFIXES, *_ZH_GROUP_SUFFIXES]
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        log.exception("蓝图种类查询失败，本次导入不做蓝图过滤")
        return set()
    return {int(r[0]) for r in rows}


def is_material_name(conn: sqlite3.Connection | sqlite3.Cursor, name: str) -> bool:
    """名字是否可判定为「材料行」（蓝图导入按仓库类型过滤用）。

    规则：带蓝图标记 → False；否则 ``zh_name/en_name`` 精确命中 item 且该物品不是
    蓝图 → True。既无标记又查不到的垃圾行返回 False（由调用方沿用原有静默跳过）。
    """
    if looks_like_blueprint_name(name):
        return False
    text = (name or "").strip()
    if not text:
        return False
    try:
        row = conn.execute(
            "SELECT type_id FROM item WHERE zh_name = ? OR en_name = ? LIMIT 1",
            (text, text),
        ).fetchone()
    except sqlite3.Error:
        log.exception("材料行判定查询失败，跳过过滤")
        return False
    if not row:
        return False
    return int(row[0]) not in blueprint_type_ids(conn, [row[0]])
