"""物品种类判定 — 蓝图 / 材料（供剪贴板导入按仓库类型校验）。

蓝图判定依据 reference.db ``item`` 表的 group 名后缀（实测 database/reference.db
50219 件物品、CCP 分类 9 共 5044 件蓝图：命中 5044，0 误 0 漏）：

- ``en_group_name`` 以 Blueprint(s) / Formula(s) 结尾
- ``zh_group_name`` 以 蓝图 / 公式 / 配方 结尾

不用其它来源的原因：

- ``item.category_id``：随包 reference.db 该列全为 NULL（sde_loader 的 category
  步骤未跑），不能作为唯一依据。
- ``bp.blueprint_activities/products``：含发明源遗物（如「完整的推进器」）、漏部分
  真实蓝图；且 6 个「屹立…改装件 - 蓝图拷贝优化」名字含「蓝图」却并非蓝图，
  后缀谓词正好把这类名字排除。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from core.logger import log

# group 名后缀谓词（SQLite LIKE 对 ASCII 大小写不敏感）
_EN_GROUP_SUFFIXES = ("%Blueprint", "%Blueprints", "%Formula", "%Formulas")
_ZH_GROUP_SUFFIXES = ("%蓝图", "%公式", "%配方")
# 名字标记：带这些词的剪贴板行按「蓝图行」对待（反应配方 = 反应类蓝图）
_BLUEPRINT_NAME_MARKERS = ("蓝图", "blueprint", "公式", "配方", "formula")


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
