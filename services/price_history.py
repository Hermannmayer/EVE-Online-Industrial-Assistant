"""
Market price history — ESI /markets/{region_id}/history/
Cache in market.db price_history table
"""

from datetime import UTC, date, datetime, timedelta

import aiohttp

from services.database_manager import get_db

ESI_BASE_URL = "https://esi.evetech.net/latest"
REGION_ID = 10000002  # The Forge

#: ESI `/markets/{region_id}/history/` 的日更时刻（UTC，实测响应 `Expires` 为当日 11:05、
#: `Last-Modified` 为前一日 11:05）。缓存新鲜度按「是否已跨过最近的日更点」判定，
#: 而不是固定 1h：固定 1h 会让同一份一天只变一次的数据一天被拉 24 次（02-07）。
HISTORY_UPDATE_HOUR_UTC = 11
HISTORY_UPDATE_MINUTE_UTC = 5

#: 历史缓存 TTL —— **全仓单一来源**（`services/importers/getprices.py` 也 import 它）。
HISTORY_TTL_SECONDS = 24 * 3600

#: 旧名兼容：UI 走势图 worker 与既有测试仍 import 这个常量。
CACHE_TTL_SECONDS = HISTORY_TTL_SECONDS

#: `fetch_history` 收到 304（条件请求命中）时的哨兵：与「404/失败返回 None」、
#: 「200+[] 合法空」区分开，调用方据此只续 `fetched_at` 而不重写 410 行。
NOT_MODIFIED = object()

#: `price_history` 的建表语句 —— **单一来源**。
#: 除了这里的 `_ensure_table`，「更新价格」流程（`services/importers/getprices.py`）也会
#: 用 aiosqlite 直接写这张表，两边必须完全一致，所以 DDL 只留这一份。
#: market.db 是可重建缓存，故不走 `schema_migrations`（克制条款第 3 条）。
PRICE_HISTORY_DDL = """
    CREATE TABLE IF NOT EXISTS price_history (
        type_id INTEGER NOT NULL,
        region_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        average REAL NOT NULL,
        highest REAL NOT NULL DEFAULT 0,
        lowest REAL NOT NULL DEFAULT 0,
        volume INTEGER NOT NULL DEFAULT 0,
        order_count INTEGER NOT NULL DEFAULT 0,
        fetched_at TEXT NOT NULL,
        etag TEXT,
        PRIMARY KEY (type_id, region_id, date)
    )
"""

#: `(region_id, date)` 索引 —— **大盘页性能的关键**。
#: 主键是 `(type_id, region_id, date)`，按 `region_id + date` 过滤（广度、日成交额、
#: 指数装载窗口）**用不上主键前缀**，会全表扫 116 万行：实测（2026-10，真实库）
#: `get_breadth` 2.04s、`_turnover_series` 0.67s、`get_index_series` 合计近 10s，
#: 切到「市场监控」页一次性阻塞主线程 16 秒。加上本索引后这些范围扫描走索引。
PRICE_HISTORY_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_price_history_region_date ON price_history(region_id, date)"


def _last_history_update(now: datetime) -> datetime:
    """最近一次 ESI 日更点（UTC naive）。

    `fetched_at >= 这个点` ⇒ 缓存已经是「今天这一版」；否则说明跨过了日更点，要重拉。
    这样 TTL 不依赖用户点刷新的时刻，也不会在 11:05 前后各拉一次。
    """
    now = now.replace(tzinfo=None) if now.tzinfo is not None else now
    candidate = now.replace(hour=HISTORY_UPDATE_HOUR_UTC, minute=HISTORY_UPDATE_MINUTE_UTC, second=0, microsecond=0)
    return candidate if now >= candidate else candidate - timedelta(days=1)


def _ensure_table(db=None) -> None:
    """Ensure price_history table（与索引）exists in market.db"""
    conn_mgr = db or get_db()
    with conn_mgr.connect("mkt") as conn:
        conn.execute(PRICE_HISTORY_DDL)
        conn.execute(PRICE_HISTORY_INDEX_DDL)


async def fetch_history(
    type_id: int,
    region_id: int = REGION_ID,
    session: aiohttp.ClientSession | None = None,
    *,
    etag: str | None = None,
    etag_holder: list | None = None,
) -> list[dict] | None | object:
    """Fetch price history from ESI /markets/{region_id}/history/

    Returns list of {date, average, highest, lowest, volume, order_count}
    `None` on 404/error; `NOT_MODIFIED` on 304（条件请求命中，调用方只续 fetched_at）。

    etag: 上次响应头里的 ETag。`session` 路径会发 `If-None-Match`；不传 session
    （临时 APIClient 路径）时条件请求不支持，按普通 GET 处理。
    etag_holder: 传入一个 list 时，200 响应会把新 ETag append 进去（供批量导入落库）。
    """
    url = f"{ESI_BASE_URL}/markets/{region_id}/history/"
    params = {"type_id": type_id}
    headers = {"If-None-Match": etag} if etag else None

    async def _do(s: aiohttp.ClientSession) -> list[dict] | None | object:
        async with s.get(url, params=params, headers=headers) as resp:
            if resp.status == 304:
                return NOT_MODIFIED
            if resp.status == 404:
                return None
            if not resp.ok:
                resp.raise_for_status()
            if etag_holder is not None:
                etag_holder.append(resp.headers.get("ETag"))
            return await resp.json()  # type: ignore[no-any-return]

    if session is not None:
        return await _do(session)

    from services.client import APIClient

    query = "&".join(f"{k}={v}" for k, v in params.items())
    async with APIClient(timeout=30) as client:
        return await client.fetch_raw(f"{url}?{query}")  # type: ignore[no-any-return]


def get_cached_history(type_id: int, region_id: int = REGION_ID, _db=None) -> list[dict] | None:
    """Read cached history from market.db

    Returns cached data if fresh (within CACHE_TTL), None otherwise.
    """
    conn_mgr = _db or get_db()
    _ensure_table(conn_mgr)
    with conn_mgr.connect("mkt") as conn:
        row = conn.execute(
            "SELECT MAX(fetched_at) as latest FROM price_history WHERE type_id=? AND region_id=?",
            (type_id, region_id),
        ).fetchone()
        if row and row["latest"]:
            fetched = datetime.fromisoformat(row["latest"])
            now = datetime.now(UTC).replace(tzinfo=None)
            if fetched.tzinfo:
                fetched = fetched.replace(tzinfo=None)
            # 已跨过最近一次 ESI 日更点 ⇒ 缓存过期（一天只拉一次，见 02-07）
            if fetched >= _last_history_update(now):
                rows = conn.execute(
                    "SELECT date, average, highest, lowest, volume, order_count "
                    "FROM price_history WHERE type_id=? AND region_id=? "
                    "ORDER BY date ASC",
                    (type_id, region_id),
                ).fetchall()
                if rows:
                    return [dict(r) for r in rows]
    return None


def save_cache(type_id: int, region_id: int, data: list[dict], _db=None) -> None:
    """Save price history to market.db cache"""
    conn_mgr = _db or get_db()
    _ensure_table(conn_mgr)
    with conn_mgr.connect("mkt") as conn:
        conn.execute(
            "DELETE FROM price_history WHERE type_id=? AND region_id=?",
            (type_id, region_id),
        )
        now = datetime.now(UTC).isoformat()
        for entry in data:
            conn.execute(
                "INSERT INTO price_history "
                "  (type_id, region_id, date, average, highest, lowest, "
                "  volume, order_count, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    type_id,
                    region_id,
                    entry["date"],
                    entry["average"],
                    entry.get("highest", entry["average"]),
                    entry.get("lowest", entry["average"]),
                    entry["volume"],
                    entry.get("order_count", 0),
                    now,
                ),
            )


#: 「日订单量 / 日成交量」两列默认的聚合窗口（**日历天**）。
#: 与 `CACHE_TTL_SECONDS` 无关：那个管「多久算过期」，这个管「平均几天」。
SUMMARY_DAYS = 7

#: 一次 SQL 里 `IN (...)` 的参数个数上限（SQLite 变量上限的保守取值，与 blueprint_repository 同口径）
_SQL_PARAM_CHUNK = 900


def get_history_summary(
    type_ids,
    region_id: int = REGION_ID,
    days: int = SUMMARY_DAYS,
    _db=None,
    today: date | None = None,
) -> dict[int, dict]:
    """读本地缓存，算「最近 `days` 个**日历天**的平均订单量 / 成交量」→ `{type_id: {...}}`。

    载荷：`{"oc": 平均 order_count | None, "vol": 平均 volume | None,
    "days": 窗口内有记录的天数, "last": 最新记录日期, "stale": 本地历史是否整段早于窗口}`。

    ⚠️ **必须按日历天，不能按「最近 `days` 条记录」**：ESI 的
    `/markets/{region_id}/history/` **只返回有成交的日子**（日期是跳的），冷门物品那 7 条
    能横跨好几个月 —— 「近 7 日平均」于是变成「上次活跃那几天平均」。实测 `屹立白蚁 II`
    （type 47128）最新记录 2026-07-17、最近 7 条横跨 2026-05-14 ~ 07-17，算出 21.6/天，
    而它已经两个多月没成交（用户报的正是这条）。

    窗口内**没有记录的日子按 0 计入**（ESI 不返回那天 = 那天成交 0），所以分母恒为 `days`
    —— 算出来就是「最近这些天真能卖多少」。

    查不到的 type **不出现在返回值里**（调用方 `.get(id)` → `None` → 表格显示 `—`）：
    这里**不用 0 冒充「查不到」**。

    「本地没拉过」与「物品真没成交」必须分开（靠 `fetched_at`）：

    - 最近 `days` 天内**拉过**这份历史（`fetched_at` 在窗口内）→ 没记录就是**真的 0 成交**，
      照实给 `0`；
    - 最后一次拉取也早于窗口 → 本地这份数据过期，给 `stale=True` + `oc`/`vol` = `None`
      （显示 `—`，状态行提示去「更新价格」），**不拿 0 冒充「没人买」**。

    `today` 只为测试注入；缺省取本机当天。
    """
    ids = [int(t) for t in type_ids if t]
    if not ids:
        return {}

    window = max(1, int(days))
    end_day = today or date.today()
    start = (end_day - timedelta(days=window - 1)).isoformat()
    end = end_day.isoformat()

    conn_mgr = _db or get_db()
    with conn_mgr.connect("mkt") as conn:
        # 只读路径不做 DDL：表还没建（从没打开过价格走势图、也从没更新过价格）就是没有数据
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='price_history'").fetchone():
            return {}

        marks: dict[int, tuple[str, str]] = {}
        window_sums: dict[int, tuple[float, float, int]] = {}
        for offset in range(0, len(ids), _SQL_PARAM_CHUNK):
            chunk = ids[offset : offset + _SQL_PARAM_CHUNK]
            ph = ",".join("?" * len(chunk))
            for tid, last, fetched in conn.execute(
                f"SELECT type_id, MAX(date), MAX(fetched_at) FROM price_history "
                f"WHERE region_id = ? AND type_id IN ({ph}) GROUP BY type_id",
                (region_id, *chunk),
            ).fetchall():
                marks[int(tid)] = (str(last), str(fetched))
            for tid, vol_sum, oc_sum, covered in conn.execute(
                f"SELECT type_id, SUM(volume), SUM(order_count), COUNT(*) FROM price_history "
                f"WHERE region_id = ? AND type_id IN ({ph}) AND date >= ? AND date <= ? GROUP BY type_id",
                (region_id, *chunk, start, end),
            ).fetchall():
                window_sums[int(tid)] = (float(vol_sum or 0), float(oc_sum or 0), int(covered))

    out: dict[int, dict] = {}
    for tid, (last, fetched) in marks.items():
        # `fetched_at` 是 ISO 串（`2026-10-05T12:34:56.789+00:00`）→ 前 10 位就是日期
        pulled_in_window = fetched[:10] >= start
        if not pulled_in_window:
            # 本地这份历史整段早于窗口（很久没点「更新价格」）→ 不知道，不是 0
            out[tid] = {"oc": None, "vol": None, "days": 0, "last": last, "stale": True}
            continue
        vol_sum, oc_sum, covered = window_sums.get(tid, (0.0, 0.0, 0))
        out[tid] = {
            "oc": oc_sum / window,
            "vol": vol_sum / window,
            "days": covered,
            "last": last,
            "stale": False,
        }
    return out


class PriceHistoryService:
    """价格历史服务 — 容器注入 DatabaseManager（替代模块级 get_db 单例）"""

    def __init__(self, db):
        self._db = db

    async def fetch(self, type_id: int, region_id: int = REGION_ID, session=None) -> list[dict] | None:
        """拉取 ESI 历史价格（失败返回 None）。

        条件请求命中（304）时 `fetch_history` 返回 `NOT_MODIFIED` 哨兵；本服务不暴露该语义
        （调用方没有 ETag 上下文），统一折叠成 None。
        """
        data = await fetch_history(type_id, region_id, session)
        return data if isinstance(data, list) else None

    def get_cached(self, type_id: int, region_id: int = REGION_ID) -> list[dict] | None:
        """读取缓存历史价格（TTL 内命中，否则 None）"""
        return get_cached_history(type_id, region_id, _db=self._db)

    def save(self, type_id: int, region_id: int, data: list[dict]) -> None:
        """写入缓存历史价格"""
        save_cache(type_id, region_id, data, _db=self._db)
