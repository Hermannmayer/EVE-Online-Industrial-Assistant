"""产线启动小助手 v3 — 可置顶悬浮的紧凑工具窗。

竖分四区（编号 L1–L4，详见 `docs/dev/ui-blueprint.md`）：

- **L1 工具条** `#launcher_toolbar` —— 线型/人物筛选 + 筛选激活指示 + 置顶（固定单行）
- **L2 占用面板** `#launcher_occupancy` —— 每角色一行产线占用，可折叠，≤4 行不滚动
- **L3 产线列表** `#launcher_list` —— 主工作区，行卡片，动作槽位固定宽（不跳动）
- **L4 详情/执行面板** `#launcher_bottom` —— 未选中为紧凑单行；选中后给参数摘要 + 执行人物 + 启动

实时刷新：1s 内存 tick（运行中行剩余时长）+ 5s DB 轮询（计划增删改自动同步）。

设计依据（间距/字号/图标/配色/披露层级）见 `docs/dev/ui-blueprint.md`；
配色可访问性由模块级 `_CONTRAST_CONTRACT` + `tests/test_theme_registry.py` 全主题断言。

样式策略：套用 `theme.get_stylesheet()`（与全项目其它独立窗口一致）再追加本窗
`_launcher_qss()`；颜色一律取自 `theme` token，字号一律 `theme.fs()`。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
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
from services.plan_category import (
    CATEGORY_COPYING,
    CATEGORY_INVENTION,
    CATEGORY_MANUFACTURING,
    CATEGORY_REACTION,
)
from services.plan_service import group_and_sort_plans, load_plans_for_wizard
from services.plan_start_check import can_force_start, plan_start_block_reason
from services.terminology import term
from ui_pyside6.icon_cache import load_item_icon
from ui_pyside6.pin_utils import apply_window_pin
from ui_pyside6.sizing import ElidedLabel

MAX_SLOTS_PER_LINE = 11  # 单行每类产线最大格块数（技能满级 1+5+5）

# ── 线型筛选 ────────────────────────────────────────────
# 对齐游戏工业窗口的作业类型；名称走术语中心（`term.activity`），不硬编码中文。
# `production_plans` 无 activity 字段（每条计划都是制造作业），故只能按「蓝图用途性质」
# 分类，即 `services/plan_category` 推导出的 category —— 不能用 capacity_line_for_category，
# 那个映射是为「技能决定的产线容量」服务的（copying/invention 合并成科研线）。
# 材料效率研究 / 生产效率研究并入「发明」：本应用建不了研究计划（取数链路写死
# activity='manufacturing'），独立成项会恒空。
_ACTIVITY_FILTERS: tuple[tuple[str, frozenset[str]], ...] = (
    ("manufacturing", frozenset({CATEGORY_MANUFACTURING})),
    ("copying", frozenset({CATEGORY_COPYING})),
    ("invention", frozenset({CATEGORY_INVENTION, "research_material", "research_time"})),
    ("reaction", frozenset({CATEGORY_REACTION})),
)

# ── 间距标尺（Windows/Fluent 8/12/16 体系） ──────────────
# 控件间距 8、控件↔标签 12、表面↔边缘 16。布局里禁止写裸数字。
_GAP_XS = 4
_GAP_SM = 8
_GAP_MD = 12
_GAP_LG = 16

# ── 字号 ────────────────────────────────────────────────
# Windows 11 类型梯度的最小值是 12px regular，更小在 CJK 下不可读；本窗为悬浮工具窗、
# 常在放大的窗口里使用，故取梯度里更舒适的一档：Caption 13 / Body 14。
_FS_CAPTION = 13
_FS_BODY = 14

# ── 几何 ────────────────────────────────────────────────
_NAME_W = 76  # 占用区角色名默认宽（由 ProductionLauncher 按最长角色名统一算出后传入）
_MIN_NAME_W = 60
_MAX_NAME_W = 140
_OCC_ROW_H = 32
_MAX_OCC_ROWS = 4  # 超出则内部滚动，避免占用区把列表挤扁
_ICON_PX = 32  # 多行列表图标尺寸（Windows 文档：32epx）
_ROW_H = 68  # 容得下「标题+副标题」两行文字与 32px 图标，并留 8px 上下内边距
_BADGE_H = 22.0

_MIN_BLOCK_W = 4.0
_NOMINAL_BLOCK_W = 12.0  # sizeHint 里假设的格宽（决定初始窗宽）
_BLOCK_GAP = 3.0
_MIN_BLOCK_GAP = 2.0

_MIN_NON_TEXT_RATIO = 3.0  # WCAG 1.4.11 非文字对比度
_MIN_TEXT_RATIO = 4.5  # WCAG 1.4.3 正文对比度

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

# ⚠️ 字形可用性约束：段首是符号、后面紧跟中文时，Qt 会把整段解析到中文字体
# （theme.FONT_FAMILY = Microsoft YaHei UI）。实测 YaHei **有** ◆ ○ ● ▲ ▼ ■ → · × + −，
# **没有** ▸ ▾ ▶ ✓ ⓘ 📌 —— 后者会渲染成豆腐块（□）。
# 另外符号字形来自不同字体、字号与中文不匹配（▼ 明显比「折叠」大一圈），
# 故**正文里尽量不用几何符号**：状态用文字，折叠用 +/−，只有父项前缀保留 ◆。
_PARENT_GLYPH = "◆ "
_COLLAPSED_GLYPH = "+"  # 已折叠（可展开）
_EXPANDED_GLYPH = "−"  # 已展开（可折叠）
_BLOCKED_GLYPH = "?"  # 不用 ⓘ（YaHei 无此字形）

# ── 对比度契约 ───────────────────────────────────────────
# 角色 → (前景 token, 背景 token, 阈值)。
# `tests/test_theme_registry.py` 遍历 THEME_REGISTRY 的全部主题断言达标，
# 因此新增主题会被自动检查。**改样式必须同步改这张表**。
#
# 层次约定（Fluent：重要的面更亮）：BG_SURFACE 比 BG_DARK **更暗**（不是更亮），
# 所以「控件」一律用 BG_HOVER / BG_SURFACE_LIGHT 这类更亮的面，否则控件会变成黑洞。
_CONTRAST_CONTRACT: dict[str, tuple[str, str, float]] = {
    "工具条说明文字": ("TEXT_PRIMARY", "BG_DARK", _MIN_TEXT_RATIO),
    "占用区标签": ("TEXT_PRIMARY", "BG_DARK", _MIN_TEXT_RATIO),
    "状态徽章文字": ("TEXT_PRIMARY", "BG_SURFACE_LIGHT", _MIN_TEXT_RATIO),
    "行标题": ("TEXT_BRIGHT", "BG_DARK", _MIN_TEXT_RATIO),
    "行副标题": ("TEXT_PRIMARY", "BG_DARK", _MIN_TEXT_RATIO),
    "行标题(悬浮)": ("TEXT_BRIGHT", "BG_SURFACE_LIGHT", _MIN_TEXT_RATIO),
    "行副标题(悬浮)": ("TEXT_PRIMARY", "BG_SURFACE_LIGHT", _MIN_TEXT_RATIO),
    "行标题(选中)": ("TEXT_BRIGHT", "BG_SURFACE_LIGHT", _MIN_TEXT_RATIO),
    "行副标题(选中)": ("TEXT_PRIMARY", "BG_SURFACE_LIGHT", _MIN_TEXT_RATIO),
    "主启动按钮文字": ("BG_DARK", "TEXT_BRIGHT", _MIN_TEXT_RATIO),
    "主启动按钮文字(悬浮)": ("BG_DARK", "TEXT_PRIMARY", _MIN_TEXT_RATIO),
    "次要按钮文字": ("TEXT_PRIMARY", "BG_HOVER", _MIN_TEXT_RATIO),
    "输入框文字": ("TEXT_PRIMARY", "BG_HOVER", _MIN_TEXT_RATIO),
    "底部面板文字": ("TEXT_PRIMARY", "BG_SURFACE", _MIN_TEXT_RATIO),
}


# ── 对比度工具 ───────────────────────────────────────────


def _as_qcolor(value: QColor | str) -> QColor:
    """接受 QColor 或 '#rrggbb' 字符串。"""
    return value if isinstance(value, QColor) else QColor(value)


def relative_luminance(color: QColor | str) -> float:
    """WCAG 2.x 相对亮度（sRGB）。"""

    def lin(channel: int) -> float:
        c = channel / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    c = _as_qcolor(color)
    return 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())


def contrast_ratio(a: QColor | str, b: QColor | str) -> float:
    """WCAG 对比度（1.0–21.0）。"""
    l1, l2 = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def ensure_contrast(
    color: QColor | str,
    background: QColor | str,
    min_ratio: float = _MIN_NON_TEXT_RATIO,
) -> QColor:
    """把颜色朝黑/白方向线性混合，直到与背景达到 `min_ratio`。

    用于**自绘图形**（占用方块、状态字形）：强调色是给填充用的中间调，
    在部分浅色主题下直接用会低于 WCAG 非文字 3:1（实测 one-light 的绿仅 2.87、
    eve-polar 的青仅 2.85）。亮底往黑调、暗底往白调，固定步数，必然终止且必然达标。
    """
    steps = 20
    bg = _as_qcolor(background)
    original = _as_qcolor(color)
    target = QColor(0, 0, 0) if relative_luminance(bg) > 0.5 else QColor(255, 255, 255)
    current = QColor(original)
    for step in range(1, steps + 1):
        if contrast_ratio(current, bg) >= min_ratio:
            return current
        t = step / steps
        current = QColor(
            round(original.red() + (target.red() - original.red()) * t),
            round(original.green() + (target.green() - original.green()) * t),
            round(original.blue() + (target.blue() - original.blue()) * t),
        )
    return target


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
    """占用区单行：角色名 + 制造/科研/反应 的容量格 + 状态徽章。

    paintEvent 自绘；所有几何按控件实际宽度反算，字号/DPI/窗口宽度变化时不截断。

    每类产线的格子区宽度**按该类容量占全部容量的比例**分配（`line_caps` 由
    `ProductionLauncher` 按全部人物的最大容量统一算出后传入）：
    这样「制造 13 格 / 科研 1 格」不会在一行里留下十几个空档，各行也仍能纵向对齐。

    绘制字体一律用 ``self.font()`` —— 与 ``_chrome_width()`` 的量宽字体保持一致；
    否则套用全局样式表后会出现「按 A 量宽、用 B 绘制」的省略号错位。
    """

    def __init__(
        self,
        parent=None,
        *,
        name_width: int = _NAME_W,
        line_caps: dict[str, int] | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("occ_row")
        self._name_width = name_width
        self._line_caps = dict(line_caps) if line_caps else dict.fromkeys(_LINE_TYPES, MAX_SLOTS_PER_LINE)
        self._slot_total = max(sum(self._line_caps.get(line, 0) for line in _LINE_TYPES), 1)
        self._char_name = ""
        self._usage: dict[str, tuple[int, int]] = {}
        self._apply_metrics()
        theme.add_theme_listener(self._on_theme_changed)

    def _apply_metrics(self) -> None:
        """随全局字号刷新行高（方块高度跟随字号，避免大字号下比例失调）。"""
        self._block_h = max(14.0, theme.fs(_FS_BODY) + 1.0)
        self.setMinimumHeight(self.row_height())

    @staticmethod
    def row_height() -> int:
        """占用行标准高度（ProductionLauncher 据此算面板最大高度）。"""
        block_h = max(14.0, theme.fs(_FS_BODY) + 1.0)
        return max(_OCC_ROW_H, int(block_h) + 14)

    def set_usage(self, char_name: str, usage: dict[str, tuple[int, int]]) -> None:
        self._char_name = char_name or "(未分配)"
        self._usage = usage
        self.updateGeometry()
        self.update()

    def _on_theme_changed(self):
        self._apply_metrics()
        self.updateGeometry()
        self.update()

    # ── 状态 ────────────────────────────────────────────────

    def _status_info(self) -> tuple[str, str]:
        """(文本, 语义色 token 名) —— 超员 / 空闲 / 生产中。

        文本以「空闲/生产中/超员」开头（``_status_text()`` 的契约，测试依赖）。
        """
        active_total = sum(self._usage.get(line, (0, 0))[0] for line in _LINE_TYPES)
        max_total = sum(self._usage.get(line, (0, 0))[1] for line in _LINE_TYPES)
        if active_total > max_total:
            return f"超员 +{active_total - max_total}", "ACCENT_RED"
        if active_total == 0:
            return "空闲", "ACCENT_GREEN"
        return "生产中", "PRIMARY"

    def _status_text(self) -> tuple[str, str]:
        """(状态文本, 语义色) —— 兼容既有调用方与测试。"""
        return self._status_info()

    # ── 尺寸 ────────────────────────────────────────────────

    def _badge_width(self, fm: QFontMetrics) -> int:
        text, _color = self._status_info()
        return fm.horizontalAdvance(text) + 2 * _GAP_MD + 5  # +5 给左侧语义色条

    def _label_w(self, fm: QFontMetrics) -> int:
        return max(fm.horizontalAdvance(line_label(line)) for line in _LINE_TYPES) + _GAP_XS

    def _chrome_width(self) -> int:
        """角色名 + 线型标签 + 状态徽章占用的固定宽度（不含方块区）。"""
        fm = QFontMetrics(self.font())
        return (
            _GAP_SM
            + self._name_width
            + _GAP_MD
            + len(_LINE_TYPES) * (self._label_w(fm) + _GAP_SM)
            + self._badge_width(fm)
            + _GAP_SM
        )

    def sizeHint(self) -> QSize:
        width = self._chrome_width() + self._slot_total * int(_NOMINAL_BLOCK_W + _BLOCK_GAP)
        return QSize(width, self.minimumHeight())

    def minimumSizeHint(self) -> QSize:
        width = self._chrome_width() + self._slot_total * int(_MIN_BLOCK_W + _MIN_BLOCK_GAP)
        return QSize(width, self.minimumHeight())

    # ── 绘制 ────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            p.end()
            return

        font = self.font()
        fm = QFontMetrics(font)
        label_w = self._label_w(fm)
        status_text, status_color = self._status_info()
        badge_w = self._badge_width(fm)
        vcenter = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft

        # 状态徽章：中性底 + 主文字色 + 左侧 3px 语义色条。
        # 语义由**文字**承担，颜色只是辅助（不靠颜色单独区分）。
        badge = QRectF(w - badge_w - _GAP_SM, (h - _BADGE_H) / 2.0, badge_w, _BADGE_H)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BG_SURFACE_LIGHT))
        p.drawRoundedRect(badge, 4.0, 4.0)
        p.setBrush(ensure_contrast(getattr(theme, status_color), theme.BG_SURFACE_LIGHT))
        p.drawRect(QRectF(badge.left() + 3.0, badge.top() + 5.0, 3.0, badge.height() - 10.0))
        p.setFont(font)
        p.setPen(QColor(theme.TEXT_PRIMARY))
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, status_text)

        # 角色名（固定列宽保证跨行对齐，宽度由 ProductionLauncher 统一传入）
        x = float(_GAP_SM)
        name_font = QFont(font)
        name_font.setBold(True)
        p.setFont(name_font)
        p.setPen(QColor(theme.TEXT_PRIMARY))
        name_elided = QFontMetrics(name_font).elidedText(self._char_name, Qt.TextElideMode.ElideRight, self._name_width)
        p.drawText(
            QRect(int(x), 0, self._name_width, h),
            vcenter,
            name_elided,
        )
        x += self._name_width + _GAP_MD

        # 方块区预算：必须扣掉三条线型标签（label_w）与组间留白，
        # 否则格子会画到右侧状态徽章底下（旧实现遗漏了 label_w，靠 _MAX_BLOCK_W 上限掩盖）。
        avail = w - x - badge_w - 2 * _GAP_SM - len(_LINE_TYPES) * (label_w + _GAP_SM)
        if avail <= 0:
            p.end()
            return
        stride = avail / self._slot_total
        block_w = max(_MIN_BLOCK_W, stride - _BLOCK_GAP)
        stride = block_w + _BLOCK_GAP
        top = (h - self._block_h) / 2.0
        radius = min(3.0, block_w / 2.0)
        p.setFont(font)

        for line in _LINE_TYPES:
            active, mx = self._usage.get(line, (0, 0))
            # 线型靠「文字标签 + 固定位置」区分，不靠颜色单独区分
            p.setPen(QColor(theme.TEXT_PRIMARY))
            p.drawText(QRect(int(x), 0, label_w, h), vcenter, line_label(line))
            x += label_w
            raw_accent = getattr(theme, _LINE_COLORS[line])
            base = ensure_contrast(raw_accent, theme.BG_DARK)
            for i in range(self._line_caps.get(line, 0)):
                # 超过该人物技能容量（mx）的格子不绘制：格子数即该人物的容量
                if i >= mx:
                    x += stride
                    continue
                rect = QRectF(x, top, block_w, self._block_h)
                if i < active:
                    # 占用：渐变填充 + 圆角
                    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                    grad.setColorAt(0.0, base.lighter(135))
                    grad.setColorAt(1.0, base.darker(110))
                    p.setBrush(grad)
                    p.setPen(QPen(base.darker(135), 1))
                else:
                    # 空闲但可达：明显的浅格（BG_HOVER 比 BG_DARK/BG_SURFACE 都亮），不加描边
                    p.setBrush(QColor(theme.BG_HOVER))
                    p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(rect, radius, radius)
                x += stride
            x += _GAP_SM
        p.end()


class PlanRow(QWidget):
    """L3 行卡片：[图标][标题+徽章 / 副标题][时长 / 动作槽位]。

    动作槽位宽度固定（`_action_slot_w`），三种按钮互斥显隐但**占位不变** ——
    避免行动作区左右跳动；被阻塞时也给出可见的 ⓘ 入口而非留空。
    """

    clicked = Signal(int)  # 点信息区 → 复制蓝图名
    start_requested = Signal(int)  # 点启动按钮
    toggle_requested = Signal(int)  # 点折叠/展开（传 group_id）
    blocked_requested = Signal(int)  # 点 ⓘ → 查看不可启动原因

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("plan_row")
        # QWidget 子类默认不绘制 QSS 背景、也不产生 hover 事件，需显式开启
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(_ROW_H)

        self._plan: dict = {}
        self._plan_id: int | None = None
        self._last_reason: str | None = None
        self._last_pending: int = 0
        self._last_collapsed: bool = False
        self._last_can_force: bool = False

        root = QHBoxLayout(self)
        root.setContentsMargins(_GAP_MD, _GAP_SM, _GAP_MD, _GAP_SM)
        root.setSpacing(_GAP_MD)

        # 子级缩进引导线（替代原先的空格缩进）
        self._indent = QFrame()
        self._indent.setObjectName("row_indent")
        self._indent.setFixedWidth(2)
        self._indent.hide()
        root.addWidget(self._indent)

        self._icon = QLabel()
        self._icon.setObjectName("row_icon")
        self._icon.setFixedSize(_ICON_PX, _ICON_PX)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._icon)

        info = QVBoxLayout()
        info.setSpacing(_GAP_XS)
        title_row = QHBoxLayout()
        title_row.setSpacing(_GAP_SM)
        self._name = ElidedLabel("")
        self._name.setObjectName("row_title")
        title_row.addWidget(self._name)
        self._status = QLabel("")
        self._status.setObjectName("status_badge")
        title_row.addWidget(self._status)
        title_row.addStretch(1)
        info.addLayout(title_row)

        self._meta = ElidedLabel("")
        self._meta.setObjectName("row_meta")
        info.addWidget(self._meta)
        root.addLayout(info, 1)

        right = QVBoxLayout()
        right.setSpacing(_GAP_XS)
        self._duration = QLabel("")
        self._duration.setObjectName("row_duration")
        self._duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(self._duration)

        action_row = QHBoxLayout()
        action_row.setSpacing(_GAP_SM)
        action_row.addStretch(1)
        self._action_slot_w = self._compute_slot_width()
        self._btn_start = QPushButton("启动")
        self._btn_start.setObjectName("btn_row")
        self._btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.clicked.connect(self._on_start_clicked)
        self._btn_toggle = QPushButton("")
        self._btn_toggle.setObjectName("btn_row_ghost")
        self._btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_toggle.clicked.connect(self._on_toggle_clicked)
        self._btn_blocked = QPushButton(_BLOCKED_GLYPH)
        self._btn_blocked.setObjectName("btn_row_ghost")
        self._btn_blocked.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_blocked.clicked.connect(self._on_blocked_clicked)
        for btn in (self._btn_start, self._btn_toggle, self._btn_blocked):
            btn.setFixedWidth(self._action_slot_w)
            action_row.addWidget(btn)
        right.addLayout(action_row)
        root.addLayout(right)

        theme.add_theme_listener(self._on_theme_changed)

    # ── 尺寸 ────────────────────────────────────────────────

    def _compute_slot_width(self) -> int:
        """动作槽位宽度 = 三种按钮文本的最宽者 + 左右内边距。

        实测 ``▾ 折叠(1)`` 约 87px、``▶ 启动`` 约 72px；必须按最宽者取值，
        否则折叠文案会被截断。
        """
        fm = QFontMetrics(self.font())
        samples = ("启动", "折叠(99)", "展开(99)", _BLOCKED_GLYPH)
        text_w = max(fm.horizontalAdvance(s) for s in samples)
        return max(88, text_w + 2 * _GAP_MD)

    # ── 交互 ────────────────────────────────────────────────

    def _on_start_clicked(self):
        if self._plan_id is not None:
            self.start_requested.emit(self._plan_id)

    def _on_toggle_clicked(self):
        gid = int(self._plan.get("group_id") or self._plan.get("group_number") or 0)
        if gid:
            self.toggle_requested.emit(gid)

    def _on_blocked_clicked(self):
        if self._plan_id is not None:
            self.blocked_requested.emit(self._plan_id)

    # ── 数据 ────────────────────────────────────────────────

    def set_plan(
        self,
        plan: dict,
        *,
        block_reason: str | None,
        pending_children: int = 0,
        collapsed: bool = False,
        can_force_start: bool = False,
    ) -> None:
        self._plan = plan
        self._plan_id = plan.get("id")
        self._last_reason = block_reason
        self._last_pending = pending_children
        self._last_collapsed = collapsed
        self._last_can_force = can_force_start
        status = (plan.get("status") or "").lower()
        level = int(plan.get("child_level") or 0)
        name = plan.get("product_name") or f"ID:{plan.get('product_type_id', '')}"
        self._name.setText((_PARENT_GLYPH if level == 0 else "") + name)

        label = _STATUS_LABELS.get(status, status)
        self._status.setText(label)
        self._status.setToolTip(label)

        # 时长：运行中显示剩余，其余显示总时长；总量放 tooltip，不在正文重复
        total = int(plan.get("calculated_time") or 0)
        if status in ("in_progress", "running"):
            rem = _fmt_remaining(plan)
            self._duration.setText(f"剩 {rem}" if rem else _fmt_hms(total))
            self._duration.setToolTip(f"总时长 {_fmt_hms(total)}")
        elif status == "ready":
            self._duration.setText("待下线")
            self._duration.setToolTip("")
        else:
            self._duration.setText(_fmt_hms(total))
            self._duration.setToolTip("预计总时长")

        # 副标题：把原先散在 3 行的信息压成 1 行（信息集中）
        cat = capacity_line_for_category(str(plan.get("category") or ""))
        parts = [
            line_label(cat),
            f"{plan.get('runs', 1)}×{plan.get('parallels', 1)}",
            f"人物 {plan.get('char_name') or '未分配'}",
        ]
        loc = self._location_text(plan)
        if loc:
            parts.append(loc)
        self._meta.setText(" · ".join(parts))

        self._load_icon(plan)

        # 缩进引导线 + 左内边距随层级递增
        root = self.layout()
        if root is not None:
            root.setContentsMargins(_GAP_MD + level * _GAP_LG, _GAP_SM, _GAP_MD, _GAP_SM)
        self._indent.setVisible(level > 0)

        # 动作槽位：四态互斥，占位恒定
        self._btn_start.hide()
        self._btn_toggle.hide()
        self._btn_blocked.hide()
        if level == 0 and pending_children > 0:
            self._btn_toggle.setText(("展开" if collapsed else "折叠") + f"({pending_children})")
            self._btn_toggle.show()
        elif block_reason is None and status == "pending":
            self._btn_start.show()
        elif can_force_start and status == "pending":
            # 缺料是**唯一**阻塞：仍给「启动」，点击时二次确认（与计划表格同口径）
            self._btn_start.setToolTip(f"材料不足，点击后需确认（{block_reason}）")
            self._btn_start.show()
        else:
            reason = block_reason or _STATUS_LABELS.get(status, status) or "不可启动"
            self._btn_blocked.setToolTip(reason)
            self._btn_blocked.show()

    def _location_text(self, plan: dict) -> str:
        src = plan.get("facility") or ""
        dst = plan.get("output_hangar") or ""
        if src and dst:
            return f"{src}→{dst}"
        return src

    def _load_icon(self, plan: dict) -> None:
        pix = load_item_icon(int(plan.get("product_type_id") or 0), _ICON_PX)
        if pix is not None:
            self._icon.setPixmap(pix)
            self._icon.setToolTip("")
            return
        # 无图标：用类别首字占位。不用 category_symbol() 的 emoji（⚙ 📋 ⚗ 💡）——
        # 它们来自符号/emoji 字体，在本窗的字体环境里会渲染成空白或豆腐块。
        cat = capacity_line_for_category(str(plan.get("category") or ""))
        label = line_label(cat) or "?"
        self._icon.setText(label[:1])
        self._icon.setToolTip(label)

    def update_tick(self) -> None:
        """仅运行中行：刷新剩余时长（不重建行）。"""
        plan = self._plan
        if not plan:
            return
        status = (plan.get("status") or "").lower()
        if status not in ("in_progress", "running"):
            return
        rem = _fmt_remaining(plan)
        if rem:
            self._duration.setText(f"剩 {rem}")

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self._plan_id is not None:
            self.clicked.emit(self._plan_id)

    def _on_theme_changed(self):
        self._action_slot_w = self._compute_slot_width()
        for btn in (self._btn_start, self._btn_toggle, self._btn_blocked):
            btn.setFixedWidth(self._action_slot_w)
        if self._plan:
            self.set_plan(
                self._plan,
                block_reason=self._last_reason,
                pending_children=self._last_pending,
                collapsed=self._last_collapsed,
                can_force_start=self._last_can_force,
            )


def _launcher_qss() -> str:
    """本窗专属 QSS（按 objectName 作用域）。

    颜色全部取自 `theme` token、字号全部 `theme.fs()`，主题/字号切换时重建即可。
    注意：全局样式表里的 `QListWidget::item` 是**无作用域**的（theme.py），
    这里用 id 选择器覆盖它。
    """
    r = theme.RADIUS
    rs = theme.RADIUS_SMALL
    return f"""
    #launcher_toolbar {{
        background: transparent;
        border-bottom: 1px solid {theme.BORDER};
    }}
    #filter_summary {{
        color: {theme.TEXT_PRIMARY};
        font-size: {theme.fs(_FS_CAPTION)}px;
    }}
    #pin_btn:checked {{
        background-color: {theme.BG_SURFACE_LIGHT};
        color: {theme.PRIMARY};
    }}
    /* 输入控件用比背景更亮的面。全局 QComboBox 用 BG_SURFACE，而 BG_SURFACE 比
       BG_DARK 更暗 —— 直接用会渲染成「黑洞 + 亮边」（黑框），必须在本窗覆盖。 */
    #line_filter, #char_filter, #executor_combo {{
        background-color: {theme.BG_HOVER};
        color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.BORDER};
        border-radius: {rs}px;
        padding: 5px {_GAP_SM}px;
    }}
    #line_filter:hover, #char_filter:hover, #executor_combo:hover {{
        border-color: {theme.PRIMARY};
    }}
    #line_filter QAbstractItemView, #char_filter QAbstractItemView,
    #executor_combo QAbstractItemView {{
        background-color: {theme.BG_SURFACE_LIGHT};
        color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.BORDER};
        selection-background-color: {theme.BG_HOVER};
    }}
    #occ_header {{
        background: transparent;
    }}
    #occ_title, #occ_summary {{
        color: {theme.TEXT_PRIMARY};
        font-size: {theme.fs(_FS_CAPTION)}px;
    }}
    #occ_title {{
        font-weight: 600;
    }}
    #occ_disc {{
        background: transparent;
        border: none;
        color: {theme.TEXT_PRIMARY};
        font-size: {theme.fs(_FS_CAPTION)}px;
        padding: 0px;
    }}
    #occ_disc:hover {{
        color: {theme.PRIMARY};
    }}
    #occ_scroll, #occ_scroll QWidget#qt_scrollarea_viewport {{
        background: transparent;
        border: none;
    }}
    #launcher_list {{
        background-color: {theme.BG_DARK};
        border: 1px solid {theme.BORDER};
        border-radius: {rs}px;
        outline: none;
    }}
    #launcher_list::item {{
        padding: 0px;
        border: none;
    }}
    #launcher_list::item:selected {{
        background-color: {theme.BG_SURFACE_LIGHT};
    }}
    #plan_row {{
        background-color: transparent;
        border-radius: {rs}px;
    }}
    #plan_row:hover {{
        background-color: {theme.BG_SURFACE_LIGHT};
    }}
    #row_indent {{
        background-color: {theme.BORDER};
        border-radius: 1px;
    }}
    #row_title {{
        color: {theme.TEXT_BRIGHT};
        font-size: {theme.fs(_FS_BODY)}px;
        font-weight: 600;
    }}
    #row_meta, #row_duration {{
        color: {theme.TEXT_PRIMARY};
        font-size: {theme.fs(_FS_CAPTION)}px;
    }}
    /* 全局 QWidget 规则会给 QLabel 也画上不透明底色，盖住行的悬浮/选中面
       （浅色主题下表现为「文字背后一个白框」）。逐个标签设透明；
       不能写 `#plan_row QLabel` —— 那会连 #status_badge 的底色一起清掉。 */
    #row_title, #row_meta, #row_duration, #row_icon, #list_empty,
    #bottom_hint, #detail_summary, #feedback,
    #filter_summary, #occ_title, #occ_summary {{
        background: transparent;
    }}
    #row_icon {{
        color: {theme.TEXT_PRIMARY};
        font-size: {theme.fs(_FS_BODY)}px;
        font-weight: 600;
    }}
    #status_badge {{
        background-color: {theme.BG_SURFACE_LIGHT};
        color: {theme.TEXT_PRIMARY};
        border-radius: {rs}px;
        padding: 1px {_GAP_SM}px;
        font-size: {theme.fs(_FS_CAPTION)}px;
    }}
    #list_empty {{
        color: {theme.TEXT_PRIMARY};
        font-size: {theme.fs(_FS_CAPTION)}px;
    }}
    #btn_row {{
        background-color: {theme.TEXT_BRIGHT};
        color: {theme.BG_DARK};
        border: none;
        border-radius: {rs}px;
        font-size: {theme.fs(_FS_BODY)}px;
        font-weight: 600;
        padding: 7px 0px;
    }}
    #btn_row:hover {{
        background-color: {theme.TEXT_PRIMARY};
    }}
    #btn_row_ghost {{
        background-color: {theme.BG_HOVER};
        color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.BORDER};
        border-radius: {rs}px;
        font-size: {theme.fs(_FS_CAPTION)}px;
        padding: 6px 0px;
    }}
    #btn_row_ghost:hover {{
        border-color: {theme.PRIMARY};
    }}
    #btn_launch {{
        background-color: {theme.TEXT_BRIGHT};
        color: {theme.BG_DARK};
        border: none;
        border-radius: {rs}px;
        font-size: {theme.fs(_FS_BODY)}px;
        font-weight: 600;
        padding: 6px {_GAP_LG}px;
    }}
    #btn_launch:hover {{
        background-color: {theme.TEXT_PRIMARY};
    }}
    #launcher_bottom {{
        background-color: {theme.BG_SURFACE};
        border-top: 1px solid {theme.BORDER};
        border-radius: 0px 0px {r}px {r}px;
    }}
    #bottom_hint, #feedback {{
        color: {theme.TEXT_PRIMARY};
        font-size: {theme.fs(_FS_CAPTION)}px;
    }}
    #detail_summary {{
        color: {theme.TEXT_PRIMARY};
        font-size: {theme.fs(_FS_BODY)}px;
    }}
    """


class ProductionLauncher(QWidget):
    """产线启动小助手 — 非模态紧凑工具窗。"""

    plans_changed = Signal()  # 启动成功后触发，供主窗口刷新

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("产线启动小助手")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(820, 760)
        self.setMinimumSize(560, 480)

        self._all_plans: list[dict] = []
        self._visible_plans: list[dict] = []
        self._plan_map: dict[int, dict] = {}
        self._widgets: dict[int, PlanRow] = {}
        self._row_order: list[int] = []
        self._usage: dict[str, dict[str, int]] = {}
        self._shortfall_cache: dict[int, tuple] = {}
        # 本轮轮询的机库库存（内容 + 指纹），按 mat_hangar_id 记忆；_on_poll 开头清空。
        # 库存必须进缺口指纹：它不进计划字段，只按计划字段缓存会让「材料补齐后」一直显示旧缺口。
        self._stock_cache: dict[int, dict[int, int]] = {}
        self._stock_fp: dict[int, frozenset] = {}
        self._bp_short_cache: dict[int, str | None] = {}  # 本轮蓝图流程预检结果
        # 输入蓝图就绪缓存（按计划指纹），避免每行每次刷新都打 DB
        self._bp_ready_cache: dict[int, tuple] = {}
        self._collapsed: set[int] = set()  # 已折叠的组号（隐藏其子项）
        self._occ_collapsed = False
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
        self._fit_initial_size()
        self._restore_pin()

    # ── UI ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(_GAP_XS, _GAP_XS, _GAP_XS, _GAP_XS)
        root.setSpacing(_GAP_SM)

        # ── L1 工具条（固定单行） ──
        # 必须是 QFrame（而非裸布局），否则 QSS 的 `#launcher_toolbar` 命中不到
        self._toolbar = QFrame()
        self._toolbar.setObjectName("launcher_toolbar")
        bar = QHBoxLayout(self._toolbar)
        bar.setContentsMargins(0, _GAP_XS, 0, _GAP_SM)
        bar.setSpacing(_GAP_SM)

        self._line_filter = QComboBox()
        self._line_filter.setObjectName("line_filter")
        self._line_filter.addItem("全部", None)
        for key, cats in _ACTIVITY_FILTERS:
            self._line_filter.addItem(term.activity(key), cats)
        self._line_filter.setMinimumWidth(110)
        self._line_filter.setMaximumWidth(160)
        self._line_filter.currentIndexChanged.connect(self._on_filter_changed)
        bar.addWidget(self._line_filter)

        self._char_filter = QComboBox()
        self._char_filter.setObjectName("char_filter")
        self._char_filter.setMinimumWidth(140)
        self._char_filter.setMaximumWidth(260)
        self._rebuild_char_filter()
        self._char_filter.currentIndexChanged.connect(self._on_filter_changed)
        bar.addWidget(self._char_filter)

        self._filter_summary = QLabel("")
        self._filter_summary.setObjectName("filter_summary")
        bar.addWidget(self._filter_summary)
        bar.addStretch(1)

        self._pin_btn = QToolButton()
        self._pin_btn.setObjectName("pin_btn")
        self._pin_btn.setText("置顶")
        self._pin_btn.setCheckable(True)
        self._pin_btn.setToolTip("切换窗口置顶（悬浮于游戏之上）")
        self._pin_btn.toggled.connect(self._on_pin_toggled)
        bar.addWidget(self._pin_btn)
        root.addWidget(self._toolbar, 0)

        # ── L2 占用面板（可折叠，≤4 行不滚动） ──
        self._occ_header = QFrame()
        self._occ_header.setObjectName("occ_header")
        head = QHBoxLayout(self._occ_header)
        head.setContentsMargins(0, 0, 0, _GAP_XS)
        head.setSpacing(_GAP_SM)
        self._occ_disc = QToolButton()
        self._occ_disc.setObjectName("occ_disc")
        self._occ_disc.setText(_EXPANDED_GLYPH)
        self._occ_disc.setFixedSize(20, 20)
        self._occ_disc.setToolTip("折叠/展开产线占用")
        self._occ_disc.clicked.connect(self._on_occ_toggle)
        head.addWidget(self._occ_disc)
        occ_title = QLabel("产线占用")
        occ_title.setObjectName("occ_title")
        head.addWidget(occ_title)
        self._occ_summary = QLabel("")
        self._occ_summary.setObjectName("occ_summary")
        head.addWidget(self._occ_summary)
        head.addStretch(1)
        root.addWidget(self._occ_header, 0)

        occ_scroll = QScrollArea()
        occ_scroll.setObjectName("occ_scroll")
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
        root.addWidget(occ_scroll, 0)
        self._occ_scroll = occ_scroll
        self._occ_container = occ_container

        # ── L3 产线列表（主工作区） ──
        self._list = QListWidget()
        self._list.setObjectName("launcher_list")
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setSpacing(_GAP_XS)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._list, 1)

        # ── L4 详情/执行面板（固定） ──
        self._bottom_panel = QFrame(self)
        self._bottom_panel.setObjectName("launcher_bottom")
        bottom = QVBoxLayout(self._bottom_panel)
        bottom.setContentsMargins(_GAP_MD, _GAP_SM, _GAP_MD, _GAP_SM)
        bottom.setSpacing(_GAP_SM)

        # 紧凑态：未选中任何行
        self._bottom_hint = QLabel("在上方列表选一条产线")
        self._bottom_hint.setObjectName("bottom_hint")
        bottom.addWidget(self._bottom_hint)

        # 展开态：选中后才有意义
        self._detail_panel = QWidget()
        self._detail_panel.setObjectName("detail_panel")
        detail = QVBoxLayout(self._detail_panel)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(_GAP_SM)
        self._params_label = QLabel("")
        self._params_label.setObjectName("detail_summary")
        self._params_label.setWordWrap(True)
        detail.addWidget(self._params_label)

        exec_row = QHBoxLayout()
        exec_row.setSpacing(_GAP_MD)
        self._executor_combo = QComboBox()
        self._executor_combo.setObjectName("executor_combo")
        self._executor_combo.setMinimumWidth(180)
        self._executor_combo.setMaximumWidth(300)
        exec_row.addWidget(self._executor_combo)
        exec_row.addStretch(1)
        self._main_btn = QPushButton("")
        self._main_btn.setObjectName("btn_launch")
        self._main_btn.setMinimumHeight(32)
        self._main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._main_btn.clicked.connect(self._on_main_start)
        exec_row.addWidget(self._main_btn)
        detail.addLayout(exec_row)

        self._feedback = QLabel("")
        self._feedback.setObjectName("feedback")
        self._feedback.setWordWrap(True)
        self._feedback.hide()
        detail.addWidget(self._feedback)

        self._detail_panel.hide()
        bottom.addWidget(self._detail_panel)
        root.addWidget(self._bottom_panel, 0)

    def _rebuild_char_filter(self) -> None:
        self._char_filter.blockSignals(True)
        self._char_filter.clear()
        self._char_filter.addItem("全部人物", None)
        self._char_filter.addItem("未分配", "")
        for name in self._char_list:
            self._char_filter.addItem(name, name)
        self._char_filter.blockSignals(False)

    def _on_theme_changed(self):
        self.setStyleSheet(theme.get_stylesheet() + _launcher_qss())
        if self._occ_container:
            for child in self._occ_container.findChildren(CapacitySlotBar):
                child._on_theme_changed()
        self._apply_occ_height(self._occ_row_count())

    # ── L2 折叠 ──────────────────────────────────────────

    def _on_occ_toggle(self) -> None:
        self._occ_collapsed = not self._occ_collapsed
        self._occ_disc.setText(_COLLAPSED_GLYPH if self._occ_collapsed else _EXPANDED_GLYPH)
        self._apply_occ_height(self._occ_row_count())

    def _occ_row_count(self) -> int:
        return len(self._occ_container.findChildren(CapacitySlotBar)) if self._occ_container else 0

    def _apply_occ_height(self, rows: int) -> None:
        """占用区高度：≤_MAX_OCC_ROWS 行按内容，超出则内部滚动 —— 不再撑高窗口或压扁列表。"""
        if self._occ_collapsed:
            self._occ_scroll.setFixedHeight(0)
            return
        per_row = self._occ_layout.spacing() + CapacitySlotBar.row_height()
        visible = max(min(rows, _MAX_OCC_ROWS), 0)
        self._occ_scroll.setFixedHeight(visible * per_row + 2)

    # ── 置顶 ─────────────────────────────────────────────

    def _on_pin_toggled(self, checked: bool):
        apply_window_pin(self, checked)
        from services.user_settings import save_settings

        try:
            save_settings({"production_launcher_pin": checked})
        except Exception:
            log.exception("保存产线小助手置顶偏好失败")

    def _restore_pin(self) -> None:
        try:
            from services.user_settings import load_settings

            if load_settings().get("production_launcher_pin"):
                self._pin_btn.setChecked(True)
                apply_window_pin(self, True)
        except Exception:
            log.exception("恢复产线小助手置顶偏好失败")

    def _fit_initial_size(self) -> None:
        """按占用区内容宽度定窗宽 —— 默认尺寸下占用条右侧徽章会被裁。"""
        hint = self._occ_container.sizeHint().width()
        if hint > 0:
            self.resize(max(self.width(), min(hint + 40, 1100)), self.height())

    # ── 数据刷新 ─────────────────────────────────────────

    def _on_poll(self) -> None:
        """5s 轮询：补算过期 + 重载非完成计划 + 刷新占用/列表。

        库存快照在这里作废：材料是否备齐不进计划字段，必须每轮重取，
        否则「补齐材料」后缺口判定永远停在旧值。
        """
        self._stock_cache.clear()
        self._stock_fp.clear()
        self._bp_short_cache.clear()
        try:
            plan_execution.expire_overdue_plans()
            self._all_plans = load_plans_for_wizard()
        except Exception:
            log.exception("产线小助手轮询失败")
            return
        self._refresh_occupancy()
        self._apply_filters()

    def _on_tick(self) -> None:
        for pid, w in self._widgets.items():
            plan = self._plan_map.get(pid)
            if plan and (plan.get("status") or "").lower() in ("in_progress", "running"):
                w.update_tick()

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
            self._occ_summary.setText("（无人物配置，请在人物设置中添加）")
            self._apply_occ_height(0)
            return

        # 统一角色名列宽 → 各行的产线方块保持纵向对齐（逐行自算会错位）
        fm = QFontMetrics(self.font())
        name_width = max((fm.horizontalAdvance(c or "(未分配)") for c in chars), default=_NAME_W) + _GAP_SM
        name_width = max(_MIN_NAME_W, min(name_width, _MAX_NAME_W))

        # 先按全部人物算出每类产线的最大容量 → 各行格子区宽度按容量比例分配且纵向对齐
        per_char: list[tuple[str, dict[str, tuple[int, int]]]] = []
        line_caps: dict[str, int] = dict.fromkeys(_LINE_TYPES, 0)
        active_total = 0
        max_total = 0
        for char in chars:
            skills = (chars_data.get(char, {}) or {}).get("skills", {}) or {}
            usage = self._usage.get(char or "", {})
            per_line: dict[str, tuple[int, int]] = {}
            for line in _LINE_TYPES:
                mx = max_lines_for_category(char, line, skills=skills)
                active = usage.get(line, 0)
                per_line[line] = (active, mx)
                line_caps[line] = max(line_caps[line], mx)
                active_total += active
                max_total += mx
            per_char.append((char, per_line))

        for char, per_line in per_char:
            bar = CapacitySlotBar(self._occ_container, name_width=name_width, line_caps=line_caps)
            bar.set_usage(char, per_line)
            self._occ_layout.addWidget(bar)
        self._occ_layout.addStretch(1)

        self._occ_summary.setText(f"{len(chars)} 人物 · 占用 {active_total}/{max_total}")
        self._apply_occ_height(len(chars))

    def _match_filters(self, plan: dict) -> bool:
        cats = self._line_filter.currentData()
        if cats is not None and str(plan.get("category") or CATEGORY_MANUFACTURING) not in cats:
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
        self._update_filter_summary(len(full), len(visible))
        self._update_bottom()

    def _update_filter_summary(self, total: int, shown: int) -> None:
        """筛选激活指示 —— 用户应能一眼看出「数据已被过滤」（NN/g 表设计）。"""
        filtered = self._line_filter.currentData() is not None or self._char_filter.currentData() is not None
        self._filter_summary.setText(f"已筛选 {shown}/{total}" if filtered else f"共 {total} 条")

    def _is_collapsed_child(self, plan: dict) -> bool:
        gid = int(plan.get("group_id") or plan.get("group_number") or 0)
        return bool(gid and int(plan.get("child_level") or plan.get("sub_level") or 0) > 0 and gid in self._collapsed)

    # ── 列表同步 ─────────────────────────────────────────

    def _hangar_stock(self, mat_hangar_id: int) -> dict[int, int]:
        """本轮轮询内的机库库存快照（每机库只查一次）。"""
        stock = self._stock_cache.get(mat_hangar_id)
        if stock is None:
            from services import inventory_manager

            stock = inventory_manager.get_hangar_stock(mat_hangar_id)
            self._stock_cache[mat_hangar_id] = stock
        return stock

    def _stock_key(self, mat_hangar_id: int) -> frozenset:
        """该机库本轮库存的内容指纹（每机库只构造一次）。"""
        key = self._stock_fp.get(mat_hangar_id)
        if key is None:
            key = frozenset(self._hangar_stock(mat_hangar_id).items())
            self._stock_fp[mat_hangar_id] = key
        return key

    def _shortfall_count(self, plan: dict) -> int:
        """材料缺口种数（指纹缓存，避免每轮全量评分）。

        指纹**必须含库存内容**：库存变化不进计划字段，只按计划字段缓存会在「材料补齐后」
        永远命中旧值，行上于是一直显示问号，直到改计划字段或重启应用（历史缺陷）。
        库存在 `_on_poll` 的节拍上重取（每机库每轮一次），内容没变仍命中缓存。
        """
        pid = int(plan.get("id") or 0)
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar
        is_pending = (plan.get("status") or "").lower() == "pending"
        stock_key = self._stock_key(int(mat)) if (is_pending and mat) else None
        fp = (
            plan.get("status"),
            plan.get("runs"),
            plan.get("parallels"),
            plan.get("me_level"),
            plan.get("te_level"),
            plan.get("char_name"),
            plan.get("mat_hangar_id"),
            stock_key,
        )
        cached = self._shortfall_cache.get(pid)
        if cached and cached[0] == fp:
            return int(cached[1])
        count = 0
        if is_pending and mat:
            try:
                missing = [
                    r
                    for r in plan_execution.check_materials(plan, mat, stock=self._stock_cache.get(int(mat)))
                    if (r.get("missing") or 0) > 0
                ]
                count = len(missing)
            except Exception:
                log.exception("材料缺口计算失败 plan_id=%s", plan.get("id"))
                count = 0
        self._shortfall_cache[pid] = (fp, count)
        return count

    def _bp_short(self, plan: dict) -> str | None:
        """蓝图流程不足的原因（本轮轮询内每计划只查一次）。"""
        pid = int(plan.get("id") or 0)
        if pid not in self._bp_short_cache:
            try:
                self._bp_short_cache[pid] = plan_execution.binding_shortfall(pid)
            except Exception:
                log.exception("蓝图流程预检失败 plan_id=%s", pid)
                self._bp_short_cache[pid] = None
        return self._bp_short_cache[pid]

    def _blueprint_ready(self, plan: dict) -> bool:
        """输入蓝图是否就绪（按活动规则，见 services.plan_job_kinds）。带指纹缓存。"""
        pid = int(plan.get("id") or 0)
        fp = (
            plan.get("status"),
            plan.get("activity"),
            plan.get("runs"),
            plan.get("parallels"),
            plan.get("assigned_blueprint_id"),
        )
        cached = self._bp_ready_cache.get(pid)
        if cached and cached[0] == fp:
            return bool(cached[1])
        try:
            ready = plan_execution.plan_blueprint_ready(plan)
        except Exception:
            ready = True  # 读不到时不拦（与旧宽松语义一致）
        self._bp_ready_cache[pid] = (fp, ready)
        return ready

    def _block_reason(self, plan: dict) -> str | None:
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar
        return plan_start_block_reason(
            plan,
            mat,
            self._all_plans,
            shortfall_count=self._shortfall_count(plan),
            bp_short=self._bp_short(plan),
            blueprint_ready=self._blueprint_ready(plan),
        )

    def _can_force_start(self, plan: dict) -> bool:
        """缺料 / 蓝图流程不足是否为唯一阻塞（是 → 仍给「启动」，点击时二次确认）。"""
        mat = plan.get("mat_hangar_id") or self._default_mat_hangar
        return can_force_start(
            plan,
            mat,
            self._all_plans,
            shortfall_count=self._shortfall_count(plan),
            bp_short=self._bp_short(plan),
            blueprint_ready=self._blueprint_ready(plan),
        )

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
                        can_force_start=self._can_force_start(plan),
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
            empty.setObjectName("list_empty")
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
            row.blocked_requested.connect(self._on_blocked_info)
            row.set_plan(
                plan,
                block_reason=self._block_reason(plan),
                pending_children=int(plan.get("_pending_children") or 0),
                collapsed=self._row_collapsed(plan),
                can_force_start=self._can_force_start(plan),
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

    def _select_visible_row(self, plan_id: int) -> bool:
        """把某计划设为列表选中项（行内启动 / ⓘ 共用）。"""
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == plan_id:
                self._list.setCurrentItem(it)
                return True
        return False

    def _on_row_clicked(self, plan_id: int):
        self._copy_blueprint(plan_id)

    def _on_row_start(self, plan_id: int):
        # 行内启动：先让该行成为选中 → 执行人物组合框跟随该计划
        self._select_visible_row(plan_id)
        self._start(plan_id)

    def _on_blocked_info(self, plan_id: int) -> None:
        """点动作槽位的 ⓘ：选中该行 → 底部反馈区给出不可启动原因。"""
        self._select_visible_row(plan_id)

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

    def _show_feedback(self, text: str) -> None:
        """反馈按需显示 —— 无内容时不占位。"""
        self._feedback.setText(text)
        self._feedback.setVisible(bool(text))

    def _update_bottom(self) -> None:
        plan = self._plan_map.get(self._selected_id or -1)
        if plan is None:
            # 紧凑态：只留一行提示，不再露出全宽空下拉
            self._detail_panel.hide()
            self._executor_combo.setVisible(False)
            self._bottom_hint.show()
            self._show_feedback("")
            self._main_btn.hide()
            self._executor_combo.clear()
            return

        self._bottom_hint.hide()
        self._detail_panel.show()
        self._executor_combo.setVisible(True)

        cat = capacity_line_for_category(str(plan.get("category") or ""))
        runs = plan.get("runs", 1)
        parallels = plan.get("parallels", 1)
        facility = plan.get("facility") or "—"
        output = plan.get("output_hangar") or "—"
        status = (plan.get("status") or "").lower()
        cost = plan.get("material_cost") or 0
        name = plan.get("product_name") or f"ID:{plan.get('product_type_id', '')}"
        # 产品名放在可换行的摘要行，而不是按钮上 —— 否则长名会把按钮撑爆、挤掉执行人物下拉
        parts = [name, line_label(cat), f"流程 {runs}×{parallels}", f"{facility} → {output}"]
        if status in ("in_progress", "running"):
            rem = _fmt_remaining(plan)
            if rem:
                parts.append(f"剩余 {rem}")
        if cost:
            parts.append(f"预计成本 {cost:,.0f} ISK")
        self._params_label.setText(" · ".join(parts))

        # 执行人物下拉（含剩余容量）—— 注意别复用 `name`（那是产品名）
        self._executor_combo.blockSignals(True)
        self._executor_combo.clear()
        chars = list(self._char_list)
        plan_char = (plan.get("char_name") or "").strip()
        if plan_char and plan_char not in chars:
            chars.insert(0, plan_char)
        for char_name in chars:
            remaining = max_lines_for_category(char_name, cat) - int(self._usage.get(char_name or "", {}).get(cat, 0))
            self._executor_combo.addItem(f"{char_name}（剩 {max(remaining, 0)} 条）", char_name)
        if plan_char:
            idx = self._executor_combo.findData(plan_char)
            if idx >= 0:
                self._executor_combo.setCurrentIndex(idx)
        self._executor_combo.blockSignals(False)

        # 主按钮
        reason = self._block_reason(plan)
        force = reason is not None and self._can_force_start(plan)
        if reason is None or force:
            qty = 1
            try:
                qty = plan_execution.output_per_run(int(plan.get("product_type_id") or 0))
            except Exception:
                log.exception("产量查询失败 type_id=%s", plan.get("product_type_id"))
                qty = 1
            total = max(int(runs or 1), 1) * max(int(parallels or 1), 1) * qty
            # 缺料是唯一阻塞时仍给按钮（点击后二次确认），文案点明是强制启动 ——
            # 否则会出现「行上显示启动、选中反而报不可启动」的自相矛盾
            self._main_btn.setText(f"强制启动 x {total}" if force else f"启动 x {total}")
            self._main_btn.setToolTip(f"{name} × {total}")
            self._main_btn.show()
            self._show_feedback("")
        else:
            self._main_btn.hide()
            self._show_feedback(f"不可启动：{reason}")

    def _copy_blueprint(self, plan_id: int) -> None:
        plan = self._plan_map.get(plan_id)
        if plan is None:
            return
        from services.ui_data_service import resolve_plan_blueprint_name

        bp_name = resolve_plan_blueprint_name(plan, db=get_container().db)
        if not bp_name:
            self._show_feedback("该计划无蓝图信息")
            return
        QApplication.clipboard().setText(bp_name)
        self._show_feedback(f"「{bp_name}」已复制进剪切板")

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

        # 软阻塞预检：材料缺口 / 蓝图流程不足 —— 两者都可强制启动（与计划表格同口径）
        allow_short = False
        allow_bp_short = False
        shortfalls: list[dict] = []
        if mat:
            try:
                shortfalls = [
                    r
                    for r in plan_execution.check_materials(plan, mat, stock=self._stock_cache.get(int(mat)))
                    if (r.get("missing") or 0) > 0
                ]
            except Exception:
                log.exception("材料校验失败 plan_id=%s", plan_id)
                shortfalls = []
        bp_short = self._bp_short(plan)

        reasons: list[str] = []
        if shortfalls:
            lines = "\n".join(f"  {r.get('name')}: 缺 {r.get('missing'):,.0f}" for r in shortfalls[:10])
            if len(shortfalls) > 10:
                lines += f"\n  … 等 {len(shortfalls)} 种"
            reasons.append(f"材料不足：\n{lines}")
        if bp_short:
            reasons.append(f"蓝图流程不足：{bp_short}")
        if reasons:
            if not can_force_start(
                plan,
                mat,
                self._all_plans,
                shortfall_count=len(shortfalls),
                bp_short=bp_short,
            ):
                # 除软阻塞外还有别的硬阻塞（无蓝图 / 等子项）→ 不该走到这里，兜底拦住
                QMessageBox.warning(self, "启动失败", self._block_reason(plan) or "当前不可启动")
                return
            ret = QMessageBox.question(
                self,
                "启动前确认",
                "\n\n".join(reasons) + "\n\n是否强制启动？\n"
                "材料按现有库存扣减、缺口记待补；蓝图**不会**自动补流程或换绑，"
                "完成时按实际可用流程消耗。\n"
                "由此产生的账面偏差，请稍后用「蓝图管理 → 粘贴导入蓝图 → 全量同步」矫正。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
            allow_short = bool(shortfalls)
            allow_bp_short = bool(bp_short)

        res = plan_execution.start_plan(
            plan,
            mat_hangar_id=mat,
            char_name=executor,
            allow_short=allow_short,
            allow_bp_short=allow_bp_short,
        )
        if res.get("ok"):
            self._show_feedback(f"已启动：{plan.get('product_name', '')}")
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

    def showEvent(self, event) -> None:
        """单实例复用时必须重启定时器 —— closeEvent 停表后不会自动恢复。

        否则「关闭再打开」得到的是不刷新倒计时/计划列表的死窗口。
        """
        super().showEvent(event)
        self._tick_timer.start()
        self._poll_timer.start()
        self._on_poll()

    def closeEvent(self, event) -> None:
        self._tick_timer.stop()
        self._poll_timer.stop()
        super().closeEvent(event)
