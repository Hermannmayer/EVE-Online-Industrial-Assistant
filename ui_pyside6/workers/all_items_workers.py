"""全物品市场 — 后台 Worker（市场树 / 物品列表 / 搜索）"""

from PySide6.QtCore import QThread, Signal

from core.constants import TRADE_HUB_IDS
from core.container import get_container

JITA_RID = TRADE_HUB_IDS["Jita"]

_SQL = (
    "SELECT i.market_group_id,i.type_id,i.zh_name,i.en_name,i.volume,"
    "mp.buy_price,mp.sell_price,mp.buy_volume,mp.sell_volume "
    "FROM item i "
    "LEFT JOIN mkt.market_prices mp ON mp.type_id=i.type_id "
    "AND mp.region_id=? AND mp.fetch_time=(SELECT MAX(fetch_time) "
    "FROM mkt.market_prices WHERE type_id=i.type_id AND region_id=?) "
)


def _fetch(sql, rid: int, params=None):
    with get_container().db.connect("ref", "mkt") as conn:
        c = conn.cursor()
        if params:
            c.execute(sql, (rid, rid, *params))
        else:
            c.execute(sql, (rid, rid))
        r = []
        for row in c.fetchall():
            mg, tid, zh, en, vol, bp, sp, bv, sv = row
            ap = ((bp or 0) + (sp or 0)) / 2 if bp and sp else (bp or sp)
            r.append(
                {
                    "mg": mg,
                    "id": tid,
                    "z": zh or "",
                    "e": en or "",
                    "v": vol or 0,
                    "bp": bp,
                    "sp": sp,
                    "ap": ap,
                    "bv": bv or 0,
                    "sv": sv or 0,
                }
            )
        return r


class TreeW(QThread):
    done = Signal(list)

    def run(self):
        with get_container().db.connect("ref", "bp") as conn:
            c = conn.cursor()
            c.execute("SELECT market_group_id,parent_group_id,zh_name FROM market_tree ORDER BY zh_name")
            r = [{"id": i, "p": p, "n": z or f"G{i}"} for i, p, z in c.fetchall()]
            self.done.emit(r)


class ItemsW(QThread):
    done = Signal(list)

    def __init__(self, ids=None, rid: int = 0, parent=None):
        super().__init__(parent)
        self._ids = ids
        self._rid = rid

    def run(self):
        if self._ids:
            ph = ",".join("?" * len(self._ids))
            r = _fetch(_SQL + f"WHERE i.market_group_id IN ({ph}) ORDER BY i.zh_name LIMIT 2000", self._rid, self._ids)
        else:
            r = _fetch(_SQL + "ORDER BY i.zh_name LIMIT 2000", self._rid)
        self.done.emit(r)


class SearchItemsW(QThread):
    """按名称/ID 搜索物品"""

    done = Signal(list)

    def __init__(self, query: str, rid: int, parent=None):
        super().__init__(parent)
        self._query = query
        self._rid = rid

    def run(self):
        q = self._query.strip()
        if not q:
            self.done.emit([])
            return
        with get_container().db.connect("ref", "mkt", "bp") as conn:
            c = conn.cursor()
            rid = self._rid
            like = f"%{q}%"
            if q.isdigit():
                _sql_where = _SQL + "WHERE (i.type_id=? OR i.zh_name LIKE ? OR i.en_name LIKE ?)"
                _sql_where += " ORDER BY i.zh_name LIMIT 500"
                c.execute(_sql_where, (rid, rid, int(q), like, like))
            else:
                _sql_where = _SQL + "WHERE (i.zh_name LIKE ? OR i.en_name LIKE ?)"
                _sql_where += " ORDER BY CASE WHEN i.en_name LIKE ? THEN 0"
                _sql_where += " WHEN i.zh_name LIKE ? THEN 1 ELSE 2 END, i.zh_name LIMIT 500"
                c.execute(_sql_where, (rid, rid, like, like, f"{q}%", f"{q}%"))
            r = []
            for row in c.fetchall():
                mg, tid, zh, en, vol, bp, sp, bv, sv = row
                ap = ((bp or 0) + (sp or 0)) / 2 if bp and sp else (bp or sp)
                r.append(
                    {
                        "mg": mg,
                        "id": tid,
                        "z": zh or "",
                        "e": en or "",
                        "v": vol or 0,
                        "bp": bp,
                        "sp": sp,
                        "ap": ap,
                        "bv": bv or 0,
                        "sv": sv or 0,
                    }
                )
            self.done.emit(r)
