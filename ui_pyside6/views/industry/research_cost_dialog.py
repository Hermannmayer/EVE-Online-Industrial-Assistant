"""研究分析对话框 — 只读展示一张蓝图的拷贝 / 发明 / 效率研究成本。

与 CostBreakdownDialog 的区别：后者绑定的是**计划行**（按行的 activity 分派明细），
本对话框绑定的是**蓝图**（还没建计划时先看看划不划算）。

三类蓝图三种形态：
    T1 BPO          → 拷贝成本（mpl、时长、材料、单份/批量） + 可发明出的 T2 蓝图列表
    T2/T3 蓝图       → 发明成本（来源 T1、产物下拉、解码器下拉、成功率、单位成本）
    反应公式         → 提示不可拷贝/发明/研究
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from domain.research import DECRYPTORS, invention_output_me_te, invention_output_runs
from services.plan_metrics import copying_plan_cost, invention_plan_cost
from services.research_plans import invention_base_runs, resolve_invention_source


def _fmt_isk(v: float) -> str:
    return f"{v:,.0f}" if v else "—"


def _fmt_duration(seconds: float) -> str:
    s = int(seconds or 0)
    if s <= 0:
        return "—"
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}d{h}h{m}m" if d else (f"{h}h{m}m" if h else f"{m}m")


class ResearchCostDialog(QDialog):
    """研究分析（只读）。"""

    def __init__(self, db, blueprint_type_id: int, blueprint_name: str, *, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"研究分析 — {blueprint_name}")
        self.setMinimumSize(620, 520)
        self._db = db
        self._bp_id = int(blueprint_type_id)
        self._name = blueprint_name
        self._labels: list[QLabel] = []

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._form = QFormLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        outer.addWidget(box)

        self._build()

        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    # ── 构建 ──

    def _row(self, label: str, value: str, *, accent: bool = False) -> None:
        lbl = QLabel(value)
        lbl.setWordWrap(True)
        lbl.setObjectName("accent" if accent else "plain")
        self._labels.append(lbl)
        self._form.addRow(label, lbl)

    def _build(self) -> None:
        with self._db.connect("bp", "ref") as conn:
            kind = self._classify(conn)
            if kind == "reaction":
                self._row("说明", "反应公式不可拷贝、发明或研究，只能直接跑反应作业。")
                return
            if kind == "invention":
                self._build_invention(conn)
            else:
                self._build_copying(conn)

    def _classify(self, conn) -> str:
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

    def _prices(self, conn, type_ids: list[int]) -> dict[int, float]:
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

    def _mats(self, conn, bp_id: int, activity: str) -> list[tuple[int, int]]:
        from services.plan_job_kinds import material_activity

        return [
            (int(r[0]), int(r[1] or 0))
            for r in conn.execute(
                "SELECT material_type_id, quantity FROM blueprint_materials "
                "WHERE blueprint_type_id = ? AND activity = ?",
                (bp_id, material_activity(activity)),
            ).fetchall()
        ]

    def _material_lines(self, conn, mats: list[tuple[int, int]], prices: dict[int, float], n: int) -> str:
        if not mats:
            return "（无材料）"
        lines = []
        for mid, qty in mats:
            row = conn.execute("SELECT zh_name FROM item WHERE type_id = ?", (mid,)).fetchone()
            nm = (row[0] if row else None) or str(mid)
            total = qty * n
            lines.append(f"{nm} ×{total:,} @ {prices.get(mid, 0):,.0f} = {total * prices.get(mid, 0):,.0f}")
        return "\n".join(lines)

    def _build_copying(self, conn) -> None:
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
        from services.scoring_service import get_system_cost_index

        sci = float(get_system_cost_index(None, "copying", _db=self._db) or 0.0)
        cost = copying_plan_cost(materials=mats, prices=prices, sci=sci, total_copy_runs=limit, copies=1)

        self._row("类型", "T1 / 可拷贝蓝图")
        self._row("每份流程上限", f"{limit:,}（蓝图拷贝活动的最大授权流程）")
        self._row("单次拷贝时长", _fmt_duration(base_time))
        self._row("拷贝材料", self._material_lines(conn, mats, prices, limit))
        self._row("材料成本", f"{_fmt_isk(cost['material_cost'])} ISK")
        self._row("安装费", f"{_fmt_isk(cost['fee'])} ISK（含 SCI {sci:g}）")
        self._row("单份总成本", f"{_fmt_isk(cost['total_cost'])} ISK（{limit:,} 流程）", accent=True)

        # 可发明出的 T2（本蓝图作为 T1 时）
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

    def _build_invention(self, conn) -> None:
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
        from services.scoring_service import get_system_cost_index

        sci = float(get_system_cost_index(None, "invention", _db=self._db) or 0.0)

        rows: list[str] = []
        for oc in src["outcomes"]:
            bp_id = int(oc["blueprint_type_id"])
            base_runs = invention_base_runs(conn, bp_id, t1_bp)
            cost = invention_plan_cost(
                base_probability=float(oc["base_probability"]),
                materials=mats,
                prices=prices,
                sci=sci,
                base_runs=base_runs,
                output_runs_needed=base_runs,
            )
            mark = "← 本蓝图" if bp_id == self._bp_id else ""
            rows.append(
                f"{oc['name']}{mark}：基础 {(oc['base_probability'] or 0) * 100:.0f}%"
                f" / 产出 {cost['runs_per_bpc']} 流程 / 单位成本 {_fmt_isk(cost['bpc_unit_cost'])}"
            )
        self._row("可能产物", "\n".join(rows) if rows else "—")

        base_runs = invention_base_runs(conn, self._bp_id, t1_bp)
        self._row("数据核心（每尝试）", self._material_lines(conn, mats, prices, 1))
        self._row("产出 ME/TE（无解码器）", "ME {} / TE {}".format(*invention_output_me_te(None)))

        dec_lines = []
        for tid, d in DECRYPTORS.items():
            if prices.get(tid):
                out_runs = invention_output_runs(base_runs, d)
                me, te = invention_output_me_te(d)
                dec_lines.append(
                    f"{d.name}：×{d.prob_mult:g} / {out_runs} 流程 / ME{me}-TE{te} / {_fmt_isk(prices[tid])}"
                )
        self._row("解码器选项", "\n".join(dec_lines) if dec_lines else "（无价格数据）")

    def _on_theme_changed(self) -> None:
        for lbl in self._labels:
            color = theme.ACCENT_CYAN if lbl.objectName() == "accent" else theme.TEXT_PRIMARY
            lbl.setStyleSheet(f"color: {color}; font-size: {theme.fs(12)}px;")
        for lbl in self.findChildren(QLabel):
            if lbl in self._labels:
                continue
            lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.fs(12)}px;")
        self.setCursor(Qt.CursorShape.ArrowCursor)
