"""物品查询页 · 有结果态详情的数据整形（**纯函数，零 Qt/DB/缓存**）。

第 2 步（详情桥）的几何与文案算法全在这里，`ui_qml/bridge/query_detail_bridge.py`
只负责取数（DB / ESI / worker）并把结果喂进来。QML 侧只画，不做取最值/取整。
这条分工与 `ui_qml/bridge/price_chart_bridge.py` 的 `nice_range` / `plot_model`
是同一条既有约定（QML 不做几何计算）。

各函数对应结果区的一块面板：
  - `hub_bar_rows`     —— 5 个默认贸易中心的价格（每中心两行 + 一条横向柱形条 + 帝国圆点）
  - `material_rows`    —— 制造该物品所需的材料（买/卖双价）
  - `refine_rows`      —— 精炼该物品的产物
  - `refine_total_rows`—— 精炼的「产出 / 利润」总计行
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["hub_bar_rows", "material_rows", "refine_rows", "refine_total_rows"]

#: 无数据时显示的占位符（与查询页其余表格同口径）
_MISSING = "—"

# ── 贸易中心 → 所在帝国 ────────────────────────────────────────────
# 硬编码：帝国名不在 SDE item 表里，且本模块必须是纯函数（无 DB 查询）。
# 帝国标识用英文（与主题 token 表对齐），对外展示用中文名（见 _EMPIRE_ZH）。
# Jita 属加达里（The Forge）、Amarr 属艾玛（Domain）、Dodixie 属盖伦特（Sinq Laison）、
# Rens（Heimatar）与 Hek（Metropolis）同属米玛塔尔。
_HUB_EMPIRE: dict[str, str] = {
    "Jita": "Caldari",
    "Amarr": "Amarr",
    "Dodixie": "Gallente",
    "Rens": "Minmatar",
    "Hek": "Minmatar",
}

#: 帝国标识 → 中文展示名（CCP 官方译名）。
_EMPIRE_ZH: dict[str, str] = {
    "Amarr": "艾玛",
    "Caldari": "加达里",
    "Gallente": "盖伦特",
    "Minmatar": "米玛塔尔",
}

#: 帝国 → 主题 token **名**（不是色值；由桥 `getattr(theme, token)` + `ensure_contrast` 解析）。
_EMPIRE_TOKEN: dict[str, str] = {
    "Amarr": "ACCENT_YELLOW",
    "Caldari": "ACCENT_CYAN",
    "Gallente": "ACCENT_GREEN",
    "Minmatar": "ACCENT_RED",
}


def _num(value: Any) -> float:
    """宽松转 float：None / 非数值一律当 0.0（价格缺列时不上抛）。"""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _money(value: float) -> str:
    """千分位两位小数；无值（0/缺失）显式给 `—`，避免出现 `0.00` 的假价格。"""
    if not value:
        return _MISSING
    return f"{value:,.2f}"


def _best_index(values: Sequence[float], *, highest: bool) -> int:
    """在**正**值里取最高/最低的下标；并列取第一个，全无正值返回 -1。

    只认正值是关键：0/缺失代表「该中心没这个价」，不该被当成「最低卖价 0」，
    否则一个没数据的中心会被标成「对买家最划算」。
    """
    eligible = [v for v in values if v > 0]
    if not eligible:
        return -1
    target = max(eligible) if highest else min(eligible)
    for i, v in enumerate(values):
        if v > 0 and v == target:
            return i
    return -1


def hub_bar_rows(snapshots: Mapping[str, Mapping[str, Any]], hubs: Sequence[str]) -> list[dict]:
    """5 个贸易中心的价格快照 → 柱形条行（**按 `hubs` 顺序**）。

    入参 `snapshots` 形如
    `{hub_name: {"buy": float, "sell": float, "buy_volume": int, "sell_volume": int}}`
    （由 `market_repo.get_batch_market_snapshot` 每个 hub 各查一次拼出）。

    每项返回：
      `{"hub", "empire", "empireColor", "buy", "sell", "buyText", "sellText",
        "buyPos", "sellPos", "buyVal", "sellVal", "bestBuy", "bestSell"}`

    - `empire` / `empireColor`：该中心所在帝国的**中文名**与**主题 token 名**
      （不是色值 —— 由桥解析成实际颜色）。未知中心两者均为空串。
    - `buyText` / `sellText`：千分位两位小数，无值（None/0）→ `—`。
    - `buyPos` / `sellPos` ∈ 0..1 = 该值 ÷ **5 个中心里的最大值**（买、卖**各自**归一化）。
      最大值 ≤ 0 时一律 0.0 —— 柱长按 5 个中心一起归一化是硬要求，不能各自满格。
    - `buyVal` / `sellVal`：原始数值（缺失为 0.0），供 QML 按数值决定深浅/提示。
    - `bestBuy` = 买价是 5 者中最高；`bestSell` = 卖价最低（对买家最划算）。并列只标第一个。
      全无正值时整列都不标（没有「最划算」可言）。
    """
    rows: list[dict] = []
    buys: list[float] = []
    sells: list[float] = []

    for hub in hubs:
        snap = snapshots.get(hub) or {}
        buy = _num(snap.get("buy"))
        sell = _num(snap.get("sell"))
        buys.append(buy)
        sells.append(sell)
        empire = _HUB_EMPIRE.get(hub, "")
        rows.append(
            {
                "hub": str(hub),
                "empire": _EMPIRE_ZH.get(empire, empire),
                "empireColor": _EMPIRE_TOKEN.get(empire, ""),
                "buy": buy,
                "sell": sell,
                "buyText": _money(buy),
                "sellText": _money(sell),
                "buyVal": buy,
                "sellVal": sell,
            }
        )

    max_buy = max(buys) if buys else 0.0
    max_sell = max(sells) if sells else 0.0
    best_buy = _best_index(buys, highest=True)
    best_sell = _best_index(sells, highest=False)

    for i, row in enumerate(rows):
        buy = row["buy"]
        sell = row["sell"]
        row["buyPos"] = (buy / max_buy) if max_buy > 0 else 0.0
        row["sellPos"] = (sell / max_sell) if max_sell > 0 else 0.0
        row["bestBuy"] = i == best_buy
        row["bestSell"] = i == best_sell

    return rows


def material_rows(
    sell_materials: Sequence[Mapping[str, Any]],
    buy_materials: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict]:
    """制造材料（**买/卖双向各展开一次**）→ 材料行。

    两次都来自 `services.bom_expander.get_flat_materials`（`price_type="sell"` 与
    `"buy"`），形状 `[{type_id, name, total_qty, unit_price, subtotal}]`。
    以 `price_type="sell"` 那份为准（顺序/名称/数量），买价按 `type_id` 去另一份里配。

    输出 `[{"name", "qtyText", "buyText", "sellText", "totalBuyText", "totalSellText"}]`：
    数量整数量千分位，四类单价/总价千分位两位小数。空输入返回空列表。
    """
    buy_by_id: dict[Any, Mapping[str, Any]] = {}
    for mat in buy_materials or []:
        buy_by_id[mat.get("type_id")] = mat

    rows: list[dict] = []
    for mat in sell_materials or []:
        buy = buy_by_id.get(mat.get("type_id"), {})
        rows.append(
            {
                "name": str(mat.get("name") or ""),
                "qtyText": f"{_num(mat.get('total_qty')):,.0f}",
                "buyText": f"{_num(buy.get('unit_price')):,.2f}",
                "sellText": f"{_num(mat.get('unit_price')):,.2f}",
                "totalBuyText": f"{_num(buy.get('subtotal')):,.2f}",
                "totalSellText": f"{_num(mat.get('subtotal')):,.2f}",
            }
        )
    return rows


def refine_rows(result: Mapping[str, Any]) -> list[dict]:
    """`RefineWorker.result_signal` 的载荷 → **每个产出材料一行**的扁平列表。

    入参 `{"items": [{"input_name", "input_qty", "yield_rate", "output",
    "input_value", "output_value", "profit", "margin_pct"}], ...}`。

    ⚠️ **`output` 的实际形状是 list，不是 dict**（与原设计稿的 `{材料名: 数量}`
    假设不同，以 `services/refining_service.py:72-89` 的实现为准）：
    `[{"type_id", "name", "qty", "price", "total"}]` —— 每个精炼产出材料一个 dict。
    本函数按这个真实形状遍历。

    每行返回：
      `{"name", "qtyText", "sourceName", "yieldText", "valueText",
        "profitText", "profitPos"}`

    - `name` / `qtyText` / `valueText`：该产出材料的名、量、价值（`output[].total`）。
    - `sourceName` / `yieldText`：来源投入材料的名字与产率（百分比，一位小数）。
    - `profitText` / `profitPos`：**投入项级**的精炼利润（`refining_service` 只在
      item 级算 profit，不按产出拆分），千分位两位小数带正负号；
      `profitPos` 为利润是否非负（供 QML 选红/绿）。同一投入项的多个产出行
      会共享同一个利润值 —— 这是平坦 schema 的已知取舍，汇总读 `refine_total_rows`。
    """
    rows: list[dict] = []
    for item in (result or {}).get("items") or []:
        source = str(item.get("input_name") or "")
        yield_text = f"{_num(item.get('yield_rate')) * 100:.1f}%"
        profit = _num(item.get("profit"))
        profit_text = f"{profit:+,.2f}"
        profit_pos = profit >= 0
        for out in item.get("output") or []:
            rows.append(
                {
                    "name": str(out.get("name") or ""),
                    "qtyText": f"{_num(out.get('qty')):,.2f}",
                    "sourceName": source,
                    "yieldText": yield_text,
                    "valueText": f"{_num(out.get('total')):,.2f}",
                    "profitText": profit_text,
                    "profitPos": profit_pos,
                }
            )
    return rows


def refine_total_rows(result: Mapping[str, Any]) -> list[dict]:
    """精炼总计 → `[{"label", "valueText", "token"}]`（两行：产出 / 利润）。

    `token` 是主题 token **名**（空串 = 用默认前景色），由桥解析成实际色值；
    利润行按正负取 `ACCENT_GREEN` / `ACCENT_RED`。无有效结果时返回空列表。
    """
    if not result or not (result.get("items") or []):
        return []
    output_value = _num(result.get("total_output_value"))
    profit = _num(result.get("total_profit"))
    return [
        {"label": "产出", "valueText": f"{output_value:,.2f}", "token": ""},
        {"label": "利润", "valueText": f"{profit:+,.2f}", "token": "ACCENT_GREEN" if profit >= 0 else "ACCENT_RED"},
    ]
