"""`PlanTableModel` → QML 可消费形式。

与 `estimate_qml_model` 同一套适配思路（QML 只认命名角色、渲染不了 `QPixmap`），
但生产计划表有 21 列且每列的渲染方式都不同，因此这里**不按列开角色**，而是把
Widgets 版 delegate 的展示职责折成几个「按索引取值」的角色：

| 角色 | 说明 |
|---|---|
| `text` | 该单元格的显示文本（等价 `DisplayRole`，逐列计算） |
| `fg` | 该单元格的前景色，空串 = 用默认色 |
| `bg` | 该单元格的底色（类别染色），空串 = 无 |
| `iconUrl` | 该单元格的图标（`file://` URL），空串 = 无 |
| `iconColor` | SVG 图标的染色值 |
| `checked` | 备料勾选列的勾选态 |
| … | 见 `ROLE_NAMES` |

关键点：角色名是固定的，但 `data()` 拿得到完整 index，**列信息在取值时才算**，
所以一个 `text` 角色就能覆盖 21 列，QML delegate 里不必写 21 路 switch。

颜色以**已解析的 hex 字符串**返回而非 token 名：QML 侧拿 token 名字符串做属性查表
（`Theme[name]`）无法参与依赖追踪，主题切换时不会重绘；改为表在主题变更时调
`refresh_colors()` 统一补发 `dataChanged`（见 `PlanTable._on_theme_changed`）。
hex 本身仍全部来自 `ui_qml.theme.registry`，不违反「配色只在 theme」的铁律。
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QModelIndex, Qt, QUrl, Signal
from PySide6.QtGui import QColor

from ui_qml.icon_cache import item_icon_path
from ui_qml.icon_provider import PROVIDER_ID
from ui_qml.icons import svg_path
from ui_qml.models.industry_models import PlanTableModel
from ui_qml.models.plan_table_constants import (
    COL_BLUEPRINT,
    COL_CATEGORY,
    COL_ICON,
    COL_PRODUCT,
    COL_PROFIT,
    COL_STATUS,
    COL_TIME,
)
from ui_qml.theme import registry as theme

__all__ = ["PlanQmlModel", "ROLE_NAMES"]

_BASE = Qt.ItemDataRole.UserRole
ROLE_NAMES: dict[int, bytes] = {
    _BASE + 1: b"text",
    _BASE + 2: b"fg",
    _BASE + 3: b"bg",
    _BASE + 4: b"iconUrl",
    _BASE + 5: b"checked",
    _BASE + 6: b"editable",
    _BASE + 7: b"statusKey",
    _BASE + 8: b"isSynthetic",
    _BASE + 9: b"foldState",
    _BASE + 10: b"indent",
    _BASE + 11: b"tooltip",
    _BASE + 12: b"rowIndex",
    _BASE + 13: b"planId",
    _BASE + 14: b"groupKey",
}

_TEXT = _BASE + 1
_FG = _BASE + 2
_BG = _BASE + 3
_ICON_URL = _BASE + 4
_CHECKED = _BASE + 5
_EDITABLE = _BASE + 6
_STATUS_KEY = _BASE + 7
_SYNTHETIC = _BASE + 8
_FOLD_STATE = _BASE + 9
_INDENT = _BASE + 10
_TOOLTIP = _BASE + 11
_ROW_INDEX = _BASE + 12
_PLAN_ID = _BASE + 13
_GROUP_KEY = _BASE + 14

# 类别 → 图标文件 + 染色 token（对齐 plan_table_delegate 的 _CATEGORY_ICON_FILES）
_CATEGORY_ICONS: dict[str, tuple[str, str]] = {
    "manufacturing": ("gear-six-fill", "TEXT_SECONDARY"),
    "invention": ("lightbulb-fill", "ACCENT_PURPLE"),
    "reaction": ("flask-fill", "ACCENT_GREEN"),
    "copying": ("clipboard-text-fill", "ACCENT_CYAN"),
}

# 类别 → 整行底色 token（对齐 delegate 的 _CATEGORY_COLORS）
_CATEGORY_TINTS: dict[str, str] = {
    "copying": "ACCENT_CYAN",
    "invention": "ACCENT_PURPLE",
    "reaction": "ACCENT_GREEN",
}


def phosphor_url(filename: str, color: str, size: int = 16) -> str:
    """Phosphor SVG 的 `image://phosphor/...` URL（颜色与尺寸编进查询串）。

    走 `ui_qml.icon_provider` 而不是 `file://`：QML 的 `Image` 拿到原始 SVG
    是**未染色**的（Phosphor 的 fill 在根节点上），必须在取图时注入。
    文件不存在时返回空串，QML 的 Image 不加载也不报警告。
    """
    if not os.path.isfile(svg_path(filename)):
        return ""
    encoded = str(color).replace("#", "%23")
    return f"image://{PROVIDER_ID}/{filename}?c={encoded}&s={int(size)}"


def _png_url(type_id: Any) -> str:
    """物品图标（磁盘上的 PNG）URL。"""
    if not type_id:
        return ""
    path = item_icon_path(int(type_id))
    if not os.path.isfile(path):
        return ""
    return QUrl.fromLocalFile(path).toString()


def _token(name: str) -> str:
    """按 token 名取当前主题色值。"""
    return str(getattr(theme, name, "") or "")


#: 类别底色的不透明度。**必须带透明度**：旧 Widgets 版直接把类别色当整行底色
#: （100% 饱和），文字压在上面几乎读不出来（实测绿底上的「生产中」就是如此）。
#: Fluent 的强调色底同样只用浅色调，这里按 18% 叠加，既保留类别区分又不伤可读性。
_TINT_ALPHA = 0.18


def _tint(name: str) -> str:
    """类别色 → 带透明度的 `#AARRGGBB`（QML 的 color 认这个格式）。"""
    color = QColor(_token(name))
    if not color.isValid():
        return ""
    color.setAlphaF(_TINT_ALPHA)
    return color.name(QColor.NameFormat.HexArgb)


class PlanQmlModel(PlanTableModel):
    """生产计划模型 + QML 命名角色。数据/排序/折叠逻辑全在父类。"""

    #: 排序状态变化（QML 表头据此画升降序箭头）
    sortChanged = Signal()

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return ROLE_NAMES

    # ── 取值 ──────────────────────────────────────────────────

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        if role < _TEXT:
            # Display/Decoration/Foreground/UserRole… 交回父类，Widgets 视图照常可用
            return super().data(index, role)

        p = self._plan_at(index.row())
        c = index.column()

        if role == _TEXT:
            return self._display_text(p, c)
        if role == _FG:
            return self._fg(p, c)
        if role == _BG:
            tint = _CATEGORY_TINTS.get(str(p.get("category") or ""))
            return _tint(tint) if tint else ""
        if role == _ICON_URL:
            return self._icon_url(p, c)
        if role == _CHECKED:
            return bool(p.get("materials_ready", 0))
        if role == _EDITABLE:
            return c in self._EDITABLE_COLS and p.get("status") not in ("completed", "done")
        if role == _STATUS_KEY:
            return str(p.get("status") or "").lower()
        if role == _SYNTHETIC:
            return bool(p.get("_synthetic"))
        if role == _FOLD_STATE:
            return self._fold_state(p) if c == COL_PRODUCT else ""
        if role == _INDENT:
            return int(p.get("child_level") or 0) if c == COL_PRODUCT else 0
        if role == _TOOLTIP:
            return self._levels_tooltip(p) if c == COL_BLUEPRINT else ""
        if role == _ROW_INDEX:
            return index.row()
        if role == _PLAN_ID:
            return p.get("id")
        if role == _GROUP_KEY:
            return p.get("group_id") or p.get("group_number") or 0
        return None

    def _plan_at(self, row: int) -> dict:
        """过滤行号 → 行 dict（折叠时经 `_row_map` 映射）。"""
        actual = self._row_map(row) if self._collapsed_groups else row
        return self._plans[actual] if 0 <= actual < len(self._plans) else {}

    # ── 列级展示规则（逐条对齐 plan_table_delegate） ─────────────

    def _fg(self, p: dict, c: int) -> str:
        if c == COL_PROFIT:
            profit = p.get("profit", 0) or 0
            if profit > 0:
                return _token("GREEN")
            if profit < 0:
                return _token("RED")
        if c == COL_TIME:
            status = p.get("status", "")
            if status in ("in_progress", "running"):
                from services.plan_execution import remaining_seconds

                rem = remaining_seconds(p)
                if rem is not None and rem <= 0:
                    return _token("ACCENT_RED")
                return _token("PRIMARY")
            if status == "ready":
                return _token("ACCENT_ORANGE")
        if c == COL_STATUS:
            status = p.get("status", "")
            if status in ("completed", "done"):
                return _token("GREEN")
            if status in ("in_progress", "running"):
                return _token("PRIMARY")
            if status == "ready":
                return _token("ACCENT_ORANGE")
            if status == "pending":
                return _token("TEXT_SECONDARY")
        if c == COL_BLUEPRINT and (p.get("status") or "") not in ("completed", "done"):
            # 蓝图绑定不足：标红提示「差 N 张」
            bound = p.get("bound_blueprint_ids") or []
            if len(bound) < int(p.get("need_blueprints") or 1):
                return _token("ACCENT_RED")
        return ""

    def _icon_url(self, p: dict, c: int) -> str:
        if c == COL_ICON:
            return _png_url(p.get("product_type_id"))
        if c == COL_CATEGORY:
            spec = _CATEGORY_ICONS.get(str(p.get("category", "manufacturing")))
            return phosphor_url(spec[0], _token(spec[1]), 16) if spec else ""
        if c == COL_PRODUCT and int(p.get("child_level") or 0) > 0:
            return phosphor_url("caret-right", _token("TEXT_SECONDARY"), 16)  # 子项层级箭头
        return ""

    def _fold_state(self, p: dict) -> str:
        """产品列的折叠态：`""` 无可折叠 | `expanded` | `collapsed`。

        父类的 `_display_text` 会给文本前缀 ▼/▶，QML 侧改为画图标，故这里单独给状态。
        """
        gid = p.get("group_id") or p.get("group_number") or 0
        if p.get("_synthetic"):
            return "collapsed" if -1 in self._collapsed_groups else "expanded"
        if int(p.get("child_level") or 0) > 0:
            return ""
        if gid and self._has_children(gid):
            return "collapsed" if gid in self._collapsed_groups else "expanded"
        return ""

    # `text` 角色不要折叠图标：QML 用 `foldState` 单独画
    def _display_text(self, p: dict, c: int) -> str:  # type: ignore[override]
        text = super()._display_text(p, c)
        if c == COL_PRODUCT and text[:1] in ("▼", "▶"):
            return text[2:]
        return text

    # ── 主题变更 ──────────────────────────────────────────────

    def refresh_colors(self) -> None:
        """主题切换后重算所有单元格颜色（`fg`/`bg`/`iconColor` 是已解析的 hex）。"""
        if not self._plans:
            return
        rows = self.rowCount()
        self.dataChanged.emit(self.index(0, 0), self.index(rows - 1, self.columnCount() - 1), list(ROLE_NAMES))

    # ── 排序 ─────────────────────────────────────────────────

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:  # type: ignore[override]
        super().sort(column, order)
        self.sortChanged.emit()

    @property
    def sort_column(self) -> int:
        return self._sort_col

    @property
    def sort_ascending(self) -> bool:
        return self._sort_order == Qt.SortOrder.AscendingOrder
