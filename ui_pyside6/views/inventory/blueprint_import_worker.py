"""
仓库页面 — 蓝图导入后台线程
"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container


def parse_blueprint_clipboard(raw: str, conn) -> list[dict]:
    """解析 EVE 蓝图剪贴板 → [{blueprint_type_id, name, is_bpo, me, te, runs}]

    纯函数（依赖传入的 ref/bp 连接做名称→蓝图 ID 解析）。
    行格式（Tab 分隔，与游戏全选复制一致）:
        <蓝图名或产物名>\t<ME>\t<TE>\t<流程数>\t<原图/拷贝>
    """
    from collections import Counter

    lines = [ln for ln in raw.split("\n") if ln.strip()]
    seen: Counter = Counter()  # (bpid, is_bpo, me, te, runs) → 数量（同属性多张）
    names: dict[int, str] = {}
    for line in lines:
        cols = line.split("\t")
        if len(cols) < 5:
            continue
        name_part = cols[0].strip().rstrip("*")
        if not name_part:
            continue
        try:
            me = int(cols[1].strip())
            te = int(cols[2].strip())
            runs = int(cols[3].strip())
        except ValueError:
            continue
        is_bpo = "原图" in cols[4].strip() or "原本" in cols[4].strip()
        bpid = _lookup_bpid(conn, name_part)
        if not bpid:
            continue
        key = (bpid, is_bpo, me, te, runs)
        seen[key] += 1
        if bpid not in names:
            names[bpid] = _lookup_name(conn, bpid, name_part)
    return [
        {
            "blueprint_type_id": k[0],
            "is_bpo": k[1],
            "me": k[2],
            "te": k[3],
            "runs": k[4],
            "qty": q,
            "name": names.get(k[0], ""),
        }
        for k, q in seen.items()
    ]


def _lookup_bpid(c, name_part):
    """蓝图名/产物名 → blueprint_type_id（先精确匹配蓝图，再产物反查）"""
    # 1. 精确匹配 item 表，且必须是制造蓝图
    c.execute("SELECT type_id FROM item WHERE zh_name = ? OR en_name = ? LIMIT 1", (name_part, name_part))
    r = c.fetchone()
    if r:
        tid = r[0]
        c.execute(
            "SELECT 1 FROM blueprint_products WHERE blueprint_type_id = ? AND activity = 'manufacturing' LIMIT 1",
            (tid,),
        )
        if c.fetchone():
            return tid
        # 命中的是产品行 → 从产品反查制造蓝图
        c.execute(
            "SELECT blueprint_type_id FROM blueprint_products"
            " WHERE product_type_id = ? AND activity = 'manufacturing' LIMIT 1",
            (tid,),
        )
        r2 = c.fetchone()
        if r2:
            return r2[0]
    # 2. 产物反查：蓝图名替换 "蓝图 X" → " X" → 产物名 → 制造蓝图
    for suffix in ("蓝图 II", "蓝图 I", "蓝图 III"):
        if suffix in name_part:
            prod_name = name_part.replace(suffix, suffix.replace("蓝图", ""))
            c.execute("SELECT type_id FROM item WHERE zh_name = ? LIMIT 1", (prod_name,))
            r = c.fetchone()
            if r:
                c.execute(
                    "SELECT blueprint_type_id FROM blueprint_products"
                    " WHERE product_type_id = ?"
                    " AND activity = 'manufacturing' LIMIT 1",
                    (r[0],),
                )
                r2 = c.fetchone()
                if r2:
                    return r2[0]
            break  # 只尝试第一个匹配的后缀
    return None


def _lookup_name(c, bpid: int, fallback: str) -> str:
    """蓝图类型 ID → 显示名（找不到用剪贴板名兜底）"""
    c.execute("SELECT zh_name FROM item WHERE type_id = ?", (bpid,))
    r = c.fetchone()
    return (r[0] or fallback) if r else fallback


def build_blueprint_changes(
    before: dict[tuple, int],
    after: dict[tuple, int],
    names: dict[int, str],
) -> list[dict]:
    """对比导入前后蓝图库，返回变化行列表（对齐材料 compute_import_diff）。

    Args:
        before: 导入前 {(bpid, is_bpo, me, te, runs): 数量}
        after: 导入后 {(bpid, is_bpo, me, te, runs): 数量}
        names: 蓝图名映射 {bpid: 显示名}

    Returns:
        [{name, attr, qty_before, qty_after, qty_delta}]，仅含数量变化的行。
    """
    result: list[dict] = []
    all_keys = set(before) | set(after)
    for key in sorted(all_keys):
        b_qty = before.get(key, 0)
        a_qty = after.get(key, 0)
        if b_qty == a_qty:
            continue
        kind = "原图" if key[1] else "拷贝"
        result.append(
            {
                "name": names.get(key[0], f"ID:{key[0]}"),
                "attr": f"{kind}  ME{key[2]}  TE{key[3]}  流程{key[4]}",
                "qty_before": b_qty,
                "qty_after": a_qty,
                "qty_delta": a_qty - b_qty,
            }
        )
    return result


class _BlueprintImportWorker(QThread):
    """后台线程：解析剪贴板 → 比对库 → 产出 diff（增/删/不变）供预览确认"""

    progress = Signal(int, int, str)
    finished = Signal(
        list
    )  # diff rows: [{name, blueprint_type_id, is_bpo, me, te, runs, qty, existing_qty, row_id, delta, final}]

    def __init__(self, raw: str, hangar_id: int, parent=None):
        super().__init__(parent)
        self._raw = raw
        self._hangar_id = hangar_id

    def run(self):
        # 1. 解析剪贴板
        with get_container().db.connect("ref", "bp") as conn:
            c = conn.cursor()
            parsed = parse_blueprint_clipboard(self._raw, c)

        # 2. 读取库中现有蓝图（保留 id 用于精确删除）
        existing: dict[tuple, list[int]] = {}  # (bpid, is_bpo, me, te, runs) → [row_ids]（同属性多张）
        with get_container().db.connect("user") as uc:
            c = uc.cursor()
            c.execute(
                "SELECT id, blueprint_type_id, is_bpo, me_level, te_level, runs"
                " FROM user_blueprints WHERE hangar_id = ?",
                (self._hangar_id,),
            )
            for row in c.fetchall():
                key = (row[1], bool(row[2]), row[3], row[4], row[5])
                existing.setdefault(key, []).append(row[0])

        # 3. 比对变化（保留重复数量）
        from collections import Counter

        pasted = Counter(
            {(r["blueprint_type_id"], bool(r["is_bpo"]), r["me"], r["te"], r["runs"]): r["qty"] for r in parsed}
        )
        existing_cnt = Counter({k: len(v) for k, v in existing.items()})
        all_keys = set(pasted) | set(existing_cnt)
        names = {r["blueprint_type_id"]: r["name"] for r in parsed}

        diff: list[dict] = []
        for key in sorted(all_keys):
            p_cnt = pasted.get(key, 0)
            e_cnt = existing_cnt.get(key, 0)
            diff.append(
                {
                    "blueprint_type_id": key[0],
                    "is_bpo": key[1],
                    "me": key[2],
                    "te": key[3],
                    "runs": key[4],
                    "qty": p_cnt,  # 剪贴板数量
                    "existing_qty": e_cnt,  # 库中数量
                    "row_ids": existing.get(key, []),
                    "name": names.get(key[0], ""),
                }
            )
        self.finished.emit(diff)


def apply_blueprint_diff(diff_rows: list[dict], hangar_id: int, mode: str = "full") -> tuple[int, int]:
    """按勾选行应用增删，返回 (added, removed)。

    Args:
        diff_rows: [{blueprint_type_id, is_bpo, me, te, runs, target_qty, row_ids}]
        mode: "full" 全量同步（target_qty 为最终目标，增删按差额）
              "incremental" 增量累加（target_qty = 现有+剪贴板，只增不减）
    """
    added = 0
    removed = 0
    with get_container().db.connect("user") as uc:
        from services import inventory_manager

        for row in diff_rows:
            key = (row["blueprint_type_id"], int(row["is_bpo"]), int(row["me"]), int(row["te"]), int(row["runs"]))
            target = int(row.get("target_qty", 0))
            row_ids = list(row.get("row_ids", []))
            if mode == "incremental":
                # 增量只加不减：目标 = 现有 + 剪贴板
                target = len(row_ids) + int(row.get("qty", 0))
            existing_cnt = len(row_ids)
            if target > existing_cnt:
                for _ in range(target - existing_cnt):
                    inventory_manager.add_blueprint(
                        hangar_id,
                        key[0],
                        is_bpo=bool(key[1]),
                        me_level=key[2],
                        te_level=key[3],
                        runs=key[4],
                        quantity=1,
                        conn=uc,
                    )
                    added += 1
            elif target < existing_cnt:
                # 删除多余（保留 row_ids 尾部，删前面多余的）
                for rid in row_ids[target - existing_cnt :]:
                    inventory_manager.delete_blueprint(rid, conn=uc)
                    removed += 1
        uc.commit()
    return added, removed
