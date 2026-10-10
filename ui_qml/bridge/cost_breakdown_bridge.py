"""查看核算（成本明细）对话框的桥（阶段 4）。

对照旧 Widgets 版：
左边材料清单（6 列），右边三块「标签: 值」明细（制造作业费 / 市场费用 / 汇总）。

计算口径：统一走 `scoring_service().calculate_plan_metrics()`（与主表
批量重算同一条路径）。**对话框整块是个人口径**（同组自制子项按自制价，缺口按市价/库存），
市场口径只以「调整前的 margin」出现在两处标注里 —— 两个数挨着显示，不能看起来像同一个。

拆解母项时自制子项按制造价计入成本而非市场买入价（`_compute_subitem_costs`，含嵌套拆解的
自底向上算法），映射值走 `plan_metrics.SubitemCost` 契约（**单件制造价 + 子项自己的产出量**）：

- 单件制造价 = 子项整线制造价 ÷ 子项产出量（`runs × parallels × 每轮产出`，每轮产出按该计划的
  activity 查配方）。子项产线排的是**净需求**（库存已被扣掉），产出量常小于母项需求，
  于是**缺口按市价补齐** —— 旧口径把整线价当成「覆盖全部需求」，等于把缺口算成 0 成本。
- **制造价为 0 的子项（0 轮产线）不进映射**、该行回退市价 —— 与主表批量重算那条路径对齐。
- 同一汇总框里的 `ISK/h` 必须与调整后的利润同口径（直接用 `profit / hours` 重算），
  不再取市场口径的 `metrics["iskph"]`（实测利润为个人口径、ISK/h 取市场口径时符号相反）。

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

from core.container import get_container
from core.formatting import fmt_isk_exact
from services.industry_dialog_queries import get_subitem_plans, get_system_name
from services.plan_metrics import SubitemCost
from ui_qml.bridge.summary_dialog import cell
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.theme import registry as theme

__all__ = ["CostBreakdownBridge", "CostBreakdownQmlDialog", "fmt_material_saving"]

_QML_FILE = "dialogs/CostBreakdownDialog.qml"

_MATERIAL_HEADERS = ["材料", "基础量", "材料减成%", "实际量", "单价", "自制成本", "小计"]


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
        sub_cost_map: dict[int, SubitemCost] = {}
        try:
            gid = self._plan.get("group_id") or self._plan.get("group_number")
            my_lvl = int(self._plan.get("sub_level") or self._plan.get("child_level") or 0)
            if gid:
                sub_cost_map = self._compute_subitem_costs(
                    gid, my_lvl, need_by_type=self._material_needs(metrics, total_mult)
                )
        except Exception:
            from core.logger import log

            log.exception("计算拆解子项成本失败: %s", self._plan.get("product_name"))
            sub_cost_map = {}

        # 市场口径利润率 = 调整前留存（个人口径的调整只换材料成本，收入/费用不动）
        market_margin = metrics.get("margin", 0) or 0
        if sub_cost_map:
            from services.scoring_service import ScoringService

            adj_mat, profit, margin, _ = ScoringService.adjust_mother_metrics(metrics, sub_cost_map, total_mult)
            material_cost = adj_mat
        else:
            material_cost = metrics.get("material_cost", 0)
            profit = metrics.get("profit", 0)
            margin = metrics.get("margin", 0)

        score = metrics.get("score", 0) or 0
        hours = metrics.get("calculated_time", 0) / 3600 if metrics.get("calculated_time") else 0
        # ISK/h 与上面这份利润**同口径**：手动重算，不取市场口径的 `metrics["iskph"]`
        # （实测原写法在同一个汇总框里给出「利润 +3.4 亿 / ISK/h −514 万」这种自相矛盾的值）
        isk_per_hour = profit / hours if hours > 0 else 0
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
            f"口径: 个人口径（同组自制子项按自制价，缺口按市价/库存）"
            f" | 计划设定: {parallels} 并行 × {runs} 流程 = {total_mult} 总流程 "
            f"| 共 {len(materials)} 种材料 | 评分 {score:.1f} | 利润 {fmt_isk_exact(profit)} | 利润率 {margin:.1f}% "
            f"（市场口径 {market_margin:.1f}%）"
            f"| 自制成本 = 料+作业费(+研究费)÷单轮产出，不含卖出费用（— 表示无制造蓝图）"
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
            # 两个口径挨着显示且各自标明来源：个人口径（上面那行）与市场口径不是同一个数
            _field("市场口径利润率:", f"{market_margin:.2f}%", "TEXT_SECONDARY"),
            _field("耗时:", f"{hours:.2f}h"),
            _field("日产能:", f"{daily_output:.1f} 件/天"),
            _field("日利润:", fmt_isk_exact(daily_profit)),
            _field("评分:", f"{score:.1f}"),
            _field("ISK/h:", fmt_isk_exact(isk_per_hour)),
        ]

    def _build_material_rows(self, metrics: dict, total_mult: int, sub_cost_map: dict[int, SubitemCost]) -> None:
        from domain.formulas import material_total_for_runs

        structure_mat_saving = metrics.get("structure_mat_saving", 1.0)
        me = self._plan.get("me_level", 0) or 0
        materials = metrics.get("materials", [])
        # 「这件料自己造要多少钱」—— 口径 = `domain.scoring.make_cost_per_unit`：
        # 料钱 + 作业费（含 SCI/设施税）+ 研究费 ÷ 单轮产出，用用户手上最好的那张蓝图的 ME/TE，
        # **不含**经纪费/改单费/销售税（那是卖出去才产生的花费，且按售价算）。
        # 本列**不递归**（不把「料也自己造」逐层算下去）。算不出的（矿物/数据核心/解码器等
        # 无制造蓝图）显示 `—`。
        make_costs = self._unit_make_costs([m.get("type_id") for m in materials])
        rows: list[dict] = []
        for mat in materials:
            base = mat.get("base_qty", 0)
            # 整批取整：优先用评分链路算好的 `total_qty`。口径的**单一定义处**是
            # `domain.formulas.material_total_for_runs` —— 这段以前把同一套规则内联在这里，
            # 于是「查看核算」的合计与启动时的实际扣减漂移过（用户能直接看出数字不一样）。
            total_qty = mat.get("total_qty")
            if total_qty is None:
                total_qty = material_total_for_runs(
                    mat, total_mult, me_level=me, structure_mat_saving=structure_mat_saving
                )
            mid = mat.get("type_id")
            sub = sub_cost_map.get(int(mid)) if mid else None
            if sub is not None:
                # 自制子项：覆盖到的那部分（= min(需求, 子项产出量)）按子项单件制造价，
                # 缺口按市价补齐（子项产线排的是净需求，差的那批在库存里/要买）。
                # 覆盖量拿不到（无配方）时按「整线覆盖全部需求」处理，与 adjust_mother_metrics 一致。
                covered = float(total_qty) if sub.covered_qty is None else min(float(total_qty), float(sub.covered_qty))
                gap = max(0.0, float(total_qty) - covered)
                sub_total = covered * sub.unit_cost + gap * (mat.get("unit_price", 0) or 0)
                unit_price = sub_total / total_qty if total_qty > 0 else 0.0
                name = mat.get("name", "")
                name_display = (
                    f"{name}（自制 {covered:,.0f}/{total_qty:,.0f}）"
                    if sub.covered_qty is not None
                    else f"{name}（自制）"
                )
            else:
                unit_price = mat.get("unit_price", 0) or 0
                sub_total = unit_price * total_qty
                name_display = mat.get("name", "")
            cost = make_costs.get(int(mid)) if mid else None
            rows.append(
                {
                    "cells": [
                        cell(name_display),
                        cell(str(base)),
                        cell(fmt_material_saving(total_qty, base, total_mult)),
                        cell(f"{total_qty:,.0f}"),
                        cell(fmt_isk_exact(unit_price)),
                        cell(fmt_isk_exact(cost) if cost else "—"),
                        cell(fmt_isk_exact(sub_total)),
                    ]
                }
            )
        self._material_rows = rows

    def _unit_make_costs(self, type_ids: list[Any]) -> dict[int, float]:
        """每件「自己造」的成本（口径见 `ScoringService.manufacturing_unit_costs`）。

        按**本对话框当前的价格设置**（计划 hub / 工具栏卖价买价 / 材料倍率）与**计划的材料机库**
        （设施成本倍率、材料减成、设施税、星系 SCI）算 —— 这样它和左边「单价」列是同一口径，
        两列并排就能看出「这件料自己造 vs 直接买」。取不到（无制造蓝图）→ 不在结果里 → 显示 `—`。
        """
        ids = [int(t) for t in type_ids if t]
        if not ids:
            return {}
        try:
            costs: dict[int, float] = (
                get_container()
                .scoring_service()
                .manufacturing_unit_costs(
                    ids,
                    mat_hub=str(self._plan.get("mat_hub") or "Jita"),
                    price_type_mat=str(self._price_type_mat or "sell"),
                    mat_mult=float(self._mat_mult or 1.0),
                    char_config=self._char_config or {},
                    hangar_id=int(self._plan.get("mat_hangar_id") or 0) or None,
                    facility_tax_pct=float(self._plan.get("facility_tax") or 0.0),
                )
            )
            return costs
        except Exception:
            from core.logger import log

            log.exception("自制成本计算失败（查看核算）: %s", self._plan.get("product_name"))
            return {}

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

    @staticmethod
    def _material_needs(metrics: dict, total_mult: int) -> dict[int, float]:
        """母项每种材料的需求量 {type_id: 需求}，口径与 `adjust_mother_metrics` 一致。

        只在「某子项查不到配方、拿不到自己的产出量」时用来把整线价折成单件价
        （见 `_compute_subitem_costs`）。
        """
        out: dict[int, float] = {}
        for mat in metrics.get("materials", []) or []:
            mid = mat.get("type_id")
            if not mid:
                continue
            need = mat.get("total_qty")
            if need is None:
                need = (mat.get("qty", 0) or 0) * total_mult
            out[int(mid)] = float(need)
        return out

    @staticmethod
    def _subitem_output_qty(rows: list[dict]) -> dict[int, int]:
        """{子项 plan_id: 子项产线产出量} —— 口径与 `child_manufacturing_cost` 同一条规则。

        每轮产出与「0 轮 = 不产出」的判定都在 `services/blueprint_reader.plan_output_qty`
        里（那里查询也排除 SDE 的两张测试蓝图）—— 别再在桥里抄一份。0 轮产线与查不到配方的
        都不进结果，调用方退回「整线价覆盖全部需求」的旧口径。
        """
        from services.blueprint_reader import plan_output_qty

        out: dict[int, int] = {}
        with get_container().db.connect("bp", "ref") as conn:
            for p in rows:
                qty = plan_output_qty(conn, p)
                if qty > 0:
                    out[int(p.get("id") or 0)] = qty
        return out

    def _compute_subitem_costs(
        self,
        group_number: int,
        deeper_than: int,
        need_by_type: dict[int, float] | None = None,
    ) -> dict[int, SubitemCost]:
        """读同组更深子项产线，返回 {子项 product_type_id: `SubitemCost`（单件制造价 + 产出量）}。

        自底向上按 sub_level 降序计算：最深子项先算，父层用子层调整后的成本，支持嵌套拆解。

        **单件制造价 = 子项整线制造价 ÷ 子项自己的产出量**（`_subitem_output_qty`）。
        子项产线排的是**净需求**（`services.plan_rebuild.plan_net_runs` 先扣掉了库存），
        产出量常小于母项需求，差的那部分由消费方按市价补齐 —— 只带整线价、当成
        「覆盖全部需求」会把缺口算成 0 成本（实测单价偏低 4.24%、总成本偏低）。
        查不到配方（拿不到每轮产出）时退回旧口径：按母项需求 `need_by_type` 折算单件价、
        `covered_qty=None`（消费方按「整线覆盖全部需求」处理）；连需求都没有就不猜，
        该行不进映射、回退市价。

        **制造价 ≤ 0 的子项（0 轮产线）不进返回的映射**（与
        `services.plan_metrics.mother_subitem_cost_map` 同规则）—— 否则「自制件成本 0 ISK」
        会被当成真实成本写进母项（实测把母项 material_cost 打成 0.00）。
        """
        from services.plan_metrics import (
            adjust_mother_metrics,
            child_manufacturing_cost,
            mother_subitem_cost_map,
        )

        rows = get_subitem_plans(get_container().db, group_number, deeper_than)
        if not rows:
            return {}
        for p in rows:
            p["group_id"] = p.get("group_number", 0)
            p["child_level"] = p.get("sub_level", 0)

        svc = get_container().scoring_service()
        #: plan id → (plan, metrics)；自底向上逐层把子层制造价折进父层 metrics
        base: dict[int, tuple[dict, dict]] = {}
        for p in rows:
            base[int(p.get("id") or 0)] = (
                p,
                svc.calculate_plan_metrics(
                    p,
                    self._char_config or {},
                    price_type_mat=self._price_type_mat,
                    price_type_prod=self._price_type_prod,
                    mat_mult=self._mat_mult,
                    prod_mult=self._prod_mult,
                ),
            )
        output_qty = self._subitem_output_qty(rows)

        # `get_subitem_plans` 已按 sub_level DESC 返回，这里再显式排一次，不依赖 SQL 顺序
        costs: dict[int, float] = {}
        for p in sorted(rows, key=lambda r: -int(r.get("sub_level") or 0)):
            metrics = base[int(p.get("id") or 0)][1]
            child_map = mother_subitem_cost_map(base, p, output_qty_by_plan=output_qty)
            if child_map:
                total_mult = max(int(p.get("runs") or 1), 1) * max(int(p.get("parallels") or 1), 1)
                adj_mat, _, _, _ = adjust_mother_metrics(metrics, child_map, total_mult)
                metrics = dict(metrics)
                metrics["material_cost"] = adj_mat
                base[int(p.get("id") or 0)] = (p, metrics)
            costs[int(p.get("id") or 0)] = child_manufacturing_cost(p, metrics)

        out: dict[int, SubitemCost] = {}
        for p in rows:
            pid = int(p.get("id") or 0)
            cost = costs.get(pid, 0.0)
            if cost <= 0:  # 与 mother_subitem_cost_map 同规则：0 值自制件不进映射
                continue
            type_id = int(p.get("product_type_id") or 0)
            qty = output_qty.get(pid)
            # 单件价**不取整**：消费方要按 `覆盖量 × 单件价` 还原整线价（实测先 round 到分
            # 会让母项总成本少 2.62 ISK/行，与右侧汇总对不上）
            if qty:
                out[type_id] = SubitemCost(unit_cost=cost / qty, covered_qty=float(qty))
                continue
            need = (need_by_type or {}).get(type_id)
            if need and need > 0:  # 无配方：整线价按需求折成单件价（covered_qty=None = 覆盖全部需求）
                out[type_id] = SubitemCost(unit_cost=cost / need, covered_qty=None)
        return out

    def material_row_count(self) -> int:
        return len(self._material_rows)


class CostBreakdownQmlDialog(QmlDialog):
    """QML 版「查看核算」。`CostBreakdownDialog(plan, parent, ...)` 的调用方原样可用。

    注意：它是**只读查看器**，走的是 `modeless=True` 的独立窗口（调用方 `show()`
    而非 `exec()`），所以没有「确定」，只有「关闭」。
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
        # 尺寸：加了「自制成本」列后左表要更宽（560→680），窗口同步加宽，右栏宽度不变
        super().__init__(_QML_FILE, bridge, parent=parent, size=(1120, 720), modeless=True)
