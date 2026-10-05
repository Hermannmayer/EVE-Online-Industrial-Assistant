"""市场大盘页（计划 `docs/dev/market-monitor-plan.md` §4.1）的契约测试。

分两层（与 `test_qml_watchlist.py` / `test_qml_trade.py` 同构）：

  - **桥层**：`MarketPulseBridge` 对三个后端服务的装配 —— 指数卡 / 主图（含 7 日均线）/
    量价广度（含量价背离）/ 篮子成员 / 异动榜两区 / 数据状态行 / 抽屉里的传导链；
  - **页面层**：`MarketPulsePane.qml` 能加载、无 QML 告警。

三个后端服务（`market_index_service` / `market_movers_service` / `market_chain_service`）
在这里**全部换替身**：本页与它们并行开发，替身让这两条用例既不依赖真实 `market.db`，
也不受那边接口微调影响 —— 桥对它们的唯一入口就是模块级的
`_index_service()` / `_movers_service()` / `_chain_service()` 三个取值函数。

生产环境里仍然是真的惰性 import（见桥的模块 docstring），这里只换了取值函数。
"""

from __future__ import annotations

import pytest

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


class _FakeBackend:
    def __init__(self) -> None:
        self.index = _FakeIndexService()
        self.movers = _FakeMoversService()
        self.chain = _FakeChainService()


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
    """把三个服务与两段就地 SQL 一起换成替身（页面测试不该碰真实 market.db）。"""
    import ui_qml.bridge.market_pulse_bridge as mpb

    backend = _FakeBackend()
    monkeypatch.setattr(mpb, "_index_service", lambda: backend.index)
    monkeypatch.setattr(mpb, "_movers_service", lambda: backend.movers)
    monkeypatch.setattr(mpb, "_chain_service", lambda: backend.chain)
    monkeypatch.setattr(mpb, "_hub_snapshot_rows", _hub_rows)
    monkeypatch.setattr(mpb, "_turnover_series", lambda region_id, days=30: _turnover_rows())
    return backend


# ════════════════════════════════════════════════════════════
#  桥层：一次装配全部区块
# ════════════════════════════════════════════════════════════


def test_bridge_assembles_cards_chart_movers_and_chain(qapp, stubs):
    """一次 `refresh()` 后各区块的数据装配（卡片/主图/广度/成员/异动/状态行/抽屉）。

    并成一条用例：它们共用同一次取数，拆开只会把同一份替身断言抄几遍。
    """
    from ui_qml.bridge.market_pulse_bridge import MarketPulseBridge

    bridge = MarketPulseBridge(None)
    bridge.refresh()

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

    # 外壳切页钩子（`ui_qml/monitor_page.py` 的转发器会调）：只重读本地数据，
    # **不**自动重算指数 —— 重算要聚合几十万行、且对 market.db 有真实写入副作用
    calls_before = len(stubs.index.calls)
    bridge.on_shown()
    assert len(stubs.index.calls) > calls_before
    assert all(call[0] != "refresh" for call in stubs.index.calls)
    assert bridge.busy is False


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
