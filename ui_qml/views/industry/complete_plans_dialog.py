"""下线确认的**业务函数**（展示对话框已迁到 QML，见 `ui_qml/bridge/complete_plans_bridge.py`）。

把一批「待下线(ready)」计划下线：更新每条计划 deposit_hangar_id 并完成入库（不可逆）。
本模块只留落库与「发明结果回填」的编排，不再是 QDialog。
"""

from PySide6.QtWidgets import QMessageBox

from core.container import get_container
from services import plan_execution
from services.industry_dialog_queries import set_plan_deposit_hangar


def complete_plans(
    plans: list[dict],
    hangar_id: int,
    *,
    parent=None,
    ask_outcome: bool = True,
    allow_bp_short: bool = False,
    update_hangar: bool = True,
    hangar_ids: list[int] | None = None,
) -> dict:
    """把一批 ready 计划下线到指定机库。

    hangar_id > 0 → 入库该机库；否则置 NULL（不自动入库，跳过入库仍完成）。
    每条计划先更新 deposit_hangar_id 再调用 complete_plan（幂等）。
    update_hangar=False → **不动**计划的产出机库，沿用库里已存的：采购页「一键完成」
    走这条（它不选机库，入库目标仍是计划自己配的那个）。
    allow_bp_short: 蓝图流程不足时是否放行（与 `start_plan` 成对使用）。
    hangar_ids: **逐条**产出机库 id（与 `plans` 同序）。批量入口传它 —— 每行在对话框里
    各自选一个机库。不给（None）时沿用 `hangar_id` 覆盖全批，**既有调用方语义不变**。

    发明行先弹 InventionOutcomeDialog 回填**成功产线数**（用户取消 → 该行不完成）。
    ⚠️ validate 档测试在**没有 QApplication** 的情况下直调本函数时必须传
    `ask_outcome=False`，否则弹窗会崩或挂死。
    Returns: {"completed": int, "deposited": int, "removed": int, "failed": [...],
              "skipped": [...], "failed_reasons": [...]}
    ``removed``：母项下线时被顺带清理掉的已完成子项行数（见
    `plan_execution.remove_completed_children`）；非母项恒为 0。
    ``failed`` 只有产品名（调用方原样展示），``failed_reasons`` 带 `complete_plan`
    的拒绝原因——只报名字等于没说，用户无从判断是流程不足还是未回填发明产出。
    """
    completed = 0
    deposited = 0
    removed = 0
    failed: list[str] = []
    failed_reasons: list[str] = []
    skipped: list[str] = []
    scalar_deposit = hangar_id if hangar_id and hangar_id > 0 else None
    for i, plan in enumerate(plans):
        if update_hangar:
            # 逐条优先：给了 hangar_ids 就按序号取，否则整批用同一个标量（向后兼容）
            if hangar_ids is not None:
                one = hangar_ids[i] if i < len(hangar_ids) else hangar_id
                deposit = one if one and one > 0 else None
            else:
                deposit = scalar_deposit
            set_plan_deposit_hangar(get_container().db, plan["id"], deposit)
        actual = None
        actual_bpc = None
        if ask_outcome and _is_pending_invention(plan):
            outcome = _ask_invention_outcome(plan, parent)
            if outcome is None:  # 用户取消
                skipped.append(plan.get("product_name") or str(plan.get("id")))
                continue
            actual, actual_bpc = outcome
        res = plan_execution.complete_plan(
            plan,
            actual_output_runs=actual,
            actual_bpc_count=actual_bpc,
            allow_bp_short=allow_bp_short,
        )
        if res.get("ok"):
            completed += 1
            if res.get("deposited"):
                deposited += 1
            removed += int(res.get("removed") or 0)
        else:
            name = plan.get("product_name") or str(plan.get("id"))
            failed.append(name)
            failed_reasons.append(f"{name}：{res.get('message') or '未知原因'}")
    return {
        "completed": completed,
        "deposited": deposited,
        "removed": removed,
        "failed": failed,
        "skipped": skipped,
        "failed_reasons": failed_reasons,
    }


def complete_one_plan(parent, plan: dict) -> dict | None:
    """单行下线端到端：选产出机库 → 蓝图流程预检 → complete_plans → 失败告警。

    **非 None 即成功**；返回 None 表示「用户取消」或「已弹过失败告警」。
    调用方拿到 None 直接返回即可 —— 千万不要把它当成失败结果去改本地状态
    （会让失败的计划在界面上显示成已完成）。

    计划表格的单行下线与小助手的行内「可下线」共用本函数，两条入口的机库选择、
    流程预检与失败提示口径因此完全一致。
    """
    from services.inventory_manager import get_hangars
    from services.user_settings import get_default_hangar_id
    from ui_qml.bridge.complete_guard import confirm_bp_shortfall
    from ui_qml.bridge.complete_plans_bridge import CompletePlansQmlDialog as CompletePlansDialog

    dlg = CompletePlansDialog(
        [plan],
        get_hangars(),
        get_default_hangar_id("default_deposit_hangar_id"),
        parent,
    )
    if not dlg.exec():
        return None
    allow_bp_short = confirm_bp_shortfall(parent, [plan])
    if allow_bp_short is None:
        return None
    result = complete_plans([plan], dlg.selected_hangar_id(), parent=parent, allow_bp_short=allow_bp_short)
    if not result["completed"]:
        detail = "\n".join(result.get("failed_reasons") or []) or "、".join(result["failed"]) or "未知错误"
        QMessageBox.warning(parent, "下线失败", detail)
        return None
    return result


def _is_pending_invention(plan: dict) -> bool:
    """发明行且尚未回填实际产出。"""
    from services.plan_job_kinds import normalize

    return normalize(plan.get("activity")) == "invention" and plan.get("actual_output_runs") is None


def _invention_defaults_from_sde(plan: dict) -> tuple[int, float]:
    """从 SDE 取该发明计划的 (T1→T2 基础流程数, 基础成功率)。

    为什么需要它：表格行**没跑过评分**时 `plan["breakdown"]` 是空的，而回填框的
    「每张流程数」只从 breakdown 取 —— 于是界面上出现「每张 0 流程、共 0 流程」，
    用户在框里填多少条成功产线都会换算成 0 流程入库（2026-10-11 用户报的 bug）。
    这里查权威来源：
      - 基础流程 = `blueprint_products.quantity`（T1→T2 那条发明行，缺省 10）
      - 基础成功率 = 同一批产物条目里命中本蓝图那条的 `probability`

    查不到（蓝图库未初始化 / 该蓝图不是发明产物）→ (0, 0.0)，由调用方兜底。
    """
    from core.container import get_container
    from core.logger import log
    from services.research_plans import invention_base_runs, resolve_invention_source

    t2_bp = int(plan.get("blueprint_type_id") or plan.get("product_type_id") or 0)
    if not t2_bp:
        return 0, 0.0
    try:
        with get_container().db.connect("bp", "ref") as conn:
            src = resolve_invention_source(conn, t2_bp)
            if not src:
                return 0, 0.0
            base_runs = invention_base_runs(conn, t2_bp, int(src["t1_blueprint_type_id"]))
            probability = next(
                (
                    float(o.get("base_probability") or 0.0)
                    for o in (src.get("outcomes") or [])
                    if int(o.get("blueprint_type_id") or 0) == t2_bp
                ),
                0.0,
            )
    except Exception:
        log.exception("读取发明基础数据失败 plan=%s", plan.get("id"))
        return 0, 0.0
    return base_runs, probability


def _ask_invention_outcome(plan: dict, parent) -> tuple[int, int] | None:
    """弹出发明结果回填对话框。返回 (实际产出流程数, BPC 张数)；取消 → None。"""
    from domain.research import get_decryptor, invention_output_runs
    from ui_qml.bridge.invention_outcome_bridge import InventionOutcomeQmlDialog as InventionOutcomeDialog

    bd = plan.get("breakdown") or {}
    attempts = max(int(plan.get("runs") or 1), 1)
    expected_runs = int(bd.get("expected_runs") or bd.get("output_runs") or 0)
    runs_per = int(bd.get("runs_per_bpc") or 0)
    expected_bpc = int(bd.get("expected_bpc") or 0)
    decryptor = get_decryptor(plan.get("decryptor_type_id"))

    # breakdown 缺任一项就回 SDE 取权威值 —— 尤其是 `runs_per`：「每次成功产出的流程数」
    # 是 base_runs + 解码器修正，不该因为没跑过评分就变成 0。
    if runs_per <= 0 or expected_bpc <= 0:
        base_runs, base_probability = _invention_defaults_from_sde(plan)
        if runs_per <= 0:
            runs_per = invention_output_runs(base_runs, decryptor)
        if expected_bpc <= 0:
            rate = bd.get("success_rate")
            # 有评分成功率就用它，否则用 SDE 基础成功率（未计技能加成，属保守粗估）
            expected_bpc = round(attempts * (float(rate) if rate is not None else base_probability))
    # 连基础成功率都取不到（蓝图库没初始化等）→ 退化为「每条产线成功一次」
    if expected_bpc <= 0:
        expected_bpc = attempts
    # 最后一道兜底：仍然没有每次流程数时，从「期望流程 ÷ 期望张数」反推
    if runs_per <= 0 and expected_bpc > 0 and expected_runs > 0:
        runs_per = max(1, expected_runs // expected_bpc)
    if expected_runs <= 0 and runs_per > 0:
        expected_runs = expected_bpc * runs_per

    dlg = InventionOutcomeDialog(
        plan_name=plan.get("product_name") or str(plan.get("id")),
        expected_runs=expected_runs,
        expected_bpc=expected_bpc,
        attempts=int(plan.get("runs") or 0),
        decryptor_name=decryptor.name if decryptor else "",
        runs_per_bpc=runs_per,
        parent=parent,
    )
    from PySide6.QtWidgets import QDialog

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return dlg.outcome()
