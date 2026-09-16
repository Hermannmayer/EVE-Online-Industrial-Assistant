"""下线前的蓝图流程预检 —— 四条下线入口共用的「流程不足」确认。

`plan_table`（单行 / 右键批量）与 `procurement_tab`（一键完成）各自内联过一份
几乎相同的确认框，而底部状态栏的「全部下线」漏了这份检查：它不预检、也不传
`allow_bp_short`，于是强制启动过的计划（蓝图流程账面不足，或原图尚未归一）
在该入口**永远无法下线**，且失败原因被 `complete_plans` 吞成一句「下线失败」。

原先住在 `ui_pyside6/views/industry/complete_guard.py`。批次 7.4 搬到 `ui_qml/bridge/`：
`ui_pyside6/` 要在 7.5 整个删掉，而这条确认的四个调用点都还活着，不搬就会连带打断它们。
搬迁同时把 `QMessageBox.question` 换成自绘的 `FMessageDialog.question`。

**接缝没变**：`confirm_bp_shortfall(parent, plans) -> bool | None` 一个字不改 ——
四个调用点只改 import 路径，行为不变（见下 `default_yes` 的说明）。
"""

from __future__ import annotations

from typing import Any

from services import plan_execution
from ui_qml.bridge.message_dialog import FMessageDialog

__all__ = ["confirm_bp_shortfall", "shortfall_lines"]

_SHORTFALL_HINT = "流程按实际可用量消耗；由此产生的账面偏差，请稍后用「蓝图管理 → 粘贴导入蓝图 → 全量同步」矫正。"


def shortfall_lines(plans: list[dict]) -> list[str]:
    """逐计划查蓝图绑定短板，返回「产物: 原因」文本行（无短板则为空列表）。"""
    lines: list[str] = []
    for p in plans:
        pid = p.get("id")
        if not pid:
            continue
        short = plan_execution.binding_shortfall(pid)
        if short:
            lines.append(f"  {p.get('product_name') or pid}: {short}")
    return lines


def confirm_bp_shortfall(parent: Any, plans: list[dict]) -> bool | None:
    """蓝图流程不足时确认一次（批量只问一次）。

    Returns:
        True  = 确有不足且用户选择强制放行
        False = 没有不足，按常规路径走
        None  = 用户取消，调用方应中止本次下线
    """
    lines = shortfall_lines(plans)
    if not lines:
        return False
    # `default_yes=False` 对应原版 `QMessageBox.question(..., defaultButton=No)`。
    # 这是「要不要强制放行」的破坏性确认，**默认项必须落在「否」**：
    # 手快回车不该把流程不足的计划放下去。
    confirmed = FMessageDialog.question(
        parent,
        "蓝图流程不足",
        "\n".join(lines[:10]) + "\n\n仍要下线？\n" + _SHORTFALL_HINT,
        default_yes=False,
    )
    return True if confirmed else None
