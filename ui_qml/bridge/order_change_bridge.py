"""订单变动确认对话框 —— 读取订单后逐条选定「成交 / 手动撤销」。

原先读订单成功后只弹一个「是 / 否」问答（「要把没出现的旧订单标记为已结束吗」），
既问不出「这笔是卖出成交还是我自己撤销的」，也没法据此调整钱包余额。本对话框换成
**逐条选择**：

- 每条变动给三选一：**买到了 / 卖完了**（= 成交，会动钱包）｜ **手动撤销**（不动钱包）
- 默认值按变动种类定：消失的旧单 → 成交；数量变少的单 → 成交（部分成交）
- 点「应用变动」把每条的选定交回桥，由桥调
  ``asset_snapshot_service.adjust_wallet_balance`` 增减余额、落 ``order_events`` 台账

`OrderChangeBridge` 只做「列条目 + 收选择 + 算预计金额」，**不碰数据库也不碰钱包** ——
真正的落账在调用方（`QueryDashboardBridge.applyOrderChanges`），
这样在没有 GUI 的测试里也能直接构造本桥验分类与默认值。

口径（用户确认）：**不扣销售税 / 中介费** —— 成交金额就是 ``价格 × 剩余量``。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = ["OrderChangeBridge", "OrderChangeQmlDialog", "OUTCOME_CANCELLED", "OUTCOME_FILLED"]

_QML_FILE = "dialogs/OrderChangeDialog.qml"

#: 成交（卖单卖完了 / 买单买到了）—— 会增减钱包余额
OUTCOME_FILLED = "filled"
#: 用户自己在游戏里撤销了挂单 —— 不动钱包
OUTCOME_CANCELLED = "cancelled"

#: 三种选择的展示顺序与文案（QML 侧的组合框直接用这个顺序）
_CHOICES: tuple[tuple[str, str], ...] = (
    (OUTCOME_FILLED, "买到了 / 卖完了"),
    (OUTCOME_CANCELLED, "手动撤销"),
)
_DEFAULT_INDEX = {OUTCOME_FILLED: 0, OUTCOME_CANCELLED: 1}

#: 「变动」列的短文案
_KIND_TEXT = {"gone": "本次导出里没有了", "partial": "数量变少", "added": "本次新出现"}


class OrderChangeBridge(DialogBridge):
    """订单变动对话框的后端：条目模型 + 逐条选择 + 预计钱包变化。"""

    rowsChanged = Signal()

    def __init__(self, rows: list[dict], *, wallet: float = 0.0, ledger_only: bool = False) -> None:
        """Args:
        rows: 变动条目，每条 ``{order_id, name, is_buy, price, volume, delta, kind}``。
            ``kind`` = ``"gone"``（本次导出里没有了）/ ``"partial"``（数量变少）/ ``"added"``。
            ``volume`` 对 ``gone`` 是原剩余量、对 ``partial`` 是本次减少的数量。
        wallet: 当前钱包余额 —— 只用于显示「预计余额」，**不回写**。
        ledger_only: 只记台账、**不动钱包**。ESI 同步路径用：余额是 ESI 给的绝对值，
            再按成交加减一次会算两遍，所以那一路只把变动记进 `order_events`。
        """
        super().__init__()
        self.set_title("确认订单变动")
        self._wallet = float(wallet)
        self._ledger_only = bool(ledger_only)
        self._rows: list[dict] = [self._normalize(r) for r in rows]
        self._choices = [label for _value, label in _CHOICES]

    # ── QML 读 ────────────────────────────────────────────────

    @Property(list, notify=rowsChanged)
    def rows(self) -> list[dict]:
        """`[{orderId, name, is_buy, priceText, volumeText, kindText, outcomeIndex}]`。"""
        return [
            {
                "orderId": int(r["orderId"]),
                "name": r["name"],
                "is_buy": bool(r["is_buy"]),
                "priceText": f"{r['price']:,.2f}",
                "volumeText": f"{r['volume']:,}",
                "kindText": _KIND_TEXT.get(r["kind"], r["kind"]),
                "outcomeIndex": int(r["outcomeIndex"]),
            }
            for r in self._rows
        ]

    @Property(list, constant=True)
    def choices(self) -> list[str]:
        return list(self._choices)

    @Property(str, notify=rowsChanged)
    def summary(self) -> str:
        gone = sum(1 for r in self._rows if r["kind"] == "gone")
        partial = sum(1 for r in self._rows if r["kind"] == "partial")
        parts = [f"共 {len(self._rows)} 条变动"]
        if gone:
            parts.append(f"消失的 {gone} 条")
        if partial:
            parts.append(f"数量变少的 {partial} 条")
        if self._ledger_only:
            parts.append("按「买到了 / 卖完了」记入台账，按「手动撤销」跳过（余额由 ESI 直接给，不再加减）")
        else:
            parts.append("按「买到了 / 卖完了」计入钱包，按「手动撤销」跳过")
        return " · ".join(parts)

    @Property(str, notify=rowsChanged)
    def walletText(self) -> str:
        """`当前余额 → 应用后余额`（按当前选择实时算）。

        `ledger_only` 时不预测余额 —— 那条路径根本不动它，写个数字只会误导。
        """
        if self._ledger_only:
            return "余额由 ESI 直接给出，本次不加减"
        return f"钱包余额 {self._wallet:,.2f} → {self._wallet + self._delta():,.2f} ISK"

    @Property(str, notify=rowsChanged)
    def deltaText(self) -> str:
        """预计变动额（带正负号；为 0 时写「不变」）。`ledger_only` 时不预测。"""
        if self._ledger_only:
            return "仅记台账"
        delta = self._delta()
        if abs(delta) < 0.005:
            return "钱包不变"
        return f"预计 {delta:+,.2f} ISK"

    @Property(bool, notify=rowsChanged)
    def hasRows(self) -> bool:
        return bool(self._rows)

    # ── QML 写 ────────────────────────────────────────────────

    @Slot(int, int)
    def setOutcomeIndex(self, index: int, choice: int) -> None:
        """把第 `index` 条的处置改成下拉的第 `choice` 项。越界忽略（不抛）。"""
        if not 0 <= int(index) < len(self._rows):
            return
        if not 0 <= int(choice) < len(_CHOICES):
            return
        self._rows[int(index)]["outcomeIndex"] = int(choice)
        self.rowsChanged.emit()

    # ── 给 Python 调用方 ──────────────────────────────────────

    def outcomes(self) -> list[dict]:
        """`[{order_id, outcome, is_buy, price, volume, delta}]` —— 每条选定的结果。

        ``volume`` 对 ``partial`` 是**本次减少的数量**（不是剩余量），
        对 ``gone`` 则是原剩余量；``delta`` 按成交口径算（撤销恒为 0）。
        """
        return [self._outcome_of(row) for row in self._rows]

    def total_delta(self) -> float:
        """按当前选择应增减的钱包金额（成交项求和，撤销项不计）。"""
        return self._delta()

    def is_empty(self) -> bool:
        return not self._rows

    # ── 内部 ──────────────────────────────────────────────────

    @staticmethod
    def _normalize(row: dict) -> dict:
        is_buy = bool(row.get("is_buy"))
        volume = int(row.get("volume") or 0)
        delta = float(row.get("delta") or 0.0)
        if not delta:
            # 成交对钱包的影响：卖出 +金额、买入 −金额（**不扣税费**，用户确认口径）
            delta = volume * float(row.get("price") or 0.0) * (-1.0 if is_buy else 1.0)
        kind = str(row.get("kind") or "gone")
        return {
            "orderId": int(row.get("order_id") or 0),
            "name": str(row.get("name") or ""),
            "is_buy": is_buy,
            "price": float(row.get("price") or 0.0),
            "volume": volume,
            "delta": delta,
            "kind": kind,
            "outcomeIndex": _DEFAULT_INDEX[OUTCOME_FILLED],
            #: 部分成交：成交后挂单**剩余量**（`gone` 行没有 → 成交即删行）
            "newRemain": row.get("new_remain"),
        }

    def _delta(self) -> float:
        return round(sum(float(self._outcome_of(row)["delta"]) for row in self._rows), 2)

    @staticmethod
    def _outcome_of(row: dict) -> dict:
        outcome = _CHOICES[int(row.get("outcomeIndex") or 0)][0]
        delta = float(row["delta"]) if outcome == OUTCOME_FILLED else 0.0
        return {
            "order_id": int(row["orderId"]),
            "outcome": outcome,
            "is_buy": 1 if row["is_buy"] else 0,
            "price": float(row["price"]),
            "volume": int(row["volume"]),
            "delta": round(delta, 2),
            #: 部分成交后**还剩多少**（`gone` 行给 None → 调用方删行而不是回写）
            "new_remain": row.get("newRemain"),
        }


class OrderChangeQmlDialog(QmlDialog):
    """QML 版订单变动确认框。"""

    def __init__(self, bridge: OrderChangeBridge, parent: Any = None, size: tuple[int, int] = (720, 460)) -> None:
        super().__init__(_QML_FILE, bridge, parent=parent, size=size)
        self._change_bridge = bridge

    @staticmethod
    def confirm(
        parent: Any, rows: list[dict], *, wallet: float = 0.0, ledger_only: bool = False
    ) -> tuple[list[dict], bool]:
        """开一次对话框；返回 `(每条的选择结果, 是否点了「应用变动」)`。

        取消 / Esc → `(结果仍照默认算, False)`，调用方据此**什么都不做**。
        """
        bridge = OrderChangeBridge(rows, wallet=wallet, ledger_only=ledger_only)
        dlg = OrderChangeQmlDialog(bridge, parent=parent)
        ok = dlg.exec() == int(dlg.DialogCode.Accepted)  # type: ignore[attr-defined]
        return bridge.outcomes(), ok
