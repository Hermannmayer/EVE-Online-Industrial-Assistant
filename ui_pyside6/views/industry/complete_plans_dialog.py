"""
工业制造页 — 下线确认对话框（CompletePlansDialog）

把一批「待下线(ready)」计划下线：展示产物/流程/产出量，选择产出机库
（默认=设置中的默认产出机库，可改为其他机库或「不自动入库」），确认后
更新每条计划 deposit_hangar_id 并完成入库（不可逆）。
"""

from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
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
) -> dict:
    """把一批 ready 计划下线到指定机库。

    hangar_id > 0 → 入库该机库；否则置 NULL（不自动入库，跳过入库仍完成）。
    每条计划先更新 deposit_hangar_id 再调用 complete_plan（幂等）。
    allow_bp_short: 蓝图流程不足时是否放行（与 `start_plan` 成对使用）。

    发明行先弹 InventionOutcomeDialog 回填实际产出（用户取消 → 该行不完成）。
    ⚠️ validate 档测试在**没有 QApplication** 的情况下直调本函数时必须传
    `ask_outcome=False`，否则弹窗会崩或挂死。
    Returns: {"completed": int, "deposited": int, "failed": [...], "skipped": [...],
              "failed_reasons": [...]}
    ``failed`` 只有产品名（调用方原样展示），``failed_reasons`` 带 `complete_plan`
    的拒绝原因——只报名字等于没说，用户无从判断是流程不足还是未回填发明产出。
    """
    completed = 0
    deposited = 0
    failed: list[str] = []
    failed_reasons: list[str] = []
    skipped: list[str] = []
    deposit = hangar_id if hangar_id and hangar_id > 0 else None
    for plan in plans:
        set_plan_deposit_hangar(get_container().db, plan["id"], deposit)
        actual = None
        if ask_outcome and _is_pending_invention(plan):
            actual = _ask_invention_outcome(plan, parent)
            if actual is None:  # 用户取消
                skipped.append(plan.get("product_name") or str(plan.get("id")))
                continue
        res = plan_execution.complete_plan(plan, actual_output_runs=actual, allow_bp_short=allow_bp_short)
        if res.get("ok"):
            completed += 1
            if res.get("deposited"):
                deposited += 1
        else:
            name = plan.get("product_name") or str(plan.get("id"))
            failed.append(name)
            failed_reasons.append(f"{name}：{res.get('message') or '未知原因'}")
    return {
        "completed": completed,
        "deposited": deposited,
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
    from ui_pyside6.views.industry.complete_guard import confirm_bp_shortfall

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


def _ask_invention_outcome(plan: dict, parent) -> int | None:
    """弹出发明结果回填对话框；取消 → None。"""
    from domain.research import get_decryptor
    from ui_pyside6.views.industry.invention_outcome_dialog import InventionOutcomeDialog

    bd = plan.get("breakdown") or {}
    expected = int(bd.get("expected_runs") or bd.get("output_runs") or 0)
    if expected <= 0:
        # 计划行没带 breakdown（批量行）→ 退化为「尝试次数 × 每次产出」
        attempts = max(int(plan.get("runs") or 1), 1)
        runs_per = int(bd.get("runs_per_bpc") or 0)
        expected = attempts * runs_per if runs_per else attempts
    d = get_decryptor(plan.get("decryptor_type_id"))
    dlg = InventionOutcomeDialog(
        plan_name=plan.get("product_name") or str(plan.get("id")),
        expected_runs=expected,
        attempts=int(plan.get("runs") or 0),
        decryptor_name=d.name if d else "",
        runs_per_bpc=int(bd.get("runs_per_bpc") or 0),
        parent=parent,
    )
    from PySide6.QtWidgets import QDialog

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return dlg.outcome()


class CompletePlansDialog(QDialog):
    """下线确认 — 展示待下线计划清单 + 选择产出机库。"""

    _HEADERS = ["产物", "流程", "产出量", "当前机库"]

    def __init__(self, plans: list[dict], hangars: list[dict], default_hangar_id: int | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("下线确认")
        self.setMinimumSize(560, 420)
        self.resize(640, 480)
        self._plans = plans
        self._hangars = hangars
        self._hangar_by_id = {h["id"]: h["name"] for h in hangars}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        tip = QLabel("以下「待下线」计划将被下线（产出成品入库，不可逆）：")
        tip.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.fs(12)}px;")
        layout.addWidget(tip)

        # ── 计划清单表 ──
        self._table = QTableWidget(len(plans), len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        total_qty = 0
        for row, p in enumerate(plans):
            name = str(p.get("product_name") or f"ID:{p.get('product_type_id', '')}")
            runs = int(p.get("runs") or 1)
            parallels = int(p.get("parallels") or 1)
            qty = runs * parallels * plan_execution.output_per_run(p.get("product_type_id") or 0)
            total_qty += qty
            dep = p.get("deposit_hangar_id")
            dep_name = self._hangar_by_id.get(dep) if dep and dep > 0 else "不自动入库"
            for col, text in [(0, name), (1, f"{parallels}X{runs}"), (2, f"{qty:,}"), (3, dep_name)]:
                it = QTableWidgetItem(str(text))
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col >= 1:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, col, it)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(0, 200)
        layout.addWidget(self._table, 1)

        # ── 产出机库选择 ──
        hangar_row = QHBoxLayout()
        hangar_row.addWidget(QLabel("产出机库:"))
        self._hangar_combo = QComboBox()
        self._hangar_combo.addItem("不自动入库", -1)
        for h in hangars:
            self._hangar_combo.addItem(h["name"], h["id"])
        # 默认：设置的默认产出机库 → 否则第一个机库
        idx = -1
        if default_hangar_id and default_hangar_id > 0 and default_hangar_id in self._hangar_by_id:
            idx = self._hangar_combo.findData(default_hangar_id)
        if idx < 0 and hangars:
            idx = 1  # 第一个机库
        if idx >= 0:
            self._hangar_combo.setCurrentIndex(idx)
        hangar_row.addWidget(self._hangar_combo, 1)
        layout.addLayout(hangar_row)

        # ── 汇总 ──
        self._summary = QLabel(f"共 {len(plans)} 项计划，产出 {total_qty:,} 件")
        self._summary.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.fs(11)}px;")
        layout.addWidget(self._summary)

        # ── 按钮 ──
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("确认下线")
        btn.accepted.connect(self.accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)

        theme.add_theme_listener(self._on_theme_changed)

    def selected_hangar_id(self) -> int:
        """返回选中的机库 id（-1 = 不自动入库）"""
        return cast(int, self._hangar_combo.currentData())

    def _on_theme_changed(self):
        pass
