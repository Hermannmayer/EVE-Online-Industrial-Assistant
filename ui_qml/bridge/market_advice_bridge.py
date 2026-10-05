"""「挂单建议」对话框的桥与 QML 宿主。

入口在「可制造物品」窗口的右键菜单：`ManufacturableItemsBridge.showMarketAdvice(row)`
→ 构造本模块的 `MarketAdviceQmlDialog(type_id, name, host_widget())` → `show()`。

三处与同仓其它对话框一致的选择：

1. **只读查看器 → `modeless=True` + `show()`**（没有返回值要给调用方，也不该阻塞父窗）——
   与同一座桥里双击行开的「制造材料」（`all_items_bridge.MatQmlDialog`）同一形态。
2. **同步取数、不开 QThread**：`get_trade_advice` 只读本地 `market.db` 的三张表
   （`market_prices` / `price_history` / `market_volume_snapshots`），没有网络请求；
   需要打 ESI 的 `PriceChartQmlDialog` 那种才必须开线程。
3. **颜色只给 token 名**（`ACCENT_GREEN` / `ACCENT_YELLOW` / `PRIMARY` / `TEXT_SECONDARY`），
   QML 侧翻成 `Theme.*`（本仓惯例，见 `ImportReviewDialog.qml` 的 `tokenColor`）——
   桥里出现 hex 就是违反铁律。

**展示字段与大盘页 `advicePanel` 同款**（同一份服务、同一套措辞：verdict 标题 + 关键数字 +
买/卖建议 + 依据 + 口径 +「规则推导，不构成投资建议」），但映射函数是本模块**自己的一份**：
`market_pulse_bridge._advice_view` 是桥内私有函数，不跨模块 import。两处口径一起改时改两处；
真要收口就该提到共享模块（那时两处调用方就都齐了），本轮没做，理由见交付说明。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property

from core.logger import log
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["MarketAdviceBridge", "MarketAdviceQmlDialog", "advice_view"]

_QML_FILE = "dialogs/MarketAdviceDialog.qml"

#: 缺值占位符（与全仓一致：**不用 0 冒充**「没数据」）
_DASH = "—"

#: verdict → 面板标题（逐字对齐大盘页 `advicePanel` 的四档判定）
_ADVICE_TITLES: dict[str, str] = {
    "two_sided": "两侧挂单划算",
    "take_orders": "直接吃单更划算",
    "avoid_thin": "薄市场：别挂大单",
    "no_data": "本地没有这只物品的挂单/成交数据",
}

#: verdict → 标题颜色 token（QML 侧 `tokenColor()` 翻成 `Theme.*`）
_ADVICE_TOKENS: dict[str, str] = {
    "two_sided": "ACCENT_GREEN",
    "take_orders": "PRIMARY",
    "avoid_thin": "ACCENT_YELLOW",
    "no_data": "TEXT_SECONDARY",
}


def _advice_service() -> Any:
    """惰性取 `services.market_advice_service`。

    模块级 import 会把 services 整条业务链拖进外壳启动路径（与 `ui_qml/registry.py`
    的懒导入同一理由）；测试 monkeypatch 本函数就换掉了整个后端。
    """
    from services import market_advice_service

    return market_advice_service


# ════════════════════════════════════════════════════════════
#  纯格式化（桥层用例直接断言这些）
# ════════════════════════════════════════════════════════════


def _as_float(value: Any) -> float | None:
    """转 float；`None`/空串/非数值一律 `None`（调用方据此显示 `—`）。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(value: Any) -> str:
    """百分比两位小数；缺值 `—`。"""
    number = _as_float(value)
    return _DASH if number is None else f"{number:,.2f}%"


def _int_text(value: Any) -> str:
    """整数千分位（成交件数）；缺值 `—`。"""
    number = _as_float(value)
    return _DASH if number is None else f"{int(number):,}"


def _qty_text(value: Any) -> str:
    """数量：整数不带小数点，否则两位（日均成交量是小数）；缺值 `—`。"""
    number = _as_float(value)
    if number is None:
        return _DASH
    return f"{int(number):,}" if number == int(number) else f"{number:,.2f}"


def _order_queue_text(order_volume: Any, turn_days: Any) -> str:
    """卖单队列：`2,705 件 ≈ 89.3 天` —— 挂单量除以日均成交量就是「要排队几天」。"""
    vol = _as_float(order_volume)
    days = _as_float(turn_days)
    if vol is None:
        return _DASH
    if days is None:
        return f"{_int_text(vol)} 件"
    return f"{_int_text(vol)} 件 ≈ {days:,.1f} 天"


def advice_view(raw: dict) -> dict:
    """`get_trade_advice` → QML 展示字段；`raw` 为空 → `{}`（QML 走空态）。

    数字行把「为什么这么建议」摊开：价差、来回费用、日均成交、卖单队列 ——
    只给一句「两侧挂单划算」用户无法判断该不该信。**缺值一律 `—`**，不拿 0 冒充。
    """
    if not raw:
        return {}
    verdict = str(raw.get("verdict") or "")
    return {
        "verdict": verdict,
        "title": _ADVICE_TITLES.get(verdict, _DASH),
        "token": _ADVICE_TOKENS.get(verdict, "TEXT_SECONDARY"),
        "metrics": [
            {"label": "价差（卖−买）", "value": _pct(raw.get("spreadPct"))},
            {"label": "来回费用（买+卖+税）", "value": _pct(raw.get("roundTripFeePct"))},
            {"label": "近 7 天日均成交", "value": _qty_text(raw.get("dayVolume"))},
            {"label": "卖单队列", "value": _order_queue_text(raw.get("orderVolume"), raw.get("turnDays"))},
        ],
        "buyAdvice": str(raw.get("buyAdvice") or ""),
        "sellAdvice": str(raw.get("sellAdvice") or ""),
        "reasons": [str(reason) for reason in (raw.get("reasons") or [])],
        "caliber": str(raw.get("caliber") or ""),
    }


# ════════════════════════════════════════════════════════════
#  桥 / 宿主
# ════════════════════════════════════════════════════════════


class MarketAdviceBridge(DialogBridge):
    """「挂单建议」的 QML 后端（只读，构造时同步取一次本地行情）。"""

    def __init__(self, type_id: int, name: str = "") -> None:
        super().__init__()
        self._type_id = int(type_id)
        self._status = ""
        raw = self._load()
        self._view = advice_view(raw)
        #: 名字优先用调用方给的（右键那一行的物品名），次选服务解析出来的，最后退回 type_id
        self._name = str(name or raw.get("name") or self._type_id)
        self.set_title(f"挂单建议 — {self._name}")

    #: 顶部标题：物品名 + Type ID
    headerText = Property(str, lambda self: f"{self._name} (Type ID: {self._type_id})", constant=True)
    #: 取数失败说明行（空串 = 不显示）
    statusText = Property(str, lambda self: self._status, constant=True)
    #: 四档判定之一；空串 = 没取到建议（QML 走空态）
    verdict = Property(str, lambda self: str(self._view.get("verdict") or ""), constant=True)
    #: 判定标题（一句话结论）
    title = Property(str, lambda self: str(self._view.get("title") or ""), constant=True)
    #: 标题颜色 token（QML 翻成 `Theme.*`）
    token = Property(str, lambda self: str(self._view.get("token") or "TEXT_SECONDARY"), constant=True)
    #: 关键数字四行 `[{label, value}]`（缺数据一律 `—`）
    metrics = Property(list, lambda self: list(self._view.get("metrics") or []), constant=True)
    buyAdvice = Property(str, lambda self: str(self._view.get("buyAdvice") or ""), constant=True)
    sellAdvice = Property(str, lambda self: str(self._view.get("sellAdvice") or ""), constant=True)
    reasons = Property(list, lambda self: list(self._view.get("reasons") or []), constant=True)
    #: 口径说明（服务侧逐字给的，UI 直接显示）
    caliber = Property(str, lambda self: str(self._view.get("caliber") or ""), constant=True)

    def _load(self) -> dict:
        """同步取一次建议；失败 → 空 dict + 状态行（对话框照样打得开）。

        这里吞的是**读本地库**这一类失败：`sqlite3.Error`（`market.db` 打不开、表被写锁住）、
        服务侧的 `ValueError`/`TypeError`（口径算不出）以及服务未落地的
        `ModuleNotFoundError`/`AttributeError`。失败退化成空态 + 一行说明，原因进日志 ——
        不该因为一次读库失败让右键菜单炸掉。
        """
        try:
            service = _advice_service()
            # region 与大盘同源：取服务自己的 `JITA_RID`，不在桥里写死 10000002
            return dict(service.get_trade_advice(self._type_id, region_id=int(service.JITA_RID)))
        except Exception:
            log.exception("读取交易建议失败 typeId=%s", self._type_id)
            self._status = "读取本地行情失败（详见日志）"
            return {}


class MarketAdviceQmlDialog(QmlDialog):
    """QML 版「挂单建议」。

    只读查看器 → **非模态独立窗**（`modeless=True`），调用方用 `show()` 而非 `exec()`；
    保活与 `WA_DeleteOnClose` 由 `dialog_host` 统一负责，调用方不必自己缓存实例。
    `parent` 照吃但会被 `QmlDialog` 忽略（独立窗要的是真 top-level）—— 留着只为让调用点
    与同族对话框（`MatQmlDialog` / `PriceChartQmlDialog`）写法一致。
    """

    def __init__(self, type_id: int, name: str = "", parent: Any = None) -> None:
        bridge = MarketAdviceBridge(type_id, name)
        super().__init__(_QML_FILE, bridge, parent=parent, size=(560, 460), modeless=True)
