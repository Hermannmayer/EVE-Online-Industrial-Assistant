"""物品查询页（阶段 3）的契约测试。

页面形态已按用户要求改成「**候选弹窗就是匹配清单**」：输入即列全部前缀匹配、
点一条直接出详情，**没有结果表格**。所以这一层不再有模型角色 / 展示规则 / 排序 /
右键菜单 / 复制的断言 —— 那套连代码一起删了（`query_model(s).py`）。

分两层：
  - **桥层**（`ui`）：`QueryBridge` 的候选整形、推送详情、区域同步。
    （候选本身的匹配口径在 `tests/test_ui_data_service.py`。）
  - **页面层**（`ui`）：`QueryPage.qml` 能加载、无 QML 告警、两态判据。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Qt

from tests.qml_click import spin as _spin
from tests.qml_page_load import assert_page_loads_quietly, page_host

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bridge(qapp):
    from ui_qml.bridge.query_bridge import QueryBridge

    b = QueryBridge(None)
    yield b


@pytest.mark.ui
def test_regions_come_from_the_shared_sources(bridge):
    """区域取自既有常量，不在桥里另抄一份。"""
    from core.constants import TRADE_HUBS

    assert bridge.regions == list(TRADE_HUBS)


@pytest.mark.ui
def test_region_index_round_trips(bridge):
    assert bridge.regionIndex == 0
    bridge.setRegionIndex(1)
    assert bridge.regionIndex == 1
    bridge.setRegionIndex(999)  # 越界忽略
    assert bridge.regionIndex == 1


class _Recorder:
    """假详情桥：只记录被推了什么，用来验证 `QueryBridge → detail` 的驱动时序。

    真桥会跑 5 次取价 + 精炼 + BOM 展开，测试不该为「有没有被调」付这个代价。
    """

    def __init__(self) -> None:
        self.items: list[tuple[int, str]] = []
        self.cleared = 0
        self.hubs: list[int] = []
        self.order_reloads = 0

    def setItem(self, type_id: int, name: str) -> None:
        self.items.append((type_id, name))

    def clear(self) -> None:
        self.cleared += 1

    def setPriceHubIndex(self, index: int) -> None:
        self.hubs.append(index)

    def reloadOrders(self) -> None:
        self.order_reloads += 1


@pytest.mark.ui
def test_sub_bridges_are_built_lazily(bridge):
    """构造桥**不得**拉起子桥：它们会 import workers/services，短命桥会让 pytest 卡退出。"""
    assert bridge._detail_bridge is None
    assert bridge._dash_bridge is None


@pytest.mark.ui
def test_picking_a_candidate_pushes_it_straight_to_the_detail(bridge):
    """点候选 = 直接出详情（页面已经没有「搜索」这一步，也没有结果表）。

    `_show_detail` 走的是同一个子桥，所以这里换成记录桩就能验「推了什么」。
    """
    rec = _Recorder()
    bridge._detail_bridge = rec
    bridge._on_suggestions([(17715, "毒蜥级", "毒蜥级")])

    bridge.pickSuggestion("毒蜥级")

    assert rec.items == [(17715, "毒蜥级")], "候选带 type_id，应当直接推给详情桥"
    assert bridge.suggestions == [], "选中后候选要收起"
    assert bridge.searchText == "毒蜥级"


@pytest.mark.ui
def test_picking_a_candidate_uses_the_searchable_string(bridge):
    """候选的**展示串**与**查询串**是分开的两个字段，不能合并成一个。

    回归背景（用户实测「点候选后永远未找到物品」）：展示串曾形如
    `[17715] 毒蜥级 (Gila)`（带 Type ID 与中英双名）。现在展示串已简化成纯物品名
    （两者恰好同值），但这条分离仍是**契约**：展示串以后怎么改都不该影响
    送给详情桥的那一串。
    """
    rec = _Recorder()
    bridge._detail_bridge = rec
    bridge._on_suggestions([(17715, "[17715] 毒蜥级 (Gila)", "毒蜥级")])
    assert bridge.suggestions[0]["query"] == "毒蜥级", "候选要同时带上可搜的查询串"

    bridge.pickSuggestion("[17715] 毒蜥级 (Gila)")

    assert rec.items == [(17715, "毒蜥级")], "推给详情桥的必须是可搜的那串，不是展示串"
    assert bridge.searchText == "毒蜥级"


@pytest.mark.ui
def test_picking_a_history_entry_refetches_suggestions(bridge):
    """历史项是**裸查询词**、没有 type_id → 填回输入框并重新拉候选。

    历史里存的词可能对应多件物品（比如「毒蜥级」同时命中船、蓝图、涂装），
    替用户猜一件不如把候选重新摆出来让他选。
    """
    fetched: list[int] = []
    bridge._fetch_suggestions = lambda: fetched.append(1)

    bridge.pickSuggestion("三钛合金")

    assert bridge.searchText == "三钛合金"
    assert fetched == [1], "历史项要走重新拉候选那条路"
    assert bridge._detail_bridge is None, "历史项不该直接推详情"


@pytest.mark.ui
def test_clear_clears_the_query_and_the_detail(bridge):
    rec = _Recorder()
    bridge._detail_bridge = rec

    bridge.clear()

    assert rec.cleared == 1, "清空要连带把详情面板请回仪表盘"
    assert bridge.searchText == ""
    assert bridge.statusText == "已清空"


@pytest.mark.ui
def test_region_change_resyncs_detail_hub_and_orders(bridge):
    """换区域：详情桥的价格中心跟着走（下标取自 `TRADE_HUBS`），订单按新区域重取。

    精炼与材料由 `setPriceHubIndex` 自己重算，这里只需补订单 —— 它的 region 是从
    价格中心推出来的。
    """
    rec = _Recorder()
    bridge._detail_bridge = rec

    bridge.setRegionIndex(2)

    assert rec.hubs == [2]
    assert rec.order_reloads == 1


@pytest.mark.ui
def test_occupancy_delegate_guards_model_data(qapp):
    """静态护栏：`OccupancyPanel` 的 delegate 必须**防着 `modelData` 为 null**。

    真窗口实测踩过：`height: ... modelData.lines.length ...` 在 `modelData` 尚未注入的
    那一刻抛 `TypeError`，而 QML 对绑定错误是**静默**的 —— `height` 停在 0，
    整块「每人物一块」一个都不画（面板空着、汇总却说「2 人物」，且控制台无任何报错）。
    离屏快照看不出来（离屏下 `QFontDatabase` 为 0，本来就不看字形），必须真窗口才会现形。

    这条守的是「形状」而不是像素：只要 delegate 里出现 `modelData.lines`，
    就必须写成带 `modelData &&` 的守卫形式。
    """
    src = (_ROOT / "ui_qml" / "qml" / "pages" / "query" / "OccupancyPanel.qml").read_text(encoding="utf-8")
    assert "modelData && charBlock.modelData.lines" in src, (
        "delegate 的 lines 绑定缺少 modelData 空值守卫 —— 真窗口下会静默画不出任何人"
    )


@pytest.mark.ui
def test_page_declares_the_query_panel_import(qapp):
    """静态守卫：页面必须 import 面板所在目录。

    QML 只按同目录解析本地类型 —— 少了这行 `import "query"`，整页加载失败、
    外壳把本页记为「暂缺」（实测踩过）。这是**加载期契约**，与面板内部怎么起名无关，
    所以只守这一条；两态的渲染与切换由 `test_query_dashboard` 的交互用例覆盖。
    """
    text = (_ROOT / "ui_qml" / "qml" / "pages" / "QueryPage.qml").read_text(encoding="utf-8")
    assert 'import "query"' in text, 'QueryPage.qml 少了 `import "query"`，整页会加载失败'


@pytest.mark.ui
def test_query_panels_all_exist():
    """面板文件一个都不能少 —— 缺一个就是「整页加载失败、本页暂缺」。"""
    panel_dir = _ROOT / "ui_qml" / "qml" / "pages" / "query"
    expected = {
        "QueryDashboard.qml",
        "QueryDetailPane.qml",
        "OccupancyPanel.qml",
        "AssetChartPanel.qml",
        "OpenOrdersPanel.qml",
        "HubPricePanel.qml",
        "OrderPanel.qml",
        "RefinePanel.qml",
        "MaterialPanel.qml",
    }
    missing = sorted(name for name in expected if not (panel_dir / name).exists())
    assert not missing, f"缺少面板文件：{missing}"


# ════════════════════════════════════════════════════════════
#  页面层
# ════════════════════════════════════════════════════════════


@pytest.fixture
def query_page(qapp):
    from ui_qml.bridge.query_bridge import QueryBridge

    with page_host("pages/QueryPage.qml", QueryBridge(None)) as pair:
        yield pair


@pytest.mark.ui
def test_page_loads_and_is_quiet(query_page):
    """能加载 + 桥到位 + 不给 Qt 刷告警（共用实现见 `tests/qml_page_load.py`）。"""
    host, bridge = query_page
    root = assert_page_loads_quietly(host, bridge, key="query", size=(1200, 700))
    assert root.findChild(QObject, "suggestPopup") is not None, "候选弹窗的 objectName 丢了"
    assert root.findChild(QObject, "searchInput") is not None, "搜索框的 objectName 丢了"


@pytest.mark.ui
def test_idle_judgement_is_the_selected_item_and_not_busy():
    """两态判据 = 详情桥有没有拿到物品（`detail.typeId > 0`），且**不能带 `busy`**。

    判据带 `busy` 的实测症状（用户报的「两个界面来回抢显示」）：按候选查明细时
    `busy=true` 切到详情区、查完又切回仪表盘，一来一回翻两次。
    结果表删掉之后，「有没有结果」这个判据本身也不存在了 —— 只剩「有没有选中物品」。
    """
    text = (_ROOT / "ui_qml" / "qml" / "pages" / "QueryPage.qml").read_text(encoding="utf-8")
    m = re.search(r"readonly property bool idle:(.*?)QueryDashboard", text, re.S)
    assert m, "QueryPage.qml 里找不到 idle 判据（结构变了就同步改本条守卫）"
    judged = m.group(1)
    assert "detail.typeId" in judged, "两态判据应当是「详情桥有没有拿到物品」"
    assert "busy" not in judged, "idle 判据里出现了 busy —— 中间态会让界面来回翻两次"


@pytest.mark.ui
def test_page_has_no_results_table():
    """结果表已按用户要求删除：页面里不该再出现表格与那些已删的桥属性。

    这条是**反向守卫** —— 删掉的东西很容易在后续改动里被顺手加回来，
    而加回来不会报错（桥那边没有的属性和方法只会让绑定静默失败）。
    """
    text = (_ROOT / "ui_qml" / "qml" / "pages" / "QueryPage.qml").read_text(encoding="utf-8")
    for gone in ("TableView", "HorizontalHeaderView", "FTableClickArea", "countText", "rowMenu", "query.columns"):
        assert gone not in text, f"结果表删掉了，QueryPage.qml 里不该再有 `{gone}`"


def _write_history(monkeypatch, tmp_path, payload) -> None:
    """把历史文件换成一个临时文件（`load_search_history` 读的是模块级路径）。"""
    import json

    import core.search_history as sh

    hist = tmp_path / "history.json"
    hist.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sh, "HISTORY_FILE", hist)


@pytest.mark.ui
def test_history_shows_item_names_not_raw_records(bridge, monkeypatch, tmp_path):
    """历史项只显示**物品名**。

    回归背景：历史文件里存的是 `{"query": ..., "time": ...}` **字典**，而桥原先写的是
    `[str(h) for h in ...]` —— 整条 dict 连时间戳一起被渲染成历史项，
    用户看到的是 `{'query': '毒蜥级', 'time': 1758...}`。
    """
    _write_history(
        monkeypatch,
        tmp_path,
        [{"query": "毒蜥级", "time": 1758111111.0}, {"query": "三钛合金", "time": 1758222222.0}],
    )

    bridge.showHistory()
    assert bridge.history == ["毒蜥级", "三钛合金"]


@pytest.mark.ui
def test_history_skips_dirty_records(bridge, monkeypatch, tmp_path):
    """历史文件是用户可改的纯文本：非 dict / 缺 query / 空 query 一律跳过，不能连累整个弹窗。"""
    _write_history(
        monkeypatch,
        tmp_path,
        ["裸字符串", {"time": 1.0}, {"query": ""}, {"query": "渡鸦级"}],
    )

    bridge.showHistory()
    assert bridge.history == ["渡鸦级"]


@pytest.mark.ui
def test_show_history_clears_stale_suggestions(bridge, monkeypatch, tmp_path):
    """空框聚焦时若候选还留着上一次的内容，弹窗会显示旧候选而不是历史。"""
    _write_history(monkeypatch, tmp_path, [{"query": "毒蜥级", "time": 1.0}])
    bridge._on_suggestions([(17715, "毒蜥级", "毒蜥级")])
    assert bridge.suggestions != []

    bridge.showHistory()
    assert bridge.suggestions == []
    assert bridge.history == ["毒蜥级"]


@pytest.mark.ui
def test_reclicking_the_empty_search_box_reshows_history(query_page, monkeypatch, tmp_path):
    """空搜索框**反复点击**每次都要重新弹历史。

    回归背景（用户实测两轮才定位）：`suggestPopup.visible` 原先只由 `items.length > 0`
    这一个绑定驱动，而绑定只在**依赖值变化**时重算 —— 点外面 / Esc 关掉一次之后历史内容
    没变，`items.length` 也就不变，于是「只有第一次点击会弹出历史，之后怎么点都没反应」。

    用户补的关键线索：点输入框之后再去点本机窗口的其他地方，**输入框并不会丢焦点**，
    所以挂在 `onActiveFocusChanged` 上的那次修复对第二次点击完全无效。现在改由
    `onPressed` 显式 `open()`；本用例用**真实鼠标点击**（不是调方法），
    所以「挂错信号」这种接线错误也逃不掉。
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    host, bridge = query_page
    _write_history(monkeypatch, tmp_path, [{"query": "毒蜥级", "time": 1.0}])
    host.resize(1200, 800)
    host.show()
    _spin(250)

    root = host.rootObject()
    field = root.findChild(QObject, "searchInput")
    popup = root.findChild(QObject, "suggestPopup")
    assert field is not None, "搜索框的 objectName 丢了"
    assert popup is not None, "候选弹窗的 objectName 丢了"
    assert field.property("text") == ""

    asked: list[int] = []
    bridge.suggestionsChanged.connect(lambda: asked.append(1))

    origin = field.mapToItem(root, 0.0, 0.0)
    host_pt = root.mapToItem(None, origin.x(), origin.y())
    pt = QPoint(int(host_pt.x()) + int(field.width() / 2), int(host_pt.y()) + int(field.height() / 2))

    def click_field() -> None:
        QTest.mouseClick(host, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pt)
        _spin(150)

    click_field()
    assert len(asked) == 1, "第一次点击要问一次历史"
    assert popup.property("visible") is True, "第一次点击要弹出历史"

    click_field()
    assert field.property("activeFocus") is True, "这里正是用户报的关键：第二次点击时输入框仍持有焦点"
    assert len(asked) == 2, "第二次点击必须**重新问一次**历史 —— 挂在 onActiveFocusChanged 上只会问一次"
    assert popup.property("visible") is True, "第二次点击也要弹出历史"
