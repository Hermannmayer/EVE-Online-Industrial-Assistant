"""库存剪贴板解析 — 将 EVE 复制文本匹配到物品 ID。"""

from __future__ import annotations

from core.container import get_container
from services.inventory_import import split_clipboard_lines
from services.name_resolver import resolve_item_name, search_item_type_id


def parse_clipboard(raw: str) -> list[dict]:
    """解析 EVE 剪贴板 → list[{type_id|None, raw_name, zh_name, en_name, qty, status}]。"""
    rows: list[dict] = []
    with get_container().db.connect("ref") as conn:
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
    return rows
