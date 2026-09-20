"""
统一物品名称解析服务。

将 type_id 转换为可读的中文/英文物品名称。

解析优先级: terminology.item_overrides > item.zh_name > item.en_name > str(id)
"""

from __future__ import annotations

import re
import sqlite3

from core.logger import log
from services.item_kind import ensure_item_name_indexes
from services.terminology import term

#: 精确匹配的 IN 分块大小 —— 名字数量 ÷ 块数 = SQL 往返次数，块只影响往返延迟，不改语义
_NAME_CHUNK = 500


def _ensure_name_indexes(conn: sqlite3.Connection | sqlite3.Cursor) -> None:
    """模糊匹配前按需给 item 表补 zh_name / en_name 索引。

    LIKE 在无索引时是对 5 万行 item 表的**全表扫描**，整仓导入几百行就是秒级卡顿。
    两个 importer 的 ``initialize_database`` 建这两条索引（新库与重跑初始化即有），
    这里兜住**未重跑初始化步骤的已有库**：第一次用到时补建一次并 commit。

    索引已存在时只是一次 sqlite_master 查询，幂等。库只读 / 缺列 → 静默跳过，
    解析照旧走全表扫描（只是慢），绝不让加速手段变成导入的失败点。
    """
    if not isinstance(conn, sqlite3.Connection):
        return  # cursor 路径无 DDL 能力（测试替身），跳过
    try:
        if ensure_item_name_indexes(conn):
            conn.commit()
    except sqlite3.Error:
        log.debug("item 名称索引补建失败（库只读或结构异常），按名称查找将全表扫描")


def _terminology_reverse() -> dict[str, int]:
    """terminology.item_overrides 反向索引 {覆盖名: type_id}（基础矿物 34-40 等不在 item 表）。

    重名时保留注册顺序里**首个**出现的 type_id，与逐行遍历 overrides 的语义一致。
    """
    term._ensure()
    overrides = term._data.get("item_overrides") or {}
    reverse: dict[str, int] = {}
    for tid_str, override_name in overrides.items():
        reverse.setdefault(str(override_name), int(tid_str))
    return reverse


def _exact_type_id(conn: sqlite3.Connection | sqlite3.Cursor, name: str) -> int | None:
    """item 表精确匹配 zh_name / en_name，未命中返回 None。"""
    row = conn.execute("SELECT type_id FROM item WHERE zh_name = ? OR en_name = ? LIMIT 1", (name, name)).fetchone()
    return int(row[0]) if row else None


def _exact_type_ids_batch(
    conn: sqlite3.Connection | sqlite3.Cursor,
    names: list[str],
) -> dict[str, int]:
    """一次 IN 查询批量精确匹配 {名字: type_id}。

    与逐行 `_exact_type_id` 同语义：按 type_id 升序取每个名字的首个命中
    （无索引时 SQLite 走主键顺序，等价于逐行 ``LIMIT 1`` 拿到的行）。
    调用方须传入去重后的名字，且只对未命中者再走模糊回退。
    """
    uniq = list(dict.fromkeys(n for n in names if n))
    found: dict[str, int] = {}
    for i in range(0, len(uniq), _NAME_CHUNK):
        chunk = uniq[i : i + _NAME_CHUNK]
        chunk_set = set(chunk)
        ph = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT zh_name, en_name, type_id FROM item WHERE zh_name IN ({ph}) OR en_name IN ({ph})",
            [*chunk, *chunk],
        ).fetchall()
        best: dict[str, int] = {}
        for zh, en, tid in rows:
            for key in (zh, en):
                if key in chunk_set and (key not in best or int(tid) < best[key]):
                    best[key] = int(tid)
        found.update(best)
    return found


def _like_type_id(conn: sqlite3.Connection | sqlite3.Cursor, name: str) -> int | None:
    """LIKE 模糊匹配（含引号归一化回退），未命中返回 None。

    item 表无 zh_name/en_name 索引时 LIKE 是全表扫描 —— 各调用方一律先跑精确匹配，
    只对未命中的少数行调用本函数。
    """
    _ensure_name_indexes(conn)
    like = f"%{name}%"
    row = conn.execute(
        "SELECT type_id FROM item WHERE zh_name LIKE ? OR en_name LIKE ? LIMIT 1", (like, like)
    ).fetchone()
    if row:
        return int(row[0])
    # 引号归一化（ASCII/弯引号 → % 通配）
    fuzzy = re.sub(r"[\"\"'']+", "%", name)
    if fuzzy != name:
        row = conn.execute(
            "SELECT type_id FROM item WHERE zh_name LIKE ? OR en_name LIKE ? LIMIT 1",
            (f"%{fuzzy}%", f"%{fuzzy}%"),
        ).fetchone()
        if row:
            return int(row[0])
    return None


def search_item_type_id(conn: sqlite3.Connection | sqlite3.Cursor, name: str) -> int | None:
    """名称→type_id：精确 → terminology 反向 → LIKE 模糊 → 引号归一化 LIKE。

    未命中返回 None。供剪贴板解析（库存修正 / 购买记录导入）使用。

    注意：基础矿物（type_id 34-40）不在 item 表，仅在 terminology.json 注册，
    因此 terminology 反向必须在 LIKE 之前，避免「三钛合金」被 LIKE 误匹配到
    「三钛合金条」等名称含子串的无关物品。

    批量场景（整仓剪贴板导入）改用 `search_item_type_ids_batch`：逐行 LIKE 是全表扫描，
    几百行就是秒级。
    """
    name = name.strip()
    if not name:
        return None
    hit = _exact_type_id(conn, name)
    if hit is not None:
        return hit
    reverse = _terminology_reverse().get(name)
    if reverse is not None:
        return reverse
    return _like_type_id(conn, name)


def search_item_type_ids_batch(
    conn: sqlite3.Connection | sqlite3.Cursor,
    names: list[str],
) -> dict[str, int | None]:
    """批量名称→type_id，键为原样传入的名字（含重复项与空串）。

    结果与逐行调用 `search_item_type_id` 完全一致（四级回退同序），
    但精确匹配合并成几次 IN 查询，LIKE 只对仍未命中的行执行。
    """
    stripped = [n.strip() for n in names]
    result: dict[str, int | None] = dict.fromkeys(set(names), None)
    exact = _exact_type_ids_batch(conn, stripped)
    reverse = _terminology_reverse()
    pending: list[str] = []
    for raw, name in zip(names, stripped, strict=True):
        if not name:
            continue
        hit = exact.get(name)
        if hit is None:
            hit = reverse.get(name)
        if hit is not None:
            result[raw] = hit
        else:
            pending.append(name)
    for name in pending:
        result.setdefault(name, None)
    # 模糊回退按去重后的名字跑一次，再回填到所有同名的原始键
    fallback: dict[str, int | None] = {}
    for name in dict.fromkeys(pending):
        fallback[name] = _like_type_id(conn, name)
    for raw, name in zip(names, stripped, strict=True):
        if name and result.get(raw) is None and fallback.get(name) is not None:
            result[raw] = fallback[name]
    return result


def resolve_item_name(conn: sqlite3.Connection | sqlite3.Cursor, type_id: int) -> str:
    """统一物品名称解析：term override → item 表 → str(id)。

    Args:
        conn: reference.db 的数据库连接（Connection 或 Cursor，均支持 execute/fetchone）
        type_id: 物品 type_id

    Returns:
        物品名称（优先中文，其次英文，最后回退到字符串 id）
    """
    override = term.item_override(type_id)
    if override is not None:
        return override
    cur = conn.execute(
        "SELECT zh_name, en_name FROM item WHERE type_id = ?",
        (type_id,),
    )
    row = cur.fetchone()
    if row:
        name: str = row[0] or row[1]
        if name:
            return name
    return str(type_id)


def resolve_item_names_batch(
    conn: sqlite3.Connection,
    type_ids: list[int],
) -> dict[int, str]:
    """批量查询物品名称，减少数据库往返。

    Args:
        conn: reference.db 的连接
        type_ids: 需要查询的 type_id 列表

    Returns:
        {type_id: name, ...}
    """
    if not type_ids:
        return {}

    result: dict[int, str] = {}
    remaining: list[int] = []

    # 先查 terminology.json 覆盖
    for tid in type_ids:
        override = term.item_override(tid)
        if override is not None:
            result[tid] = override
        else:
            remaining.append(tid)

    if not remaining:
        return result

    # 剩下的查数据库
    placeholders = ",".join("?" * len(remaining))
    cur = conn.execute(
        f"SELECT type_id, zh_name, en_name FROM item WHERE type_id IN ({placeholders})",
        remaining,
    )
    for row in cur.fetchall():
        result[row[0]] = row[1] or row[2]
    # 未查到的用 str(id)
    for tid in remaining:
        if tid not in result:
            result[tid] = str(tid)
    return result


def mat_name(mat_id: int, conn: sqlite3.Connection) -> str:
    """查询材料名称，优先查 item 表，基础矿物走 terminology.json 覆盖。"""
    return resolve_item_name(conn, mat_id)


def resolve_system_name(conn: sqlite3.Connection, solar_system_id: int) -> str:
    """星系显示名：中文 (英文)。中文优先 terminology.system_names，fallback 英文 → str(id)。

    Args:
        conn: reference.db 的数据库连接
        solar_system_id: 星系 solar_system_id

    Returns:
        如 "吉他 (Jita)"；未注册中文且表无英文名时回退字符串 id。
    """
    row = conn.execute(
        "SELECT solar_system_name FROM solar_system WHERE solar_system_id = ?",
        (solar_system_id,),
    ).fetchone()
    en = row[0] if row and row[0] else ""
    zh = term.system_name(en) if en else None
    if zh:
        return f"{zh} ({en})"
    return en or str(solar_system_id)


def resolve_system_names_batch(
    conn: sqlite3.Connection,
    solar_system_ids: list[int],
) -> dict[int, str]:
    """批量查询星系显示名（中英对照），减少数据库往返。"""
    if not solar_system_ids:
        return {}
    placeholders = ",".join("?" * len(solar_system_ids))
    rows = conn.execute(
        f"SELECT solar_system_id, solar_system_name FROM solar_system WHERE solar_system_id IN ({placeholders})",
        solar_system_ids,
    ).fetchall()
    result: dict[int, str] = {}
    for sid, en in rows:
        sid = int(sid)
        en = en or ""
        zh = term.system_name(en) if en else None
        result[sid] = f"{zh} ({en})" if zh else (en or str(sid))
    return result


def resolve_system_display_names_batch(solar_system_ids: list[int]) -> dict[int, str]:
    """批量查询星系显示名；异常返回空 dict。"""
    if not solar_system_ids:
        return {}
    try:
        from core.container import get_container

        with get_container().db.connect("ref") as conn:
            return resolve_system_names_batch(conn, solar_system_ids)
    except Exception:
        return {}
