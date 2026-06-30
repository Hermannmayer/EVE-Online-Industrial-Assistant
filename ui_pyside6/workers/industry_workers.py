"""工业制造 — 后台 Worker 线程"""

from PySide6.QtCore import QThread, Signal

from services.scoring import calc_manufacturing_score


class SearchWorker(QThread):
    """搜索可制造物品"""

    finished = Signal(list)

    def __init__(self, query: str, db, parent=None):
        super().__init__(parent)
        self._query = query
        self._db = db

    def run(self):
        with self._db.connect("ref") as conn:
            c = conn.cursor()
            like = f"%{self._query}%"
            c.execute(
                """
                SELECT type_id, zh_name, en_name FROM item
                WHERE en_name LIKE ? OR zh_name LIKE ?
                ORDER BY CASE WHEN en_name LIKE ? THEN 0 WHEN zh_name LIKE ? THEN 1 ELSE 2 END,
                         LENGTH(en_name), type_id
                LIMIT 30
            """,
                (like, like, f"{self._query}%", f"{self._query}%"),
            )
            rows = [{"type_id": r[0], "zh_name": r[1] or "", "en_name": r[2] or ""} for r in c.fetchall()]
            self.finished.emit(rows)


class ScoreWorker(QThread):
    """单项制造评分"""

    finished = Signal(dict)

    def __init__(
        self,
        type_id: int,
        bp_me: int,
        bp_te: int,
        mat_hub: str,
        sell_hub: str,
        tax: float,
        mat_price_type: str = "sell",
        runs: int = 1,
        parent=None,
    ):
        super().__init__(parent)
        self._tid = type_id
        self._bp_me = bp_me
        self._bp_te = bp_te
        self._mat_hub = mat_hub
        self._sell_hub = sell_hub
        self._tax = tax
        self._mat_price_type = mat_price_type
        self._runs = runs

    def run(self):
        result = calc_manufacturing_score(
            type_id=self._tid,
            char_config={"skills": {"工业理论": 5, "高级工业理论": 5}},
            bp_me=self._bp_me,
            bp_te=self._bp_te,
            mat_source_hub=self._mat_hub,
            sell_hub=self._sell_hub,
            facility_tax_pct=self._tax,
            price_type_mat=self._mat_price_type,
            price_type_prod="sell",
        )
        self.finished.emit(result)


class RankWorker(QThread):
    """批量评分所有可制造物品"""

    progress = Signal(int, int)
    result = Signal(list)
    done = Signal(float)

    def __init__(
        self,
        mat_hub: str,
        sell_hub: str,
        mat_price_type: str,
        bp_me: int,
        bp_te: int,
        tax: float,
        db,
        parent=None,
        top_n: int | None = None,
    ):
        super().__init__(parent)
        self._mat_hub = mat_hub
        self._sell_hub = sell_hub
        self._mat_price_type = mat_price_type
        self._bp_me = bp_me
        self._bp_te = bp_te
        self._tax = tax
        self._db = db
        self._top_n = top_n

    def run(self):
        import time

        started = time.time()
        results = []

        with self._db.connect("bp", "mkt") as conn:
            c = conn.cursor()
            c.execute("""
                SELECT DISTINCT product_type_id FROM blueprint_products
                WHERE activity = 'manufacturing'
            """)
            tids = [r[0] for r in c.fetchall()]

        total = len(tids)
        for i, tid in enumerate(tids):
            r = calc_manufacturing_score(
                type_id=tid,
                char_config={"skills": {"工业理论": 5, "高级工业理论": 5}},
                bp_me=self._bp_me,
                bp_te=self._bp_te,
                mat_source_hub=self._mat_hub,
                sell_hub=self._sell_hub,
                facility_tax_pct=self._tax,
                price_type_mat=self._mat_price_type,
                price_type_prod="sell",
            )
            if not r.get("status"):
                r["_type_id"] = tid
                results.append(r)

            if (i + 1) % 100 == 0:
                self.progress.emit(i + 1, total)

        results.sort(key=lambda x: x.get("isk_per_hour", 0), reverse=True)

        # 若指定了 Top N，先排序再截断（减少后续计算量）
        if self._top_n and self._top_n < len(results):
            results = results[: self._top_n]

        self.result.emit(results)
        self.done.emit(time.time() - started)
