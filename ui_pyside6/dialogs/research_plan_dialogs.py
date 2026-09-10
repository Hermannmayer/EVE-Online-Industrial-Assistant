"""科研计划对话框 — 拷贝 / 发明 / 效率研究的建计划入口。

三者共用同一套「目标 / 参数 / 机库 / 角色」骨架，只在专属字段上分叉：
    拷贝  CopyPlanDialog      份数 + 每份授权流程（上限 = 蓝图 copying 的 max_production_limit）
    发明  InventionPlanDialog 产物（多产物时下拉）+ 解码器 + 预期成功率 + 尝试次数
    研究  ResearchPlanDialog  ME/TE + 目标等级
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from domain.research import ACTIVITY_COPYING, ACTIVITY_INVENTION, DECRYPTORS
from services import inventory_manager
from ui_pyside6.views.char_settings_view import get_character_list


def _hangars() -> list[dict]:
    try:
        return inventory_manager.get_hangars()
    except Exception:
        return []


def _default_hangar_id(key: str) -> int | None:
    try:
        from services import user_settings

        return user_settings.get_default_hangar_id(key)
    except Exception:
        return None


class _ResearchDialogBase(QDialog):
    """三张科研对话框的公共骨架：角色 / 材料机库 / 输出机库 / 设施。"""

    def __init__(self, blueprint_name: str, *, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{title} — {blueprint_name}")
        self.setMinimumWidth(460)
        self._blueprint_name = blueprint_name
        self._result_data: dict[str, Any] | None = None
        self._root = QVBoxLayout(self)
        self._form = QFormLayout()
        self._root.addLayout(self._form)
        self._form.addRow("蓝图:", QLabel(blueprint_name))

        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

    # ── 公共尾部（子类在填完专属控件后调用） ──

    def _add_common_fields(self) -> None:
        self._char = QComboBox()
        chars = get_character_list()
        if chars:
            self._char.addItems(chars)
        else:
            self._char.addItem("main")
        self._form.addRow("角色:", self._char)

        self._mat_hangar = QComboBox()
        self._mat_hangar.addItem("未设置", -1)
        for h in _hangars():
            self._mat_hangar.addItem(h.get("name", ""), h.get("id"))
        hid = _default_hangar_id("default_mat_hangar_id")
        idx = self._mat_hangar.findData(hid)
        self._mat_hangar.setCurrentIndex(idx if idx >= 0 else 0)
        self._form.addRow("材料机库:", self._mat_hangar)

        self._out_hangar = QComboBox()
        self._out_hangar.addItem("未设置", -1)
        for h in _hangars():
            self._out_hangar.addItem(h.get("name", ""), h.get("id"))
        hid = _default_hangar_id("default_research_hangar_id") or _default_hangar_id("default_deposit_hangar_id")
        idx = self._out_hangar.findData(hid)
        self._out_hangar.setCurrentIndex(idx if idx >= 0 else 0)
        self._form.addRow("输出机库:", self._out_hangar)

        self._facility = QComboBox()
        self._facility.setEditable(True)
        self._facility.setPlaceholderText("选择或输入设施名称")
        for h in _hangars():
            self._facility.addItem(h.get("name", ""))
        self._facility.setCurrentIndex(-1)
        self._form.addRow("设施:", self._facility)

        tip = QLabel("提示：科研作业不消耗蓝图原本的流程；发明成功率高时一次尝试即可产出整张 BPC。")
        tip.setWordWrap(True)
        tip.setObjectName("research_tip")
        self._root.addWidget(tip)

        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("加入规划")
        btn.accepted.connect(self._on_ok)
        btn.rejected.connect(self.reject)
        self._root.addWidget(btn)

    # ── 取值 ──

    def result_data(self) -> dict[str, Any] | None:
        return self._result_data

    def _common_data(self, activity: str) -> dict[str, Any]:
        mat = self._mat_hangar.currentData()
        out = self._out_hangar.currentData()
        mat_id = int(mat) if mat and int(mat) > 0 else None
        out_id = int(out) if out and int(out) > 0 else None
        return {
            "activity": activity,
            "char_name": self._char.currentText().strip(),
            "mat_hangar_id": mat_id,
            "deposit_hangar_id": out_id,
            "solar_system_id": inventory_manager.get_hangar_system_id(mat_id) if mat_id else None,
            "facility": self._facility.currentText().strip(),
        }

    def _on_ok(self) -> None:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def _on_theme_changed(self) -> None:
        # 字号一律走 theme.fs()，禁止写死像素（全局字号设置要能生效）
        for lbl in self.findChildren(QLabel):
            color = theme.TEXT_SECONDARY if lbl.objectName() == "research_tip" else theme.TEXT_PRIMARY
            lbl.setStyleSheet(f"color: {color}; font-size: {theme.fs(12)}px;")


class CopyPlanDialog(_ResearchDialogBase):
    """拷贝计划：份数 + 每份授权流程（上限 = 蓝图 copying 活动上限）。"""

    def __init__(self, blueprint_name: str, *, max_production_limit: int, parent=None):
        super().__init__(blueprint_name, title="加入拷贝规划", parent=parent)
        self._limit = max(1, int(max_production_limit or 1))

        self._copies = QSpinBox()
        self._copies.setRange(1, 1000)
        self._copies.setValue(1)
        self._form.addRow("产出份数:", self._copies)

        runs_row = QHBoxLayout()
        self._runs = QSpinBox()
        self._runs.setRange(1, self._limit)
        self._runs.setValue(self._limit)
        self._runs.setToolTip(f"每份 BPC 的授权生产流程数，上限 {self._limit}（蓝图拷贝上限）")
        runs_row.addWidget(self._runs)
        runs_row.addWidget(QLabel(f"/ 上限 {self._limit}"))
        self._form.addRow("每份流程:", runs_row)

        self._add_common_fields()

    def _on_ok(self) -> None:
        data = self._common_data(ACTIVITY_COPYING)
        data.update({"copies": self._copies.value(), "runs_per_copy": self._runs.value()})
        self._result_data = data
        self.accept()


class InventionPlanDialog(_ResearchDialogBase):
    """发明计划：产物选择 + 解码器 + 预期成功率 + 尝试次数。"""

    def __init__(
        self,
        t1_blueprint_name: str,
        *,
        outcomes: list[dict[str, Any]],
        base_runs_by_outcome: dict[int, int],
        default_probability: dict[int, float],
        parent=None,
    ):
        super().__init__(t1_blueprint_name, title="加入发明规划", parent=parent)
        self._outcomes = outcomes
        self._base_runs = base_runs_by_outcome
        self._default_prob = default_probability
        self._form.addRow("产物:", QLabel(f"由「{t1_blueprint_name}」发明，共 {len(outcomes)} 种可能"))

        self._outcome = QComboBox()
        for oc in outcomes:
            self._outcome.addItem(f"{oc['name']}（基础成功率 {oc['base_probability'] * 100:.0f}%）", oc)
        self._form.addRow("发明产物:", self._outcome)

        self._decryptor = QComboBox()
        self._decryptor.addItem("不使用", None)
        for tid, d in DECRYPTORS.items():
            self._decryptor.addItem(
                f"{d.name}（成功率 ×{d.prob_mult:g}，流程 {d.runs_mod:+d}）",
                tid,
            )
        self._form.addRow("解码器:", self._decryptor)

        self._rate = QDoubleSpinBox()
        self._rate.setRange(0.01, 100.0)
        self._rate.setDecimals(1)
        self._rate.setSuffix(" %")
        self._form.addRow("预期成功率:", self._rate)
        self._rate_hint = QLabel()
        self._rate_hint.setObjectName("research_tip")
        self._form.addRow("", self._rate_hint)

        self._attempts = QSpinBox()
        self._attempts.setRange(1, 10000)
        self._attempts.setValue(1)
        self._attempts.setToolTip("计划要跑几次发明尝试（每次消耗 1 份输入 BPC 流程 + 一份数据核心）")
        self._form.addRow("尝试次数:", self._attempts)

        self._add_common_fields()

        self._outcome.currentIndexChanged.connect(self._refresh_probability)
        self._decryptor.currentIndexChanged.connect(self._refresh_probability)
        self._refresh_probability()

    def _refresh_probability(self) -> None:
        oc = self._outcome.currentData() or {}
        tid = self._decryptor.currentData()
        d = DECRYPTORS.get(int(tid)) if tid else None
        base = float(oc.get("base_probability") or 0.0)
        mult = d.prob_mult if d else 1.0
        computed = min(1.0, base * mult)
        self._rate.blockSignals(True)
        self._rate.setValue(max(0.01, computed * 100))
        self._rate.blockSignals(False)
        runs = self._base_runs.get(int(oc.get("blueprint_type_id") or 0), 10)
        out_runs = max(1, runs + (d.runs_mod if d else 0))
        self._rate_hint.setText(
            f"按技能算的基础成功率 {base * 100:.0f}%"
            + (f" × 解码器 {mult:g}" if d else "")
            + f" → {computed * 100:.1f}%；成功一次产出 {out_runs} 流程的 BPC"
        )

    def outcome_combo(self) -> QComboBox:
        """产物下拉（供调用方按右键选中的那张蓝图预选）。"""
        return self._outcome

    def _on_ok(self) -> None:
        oc = self._outcome.currentData() or {}
        tid = self._decryptor.currentData()
        data = self._common_data(ACTIVITY_INVENTION)
        data.update(
            {
                "product_blueprint_type_id": int(oc.get("blueprint_type_id") or 0),
                "product_name": oc.get("name") or "",
                "decryptor_type_id": int(tid) if tid else None,
                "success_rate": round(self._rate.value() / 100.0, 4),
                "attempts": self._attempts.value(),
            }
        )
        self._result_data = data
        self.accept()


class ResearchPlanDialog(_ResearchDialogBase):
    """效率研究计划：ME / TE 二选一 + 目标等级。"""

    def __init__(self, blueprint_name: str, *, parent=None):
        super().__init__(blueprint_name, title="加入效率研究规划", parent=parent)
        self._kind = QComboBox()
        self._kind.addItem("材料效率（ME，降低材料需求）", "researching_material_efficiency")
        self._kind.addItem("时间效率（TE，缩短制造时间）", "researching_time_efficiency")
        self._form.addRow("研究类型:", self._kind)

        self._level = QSpinBox()
        self._level.setRange(1, 10)
        self._level.setValue(1)
        self._level.setToolTip("目标等级（ME 0-10 / TE 0-20，本助手按 1-10 计）")
        self._form.addRow("目标等级:", self._level)

        self._add_common_fields()

    def _on_ok(self) -> None:
        data = self._common_data(str(self._kind.currentData()))
        data.update({"target_level": self._level.value()})
        self._result_data = data
        self.accept()
