"""合同市场数据访问 — 供 UI Worker 调用的只读查询。"""

from __future__ import annotations

from core.container import get_container


def load_contracts(region_id: int, contract_type: str = "all") -> list[dict]:
    with get_container().db.connect("mkt") as conn:
        query = "SELECT * FROM public_contracts WHERE region_id = ?"
        params: list = [region_id]
        if contract_type != "all":
            query += " AND type = ?"
            params.append(contract_type)
        query += " ORDER BY date_issued DESC LIMIT 2000"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def load_contract_items(contract_id: int) -> list[dict]:
    with get_container().db.connect("mkt", "ref") as conn:
        rows = conn.execute(
            """
            SELECT ci.*, r.zh_name, r.en_name
            FROM contract_items ci
            LEFT JOIN ref.item r ON ci.type_id = r.type_id
            WHERE ci.contract_id = ?
            ORDER BY ci.record_id
            """,
            (contract_id,),
        ).fetchall()
        return [dict(r) for r in rows]
