"""
仓库页面 — 蓝图导入后台线程
"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container


class _BlueprintImportWorker(QThread):
    """后台线程：解析剪贴板 → 比对库 → 替换写入"""

    progress = Signal(int, int, str)
    finished = Signal(int, int, int)  # added, removed, total

    def __init__(self, raw: str, hangar_id: int):
        super().__init__()
        self._raw = raw
        self._hangar_id = hangar_id

    def run(self):
        # 1. 解析剪贴板
        pasted: list[tuple] = []  # (bpid, is_bpo, me, te, runs)
        with get_container().db.connect("ref", "bp") as conn:
            c = conn.cursor()
            lines = [ln for ln in self._raw.split("\n") if ln.strip()]
            total = len(lines)
            for i, line in enumerate(lines):
                cols = line.split("\t")
                if len(cols) < 5:
                    continue
                name_part = cols[0].strip().rstrip("*")
                try:
                    me = int(cols[1].strip())
                    te = int(cols[2].strip())
                    runs = int(cols[3].strip())
                except ValueError:
                    continue
                is_bpo = "原图" in cols[4].strip() or "原本" in cols[4].strip()
                bpid = self._lookup_bpid(c, name_part, cols)
                if not bpid:
                    continue
                pasted.append((bpid, int(is_bpo), me, te, runs))
                if i % 100 == 0:
                    self.progress.emit(i, total, f"解析中... {i}/{total}")

        # 2. 读取库中现有蓝图（保留 id 用于精确删除）
        existing_map: dict[tuple, int] = {}  # (bpid, is_bpo, me, te, runs) → row_id
        with get_container().db.connect("user") as uc:
            c = uc.cursor()
            c.execute(
                "SELECT id, blueprint_type_id, is_bpo, me_level, te_level, runs"
                " FROM user_blueprints WHERE hangar_id = ?",
                (self._hangar_id,),
            )
            for row in c.fetchall():
                existing_map[(row[1], row[2], row[3], row[4], row[5])] = row[0]

        # 3. 比对变化（用 list 比较，保留重复数量）
        from collections import Counter

        pasted_counter = Counter(pasted)
        existing_counter = Counter(existing_map.keys())
        all_keys = set(pasted_counter) | set(existing_counter)

        to_add: list[tuple] = []
        to_remove: list[int] = []
        added = 0
        removed = 0
        for key in all_keys:
            p_cnt = pasted_counter.get(key, 0)
            e_cnt = existing_counter.get(key, 0)
            if p_cnt > e_cnt:
                # 需要新增 p_cnt - e_cnt 条
                to_add.extend([key] * (p_cnt - e_cnt))
                added += p_cnt - e_cnt
            elif p_cnt < e_cnt:
                # 需要删除 e_cnt - p_cnt 条
                # 找到所有匹配 key 的 row_id
                for ek, rid in existing_map.items():
                    if ek == key:
                        to_remove.append(rid)
                        if len(to_remove) >= e_cnt - p_cnt + removed:
                            break
                removed += e_cnt - p_cnt

        # 4. 无变化则跳过
        if added == 0 and removed == 0:
            self.finished.emit(0, 0, len(pasted))
            return

        # 5. 增量更新
        with get_container().db.connect("user") as uc:
            c = uc.cursor()
            for row_id in to_remove:
                c.execute("DELETE FROM user_blueprints WHERE id = ?", (row_id,))
            uc.commit()

            for i, bp in enumerate(to_add):
                c.execute(
                    "INSERT INTO user_blueprints"
                    " (hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity)"
                    " VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (self._hangar_id, bp[0], bp[1], bp[2], bp[3], bp[4]),
                )
                if i % 200 == 0 or i == len(to_add) - 1:
                    uc.commit()
                    self.progress.emit(i + 1, len(to_add), f"写入中... {i + 1}/{len(to_add)}")
            uc.commit()

        self.finished.emit(added, removed, len(pasted))

    def _lookup_bpid(self, c, name_part, cols):
        # 1. 精确匹配
        c.execute("SELECT type_id FROM item WHERE zh_name = ? OR en_name = ? LIMIT 1", (name_part, name_part))
        r = c.fetchone()
        if r:
            return r[0]
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
