"""蓝图页那几条「重编排」动作 —— 从 `blueprint_tab` 平移过来，逻辑一字未改。

单独成模块的原因：它们要拉进 plan_service / research_plans / worker，
放进 `inventory_bridge` 会让那个文件的导入面变得很宽（而且其中几个只有
右键菜单用得到）。

本模块只负责「凑参数 → 开对话框 → 落库 → 刷新」。**对话框与取值框都已换成 QML 版**
（研究计划三框见 `research_plan_bridge`，取值见 `input_dialog`）：原先调的是 Widgets 版，
会把原生窗口弹进 QML 页面，和「页面已经全是 QML」的前提冲突。
反馈走桥的提示文案而不是 `QMessageBox`，同理。
"""

from __future__ import annotations

from typing import Any

__all__ = ["add_blueprints_to_plan", "add_research_plan", "auto_fill_cost_per_run", "paste_blueprints"]


def _parent(bridge: Any) -> Any:
    from PySide6.QtWidgets import QWidget

    shell = bridge._shell
    return shell if isinstance(shell, QWidget) else None


def _first_with_blueprint(bridge: Any, blueprints: list[dict]) -> dict | None:
    """科研类操作以单张为目标（对齐 `BlueprintTab._bp_for_selected`）。"""
    for bp in blueprints:
        if bp.get("blueprint_type_id"):
            return bp
    bridge._set_bp_hint("所选蓝图缺少蓝图信息")
    return None


# ═══════════════════════════════════════════════════════════
#  加入制造业规划
# ═══════════════════════════════════════════════════════════


def add_blueprints_to_plan(bridge: Any, blueprints: list[dict]) -> None:
    """多选蓝图 → 同(蓝图+原图/拷贝+ME+TE+流程)合并成一行并行 → 后台评分后批量落库绑定。

    整张直接加入，不弹配置对话框：流程/等级/设施均按蓝图自身属性。
    """
    from services import plan_execution, plan_service
    from ui_qml.workers.blueprint_plan_worker import _BulkPlanMetricsWorker

    valid = [bp for bp in blueprints if bp.get("product_type_id")]
    if not valid:
        bridge._set_bp_hint("所选蓝图无产物信息")
        return

    # 原图必须在分组键里：原图无流程数概念（runs 恒为 0），只按 runs 分组会与
    # 「流程数为 0/1 的拷贝」撞键合并成同一行并行产线。
    groups: dict[tuple, list[dict]] = {}
    for bp in valid:
        is_bpo = bool(bp.get("is_bpo"))
        key = (
            bp.get("blueprint_type_id"),
            is_bpo,
            int(bp.get("me_level") or 0),
            int(bp.get("te_level") or 0),
            0 if is_bpo else int(bp.get("runs") or 0),
        )
        groups.setdefault(key, []).append(bp)

    product_name = valid[0].get("product_name") or valid[0].get("display_name") or "?"
    char_name = ""
    try:
        from services.char_config_resolver import get_character_list

        chars = get_character_list()
        if chars:
            char_name = chars[0]
    except Exception:
        char_name = ""

    bulk = _BulkPlanMetricsWorker(list(groups.values()), product_name, char_name, parent=_parent(bridge))  # type: ignore[arg-type]
    bridge._add_plan_bulk = bulk  # 强引用保活，防止局部 QThread 被 GC

    def _on_bulk_done(rows: list) -> None:
        try:
            ids = plan_service.insert_plans_batch(rows, auto_bind=False)
            bindings = [(pid, r["bp_ids"]) for pid, r in zip(ids, rows, strict=False) if pid and pid > 0]
            if bindings:
                plan_execution.bind_blueprints_many(bindings)
            bridge._set_bp_hint(f"已加入制造业规划 {len(rows)} 行（{len(valid)} 张蓝图，合并 {len(groups)} 组）")
            bridge.loadBlueprints()
        finally:
            bridge._add_plan_bulk = None

    bulk.done.connect(_on_bulk_done)
    bulk.start()


# ═══════════════════════════════════════════════════════════
#  科研计划（拷贝 / 发明 / 效率研究）
# ═══════════════════════════════════════════════════════════


def _create_research_plan(
    bridge: Any,
    blueprint_type_id: int,
    name: str,
    *,
    activity: str,
    runs: int,
    parallels: int,
    data: dict,
    decryptor_type_id: Any = None,
    success_rate: Any = None,
    research_target_level: int = 0,
) -> None:
    """统一落库科研计划并回报。"""
    from services.research_plans import create_research_plan

    plan_id = create_research_plan(
        blueprint_type_id,
        activity=activity,
        blueprint_name=name,
        runs=runs,
        parallels=parallels,
        mat_hangar_id=data.get("mat_hangar_id"),
        deposit_hangar_id=data.get("deposit_hangar_id"),
        solar_system_id=data.get("solar_system_id"),
        char_name=data.get("char_name") or "",
        facility=data.get("facility") or "",
        decryptor_type_id=decryptor_type_id,
        success_rate=success_rate,
        research_target_level=research_target_level,
    )
    if plan_id > 0:
        bridge._set_bp_hint(f"已加入规划：{name}（计划 #{plan_id}）")
        bridge.loadBlueprints()
    else:
        bridge._set_bp_hint("加入规划失败，见日志")


def add_research_plan(bridge: Any, blueprints: list[dict], kind: str) -> None:
    """`kind`: `copying` / `invention` / `researching_*`（与蓝图活动名一致）。"""
    bp = _first_with_blueprint(bridge, blueprints)
    if not bp:
        return
    if kind == "copying":
        _add_copy_plan(bridge, bp)
    elif kind == "invention":
        _add_invention_plan(bridge, bp)
    else:
        _add_research_plan(bridge, bp)


def _add_copy_plan(bridge: Any, bp: dict) -> None:
    """加入拷贝规划（只能基于 BPO）。"""
    from PySide6.QtWidgets import QDialog

    from core.container import get_container
    from ui_qml.bridge.research_plan_bridge import CopyPlanDialogQmlDialog

    if not bp.get("is_bpo"):
        bridge._set_bp_hint("拷贝只能基于蓝图原本(BPO)，蓝图拷贝(BPC)不可再拷贝")
        return

    bid = int(bp["blueprint_type_id"])
    try:
        with get_container().db.connect("bp") as conn:
            row = conn.execute(
                "SELECT max_production_limit FROM blueprint_activities "
                "WHERE blueprint_type_id = ? AND activity = 'copying' LIMIT 1",
                (bid,),
            ).fetchone()
    except Exception:
        row = None
    if not row:
        bridge._set_bp_hint("该蓝图没有拷贝活动")
        return

    name = bp.get("display_name") or bp.get("zh_name") or str(bid)
    dialog = CopyPlanDialogQmlDialog(name, max_production_limit=int(row[0] or 1), parent=_parent(bridge))
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    data = dialog.result_data() or {}
    _create_research_plan(
        bridge,
        bid,
        name,
        activity="copying",
        runs=int(data.get("runs_per_copy") or 1),
        parallels=int(data.get("copies") or 1),
        data=data,
    )


def _add_invention_plan(bridge: Any, bp: dict) -> None:
    """加入发明规划（用库存 T1 BPC 发明出 T2 BPC）。"""
    from PySide6.QtWidgets import QDialog

    from core.container import get_container
    from core.logger import log
    from services.research_plans import invention_base_runs, resolve_invention_source
    from ui_qml.bridge.research_plan_bridge import InventionPlanDialogQmlDialog

    bid = int(bp["blueprint_type_id"])
    try:
        with get_container().db.connect("bp", "ref") as conn:
            src = resolve_invention_source(conn, bid)
            if src is None:
                bridge._set_bp_hint("该蓝图不是发明产物（T2/T3），无法发明")
                return
            t1_id = int(src["t1_blueprint_type_id"])
            base_runs = {
                int(oc["blueprint_type_id"]): invention_base_runs(conn, int(oc["blueprint_type_id"]), t1_id)
                for oc in src["outcomes"]
            }
    except Exception:
        log.exception("读取发明来源失败 bp=%s", bid)
        bridge._set_bp_hint("读取发明数据失败，见日志")
        return

    # 发明作业跑在 **T1 蓝图** 上，产物是选中的 T2 蓝图
    dialog = InventionPlanDialogQmlDialog(
        src["t1_name"],
        outcomes=src["outcomes"],
        base_runs_by_outcome=base_runs,
        default_probability={int(o["blueprint_type_id"]): float(o["base_probability"]) for o in src["outcomes"]},
        t1_blueprint_type_id=t1_id,
        parent=_parent(bridge),
    )
    for i in range(dialog.outcome_combo().count()):
        outcome = dialog.outcome_combo().itemData(i) or {}
        if int(outcome.get("blueprint_type_id") or 0) == bid:
            dialog.outcome_combo().setCurrentIndex(i)
            break
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    data = dialog.result_data() or {}
    product_bp = int(data.get("product_blueprint_type_id") or 0)
    if not product_bp:
        bridge._set_bp_hint("未选择发明产物")
        return
    _create_research_plan(
        bridge,
        product_bp,
        data.get("product_name") or str(product_bp),
        activity="invention",
        runs=int(data.get("attempts") or 1),
        parallels=int(data.get("parallels") or 1),
        data=data,
        decryptor_type_id=data.get("decryptor_type_id"),
        success_rate=data.get("success_rate"),
    )


def _add_research_plan(bridge: Any, bp: dict) -> None:
    """加入效率研究规划（ME/TE，只能基于 BPO）。"""
    from PySide6.QtWidgets import QDialog

    from ui_qml.bridge.research_plan_bridge import ResearchPlanDialogQmlDialog

    if not bp.get("is_bpo"):
        bridge._set_bp_hint("研究只能基于蓝图原本(BPO)，蓝图拷贝(BPC)不可研究")
        return

    bid = int(bp["blueprint_type_id"])
    name = bp.get("display_name") or bp.get("zh_name") or str(bid)
    dialog = ResearchPlanDialogQmlDialog(name, parent=_parent(bridge))
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    data = dialog.result_data() or {}
    _create_research_plan(
        bridge,
        bid,
        name,
        activity=str(data.get("activity") or "researching_material_efficiency"),
        runs=int(data.get("target_level") or 1),
        parallels=1,
        data=data,
        research_target_level=int(data.get("target_level") or 1),
    )


# ═══════════════════════════════════════════════════════════
#  按发明期望成本自动填写每流程成本
# ═══════════════════════════════════════════════════════════


def auto_fill_cost_per_run(bridge: Any, blueprints: list[dict], _hangar_id: Any = None) -> None:
    """按发明期望成本自动填写 `cost_per_run`（多产物时让用户选）。"""
    from core.container import get_container
    from core.logger import log
    from services.research_plans import research_cost_per_run
    from ui_qml.bridge.input_dialog import InputQmlDialog

    bp = _first_with_blueprint(bridge, blueprints)
    if not bp:
        return

    bid = int(bp["blueprint_type_id"])
    try:
        info = research_cost_per_run(get_container().db, bid)
    except Exception:
        log.exception("计算每流程成本失败 bp=%s", bid)
        info = None
    if not info:
        bridge._set_bp_hint("该蓝图既无发明路径也无拷贝活动，无法估算每流程成本")
        return

    if info.get("kind") == "invention":
        outcomes = info.get("outcomes") or []
        if not outcomes:
            bridge._set_bp_hint("未找到发明产物")
            return
        names = [
            f"{o['name']} — {o['cost_per_run']:,.0f} ISK/流程（成功率 {o['success_rate'] * 100:.1f}%）"
            for o in outcomes
        ]
        pick, ok = InputQmlDialog.get_item(
            _parent(bridge), "选择产物", "该 T1 蓝图有多个发明产物，按哪个算？", names, 0
        )
        if not ok:
            return
        value = outcomes[names.index(pick)]["cost_per_run"]
    else:
        value = info.get("cost_per_run", 0.0)

    from services.inventory_manager import update_blueprints_batch

    update_blueprints_batch([bp["id"]], cost_per_run=float(value))
    bridge._set_bp_hint(f"已按研究成本填写每流程成本：{value:,.0f} ISK")
    bridge.loadBlueprints()


# ═══════════════════════════════════════════════════════════
#  粘贴导入蓝图
# ═══════════════════════════════════════════════════════════


def paste_blueprints(bridge: Any, hangar_id: int | None, hangar_label: str) -> None:
    """剪贴板 → 解析（后台线程）→ 预览确认 → 应用 → 变动汇总。

    与原 `BlueprintTab._on_paste_blueprint` 同一流程，只是反馈不再弹原生消息框
    （解析期进度仍借外壳的状态栏进度条）。
    """
    from PySide6.QtWidgets import QApplication, QDialog

    from services.inventory_manager import get_blueprints
    from ui_qml.bridge.blueprint_import_bridge import (
        BlueprintImportChangeQmlDialog as BlueprintImportChangeDialog,
    )
    from ui_qml.bridge.blueprint_import_bridge import (
        BlueprintImportReviewQmlDialog as BlueprintImportReviewDialog,
    )
    from ui_qml.workers.blueprint_import_worker import (
        _BlueprintImportWorker,
        apply_blueprint_diff,
        build_blueprint_changes,
        snapshot_blueprints,
    )

    if hangar_id is None:
        return
    clipboard = QApplication.clipboard()
    raw = clipboard.text().strip() if clipboard is not None else ""
    if not raw:
        bridge._set_bp_hint("剪贴板为空，请先在游戏中复制蓝图（Ctrl+C）")
        return

    before_map = snapshot_blueprints(hangar_id)
    parent = _parent(bridge)

    def _on_ready(diff: list, worker: Any) -> None:
        bridge._import_worker = None
        if not diff:
            bridge._set_bp_hint(
                f"剪贴板中 {worker.filtered_count} 行是材料、{worker.unresolved_count} 行认不出对应蓝图；已全部跳过"
            )
            return
        dialog = BlueprintImportReviewDialog(
            diff,
            hangar_label,
            parent,
            default_mode="full",
            filtered_note=worker.filtered_count,
            unresolved_note=worker.unresolved_count,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        added, removed, blocked = apply_blueprint_diff(dialog.get_applied_rows(), hangar_id, dialog.mode())

        after_map = snapshot_blueprints(hangar_id)
        names = {
            bp["blueprint_type_id"]: bp["zh_name"] or bp.get("display_name") or f"ID:{bp['blueprint_type_id']}"
            for bp in get_blueprints(hangar_id)
        }
        BlueprintImportChangeDialog(
            build_blueprint_changes(before_map, after_map, names), added, removed, hangar_label or "蓝图", parent
        ).exec()
        if blocked:
            bridge._set_bp_hint(f"{blocked} 张蓝图正被生产计划占用，已跳过删除")
        bridge.loadBlueprints()

    worker = _BlueprintImportWorker(raw, hangar_id, parent=parent)
    bridge._import_worker = worker  # 强引用保活（防局部 QThread 被 GC）
    worker.finished_signal.connect(lambda diff, w=worker: _on_ready(diff, w))
    worker.start()
