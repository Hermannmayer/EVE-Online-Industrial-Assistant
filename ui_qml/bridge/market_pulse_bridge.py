"""市场大盘 bridge —— QML 与「指数 / 异动 / BOM 传导链」三个服务之间的唯一通道。

页面规格来自 `docs/dev/market-monitor-plan.md` §4.1（大盘 Tab）：
指数卡 ×5 → 主图（五条基期=100 的指数折线 + 7 日均线开关）→ 量价/广度 →
篮子成员表 → 异动榜两区（合格成分 / 全市场）→ 数据状态行；点异动行在右侧抽屉看
`get_transmission_chain` 的逐级传导表。

**本页只读本地 `market.db`，不发起任何 ESI 请求** —— 唯一的例外是顶部「刷新指数」，
它走 `IndexRefreshWorker`（QThread）重算 `market_index_daily` 物化表。

## 后端契约怎么接

`services.market_index_service` / `market_movers_service` / `market_chain_service`
全部**惰性 import**，且集中在本模块的三个取值函数里：

  * 惰性：模块级 import 会把 services 整条业务链拖进外壳启动路径
    （与 `ui_qml/registry.py` 的懒导入同一理由）；
  * 集中成 `_index_service()` / `_movers_service()` / `_chain_service()`：
    测试 monkeypatch 这三个函数就换掉了整个后端，**不必等那几个服务落地**
    （本页与它们在并行开发）。

## 标尺口径（格式化一律在桥里做，QML 只画不判断）

  * `chg*` 一律按**百分点**给（服务返回 1.25 = +1.25%）；
  * `weight` / `cost_share` 一律按 **0–1 份额**给（0.25 = 25%，指数的单成分上限就是 25%）；
  * 缺值一律 `—`，**绝不用 0 冒充**「没数据」；
  * 颜色只给 token 名（`ACCENT_GREEN` / `ACCENT_RED` / `TEXT_SECONDARY`），
    QML 侧翻成 `Theme.*`（本仓惯例，见 `qml/dialogs/ImportReviewDialog.qml` 的 `tokenColor`）。
    这样切主题不必让桥重算，也不会被「hex 字面量」的铁律绊住。

**涨跌配色照本仓既有口径**（`trade_rank_model` / `query_detail_model`）：涨=绿、跌=红。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, QThread, Signal, Slot

from core.constants import TRADE_HUB_IDS
from core.logger import log

__all__ = ["IndexRefreshWorker", "MarketPulseBridge"]

#: 缺值占位符（与全仓一致：不用 0 冒充「没数据」）
_DASH = "—"

#: 异动榜「薄市场」阈值：近 N 日**日均成交量**低于它就标「薄」。
#: 单笔成交就能推出来的百分比基本都出自这些行（实测 `共和舰队热能涂层` 3 天 +161843%，
#: 窗口里只有 1 笔成交）—— 指数侧有 ±20% 日收益截断，异动榜没有，所以这个标记必须有。
_THIN_VOLUME = 10
#: 异动榜涨幅的**显示**上限（百分点）：绝对值超过它就夹成这两个文案。
#: **只夹显示文本**，真值仍留在 `chg` 字段里（排序与后续判据都用真值）。
_CHG_OVER_TEXT = ">+9999%"
_CHG_UNDER_TEXT = "<-9999%"
_CHG_DISPLAY_CAP = 9999.0

#: 五个指数的折线颜色（token 名，QML 侧翻成 `Theme.*`）。按后端返回顺序取，多余的回环。
_SERIES_TOKENS = (
    "PRIMARY",
    "ACCENT_CYAN",
    "ACCENT_PURPLE",
    "ACCENT_YELLOW",
    "ACCENT_ORANGE",
    "ACCENT_GREEN",
)

#: 后端 `source` 字段（机器名）→ 人读的口径标签。
#: 计划 §4.1 要求传导链/成员表带「口径标签」：指数与异动榜只用成交均价，
#: 缺历史时才退回挂单卖价，这几十个像素的文字是用户判断数字可信度的依据。
_SOURCE_LABELS = {
    "history": "成交均价",
    "snapshot": "挂单卖价",
    "fixed": "固定篮子",
    "tier": "用途层级",
    "liquidity": "流动性 top-N",
}

#: 异动榜的观察窗口（天）与后端取数上限。
_MOVER_DAYS = 3
_MOVER_LIMIT = 50
#: 异动榜**每区**最多画多少行。后端给 50 条，全画进 Repeater 会让整页光建项就上千个；
#: 页面本身没有内层滚动，靠外层 Flickable，故这里就截断（并如实写出「显示前 N 条」）。
_MOVER_DISPLAY_CAP = 20
#: 篮子成员表最多画多少行（CPI 代理有 300 个成分，全画会拖垮页面）。
_MEMBER_CAP = 20
#: 传导链下钻层级（`get_transmission_chain` 的 depth）
_CHAIN_DEPTH = 2

#: 成交额序列的回看窗口（算「量价背离」用）
_TURNOVER_DAYS = 30
#: 各中心快照天数低于它就标「样本太短」（计划 §6：除 Jita 外只有 5–9 天）
_HUB_MIN_DAYS = 20
#: 量价背离判据：指数涨超这个百分点、且成交额环比跌超下面的百分点 → 虚涨提示
_DIVERGENCE_CHG_PCT = 0.5
_DIVERGENCE_TURNOVER_PCT = -5.0


# ═══════════════════════════════════════════════════════════
#  后端取值函数（测试 monkeypatch 这三个就换掉整个后端）
# ═══════════════════════════════════════════════════════════


def _index_service() -> Any:
    """惰性取 `services.market_index_service`（测试里换成替身模块/命名空间）。"""
    from services import market_index_service

    return market_index_service


def _movers_service() -> Any:
    """惰性取 `services.market_movers_service`。"""
    from services import market_movers_service

    return market_movers_service


def _chain_service() -> Any:
    """惰性取 `services.market_chain_service`。"""
    from services import market_chain_service

    return market_chain_service


# ═══════════════════════════════════════════════════════════
#  就地查询（后端暂时没有的接口，见各自 docstring）
# ═══════════════════════════════════════════════════════════


def _has_table(conn: Any, name: str) -> bool:
    """只读路径先探表存不存在 —— 同 `services.price_history.get_history_summary` 的口径。

    页面的读路径**不做 DDL**：本地从没点过「更新价格」就是没有数据，不该顺手建表。
    """
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _hub_snapshot_rows() -> list[dict]:
    """各贸易中心「快照天数 / 最后日期」—— 就地一次 SQL，**临时**。

    ⚠️ 为什么要在这里查：计划 §4.1 要求页面底部把「各中心快照天数与最后日期」写出来
    （只有 Jita 够长，其余 5–9 天必须让用户看见），而三个后端服务都不提供这个
    「数据状态」接口。等 `market_index_service`（或市场浏览服务）给出统一入口后，
    本函数应删掉。

    表不存在（从没更新过价格）返回空列表，由页面显示「先去更新价格」。
    """
    try:
        from services.database_manager import get_db

        with get_db().connect("mkt") as conn:
            if not _has_table(conn, "market_volume_snapshots"):
                return []
            rows = conn.execute(
                "SELECT region_id, COUNT(DISTINCT date) AS days, MAX(date) AS last_date "
                "FROM market_volume_snapshots GROUP BY region_id"
            ).fetchall()
    except Exception:
        # 吞的是 sqlite3.Error（表缺失/被写锁住）与 market.db 打不开 —— 状态行是附属信息，
        # 读不到就退化成一屏空状态，不该让整个大盘页打不开。
        log.exception("读取各中心快照天数失败")
        return []

    by_region = {int(r["region_id"]): (int(r["days"] or 0), str(r["last_date"] or "")) for r in rows}
    out: list[dict] = []
    for hub, region_id in TRADE_HUB_IDS.items():
        days, last = by_region.get(int(region_id), (0, ""))
        out.append({"hub": hub, "days": days, "last": last, "short": days < _HUB_MIN_DAYS})
    return out


def _turnover_series(region_id: int, days: int = _TURNOVER_DAYS) -> list[dict]:
    """近 `days` 天的**日成交额**（Σ 成交均价 × 成交量）—— 就地一次 SQL，**临时**。

    ⚠️ 为什么要自己算：计划 §4.1 的「量价背离提示」要比**今天和之前的成交额**，
    而后端契约 `get_breadth()` 只给当日一个 `turnover`，没有历史。
    `price_history.average × volume` 就是成交额（计划 §0 用「成交额」替代 CCP 的货币流速），
    一次按日聚合即可。等后端补出成交额序列后应删掉本函数（与 `_hub_snapshot_rows` 同一处境）。

    返回按日期升序的 `[{date, isk}]`；表不存在返回空列表。
    """
    try:
        from services.database_manager import get_db

        with get_db().connect("mkt") as conn:
            if not _has_table(conn, "price_history"):
                return []
            rows = conn.execute(
                "SELECT date, SUM(average * volume) AS isk FROM price_history "
                "WHERE region_id = ? AND date >= date((SELECT MAX(date) FROM price_history WHERE region_id = ?), ?) "
                "GROUP BY date ORDER BY date ASC",
                (region_id, region_id, f"-{max(1, int(days))} days"),
            ).fetchall()
    except Exception:
        # 同上：读不到就不给「量价背离」提示，页面其余部分照常。
        log.exception("读取日成交额序列失败")
        return []

    return [{"date": str(r["date"]), "isk": float(r["isk"] or 0.0)} for r in rows]


# ═══════════════════════════════════════════════════════════
#  纯格式化（桥层用例直接断言这些）
# ═══════════════════════════════════════════════════════════


def _as_float(value: Any) -> float | None:
    """转 float；`None`/空串/非数值一律 `None`（调用方据此显示 `—`）。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> str:
    """两位小数（价格/指数现值）。"""
    number = _as_float(value)
    return _DASH if number is None else f"{number:,.2f}"


def _int_text(value: Any) -> str:
    """整数千分位（成交量/家数/天数）。"""
    number = _as_float(value)
    return _DASH if number is None else f"{int(number):,}"


def _qty_text(value: Any) -> str:
    """用量：整数就不带小数点，否则两位（反应配方里有小数用量）。"""
    number = _as_float(value)
    if number is None:
        return _DASH
    return f"{int(number):,}" if number == int(number) else f"{number:,.2f}"


def _pct(value: Any) -> str:
    """百分点 → 带符号百分比（`chg*` 口径）。"""
    number = _as_float(value)
    return _DASH if number is None else f"{number:+.2f}%"


def _share(value: Any) -> str:
    """0–1 份额 → 百分比（`weight` / `cost_share` 口径）。"""
    number = _as_float(value)
    return _DASH if number is None else f"{number * 100:.2f}%"


def _ratio(value: Any) -> str:
    """量比（倍数）。"""
    number = _as_float(value)
    return _DASH if number is None else f"{number:.1f}×"


def _source_text(value: Any) -> str:
    """口径机器名 → 人读标签（未知值原样回显，缺值 `—`）。"""
    raw = str(value or "")
    return _SOURCE_LABELS.get(raw, raw) or _DASH


def _chg_token(value: Any) -> str:
    """涨跌 → token 名。涨绿跌红、零与缺值用次要色（0 不该看着像上涨）。"""
    number = _as_float(value)
    if number is None or number == 0:
        return "TEXT_SECONDARY"
    return "ACCENT_GREEN" if number > 0 else "ACCENT_RED"


def _short_date(value: str) -> str:
    """`2026-10-05` → `10-05`（横轴标签，一年内的图不需要年份）。"""
    return value[5:] if len(value) >= 10 and value[4] == "-" else value


def _ma7(points: list[dict]) -> list[dict]:
    """7 日移动平均（**尾部窗口**：第 i 点取 i-6..i 的均值，开头够不到 7 天就有几天算几天）。

    放在桥里而不是 QML 里：这是「后端给原始值、桥给可直接画的序列」分工的一部分
    （FLineChart 只画曲线与轴，不做统计；见组件头部说明）。
    """
    values = [float(p.get("y") or 0.0) for p in points]
    out: list[dict] = []
    for index, point in enumerate(points):
        window = values[max(0, index - 6) : index + 1]
        out.append({"x": int(point.get("x") or index), "y": sum(window) / len(window)})
    return out


# ── 各段数据的「视图」装配 ──────────────────────────────────


def _card_view(raw: dict) -> dict:
    """指数卡：现值 + 今日/7/30/90/180 涨跌（缺值 `—`）。"""
    changes = (
        ("今日", raw.get("chg1")),
        ("7日", raw.get("chg7")),
        ("30日", raw.get("chg30")),
        ("90日", raw.get("chg90")),
        ("180日", raw.get("chg180")),
    )
    return {
        "key": str(raw.get("key") or ""),
        "label": str(raw.get("label") or raw.get("key") or ""),
        "valueText": _num(raw.get("value")),
        "chg1": _as_float(raw.get("chg1")),  # 量价背离要用原始值，不解析文案
        "days": int(_as_float(raw.get("days")) or 0),
        "baseDate": str(raw.get("base_date") or _DASH),
        "selected": False,
        "chgs": [{"label": label, "text": _pct(value), "token": _chg_token(value)} for label, value in changes],
    }


def _series_views(raw_series: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """`get_index_series` → `(原线, 7 日均线, 横轴日期标签)`。

    每条线给 `{key, label, token, points:[{x,y}]}` —— `x` 是**序号**、`y` 是真实值：
    FLineChart 的轴与窗口数学在组件里做（`normalize: true` 时按首点归一到 100），
    桥只把原始值按日期排好序。
    """
    lines: list[dict] = []
    smooth: list[dict] = []
    x_labels: list[str] = []
    longest = 0
    for index, item in enumerate(raw_series or []):
        points = sorted(
            (p for p in (item.get("points") or []) if _as_float(p.get("value")) is not None),
            key=lambda p: str(p.get("date") or ""),
        )
        key = str(item.get("key") or "")
        label = str(item.get("label") or key)
        token = _SERIES_TOKENS[index % len(_SERIES_TOKENS)]
        base = [{"x": i, "y": float(_as_float(p.get("value")) or 0.0)} for i, p in enumerate(points)]
        lines.append({"key": key, "label": label, "token": token, "points": base})
        smooth.append({"key": key, "label": f"{label} 7日均线", "token": token, "points": _ma7(base)})
        # 横轴标签取**最长**那条线的日期（五条线同源，长短不一说明某条缺历史）
        if len(points) > longest:
            longest = len(points)
            x_labels = [_short_date(str(p.get("date") or "")) for p in points]
    return lines, smooth, x_labels


def _members_by_key(raw_series: list[dict]) -> dict[str, list[dict]]:
    """`get_index_series` → `{指数 key: members}`（点卡切篮子时按 key 取）。"""
    out: dict[str, list[dict]] = {}
    for item in raw_series or []:
        key = str(item.get("key") or "")
        if key:
            out[key] = list(item.get("members") or [])
    return out


def _member_view(raw: dict) -> dict:
    """篮子成员行：权重、现价、30 日涨跌、是否触顶（`capped`）、口径。

    `price` 是后端在**锚定指数日（含）之前最近一次成交均价**（当日没成交就往前找，
    完全没有观测给 `None`）—— 与指数、异动榜同一口径，不用挂单价。
    """
    return {
        "typeId": int(_as_float(raw.get("typeId")) or 0),
        "name": str(raw.get("name") or raw.get("typeId") or ""),
        "weightText": _share(raw.get("weight")),
        "priceText": _num(raw.get("price")),
        "chg30Text": _pct(raw.get("chg30")),
        "chg30Token": _chg_token(raw.get("chg30")),
        "capped": bool(raw.get("capped")),
        "sourceText": _source_text(raw.get("source")),
    }


def _chg_display_text(value: Any) -> str:
    """异动榜涨幅文案：绝对值超过显示上限就夹住。

    `+161843%` 这种数字在界面上看着像 bug 而不是行情（实测来自**一笔**成交），
    所以只夹**显示文本**；真值仍由 `_mover_view` 的 `chg` 字段带出去。
    """
    number = _as_float(value)
    if number is None:
        return _DASH
    if number > _CHG_DISPLAY_CAP:
        return _CHG_OVER_TEXT
    if number < -_CHG_DISPLAY_CAP:
        return _CHG_UNDER_TEXT
    return _pct(number)


def _mover_view(raw: dict, labels: dict[str, str]) -> dict:
    """异动行：现价、涨跌、成交量、量比、命中哪些指数（key 翻成人读的 label）。

    `thin` = 近 N 日日均成交量低于 `_THIN_VOLUME`（**薄市场**）—— 界面给这行打「薄」标记：
    这种行的百分比往往只是一笔成交推出来的，`qualified` 那区才过流动性门槛。
    成交量查不到（`None`）时不打标记：「不知道」不等于「薄」。
    """
    keys = raw.get("index_keys") or []
    names = [labels.get(str(k), str(k)) for k in keys]
    volume = _as_float(raw.get("volume"))
    return {
        "typeId": int(_as_float(raw.get("typeId")) or 0),
        "name": str(raw.get("name") or raw.get("typeId") or ""),
        "priceText": _num(raw.get("price")),
        "chg": _as_float(raw.get("chg")),  # 真值（显示文本可能被夹过）
        "chgText": _chg_display_text(raw.get("chg")),
        "chgToken": _chg_token(raw.get("chg")),
        "volumeText": _int_text(raw.get("volume")),
        "ratioText": _ratio(raw.get("volume_ratio")),
        "thin": volume is not None and volume < _THIN_VOLUME,
        "qualified": bool(raw.get("qualified")),
        "indexText": "、".join(names) if names else _DASH,
    }


def _chain_view(raw: dict) -> dict:
    """传导链行：层级（QML 按它缩进）、用量、成本占比、30/90/180 涨跌、未跟涨、口径。"""
    return {
        "level": int(_as_float(raw.get("level")) or 0),
        "typeId": int(_as_float(raw.get("typeId")) or 0),
        "parentTypeId": int(_as_float(raw.get("parent_type_id")) or 0),
        "name": str(raw.get("name") or raw.get("typeId") or ""),
        "qtyText": _qty_text(raw.get("qty")),
        "priceText": _num(raw.get("price")),
        "costShareText": _share(raw.get("cost_share")),
        "chg30Text": _pct(raw.get("chg30")),
        "chg30Token": _chg_token(raw.get("chg30")),
        "chg90Text": _pct(raw.get("chg90")),
        "chg90Token": _chg_token(raw.get("chg90")),
        "chg180Text": _pct(raw.get("chg180")),
        "chg180Token": _chg_token(raw.get("chg180")),
        # `not_caught_up` 算不出来时后端给 `None`（不是 False）—— 只有**确实**没跟涨才高亮，
        # 「不知道」不该看着像「安全」。
        "notCaughtUp": raw.get("not_caught_up") is True,
        "sourceText": _source_text(raw.get("source")),
    }


def _status_view(raw: dict) -> dict:
    """数据状态行：`Jita：29 天 · 最后 2026-10-05`（样本太短的标黄）。"""
    days = int(_as_float(raw.get("days")) or 0)
    last = str(raw.get("last") or _DASH)
    hub = str(raw.get("hub") or "")
    suffix = "" if days else "（还没有快照）"
    return {
        "hub": hub,
        "days": days,
        "text": f"{hub}：{days} 天 · 最后 {last}{suffix}",
        "token": "ACCENT_YELLOW" if raw.get("short") else "TEXT_SECONDARY",
    }


def _status_hint(rows: list[dict], region_id: int) -> str:
    """状态条的说明文案 —— 计划 §6 要求把「其余中心天数不足」明确写出来。"""
    if not rows:
        return "本地还没有各中心快照 —— 先在顶栏点「更新价格」"
    short = [r for r in rows if r.get("short")]
    if not short:
        return ""
    listed = "、".join(f"{r['hub']} {r['days']} 天" for r in short)
    jita_days = next((r["days"] for r in rows if int(TRADE_HUB_IDS.get(str(r["hub"]), 0)) == region_id), 0)
    return f"指数只用 Jita（{jita_days} 天历史）；以下中心快照太短，不参与计算：{listed}"


def _turnover_text(series: list[dict], breadth: dict) -> str:
    """成交额文案：优先用本地算的日序列（只有它带环比），没有就退回 `get_breadth` 的当日值。"""
    if series:
        last = _as_float(series[-1].get("isk"))
        if last is not None:
            text = f"成交额 {last:,.0f} ISK（{series[-1].get('date') or _DASH}）"
            previous = _as_float(series[-2].get("isk")) if len(series) >= 2 else None
            if previous:
                text += f" 环比 {(last - previous) / previous * 100:+.1f}%"
            return text
    value = _as_float(breadth.get("turnover"))
    if value is None:
        return "成交额 —"
    return f"成交额 {value:,.0f} ISK（{breadth.get('date') or _DASH}）"


def _adv_decl_text(breadth: dict) -> str:
    """涨跌家数文案。"""
    if _as_float(breadth.get("advancers")) is None and _as_float(breadth.get("decliners")) is None:
        return "涨跌家数 —"
    return f"涨 {_int_text(breadth.get('advancers'))} / 跌 {_int_text(breadth.get('decliners'))} / 平 {_int_text(breadth.get('unchanged'))}"


def _divergence(chg_pct: float | None, series: list[dict]) -> tuple[str, str]:
    """量价背离判据 → `(文案, token)`。

    计划 §4.1：「价涨量跌＝虚涨」。这里取**指数涨超 +0.5% 而成交额环比跌超 5%** ——
    成交额下来了说明推动价格的不是真实成交（挂单/个别玩家），指数涨得不牢。
    判据的两个阈值是命名常量，改口径只改常量。
    """
    if chg_pct is None or len(series) < 2:
        return "", ""
    last = _as_float(series[-1].get("isk"))
    previous = _as_float(series[-2].get("isk"))
    if not last or not previous:
        return "", ""
    ratio = (last - previous) / previous * 100.0
    if chg_pct > _DIVERGENCE_CHG_PCT and ratio < _DIVERGENCE_TURNOVER_PCT:
        return (
            f"⚠ 量价背离：指数 {chg_pct:+.2f}% 而成交额环比 {ratio:+.1f}% —— 可能是虚涨（挂单推动，成交没跟上）",
            "ACCENT_YELLOW",
        )
    return "", ""


# ═══════════════════════════════════════════════════════════
#  后台线程
# ═══════════════════════════════════════════════════════════


class IndexRefreshWorker(QThread):
    """「刷新指数」后台线程 —— 重算 `market_index_daily` 物化表。

    为什么必须开线程：`refresh_index_daily` 要按日聚合 `price_history` 几十万行再写物化表
    （计划 §3 实测一次聚合约 30 万行），同步跑会把界面冻住整秒级。写法照
    `ui_qml/workers/trade_workers.py` 的 `CrossRegionRankWorker`：结果走信号回主线程，
    异常收敛成 `failed_signal` —— 让它逃逸到 `sys.excepthook` 会被报成「程序遇到意外错误」
    并让按钮永久卡在「重算中」（贸易页踩过这个坑）。
    """

    finished_signal = Signal(int)  # 写入的日指数行数
    failed_signal = Signal(str)

    def __init__(self, region_id: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._region_id = int(region_id)

    def run(self) -> None:
        try:
            written = _index_service().refresh_index_daily(self._region_id)
            self.finished_signal.emit(int(written or 0))
        except Exception as ex:
            log.exception("重算市场指数失败")
            self.failed_signal.emit(str(ex))


# ═══════════════════════════════════════════════════════════
#  桥
# ═══════════════════════════════════════════════════════════


class MarketPulseBridge(QObject):
    """市场大盘页的 QML 后端。

    三个信号按「哪一块变了」分开，QML 的绑定只重算受影响的部分：

      * `dataChanged`       卡片 / 主图 / 广度 / 成员表 / 异动榜 / 数据状态行；
      * `refreshStateChanged`  `busy` + `statusText`（重算指数的进度与结果）；
      * `detailChanged`      右侧抽屉（传导链）。
    """

    dataChanged = Signal()
    refreshStateChanged = Signal()
    detailChanged = Signal()

    def __init__(self, shell: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell

        self._cards: list[dict] = []
        self._series: list[dict] = []
        self._ma7: list[dict] = []
        self._x_labels: list[str] = []
        self._members_by_key: dict[str, list[dict]] = {}
        self._selected_key = ""
        self._show_ma7 = False
        self._breadth: dict = {}
        self._turnover: list[dict] = []
        self._members: list[dict] = []
        self._members_note = ""
        self._qualified: list[dict] = []
        self._market: list[dict] = []
        self._movers_note = ""
        self._status_rows: list[dict] = []
        self._status_hint = ""

        #: 量价/广度那三行（`refresh` 之前 QML 就会绑定它们，必须先有初值 ——
        #: 绑定里读不存在的属性是**静默失败**，只会让那一格空着）
        self._turnover_text = "成交额 —"
        self._adv_decl_text = "涨跌家数 —"
        self._divergence_text = ""
        self._divergence_token = ""

        self._status_text = "正在读取本地数据…"
        self._busy = False
        self._worker: QThread | None = None

        self._detail_open = False
        self._detail_title = ""
        self._detail_status = ""
        self._detail_rows: list[dict] = []

    # ── 指数卡 / 主图 ────────────────────────────────────────

    cards = Property(list, lambda self: self._cards, notify=dataChanged)
    xLabels = Property(list, lambda self: self._x_labels, notify=dataChanged)
    series = Property(list, lambda self: self._series, notify=dataChanged)
    ma7Series = Property(list, lambda self: self._ma7, notify=dataChanged)
    #: 真正喂给 FLineChart 的那组线：开了「7 日均线」就给平滑序列。
    #: 两者**不同时画**：同一指数的原线与均线同色，五条叠成十条只会糊成一团。
    displaySeries = Property(list, lambda self: self._ma7 if self._show_ma7 else self._series, notify=dataChanged)
    showMa7 = Property(bool, lambda self: self._show_ma7, notify=dataChanged)
    selectedKey = Property(str, lambda self: self._selected_key, notify=dataChanged)

    @Slot(str)
    def selectIndex(self, key: str) -> None:
        """点指数卡：选中它（成员表跟着切）；再点一次取消。"""
        key = str(key)
        self._selected_key = "" if key == self._selected_key else key
        for card in self._cards:
            card["selected"] = card["key"] == self._selected_key
        self._sync_members()
        self._sync_divergence()
        self.dataChanged.emit()

    @Slot(bool)
    def setShowMa7(self, checked: bool) -> None:
        """7 日均线开关（序列由桥给，见 `displaySeries`）。"""
        if bool(checked) != self._show_ma7:
            self._show_ma7 = bool(checked)
            self.dataChanged.emit()

    # ── 量价 / 广度 ─────────────────────────────────────────

    turnoverText = Property(str, lambda self: self._turnover_text, notify=dataChanged)
    advDeclText = Property(str, lambda self: self._adv_decl_text, notify=dataChanged)
    divergenceText = Property(str, lambda self: self._divergence_text, notify=dataChanged)
    divergenceToken = Property(str, lambda self: self._divergence_token, notify=dataChanged)

    # ── 篮子成员表 ──────────────────────────────────────────

    members = Property(list, lambda self: self._members, notify=dataChanged)
    membersNote = Property(str, lambda self: self._members_note, notify=dataChanged)

    # ── 异动榜（两区）──────────────────────────────────────

    qualifiedMovers = Property(list, lambda self: self._qualified, notify=dataChanged)
    marketMovers = Property(list, lambda self: self._market, notify=dataChanged)
    moversNote = Property(str, lambda self: self._movers_note, notify=dataChanged)

    # ── 数据状态行 ──────────────────────────────────────────

    statusRows = Property(list, lambda self: self._status_rows, notify=dataChanged)
    statusHint = Property(str, lambda self: self._status_hint, notify=dataChanged)

    # ── 刷新状态 ────────────────────────────────────────────

    busy = Property(bool, lambda self: self._busy, notify=refreshStateChanged)
    statusText = Property(str, lambda self: self._status_text, notify=refreshStateChanged)

    # ── 右侧抽屉（BOM 传导链）──────────────────────────────

    detailOpen = Property(bool, lambda self: self._detail_open, notify=detailChanged)
    detailTitle = Property(str, lambda self: self._detail_title, notify=detailChanged)
    detailStatus = Property(str, lambda self: self._detail_status, notify=detailChanged)
    detailRows = Property(list, lambda self: self._detail_rows, notify=detailChanged)

    # ═══════════════════════════════════════════════════════
    #  取数
    # ═══════════════════════════════════════════════════════

    @Slot()
    def refresh(self) -> None:
        """重新读一遍页面数据（全部是本地库的读，不碰网络）。"""
        region = self._region_id()
        self._refresh_indices(region)
        self._refresh_movers(region)
        self._refresh_breadth(region)
        self._refresh_status(region)
        self._status_text = (
            f"指数 {len(self._cards)} 个 · 异动 {len(self._qualified)} 条合格成分 / "
            f"{len(self._market)} 条全市场 · 成交额窗口 {len(self._turnover)} 天"
        )
        self.dataChanged.emit()
        self.refreshStateChanged.emit()

    def _region_id(self) -> int:
        """本页用的区域 —— 计划 §6 决定指数**先只做 Jita**（其余中心快照只有 5–9 天）。

        取后端自己的 `JITA_RID`；服务还没落地（并行开发期）就退回
        `core.constants.TRADE_HUB_IDS["Jita"]` —— 两者本来就是同一个 region_id。
        """
        try:
            return int(_index_service().JITA_RID)
        except Exception:
            # 吞的是 ModuleNotFoundError（服务未落地）/ AttributeError（契约漂了）
            log.exception("读取大盘区域 id 失败，退回 Jita")
            return int(TRADE_HUB_IDS["Jita"])

    def _safe(self, what: str, load: Callable[[], Any], default: Any) -> Any:
        """跑一次后端读取；失败就退化成 `default` 并记日志。

        这里吞的是**读本地库/后端服务**这一类失败：`sqlite3.Error`（market.db 被写锁住、
        表还没建）、服务侧的 `ValueError`（样本天数不够算不出指数）以及后端尚未落地的
        `ModuleNotFoundError`/`AttributeError`。这些都不该让整页打不开 ——
        失败的那一块退化成空/`—`，其余照常显示，原因进日志。
        """
        try:
            return load()
        except Exception:
            log.exception("%s 失败", what)
            return default

    def _refresh_indices(self, region: int) -> None:
        def _load() -> tuple[list[dict], list[dict]]:
            api = _index_service()
            return (
                list(api.get_index_cards(region)),
                list(api.get_index_series(keys=None, region_id=region)),
            )

        cards_raw, series_raw = self._safe("读取指数卡片与序列", _load, ([], []))

        self._cards = [_card_view(raw) for raw in cards_raw]
        self._series, self._ma7, self._x_labels = _series_views(series_raw)
        self._members_by_key = _members_by_key(series_raw)
        # 选中的指数已经不在卡片里（数据/成分变了）→ 清掉，免得成员表停在旧篮子上
        if self._selected_key and self._selected_key not in {card["key"] for card in self._cards}:
            self._selected_key = ""
        for card in self._cards:
            card["selected"] = card["key"] == self._selected_key
        self._sync_members()

    def _refresh_movers(self, region: int) -> None:
        def _load() -> list[dict]:
            return list(
                _movers_service().get_movers(
                    days=_MOVER_DAYS,
                    limit=_MOVER_LIMIT,
                    region_id=region,
                    qualified_only=False,
                )
            )

        raw = self._safe("读取市场异动榜", _load, [])
        labels = {card["key"]: card["label"] for card in self._cards}
        views = [_mover_view(row, labels) for row in raw]
        # 「合格成分」是可信的那一区（白名单准入 + 流动性门槛），「全市场」把噪音也放进来
        self._qualified = [row for row in views if row["qualified"]][:_MOVER_DISPLAY_CAP]
        self._market = [row for row in views if not row["qualified"]][:_MOVER_DISPLAY_CAP]
        if not views:
            self._movers_note = "没有异动数据 —— 先在顶栏「更新价格」补齐成交均价历史"
        else:
            self._movers_note = f"窗口 {_MOVER_DAYS} 天 · 每区显示前 {_MOVER_DISPLAY_CAP} 条（共 {len(views)} 条）"

    def _refresh_breadth(self, region: int) -> None:
        self._breadth = self._safe("读取市场广度", lambda: dict(_index_service().get_breadth(region)), {})
        self._turnover = self._safe("读取日成交额序列", lambda: _turnover_series(region), [])
        self._turnover_text = _turnover_text(self._turnover, self._breadth)
        self._adv_decl_text = _adv_decl_text(self._breadth)
        self._sync_divergence()

    def _refresh_status(self, region: int) -> None:
        raw = self._safe("读取各中心快照天数", _hub_snapshot_rows, [])
        self._status_rows = [_status_view(row) for row in raw]
        self._status_hint = _status_hint(raw, region)

    def _sync_members(self) -> None:
        """成员表按**选中**的指数取；没选中就默认第一条（否则一进页面是一张空表）。"""
        key = self._selected_key or (self._cards[0]["key"] if self._cards else "")
        raw = self._members_by_key.get(key, [])
        self._members = [_member_view(row) for row in raw[:_MEMBER_CAP]]
        label = next((card["label"] for card in self._cards if card["key"] == key), key)
        if not raw:
            self._members_note = f"{label}：暂无成分数据（先在顶栏「更新价格」补齐成交均价历史）"
        elif len(raw) > _MEMBER_CAP:
            self._members_note = f"{label}：按权重显示前 {_MEMBER_CAP} 个，共 {len(raw)} 个成分"
        else:
            self._members_note = f"{label}：{len(raw)} 个成分"

    def _index_chg_pct(self) -> float | None:
        """量价背离要用的「指数涨跌」：选中那张卡用它的今日涨跌，没选就取五条线的均值。"""
        if self._selected_key:
            for card in self._cards:
                if card["key"] == self._selected_key:
                    return _as_float(card.get("chg1"))
        values = [float(card["chg1"]) for card in self._cards if card.get("chg1") is not None]
        return sum(values) / len(values) if values else None

    def _sync_divergence(self) -> None:
        self._divergence_text, self._divergence_token = _divergence(self._index_chg_pct(), self._turnover)

    # ═══════════════════════════════════════════════════════
    #  异动行 → 传导链抽屉
    # ═══════════════════════════════════════════════════════

    @Slot(str, int)
    def openMover(self, section: str, row: int) -> None:
        """点异动行：右侧抽屉显示该物品的 BOM 传导链（`section` 是 `qualified` / `market`）。"""
        rows = self._qualified if section == "qualified" else self._market
        if not 0 <= row < len(rows):
            return
        mover = rows[row]
        type_id = int(mover["typeId"])

        self._detail_open = True
        self._detail_title = str(mover["name"])
        self._detail_status = "正在读本地 BOM 传导链…"
        self._detail_rows = []
        self.detailChanged.emit()  # 先把抽屉开出来，链子读得慢也知道点到了

        raw = self._safe(
            "读取 BOM 传导链",
            lambda: list(
                _chain_service().get_transmission_chain(type_id, depth=_CHAIN_DEPTH, region_id=self._region_id())
            ),
            [],
        )
        self._detail_rows = [_chain_view(row_) for row_ in raw]
        self._detail_status = _detail_note(raw)
        self.detailChanged.emit()

    @Slot()
    def closeDetail(self) -> None:
        """关抽屉。"""
        if not self._detail_open:
            return
        self._detail_open = False
        self._detail_rows = []
        self._detail_status = ""
        self.detailChanged.emit()

    # ═══════════════════════════════════════════════════════
    #  「刷新指数」（后台线程）
    # ═══════════════════════════════════════════════════════

    @Slot()
    def on_shown(self) -> None:
        """外壳把本页切到前台时的钩子（`ui_qml/monitor_page.py` 的转发器会调两个桥）。

        只重读一遍本地数据（`refresh`）—— 切回来该看到新的，且都是本地库的快照读，
        不同步做重活。

        ⚠️ **不**在这里自动跑 `refreshIndex()`：那要聚合几十万行 `price_history`，
        每次切页都来一遍是浪费（用户手上有「刷新指数」按钮，空态文案也指着它）；
        更要紧的是测试/首次运行时它会对 market.db 产生真实写入副作用。
        首次打开若指数物化表是空的，页面会显示「点右上『刷新指数』」。
        """
        self.refresh()

    @Slot()
    def refreshIndex(self) -> None:
        """顶部「刷新指数」：重算 `market_index_daily` 物化表（QThread，不卡 UI）。"""
        if self._busy:
            return
        self._busy = True
        self._status_text = "正在重算日指数（要聚合几十万行本地成交历史）…"
        self.refreshStateChanged.emit()

        from ui_qml.workers.trade_workers import spawn

        worker = IndexRefreshWorker(self._region_id())
        self._worker = worker
        worker.finished_signal.connect(self._on_index_refreshed)
        worker.failed_signal.connect(self._on_index_failed)
        spawn(worker)

    def _on_index_refreshed(self, written: int) -> None:
        self.refresh()
        self._busy = False
        self._status_text = f"指数已重算（写入 {written} 行日指数）· {self._status_text}"
        self.refreshStateChanged.emit()

    def _on_index_failed(self, message: str) -> None:
        self._busy = False
        self._status_text = f"重算指数失败：{message}"
        self.refreshStateChanged.emit()

    @Slot()
    def shutdown(self) -> None:
        """页面/外壳销毁前收尾在跑的线程（宿主先走而线程还在跑 → Qt 直接 abort）。"""
        from ui_qml.workers.lifecycle import drop_worker

        worker = self._worker
        if worker is None:
            return
        drop_worker(worker)
        self._worker = None


def _detail_note(raw: list[dict]) -> str:
    """抽屉状态行：行数 + 最深层级 + 口径标签（计划 §4.1 的「带口径标签」）。"""
    if not raw:
        return "没有可下钻的制造链 —— 该物品不是任何蓝图的材料/产物（或本地蓝图库为空）"
    sources = "、".join(sorted({_source_text(row.get("source")) for row in raw}))
    depth = max(int(_as_float(row.get("level")) or 0) for row in raw)
    return f"{len(raw)} 行 · 最深 {depth} 级 · 口径：{sources}"
