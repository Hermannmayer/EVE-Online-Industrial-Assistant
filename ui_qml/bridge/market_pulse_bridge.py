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

import time
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


def _advice_service() -> Any:
    """惰性取 `services.market_advice_service`（挂单/卖单建议）。"""
    from services import market_advice_service

    return market_advice_service


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

    **尾部残缺日会被丢掉**：ESI 的历史按天逐步出，最后一天常常只有几百个 type
    （实测 2026-10-04 只有 434 个、前一天 2,926 个），把它算进环比会得到
    「−83.6%」这种纯属数据没补齐的假信号。
    """
    try:
        from services.database_manager import get_db

        with get_db().connect("mkt") as conn:
            if not _has_table(conn, "price_history"):
                return []
            rows = conn.execute(
                "SELECT date, COUNT(*) AS n, SUM(average * volume) AS isk FROM price_history "
                "WHERE region_id = ? AND date >= date((SELECT MAX(date) FROM price_history WHERE region_id = ?), ?) "
                "GROUP BY date ORDER BY date ASC",
                (region_id, region_id, f"-{max(1, int(days))} days"),
            ).fetchall()
    except Exception:
        # 同上：读不到就不给「量价背离」提示，页面其余部分照常。
        log.exception("读取日成交额序列失败")
        return []

    out: list[tuple[str, float, int]] = [(str(r["date"]), float(r["isk"] or 0.0), int(r["n"] or 0)) for r in rows]
    # 尾部残缺日：覆盖 type 数明显低于窗口常态的日子（通常是还没补齐的当天/昨天），直接丢掉
    if len(out) >= 3:
        typical = max(n for _day, _isk, n in out[:-1])
        while len(out) >= 3 and out[-1][2] < 0.5 * typical:
            out.pop()
    return [{"date": day, "isk": isk} for day, isk, _n in out]


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


def _card_hint(key: str, days: int, value: float | None) -> str:
    """卡片的补充说明（空串 = 不显示）。

    PLEX 必须单独说清口径：**它的价格全服统一、没有区域划分**，ESI 的区块历史对它恒返回空
    —— 数据来自「更新价格」里 `/markets/prices/` 的每日快照，与另外四条（区域成交均价）
    不是一回事，不能让人以为它是同口径的第五个指数。
    """
    if key == "plex":
        if value is None:
            return "全服统一价：ESI 不提供区域历史，先跑一次「更新价格」才有序列"
        return "全服统一价（口径不同于另外四条的区域成交均价）"
    if days < 30:
        return "基期短，长窗口不全"
    return ""


def _card_view(raw: dict) -> dict:
    """指数卡：现值 + 今日/7/30/90/180 涨跌（缺值 `—`）+ 口径/基期提示。"""
    changes = (
        ("今日", raw.get("chg1")),
        ("7日", raw.get("chg7")),
        ("30日", raw.get("chg30")),
        ("90日", raw.get("chg90")),
        ("180日", raw.get("chg180")),
    )
    key = str(raw.get("key") or "")
    days = int(_as_float(raw.get("days")) or 0)
    return {
        "key": key,
        "label": str(raw.get("label") or raw.get("key") or ""),
        "valueText": _num(raw.get("value")),
        "chg1": _as_float(raw.get("chg1")),  # 量价背离要用原始值，不解析文案
        "chg30": _as_float(raw.get("chg30")),  # 图例与诊断要原始值
        "days": days,
        "baseDate": str(raw.get("base_date") or _DASH),
        "selected": False,
        "hint": _card_hint(key, days, _as_float(raw.get("value"))),
        "chgs": [{"label": label, "text": _pct(value), "token": _chg_token(value)} for label, value in changes],
    }


#: 折线图的时间粒度（点数 = 交易日数）。用户口径：「如果我想看近 7 日或者近 30 天的，
#: 这个时间粒度没有筛选」——图默认拉满 180 天，五条线挤在一起看不出近期的拐点。
RANGE_OPTIONS: tuple[int, ...] = (7, 30, 90, 180)
RANGE_LABELS: tuple[str, ...] = ("近 7 天", "近 30 天", "近 90 天", "近 180 天")
DEFAULT_RANGE_INDEX = 3  # 默认 180 天（与「刷新指数」的物化窗口一致）


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
    """篮子成员行：权重、现价、30 日涨跌、**对指数的贡献**、是否触顶（`capped`）、口径。

    `price` 是后端在**锚定指数日（含）之前最近一次成交均价**（当日没成交就往前找，
    完全没有观测给 `None`）—— 与指数、异动榜同一口径，不用挂单价。

    贡献（百分点）= 权重 × 该成员 30 日涨跌：指数跌 8% 时，一眼看出是**谁在拖**（哪几个
    成分贡献了大部分跌幅）—— 只按权重排序看不出这件事。
    """
    weight = _as_float(raw.get("weight"))
    chg30 = _as_float(raw.get("chg30"))
    contrib = None if weight is None or chg30 is None else weight * chg30
    return {
        "typeId": int(_as_float(raw.get("typeId")) or 0),
        "name": str(raw.get("name") or raw.get("typeId") or ""),
        "weightText": _share(raw.get("weight")),
        "priceText": _num(raw.get("price")),
        "chg30Text": _pct(raw.get("chg30")),
        "chg30Token": _chg_token(raw.get("chg30")),
        "contribText": _pp_text(contrib),
        "contribToken": _chg_token(contrib),
        "capped": bool(raw.get("capped")),
        "sourceText": _source_text(raw.get("source")),
    }


def _pp_text(value: float | None) -> str:
    """百分点文案（贡献度）：`-1.23pp` / `—`。"""
    if value is None:
        return _DASH
    return f"{value:+.2f}pp"


#: 首次使用引导：这一页能回答什么问题、3 步怎么用（用户口径：「有点门槛，我不太会用」）。
_GUIDE_TEXT = (
    "这一页回答一个问题：现在这个市场，该囤、该卖、还是该停。\n"
    "① 先看上面的诊断条与四条实体线的方向（10 秒）；\n"
    "② 哪条线明显偏离就去点它的成员表，看是谁在拉/在拖（「贡献」那一列）；\n"
    "③ 再用下面的异动榜找具体物品、点开抽屉看 BOM 传导链与挂单建议 —— 提前备料或提前出货。\n"
    "口径：只用 Jita 的成交均价（挂单价一个人就能推，只做供给予警）；指数 100 = 基期，"
    "跌 = 这一篮子东西整体变便宜。PLEX 是全服统一价，与另外四条不是同一种口径。"
)


#: 每张指数卡的「构成 + 口径」副标题与「怎么看」提示（键 = 指数 key，成员数在调用处补）。
_CARD_META: dict[str, tuple[str, str]] = {
    "mpi": (
        "8 种矿物 · 成交额加权 · 30 天滚动再平衡",
        "CCP 官方 MPI 同款篮子。100 = 基期水平；读数 82 表示这 8 种矿比基期平均便宜 18%。"
        "矿物全线涨 → 采矿端紧缩或需求爆发（该抢料）；全线跌 → 上游在松，别囤料。",
    ),
    "pppi": (
        "初级投入品 · 成交额加权 · 30 天滚动再平衡",
        "供入的对象**仍然是材料**的那些东西（矿石/月矿/行星产物/发明用品）。它涨而 SPPI 没涨 → 冶炼与中间品在吃利润。",
    ),
    "sppi": (
        "次级投入品 · 成交额加权 · 30 天滚动再平衡",
        "直接供消费品生产的材料与物品（T2 组件、R.A.M. 等）。它涨得比 CPI 快 → 生产端瓶颈，该卖组件而不是卖成品。",
    ),
    "cpi": (
        "消费品（成交额前 N，代理 CCP 的 4000+ 篮子）",
        "终端需求的温度计：成品在跌而原料没跌 → 加工利润被压缩；成品跌得比原料快 → 需求在退，别囤料、成品早出手。",
    ),
    "plex": (
        "全服统一价 · ISK 锚（不走区域成交历史）",
        "PLEX 价格**全服统一、没有区域划分**，ESI 不提供它的区块历史，本线取自 "
        "「更新价格」里 /markets/prices/ 的每日快照。它涨 = ISK 贬值；四条实体线不动而它涨，"
        "说明只是货币现象，不是供需。",
    ),
}


def _card_meta(key: str, members: int) -> tuple[str, str]:
    """卡片副标题（构成/口径）与「怎么看」提示；成员数塞进 N 占位。"""
    subtitle, tip = _CARD_META.get(key, ("", ""))
    if members > 0:
        subtitle = subtitle.replace("N", str(members))
    elif "N" in subtitle:
        subtitle = "消费品（篮子按成交额选取）"
    return subtitle, tip


def _diagnosis(cards: list[dict], breadth: dict, adv_decl: str) -> list[dict]:
    """把指数与广度压成 2~4 条**带含义的结论**（规则推导，不是预测）。

    每条给 `{text, token}`：`text` 是人话结论 + 「含义：…」，`token` 决定颜色
    （涨绿/跌红/中性）。用户口径是「不知道这页有什么用」——所以这里必须把数字翻译成
    「那我该干什么」，而不是再摆一遍数字。
    """
    by_key = {card["key"]: card for card in cards}
    real = [k for k in ("mpi", "pppi", "sppi", "cpi") if by_key.get(k, {}).get("chg30") is not None]
    out: list[dict] = []

    if not real:
        return [
            {
                "text": "还没有可算的指数 —— 先在顶栏「更新价格」拉一次市场历史"
                "（成交历史在 ESI 侧一次给全，跑一轮就有 90/180 天窗口）",
                "token": "TEXT_SECONDARY",
            }
        ]

    avg30 = sum(float(by_key[k]["chg30"]) for k in real) / len(real)
    if avg30 <= -3:
        out.append(
            {
                "text": f"整体在通缩：四条实体线近 30 天平均 {avg30:+.1f}%"
                "。含义：现金更值钱，别囤料、成品尽快出手，扩产要谨慎。",
                "token": "ACCENT_GREEN" if avg30 > 0 else "ACCENT_RED",
            }
        )
    elif avg30 >= 3:
        out.append(
            {
                "text": f"整体在通胀：四条实体线近 30 天平均 {avg30:+.1f}%"
                "。含义：实物在涨价，可考虑提前备料；但先看是全线涨还是单环节涨。",
                "token": "ACCENT_YELLOW",
            }
        )
    else:
        out.append(
            {
                "text": f"大盘走平：四条实体线近 30 天平均 {avg30:+.1f}%（±3% 以内视为横盘）"
                "。含义：趋势不帮忙，收益主要看具体物品的价差与产能。",
                "token": "TEXT_SECONDARY",
            }
        )

    mpi = _as_float(by_key.get("mpi", {}).get("chg30"))
    cpi = _as_float(by_key.get("cpi", {}).get("chg30"))
    if mpi is not None and cpi is not None:
        gap = cpi - mpi  # 成品相对原料的强弱
        if gap >= 1.5:
            out.append(
                {
                    "text": f"加工端在改善：成品（CPI {cpi:+.1f}%）比原料（MPI {mpi:+.1f}%）更抗跌。"
                    "含义：制造出售的价差在变宽，值得多排产。",
                    "token": "ACCENT_GREEN",
                }
            )
        elif gap <= -1.5:
            out.append(
                {
                    "text": f"加工端在恶化：成品（CPI {cpi:+.1f}%）比原料（MPI {mpi:+.1f}%）跌得更狠。"
                    "含义：造出来卖不上价，先按需生产、别压库存。",
                    "token": "ACCENT_RED",
                }
            )

    adv = _as_float(breadth.get("advancers"))
    dec = _as_float(breadth.get("decliners"))
    if adv is not None and dec is not None and (adv + dec) > 0:
        ratio = adv / max(1.0, dec)
        if ratio >= 1.5:
            word, token = "普涨（涨家数明显多于跌家数）", "ACCENT_GREEN"
        elif ratio <= 0.67:
            word, token = "普跌（跌家数明显多于涨家数）", "ACCENT_RED"
        else:
            word, token = "分化（涨跌家数接近，说明是个别板块在动）", "TEXT_SECONDARY"
        out.append(
            {
                "text": f"广度：{word} —— {adv_decl}。含义："
                + ("普涨时跟大盘走比较安全；" if ratio >= 1.5 else "")
                + ("普跌时优先保现金；" if ratio <= 0.67 else "")
                + "分化时去看下面的异动榜找线索。",
                "token": token,
            }
        )

    thin = [card["key"] for card in cards if card.get("days", 0) < 180 and card["key"] != "plex"]
    if thin:
        out.append(
            {
                "text": "长窗口还在补数："
                + "、".join(card["label"] for card in cards if card["key"] in thin)
                + " 的 90/180 天窗口未满 —— 成交历史一次能拉全，跑一轮「更新价格」即可。",
                "token": "TEXT_SECONDARY",
            }
        )
    return out


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


#: 切页重读的 TTL（秒）：窗口内重复切到本页直接复用上次结果。
#: 为什么要有：整页读取实测约 11 秒（卡片 3.1s + 曲线/成员 7.0s + 异动 0.8s，真实库 116 万行），
#: 每次切页都重跑既浪费又让用户等；数据变化只可能来自「更新价格」或「刷新指数」，
#: 那两个入口都会 `force=True` 绕开它。
_REFRESH_TTL_S = 60.0


def _load_payload(region_id: int) -> dict[str, Any]:
    """整页要用的本地数据，**一次读全**（在后台线程里跑，绝不碰网络）。

    每一块的失败都单独吞掉并记日志（与桥里原来的 `_safe` 同口径）：某个后端没落地时
    那一块退化成空，其余照常显示，而不是整页打不开。
    """

    def read(what: str, load: Callable[[], Any], default: Any) -> Any:
        try:
            return load()
        except Exception:
            log.exception("%s 失败", what)
            return default

    try:
        api = _index_service()
    except Exception:
        log.exception("大盘后端未落地，整页退化成空态")
        return {}
    return {
        "cards": list(read("读取指数卡片", lambda: api.get_index_cards(region_id), [])),
        "series": list(read("读取指数序列", lambda: api.get_index_series(keys=None, region_id=region_id), [])),
        "breadth": dict(read("读取市场广度", lambda: api.get_breadth(region_id), {})),
        "turnover": list(read("读取日成交额序列", lambda: _turnover_series(region_id), [])),
        "movers": list(
            read(
                "读取市场异动榜",
                lambda: _movers_service().get_movers(
                    days=_MOVER_DAYS, limit=_MOVER_LIMIT, region_id=region_id, qualified_only=False
                ),
                [],
            )
        ),
        "status": list(read("读取各中心快照天数", _hub_snapshot_rows, [])),
    }


class PulseLoadWorker(QThread):
    """整页数据后台读取（卡片/曲线/篮子成员/广度/成交额/异动/数据状态行）。

    为什么必须开线程：实测真实库下这几步合计约 11 秒，同步跑会让「切到市场监控」卡住
    整个主窗口。用户口径：「每次点市场监控这一页都会卡半天」「重算指数不应该阻塞主窗口，
    应该自己在后台算就行」。写法同 :class:`IndexRefreshWorker`：结果走信号回主线程。
    """

    loaded_signal = Signal(object)  # dict payload
    failed_signal = Signal(str)

    def __init__(self, region_id: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._region_id = int(region_id)

    def run(self) -> None:
        try:
            self.loaded_signal.emit(_load_payload(self._region_id))
        except Exception as ex:
            log.exception("读取大盘页数据失败")
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
    guideChanged = Signal()

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
        self._diagnosis: list[dict] = []
        #: 首次使用引导：说明「这一页能回答什么问题」。只对本次会话有效（与「置顶」同口径，
        #: 不落盘）—— 用户学会之后关掉即可
        self._guide_visible = True

        #: 量价/广度那三行（`refresh` 之前 QML 就会绑定它们，必须先有初值 ——
        #: 绑定里读不存在的属性是**静默失败**，只会让那一格空着）
        self._turnover_text = "成交额 —"
        self._adv_decl_text = "涨跌家数 —"
        self._divergence_text = ""
        self._divergence_token = ""

        self._status_text = "正在读取本地数据…"
        self._busy = False
        self._worker: QThread | None = None
        #: 整页数据是否正在后台读（`refresh()` 的并发闸门）
        self._loading = False
        #: 上次读完的时间（`time.monotonic()`）——`_REFRESH_TTL_S` 内的切页直接复用
        self._loaded_at = 0.0
        self._load_worker: PulseLoadWorker | None = None
        #: 折线图时间粒度（下标进 `RANGE_OPTIONS`）+ 原始 180 天点位
        self._range_index = DEFAULT_RANGE_INDEX
        self._range_days = RANGE_OPTIONS[self._range_index]
        self._series_raw: list[dict] = []
        self._base_note = ""

        self._detail_open = False
        self._detail_title = ""
        self._detail_status = ""
        self._detail_rows: list[dict] = []
        self._advice: dict = dict(_EMPTY_ADVICE)

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

    #: 折线图时间粒度：`rangeLabels` 给 QML 画按钮，`rangeIndex` 是当前选项
    rangeLabels = Property(list, lambda self: list(RANGE_LABELS), notify=dataChanged)
    rangeIndex = Property(int, lambda self: self._range_index, notify=dataChanged)
    #: 图上要写出来的基期说明（「基期 2026-03-04 = 100 · 当前显示最近 180 个交易日」）
    baseNote = Property(str, lambda self: self._base_note, notify=dataChanged)

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

    # ── 市场诊断与首次引导 ──────────────────────────────────

    #: `[{text, token}]` —— 规则从指数/广度推出来的结论（**不是预测**，也不构成投资建议）
    diagnosis = Property(list, lambda self: self._diagnosis, notify=dataChanged)

    #: 这一页能回答什么、怎么用（3 步）。关掉只影响本次会话
    guideVisible = Property(bool, lambda self: self._guide_visible, notify=guideChanged)
    guideText = Property(str, lambda self: _GUIDE_TEXT, notify=guideChanged)

    # ── 刷新状态 ────────────────────────────────────────────

    busy = Property(bool, lambda self: self._busy, notify=refreshStateChanged)
    statusText = Property(str, lambda self: self._status_text, notify=refreshStateChanged)

    # ── 右侧抽屉（BOM 传导链）──────────────────────────────

    detailOpen = Property(bool, lambda self: self._detail_open, notify=detailChanged)
    detailTitle = Property(str, lambda self: self._detail_title, notify=detailChanged)
    detailStatus = Property(str, lambda self: self._detail_status, notify=detailChanged)
    detailRows = Property(list, lambda self: self._detail_rows, notify=detailChanged)

    #: 挂单/卖单建议（点异动行时装配；空 dict = 还没点或读失败）：
    #: `{verdict, title, token, buyAdvice, sellAdvice, reasons, caliber, metrics}`
    advice = Property(dict, lambda self: self._advice, notify=detailChanged)

    # ═══════════════════════════════════════════════════════
    #  取数
    # ═══════════════════════════════════════════════════════

    @Slot()
    def refresh(self, force: bool = False) -> None:
        """重新读一遍页面数据（**全部是本地库的读**，不碰网络）—— 在后台线程里跑。

        为什么必须离开主线程：实测真实库（116 万行 `price_history`）卡片 3.1s +
        曲线与篮子成员 7.0s + 异动 0.8s，同步跑会让「切到市场监控」卡住主窗口近 11 秒。
        用户口径：「重算指数不应该阻塞主窗口，应该自己在后台算就行」。

        另外做一层 TTL（:data:`_REFRESH_TTL_S`）：切页来回一次不该重跑十几秒的重算 ——
        窗口内的切页直接复用上次结果。手动「刷新指数」重算完成时会 `force=True` 绕开它。
        """
        if self._loading:
            return  # 已经在读，别叠第二个 worker
        if not force and self._loaded_at and (time.monotonic() - self._loaded_at) < _REFRESH_TTL_S:
            return

        self._loading = True
        self._status_text = "正在读取本地数据…"
        self.refreshStateChanged.emit()

        from ui_qml.workers.trade_workers import spawn

        worker = PulseLoadWorker(self._region_id())
        self._load_worker = worker
        worker.loaded_signal.connect(self._on_loaded)
        worker.failed_signal.connect(self._on_load_failed)
        spawn(worker)

    @Slot(object)
    def _on_loaded(self, payload: object) -> None:
        """后台读完了：把结果装上并通知 QML（主线程）。"""
        data = dict(payload or {}) if isinstance(payload, dict) else {}
        self._apply_indices(list(data.get("cards") or []), list(data.get("series") or []))
        self._apply_movers(list(data.get("movers") or []))
        self._apply_breadth(dict(data.get("breadth") or {}), list(data.get("turnover") or []))
        self._apply_status(list(data.get("status") or []))
        self._status_text = (
            f"指数 {len(self._cards)} 个 · 异动 {len(self._qualified)} 条合格成分 / "
            f"{len(self._market)} 条全市场 · 成交额窗口 {len(self._turnover)} 天"
        )
        self._loaded_at = time.monotonic()
        self._loading = False
        self._load_worker = None
        self.dataChanged.emit()
        self.refreshStateChanged.emit()

    @Slot(str)
    def _on_load_failed(self, message: str) -> None:
        """整页读取失败（后端没落地/库坏了）：留空态 + 如实写状态，不装成功。"""
        self._loading = False
        self._load_worker = None
        self._status_text = f"读取本地数据失败：{message}"
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

    def _apply_indices(self, cards_raw: list[dict], series_raw: list[dict]) -> None:
        self._cards = [_card_view(raw) for raw in cards_raw]
        # 序列原始点位留一份（180 天），时间粒度筛选只**切点**，不重读库
        self._series_raw = list(series_raw or [])
        self._members_by_key = _members_by_key(series_raw)
        # 卡片副标题（构成 N 个成分 + 权重口径）与「怎么看」提示：成员数只有这里知道
        for card in self._cards:
            members = self._members_by_key.get(card["key"]) or []
            card["subtitle"], card["toolTipText"] = _card_meta(card["key"], len(members))
        self._rebuild_series()
        # 图例带上「现值 · 30 日涨跌」：五条线只看名字看不出各自在什么水平
        by_key = {card["key"]: card for card in self._cards}
        for line in self._series:
            card = by_key.get(line["key"]) or {}
            chg = _as_float(card.get("chg30"))
            line["note"] = card.get("valueText", _DASH) + ("" if chg is None else f" · 30日 {_pct(chg)}")
        # 选中的指数已经不在卡片里（数据/成分变了）→ 清掉，免得成员表停在旧篮子上
        if self._selected_key and self._selected_key not in {card["key"] for card in self._cards}:
            self._selected_key = ""
        for card in self._cards:
            card["selected"] = card["key"] == self._selected_key
        self._sync_members()

    def _rebuild_series(self) -> None:
        """按当前**时间粒度**切点并重建图例线（不发请求、不读库 —— 用户切粒度要瞬时）。

        用户口径：「如果我想看近 7 日或者近 30 天的，这个时间粒度没有筛选」。
        后端给的序列固定是 180 天，这里只按日期裁掉左边的点。
        """
        sliced: list[dict] = []
        days = self._range_days
        for item in self._series_raw or []:
            points = list(item.get("points") or [])
            if days and len(points) > days:
                points = points[-days:]
            sliced.append({**item, "points": points})
        self._series, self._ma7, self._x_labels = _series_views(sliced)
        # 基期说明：图上必须自己写出「100 从哪天开始」（用户问过），再补当前粒度
        base = min((card["baseDate"] for card in self._cards if card.get("baseDate") not in ("", _DASH)), default="")
        if base:
            self._base_note = f"基期 {base} = 100 · 当前显示最近 {days} 个交易日"
        else:
            self._base_note = f"当前显示最近 {days} 个交易日（还没有基期）"

    def _apply_movers(self, raw: list[dict]) -> None:
        labels = {card["key"]: card["label"] for card in self._cards}
        views = [_mover_view(row, labels) for row in raw]
        # 「合格成分」是可信的那一区（白名单准入 + 流动性门槛），「全市场」把噪音也放进来
        self._qualified = [row for row in views if row["qualified"]][:_MOVER_DISPLAY_CAP]
        self._market = [row for row in views if not row["qualified"]][:_MOVER_DISPLAY_CAP]
        if not views:
            self._movers_note = "没有异动数据 —— 先在顶栏「更新价格」补齐成交均价历史"
        else:
            self._movers_note = f"窗口 {_MOVER_DAYS} 天 · 每区显示前 {_MOVER_DISPLAY_CAP} 条（共 {len(views)} 条）"

    def _apply_breadth(self, breadth: dict, turnover: list[dict]) -> None:
        self._breadth = breadth
        self._turnover = turnover
        self._turnover_text = _turnover_text(self._turnover, self._breadth)
        self._adv_decl_text = _adv_decl_text(self._breadth)
        self._sync_divergence()
        # 诊断条要同时看指数与广度，放在两者都算完之后
        self._diagnosis = _diagnosis(self._cards, self._breadth, self._adv_decl_text)

    def _apply_status(self, raw: list[dict]) -> None:
        self._status_rows = [_status_view(row) for row in raw]
        self._status_hint = _status_hint(raw, self._region_id())

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
        self._detail_status = "正在读本地数据…"
        self._detail_rows = []
        self._advice = dict(_EMPTY_ADVICE)
        self.detailChanged.emit()  # 先把抽屉开出来，读得慢也知道点到了

        raw = self._safe(
            "读取 BOM 传导链",
            lambda: list(
                _chain_service().get_transmission_chain(type_id, depth=_CHAIN_DEPTH, region_id=self._region_id())
            ),
            [],
        )
        self._detail_rows = [_chain_view(row_) for row_ in raw]
        self._detail_status = _detail_note(raw)
        self._advice = self._load_advice(type_id)
        self.detailChanged.emit()

    def _load_advice(self, type_id: int) -> dict:
        """取该物品的挂单/卖单建议（带大盘方向修正）。

        `trend_30d` 用 **CPI 的近 30 天涨跌** —— 它就是「成品端在涨还是跌」，与诊断条同源；
        没有 CPI 数据就给 `None`（服务侧会跳过那句大盘话术）。
        """
        trend: float | None = None
        for card in self._cards:
            if card["key"] == "cpi":
                trend = _as_float(card.get("chg30"))
        raw = self._safe(
            "读取交易建议",
            lambda: dict(_advice_service().get_trade_advice(type_id, self._region_id(), trend_30d=trend)),
            {},
        )
        return _advice_view(raw or {})

    @Slot()
    def closeDetail(self) -> None:
        """关抽屉。"""
        if not self._detail_open:
            return
        self._detail_open = False
        self._detail_rows = []
        self._detail_status = ""
        self._advice = dict(_EMPTY_ADVICE)
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
    def dismissGuide(self) -> None:
        """关掉首次使用引导（只对本次会话有效，与「置顶」同口径：不落盘）。"""
        if self._guide_visible:
            self._guide_visible = False
            self.guideChanged.emit()

    @Slot(int)
    def setRangeIndex(self, index: int) -> None:
        """切折线图的时间粒度（近 7/30/90/180 天）—— 只切已加载的点，不重读库。"""
        if not 0 <= index < len(RANGE_OPTIONS) or index == self._range_index:
            return
        self._range_index = int(index)
        self._range_days = RANGE_OPTIONS[self._range_index]
        self._rebuild_series()
        # 图例的「现值 · 30 日涨跌」在重建后要重新贴上
        by_key = {card["key"]: card for card in self._cards}
        for line in self._series:
            card = by_key.get(line["key"]) or {}
            chg = _as_float(card.get("chg30"))
            line["note"] = card.get("valueText", _DASH) + ("" if chg is None else f" · 30日 {_pct(chg)}")
        self.dataChanged.emit()

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
        self._busy = False
        # 重算完成 → 强制重读一次（绕开 `_REFRESH_TTL_S`：物化表刚变，缓存必须作废）
        self.refresh(force=True)
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

        # 两个 worker 都要收：`_worker` 是「刷新指数」的重算线程，
        # `_load_worker` 是整页数据的后台读取线程（切页/关窗时可能还在读）
        for attr in ("_worker", "_load_worker"):
            worker = getattr(self, attr, None)
            if worker is not None:
                drop_worker(worker)
                setattr(self, attr, None)
        self._loading = False


_ADVICE_TITLES: dict[str, str] = {
    "two_sided": "两侧挂单划算",
    "take_orders": "直接吃单更划算",
    "avoid_thin": "薄市场：别挂大单",
    "no_data": "本地没有这只物品的挂单/成交数据",
}

_ADVICE_TOKENS: dict[str, str] = {
    "two_sided": "ACCENT_GREEN",
    "take_orders": "PRIMARY",
    "avoid_thin": "ACCENT_YELLOW",
    "no_data": "TEXT_SECONDARY",
}

#: 没有建议时的**完整形状**（而不是空 dict）：QML 直接读 `advice.buyAdvice`，
#: 空 dict 上取键在 QML 里是 `undefined` 并刷「Unable to assign [undefined]」告警。
_EMPTY_ADVICE: dict[str, Any] = {
    "verdict": "",
    "title": "",
    "token": "",
    "buyAdvice": "",
    "sellAdvice": "",
    "reasons": [],
    "caliber": "",
    "metrics": [],
}


def _advice_view(raw: dict) -> dict:
    """`get_trade_advice` → QML 展示字段（含关键数字行）。

    数字行把「为什么这么建议」摊开：价差、来回费用、日均成交、卖单队列天数 ——
    只给一句「两侧挂单划算」用户无法判断该不该信。
    """
    if not raw:
        return dict(_EMPTY_ADVICE)
    verdict = str(raw.get("verdict") or "")
    metrics = [
        {"label": "价差（卖−买）", "value": _pct(raw.get("spreadPct"))},
        {"label": "来回费用（买+卖+税）", "value": _pct(raw.get("roundTripFeePct"))},
        {"label": "近 7 天日均成交", "value": _qty_text(raw.get("dayVolume"))},
        {"label": "卖单队列", "value": _order_queue_text(raw.get("orderVolume"), raw.get("turnDays"))},
    ]
    return {
        "verdict": verdict,
        "title": _ADVICE_TITLES.get(verdict, "—"),
        "token": _ADVICE_TOKENS.get(verdict, "TEXT_SECONDARY"),
        "buyAdvice": str(raw.get("buyAdvice") or ""),
        "sellAdvice": str(raw.get("sellAdvice") or ""),
        "reasons": [str(r) for r in (raw.get("reasons") or [])],
        "caliber": str(raw.get("caliber") or ""),
        "metrics": metrics,
    }


def _order_queue_text(order_volume: Any, turn_days: Any) -> str:
    """卖单队列：`2,705 件 ≈ 89.3 天` —— 挂单量除以日均成交量就是「要排队几天」。"""
    vol = _as_float(order_volume)
    days = _as_float(turn_days)
    if vol is None:
        return _DASH
    if days is None:
        return f"{_int_text(vol)} 件"
    return f"{_int_text(vol)} 件 ≈ {days:,.1f} 天"


def _detail_note(raw: list[dict]) -> str:
    """抽屉状态行：行数 + 最深层级 + 口径标签（计划 §4.1 的「带口径标签」）。"""
    if not raw:
        return "没有可下钻的制造链 —— 该物品不是任何蓝图的材料/产物（或本地蓝图库为空）"
    sources = "、".join(sorted({_source_text(row.get("source")) for row in raw}))
    depth = max(int(_as_float(row.get("level")) or 0) for row in raw)
    return f"{len(raw)} 行 · 最深 {depth} 级 · 口径：{sources}"
