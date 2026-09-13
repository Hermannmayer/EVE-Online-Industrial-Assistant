"""甘特图组件 — QPainter 自定义绘制

排期口径（见 `load_from_plans`）：行序取计划树序（母项在前、子项紧随），
时间上**子项先跑、母项接在其后** —— 母项依赖子项产出，不能一起开跑。
柱形条末端标出预计完成时刻。
"""

from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

import ui_pyside6.theme as theme


class GanttView(QWidget):
    """生产计划甘特图 — QPainter 自定义绘制"""

    ROW_HEIGHT = 32
    LABEL_WIDTH = 200
    HEADER_HEIGHT = 40
    # 末端「预计完成时刻」的占位样本：按它的实际像素宽预留右侧空间，
    # 否则最长的柱形条会顶到控件右边界，把标签挤出可视区
    END_TIME_SAMPLE = "99-99 99:99"
    GRID_COLOR = None  # 在 _on_theme_changed 设置
    BG_COLOR = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []
        self._colors = self._palette()
        self._max_hours: int = 48
        self.GRID_COLOR = QColor(theme.BORDER)
        self.BG_COLOR = QColor(theme.BG_SURFACE)
        theme.add_theme_listener(self._on_theme_changed)

    @staticmethod
    def _palette() -> list:
        return [
            theme.PRIMARY,
            theme.ACCENT_GREEN,
            theme.ACCENT_ORANGE,
            theme.ACCENT_CYAN,
            theme.ACCENT_RED,
            theme.ACCENT_PURPLE,
        ]

    def set_items(self, items: list[dict]):
        self._items = items
        self._max_hours = int(max((i.get("duration", 1) + i.get("start", 0) for i in items), default=48))
        self._max_hours = max(self._max_hours, 24)
        # 向上取整到 12 的倍数
        self._max_hours = ((self._max_hours + 11) // 12) * 12
        self.update()

    def clear(self):
        self._items = []
        self._max_hours: int = 48
        self.update()

    def load_from_plans(self, plans: list[dict]):
        """把计划列表排成「按 BOM 依赖串行」的甘特条。

        - **行序**用 `group_and_sort_plans`：母项在前、子项紧随其后（与项目其它视图的树序一致）。
          合成根行（共享组件占位，`id is None`）不是真实计划，跳过不画。
        - **时间**上子项先跑（同组子项之间并行、都从 0 起），母项接在全部子项结束之后。
        """
        from services.plan_service import group_and_sort_plans

        ordered = [p for p in group_and_sort_plans(list(plans)) if p.get("id") is not None]
        rows: list[dict] = []
        for i, plan in enumerate(ordered):
            calculated = plan.get("calculated_time", 0) or 0
            if calculated > 0:
                hours = calculated / 3600  # 秒 → 小时
            else:
                hours = plan.get("runs", 1) * plan.get("parallels", 1) * 2  # 兜底占位
            rows.append(
                {
                    "name": plan.get("product_name", f"计划#{plan.get('id', i)}"),
                    "start": 0.0,
                    "duration": float(hours),
                    "color": self._colors[i % len(self._colors)],
                    "plan": plan,  # 供 paintEvent 算末端完成时刻（状态 / started_at）
                }
            )
        self._apply_dependencies(rows)
        self.set_items(rows)

    @staticmethod
    def _apply_dependencies(rows: list[dict]) -> None:
        """同组内按 `component_parent_type_id` 建依赖边：父项 start = max(子项 end)。

        子项都是叶子 → 从 0 起跑；每一层的父项被推到子项结束之后。
        用**松弛迭代**而不是递归：BOM 层数未知，迭代天然能容忍环（轮数上界 = 行数）。
        **跨组不串行** —— 不同 group_number 是不同产品，各自从 0 起。
        """
        by_group: dict[int, list[dict]] = {}
        for row in rows:
            plan = row["plan"]
            gid = int(plan.get("group_id") or plan.get("group_number") or 0)
            by_group.setdefault(gid, []).append(row)

        for gid, members in by_group.items():
            if not gid:  # 独立计划：各自从 0 起跑
                continue
            by_tid = {int(m["plan"].get("product_type_id") or 0): m for m in members}
            mother = next((m for m in members if GanttView._level(m["plan"]) == 0), None)

            for _ in range(len(members)):
                changed = False
                for row in members:
                    parent = GanttView._parent_row(row, by_tid, mother)
                    if parent is None:
                        continue
                    end = row["start"] + row["duration"]
                    if end > parent["start"]:
                        parent["start"] = end
                        changed = True
                if not changed:
                    break

    @staticmethod
    def _parent_row(row: dict, by_tid: dict, mother: dict | None) -> dict | None:
        """行在时间上的前驱：同组内 `component_parent_type_id` 指向的那一行。

        缺失 / 指回自己 → 回退该组的母项；母项自己 → None（没有前驱）。
        """
        ptid = row["plan"].get("component_parent_type_id")
        parent = by_tid.get(int(ptid)) if ptid else None
        if parent is None or parent is row:
            parent = mother
        return None if parent is row else parent

    @staticmethod
    def _level(plan: dict) -> int:
        return int(plan.get("child_level") or plan.get("sub_level") or 0)

    @staticmethod
    def _end_time_text(plan: dict, end_hours: float, now: datetime | None = None) -> str:
        """柱形条末端的预计完成时刻（**本地时区** MM-DD HH:MM）。

        - 在产计划给**真实 ETA**：`started_at + calculated_time`，与倒计时列同一实现
          （`plan_execution.remaining_seconds`），只是换算到本地时区再显示 ——
          库里 `started_at` 存的是 naive UTC，直接显示会差一个时区。
        - 其余按「现在开工」推算：本地当前时间 + 排期结束偏移。
        """
        from services.plan_execution import remaining_seconds

        now_utc = now or datetime.now(UTC)
        if str(plan.get("status") or "").lower() in ("in_progress", "running"):
            rem = remaining_seconds(plan, now=now_utc)
            if rem is not None:
                return (now_utc + timedelta(seconds=rem)).astimezone().strftime("%m-%d %H:%M")
        local_now = now_utc.astimezone().replace(tzinfo=None)
        return (local_now + timedelta(hours=end_hours)).strftime("%m-%d %H:%M")

    def minimumSizeHint(self):
        w = self.LABEL_WIDTH + self._max_hours * 12
        h = self.HEADER_HEIGHT + len(self._items) * self.ROW_HEIGHT + 10
        return QSize(max(w, 400), max(h, 200))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景
        painter.fillRect(self.rect(), self.BG_COLOR)

        if not self._items:
            painter.setPen(QColor(theme.TEXT_SECONDARY))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无数据")
            return

        # 绘制时间刻度
        painter.setPen(QPen(QColor(theme.TEXT_SECONDARY), 1))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        # 计算时间轴比例。末端标签要贴在条右侧，必须先把它的宽度从可用宽度里扣掉，
        # 否则最长的条会顶到右边界、标签被挤出可视区。
        end_label_w = painter.fontMetrics().horizontalAdvance(self.END_TIME_SAMPLE) + 8
        total_w = self.width() - self.LABEL_WIDTH - 10 - end_label_w
        if total_w < 50:
            return
        # 刻度线与柱形条共用这一个比例，改分母时不要只改一处
        px_per_hour = total_w / self._max_hours

        for h in range(0, self._max_hours + 1, 12):
            x = self.LABEL_WIDTH + h * px_per_hour
            painter.drawText(int(x - 15), 5, 30, 15, Qt.AlignmentFlag.AlignCenter, f"{h}h")
            # 垂直网格线
            painter.setPen(QPen(self.GRID_COLOR, 1, Qt.PenStyle.DotLine))
            painter.drawLine(int(x), self.HEADER_HEIGHT, int(x), self.height())
            painter.setPen(QPen(QColor(theme.TEXT_SECONDARY), 1))

        now_utc = datetime.now(UTC)

        # 绘制行
        for row, item in enumerate(self._items):
            y = self.HEADER_HEIGHT + row * self.ROW_HEIGHT

            # 水平网格线
            painter.setPen(QPen(self.GRID_COLOR, 1))
            painter.drawLine(self.LABEL_WIDTH, y, self.width(), y)

            # 标签
            painter.setPen(QColor(theme.TEXT_PRIMARY))
            label_rect = QRectF(5, y, self.LABEL_WIDTH - 10, self.ROW_HEIGHT)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, item["name"])

            # 条形
            start_hours = float(item.get("start", 0) or 0)
            duration = float(item.get("duration", 1) or 0)
            start_x = self.LABEL_WIDTH + start_hours * px_per_hour
            bar_w = max(duration * px_per_hour, 4)
            bar_h = self.ROW_HEIGHT - 6
            bar_y = y + 3
            color = item.get("color", theme.PRIMARY)
            painter.fillRect(QRectF(start_x, bar_y, bar_w, bar_h), color)

            # 时长文字（条内）
            painter.setPen(QColor(theme.TEXT_ON_PRIMARY))
            if bar_w > 40:
                dur_text = f"{duration:.0f}h"
                painter.drawText(QRectF(start_x + 2, bar_y, bar_w - 4, bar_h), Qt.AlignmentFlag.AlignCenter, dur_text)

            # 末端预计完成时刻（条外右侧）
            plan = item.get("plan")
            if plan:
                painter.setPen(QColor(theme.TEXT_PRIMARY))
                painter.drawText(
                    QRectF(start_x + bar_w + 4, bar_y, end_label_w, bar_h),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    self._end_time_text(plan, start_hours + duration, now_utc),
                )

        painter.end()

    def _on_theme_changed(self):
        """主题切换时刷新 QPainter 绘制颜色"""
        self.GRID_COLOR = QColor(theme.BORDER)
        self.BG_COLOR = QColor(theme.BG_SURFACE)
        self._colors = self._palette()
        self.update()
