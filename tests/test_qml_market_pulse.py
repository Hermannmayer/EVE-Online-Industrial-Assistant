"""市场大盘页（计划 `docs/dev/market-monitor-plan.md` §4.1）的契约测试。

分两层（与 `test_qml_watchlist.py` / `test_qml_trade.py` 同构）：

  - **桥层**：`MarketPulseBridge` 对三个后端服务的装配 —— 指数卡 / 主图（含 7 日均线）/
    量价广度（含量价背离）/ 篮子成员 / 异动榜两区 / 数据状态行 / 抽屉里的传导链与挂单建议 /
    行右键的三个动作（复制名称 / 加入关注列表 / 加入制造列表）；
  - **页面层**：`MarketPulsePane.qml` 能加载、无 QML 告警。

后端服务（`market_index_service` / `market_movers_service` / `market_chain_service` /
`market_advice_service`）与行右键写库的两个入口（`watchlist_manager` / 蓝图仓储 +
落计划）在这里**全部换替身**：本页与它们并行开发，替身让这两条用例既不依赖真实
`market.db` / `user.db` / `blueprint.db`，也不受那边接口微调影响 —— 桥对它们的唯一入口
就是模块级的 `_index_service()` / `_movers_service()` / `_chain_service()` /
`_advice_service()` / `_watchlist_service()` / `_blueprint_repo()` / `_add_to_plan()`
这几个取值函数。

生产环境里仍然是真的惰性 import（见桥的 module docstring），这里只换了取值函数。
"""

from __future__ import annotations

import pytest

from tests.clipboard_wait import wait_for_copy
from tests.qml_page_load import assert_page_loads_quietly, page_host

pytestmark = pytest.mark.ui

_JITA = 10000002
_CARD_KEYS = (
    ("mpi", "矿物指数 (MPI)"),
    ("pppi", "初级投入品 (PPPI)"),
    ("sppi", "次级投入品 (SPPI)"),
    ("cpi", "消费品 (CPI·代理)"),
    ("plex", "PLEX (ISK 锚)"),
)


# ════════════════════════════════════════════════════════════
#  替身：三个后端服务 + 两段「后端还没有的接口」的就地 SQL
# ════════════════════════════════════════════════════════════


class _FakeIndexService:
    """`services.market_index_service` 的替身（只用契约里的那几个函数）。"""

    JITA_RID = _JITA

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_index_cards(self, region_id: int = _JITA, _db=None) -> list[dict]:
        self.calls.append(("cards", region_id))
        return [
            {
                "key": key,
                "label": label,
                "value": 100.0 + index,
                # 首张卡今日 +1.25%：量价背离判据（涨）要靠它；其余也小涨，均值仍为正
                "chg1": 1.25 if index == 0 else 0.9,
                "chg7": -2.5,
                # 30 日缺数据 → 卡上必须显示 `—` 而不是 0
                "chg30": None,
                "chg90": 4.0,
                "chg180": None,
                "days": 29 - index,
                "base_date": "2026-09-07",
            }
            for index, (key, label) in enumerate(_CARD_KEYS)
        ]

    def get_index_series(self, keys=None, region_id: int = _JITA, _db=None) -> list[dict]:
        self.calls.append(("series", keys, region_id))
        # 7 个点：7 日均线的头部窗口要能算出来
        points = [{"date": f"2026-09-{day:02d}", "value": 100.0 + day * 0.5} for day in range(1, 8)]
        return [
            {
                "key": "mpi",
                "label": "矿物指数 (MPI)",
                "points": points,
                "members": [
                    {
                        "typeId": 34,
                        "name": "三钛合金",
                        "weight": 0.25,
                        "capped": True,
                        "price": 5.5,
                        "chg30": 12.5,
                        "source": "fixed",
                    },
                    {
                        "typeId": 35,
                        "name": "类晶体胶矿",
                        "weight": 0.125,
                        "capped": False,
                        "price": None,  # 该成员没有成交观测 → 页面显示 `—`
                        "chg30": None,
                        "source": "fixed",
                    },
                ],
            },
            {"key": "pppi", "label": "初级投入品 (PPPI)", "points": points, "members": []},
        ]

    def get_breadth(self, region_id: int = _JITA, _db=None) -> dict:
        self.calls.append(("breadth", region_id))
        return {"date": "2026-10-05", "advancers": 120, "decliners": 80, "unchanged": 5, "turnover": 4.0e9}

    def refresh_index_daily(self, region_id: int = _JITA) -> int:
        self.calls.append(("refresh", region_id))
        return 29


class _FakeMoversService:
    """`services.market_movers_service` 的替身。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_movers(
        self, days: int = 3, limit: int = 50, region_id: int = _JITA, qualified_only: bool = False, _db=None
    ):
        self.calls.append({"days": days, "limit": limit, "region_id": region_id, "qualified_only": qualified_only})
        return [
            {
                "typeId": 34,
                "name": "三钛合金",
                "price": 5.5,
                "chg": 25.0,
                "volume": 12000,
                "volume_ratio": 3.2,
                "qualified": True,
                "index_keys": ["mpi"],
            },
            {
                "typeId": 12345,
                "name": "某人炒作货",
                "price": 999.0,
                "chg": -40.0,
                "volume": 12,
                "volume_ratio": None,
                "qualified": False,
                "index_keys": [],
            },
            {
                # 薄市场 + 极端涨幅：实测「共和舰队热能涂层」3 天 +161843%（窗口里只有 1 笔成交）
                "typeId": 99001,
                "name": "单笔成交货",
                "price": 1.0e6,
                "chg": 161843.0,
                "volume": 3,
                "volume_ratio": 0.1,
                "qualified": False,
                "index_keys": [],
            },
            {
                # 反向极端：极小值也要夹住显示文本
                "typeId": 99002,
                "name": "暴跌货",
                "price": 5.0,
                "chg": -20000.0,
                "volume": 5000,
                "volume_ratio": 2.0,
                "qualified": False,
                "index_keys": [],
            },
        ]


class _FakeChainService:
    """`services.market_chain_service` 的替身。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_transmission_chain(self, type_id: int, depth: int = 2, region_id: int = _JITA, _db=None) -> list[dict]:
        self.calls.append((type_id, depth, region_id))
        return [
            {
                "level": 1,
                "parent_type_id": 12345,
                "typeId": 35,
                "name": "类晶体胶矿",
                "qty": 100,
                "price": 12.5,
                "cost_share": 0.75,
                "chg30": 4.5,
                "chg90": None,
                "chg180": -2.0,
                "not_caught_up": True,  # 上游涨了、这一环没跟上 → 页面高亮
                "source": "history",
            },
            {
                "level": 2,
                "parent_type_id": 35,
                "typeId": 36,
                "name": "类胶质",
                # 小数用量 / 缺成本占比 / 「未跟涨」算不出来（None，不是 False）/ 没有口径
                "qty": 250.5,
                "price": None,
                "cost_share": None,
                "chg30": None,
                "chg90": None,
                "chg180": None,
                "not_caught_up": None,
                "source": None,
            },
        ]


class _FakeAdviceService:
    """`services.market_advice_service` 的替身（只用 `get_trade_advice`）。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_trade_advice(self, type_id: int, region_id: int = _JITA, *, trend_30d=None, _db=None) -> dict:
        self.calls.append((int(type_id), int(region_id), trend_30d))
        return {
            "verdict": "two_sided",
            "buyAdvice": "买单挂 5.40 ISK（比最低卖单低 1.8%）",
            "sellAdvice": "卖单挂 5.60 ISK（排在当前最低卖单前面）",
            "reasons": ["价差 3.60% 高于来回费用 2.40%"],
            "caliber": "成交均价 · Jita",
            "spreadPct": 3.6,
            "roundTripFeePct": 2.4,
            "dayVolume": 12000.0,
            "orderVolume": 2705.0,
            "turnDays": 89.3,
        }


class _FakeWatchlistService:
    """`services.watchlist_manager` 的替身 —— **绝不**真写 user.db。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        #: 返回值：>0 = 写成功（或已存在），0 = 服务拒绝（用例据此断言失败文案）
        self.result = 1

    def add_to_watchlist(self, type_id: int, region_id: int = _JITA, note: str = "") -> int:
        self.calls.append((int(type_id), int(region_id)))
        return int(self.result)


class _FakeBlueprintRepo:
    """蓝图仓储替身：只有产物有制造蓝图，矿物（34 / 35）返回 `None`。"""

    #: 有制造蓝图的产物 type_id（替身里的「全市场异动」那几条）
    PRODUCTS = frozenset({12345, 99001, 99002})

    def __init__(self) -> None:
        self.calls: list[int] = []

    def get_blueprint_for_product(self, product_type_id: int, activity: str = "manufacturing") -> tuple | None:
        self.calls.append(int(product_type_id))
        return (2001, 1, 3600.0) if int(product_type_id) in self.PRODUCTS else None


class _FakeBackend:
    def __init__(self) -> None:
        self.index = _FakeIndexService()
        self.movers = _FakeMoversService()
        self.chain = _FakeChainService()
        self.advice = _FakeAdviceService()
        self.watchlist = _FakeWatchlistService()
        self.blueprint = _FakeBlueprintRepo()
        #: 落计划的替身记录（(type_id, name)）—— 真写 user.db 会污染用户数据
        self.plan_calls: list[tuple] = []


def _hub_rows() -> list[dict]:
    """各中心快照天数：Jita 够长、其余 6–9 天（计划 §6 的真实处境）。"""
    return [
        {"hub": "Jita", "days": 29, "last": "2026-10-05", "short": False},
        {"hub": "Amarr", "days": 6, "last": "2026-10-05", "short": True},
        {"hub": "Dodixie", "days": 6, "last": "2026-10-05", "short": True},
        {"hub": "Rens", "days": 5, "last": "2026-10-04", "short": True},
        {"hub": "Hek", "days": 5, "last": "2026-10-04", "short": True},
    ]


def _turnover_rows() -> list[dict]:
    """成交额环比 -20%：配合今日指数上涨，正好触发「量价背离」提示。"""
    return [{"date": "2026-10-04", "isk": 5.0e9}, {"date": "2026-10-05", "isk": 4.0e9}]


@pytest.fixture
def stubs(monkeypatch) -> _FakeBackend:
    """把后端服务与行右键写库的入口一起换成替身（页面测试不该碰真实 market/user.db）。"""
    import ui_qml.bridge.market_pulse_bridge as mpb

    backend = _FakeBackend()

    def _fake_add_to_plan(type_id: int, name: str) -> None:
        backend.plan_calls.append((int(type_id), str(name)))

    monkeypatch.setattr(mpb, "_index_service", lambda: backend.index)
    # 磁盘缓存与设置必须隔离：桥的 `__init__` 会先用**上次运行的整页缓存**铺首屏
    # （用户要的「点开就出数」），跑测试时那份缓存是真实数据、会把替身数据盖掉
    monkeypatch.setattr(mpb, "_load_cached_payload", lambda: {})
    monkeypatch.setattr(mpb, "_read_settings", lambda: {})
    monkeypatch.setattr(mpb, "_save_cached_payload", lambda payload: None)
    monkeypatch.setattr(mpb, "_write_settings", lambda payload: None)
    monkeypatch.setattr(mpb, "_movers_service", lambda: backend.movers)
    monkeypatch.setattr(mpb, "_chain_service", lambda: backend.chain)
    monkeypatch.setattr(mpb, "_advice_service", lambda: backend.advice)
    monkeypatch.setattr(mpb, "_watchlist_service", lambda: backend.watchlist)
    monkeypatch.setattr(mpb, "_blueprint_repo", lambda: backend.blueprint)
    monkeypatch.setattr(mpb, "_add_to_plan", _fake_add_to_plan)
    monkeypatch.setattr(mpb, "_hub_snapshot_rows", _hub_rows)
    monkeypatch.setattr(mpb, "_turnover_series", lambda region_id, days=30: _turnover_rows())
    return backend


# ════════════════════════════════════════════════════════════
#  桥层：一次装配全部区块
# ════════════════════════════════════════════════════════════


def test_bridge_assembles_cards_chart_movers_and_chain(qapp, stubs):
    """一次 `refresh()` 后各区块的数据装配（卡片/主图/广度/成员/异动/状态行/抽屉/行右键）。

    并成一条用例：它们共用同一次取数，拆开只会把同一份替身断言抄几遍。
    """
    import ui_qml.bridge.market_pulse_bridge as mpb
    from ui_qml.bridge.market_pulse_bridge import MarketPulseBridge

    bridge = MarketPulseBridge(None)
    # `refresh()` 现在走**后台线程**（用户口径：切页/重算不该阻塞主窗口），用例不等真线程，
    # 直接跑同一条「读 → 装配」路径：`_load_payload` 是 worker 里跑的那个读函数。
    bridge._on_loaded(mpb._load_payload(bridge._region_id()))

    # ── 指数卡 ×5：现值 + 五档涨跌，缺值 `—`（不是 0）──
    assert [card["key"] for card in bridge.cards] == [key for key, _ in _CARD_KEYS]
    assert bridge.cards[0]["label"] == "矿物指数 (MPI)"
    assert bridge.cards[0]["valueText"] == "100.00"
    assert [change["label"] for change in bridge.cards[0]["chgs"]] == ["今日", "7日", "30日", "90日", "180日"]
    assert bridge.cards[0]["chgs"][0] == {"label": "今日", "text": "+1.25%", "token": "ACCENT_GREEN"}
    assert bridge.cards[0]["chgs"][1]["text"] == "-2.50%"
    assert bridge.cards[0]["chgs"][1]["token"] == "ACCENT_RED"
    assert bridge.cards[0]["chgs"][2]["text"] == "—"
    assert bridge.cards[0]["chgs"][2]["token"] == "TEXT_SECONDARY"
    assert bridge.cards[0]["selected"] is False

    # ── 主图：五条线的 token + 原始点；横轴日期取最长那条 ──
    assert bridge.series[0]["label"] == "矿物指数 (MPI)"
    assert bridge.series[0]["token"] == "PRIMARY"
    assert bridge.series[1]["token"] == "ACCENT_CYAN"
    assert bridge.series[0]["points"][0] == {"x": 0, "y": 100.5}
    assert bridge.xLabels[0] == "09-01" and len(bridge.xLabels) == 7

    # 7 日均线开关：同一组线换成平滑序列（尾部窗口，末点 = 7 个点的均值）
    assert bridge.showMa7 is False
    assert bridge.displaySeries[0]["label"] == bridge.series[0]["label"]
    bridge.setShowMa7(True)
    assert bridge.showMa7 is True
    assert bridge.displaySeries[0]["label"] == "矿物指数 (MPI) 7日均线"
    assert bridge.displaySeries[0]["points"][-1]["y"] == pytest.approx(102.0)

    # ── 量价/广度：成交额 + 环比、涨跌家数、量价背离（价涨量跌）──
    assert "成交额" in bridge.turnoverText and "环比 -20.0%" in bridge.turnoverText
    assert bridge.advDeclText == "涨 120 / 跌 80 / 平 5"
    assert "量价背离" in bridge.divergenceText
    assert bridge.divergenceToken == "ACCENT_YELLOW"

    # ── 篮子成员表：默认第一条指数（没选卡时不能是空表）──
    assert bridge.selectedKey == ""
    assert [row["name"] for row in bridge.members] == ["三钛合金", "类晶体胶矿"]
    assert "矿物指数 (MPI)" in bridge.membersNote
    first = bridge.members[0]
    assert (first["weightText"], first["priceText"], first["chg30Text"]) == ("25.00%", "5.50", "+12.50%")
    assert first["capped"] is True
    assert first["sourceText"] == "固定篮子"  # 口径机器名翻成人读标签
    assert bridge.members[1]["priceText"] == "—"
    assert bridge.members[1]["chg30Token"] == "TEXT_SECONDARY"

    # 点卡切换选中 / 再点取消
    bridge.selectIndex("mpi")
    assert bridge.selectedKey == "mpi" and bridge.cards[0]["selected"] is True
    assert [row["name"] for row in bridge.members] == ["三钛合金", "类晶体胶矿"]
    bridge.selectIndex("pppi")
    assert bridge.members == [] and "暂无成分数据" in bridge.membersNote
    bridge.selectIndex("pppi")
    assert bridge.selectedKey == ""

    # ── 异动榜两区：按 `qualified` 分；指数 key 翻成 label ──
    assert [row["name"] for row in bridge.qualifiedMovers] == ["三钛合金"]
    assert bridge.qualifiedMovers[0]["indexText"] == "矿物指数 (MPI)"
    assert (bridge.qualifiedMovers[0]["volumeText"], bridge.qualifiedMovers[0]["ratioText"]) == ("12,000", "3.2×")
    assert bridge.qualifiedMovers[0]["thin"] is False
    assert [row["name"] for row in bridge.marketMovers] == ["某人炒作货", "单笔成交货", "暴跌货"]
    assert bridge.marketMovers[0]["indexText"] == "—"
    assert bridge.marketMovers[0]["ratioText"] == "—"
    assert [row["thin"] for row in bridge.marketMovers] == [False, True, False]
    # 极端涨幅只夹**显示文本**：`>+9999%` 这种数字在界面上像 bug（真值仍在 `chg` 上）
    extreme_up = bridge.marketMovers[1]
    assert (extreme_up["chgText"], extreme_up["chg"]) == (">+9999%", 161843.0)
    assert extreme_up["chgToken"] == "ACCENT_GREEN"
    extreme_down = bridge.marketMovers[2]
    assert (extreme_down["chgText"], extreme_down["chg"]) == ("<-9999%", -20000.0)
    assert "窗口 3 天" in bridge.moversNote
    # 后端按契约收 kwargs（区域/窗口/上限/只看合格）
    assert stubs.movers.calls == [{"days": 3, "limit": 50, "region_id": _JITA, "qualified_only": False}]

    # ── 数据状态行：Jita 够长、其余标黄并写明 ──
    assert bridge.statusRows[0]["text"] == "Jita：29 天 · 最后 2026-10-05"
    assert bridge.statusRows[0]["token"] == "TEXT_SECONDARY"
    assert bridge.statusRows[1]["token"] == "ACCENT_YELLOW"
    assert "只用 Jita" in bridge.statusHint and "Amarr 6 天" in bridge.statusHint

    # ── 抽屉：点异动行 → 传导链（层级/用量/成本占比/三档涨跌/未跟涨/口径）──
    assert bridge.detailOpen is False
    bridge.openMover("market", 0)
    assert stubs.chain.calls == [(12345, 2, _JITA)]
    assert bridge.detailOpen is True and bridge.detailTitle == "某人炒作货"
    assert "2 行" in bridge.detailStatus and "成交均价" in bridge.detailStatus

    caught = bridge.detailRows[0]
    assert caught["level"] == 1 and caught["notCaughtUp"] is True
    assert (caught["qtyText"], caught["costShareText"], caught["chg30Text"]) == ("100", "75.00%", "+4.50%")
    assert caught["chg30Token"] == "ACCENT_GREEN" and caught["chg180Token"] == "ACCENT_RED"
    assert caught["sourceText"] == "成交均价"

    missing = bridge.detailRows[1]
    # 小数用量保留两位；缺的成本占比/口径显示 `—`；`not_caught_up=None` 不能当「已跟涨」
    assert missing["qtyText"] == "250.50"
    assert (missing["costShareText"], missing["sourceText"]) == ("—", "—")
    assert missing["notCaughtUp"] is False

    bridge.closeDetail()
    assert bridge.detailOpen is False and bridge.detailRows == []
    bridge.openMover("qualified", 99)  # 越界行：不动抽屉、不抛
    assert bridge.detailOpen is False

    # ── 篮子成员行也能点开**同一个**抽屉（用户：每行物品都要能点出挂单建议）──
    bridge.openMember(0)  # 成员表第一行：三钛合金
    assert stubs.chain.calls[-1] == (34, 2, _JITA)
    assert bridge.detailOpen is True and bridge.detailTitle == "三钛合金"
    # 挂单建议一并装配（替身记下传进去的 type_id / 区域 / 大盘方向）
    assert stubs.advice.calls[-1] == (34, _JITA, None)
    assert bridge.advice["verdict"] == "two_sided" and bridge.advice["title"] == "两侧挂单划算"
    assert bridge.advice["metrics"][0] == {"label": "价差（卖−买）", "value": "+3.60%"}
    assert "2 行" in bridge.detailStatus and "成交均价" in bridge.detailStatus
    bridge.openMember(99)  # 越界行：不动抽屉、不抛
    assert bridge.detailOpen is True
    bridge.closeDetail()

    # ── 行右键三个动作（全走替身：不真写 user.db、不真建计划）──
    # 复制名称：剪贴板拿到物品名（剪贴板是异步的，等一等，见 tests/clipboard_wait.py）
    assert wait_for_copy(lambda: bridge.copyName("market", 0), "某人炒作货") == "某人炒作货"
    assert bridge.statusText == "已复制名称：某人炒作货"

    # 加入关注列表：替身记下传进去的 type_id + 区域
    bridge.addToWatchlist("market", 0)
    assert stubs.watchlist.calls == [(12345, _JITA)]
    assert bridge.statusText == "已加入关注列表：某人炒作货"
    # 服务拒绝（返回 0）时状态栏必须说清原因，不能静默失败
    stubs.watchlist.result = 0
    bridge.addToWatchlist("member", 1)  # 类晶体胶矿
    assert stubs.watchlist.calls[-1] == (35, _JITA)
    assert "加入关注列表失败" in bridge.statusText and "类晶体胶矿" in bridge.statusText
    bridge.addToWatchlist("member", 99)  # 越界行：不调服务
    assert stubs.watchlist.calls[-1] == (35, _JITA)

    # 加入制造列表：先查蓝图（是不是产物），再落计划 —— 替身记下 type_id
    bridge.addToPlan("market", 0)  # 某人炒作货（12345）：替身里有制造蓝图
    assert stubs.blueprint.calls[-1] == 12345
    assert stubs.plan_calls == [(12345, "某人炒作货")]
    assert "已加入制造列表" in bridge.statusText
    bridge.addToPlan("member", 0)  # 三钛合金（34）：矿物，服务侧没有制造蓝图
    assert stubs.blueprint.calls[-1] == 34
    assert stubs.plan_calls == [(12345, "某人炒作货")], "非产物不落库"
    assert "不是制造产物" in bridge.statusText and "三钛合金" in bridge.statusText

    # 外壳切页钩子（`ui_qml/monitor_page.py` 的转发器会调）：只重读本地数据，
    # **不**自动重算指数 —— 重算要聚合几十万行、且对 market.db 有真实写入副作用
    assert all(call[0] != "refresh" for call in stubs.index.calls)

    # TTL 契约（性能修复的核心）：整页读取实测约 11 秒，刚读完 60 秒内再切回本页
    # **不重复读**；过期后才真的去后台重读（这里只验它起了线程，不等读完）
    calls_before = len(stubs.index.calls)
    bridge.on_shown()
    assert len(stubs.index.calls) == calls_before
    bridge._loaded_at = 0.0
    bridge.refresh()
    assert bridge._loading is True and bridge._load_worker is not None
    bridge.shutdown()
    assert bridge._loading is False
    assert bridge.busy is False

    # 折线图时间粒度（用户口径：「我想看近 7 日或者近 30 天的，这个时间粒度没有筛选」）：
    # 默认拉满 180 天；切粒度**只切已加载的点**，不重读库
    assert bridge.rangeIndex == 3 and list(bridge.rangeLabels)[:2] == ["近 7 天", "近 30 天"]
    assert bridge.baseNote.startswith("基期")  # 图上必须写出「100 是从哪天开始」
    calls_after_shown = len(stubs.index.calls)
    bridge.setRangeIndex(1)
    assert bridge.rangeIndex == 1
    assert all(len(line["points"]) <= 30 for line in bridge.series)
    assert len(stubs.index.calls) == calls_after_shown  # 切粒度不重读
    assert "30 个交易日" in bridge.baseNote


# ════════════════════════════════════════════════════════════
#  页面层
# ════════════════════════════════════════════════════════════


@pytest.fixture
def pulse_page(qapp, stubs):
    from ui_qml.bridge.market_pulse_bridge import MarketPulseBridge

    with page_host("pages/MarketPulsePane.qml", MarketPulseBridge(None)) as pair:
        yield pair


def test_page_loads_and_is_quiet(pulse_page):
    """能加载 + 桥到位 + 不给 Qt 刷告警（共用实现见 `tests/qml_page_load.py`）。

    页面 `Component.onCompleted` 会调一次 `refresh()`，所以这一条同时覆盖了
    「五张卡 + 成员表 + 两个异动区 + 数据状态行都真的有数据时」的布局期告警
    （delegate 里引用不存在的角色、列宽函数与表头对不上都会在这里露出来）。
    """
    host, bridge = pulse_page
    assert_page_loads_quietly(host, bridge, key="pulse", size=(1280, 720))
