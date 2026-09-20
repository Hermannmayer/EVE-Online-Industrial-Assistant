"""合同市场 —— 三个子页各自的表格模型 + 物品明细模型。

**为什么是「一个模型 + 三份视图定义」而不是三个模型类**：三张表的行数据同源
（`services.contract_service` 的三个入口给出的都是扁平 dict），差别只在「显示哪几列、
怎么格式化、什么颜色」。写成三个类会把同一套 `set_rows`/`sort`/`roleNames` 抄三遍。

列定义与取值规则集中在本模块 —— 桥暴露给 QML 的列宽、QML 表格的 delegate 宽度、
点击命中区三处必须取同一份，各算一次必然错位。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Slot
from PySide6.QtGui import QColor, QFont

from domain.contract_analysis import STATUS_NO_ITEMS, STATUS_NO_PRICE
from ui_qml.icon_cache import icon_url
from ui_qml.icon_provider import phosphor_url
from ui_qml.theme import registry as theme

# ── 合同类型中文映射 ──
CONTRACT_TYPE_CN = {
    "item_exchange": "物品交换",
    "auction": "拍卖",
    "courier": "运输",
}

# ── 缺值统一显示「—」：0 与「没有数据」是两回事 ──
_DASH = "—"


#: 「物品」列里没有图的物品统一用这个 Phosphor 图标顶替（`ui_qml/assets/icons/` 里随仓库走，
#: 不依赖用户本地图标缓存）。**为什么要有顶替**：涂装在 EVE 图床就是 404，蓝图的图在
#: `/bp` 端点、本地缓存只下了有 `iconID` 的那批 —— 不顶替的话这一列大半是空的，
#: 看着像「读取失败」。图标只是个「这是一件物品」的占位，认东西靠右边的名字。
_FALLBACK_ICON_NAME = "package"
_FALLBACK_ICON_PX = 32  # 渲染 32 再让 QML 缩到 18，屏幕缩略更干净


def _fallback_icon_url() -> str:
    """占位图标的 URL —— 颜色**每次取**（切主题后要跟着变，不能在导入期定死）。"""
    return phosphor_url(_FALLBACK_ICON_NAME, theme.TEXT_SECONDARY, _FALLBACK_ICON_PX)


def _content_cell(row: dict) -> str:
    """「物品」列的文本：主物品名（+ 其余件数）。

    图标只覆盖一小部分物品（涂装在 EVE 图床就是 404），所以这一列**必须有名字兜底**，
    否则半数合同看着像空的。物品还没补齐时返回空串 —— 空着表示「还不知道」，
    不是「里面没东西」。
    """
    name = str(row.get("top_item_name") or "")
    if not name:
        return ""
    count = int(row.get("item_count") or 0)
    return f"{name} +{count - 1}" if count > 1 else name


#: 内容物市价**不可信**的状态。此时「价差」等于「−合同价」（市价按 0 算），
#: 整屏都是巨额负数，看着像「所有合同都不值得买」—— 那是物品还没拉，不是结论。
#: 必须显示「—」，让用户看出「还没算」而不是「算了，是亏的」。
_UNVALUED = frozenset({STATUS_NO_ITEMS, STATUS_NO_PRICE})


def _valued(row: dict) -> bool:
    """内容物市价算得出来吗（有物品、且至少一件有价）。"""
    return row.get("status") not in _UNVALUED


def _isk(value: Any) -> str:
    return f"{float(value):,.0f}" if value else _DASH


def _isk_signed(value: Any) -> str:
    if value is None:
        return _DASH
    return f"{float(value):+,.0f}"


def _pct_signed(value: Any) -> str:
    return _DASH if value is None else f"{float(value):+.1f}%"


def _m3(value: Any) -> str:
    return f"{float(value):,.1f}" if value else _DASH


def _count(value: Any) -> str:
    return f"{int(value):,}" if value else _DASH


def _remaining(seconds: Any) -> str:
    """剩余时间 —— 合同最要紧的一列，跨天给「N天M小时」，一天内给「M小时」。"""
    if seconds is None:
        return _DASH
    secs = int(seconds)
    if secs <= 0:
        return "已过期"
    days, rest = divmod(secs, 86_400)
    hours = rest // 3600
    if days:
        return f"{days}天{hours}小时"
    minutes = (rest % 3600) // 60
    return f"{hours}小时{minutes}分"


def _place(station: Any, system: Any, security: Any) -> str:
    """站点列 —— 站名与星系都给（同名站点遍布新伊甸，只给站名会认错地方）。"""
    if not station:
        return "未知地点"
    sec = f" {float(security):.1f}" if security is not None else ""
    return f"{station} ({system}{sec})" if system else str(station)


@dataclass(frozen=True)
class ContractView:
    """一张合同表的列定义与取值规则。"""

    key: str
    columns: tuple[tuple[str, int], ...]
    #: 右对齐 + 等宽字体的列号（金额/数量）
    numeric: frozenset[int] = field(default_factory=frozenset)
    #: `(行, 列) → 显示文本`
    render: Callable[[dict, int], str] = lambda _row, _col: ""
    #: 该列存的是不是「价差」—— 正绿负红
    diff_columns: frozenset[int] = field(default_factory=frozenset)
    #: 「里面是什么」的列号（-1 = 没有这一列）。该列的文字前会画上主物品图标，
    #: 图标走 `iconUrls` role —— 有没有图标都照常显示文字
    icon_column: int = -1


# ── 拍卖 ──


def _render_auction(row: dict, col: int) -> str:
    valued = _valued(row)
    return [
        _content_cell(row),
        str(row.get("title") or _DASH),
        str(row.get("issuer_name") or _DASH),
        _isk(row.get("buyout")),
        _isk(row.get("current_bid")),
        _isk(row.get("market_value")) if valued else _DASH,
        _isk_signed(row.get("price_diff")) if valued else _DASH,
        _pct_signed(row.get("diff_pct")) if valued else _DASH,
        _remaining(row.get("remaining_seconds")),
        _place(row.get("start_station"), row.get("start_system"), row.get("start_security")),
    ][col]


AUCTION_VIEW = ContractView(
    key="auction",
    columns=(
        ("物品", 230),
        ("标题", 150),
        ("发布者", 140),
        ("一口价", 130),
        ("当前出价", 130),
        ("内容物市价", 140),
        ("价差", 130),
        ("价差%", 80),
        ("剩余", 90),
        ("地点", 230),
    ),
    numeric=frozenset({3, 4, 5, 6, 7}),
    diff_columns=frozenset({6, 7}),
    icon_column=0,
    render=_render_auction,
)


# ── 物品交换 ──


def _render_exchange(row: dict, col: int) -> str:
    valued = _valued(row)
    return [
        _content_cell(row),
        str(row.get("title") or _DASH),
        str(row.get("issuer_name") or _DASH),
        _isk(row.get("entry_cost")),
        _isk(row.get("market_value")) if valued else _DASH,
        _isk_signed(row.get("price_diff")) if valued else _DASH,
        _pct_signed(row.get("diff_pct")) if valued else _DASH,
        "是" if row.get("has_blueprint") else "",
        # 没有蓝图的行走普通口径，蓝图两列为空而不是 0
        _isk(row.get("blueprint_value")) if row.get("has_blueprint") and valued else _DASH,
        _isk(row.get("manufacturing_profit")) if row.get("has_blueprint") and valued else _DASH,
        _remaining(row.get("remaining_seconds")),
        _place(row.get("start_station"), row.get("start_system"), row.get("start_security")),
    ][col]


EXCHANGE_VIEW = ContractView(
    key="exchange",
    columns=(
        ("物品", 230),
        ("标题", 150),
        ("发布者", 140),
        ("合同价", 130),
        ("内容物市价", 140),
        ("价差", 130),
        ("价差%", 80),
        ("蓝图", 50),
        ("蓝图市价", 130),
        ("制造利润", 130),
        ("剩余", 90),
        ("地点", 230),
    ),
    numeric=frozenset({3, 4, 5, 6, 8, 9}),
    diff_columns=frozenset({5, 6}),
    icon_column=0,
    render=_render_exchange,
)


# ── 运输 ──

#: 跳数为什么空着 —— 与 `services.contract_service` 的状态码一一对应。
#: **不能都显示成「—」**：「高安口径下无路线」意味着这活要穿低安，是决策信息；
#: 「起止点解析不出」是我们不知道这是哪。两者行动相反。
_JUMP_TEXT = {
    "not_computed": "未计算",
    "unknown_endpoint": "未知地点",
    "unroutable": "需穿低安",
    "ok": "",
}


def _render_courier(row: dict, col: int) -> str:
    status = str(row.get("jumps_status") or "")
    jumps = row.get("jumps")
    jumps_text = str(jumps) if jumps is not None else _JUMP_TEXT.get(status, _DASH)
    return [
        str(row.get("issuer_name") or _DASH),
        _place(row.get("start_station"), row.get("start_system"), row.get("start_security")),
        _place(row.get("end_station"), row.get("end_system"), row.get("end_security")),
        jumps_text,
        _m3(row.get("volume_m3")),
        _isk(row.get("reward")),
        _isk(row.get("collateral")),
        _isk(row.get("isk_per_jump")),
        _isk(row.get("isk_per_jump_m3")),
        _remaining(row.get("remaining_seconds")),
    ][col]


COURIER_VIEW = ContractView(
    key="courier",
    columns=(
        ("发布者", 140),
        ("起点", 185),
        ("终点", 185),
        ("跳数", 80),
        ("方数", 90),
        ("报酬", 130),
        ("抵押", 130),
        ("每跳 ISK", 110),
        ("每方每跳 ISK", 120),
        ("剩余", 90),
    ),
    numeric=frozenset({4, 5, 6, 7, 8}),
    render=_render_courier,
)


VIEWS: dict[str, ContractView] = {
    AUCTION_VIEW.key: AUCTION_VIEW,
    EXCHANGE_VIEW.key: EXCHANGE_VIEW,
    COURIER_VIEW.key: COURIER_VIEW,
}


# ═══════════════════════════════════════════════════════════
#  QML 命名角色
# ═══════════════════════════════════════════════════════════

_BASE = Qt.ItemDataRole.UserRole
_C_TEXT = _BASE + 1
_C_FG = _BASE + 2
_C_BG = _BASE + 3
_C_ALIGN = _BASE + 4
_C_MONO = _BASE + 5
_C_ICONS = _BASE + 6

CONTRACT_ROLE_NAMES: dict[int, bytes] = {
    _C_TEXT: b"text",
    _C_FG: b"fg",
    _C_BG: b"bg",
    _C_ALIGN: b"alignRight",
    _C_MONO: b"mono",
    #: 该行主物品的图标 URL 列表（缺图标文件的已被滤掉；涂装之类本来就没有图）
    _C_ICONS: b"iconUrls",
}


class ContractTableModel(QAbstractTableModel):
    """一张合同表 —— 外观由传入的 `ContractView` 决定。"""

    def __init__(self, view: ContractView, parent=None):
        super().__init__(parent)
        self._view = view
        self._rows: list[dict] = []
        self._sort_col = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    @property
    def view(self) -> ContractView:
        return self._view

    @property
    def sort_column(self) -> int:
        """当前排序列（-1 = 没排过，仍是 SQL 给的「按价格降序」）。"""
        return self._sort_col

    @property
    def sort_descending(self) -> bool:
        return self._sort_order == Qt.SortOrder.DescendingOrder

    def set_rows(self, rows: list[dict]) -> None:
        """换一批数据，**保留用户点过的排序**。

        补齐过程每 500 条就重播一次列表，无条件重置排序列的话，用户按价差排好序后
        会被一次次抖回默认序（旧实现只在「手动点一次补齐、等它跑完」的年代无所谓）。
        """
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        if self._sort_col >= 0:
            self.sort(self._sort_col, self._sort_order)

    @Slot()
    def notifyReset(self) -> None:
        """把当前行原样重播一次（触发模型重置）。

        只为修一个 Qt 侧的静默缺陷：**数据比首次布局先到**时（页面 `Component.onCompleted`
        就发起查库，快过窗口 show），`TableView` 的 `contentItem` 会停在 0×0 且此后不自愈
        —— 点击区 `anchors.fill: parent` 跟着变成 0×0，界面看着完全正常，但点哪一行都没反应。

        实测只有**模型重置**能重算：`forceLayout()`、重挂 `model` 都不行。
        所以 QML 侧在表第一次拿到实际尺寸时调本方法（见 `ContractTabPane.qml`）。
        """
        self.set_rows(list(self._rows))

    def get_row(self, idx: int) -> dict | None:
        return self._rows[idx] if 0 <= idx < len(self._rows) else None

    def rowCount(self, parent=None) -> int:
        return len(self._rows)

    def columnCount(self, parent=None) -> int:
        return len(self._view.columns)

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return CONTRACT_ROLE_NAMES

    def _fg(self, row: dict, col: int) -> str:
        #: 价差列正绿负红 —— 这是整页最常被扫的一列；算不出来时给次级色而不是判成「负」
        if col in self._view.diff_columns:
            if not _valued(row) or row.get("price_diff") is None:
                return theme.TEXT_SECONDARY
            return theme.ACCENT_GREEN if row["price_diff"] > 0 else theme.ACCENT_RED
        return theme.TEXT_PRIMARY

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == _C_TEXT:
            return self._view.render(row, col)
        if role == _C_FG:
            return self._fg(row, col)
        if role == _C_BG:
            return theme.BG_SURFACE if index.row() % 2 == 0 else theme.BG_DARK
        if role == _C_ALIGN:
            return col in self._view.numeric
        if role == _C_MONO:
            return col in self._view.numeric
        if role == _C_ICONS:
            # 图标 URL 只对**可见单元格**求值（`icon_url` 要 stat 图标文件，
            # 3000 行 × 3 件一次性算完就是几千次系统调用，而屏幕上只有几十行）
            if col != self._view.icon_column:
                return []
            fallback = _fallback_icon_url()
            return [icon_url(t) or fallback for t in row.get("icon_type_ids") or []]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section >= len(self._view.columns):
                return None
            label = self._view.columns[section][0]
            if section == self._sort_col:
                label += " ▲" if self._sort_order == Qt.SortOrder.AscendingOrder else " ▼"
            return label
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        if not (0 <= column < len(self._view.columns)):
            return
        key = _SORT_KEYS.get(self._view.key, {}).get(column)
        if key is None:
            return
        # 「没有数据」永远排在末尾，**不随升降序翻转** —— 用 `(is None, value)` 当排序键
        # 再 reverse 的话，降序会把「算不出价差」「跳数未知」的行顶到最前面，
        # 而它们恰恰是最不该占着第一屏的。
        present = [r for r in self._rows if r.get(key) is not None]
        missing = [r for r in self._rows if r.get(key) is None]
        present.sort(key=lambda r: r[key], reverse=order == Qt.SortOrder.DescendingOrder)
        self.beginResetModel()
        self._rows = present + missing
        self._sort_col = column
        self._sort_order = order
        self.endResetModel()


#: 列号 → 该列的排序字段。文本列也给 —— 不排序的列点了表头没反应会显得是坏的。
_SORT_KEYS: dict[str, dict[int, str]] = {
    "auction": {
        2: "issuer_name",
        3: "buyout",
        4: "current_bid",
        5: "market_value",
        6: "price_diff",
        7: "diff_pct",
        8: "remaining_seconds",
    },
    "exchange": {
        2: "issuer_name",
        3: "entry_cost",
        4: "market_value",
        5: "price_diff",
        6: "diff_pct",
        8: "blueprint_value",
        9: "manufacturing_profit",
    },
    "courier": {
        0: "issuer_name",
        3: "jumps",
        4: "volume_m3",
        5: "reward",
        6: "collateral",
        7: "isk_per_jump",
        8: "isk_per_jump_m3",
    },
}


# ═══════════════════════════════════════════════════════════
#  合同内物品
# ═══════════════════════════════════════════════════════════

ITEM_COLUMNS = (
    ("中文名", 170),
    ("英文名", 150),
    ("数量", 70),
    ("蓝图复制品", 80),
    ("包含", 60),
    ("ME", 50),
    ("PE", 50),
    ("剩余流程数", 90),
    ("单价", 110),
    ("小计", 120),
    # 合同级的三个数，放在最后：它们对同一份合同的每一行都一样，跟着物品列会喧宾夺主
    ("合同价", 130),
    ("内容物市价", 140),
    ("价差", 130),
)

#: 物品表画图标的那一列（首列，与总表的「物品」列同款：图标在名字前面）
ITEM_ICON_COLUMN = 0

_ITEM_NUMERIC = frozenset({2, 7, 8, 9, 10, 11, 12})

_I_TEXT = _BASE + 1
_I_ALIGN = _BASE + 2
_I_ICONS = _BASE + 3

ITEM_ROLE_NAMES: dict[int, bytes] = {
    _I_TEXT: b"text",
    _I_ALIGN: b"alignRight",
    _I_ICONS: b"iconUrls",
}

#: 物品表可排序列 → 取值函数。没列进来的（蓝图复制品/包含/ME/PE/合同级三列）点了不排 ——
#: 是/否列与整列同值的列，排了等于没排。BPO 的「剩余流程数」给 None：**排最后**而不是当 0，
#: 0 会被读成「一次都跑不了」。
_ITEM_SORT_KEYS: dict[int, Callable[[dict], Any]] = {
    0: lambda it: str(it.get("zh_name") or ""),
    2: lambda it: int(it.get("quantity") or 0),
    7: lambda it: int(it.get("runs") or 1) if it.get("is_blueprint_copy") else None,
    8: lambda it: it.get("unit_price"),
    9: lambda it: (it.get("unit_price") or 0) * int(it.get("quantity") or 0),
}


class ContractItemTableModel(QAbstractTableModel):
    """合同内物品明细（含市场单价与小计）。

    末尾三列是**合同级**的数（合同价/内容物市价/价差），来自被选中的那份合同 ——
    看物品的同时不必再回头找上面那一行。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._contract: dict = {}
        self._sort_col: int = -1
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder

    def set_contract(self, contract: dict | None) -> None:
        """换一份合同（末尾三列的值来源）。未选中时清空。"""
        self._contract = dict(contract or {})

    @property
    def sort_column(self) -> int:
        return self._sort_col

    @property
    def sort_descending(self) -> bool:
        return self._sort_order == Qt.SortOrder.DescendingOrder

    @property
    def numeric_columns(self) -> frozenset[int]:
        """右对齐/可比较大小的列（供「首次点这一列给升序还是降序」判断）。"""
        return _ITEM_NUMERIC

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        if self._sort_col >= 0:
            self.sort(self._sort_col, self._sort_order)

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        key = _ITEM_SORT_KEYS.get(column)
        if key is None:
            return
        # 「没有数据」永远排在末尾，不随升降序翻转（与总表同一条规矩）
        present = [r for r in self._rows if key(r) is not None]
        missing = [r for r in self._rows if key(r) is None]
        present.sort(key=key, reverse=order == Qt.SortOrder.DescendingOrder)
        self.beginResetModel()
        self._rows = present + missing
        self._sort_col = column
        self._sort_order = order
        self.endResetModel()

    def rowCount(self, parent=None) -> int:
        return len(self._rows)

    def columnCount(self, parent=None) -> int:
        return len(ITEM_COLUMNS)

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return ITEM_ROLE_NAMES

    def _display(self, row: dict, col: int) -> str:
        quantity = int(row.get("quantity") or 0)
        unit = row.get("unit_price")
        contract = self._contract
        valued = _valued(contract)
        return [
            str(row.get("zh_name") or _DASH),
            str(row.get("en_name") or _DASH),
            str(quantity),
            "是" if row.get("is_blueprint_copy") else "否",
            "是" if row.get("is_included", True) else "否",
            str(row["material_efficiency"]) if row.get("material_efficiency") else _DASH,
            str(row["time_efficiency"]) if row.get("time_efficiency") else _DASH,
            _count(row.get("runs")) if row.get("is_blueprint_copy") else _DASH,
            _isk(unit),
            _isk(float(unit) * quantity) if unit else _DASH,
            _isk(contract.get("entry_cost")),
            _isk(contract.get("market_value")) if valued else _DASH,
            _isk_signed(contract.get("price_diff")) if valued else _DASH,
        ][col]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == _I_TEXT:
            return self._display(row, col)
        if role == _I_ALIGN:
            return col in _ITEM_NUMERIC
        if role == _I_ICONS:
            # 与总表同一套：有图用图，没图（涂装等）用通用占位图标
            if col != ITEM_ICON_COLUMN:
                return []
            return [icon_url(int(row.get("type_id") or 0)) or _fallback_icon_url()]
        if role == Qt.ItemDataRole.BackgroundRole:
            return QColor(theme.BG_SURFACE if index.row() % 2 == 0 else theme.BG_DARK)
        if role == Qt.ItemDataRole.FontRole and col in _ITEM_NUMERIC:
            return QFont("Consolas", 10)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section >= len(ITEM_COLUMNS):
                return None
            return ITEM_COLUMNS[section][0]
        return None
