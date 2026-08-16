"""产线启动小助手 v2 — 可置顶悬浮的紧凑工具窗。

竖分三段：顶部(占用/双下拉) 固定 · 中部(产线列表) 随高度伸缩 · 底部(反馈/启动/状态栏) 固定。
实时刷新：1s 内存 tick（运行中行剩余时长）+ 5s DB 轮询（计划增删改自动同步）。
启动即分流：底部"执行人物"下拉选定游戏里实际开工的人物，复用 char_name 回写。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from core.container import get_container
from core.logger import log
from services import plan_execution
from services.char_capacity import (
    CAPACITY_LINE_MANUFACTURING,
    CAPACITY_LINE_REACTION,
    CAPACITY_LINE_RESEARCH,
    active_lines_by_category,
    capacity_line_for_category,
    line_label,
    max_lines_for_category,
)
from services.char_config_resolver import get_character_list, load_all_data
from services.plan_service import group_and_sort_plans, load_plans_for_wizard
from services.plan_start_check import plan_start_block_reason
from ui_pyside6.icon_cache import load_item_icon
from ui_pyside6.pin_utils import apply_window_pin

MAX_SLOTS_PER_LINE = 11  # 单行每类产线最大格块数（技能满级 1+5+5）
_NAME_W = 76  # 占用区角色名固定宽（保证产线方块跨行对齐）

_LINE_TYPES = (CAPACITY_LINE_MANUFACTURING, CAPACITY_LINE_RESEARCH, CAPACITY_LINE_REACTION)
_LINE_COLORS = {
    CAPACITY_LINE_MANUFACTURING: "ACCENT_GREEN",
    CAPACITY_LINE_RESEARCH: "ACCENT_CYAN",
    CAPACITY_LINE_REACTION: "ACCENT_PURPLE",
}

_STATUS_LABELS = {
    "pending": "待生产",
    "in_progress": "生产中",
    "running": "生产中",
    "ready": "待下线",
    "completed": "已完成",
    "done": "已完成",
}


def _fmt_hms(seconds) -> str:
    """秒 → HH:MM:SS（<1 小时也显示 HH:MM:SS，保持行内对齐）。"""
    seconds = max(int(seconds or 0), 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_remaining(plan: dict) -> str:
    """运行中计划剩余时长文本。"""
    rem = plan_execution.remaining_seconds(plan)
    if rem is None:
        return ""
    if rem <= 0:
        return "已超时"
    return _fmt_hms(rem)


def _default_mat_hangar_id() -> int | None:
    """默认材料机库（settings.default_mat_hangar_id）。"""
    from services import inventory_manager

    return inventory_manager.get_default_mat_hangar_and_system()[0]


class CapacitySlotBar(QWidget):
    """占用区单行：角色名 + 制造/科研/反应 各 11 格 + 状态。

    paintEvent 自绘；技能不满时超过容量的槽位画暗格（锁定），占用超容量标红。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(26)
        self._char_name = ""
        self._usage: dict[str, tuple[int, int]] = {}
        theme.add_theme_listener(self._on_theme_changed)

    def set_usage(self, char_name: str, usage: dict[str, tuple[int, int]]) -> None:
        self._char_name = char_name or "(未分配)"
        self._usage = usage
        self.update()

    def _on_theme_changed(self):
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        x = 8
        name_font = QFont()
        name_font.setBold(True)
        p.setFont(name_font)
        p.setPen(QColor(theme.TEXT_PRIMARY))
        # 固定宽角色名列 → 不同名字长度下产线方块仍对齐
        name_elided = QFontMetrics(name_font).elidedText(self._char_name, Qt.TextElideMode.ElideRight, _NAME_W)
        p.drawText(QRect(x, 0, _NAME_W, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name_elided)
        x += _NAME_W + 12

        active_total = 0
        max_total = 0
        block_w, block_h, gap = 7, 14, 3
        stride = block_w + gap
        radius = 3
        top = (h - block_h) // 2
        for line in _LINE_TYPES:
            active, mx = self._usage.get(line, (0, 0))
            active_total += active
            max_total += mx
            p.setFont(QFont())
            p.setPen(QColor(getattr(theme, _LINE_COLORS[line])))
            p.drawText(QRect(x, 0, 28, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, line_label(line))
            x += 32
            base = QColor(getattr(theme, _LINE_COLORS[line]))
            for i in range(MAX_SLOTS_PER_LINE):
                rect = QRectF(x, top, block_w, block_h)
                if i < mx:
                    if i < active:
                        # 占用：渐变填充 + 圆角（去锯齿）
                        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                        grad.setColorAt(0.0, base.lighter(135))
                        grad.setColorAt(1.0, base.darker(110))
                        p.setBrush(grad)
                        p.setPen(QPen(base.darker(135), 1))
                    else:
                        # 空闲（容量内）：浅底 + 低透明度描边
                        p.setBrush(QColor(theme.BG_SURFACE))
                        p.setPen(QPen(QColor(base.red(), base.green(), base.blue(), 65), 1))
                    p.drawRoundedRect(rect, radius, radius)
                else:
                    # 锁定（超出技能容量）：几乎不可见的暗格
                    p.setBrush(QColor(theme.BG_SURFACE_LIGHT))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawRoundedRect(rect, radius, radius)
                x += stride
            x += 6

        # 右侧状态
        x += 4
        p.setFont(QFont())
        if active_total > max_total:
            text = f"超员 +{active_total - max_total}"
            p.setPen(QColor(theme.ACCENT_RED))
        elif active_total == 0:
            text = "空闲"
            p.setPen(QColor(theme.ACCENT_GREEN))
        else:
            text = "生产中"
            p.setPen(QColor(theme.PRIMARY))
        p.drawText(x, 0, 200, h, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        p.end()


class PlanRow(QWidget):
    """中部列表行：[图标][三行信息(可点击复制)][启动按钮/等待/留白]。"""

    clicked = Signal(int)  # 点信息区 → 复制蓝图名
    start_requested = Signal(int)  # 点启动按钮
    toggle_requested = Signal(int)  # 点折叠/展开（传 group_id）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plan: dict = {}
        self._plan_id: int | None = None
        self._last_reason: str | None = None
        self._last_pending: int = 0
        self._last_collapsed: bool = False
        self.setMinimumHeight(46)

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 1, 4, 1)
        root.setSpacing(6)

        self._icon = QLabel()
        self._icon.setFixedSize(28, 28)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._icon)

        info = QVBoxLayout()
        info.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(6)
        self._name = QLabel("")
        self._name.setStyleSheet(f"color: {theme.TEXT_BRIGHT}; font-size: 13px; font-weight: bold;")
        top.addWidget(self._name)
        self._status = QLabel("")
        top.addWidget(self._status)
        top.addStretch(1)
        info.addLayout(top)

        self._duration = QLabel("")
        self._duration.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        info.addWidget(self._duration)
        self._process = QLabel("")
        self._process.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        info.addWidget(self._process)
        root.addLayout(info, 1)

        self._btn_start = QPushButton("▶ 启动")
        self._btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.setFixedWidth(72)
        self._btn_start.clicked.connect(self._on_start_clicked)
        self._btn_toggle = QPushButton("")
        self._btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_toggle.setFixedWidth(86)
        self._btn_toggle.clicked.connect(self._on_toggle_clicked)
        self._action_box = QHBoxLayout()
        self._action_box.addWidget(self._btn_start)
        self._action_box.addWidget(self._btn_toggle)
        root.addLayout(self._action_box)

        theme.add_theme_listener(self._on_theme_changed)
        self._style_toggle()

    def _on_start_clicked(self):
        if self._plan_id is not None:
            self.start_requested.emit(self._plan_id)

    def _on_toggle_clicked(self):
        gid = int(self._plan.get("group_id") or self._plan.get("group_number") or 0)
        if gid:
            self.toggle_requested.emit(gid)

    def set_plan(
        self, plan: dict, *, block_reason: str | None, pending_children: int = 0, collapsed: bool = False
    ) -> None:
        self._plan = plan
        self._plan_id = plan.get("id")
        self._last_reason = block_reason
        self._last_pending = pending_children
        self._last_collapsed = collapsed
        status = (plan.get("status") or "").lower()
        level = int(plan.get("child_level") or 0)
        name = plan.get("product_name") or f"ID:{plan.get('product_type_id', '')}"
        prefix = "◆ " if level == 0 else "  " * level + "▸ "
        self._name.setText(prefix + name)

        color_map = {
            "pending": theme.TEXT_SECONDARY,
            "in_progress": theme.PRIMARY,
            "running": theme.PRIMARY,
            "ready": theme.ACCENT_ORANGE,
            "completed": theme.TEXT_SECONDARY,
            "done": theme.TEXT_SECONDARY,
        }
        label = _STATUS_LABELS.get(status, status)
        self._status.setText(label)
        self._status.setStyleSheet(f"color: {color_map.get(status, theme.TEXT_SECONDARY)}; font-size: 11px;")

        total = int(plan.get("calculated_time") or 0)
        loc = self._location_text(plan)
        if status in ("in_progress", "running"):
            rem = _fmt_remaining(plan)
            dur = f"剩余 {rem} / {_fmt_hms(total)}" if rem else _fmt_hms(total)
        elif status == "ready":
            dur = "待下线"
        else:
            dur = _fmt_hms(total)
        self._duration.setText(f"{dur} {loc}")

        runs = plan.get("runs", 1)
        parallels = plan.get("parallels", 1)
        cat = capacity_line_for_category(str(plan.get("category") or ""))
        self._process.setText(
            f"流程：{runs} x{parallels} · {line_label(cat)} · 人物 {plan.get('char_name') or '未分配'}"
        )

        self._load_icon(plan)

        # 操作区：母项有未完成子项 → 折叠/展开按钮；可启动 → 启动按钮；否则留白
        self._name.setStyleSheet(f"color: {theme.TEXT_BRIGHT}; font-size: 13px; font-weight: bold;")
        self.setStyleSheet("background-color: transparent;")
        if level == 0 and pending_children > 0:
            self._btn_start.hide()
            self._btn_toggle.setText(("▸ 展开" if collapsed else "▾ 折叠") + f"({pending_children})")
            self._btn_toggle.show()
        elif block_reason is None and status == "pending":
            self._btn_toggle.hide()
            self._btn_start.show()
        else:
            self._btn_start.hide()
            self._btn_toggle.hide()

    def _style_toggle(self):
        self._btn_toggle.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.PRIMARY};"
            f" border: 1px solid {theme.PRIMARY}; border-radius: 4px;"
            f" font-size: 11px; padding: 1px 4px; }}"
            f"QPushButton:hover {{ background: {theme.BG_HOVER}; }}"
        )

    def _location_text(self, plan: dict) -> str:
        src = plan.get("facility") or ""
        dst = plan.get("output_hangar") or ""
        if src and dst:
            return f"({src}→{dst})"
        if src:
            return f"({src})"
        return ""

    def _load_icon(self, plan: dict) -> None:
        pix = load_item_icon(int(plan.get("product_type_id") or 0), 32)
        if pix is not None:
            self._icon.setPixmap(pix)
            self._icon.setToolTip("")
        else:
            from services.plan_category import category_symbol

            self._icon.setText(category_symbol(str(plan.get("category") or "")))
            self._icon.setToolTip("无图标")

    def update_tick(self) -> None:
        """仅运行中行：刷新剩余时长（不重建行）。"""
        plan = self._plan
        if not plan:
            return
        status = (plan.get("status") or "").lower()
        if status not in ("in_progress", "running"):
            return
        total = int(plan.get("calculated_time") or 0)
        rem = _fmt_remaining(plan)
        dur = f"剩余 {rem} / {_fmt_hms(total)}" if rem else _fmt_hms(total)
        self._duration.setText(f"{dur} {self._location_text(plan)}")

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self._plan_id is not None:
            self.clicked.emit(self._plan_id)

    def _on_theme_changed(self):
        self._style_toggle()
        if self._plan:
            self.set_plan(
                self._plan,
                block_reason=self._last_reason,
                pending_children=self._last_pending,
                collapsed=self._last_collapsed,
            )


class ProductionLauncher(QWidget):
    """产线启动小助手 — 非模态紧凑工具窗。"""

    plans_changed = Signal()  # 启动成功后触发，供主窗口刷新

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("产线启动小助手")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(560, 700)
        self.setMinimumSize(480, 520)

        self._all_plans: list[dict] = []
        self._visible_plans: list[dict] = []
        self._plan_map: dict[int, dict] = {}
        self._widgets: dict[int, PlanRow] = {}
        self._row_order: list[int] = []
        self._bp_names: dict[int, str] = {}
        self._usage: dict[str, dict[str, int]] = {}
        self._shortfall_cache: dict[int, tuple] = {}
        self._collapsed: set[int] = set()  # 已折叠的组号（隐藏其子项）
        self._selected_id: int | None = None
        self._default_mat_hangar = _default_mat_hangar_id()
        self._char_list = get_character_list()

        self._build_ui()
        theme.add_theme_listener(self._on_theme_changed)
        self._on_theme_changed()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start()

        self._on_poll()
        self._restore_pin()

    # ── UI ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 2, 4, 4)
        root.setSpacing(4)

        # ── 顶部（固定） ──
        top = QVBoxLayout()
        top.setSpacing(3)

        title_row = QHBoxLayout()
        title = QLabel("产线启动小助手")
        title.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 14px; font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self._pin_btn = QToolButton()
        self._pin_btn.setText("📌 置顶")
        self._pin_btn.setCheckable(True)
        self._pin_btn.setToolTip("切换窗口置顶（悬浮于游戏之上）")
        self._pin_btn.toggled.connect(self._on_pin_toggled)
        title_row.addWidget(self._pin_btn)
        top.addLayout(title_row)

        filter_row = QHBoxLayout()
        self._line_filter = QComboBox()
        self._line_filter.addItem("全部线型", None)
        self._line_filter.addItem("制造", CAPACITY_LINE_MANUFACTURING)
        self._line_filter.addItem("科研", CAPACITY_LINE_RESEARCH)
        self._line_filter.addItem("反应", CAPACITY_LINE_REACTION)
        self._line_filter.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._line_filter)
        self._char_filter = QComboBox()
        filter_row.addWidget(self._char_filter)
        self._rebuild_char_filter()
        self._char_filter.currentIndexChanged.connect(self._on_filter_changed)
        top.addLayout(filter_row)

        occ_scroll = QScrollArea()
        occ_scroll.setWidgetResizable(True)
        occ_scroll.setFrameShape(QFrame.Shape.NoFrame)
        occ_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        occ_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        occ_container = QWidget()
        self._occ_layout = QVBoxLayout(occ_container)
        self._occ_layout.setContentsMargins(0, 0, 0, 0)
        self._occ_layout.setSpacing(1)
        self._occ_layout.addStretch(1)
        occ_scroll.setWidget(occ_container)
        top.addWidget(occ_scroll, 1)
        root.addLayout(top, 0)
        self._occ_scroll = occ_scroll
        self._occ_container = occ_container

        # ── 中部（随高度伸缩） ──
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setSpacing(2)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._list, 1)

        # ── 底部（固定，独立面板） ──
        self._bottom_panel = QFrame(self)
        self._bottom_panel.setObjectName("launcher_bottom")
        bottom = QVBoxLayout(self._bottom_panel)
        bottom.setContentsMargins(10, 6, 10, 6)
        bottom.setSpacing(5)

        self._feedback = QLabel("")
        self._feedback.setMinimumHeight(16)
        self._feedback.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        bottom.addWidget(self._feedback)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {theme.BORDER}; background-color: {theme.BORDER};")
        bottom.addWidget(sep)

        mid = QHBoxLayout()
        mid.setSpacing(10)
        params_box = QVBoxLayout()
        params_box.setSpacing(3)
        self._params_label = QLabel("")
        self._params_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._params_label.setWordWrap(True)
        params_box.addWidget(self._params_label)
        self._executor_combo = QComboBox()
        params_box.addWidget(self._executor_combo)
        mid.addLayout(params_box, 2)
        self._main_btn = QPushButton("")
        self._main_btn.setMinimumHeight(36)
        self._main_btn.clicked.connect(self._on_main_start)
        mid.addWidget(self._main_btn, 3)
        bottom.addLayout(mid)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._status_icon = QLabel("")
        self._status_icon.setFixedSize(20, 20)
        self._status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_icon.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 13px;")
        status_row.addWidget(self._status_icon)
        self._status_duration = QLabel("")
        self._status_duration.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 14px; font-weight: bold;")
        status_row.addWidget(self._status_duration)
        status_row.addStretch(1)
        self._status_cost = QLabel("")
        self._status_cost.setStyleSheet(f"color: {theme.ACCENT_GREEN}; font-size: 15px; font-weight: bold;")
        status_row.addWidget(self._status_cost)
        bottom.addLayout(status_row)

        root.addWidget(self._bottom_panel, 0)

    def _rebuild_char_filter(self) -> None:
        self._char_filter.blockSignals(True)
        self._char_filter.clear()
        self._char_filter.addItem("全部人物", None)
        self._char_filter.addItem("未分配", "")
        for name in self._char_list:
            self._char_filter.addItem(name, name)
        self._char_filter.blockSignals(False)

    def _apply_style(self) -> None:
        self._list.setStyleSheet(
            f"QListWidget {{ background: {theme.BG_DARK}; border: 1px solid {theme.BORDER};"
            f" border-radius: 6px; outline: none; }}"
            f"QListWidget::item {{ border-bottom: 1px solid {theme.BORDER}; }}"
            f"QListWidget::item:selected {{ background: {theme.PRIMARY}; }}"
        )

    def _style_main_button(self) -> None:
        # 主启动按钮：由 theme 色派生渐变（醒目）
        base = QColor(theme.ACCENT_GREEN)
        top = base.lighter(118).name()
        mid = base.name()
        bot = base.darker(112).name()
        self._main_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {top}, stop:0.5 {mid}, stop:1 {bot});"
            f" color: {theme.TEXT_ON_PRIMARY}; border: 1px solid {bot}; border-radius: 6px;"
            f" font-size: 13px; font-weight: bold; padding: 7px 12px; }}"
            f"QPushButton:hover {{ border: 1px solid {theme.TEXT_ON_PRIMARY}; }}"
            f"QPushButton:pressed {{ background: {bot}; }}"
        )

    def _on_theme_changed(self):
        self._apply_style()
        self._bottom_panel.setStyleSheet(
            f"#launcher_bottom {{ background-color: {theme.BG_SURFACE};"
            f" border-top: 1px solid {theme.BORDER}; border-radius: 0 0 6px 6px; }}"
        )
        self._feedback.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._params_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        self._style_main_button()
        self._status_icon.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 13px;")
        self._status_duration.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 14px; font-weight: bold;")
        self._status_cost.setStyleSheet(f"color: {theme.ACCENT_GREEN}; font-size: 15px; font-weight: bold;")
        if self._occ_container:
            for child in self._occ_container.findChildren(CapacitySlotBar):
                child._on_theme_changed()

    # ── 置顶 ─────────────────────────────────────────────

    def _on_pin_toggled(self, checked: bool):
        apply_window_pin(self, checked)
        from services.user_settings import save_settings

        try:
            save_settings({"production_launcher_pin": checked})
        except Exception:
            pass

    def _restore_pin(self) -> None:
        try:
            from services.user_settings import load_settings

            if load_settings().get("production_launcher_pin"):
                self._pin_btn.setChecked(True)
                apply_window_pin(self, True)
        except Exception:
            pass

    # ── 数据刷新 ─────────────────────────────────────────

    def _on_poll(self) -> None:
        """5s 轮询：补算过期 + 重载非完成计划 + 刷新占用/列表。"""
        try:
            plan_execution.expire_overdue_plans()
            self._all_plans = load_plans_for_wizard()
        except Exception:
            log.exception("产线小助手轮询失败")
            return
        self._load_blueprint_names()
        self._refresh_occupancy()
        self._apply_filters()

    def _on_tick(self) -> None:
        for pid, w in self._widgets.items():
            plan = self._plan_map.get(pid)
            if plan and (plan.get("status") or "").lower() in ("in_progress", "running"):
                w.update_tick()

    def _load_blueprint_names(self) -> None:
        from services.ui_data_service import get_item_names_batch

        bp_ids = {
            int(p["blueprint_type_id"])
            for p in self._all_plans
            if p.get("blueprint_type_id") and p.get("blueprint_type_id") not in self._bp_names
        }
        if bp_ids:
            self._bp_names.update(get_item_names_batch(list(bp_ids), db=get_container().db))

    def _refresh_occupancy(self) -> None:
        self._usage = active_lines_by_category(self._all_plans)
        data = load_all_data()
        chars_data = data.get("characters", {}) or {}
        chars = list(self._char_list)
        for c in self._usage:
            if c and c not in chars:
                chars.append(c)

        while self._occ_layout.count():
            item = self._occ_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()

        if not chars:
            hint = QLabel("（无人物配置，请在人物设置中添加）")
            hint.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
            self._occ_layout.addWidget(hint)
            self._occ_layout.addStretch(1)
            return

        for char in chars:
            skills = (chars_data.get(char, {}) or {}).get("skills", {}) or {}
            usage = self._usage.get(char or "", {})
            per_line: dict[str, tuple[int, int]] = {}
            for line in _LINE_TYPES:
                mx = max_lines_for_category(char, line, skills=skills)
                active = usage.get(line, 0)
                per_line[line] = (active, mx)
            bar = CapacitySlotBar(self._occ_container)
            bar.set_usage(char, per_line)
            self._occ_layout.addWidget(bar)
        self._occ_layout.addStretch(1)

    def _match_filters(self, plan: dict) -> bool:
        line = self._line_filter.currentData()
        if line and capacity_line_for_category(str(plan.get("category") or "")) != line:
            return False
        char = self._char_filter.currentData()
        if char is None:
            return True
        plan_char = (plan.get("char_name") or "").strip()
        return bool(plan_char == char)

    def _apply_filters(self) -> None:
        full = group_and_sort_plans(self._all_plans)
        # 自动展开：子项全部完成（_pending_children==0）的组不再折叠
        for p in full:
            gid = int(p.get("group_id") or 0)
            if gid and int(p.get("child_level") or 0) == 0 and not p.get("_pending_children"):
                self._collapsed.discard(gid)
        visible = [p for p in full if self._match_filters(p) and not self._is_collapsed_child(p)]
        self._visible_plans = visible
        self._sync_rows(visible)
        self._update_bottom()

    def _is_collapsed_child(self, plan: dict) -> bool:
        gid = int(plan.get("group_id") or plan.get("group_number") or 0)
        return bool(gid and int(plan.get("child_level") or plan.get("sub_level") or 0) > 0 and gid in self._collapsed)

    # ── 列表同步 ─────────────────────────────────────────

    def _shortfall_count(self, plan: dict) -> int:
        """材料缺口种数（指纹缓存，避免每轮全量评分）。"""
        pid = int(plan.get("id") or 0)
        fp = (
            plan.get("status"),
            plan.get("runs"),
            plan.get("parallels"),
            plan.get("me_level"),
            plan.get("te_level"),
            plan.get("char_name"),
            plan.get("mat_hangar_id"),
        )
        cached = self._shortfall_cache.get(pid)
        if cached and cached[0] == fp:
            return int(cached[1])
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar
        count = 0
        if (plan.get("status") or "").lower() == "pending" and mat:
            try:
                missing = [r for r in plan_execution.check_materials(plan, mat) if (r.get("missing") or 0) > 0]
                count = len(missing)
            except Exception:
                count = 0
        self._shortfall_cache[pid] = (fp, count)
        return count

    def _block_reason(self, plan: dict) -> str | None:
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar
        return plan_start_block_reason(plan, mat, self._all_plans, shortfall_count=self._shortfall_count(plan))

    def _row_collapsed(self, plan: dict) -> bool:
        gid = int(plan.get("group_id") or plan.get("group_number") or 0)
        return bool(gid and gid in self._collapsed)

    def _sync_rows(self, visible: list[dict]) -> None:
        new_ids = [int(p.get("id") or 0) for p in visible]
        if new_ids == self._row_order:
            for plan in visible:
                w = self._widgets.get(int(plan.get("id") or 0))
                if w is not None:
                    self._plan_map[int(plan.get("id") or 0)] = plan
                    w.set_plan(
                        plan,
                        block_reason=self._block_reason(plan),
                        pending_children=int(plan.get("_pending_children") or 0),
                        collapsed=self._row_collapsed(plan),
                    )
            return
        self._rebuild_rows(visible)

    def _rebuild_rows(self, visible: list[dict]) -> None:
        sel_id = self._selected_id
        scroll = self._list.verticalScrollBar().value() if self._list.verticalScrollBar() else 0
        self._list.clear()
        self._widgets.clear()
        self._plan_map.clear()
        self._row_order = [int(p.get("id") or 0) for p in visible]

        if not visible:
            empty = QLabel("该角色无产线计划")
            empty.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            item = QListWidgetItem()
            item.setSizeHint(empty.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, empty)
            self._selected_id = None
            return

        for plan in visible:
            pid = int(plan.get("id") or 0)
            self._plan_map[pid] = plan
            row = PlanRow(self._list)
            row.clicked.connect(self._on_row_clicked)
            row.start_requested.connect(self._on_row_start)
            row.toggle_requested.connect(self._on_row_toggle)
            row.set_plan(
                plan,
                block_reason=self._block_reason(plan),
                pending_children=int(plan.get("_pending_children") or 0),
                collapsed=self._row_collapsed(plan),
            )
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, pid)
            item.setSizeHint(row.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, row)
            self._widgets[pid] = row

        if sel_id is not None and sel_id in self._widgets:
            for i in range(self._list.count()):
                it = self._list.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == sel_id:
                    self._list.setCurrentItem(it)
                    break

        if self._list.verticalScrollBar():
            self._list.verticalScrollBar().setValue(scroll)

    def _on_row_clicked(self, plan_id: int):
        self._copy_blueprint(plan_id)

    def _on_row_start(self, plan_id: int):
        # 行内启动：先让该行成为选中 → 执行人物组合框跟随该计划
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == plan_id:
                self._list.setCurrentItem(it)
                break
        self._start(plan_id)

    def _on_row_toggle(self, group_id: int) -> None:
        """折叠/展开一组子项。"""
        if group_id in self._collapsed:
            self._collapsed.discard(group_id)
        else:
            self._collapsed.add(group_id)
        self._apply_filters()

    # ── 选中 / 底部 ──────────────────────────────────────

    def _on_selection_changed(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid is not None:
            self._selected_id = int(pid)
            self._update_bottom()

    def _update_bottom(self) -> None:
        plan = self._plan_map.get(self._selected_id or -1)
        if plan is None:
            self._params_label.setText("选中一行查看参数")
            self._main_btn.hide()
            self._status_icon.setText("")
            self._status_duration.setText("")
            self._status_cost.setText("")
            self._executor_combo.clear()
            return

        cat = capacity_line_for_category(str(plan.get("category") or ""))
        runs = plan.get("runs", 1)
        parallels = plan.get("parallels", 1)
        facility = plan.get("facility") or "—"
        output = plan.get("output_hangar") or "—"
        self._params_label.setText(f"{line_label(cat)} · 流程 {runs} x{parallels}\n{facility} → {output}")

        # 执行人物下拉（含剩余容量）
        self._executor_combo.blockSignals(True)
        self._executor_combo.clear()
        chars = list(self._char_list)
        plan_char = (plan.get("char_name") or "").strip()
        if plan_char and plan_char not in chars:
            chars.insert(0, plan_char)
        for name in chars:
            remaining = max_lines_for_category(name, cat) - int(self._usage.get(name or "", {}).get(cat, 0))
            self._executor_combo.addItem(f"{name} (剩 {max(remaining, 0)} 条)", name)
        if plan_char:
            idx = self._executor_combo.findData(plan_char)
            if idx >= 0:
                self._executor_combo.setCurrentIndex(idx)
        self._executor_combo.blockSignals(False)

        # 主按钮
        reason = self._block_reason(plan)
        if reason is None:
            qty = 1
            try:
                qty = plan_execution.output_per_run(int(plan.get("product_type_id") or 0))
            except Exception:
                qty = 1
            total = max(int(runs or 1), 1) * max(int(parallels or 1), 1) * qty
            name = plan.get("product_name") or f"ID:{plan.get('product_type_id', '')}"
            self._main_btn.setText(f"{name} x {total}")
            self._main_btn.show()
            self._feedback.setText("")
        else:
            self._main_btn.hide()
            self._feedback.setText(f"不可启动：{reason}")

        # 状态栏
        status = (plan.get("status") or "").lower()
        if status in ("in_progress", "running"):
            self._status_icon.setText("⏳")
            self._status_duration.setText(_fmt_remaining(plan) or _fmt_hms(plan.get("calculated_time")))
        else:
            self._status_icon.setText("⏱")
            self._status_duration.setText(_fmt_hms(plan.get("calculated_time")))
        cost = plan.get("material_cost") or 0
        self._status_cost.setText(f"预计成本 {cost:,.0f} ISK")

    def _copy_blueprint(self, plan_id: int) -> None:
        plan = self._plan_map.get(plan_id)
        if plan is None:
            return
        bp_name = (
            self._bp_names.get(int(plan.get("blueprint_type_id") or 0))
            or plan.get("blueprint_name")
            or plan.get("product_name")
            or ""
        )
        if not bp_name:
            self._feedback.setText("该计划无蓝图信息")
            return
        QApplication.clipboard().setText(bp_name)
        self._feedback.setText(f"「{bp_name}」已复制进剪切板")

    # ── 启动 ─────────────────────────────────────────────

    def _start(self, plan_id: int) -> None:
        plan = self._plan_map.get(plan_id)
        if plan is None:
            return
        executor = self._executor_combo.currentData()
        if executor is None and self._executor_combo.count() == 0:
            # 组合框未初始化（尚未选中过行）→ 用计划自身人物
            executor = (plan.get("char_name") or "").strip() or None
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar

        # 软提示：执行人物超员（沿用旧向导，不硬拦）
        if executor:
            cat = capacity_line_for_category(str(plan.get("category") or ""))
            active = int(self._usage.get(executor or "", {}).get(cat, 0))
            mx = max_lines_for_category(executor, cat)
            if active + max(int(plan.get("parallels") or 1), 1) > mx:
                ret = QMessageBox.question(
                    self,
                    "人物产线超员",
                    f"{executor} 当前占用 {active}/{mx} 条{line_label(cat)}线，启动后超员。仍要启动？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if ret != QMessageBox.StandardButton.Yes:
                    return

        res = plan_execution.start_plan(plan, mat_hangar_id=mat, char_name=executor)
        if res.get("ok"):
            self._feedback.setText(f"已启动：{plan.get('product_name', '')}")
            self.plans_changed.emit()
            self._on_poll()
        else:
            QMessageBox.warning(self, "启动失败", res.get("message", "未知错误"))

    def _on_main_start(self):
        if self._selected_id is not None:
            self._start(self._selected_id)

    # ── 过滤器 ───────────────────────────────────────────

    def _on_filter_changed(self):
        self._apply_filters()

    def focus_character(self, char_name: str | None) -> None:
        """把人物过滤定位到指定角色（右键入口初始定位）；None → 全部。"""
        idx = self._char_filter.findData(char_name or "")
        if idx >= 0:
            self._char_filter.setCurrentIndex(idx)
        else:
            self._char_filter.setCurrentIndex(0)

    def closeEvent(self, event) -> None:
        self._tick_timer.stop()
        self._poll_timer.stop()
        super().closeEvent(event)
