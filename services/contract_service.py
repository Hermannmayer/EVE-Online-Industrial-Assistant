"""合同市场数据访问 —— 供 UI Worker 调用的只读查询 + 判定。

三个子页各一个入口，内部走同一条流水线：

    1. 按星域/类型/筛选条件查 `public_contracts`（**筛选下推到 SQL**，先筛再 LIMIT；
       否则「取前 N 条再本地筛」会把真正想看的合同挡在外面）
    2. 取这些合同的物品（只取 `items_fetched_at` 非空的 —— 没拉过就是还没拉到，不是没有）
    3. 批量查市价（分块防 SQLite 变量上限；本星域缺价回落到 Jita）
    4. 起止点 → 站名/星系/安全等级
    5. 交给 `domain/contract_analysis` 算判定

判定逻辑一律不写在这里 —— 本模块只负责取数与拼装，算术全在 `domain/` 且已单测覆盖。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from core.constants import TRADE_HUB_IDS
from core.container import get_container
from core.logger import log
from domain import contract_analysis as ca
from services import item_kind
from services.logistics import compute_jumps

#: 本星域查不到市价时回落到这里（用户可手动输入任意星域，那些星域未必有市场数据）。
FALLBACK_REGION_ID = TRADE_HUB_IDS["Jita"]

#: 单次载入上限。筛选已下推到 SQL，所以这是「筛完之后」的上限。
DEFAULT_LIMIT = 3000

#: 蓝图合同的体积判据 —— 蓝图固定 0.01 m³，实测 The Forge 的 item_exchange 里
#: `volume = 0.01` 占 49.6%（最大一类），抽查 36 份 `volume ≤ 0.05` 的全部含蓝图。
#: 是启发式，不是判据 —— 用户可以关掉这个筛选。
BLUEPRINT_VOLUME_MAX = 0.05

#: 运输合同的跳数口径。`none` = 用户还没选，界面显示「—」。
JUMP_MODES = ("none", "shortest", "highsec", "custom")

#: 跳数为什么是空的 —— 四种情况对跑货的人是**完全不同的结论**，不能都显示成「—」：
#:   `ok`               算出来了
#:   `not_computed`     用户还没选口径（不是缺陷）
#:   `unknown_endpoint` 起止点解析不出星系（玩家建筑 id ≥ 1e12，或库中无此站）
#:   `unroutable`       起止点都知道，但**所选口径下没有路线** —— 高安口径下这几乎
#:                      总是意味着「必须穿低安」，这是最有价值的信号，不是「数据缺失」
JUMP_OK = "ok"
JUMP_NOT_COMPUTED = "not_computed"
JUMP_UNKNOWN_ENDPOINT = "unknown_endpoint"
JUMP_UNROUTABLE = "unroutable"

#: SQLite 变量上限防护（与 `market_repository._SQL_VAR_CHUNK` 同因）。
_SQL_VAR_CHUNK = 500


# ════════════════════════════════════════════════════
#  取数辅助
# ════════════════════════════════════════════════════


def _chunks(ids: list[int]) -> Iterable[list[int]]:
    for i in range(0, len(ids), _SQL_VAR_CHUNK):
        yield ids[i : i + _SQL_VAR_CHUNK]


def _build_where(region_id: int, contract_type: str, filters: dict[str, Any] | None) -> tuple[str, list]:
    """把筛选条件下推成 SQL —— 先筛再 LIMIT，语义才正确。"""
    where = ["region_id = ?", "type = ?"]
    params: list[Any] = [region_id, contract_type]

    f = filters or {}
    # 价格取「一口价优先，其次当前出价」，与 domain 的 entry_cost 口径一致
    if f.get("price_min"):
        where.append("COALESCE(NULLIF(buyout, 0), price) >= ?")
        params.append(float(f["price_min"]))
    if f.get("price_max"):
        where.append("COALESCE(NULLIF(buyout, 0), price) <= ?")
        params.append(float(f["price_max"]))
    if f.get("blueprint_only"):
        where.append("volume <= ?")
        params.append(BLUEPRINT_VOLUME_MAX)
    # 按发布者名字反查 —— 名字在 `contract_issuers` 里（ESI 的合同端点只给 id），
    # 所以走子查询。`LIKE` 而不是 `=`：用户往往只记得名字的一部分，而且双击复制到的
    # 是完整名字，粘进来也能匹配。
    if (f.get("issuer") or "").strip():
        where.append("issuer_id IN (SELECT issuer_id FROM contract_issuers WHERE name LIKE ?)")
        params.append(f"%{str(f['issuer']).strip()}%")
    if f.get("hide_expired", True):
        where.append("date_expired > ?")
        params.append(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    # 剩余时间下限（小时）
    if f.get("min_hours_left"):
        floor = datetime.now(UTC) + timedelta(hours=float(f["min_hours_left"]))
        where.append("date_expired >= ?")
        params.append(floor.strftime("%Y-%m-%dT%H:%M:%SZ"))

    return " AND ".join(where), params


def _contract_rows(region_id: int, contract_type: str, filters: dict[str, Any] | None, limit: int) -> list[dict]:
    clause, params = _build_where(region_id, contract_type, filters)
    with get_container().db.connect("mkt") as conn:
        try:
            rows = conn.execute(
                f"SELECT * FROM public_contracts WHERE {clause} ORDER BY COALESCE(NULLIF(buyout, 0), price) DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        except sqlite3.OperationalError as ex:
            # 只吞「发布者表还不存在」这一种：`contract_issuers` 由「拉取合同」建，
            # 老库 + 用户没点过拉取，就是没有这张表。此时按发布者查无从匹配 ——
            # 给空结果，不把整页变成「数据库查询失败」。别的一律重抛。
            if "contract_issuers" not in str(ex):
                raise
            log.warning("发布者表尚不存在（还没拉过合同），按发布者查返回空")
            return []
    return [dict(r) for r in rows]


def _items_by_contract(contract_ids: Sequence[int]) -> dict[int, list[dict]]:
    ids = list(dict.fromkeys(contract_ids))
    if not ids:
        return {}
    out: dict[int, list[dict]] = {}
    with get_container().db.connect("mkt", "ref") as conn:
        for chunk in _chunks(ids):
            ph = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT ci.*, r.zh_name, r.en_name FROM contract_items ci "
                f"LEFT JOIN ref.item r ON ci.type_id = r.type_id "
                f"WHERE ci.contract_id IN ({ph}) ORDER BY ci.record_id",
                tuple(chunk),
            ).fetchall()
            for r in rows:
                out.setdefault(int(r["contract_id"]), []).append(dict(r))
    return out


def price_map_for(type_ids: Iterable[int], region_id: int, price_type: str = "sell") -> dict[int, float]:
    """`{type_id: 单价}` —— 本星域缺价的回落到 Jita。

    回落是必要的：用户可以手动输入任意星域（例如静谧谷），而那些星域根本没有
    `market_prices` 行 —— 不回落的话整页合同都会显示「无价」。
    """
    ids = sorted({int(t) for t in type_ids if t})
    if not ids:
        return {}
    repo = get_container().market_repo
    prices: dict[int, float] = repo.get_prices_by_region(ids, region_id, price_type)
    if region_id != FALLBACK_REGION_ID:
        missing = [t for t in ids if t not in prices]
        if missing:
            prices.update(repo.get_prices_by_region(missing, FALLBACK_REGION_ID, price_type))
    return prices


def _station_lookup(location_ids: Iterable[int]) -> dict[int, dict]:
    """location_id → 站名 / 星系名 / 安全等级。

    没复用 `npc_seller.resolve_stations`：它返回 `(站名, 星系名)` 的二元组，而这里还
    需要安全等级，改它的返回形状会连累 `resolve_stations_by_ids` 的四处调用方与其测试。
    玩家建筑（id ≥ 1e12）不在 `station` 表里 —— 查不到即「未知」，这是如实反映。
    """
    ids = sorted({int(x) for x in location_ids if x})
    if not ids:
        return {}
    out: dict[int, dict] = {}
    with get_container().db.connect("ref") as conn:
        for chunk in _chunks(ids):
            ph = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT s.station_id, s.station_name, ss.solar_system_name, ss.security "
                f"FROM station s LEFT JOIN solar_system ss ON ss.solar_system_id = s.solar_system_id "
                f"WHERE s.station_id IN ({ph})",
                tuple(chunk),
            ).fetchall()
            for r in rows:
                out[int(r[0])] = {"station": r[1] or "", "system": r[2] or "", "security": r[3]}
    return out


def _blueprint_type_ids(type_ids: Iterable[int]) -> set[int]:
    ids = sorted({int(t) for t in type_ids if t})
    if not ids:
        return set()
    found: set[int] = set()
    with get_container().db.connect("ref") as conn:
        for chunk in _chunks(ids):
            found |= item_kind.blueprint_type_ids(conn, chunk)
    return found


def _recipes_for(blueprint_ids: Iterable[int]) -> dict[int, dict]:
    """`{蓝图 type_id: {product_type_id, output_qty, materials: [(mat_id, 基础量)]}}`。

    材料量用 `blueprint_materials.quantity`（**每轮基础量**）—— ME 调整由
    `domain.contract_analysis.manufacturing_profit` 走 `calc_material_for_runs` 做，
    在这里先乘一次就会把 ME 漏掉。
    """
    ids = sorted({int(b) for b in blueprint_ids if b})
    if not ids:
        return {}
    recipes: dict[int, dict] = {b: {"materials": []} for b in ids}
    with get_container().db.connect("bp") as conn:
        for chunk in _chunks(ids):
            ph = ",".join("?" * len(chunk))
            for bp_id, product_id, qty in conn.execute(
                f"SELECT blueprint_type_id, product_type_id, quantity FROM blueprint_products "
                f"WHERE activity = 'manufacturing' AND blueprint_type_id IN ({ph})",
                tuple(chunk),
            ):
                recipes[int(bp_id)]["product_type_id"] = int(product_id)
                recipes[int(bp_id)]["output_qty"] = int(qty or 1)
            for bp_id, mat_id, qty in conn.execute(
                f"SELECT blueprint_type_id, material_type_id, quantity FROM blueprint_materials "
                f"WHERE activity = 'manufacturing' AND blueprint_type_id IN ({ph})",
                tuple(chunk),
            ):
                recipes[int(bp_id)]["materials"].append((int(mat_id), int(qty)))
    # 没查到产物的条目是残缺配方，丢掉 —— 留着会让 manufacturing_profit 按 0 产物算
    return {b: r for b, r in recipes.items() if r.get("product_type_id")}


def _attach_places(rows: list[dict]) -> None:
    places = _station_lookup(lid for r in rows for lid in (r.get("start_location_id"), r.get("end_location_id")) if lid)
    for row in rows:
        for prefix, key in (("start", "start_location_id"), ("end", "end_location_id")):
            info = places.get(int(row.get(key) or 0))
            row[f"{prefix}_station"] = info["station"] if info else ""
            row[f"{prefix}_system"] = info["system"] if info else ""
            row[f"{prefix}_security"] = info["security"] if info else None


def _attach_icons(rows: list[dict], items: dict[int, list[dict]], price_map: dict[int, float]) -> None:
    """给合同行补「里面是什么」：主物品名 + 图标 + 件数。

    **不能只靠图标**：实测拍卖里值钱的物品多是涂装（SKIN），而 EVE 图床对涂装返
    404、本地图标缓存也没有 —— 只画图标这一列大半是空的。所以「物品」列是
    「图标（有就画）+ 主物品名 + N 件」，名字才是保底信息。
    """
    for row in rows:
        contract_items = items.get(int(row["contract_id"]), [])
        ranked = ca.icon_type_ids(contract_items, price_map)
        names = {
            int(it.get("type_id") or 0): (it.get("zh_name") or it.get("en_name") or f"ID:{it.get('type_id')}")
            for it in contract_items
        }
        row["icon_type_ids"] = ranked
        row["top_item_name"] = names.get(ranked[0], "") if ranked else ""
        row["item_count"] = len(contract_items)


def _attach_issuers(rows: list[dict]) -> None:
    """给合同行补 `issuer_name`（查不到给空串）。

    名字不在合同表里 —— ESI 的合同端点只给 `issuer_id`，名字由补齐任务另存到
    `contract_issuers`（见 `services.importers.getcontracts.run_issuer_name_fill`）。
    那张表由「拉取合同」建，还没拉过时缺表 —— 与 `list_regions` 缺列同款回退：
    名字列先空着，不是错误。
    """
    ids = sorted({int(r["issuer_id"]) for r in rows if r.get("issuer_id")})
    names: dict[int, str] = {}
    if ids:
        with get_container().db.connect("mkt") as conn:
            for chunk in _chunks(ids):
                ph = ",".join("?" * len(chunk))
                try:
                    found = conn.execute(
                        f"SELECT issuer_id, name FROM contract_issuers WHERE issuer_id IN ({ph})", tuple(chunk)
                    ).fetchall()
                except sqlite3.OperationalError:
                    break  # 缺表 —— 整批都不可能有名字，不必逐块重试
                names.update({int(r[0]): str(r[1]) for r in found})
    for row in rows:
        row["issuer_name"] = names.get(int(row.get("issuer_id") or 0), "")


def count_tab(region_id: int, contract_type: str, filters: dict[str, Any] | None = None) -> int:
    """当前筛选下这个页签有多少条 —— 页签上的条数徽标用。

    与列表走同一套 `_build_where`，所以徽标数字和状态行的「N 条」是同一个口径，
    不会出现「页签写 3.4 万、点进去只有 2000」（那是 LIMIT 截断，不是筛选）。
    """
    clause, params = _build_where(region_id, contract_type, filters)
    with get_container().db.connect("mkt") as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM public_contracts WHERE {clause}", params).fetchone()
    return int(row[0]) if row else 0


# ════════════════════════════════════════════════════
#  三个子页的入口
# ════════════════════════════════════════════════════


def load_auction_contracts(
    region_id: int,
    price_type: str = "sell",
    filters: dict[str, Any] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """拍卖合同 —— 内容物市价 vs 一口价（无一口价则按当前出价）。"""
    rows = _contract_rows(region_id, "auction", filters, limit)
    items = _items_by_contract([r["contract_id"] for r in rows])
    price_map = price_map_for((it["type_id"] for its in items.values() for it in its), region_id, price_type)
    for row in rows:
        row.update(ca.auction_metrics(row, items.get(int(row["contract_id"]), []), price_map))
    _attach_icons(rows, items, price_map)
    _attach_places(rows)
    _attach_issuers(rows)
    return rows


def load_exchange_contracts(
    region_id: int,
    price_type: str = "sell",
    filters: dict[str, Any] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """物品交换合同 —— 含蓝图的走「蓝图市价 + 制造利润」，其余走内容物市价。"""
    rows = _contract_rows(region_id, "item_exchange", filters, limit)
    items = _items_by_contract([r["contract_id"] for r in rows])

    all_type_ids = {int(it["type_id"]) for its in items.values() for it in its}
    blueprint_ids = _blueprint_type_ids(all_type_ids)
    recipes = _recipes_for(blueprint_ids)

    # 价格要覆盖材料与产物 —— 只查合同里的物品算不出制造利润
    needed = set(all_type_ids)
    for recipe in recipes.values():
        needed.add(recipe["product_type_id"])
        needed.update(mat_id for mat_id, _ in recipe["materials"])
    price_map = price_map_for(needed, region_id, price_type)

    for row in rows:
        contract_items = items.get(int(row["contract_id"]), [])
        has_blueprint = any(int(it["type_id"]) in blueprint_ids for it in contract_items)
        metrics = (
            ca.blueprint_exchange_metrics(row, contract_items, price_map, recipes, blueprint_ids)
            if has_blueprint
            else ca.exchange_metrics(row, contract_items, price_map)
        )
        row.update(metrics)
        row["has_blueprint"] = has_blueprint
    _attach_icons(rows, items, price_map)
    _attach_places(rows)
    _attach_issuers(rows)
    return rows


def load_courier_contracts(
    region_id: int,
    jump_mode: str = "none",
    min_security: float | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """运输合同 —— 报酬摊到每跳 / 每方每跳。

    `jump_mode = "none"` 时**不算跳数**（用户明确要求：只有选了口径才算），
    两个指标都是 None，界面显示「—」。
    """
    rows = _contract_rows(region_id, "courier", filters, limit)
    _attach_places(rows)
    _attach_issuers(rows)

    compute = jump_mode in ("shortest", "highsec", "custom")
    system_ids: dict[int, int] = {}
    if compute:
        system_ids = _system_ids_for(rows)

    for row in rows:
        jumps = None
        status = JUMP_NOT_COMPUTED
        if compute:
            origin = system_ids.get(int(row.get("start_location_id") or 0))
            dest = system_ids.get(int(row.get("end_location_id") or 0))
            if not origin or not dest:
                status = JUMP_UNKNOWN_ENDPOINT
            else:
                jumps = compute_jumps(origin, dest, jump_mode, min_security)
                status = JUMP_OK if jumps is not None else JUMP_UNROUTABLE
        row.update(ca.courier_metrics(row, jumps))
        row["jumps_status"] = status
    return rows


def _system_ids_for(rows: list[dict]) -> dict[int, int]:
    """location_id → 星系 id（跳数计算的起点/终点）。"""
    ids = sorted({int(lid) for r in rows for lid in (r.get("start_location_id"), r.get("end_location_id")) if lid})
    if not ids:
        return {}
    out: dict[int, int] = {}
    with get_container().db.connect("ref") as conn:
        for chunk in _chunks(ids):
            ph = ",".join("?" * len(chunk))
            for sid, ssid in conn.execute(
                f"SELECT station_id, solar_system_id FROM station WHERE station_id IN ({ph})", tuple(chunk)
            ):
                if ssid:
                    out[int(sid)] = int(ssid)
    return out


# ════════════════════════════════════════════════════
#  星域搜索（合同页的星域输入框用；只此一处消费）
# ════════════════════════════════════════════════════


def list_regions(query: str = "", limit: int = 30) -> list[dict]:
    """按名称搜星域 → `[{region_id, name, en_name}]`。中英文都能匹配。

    用户不该被要求记住星域 id —— 官方中文名又和口语名对不上（口语「寂静谷」，
    官方是「静谧谷」），所以界面必须是「打几个字就出候选」而不是「填全名」。

    `region.zh_name` 是后加的列，老库没有 —— 缺列时退回只用英文名，不能因此报错。
    """
    keyword = f"%{query.strip()}%" if query.strip() else "%"
    with get_container().db.connect("ref") as conn:
        try:
            rows = conn.execute(
                "SELECT region_id, region_name, zh_name FROM region "
                "WHERE region_name LIKE ? OR zh_name LIKE ? ORDER BY region_name LIMIT ?",
                (keyword, keyword, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT region_id, region_name, NULL FROM region WHERE region_name LIKE ? ORDER BY region_name LIMIT ?",
                (keyword, limit),
            ).fetchall()
    return [{"region_id": int(r[0]), "en_name": r[1] or "", "name": r[2] or r[1] or str(r[0])} for r in rows]


def region_name(region_id: int) -> str:
    """星域显示名（中文优先）。查不到就返回 id 本身 —— 界面上总得显示点什么。

    `zh_name` 是后加的列，老库没有 —— 缺列时的回退查询只选**一列**，
    所以下面按列数取，不能一律写 `row[1]`。
    """
    with get_container().db.connect("ref") as conn:
        row = None
        try:
            row = conn.execute("SELECT region_name, zh_name FROM region WHERE region_id = ?", (region_id,)).fetchone()
        except sqlite3.OperationalError:
            pass
        if row is None:
            row = conn.execute("SELECT region_name FROM region WHERE region_id = ?", (region_id,)).fetchone()
    if not row:
        return f"星域 {region_id}"
    # 主查询给 (region_name, zh_name) —— 中文优先；回退查询只有 (region_name,)。
    # 按**位置**取，不能「遍历取第一个非空」：那样英文列会先命中，中文永远显示不出来。
    values = list(row)
    en_name = values[0]
    zh_name = values[1] if len(values) > 1 else None
    return str(zh_name or en_name or f"星域 {region_id}")


# ════════════════════════════════════════════════════
#  旧的通用入口（详情对话框与物品表仍在用）
# ════════════════════════════════════════════════════


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
