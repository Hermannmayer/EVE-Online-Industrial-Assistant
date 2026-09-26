"""人物占用情况对话框的桥（阶段 4）。

对照 Widgets 版 `ui_pyside6/views/industry/char_usage_dialog.py`，但**展示换了**：
原先是一张五列表（「队列时长 / 技能等级」两列常年 N/A），现在直接渲染查询页空闲态
仪表盘左栏那块「产线详情」面板（`qml/components/OccupancyPanel.qml`）—— 每人物一块、
块内制造 / 科研 / 反应三行容量条 + 「待下线 N」，一眼看出谁的线快满了。

与仪表盘的**唯一差别是口径**：仪表盘只算**正在生产**，本对话框算**已规划**
（`PLANNED_STATUSES`：待生产的也先把线占上，待下线的也算 —— 成品没下线那条线腾不出来）。
排产阶段要看的正是这个「按现在的规划，谁的线不够」，只算在跑的等于把待排的线全漏掉。

**顺带修掉一处会崩的调用**：Widgets 版 `CharacterUsageDialog` 继承的是 `QWidget`，
而调用方 `industry_view.open_char_usage()` 对它调 `.exec()` —— `QWidget` 没有 `exec`，
点那个按钮必然 AttributeError。迁到 `QmlDialog`（真 QDialog）后这条路径才成立。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from core.logger import log
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["CharacterUsageBridge", "CharacterUsageQmlDialog"]

_QML_FILE = "dialogs/CharUsageDialog.qml"


class CharacterUsageBridge(DialogBridge):
    """人物占用情况的 QML 后端。"""

    #: 单一通知源（QML 侧一次重读两个属性，与 `SummaryTableBridge.contentChanged` 同款）
    contentChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._blocks: list[dict] = []
        self._summary = ""
        self.set_title("人物占用情况")

    #: 每人物一块（形状见 `ui_qml.bridge.occupancy`）
    occupancyByChar = Property(list, lambda self: list(self._blocks), notify=contentChanged)
    occupancySummary = Property(str, lambda self: self._summary, notify=contentChanged)

    @Slot()
    def reload(self) -> None:
        """读全部「已规划」计划 → 算块数据。同步取数（一次查询 + 一次技能配置读），不起线程。"""
        from services.char_capacity import PLANNED_STATUSES, char_line_usage
        from services.plan_service import load_plans_for_wizard
        from ui_qml.bridge.occupancy import build_occupancy_blocks, occupancy_summary

        try:
            plans = list(load_plans_for_wizard() or [])
        except Exception:
            # 吞的是「读 user.db 失败」（库被占用 / 表结构不符）—— 对话框不该整块空白，
            # 至少把原因摆在摘要行上，别让用户对着一个没人的空面板猜。
            log.exception("人物占用读取失败")
            self._blocks = []
            self._summary = "读取生产计划失败，详见日志"
            self.contentChanged.emit()
            return

        per_char, _line_caps = char_line_usage(plans, statuses=PLANNED_STATUSES)
        if not per_char:
            self._blocks = []
            self._summary = "无人物配置，请在人物设置中添加"
        else:
            self._blocks = build_occupancy_blocks(per_char, plans)
            self._summary = occupancy_summary(per_char, label="已规划")
        self.contentChanged.emit()


class CharacterUsageQmlDialog(QmlDialog):
    """QML 版「人物占用情况」。`CharacterUsageDialog(parent)` 的调用方原样可用。

    只读查看器 → **非模态独立窗**（`modeless=True`），调用方用 `show()` 而非 `exec()`。
    """

    def __init__(self, parent: Any = None) -> None:
        bridge = CharacterUsageBridge()
        super().__init__(_QML_FILE, bridge, parent=parent, size=(820, 480), modeless=True)
        # `QmlDialog` 不替子类加载数据（通用汇总表那条路才在构造末尾 reload）——
        # 这里自己调一次，QML 侧的绑定会随 `contentChanged` 拿到块数据。
        bridge.reload()
