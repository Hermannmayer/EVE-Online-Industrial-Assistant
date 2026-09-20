"""库存剪贴板解析 — 将 EVE 复制文本匹配到物品 ID，并过滤蓝图行。

材料仓库只导入材料：已匹配行按物品种类过滤蓝图，未匹配行按名字标记过滤（见
``_filter_blueprint_rows``），避免游戏内复制整仓时把蓝图（含 ME/TE/流程列）当成
材料导入。

另有 `parse_purchase_clipboard`：「钱包 → 交易记录」的**买入行**（带单价）入库，
与整仓复制是两种文本，故不共用上面的蓝图过滤 —— 买蓝图同样是正当入库。
"""

from __future__ import annotations

import sqlite3

from core.container import get_container
from core.logger import log
from services.inventory_import import split_clipboard_lines
from services.item_kind import blueprint_type_ids, looks_like_blueprint_name
from services.name_resolver import resolve_item_name, search_item_type_ids_batch
from services.wallet_import import parse_purchase_records


def parse_clipboard(raw: str) -> tuple[list[dict], int]:
    """解析 EVE 剪贴板 → (材料行, 被过滤的蓝图行数)。"""
    with get_container().db.connect("ref") as conn:
        return parse_clipboard_rows(conn, raw)


def parse_clipboard_rows(
    conn: sqlite3.Connection | sqlite3.Cursor,
    raw: str,
) -> tuple[list[dict], int]:
    """按 ref 连接解析剪贴板并过滤蓝图行（可单测，不依赖容器）。

    批量匹配：整仓复制动辄几百行，逐行匹配会对 item 表逐行 LIKE 全表扫描（秒级）。
    一次性取出全部名字批量解析，只有精确匹配未命中的少数行才走模糊回退。

    Returns:
        ``(rows, filtered)``：rows 为保留行 ``[{type_id|None, raw_name, zh_name,
        en_name, qty, status}]``（字段与旧实现一致）；filtered 为被过滤掉的蓝图行数。
    """
    entries = split_clipboard_lines(raw)
    matched = search_item_type_ids_batch(conn, [e["name"] for e in entries])
    rows: list[dict] = []
    for entry in entries:
        name = entry["name"]
        type_id = matched.get(name)
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


def parse_purchase_clipboard(raw: str) -> tuple[list[dict], dict]:
    """解析「钱包 → 交易记录」的买入行 → (行, stats)。stats 见 `parse_purchase_records`。"""
    with get_container().db.connect("ref") as conn:
        return parse_purchase_rows(conn, raw)


def parse_purchase_rows(
    conn: sqlite3.Connection | sqlite3.Cursor,
    raw: str,
) -> tuple[list[dict], dict]:
    """按 ref 连接解析买入行并匹配 type_id（可单测，不依赖容器）。

    Returns:
        ``(rows, stats)``：rows 为买入行 ``[{time, raw_name, qty, unit_price, seller,
        type_id|None, zh_name, status}]``（``status`` = matched / unmatched），
        stats 为 ``{"sales": 卖出行数, "unparsed": 认不出的行数}``。
    """
    parsed, stats = parse_purchase_records(raw)
    matched = search_item_type_ids_batch(conn, [r["raw_name"] for r in parsed])
    rows: list[dict] = []
    for row in parsed:
        type_id = matched.get(row["raw_name"])
        name = resolve_item_name(conn, type_id) if type_id else ""
        rows.append(
            {
                **row,
                "type_id": type_id,
                "zh_name": name if name and not name.isdigit() else row["raw_name"],
                "status": "matched" if type_id else "unmatched",
            }
        )
    return rows, stats


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
