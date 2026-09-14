"""查看核算（成本明细）对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/cost_breakdown_dialog.py`：
左边材料清单（6 列），右边三块「标签: 值」明细（制造作业费 / 市场费用 / 汇总）。

计算口径**一字未改**：统一走 `scoring_service().calculate_plan_metrics()`（与主表
批量重算同一条路径），拆解母项时自制子项按制造价计入成本而非市场买入价
（`_compute_subitem_costs` 原地搬过来，含嵌套拆解的自底向上算法）。

与原版的两处差异：

- 原版在 `showEvent` 里加载（延迟到显示时算），这里构造即加载——QML 桥没有
  showEvent，而原版的 showEvent 也在首帧之前跑，用户感知一致。
- 原版三个 `QGroupBox` + `QFormLayout` 换成三块 `FSection` + `FFieldList`；
  「按活动类型决定哪些行可见」在 Widgets 版是 `setVisible`，这里直接**不进列表**。

加载失败仍按原版兜底：不抛异常（原版注释：showEvent 里未捕获异常会崩事件循环），
而是把错误文案写进状态栏。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal

import ui_pyside6.theme as theme
from core.container import get_container
from core.formatting import fmt_isk_exact
from services.industry_dialog_queries import get_subitem_plans, get_system_name
from ui_qml.bridge.summary_dialog import cell
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["CostBreakdownBridge", "CostBreakdownQmlDialog", "fmt_material_saving"]

_QML_FILE = "dialogs/CostBreakdownDialog.qml"

_MATERIAL_HEADERS = ["材料", "基础量", "材料减成%", "实际量", "单价", "小计"]


def fmt_material_saving(total_qty: float, base_qty: int, total_mult: int) -> str:
    """材料减成百分比：按总量计算 (1 - total_with_ME / total_without_ME)。"""
    total_base = base_qty * total_mult
    if total_base <= 0:
        return "0%"
    pct = (1 - total_qty / total_base) * 100
    return f"{pct:.1f}%"


def _color(token: str) -> str:
    return str(getattr(theme, token, "") or "") if token else ""


def _field(label: str, value: Any, token: str = "", *, strong: bool = False) -> dict:
    return {"label": label, "value": str(value), "color": _color(token), "strong": strong}


class CostBreakdownBridge(DialogBridge):
    """成本明细的 QML 后端。"""

    contentChanged = Signal()

    def __init__(
        self,
        plan_data: dict,
        char_config: dict | None = None,
        *,
        price_type_mat: str | None = None,
        price_type_prod: str | None = None,
        mat_mult: float = 1.0,
        prod_mult: float = 1.0,
    ) -> None:
        super().__init__()
        self._plan = plan_data
        self._price_type_mat = price_type_mat
        self._price_type_prod = price_type_prod
        self._mat_mult = mat_mult
        self._prod_mult = prod_mult
        # 优先使用传入的角色配置；否则按计划角色的 char_name 解析
        if char_config is not None:
            self._char_config = char_config
        else:
            plan_char = (plan_data.get("char_name") or "").strip()
            if plan_char:
                from services.char_config_resolver import resolve_char_config

                self._char_config = resolve_char_config(char_name=plan_char) or {}
            else:
                self._char_config = {}

        product_name = plan_data.get("product_name", "未知产品")
        self._status_text = "正在加载…"
        self._material_rows: list[dict] = []
        self._job_fields: list[dict] = []
        self._mkt_fields: list[dict] = []
        self._summary_fields: list[dict] = []
        self.set_title(f"核算 — {product_name}")
        self._load_data()

    # ── 只读输出 ──────────────────────────────────────────────

    materialHeaders = Property(list, lambda self: list(_MATERIAL_HEADERS), constant=True)
    materialRows = Property(list, lambda self: list(self._material_rows), notify=contentChanged)
    jobFields = Property(list, lambda self: list(self._job_fields), notify=contentChanged)
    marketFields = Property(list, lambda self: list(self._mkt_fields), notify=contentChanged)
    summaryFields = Property(list, lambda self: list(self._summary_fields), notify=contentChanged)
    statusText = Property(str, lambda self: self._status_text, notify=contentChanged)

    # ── 加载 ──────────────────────────────────────────────────

    def _load_data(self) -> None:
        type_id = self._plan.get("product_type_id")
        if not type_id:
            self._status_text = "缺少 type_id"
            self.contentChanged.emit()
            return
        try:
            self._load_data_inner(int(type_id))
        except Exception as e:
            # 构造期未捕获异常会让对话框开不出来（原版注释：会崩 Qt 事件循环）。
            from core.logger import log

            log.exception("成本明细加载失败: %s", self._plan.get("product_name"))
            self._status_text = f"⚠ 加载失败: {e}"
        self.contentChanged.emit()

    def _load_data_inner(self, type_id: int) -> None:
        runs = max(int(self._plan.get("runs", 1)), 1)
        parallels = max(int(self._plan.get("parallels", 1)), 1)
        total_mult = runs * parallels

        # 统一调用 calculate_plan_metrics()，与主表批量重算路径一致
        metrics = (
            get_container()
            .scoring_service()
            .calculate_plan_metrics(
                self._plan,
                self._char_config or {},
                price_type_mat=self._price_type_mat,
                price_type_prod=self._price_type_prod,
                mat_mult=self._mat_mult,
                prod_mult=self._prod_mult,
            )
        )

        # 拆解母项：自制子项按其制造价（材料+作业费）计入成本，而非市场买入价
        sub_cost_map: dict[int, float] = {}
        try:
            gid = self._plan.get("group_id") or self._plan.get("group_number")
            my_lvl = int(self._plan.get("sub_level") or self._plan.get("child_level") or 0)
            if gid:
                sub_cost_map = self._compute_subitem_costs(gid, my_lvl)
        except Exception:
            from core.logger import log

            log.exception("计算拆解子项成本失败: %s", self._plan.get("product_name"))
            sub_cost_map = {}

        if sub_cost_map:
            from services.scoring_service import ScoringService

            adj_mat, profit, margin, _ = ScoringService.adjust_mother_metrics(metrics, sub_cost_map, total_mult)
            material_cost = adj_mat
        else:
            material_cost = metrics.get("material_cost", 0)
            profit = metrics.get("profit", 0)
            margin = metrics.get("margin", 0)

        score = metrics.get("score", 0) or 0
        isk_per_hour = metrics.get("iskph", 0)
        hours = metrics.get("calculated_time", 0) / 3600 if metrics.get("calculated_time") else 0
        daily_output = metrics.get("daily_output", 0)

        # 统一从 calculate_plan_metrics 的结果取 breakdown/材料/状态（避免双重解析不一致，
        # 也确保明细与主表利润使用相同的机库结构加成/设施税）
        status = metrics.get("status", "")
        if status:
            tips = {"no_blueprint": "未找到蓝图", "no_price": "无价格数据", "no_materials": "无需材料"}
            self._status_text = tips.get(status, f"状态: {status}")
            return

        self._build_material_rows(metrics, total_mult, sub_cost_map)

        bd = metrics.get("breakdown", {})
        eiv = bd.get("eiv", 0) or 0
        installation_fee = bd.get("installation_fee", 0) or 0
        facility_tax_v = bd.get("facility_tax", 0) or 0
        scc = bd.get("scc_surcharge", 0) or 0
        broker_init = bd.get("broker_init", 0) or 0
        broker_relist = bd.get("broker_relist", 0) or 0
        sales_tax = bd.get("sales_tax", 0) or 0
        revenue = bd.get("revenue", 0) or 0
        sci = bd.get("sci", 0) or 0

        materials = metrics.get("materials", [])
        self._status_text = (
            f"计划设定: {parallels} 并行 × {runs} 流程 = {total_mult} 总流程 "
            f"| 共 {len(materials)} 种材料 | 评分 {score:.1f} | 利润 {fmt_isk_exact(profit)} | 利润率 {margin:.1f}%"
        )

        # ── 制造作业费 ──
        # 展示实际使用的星系（快照/材料机库推导），帮助确认 SCI 按哪个星系计算
        sys_id = metrics.get("solar_system_id")
        sys_name = get_system_name(get_container().db, sys_id) if sys_id else ""
        sci_label = f"SCI={sci * 100:.4f}%"
        if sys_name:
            sci_label += f"（{sys_name}）"

        activity = str(bd.get("activity") or metrics.get("activity") or "manufacturing")
        is_science = activity != "manufacturing" and activity != "reaction"
        self._job_fields = [
            _field("预估物品价值 (EIV):", fmt_isk_exact(eiv)),
            _field(
                "系统成本 (SCI × EIV):", f"{fmt_isk_exact((bd.get('system_cost', 0) or 0) * total_mult)}  ({sci_label})"
            ),
            _field("设施税:", fmt_isk_exact(facility_tax_v * total_mult)),
            _field("SCC 附加费:", fmt_isk_exact(scc * total_mult)),
            _field("制造作业费:", fmt_isk_exact(installation_fee * total_mult), "PRIMARY", strong=True),
        ]
        if is_science:
            self._job_fields.extend(self._research_fields(bd, activity, total_mult))
        else:
            research_cost = bd.get("research_cost", 0) or 0
            self._job_fields.append(
                _field(
                    "拷贝/发明研究成本:",
                    fmt_isk_exact(research_cost * total_mult) if research_cost else "—（无，原图或 T1 无需研究）",
                    "TEXT_SECONDARY",
                )
            )

        # ── 市场费用 ──
        self._mkt_fields = [
            _field("经纪人费:", fmt_isk_exact(broker_init * total_mult)),
            _field("改单费:", fmt_isk_exact(broker_relist * total_mult)),
            _field("销售税:", fmt_isk_exact(sales_tax * total_mult)),
            _field(
                "市场费用合计:",
                fmt_isk_exact((broker_init + broker_relist + sales_tax) * total_mult),
                "PRIMARY",
                strong=True,
            ),
        ]

        # ── 汇总 ──
        daily_profit = profit / hours * 24 if hours > 0 else 0
        self._summary_fields = [
            _field("总成本:", fmt_isk_exact(round(material_cost, 2))),
            _field("收入:", fmt_isk_exact(revenue * total_mult)),
            _field("利润:", fmt_isk_exact(profit), "GREEN" if profit >= 0 else "RED", strong=True),
            _field("利润率:", f"{margin:.2f}%"),
            _field("耗时:", f"{hours:.2f}h"),
            _field("日产能:", f"{daily_output:.1f} 件/天"),
            _field("日利润:", fmt_isk_exact(daily_profit)),
            _field("评分:", f"{score:.1f}"),
            _field("ISK/h:", fmt_isk_exact(isk_per_hour)),
        ]

    def _build_material_rows(self, metrics: dict, total_mult: int, sub_cost_map: dict[int, float]) -> None:
        from services.manufacturing_calculator import calc_material_for_runs

        structure_mat_saving = metrics.get("structure_mat_saving", 1.0)
        rows: list[dict] = []
        for mat in metrics.get("materials", []):
            base = mat.get("base_qty", 0)
            # 单件材料(基础量≤1)不受ME影响
            if base <= 1:
                total_qty = base * total_mult
            else:
                wf = mat.get("wastefactor", 10) or 10
                me = self._plan.get("me_level", 0) or 0
                total_qty = calc_material_for_runs(base, wf, me, total_mult, structure_mat_saving=structure_mat_saving)
            mid = mat.get("type_id")
            if mid in sub_cost_map:
                # 自制子项：单价 = 子项制造价 / 本计划总需求，小计 = 子项制造价
                sub_total = sub_cost_map[mid]
                unit_price = sub_total / total_qty if total_qty > 0 else 0.0
                name_display = f"{mat.get('name', '')}（自制）"
            else:
                unit_price = mat.get("unit_price", 0) or 0
                sub_total = unit_price * total_qty
                name_display = mat.get("name", "")
            rows.append(
                {
                    "cells": [
                        cell(name_display),
                        cell(str(base)),
                        cell(fmt_material_saving(total_qty, base, total_mult)),
                        cell(f"{total_qty:,.0f}"),
                        cell(fmt_isk_exact(unit_price)),
                        cell(fmt_isk_exact(sub_total)),
                    ]
                }
            )
        self._material_rows = rows

    @staticmethod
    def _research_fields(bd: dict, activity: str, total_mult: int) -> list[dict]:
        """科研行的专属明细（原 `_fill_research_fields`，只是返回值而不是 setText）。"""
        if activity == "invention":
            rate = bd.get("success_rate")
            base = bd.get("base_probability")
            txt = f"{float(rate) * 100:.1f}%" if rate is not None else "—"
            if base:
                txt += f"（基础 {float(base) * 100:.0f}%"
                if bd.get("decryptor"):
                    txt += f"，解码器：{bd['decryptor']}"
                txt += "）"
            if bd.get("is_actual"):
                txt += " · 已回填实际产出"
            unit = bd.get("bpc_unit_cost")
            return [
                _field("发明成功率:", txt, "TEXT_SECONDARY"),
                _field(
                    "尝试次数 / 作业量:",
                    f"{bd.get('attempts', 0)} 次尝试 × {bd.get('runs_per_bpc', 0)} 流程/次",
                    "TEXT_SECONDARY",
                ),
                _field(
                    "产出蓝图单位成本:",
                    f"{fmt_isk_exact(unit)} ISK / 流程" if unit else "—",
                    "ACCENT_CYAN",
                ),
                _field(
                    "拷贝/发明研究成本:",
                    "—（科研作业不消耗输入蓝图流程；发明按尝试消耗 T1 BPC 流程）",
                    "TEXT_SECONDARY",
                ),
            ]
        if activity == "copying":
            per_copy = bd.get("per_copy_cost") or 0
            return [
                _field("发明成功率:", "—（拷贝无成功率）", "TEXT_SECONDARY"),
                _field(
                    "尝试次数 / 作业量:",
                    f"{bd.get('copies', 1)} 份 × {bd.get('runs_per_copy', 1)} 流程"
                    f"，上限 {bd.get('max_production_limit', 0)}",
                    "TEXT_SECONDARY",
                ),
                _field(
                    "产出蓝图单位成本:",
                    f"{fmt_isk_exact(per_copy)} ISK / 份（单份成本）" if per_copy else "—",
                    "ACCENT_CYAN",
                ),
                _field("拷贝/发明研究成本:", "—（拷贝不消耗原图流程，产出为 BPC）", "TEXT_SECONDARY"),
            ]
        # ME/TE 研究
        approx = "（时长为首级近似）" if bd.get("time_is_approximate") else ""
        return [
            _field("发明成功率:", "—（研究无成功率）", "TEXT_SECONDARY"),
            _field("尝试次数 / 作业量:", f"目标等级 {bd.get('target_level', 0)}", "TEXT_SECONDARY"),
            _field("产出蓝图单位成本:", "—（产出是等级提升后的原图）", "ACCENT_CYAN"),
            _field("拷贝/发明研究成本:", f"—（研究不消耗蓝图流程）{approx}", "TEXT_SECONDARY"),
        ]

    def _compute_subitem_costs(self, group_number: int, deeper_than: int) -> dict[int, float]:
        """读同组更深子项产线，返回 {子项 product_type_id: 制造价合计（材料+作业费）}。

        自底向上按 sub_level 降序计算：最深子项先算，父层用子层调整后的成本，
        支持嵌套拆解。制造价经 ScoringService.child_manufacturing_cost 含子项制造作业费。
        """
        from services.scoring_service import ScoringService

        rows = get_subitem_plans(get_container().db, group_number, deeper_than)
        if not rows:
            return {}
        for p in rows:
            p["group_id"] = p.get("group_number", 0)
            p["child_level"] = p.get("sub_level", 0)

        svc = get_container().scoring_service()
        cost_by_id: dict[int, float] = {}
        for p in rows:
            metrics = svc.calculate_plan_metrics(
                p,
                self._char_config or {},
                price_type_mat=self._price_type_mat,
                price_type_prod=self._price_type_prod,
                mat_mult=self._mat_mult,
                prod_mult=self._prod_mult,
            )
            lvl = int(p.get("sub_level") or 0)
            kids = [c for c in rows if int(c.get("sub_level") or 0) > lvl]
            if kids:
                child_map = {
                    int(k.get("product_type_id") or 0): cost_by_id.get(int(k.get("id") or 0), 0.0) for k in kids
                }
                total_mult = max(int(p.get("runs", 1)), 1) * max(int(p.get("parallels", 1)), 1)
                adj_mat, _, _, _ = ScoringService.adjust_mother_metrics(metrics, child_map, total_mult)
                metrics = dict(metrics)
                metrics["material_cost"] = adj_mat
            cost_by_id[int(p.get("id") or 0)] = ScoringService.child_manufacturing_cost(p, metrics)
        return {int(p.get("product_type_id") or 0): cost_by_id.get(int(p.get("id") or 0), 0.0) for p in rows}

    def material_row_count(self) -> int:
        return len(self._material_rows)


class CostBreakdownQmlDialog(QmlDialog):
    """QML 版「查看核算」。`CostBreakdownDialog(plan, parent, ...)` 的调用方原样可用。

    注意：它是**只读查看器且非模态**（调用方 `show()` 而非 `exec()`），所以没有
    「确定」，只有「关闭」。
    """

    def __init__(
        self,
        plan_data: dict,
        parent: Any = None,
        char_config: dict | None = None,
        *,
        price_type_mat: str | None = None,
        price_type_prod: str | None = None,
        mat_mult: float = 1.0,
        prod_mult: float = 1.0,
    ) -> None:
        bridge = CostBreakdownBridge(
            plan_data,
            char_config,
            price_type_mat=price_type_mat,
            price_type_prod=price_type_prod,
            mat_mult=mat_mult,
            prod_mult=prod_mult,
        )
        super().__init__(_QML_FILE, bridge, parent=parent, size=(960, 720))
