"""库存剪贴板解析 — 将 EVE 复制文本匹配到物品 ID，并过滤蓝图行。

材料仓库只导入材料：已匹配行按物品种类过滤蓝图，未匹配行按名字标记过滤（见
``_filter_blueprint_rows``），避免游戏内复制整仓时把蓝图（含 ME/TE/流程列）当成
材料导入。
"""

from __future__ import annotations

import sqlite3

from core.container import get_container
from core.logger import log
from services.inventory_import import split_clipboard_lines
from services.item_kind import blueprint_type_ids, looks_like_blueprint_name
from services.name_resolver import resolve_item_name, search_item_type_id


def parse_clipboard(raw: str) -> tuple[list[dict], int]:
    """解析 EVE 剪贴板 → (材料行, 被过滤的蓝图行数)。"""
    with get_container().db.connect("ref") as conn:
        return parse_clipboard_rows(conn, raw)


def parse_clipboard_rows(
    conn: sqlite3.Connection | sqlite3.Cursor,
    raw: str,
) -> tuple[list[dict], int]:
    """按 ref 连接解析剪贴板并过滤蓝图行（可单测，不依赖容器）。

    Returns:
        ``(rows, filtered)``：rows 为保留行 ``[{type_id|None, raw_name, zh_name,
        en_name, qty, status}]``（字段与旧实现一致）；filtered 为被过滤掉的蓝图行数。
    """
    rows: list[dict] = []
    for entry in split_clipboard_lines(raw):
        name = entry["name"]
        type_id = search_item_type_id(conn, name)
        if type_id:
            nm = resolve_item_name(conn, type_id)
            rows.append(
                {
                    "type_id": type_id,
                    "raw_name": name,
                    "zh_name": nm if not nm.isdigit() else name,
                    "en_name": "" if nm.isdigit() else nm,
                    "qty": entry["qty"],
                    "status": "matched",
                }
            )
        else:
            rows.append(
                {
                    "type_id": None,
                    "raw_name": name,
                    "zh_name": "",
                    "en_name": "",
                    "qty": entry["qty"],
                    "status": "unmatched",
                }
            )
    return _filter_blueprint_rows(conn, rows)


def _filter_blueprint_rows(
    conn: sqlite3.Connection | sqlite3.Cursor,
    rows: list[dict],
) -> tuple[list[dict], int]:
    """丢弃蓝图行：已匹配行按物品种类，未匹配行按名字标记。"""
    blueprint_ids = blueprint_type_ids(conn, [r.get("type_id") for r in rows])
    kept: list[dict] = []
    filtered = 0
    for row in rows:
        type_id = row.get("type_id")
        if type_id:
            drop = type_id in blueprint_ids
        else:
            drop = looks_like_blueprint_name(row.get("raw_name"))
        if not drop:
            kept.append(row)
            continue
        filtered += 1
        log.debug("材料剪贴板导入已过滤蓝图行: %s", row.get("raw_name") or type_id)
    return kept, filtered
