"""钱包交易记录的剪贴板解析 — 纯函数，无 DB / Qt 依赖。

游戏里「钱包 → 交易记录」Ctrl+A/C 复制出来的是 Tab 分隔文本，两种列型：

- **市场流水**（钱包页）：日期 / 类型 / 金额 / 余额 / 说明。第 4 列是**逐笔累计余额**，
  所以最新一笔的余额就是当前钱包余额 —— 挂单列表面板靠它免手打。
- **交易明细**（交易页）：日期 / 数量 / 物品名* / 单价 / 总额 / 卖家 / 地点 / 买家 / 账户。
  **金额为负 = 你付出 ISK（买入），为正 = 你收到 ISK（卖出）**（用户 2026-09-20 确认）。
  仓库/采购的入库只吃买入行，卖出行统计后跳过。
"""

from __future__ import annotations

import math
import re

#: 两种列型的首字段都是 `YYYY.MM.DD HH:MM`；认不出这一列的行（表头、空行）整行跳过
_TIME_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}$")
#: 金额/余额的货币后缀（客户端复制时带上）
_CURRENCY_RE = re.compile(r"(?i)(星币|isk)$")


def _money(text: str) -> float | None:
    """`-30,692 星币` → -30692.0；非法给 None（负数合法：流水里支出就是负的）。"""
    cleaned = _CURRENCY_RE.sub("", str(text or "").strip().replace(",", "").replace(" ", "").replace("_", ""))
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _count(text: str) -> int | None:
    """数量列 → int（去千分位）；非正整数给 None。"""
    cleaned = str(text or "").strip().replace(",", "").replace(" ", "")
    try:
        value = int(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def parse_wallet_journal(raw: str) -> list[dict]:
    """市场流水 → ``[{time, kind, amount, balance, note}]``（认不出的行丢弃）。"""
    rows: list[dict] = []
    for line in (raw or "").splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 4 or not _TIME_RE.match(parts[0]):
            continue
        amount = _money(parts[2])
        balance = _money(parts[3])
        if amount is None or balance is None:
            continue
        rows.append(
            {
                "time": parts[0],
                "kind": parts[1],
                "amount": amount,
                "balance": balance,
                "note": parts[4] if len(parts) > 4 else "",
            }
        )
    return rows


def latest_balance(rows: list[dict]) -> tuple[float, str] | None:
    """取最新一笔流水后的余额 → ``(余额, 时间)``；无有效行给 None。

    时间戳是零填充的 ``YYYY.MM.DD HH:MM``，字符串排序即时序排序。
    **同一分钟取靠前的那条**：客户端复制出来是「新 → 旧」，同一分钟里更晚发生的排在更前面
    （例：卖出 909,400 后紧跟扣税，两条同分钟，税那条才是最终余额）。
    """
    if not rows:
        return None
    newest_time = max(str(row.get("time", "")) for row in rows)
    for row in rows:
        if str(row.get("time", "")) == newest_time:
            return float(row["balance"]), newest_time
    return None


def parse_purchase_records(raw: str) -> tuple[list[dict], dict]:
    """交易明细 → 买入行 + 统计。

    Returns:
        ``(rows, stats)``：rows 为**买入行**（``总额 < 0``）``[{time, raw_name, qty,
        unit_price, seller}]``，物品名已去尾部 ``*``；stats 为
        ``{"sales": 正数行（卖出）数, "unparsed": 认不出的非空行数}``。
    """
    rows: list[dict] = []
    sales = 0
    unparsed = 0
    for line in (raw or "").splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("\t")]
        qty = _count(parts[1]) if len(parts) > 1 else None
        unit_price = _money(parts[3]) if len(parts) > 3 else None
        total = _money(parts[4]) if len(parts) > 4 else None
        if len(parts) < 5 or not _TIME_RE.match(parts[0]) or not parts[2] or qty is None or total is None:
            unparsed += 1
            continue
        if total >= 0:
            sales += 1
            continue
        rows.append(
            {
                "time": parts[0],
                "raw_name": parts[2].rstrip("*").strip(),
                "qty": qty,
                "unit_price": float(unit_price) if unit_price is not None else abs(total) / qty,
                "seller": parts[5] if len(parts) > 5 else "",
            }
        )
    return rows, {"sales": sales, "unparsed": unparsed}
