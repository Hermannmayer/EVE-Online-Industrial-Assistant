"""研究分析对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/research_cost_dialog.py`：
只读展示一张蓝图的拷贝/发明成本明细（材料清单、安装费、单份总成本、
可发明产物、解码器选项…）。

**判定与计算逻辑一字未改**（`_classify` / `_mats` / `_prices` / `_material_lines` /
`_build_copying` / `_build_invention` 原样搬过来），只是把「往 QFormLayout 塞 QLabel」
换成「攒成一个 `fields` 列表」。展示走通用的 `FormListDialog.qml`。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["ResearchCostBridge", "ResearchCostQmlDialog"]

_QML_FILE = "dialogs/FormListDialog.qml"


def _fmt_isk(value: float) -> str:
    return f"{value:,.0f}" if value else "—"


def _fmt_duration(seconds: float) -> str:
    total = int(seconds or 0)
    if total <= 0:
        return "—"
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}d{h}h{m}m" if d else (f"{h}h{m}m" if h else f"{m}m")


class ResearchCostBridge(DialogBridge):
    """研究分析的 QML 后端。`db` 与蓝图 id 由调用方给（与 Widgets 版同参）。"""

    fieldsChanged = Signal()

    def __init__(self, db: Any, blueprint_type_id: int, blueprint_name: str) -> None:
        super().__init__()
        self._db = db
        self._bp_id = int(blueprint_type_id)
        self._name = str(blueprint_name)
        self._fields: list[dict] = []
        self.set_title(f"研究分析 — {blueprint_name}")

    #: [{label, value, strong}] —— strong = 强调行（截图里用主色）
    fields = Property(list, lambda self: list(self._fields), notify=fieldsChanged)

    def _row(self, label: str, value: str, *, accent: bool = False) -> None:
        self._fields.append({"label": label, "value": value, "strong": accent})

    @Slot()
    def reload(self) -> None:
        self._fields = []
        try:
            # 必须带上 mkt：`_prices` 查的是 `market_prices`，它只存在于 market.db。
            # 原 Widgets 版写的是 `connect("bp", "ref")`，于是**任何非反应蓝图都会**
            # 抛 `no such table: market_prices` —— 这里顺带修掉。
            with self._db.connect("bp", "ref", "mkt") as conn:
                kind = self._classify(conn)
                if kind == "reaction":
                    self._row("说明", "反应公式不可拷贝、发明或研究，只能直接跑反应作业。")
                elif kind == "invention":
                    self._build_invention(conn)
                else:
                    self._build_copying(conn)
        except Exception:
            from core.logger import log

            log.exception("研究分析加载失败 bp=%s", self._bp_id)
            self._row("说明", "读取失败，详见日志。")
        self.fieldsChanged.emit()

    # ── 以下与原 Widgets 版逐行一致 ────────────────────────────

    def _classify(self, conn: Any) -> str:
        from services.research_plans import resolve_invention_source

        if resolve_invention_source(conn, self._bp_id) is not None:
            return "invention"
        row = conn.execute(
            "SELECT 1 FROM blueprint_activities WHERE blueprint_type_id = ? AND activity = 'reaction' LIMIT 1",
            (self._bp_id,),
        ).fetchone()
        if row:
            return "reaction"
        row = conn.execute(
            "SELECT 1 FROM blueprint_activities WHERE blueprint_type_id = ? AND activity = 'copying' LIMIT 1",
            (self._bp_id,),
        ).fetchone()
        return "copying" if row else "unknown"

    @staticmethod
    def _prices(conn: Any, type_ids: list[int]) -> dict[int, float]:
        prices: dict[int, float] = {}
        for tid in {t for t in type_ids if t}:
            row = conn.execute(
                "SELECT adjusted_price, sell_price, buy_price FROM market_prices "
                "WHERE type_id = ? ORDER BY (adjusted_price > 0) DESC, fetch_time DESC LIMIT 1",
                (tid,),
            ).fetchone()
            if row:
                prices[tid] = float(row[0] or 0) or float(row[1] or 0) or float(row[2] or 0)
        return prices

    @staticmethod
    def _mats(conn: Any, bp_id: int, activity: str) -> list[tuple[int, int]]:
        from services.plan_job_kinds import material_activity

        return [
            (int(r[0]), int(r[1] or 0))
            for r in conn.execute(
                "SELECT material_type_id, quantity FROM blueprint_materials "
                "WHERE blueprint_type_id = ? AND activity = ?",
                (bp_id, material_activity(activity)),
            ).fetchall()
        ]

    @staticmethod
    def _material_lines(conn: Any, mats: list[tuple[int, int]], prices: dict[int, float], n: int) -> str:
        if not mats:
            return "（无材料）"
        lines = []
        for mid, qty in mats:
            row = conn.execute("SELECT zh_name FROM item WHERE type_id = ?", (mid,)).fetchone()
            name = (row[0] if row else None) or str(mid)
            total = qty * n
            lines.append(f"{name} ×{total:,} @ {prices.get(mid, 0):,.0f} = {total * prices.get(mid, 0):,.0f}")
        return "\n".join(lines)

    def _build_copying(self, conn: Any) -> None:
        from services.plan_metrics import copying_plan_cost
        from services.scoring_service import get_system_cost_index

        act = conn.execute(
            "SELECT time, max_production_limit FROM blueprint_activities "
            "WHERE blueprint_type_id = ? AND activity = 'copying' LIMIT 1",
            (self._bp_id,),
        ).fetchone()
        if act is None:
            self._row("说明", "该蓝图没有拷贝活动（既非发明产物，也不可拷贝）。")
            return
        base_time, limit = int(act[0] or 0), max(1, int(act[1] or 1))
        mats = self._mats(conn, self._bp_id, "copying")
        prices = self._prices(conn, [m for m, _q in mats])
        sci = float(get_system_cost_index(None, "copying", _db=self._db) or 0.0)
        cost = copying_plan_cost(materials=mats, prices=prices, sci=sci, total_copy_runs=limit, copies=1)

        self._row("类型", "T1 / 可拷贝蓝图")
        self._row("每份流程上限", f"{limit:,}（蓝图拷贝活动的最大授权流程）")
        self._row("单次拷贝时长", _fmt_duration(base_time))
        self._row("拷贝材料", self._material_lines(conn, mats, prices, limit))
        self._row("材料成本", f"{_fmt_isk(cost['material_cost'])} ISK")
        self._row("安装费", f"{_fmt_isk(cost['fee'])} ISK（含 SCI {sci:g}）")
        self._row("单份总成本", f"{_fmt_isk(cost['total_cost'])} ISK（{limit:,} 流程）", accent=True)

        outs = conn.execute(
            "SELECT product_type_id, probability FROM blueprint_products "
            "WHERE activity = 'invention' AND blueprint_type_id = ? ORDER BY product_type_id",
            (self._bp_id,),
        ).fetchall()
        if outs:
            lines = []
            for pid, prob in outs:
                row = conn.execute("SELECT zh_name FROM item WHERE type_id = ?", (pid,)).fetchone()
                lines.append(f"{(row[0] if row else None) or pid}（基础成功率 {(prob or 0) * 100:.0f}%）")
            self._row("可发明出", "\n".join(lines))

    def _build_invention(self, conn: Any) -> None:
        from domain.research import DECRYPTORS, invention_output_me_te, invention_output_runs
        from services.plan_metrics import invention_plan_cost
        from services.research_plans import invention_base_runs, resolve_invention_source
        from services.scoring_service import get_system_cost_index

        src = resolve_invention_source(conn, self._bp_id)
        if src is None:
            self._row("说明", "未找到发明来源。")
            return
        t1_bp = int(src["t1_blueprint_type_id"])
        self._row("类型", "T2/T3 蓝图（由发明产出）")
        self._row("发明来源", src["t1_name"])
        self._row("T1 拷贝上限", f"{src['t1_copy_limit']:,} 流程 / 份")

        mats = self._mats(conn, t1_bp, "invention")
        prices = self._prices(conn, [m for m, _q in mats] + list(DECRYPTORS))
        sci = float(get_system_cost_index(None, "invention", _db=self._db) or 0.0)

        rows: list[str] = []
        for oc in src["outcomes"]:
            bid = int(oc["blueprint_type_id"])
            base_runs = invention_base_runs(conn, bid, t1_bp)
            cost = invention_plan_cost(
                base_probability=float(oc["base_probability"]),
                materials=mats,
                prices=prices,
                sci=sci,
                base_runs=base_runs,
                output_runs_needed=base_runs,
            )
            mark = "← 本蓝图" if bid == self._bp_id else ""
            rows.append(
                f"{oc['name']}{mark}：基础 {(oc['base_probability'] or 0) * 100:.0f}%"
                f" / 产出 {cost['runs_per_bpc']} 流程 / 单位成本 {_fmt_isk(cost['bpc_unit_cost'])}"
            )
        self._row("可能产物", "\n".join(rows) if rows else "—")

        base_runs = invention_base_runs(conn, self._bp_id, t1_bp)
        self._row("数据核心（每尝试）", self._material_lines(conn, mats, prices, 1))
        self._row("产出 ME/TE（无解码器）", "ME {} / TE {}".format(*invention_output_me_te(None)))

        dec_lines = []
        for tid, decryptor in DECRYPTORS.items():
            if prices.get(tid):
                out_runs = invention_output_runs(base_runs, decryptor)
                me, te = invention_output_me_te(decryptor)
                dec_lines.append(
                    f"{decryptor.name}：×{decryptor.prob_mult:g} / {out_runs} 流程 / "
                    f"ME{me}-TE{te} / {_fmt_isk(prices[tid])}"
                )
        self._row("解码器选项", "\n".join(dec_lines) if dec_lines else "（无价格数据）")


class ResearchCostQmlDialog(QmlDialog):
    """QML 版「研究分析」。构造签名与 Widgets 版一致（db / bp_id / name / parent）。"""

    def __init__(self, db: Any, blueprint_type_id: int, blueprint_name: str, *, parent: Any = None) -> None:
        bridge = ResearchCostBridge(db, blueprint_type_id, blueprint_name)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(680, 560))
        bridge.reload()
