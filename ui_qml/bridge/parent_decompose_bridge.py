"""母项拆解对话框的桥（阶段 4a 收尾）。

对照 Widgets 版 `ui_pyside6/views/industry/parent_decompose_dialog.py`：
把选中母项递归拆成子项产线（`sub_level` 逐级 +1），每行预览 需求/流程/利润，
可移除不内造的行（改外购），确认后写库并按全局引用式需求重放子项。

展示复用 `FSummaryTable`（行/列约定与 `SummaryTableBridge` 相同），本类负责算与落库。

**一处有意的界面偏离**：Widgets 版是「多选若干行 → 点『删除选中行』」，
QML 版改成**每行一个「移除」按钮**（`FSummaryTable` 的行内动作列）。
能力等价，但少了「先选再点」两步，也不会出现「选了行但忘了点按钮」；
原来的「已删 N」反馈挪到状态行。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from core.container import get_container
from services.industry_dialog_queries import get_item_name, get_max_group_number
from services.plan_decompose import collect_removed_child_ids, decompose_plan
from ui_qml.bridge.summary_dialog import cell
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["ParentDecomposeBridge", "ParentDecomposeQmlDialog", "line_cells"]

_QML_FILE = "dialogs/ParentDecomposeDialog.qml"

#: 与 Widgets 版 `_HEADERS` 同源，末尾多一列「操作」放行内移除按钮
_HEADERS = ["组号", "组件", "层", "需求", "流程", "并行", "ME-TE", "利润", "蓝图"]

_COLUMNS = [{"title": title, "width": 0 if title == "组件" else 84} for title in _HEADERS]
_COLUMNS.append({"title": "操作", "width": 76})

_TIP = (
    "提示：每个子项的「流程」按母项对它的需求自动生成（需求 ÷ 单轮产出，向上取整），"
    "总产出 ≈ 需求（1X）。「利润」按成品价−材料−作业费估算（随价格上下文变化）。"
    "移除一行 = 本轮不内造该组件（改外购）；下次显式「拆解/重算子项」仍会按需求重建。"
    "无蓝图的行需先买入对应蓝图才能运行。库存已有的组件会自动少造。"
)

_EMPTY_HINT = "所选母项均无中间组件可拆解（直接材料均可外购）。"


def line_cells(group_number: int, line: dict, name: str, profit: float | None) -> list[dict]:
    """一条拆解预览行 → 单元格。纯函数，便于单测。

    配色对齐原 `_append_row`：无蓝图标红；利润为负标红；其余默认。
    """
    no_blueprint = not line["has_blueprint"]
    return [
        cell(str(group_number)),
        cell(name),
        cell(str(line["sub_level"])),
        cell(f"{line.get('demand', 0):,}"),
        cell(str(line["runs"])),
        cell(str(line["parallels"])),
        cell(f"{line['me_level']}-{line['te_level']}"),
        cell(
            f"{profit:,.0f}" if profit is not None else "—", "ACCENT_RED" if profit is not None and profit < 0 else ""
        ),
        cell("有蓝图" if line["has_blueprint"] else "无蓝图", "ACCENT_RED" if no_blueprint else ""),
        # 最后一个是行内按钮（FSummaryTable 的 hasActionColumn），文本由 QML 的 actionText 给
        cell(""),
    ]


class ParentDecomposeBridge(DialogBridge):
    """母项拆解的 QML 后端。

    **不继承 `SummaryTableBridge`**：那个的 `accept()` 是「直接 emit 关窗」，
    而这里确认时要先落库、再弹完成提示。表格那半仍照它的行/列约定（`[{cells:[{text,color}]}]`），
    所以能直接喂给同一个 `FSummaryTable`。
    """

    contentChanged = Signal()

    def __init__(
        self,
        plans: list[dict],
        *,
        price_settings: dict | None = None,
        default_char_name: str = "",
    ) -> None:
        super().__init__()
        #: 只看母项（sub_level/child_level 为 0）；子项由拆解过程生成
        self._plans = [p for p in plans if int(p.get("sub_level") or p.get("child_level") or 0) == 0]
        self._price_settings = price_settings or {}
        self._default_char_name = default_char_name or ""
        self._removed_types: set[int] = set()
        self._profit_cache: dict[tuple, float | None] = {}
        #: 组号一次分配并存储（不在确认时重查 MAX，防弹窗显示期间新组号竞态）
        self._assignments: list[tuple[dict, int, list[dict]]] = self._allocate_and_decompose()
        #: 平铺行号 → (母项下标, 该母项内行下标, 行数据)
        self._refs: list[tuple[int, int, dict]] = []
        self._rows: list[dict] = []
        self._removed_count = 0

        self.set_title(f"母项拆解 ({len(self._plans)} 个母项)")
        self._rebuild()

    # ── QML 读的属性 ──────────────────────────────────────────

    @Property(list, constant=True)
    def columns(self) -> list[dict]:
        return [dict(c) for c in _COLUMNS]

    @Property(list, notify=contentChanged)
    def rows(self) -> list[dict]:
        return list(self._rows)

    @Property(int, notify=contentChanged)
    def rowCount(self) -> int:
        return len(self._rows)

    @Property(bool, constant=True)
    def isEmpty(self) -> bool:
        """所选母项一个都拆不出东西 —— 原版此时只显示一句说明 + 关闭。"""
        return not self._assignments

    @Property(str, constant=True)
    def emptyText(self) -> str:
        return _EMPTY_HINT

    @Property(str, constant=True)
    def tipText(self) -> str:
        return _TIP

    @Property(str, notify=contentChanged)
    def headerText(self) -> str:
        """顶部汇总。**保留原版的 `<b>` 富文本** —— Qt 的 `Text.AutoText` 会识别并加粗，
        与 Widgets 版的观感一致；换成纯文本会丢掉「数字跳出来」的效果。
        """
        if not self._assignments:
            return "将拆解 <b>0</b> 个母项"

        with_lines = [a for a in self._assignments if a[2]]
        n_mothers = len(with_lines)
        n_groups = len({gnum for _p, gnum, lines in with_lines if lines})
        n_lines = sum(len(lines) for _, _, lines in with_lines)
        return (
            f"将拆解 <b>{n_mothers}</b>/<b>{len(self._assignments)}</b> 个母项到 "
            f"<b>{n_groups}</b> 个组，共 <b>{n_lines}</b> 个子项产线"
        )

    @Property(str, notify=contentChanged)
    def statusText(self) -> str:
        if self._removed_count:
            return f"已移除 {self._removed_count} 个组件（本轮不内造，改外购）"
        return ""

    # ── 行装配 ────────────────────────────────────────────────

    def _rebuild(self) -> None:
        """重算平铺行与行号映射（初始与每次移除后）。"""
        self._refs = []
        self._rows = []
        for a_idx, (_plan, gnum, lines) in enumerate(self._assignments):
            for l_idx, line in enumerate(lines):
                self._refs.append((a_idx, l_idx, line))
                name = self._resolve_name(int(line["product_type_id"]))
                self._rows.append({"cells": line_cells(gnum, line, name, self._line_profit(a_idx, line))})
        self.contentChanged.emit()

    @Slot(int)
    def removeRow(self, row: int) -> None:
        """移除一行 = 本轮不内造该组件（改外购）。记下 type_id，确认时连带删旧子项产线。"""
        if not 0 <= row < len(self._refs):
            return
        a_idx, l_idx, line = self._refs[row]
        type_id = int(line.get("product_type_id") or 0)
        if type_id:
            self._removed_types.add(type_id)
        del self._assignments[a_idx][2][l_idx]
        self._removed_count += 1
        self._rebuild()

    def _resolve_name(self, type_id: int) -> str:
        return get_item_name(get_container().db, type_id)

    def _line_profit(self, a_idx: int, line: dict) -> float | None:
        """预估单条子项产线利润（成品卖价 − 材料 − 作业费）。失败返回 None 显示 —。"""
        mother = self._assignments[a_idx][0]
        key = (line["product_type_id"], line.get("me_level", 0), line.get("te_level", 0), line.get("runs", 1))
        if key in self._profit_cache:
            return self._profit_cache[key]
        try:
            from services.char_config_resolver import resolve_char_config
            from services.scoring_service import ScoringService

            char_name = (mother.get("char_name") or "").strip() or self._default_char_name
            char_config = resolve_char_config(char_name=char_name) if char_name else {}
            plan_data = {
                "product_type_id": line["product_type_id"],
                "me_level": line.get("me_level", 0) or 0,
                "te_level": line.get("te_level", 0) or 0,
                "runs": line.get("runs", 1) or 1,
                "parallels": line.get("parallels", 1) or 1,
                "solar_system_id": mother.get("solar_system_id"),
                "mat_hangar_id": mother.get("mat_hangar_id"),
            }
            metrics = ScoringService.calculate_plan_metrics(
                plan_data,
                char_config,
                mat_hub=self._price_settings.get("mat_hub"),
                sell_hub=self._price_settings.get("prod_hub"),
                price_type_mat=self._price_settings.get("mat_price_type"),
                price_type_prod=self._price_settings.get("prod_price_type"),
                mat_mult=float(self._price_settings.get("mat_mult") or 1.0),
                prod_mult=float(self._price_settings.get("prod_mult") or 1.0),
                system_id=mother.get("solar_system_id"),
            )
            profit = metrics.get("profit")
            result = float(profit) if isinstance(profit, int | float) else None
        except Exception:
            result = None
        self._profit_cache[key] = result
        return result

    def _allocate_and_decompose(self) -> list[tuple[dict, int, list[dict]]]:
        """为每个可拆母项分配组号并拆解 → [(plan, gnum, lines)]。

        已有 group_number>0 的母项复用原组号；无组号的从 MAX(group_number)+1 起
        分配互不重复的号。lines 为空的母项跳过（不分配组号、不落库）。
        """
        decomposable: list[tuple[dict, list[dict]]] = []
        for plan in self._plans:
            lines = decompose_plan(plan, mat_hangar_id=plan.get("mat_hangar_id"))
            if lines:
                decomposable.append((plan, lines))

        # 早退一步：没有可拆的母项时不必查库（空态对话框因此完全不碰 DB）
        if not decomposable:
            return []

        existing = {int(p.get("group_number") or 0) for p, _ in decomposable if int(p.get("group_number") or 0) > 0}
        next_g = get_max_group_number(get_container().db) + 1

        assignments: list[tuple[dict, int, list[dict]]] = []
        for plan, lines in decomposable:
            gnum = int(plan.get("group_number") or 0)
            if gnum <= 0:
                while next_g in existing:
                    next_g += 1
                gnum = next_g
                existing.add(next_g)
                next_g += 1
            assignments.append((plan, gnum, lines))
        return assignments

    # ── 确认落库 ──────────────────────────────────────────────

    @Slot()
    def accept(self) -> None:
        repo = get_container().plan_repo
        for plan, gnum, _lines in self._assignments:
            # 母项落组号（供 UI 折叠归组）；子项由 rebuild_children 统一生成/合并
            if plan.get("id"):
                repo.update(plan["id"], group_number=gnum, sub_level=0)
                plan["group_number"] = gnum
                plan["sub_level"] = 0
                plan["group_id"] = gnum
                plan["child_level"] = 0

        # 按全局引用式需求重放子项：共享组件跨母项合并为一行，需求=所有母项之和。
        # 拆解模式 create+prune：补建缺失子项、清理不再被引用的旧子项。
        from services.plan_rebuild import rebuild_children

        res = rebuild_children(create=True, prune=True)

        # 预览中移除的行 → 确认后按 组内血缘 删掉对应子项产线（本轮不内造，改外购）
        removed = self._remove_planning_discarded(self._removed_types)
        msg = f"已重算子项产线：新增 {res['created']}、更新 {res['updated']}、清理 {res['deleted']} 条"
        if removed:
            msg += f"，未建 {removed} 条"
        #: 结果提示仍是 QMessageBox —— `QMessageBox` 的统一收敛是计划里的独立一项，未做。
        #: 父窗口取宿主对话框：不传的话提示框不会跟着本对话框居中。
        QMessageBox.information(self.host_widget(), "完成", msg)
        self.accepted.emit()

    def _remove_planning_discarded(self, removed_types: set[int]) -> int:
        """删除被用户在预览中移除的组件对应的子项产线（含同组子孙）。返回删除行数。"""
        removed_types = {t for t in removed_types if t}
        if not removed_types:
            return 0
        from core.logger import log
        from services import plan_execution

        with get_container().db.connect("user") as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, product_type_id, group_number, sub_level, component_parent_type_id "
                    "FROM production_plans WHERE sub_level > 0"
                ).fetchall()
            ]
        ids = collect_removed_child_ids(rows, removed_types)
        if not ids:
            return 0
        for pid in ids:
            try:
                plan_execution.release_blueprint(pid)
            except Exception:
                log.warning("释放被删子项 %s 蓝图绑定失败", pid, exc_info=True)
        get_container().plan_repo.delete_many(sorted(ids))
        return len(ids)


class ParentDecomposeQmlDialog(QmlDialog):
    """QML 版「母项拆解」。`ParentDecomposeDialog(plans, parent, ...)` 的调用方原样可用。"""

    def __init__(
        self,
        plans: list[dict],
        parent: Any = None,
        *,
        price_settings: dict | None = None,
        default_char_name: str = "",
    ) -> None:
        bridge = ParentDecomposeBridge(
            plans,
            price_settings=price_settings,
            default_char_name=default_char_name,
        )
        super().__init__(_QML_FILE, bridge, parent=parent, size=(920, 560))
        self._decompose_bridge = bridge
        #: 给桥的 `accept` 当 QMessageBox 的父窗口，提示框才会跟着本对话框居中。
        #: **必须在 `super().__init__()` 之后**：那之前 QDialog 的 C++ 对象还没建出来，
        #: 把一个半成品 QObject 挂到别的 QObject 上会挂死（实测卡在构造里，无任何输出）。
