"""蓝图粘贴导入的两个对话框的桥（阶段 4b）：导入预览 / 导入完成变动汇总。

对照 Widgets 版 `ui_pyside6/views/inventory/blueprint_import_dialog.py`。两个宿主都保持
原 API（构造 → `exec()` → 读 accessor），所以调用点只换类名：

    dlg = BlueprintImportReviewQmlDialog(diff, label, parent, default_mode="full",
                                         filtered_note=..., unresolved_note=...)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        apply_blueprint_diff(dlg.get_applied_rows(), hangar_id, dlg.mode())

**业务判定已随之搬进来**：差异分类（`attr_text` / `runs_differ` / `default_checked`）
与变动汇总文案（`build_summary`）原先是那个 Widgets 类的静态方法/实例方法，
现为本模块顶部的模块级纯函数 —— **逻辑一字未改**，只是从类里挪出来；
不挪的话删不掉 Widgets 版（桥会在 import 期就依赖它）。
本模块只把它们**整形**成 QML 的视图模型（每格一个文本 + 可选的颜色 token），不重写判定。

**没有后台线程**：解析剪贴板是既有 `_BlueprintImportWorker` 的活，由调用方自己起并保活
（见 `blueprint_actions.paste_blueprints` 的 `_import_worker`），对话框只吃算好的 diff。
所以这两个桥不需要 `stop()`（`QmlDialog._stop_bridge` 探不到 `stop` 就什么也不做）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.bridge.summary_dialog import SummaryTableBridge, SummaryTableQmlDialog, cell
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = [
    "BlueprintImportChangeBridge",
    "BlueprintImportChangeQmlDialog",
    "BlueprintImportReviewBridge",
    "BlueprintImportReviewQmlDialog",
    "attr_text",
    "build_summary",
    "change_rows",
    "default_checked",
    "runs_differ",
    "runs_values",
]

_REVIEW_QML = "dialogs/BlueprintImportReviewDialog.qml"
_CHANGE_QML = "dialogs/BlueprintImportChangeDialog.qml"

#: 导入模式：值 → 显示名。增量在前，与原 `_mode_combo` 的 addItem 顺序一致
#: （`modeIndex` 就是这张表的下标，QML 的 currentIndex 直接对得上）。
_MODES: list[tuple[str, str]] = [("incremental", "增量累加"), ("full", "全量同步")]

#: 变动汇总表的列（原版宽 200/150/100；「蓝图」「属性」在 QML 里吃满剩余宽度）
_CHANGE_COLUMNS = [
    {"title": "蓝图", "width": 0},
    {"title": "属性", "width": 0},
    {"title": "数量（前 → 后）", "width": 140},
]


# ══════════════════════════════════════════════════════════════
#  业务判定（原在 Widgets 版的 `BlueprintImportReviewDialog` 上）
# ══════════════════════════════════════════════════════════════
#
# 这五个原先挂在要被删掉的那个类上。**逻辑一字未改**，只是从类的静态方法/实例方法
# 变成模块级函数 —— 它们本来就是纯函数（只吃 row/delta），挂在对话框类上只是因为
# 当年只有那一个调用方。搬过来才可能删掉 Widgets 版。


def runs_values(row: dict) -> list[int]:
    """现有与剪贴板两侧出现过的流程数（去重升序）——原图无流程数概念。"""
    return sorted(
        {int(u) for u in row.get("clip_runs") or []} | {int(r.get("runs") or 0) for r in row.get("existing_rows") or []}
    )


def attr_text(row: dict) -> str:
    kind = "原图" if row["is_bpo"] else "拷贝"
    text = f"{kind}  ME{row['me']}  TE{row['te']}"
    values = runs_values(row)
    if not row["is_bpo"] and values:
        text += f"  流程{values[0]}" if len(values) == 1 else f"  流程{values[0]}~{values[-1]}"
    return text


def runs_differ(row: dict) -> bool:
    """张数没变但流程数变了（BPC 被消耗、原图归一）→ 仍需原地更新。"""
    old = sorted(
        int(r.get("runs") or 0)
        for r in row.get("existing_rows") or []
        for _ in range(max(int(r.get("quantity") or 1), 0))
    )
    return old != sorted(int(u) for u in row.get("clip_runs") or [])


def default_checked(row: dict, delta: int) -> bool:
    """默认勾选策略：新增/更新默认勾选，**纯删除默认不勾选**。

    删除是唯一不可逆的动作，且会经 delete_blueprint 静默解除活跃计划的绑定；
    若默认勾上，用户直接点确定就会把「剪贴板没覆盖到的蓝图」清掉。
    """
    if delta < 0:
        return False
    if delta > 0:
        return True
    return runs_differ(row)


def build_summary(changes: list[dict], added: int, removed: int) -> str:
    """汇总文案：共 N 项变化（增加/减少）+ 新增/删除条数。"""
    if not changes:
        return f"新增 {added} 条，删除 {removed} 条，无属性变化"
    inc = sum(1 for c in changes if c["qty_delta"] > 0)
    dec = sum(1 for c in changes if c["qty_delta"] < 0)
    parts = [f"共 {len(changes)} 项变化"]
    if inc:
        parts.append(f"增加 {inc}")
    if dec:
        parts.append(f"减少 {dec}")
    if added:
        parts.append(f"新增 {added} 张")
    if removed:
        parts.append(f"删除 {removed} 张")
    return "，".join(parts)


def _delta_token(delta: int) -> str:
    """增减列的颜色 token（与 Widgets 版同一组规则：增绿 / 减红 / 零用次要色）。"""
    if delta > 0:
        return "ACCENT_GREEN"
    if delta < 0:
        return "ACCENT_RED"
    return "TEXT_SECONDARY"


def change_rows(changes: list[dict]) -> list[dict]:
    """变动行 → 单元格行。纯函数，便于单测。

    颜色与 Widgets 版同规则：增量行绿、减量行红、零变化沿用默认前景色（token 给空串）。
    """
    rows: list[dict] = []
    for ch in changes:
        delta = int(ch["qty_delta"])
        token = "ACCENT_GREEN" if delta > 0 else ("ACCENT_RED" if delta < 0 else "")
        rows.append(
            {
                "cells": [
                    cell(ch["name"]),
                    cell(ch.get("attr", ""), "TEXT_SECONDARY"),
                    cell(f"{ch['qty_before']} → {ch['qty_after']}", token),
                ]
            }
        )
    return rows


# ══════════════════════════════════════════════════════════════
#  蓝图导入预览（模式 + 逐行勾选 + 增删预览）
# ══════════════════════════════════════════════════════════════


class BlueprintImportReviewBridge(DialogBridge):
    """蓝图导入预览的 QML 后端。逐行勾选与「最终」手改正文本都按**行号**记账。"""

    contentChanged = Signal()

    def __init__(
        self,
        diff_rows: list[dict],
        hangar_name: str,
        *,
        default_mode: str = "full",
        filtered_note: int = 0,
        unresolved_note: int = 0,
    ) -> None:
        super().__init__()
        self.set_title(f"蓝图导入预览 → {hangar_name}")
        self._diff_rows = list(diff_rows)
        self._filtered_note = max(int(filtered_note or 0), 0)  # 剪贴板里被过滤的材料行数
        self._unresolved_note = max(int(unresolved_note or 0), 0)  # 结构完整但认不出蓝图的行数
        self._mode = default_mode
        # 勾选与手改的「最终」值按行号记 —— 切模式重建时不得把用户的取舍清零（原 `_snapshot_state`）
        self._checked_state: dict[int, bool] = {}
        self._final_state: dict[int, str] = {}
        #: 全量同步的删除二次确认：第一次「确定导入」只给警告，之后任何改动都作废。
        #: （原版弹 QMessageBox Yes/No；QML 里改成同一颗按钮点两次，见 `accept`）
        self._pending_confirm = False
        self._rows: list[dict] = []
        self._summary = ""
        self._rebuild()

    # ── QML 读的属性 ──────────────────────────────────────────

    modes = Property(list, lambda self: [{"label": label} for _value, label in _MODES], constant=True)
    rows = Property(list, lambda self: list(self._rows), notify=contentChanged)
    rowCount = Property(int, lambda self: len(self._rows), notify=contentChanged)
    summaryText = Property(str, lambda self: self._summary, notify=contentChanged)
    modeIndex = Property(int, lambda self: 0 if self._mode == "incremental" else 1, notify=contentChanged)
    #: 全量模式才有可编辑的「最终」列（增量模式只增不减，最终值恒等于现有 + 剪贴板）
    isFullMode = Property(bool, lambda self: self._mode == "full", notify=contentChanged)

    # ── QML 写回来的槽 ────────────────────────────────────────

    @Slot(int)
    def setModeIndex(self, index: int) -> None:
        if not 0 <= index < len(_MODES):
            return
        self._snapshot_state()  # 先按旧模式记住勾选/最终值，再切
        self._mode = _MODES[index][0]
        self._pending_confirm = False
        self._rebuild()

    @Slot(int, bool)
    def toggleCheck(self, row: int, checked: bool) -> None:
        if not 0 <= row < len(self._diff_rows):
            return
        self._checked_state[row] = bool(checked)
        self._pending_confirm = False
        self._rebuild()

    @Slot(int, str)
    def setFinal(self, row: int, text: str) -> None:
        """「最终」列编辑提交（全量模式）—— 重算增减与颜色，非法值标红拦下。

        QML 侧走 `onEditingFinished`（回车/失焦）而不是逐字符回调：逐字符回调会重建整个
        ListView、把输入框的焦点弄丢；原版 `itemChanged` 也是在编辑提交时才发一次。
        """
        if not 0 <= row < len(self._diff_rows):
            return
        self._final_state[row] = str(text)
        self._pending_confirm = False
        self._rebuild()

    @Slot()
    def selectAll(self) -> None:
        self._set_all(True)

    @Slot()
    def deselectAll(self) -> None:
        self._set_all(False)

    @Slot()
    def accept(self) -> None:
        """确定导入。三道拦截与原 `_on_accept` 一致：无勾选 / 最终值非法 / 全量删除二次确认。"""
        checked = self._checked_rows()
        if not checked:
            self.set_error("没有勾选的蓝图，无法导入")
            return
        if self._mode == "full":
            invalid = [r for r in checked if self._final_value(r) is None]
            if invalid:
                self.set_error(f"有 {len(invalid)} 行的「最终」数量不是合法的非负整数，请修正后再导入")
                return
            deletions = [
                r for r in checked if int(self._diff_rows[r].get("existing_qty", 0)) > int(self._final_value(r) or 0)
            ]
            if deletions and not self._pending_confirm:
                self._pending_confirm = True
                self.set_error(self._deletion_warning(deletions))
                return
        self.accepted.emit()

    # ── 给调用方取值（名字与原版一致）────────────────────────

    def mode(self) -> str:
        """当前导入模式："incremental" 增量累加 | "full" 全量同步"""
        return self._mode

    def get_applied_rows(self) -> list[dict]:
        """返回勾选行的最终应用参数 [{diff_row..., target_qty}]（对齐原 `get_applied_rows`）。

        全量模式：target_qty = 最终数量；增量模式：target_qty = 现有 + 剪贴板。
        """
        result: list[dict] = []
        for r in self._checked_rows():
            diff = dict(self._diff_rows[r])
            if self._mode == "full":
                final = self._final_value(r)
                if final is None:  # 非法值已在 `accept` 拦下，这里兜底为「不动」
                    continue
            else:
                final = int(diff.get("existing_qty", 0)) + int(diff.get("qty", 0))
            result.append({**diff, "target_qty": final})
        return result

    # ── 行装配（整形，不含业务判定）──────────────────────────

    def _final_text(self, row: int) -> str:
        """「最终」列当前文本：用户改过就用改过的，否则是该模式的默认值。"""
        edited = self._final_state.get(row)
        if edited is not None:
            return edited
        diff = self._diff_rows[row]
        current = int(diff.get("existing_qty", 0))
        clip = int(diff.get("qty", 0))
        return str(clip if self._mode == "full" else current + clip)

    def _final_value(self, row: int) -> int | None:
        """「最终」列的合法取值；空/非数字/负数一律 None（调用方据此拦截）。对齐原 `_final_value`。"""
        try:
            val = int(self._final_text(row).replace(",", "").strip())
        except ValueError:
            return None
        return val if val >= 0 else None

    def _base_delta(self, row: dict) -> int:
        """未编辑时的差额：全量 = 剪贴板 - 现有；增量 = 剪贴板（只增不减）。"""
        current = int(row.get("existing_qty", 0))
        clip = int(row.get("qty", 0))
        return clip - current if self._mode == "full" else clip

    def _display_delta(self, row: int) -> int:
        """增减列显示的差额：全量模式跟着手改的「最终」走，非法值回落到未编辑口径。"""
        diff = self._diff_rows[row]
        if self._mode != "full":
            return self._base_delta(diff)
        final = self._final_value(row)
        if final is None:
            return self._base_delta(diff)
        return final - int(diff.get("existing_qty", 0))

    def _is_checked(self, row: int) -> bool:
        saved = self._checked_state.get(row)
        if saved is not None:
            return saved
        return default_checked(self._diff_rows[row], self._base_delta(self._diff_rows[row]))

    def _checked_rows(self) -> list[int]:
        return [r for r in range(len(self._diff_rows)) if self._is_checked(r)]

    def _build_rows(self) -> list[dict]:
        rows: list[dict] = []
        for r, diff in enumerate(self._diff_rows):
            current = int(diff.get("existing_qty", 0))
            clip = int(diff.get("qty", 0))
            delta = self._display_delta(r)
            rows.append(
                {
                    "index": r,
                    "checked": self._is_checked(r),
                    "name": diff.get("name") or f"ID:{diff['blueprint_type_id']}",
                    "attr": attr_text(diff),
                    "current": f"{current}",
                    "clip": f"{clip}",
                    "delta": f"+{delta}" if delta > 0 else f"{delta}",
                    "deltaToken": _delta_token(delta),
                    "finalText": self._final_text(r),
                    "finalToken": "" if self._final_value(r) is not None else "ACCENT_RED",
                    "editable": self._mode == "full",
                }
            )
        return rows

    def _summary_text(self) -> str:
        """底部统计文案（逐字对齐原 `_update_summary`，含前置的过滤/未识别提示）。"""
        checked = self._checked_rows()
        total_delta = sum(self._display_delta(r) for r in checked)
        text = f"已勾选 {len(checked)} 项 / 总计 {len(self._diff_rows)} 项 / 蓝图增减 {total_delta:+d}"
        if self._mode == "full":
            text += "  ｜ 全量同步以剪贴板为准：未出现在剪贴板中的蓝图会被删除，删除项默认不勾选"
        if self._filtered_note:
            text = f"[已过滤 {self._filtered_note} 行材料] {text}"
        if self._unresolved_note:
            text = f"[未识别 {self._unresolved_note} 行蓝图] {text}"
        return text

    def _deletion_warning(self, rows: list[int]) -> str:
        """全量同步的删除二次确认文案 —— 删行不可逆，且会解除活跃计划对该蓝图的绑定。

        正文与原 `_confirm_deletions` 一致（最多列 10 项），末尾多一句「再点一次」，
        因为 QML 版把原生的 Yes/No 弹窗换成了同一颗按钮点两次。
        """
        lines: list[str] = []
        total = 0
        for r in rows:
            diff = self._diff_rows[r]
            gone = int(diff.get("existing_qty", 0)) - int(self._final_value(r) or 0)
            total += gone
            name = diff.get("name") or f"ID:{diff['blueprint_type_id']}"
            lines.append(f"  {name}（{attr_text(diff)}）: 删除 {gone} 张")
        detail = "\n".join(lines[:10])
        if len(lines) > 10:
            detail += f"\n  …等共 {len(lines)} 项"
        return (
            f"以下 {total} 张蓝图不在剪贴板中，全量同步将把它们从本机库删除：\n\n{detail}\n\n"
            "删除不可撤销，且会同时解除相关生产计划对该蓝图的绑定。确认删除？\n"
            "确认请再点一次「确定导入」。"
        )

    # ── 内部 ─────────────────────────────────────────────────

    def _snapshot_state(self) -> None:
        """切模式前把勾选与手改的「最终」值固化下来（原 `_snapshot_state`）。

        旧行为是重建时按「有变化即勾选」重算默认，用户逐个取消的删除勾选会在切换模式的
        瞬间全部复活；固化后以用户取舍为准。
        """
        for r in range(len(self._diff_rows)):
            self._checked_state[r] = self._is_checked(r)
        if self._mode == "full":
            for r in range(len(self._diff_rows)):
                val = self._final_value(r)
                if val is not None:
                    self._final_state[r] = str(val)

    def _set_all(self, checked: bool) -> None:
        for r in range(len(self._diff_rows)):
            self._checked_state[r] = checked
        self._pending_confirm = False
        self._rebuild()

    def _rebuild(self) -> None:
        self._rows = self._build_rows()
        self._summary = self._summary_text()
        # 任何改动都作废上一次的校验/删除确认提示（原版每步各自拦一次，没有常驻提示）
        self.set_error("")
        self.contentChanged.emit()


class BlueprintImportReviewQmlDialog(QmlDialog):
    """QML 版「蓝图导入预览」。`BlueprintImportReviewDialog(diff_rows, hangar_name, parent, ...)` 原样可用。"""

    def __init__(
        self,
        diff_rows: list[dict],
        hangar_name: str,
        parent: Any = None,
        *,
        default_mode: str = "full",
        filtered_note: int = 0,
        unresolved_note: int = 0,
    ) -> None:
        bridge = BlueprintImportReviewBridge(
            diff_rows,
            hangar_name,
            default_mode=default_mode,
            filtered_note=filtered_note,
            unresolved_note=unresolved_note,
        )
        super().__init__(_REVIEW_QML, bridge, parent=parent, size=(820, 480))
        self._review_bridge = bridge

    def mode(self) -> str:
        return self._review_bridge.mode()

    def get_applied_rows(self) -> list[dict]:
        return self._review_bridge.get_applied_rows()


# ══════════════════════════════════════════════════════════════
#  蓝图导入完成变动汇总（只读表 + 顶部汇总行）
# ══════════════════════════════════════════════════════════════


class BlueprintImportChangeBridge(SummaryTableBridge):
    """蓝图导入完成后的变动汇总。表格渲染交给通用的 `FSummaryTable`，本类只算行与文案。"""

    def __init__(self, changes: list[dict], added: int, removed: int, hangar_name: str) -> None:
        super().__init__(title=f"蓝图导入完成 — {hangar_name}", columns=[dict(c) for c in _CHANGE_COLUMNS])
        self._changes = list(changes)
        # 汇总文案复用原类的静态方法（不重写）；底部状态行原版就没有，留空。
        self.set_content(
            change_rows(self._changes),
            "",
            build_summary(self._changes, added, removed),
        )


class BlueprintImportChangeQmlDialog(SummaryTableQmlDialog):
    """QML 版「蓝图导入完成 — 变动汇总」。`BlueprintImportChangeDialog(changes, added, removed, hangar_name, parent)` 原样可用。"""

    def __init__(self, changes: list[dict], added: int, removed: int, hangar_name: str, parent: Any = None) -> None:
        super().__init__(
            BlueprintImportChangeBridge(changes, added, removed, hangar_name),
            parent=parent,
            size=(640, 460),
            qml_file=_CHANGE_QML,
        )
