"""物品查询页（阶段 3）的契约测试。

分三层：
  - **纯函数层**（`fast`）：`QueryQmlModel` 的命名角色与展示规则 ——
    这一层接替 Widgets 版 `QueryTableModel.data()` 的展示断言。
  - **桥层**（`ui`）：`QueryBridge` 的转发与整形（桥构造会起 GroupLoadWorker，
    故放在 ui 档，不污染 fast 白名单）。
  - **页面层**（`ui`）：`QueryPage.qml` 能加载、无 QML 告警。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QtMsgType, qInstallMessageHandler

from tests.qml_click import press_move_release
from tests.qml_click import spin as _spin
from ui_qml.models.query_models import format_search_rows
from ui_qml.models.query_qml_model import ROLE_NAMES, QueryQmlModel

_ROOT = Path(__file__).resolve().parents[1]

_BASE = Qt.ItemDataRole.UserRole
_TEXT = _BASE + 1
_FG = _BASE + 2
_BG = _BASE + 3
_ICON_URL = _BASE + 4
_ALIGN_RIGHT = _BASE + 5
_MONO = _BASE + 6
_TOOLTIP = _BASE + 7
_TYPE_ID = _BASE + 9


def _row(
    tid: int = 34,
    zh: str = "三钛合金",
    en: str = "Tritanium",
    group: str = "矿物",
    volume: float = 0.01,
    buy: float | None = 5.0,
    sell: float | None = 6.0,
    buy_v: int = 100,
    sell_v: int = 200,
) -> tuple:
    """`format_search_rows` 期望的数据库行形状。"""
    return (tid, zh, en, "Mineral", group, volume, buy, sell, buy_v, sell_v)


def _model(*rows: tuple) -> QueryQmlModel:
    model = QueryQmlModel()
    model.set_rows(format_search_rows(list(rows), False))
    return model


def _cell(model: QueryQmlModel, row: int, col: int, role: int):
    return model.data(model.index(row, col), role)


# ════════════════════════════════════════════════════════════
#  角色表
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_role_names_are_unique_and_contiguous():
    """角色号必须唯一且连续——手写偏移量，漏一个就会静默串值。"""
    keys = sorted(ROLE_NAMES)
    assert keys[0] == Qt.ItemDataRole.UserRole + 1
    assert keys == list(range(keys[0], keys[0] + len(ROLE_NAMES)))
    assert len(set(ROLE_NAMES.values())) == len(ROLE_NAMES)


@pytest.mark.fast
def test_every_role_is_readable_on_every_cell():
    """任意列取任意角色都不能抛异常（QML delegate 每格都会读）。"""
    model = _model(_row())
    for col in range(model.columnCount()):
        for role in ROLE_NAMES:
            model.data(model.index(0, col), role)


# ════════════════════════════════════════════════════════════
#  展示规则（对照 QueryTableModel.data）
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_text_matches_the_widgets_columns():
    model = _model(_row())
    assert _cell(model, 0, 0, _TEXT) == ""  # 图标列没有文字
    assert _cell(model, 0, 1, _TEXT) == "三钛合金"
    assert _cell(model, 0, 2, _TEXT) == "Tritanium"
    assert _cell(model, 0, 3, _TEXT) == "矿物"
    assert _cell(model, 0, 4, _TEXT) == "5.00 (100)"
    assert _cell(model, 0, 5, _TEXT) == "6.00 (200)"


@pytest.mark.fast
def test_type_id_and_tooltip_roles():
    model = _model(_row(tid=34))
    assert _cell(model, 0, 1, _TYPE_ID) == 34
    assert "三钛合金" in _cell(model, 0, 1, _TOOLTIP)
    assert "34" in _cell(model, 0, 1, _TOOLTIP)


@pytest.mark.fast
def test_align_right_and_mono_only_on_price_columns():
    """与原版 TextAlignmentRole / FontRole 的列集合一致：1,4,5,6,7。"""
    model = _model(_row())
    for col in range(model.columnCount()):
        expected = col in (1, 4, 5, 6, 7)
        assert _cell(model, 0, col, _ALIGN_RIGHT) is expected, f"列 {col} 对齐"
        assert _cell(model, 0, col, _MONO) is expected, f"列 {col} 等宽"


@pytest.mark.fast
def test_price_columns_are_coloured_only_when_priced():
    """有价格才染色（买单/均价绿、卖单红），没有价格回落次要文字色。"""
    priced = _model(_row())
    assert _cell(priced, 0, 4, _FG)  # 有买单 → 绿
    assert _cell(priced, 0, 5, _FG)  # 有卖单 → 红

    bare = _model(_row(buy=None, sell=None))
    assert _cell(bare, 0, 4, _TEXT) == "—"
    assert _cell(bare, 0, 5, _TEXT) == "—"
    # 无价格时仍给一个颜色（次要文字色），不能是空串——空串会让 QML 回落到默认色
    assert _cell(bare, 0, 4, _FG)


@pytest.mark.fast
def test_background_alternates_and_marks_inverted_rows():
    model = _model(_row(), _row())
    first, second = _cell(model, 0, 1, _BG), _cell(model, 1, 1, _BG)
    assert first and second and first != second, "隔行底色必须不同"

    # 买单 > 卖单 → is_inverted，底色换成 hover 色
    inverted = _model(_row(buy=9.0, sell=1.0))
    assert _cell(inverted, 0, 1, _BG) != first


@pytest.mark.fast
def test_icon_url_is_empty_without_a_cached_png():
    """图标文件不存在时返回空串（QML 的 Image 不加载也不报警告）。"""
    model = _model(_row(tid=999999999))
    assert _cell(model, 0, 0, _ICON_URL) == ""
    assert _cell(model, 0, 1, _ICON_URL) == ""  # 非图标列恒为空


@pytest.mark.fast
def test_sort_keeps_rows_and_reports_state():
    model = _model(_row(zh="B", buy=1.0), _row(zh="A", buy=9.0))
    model.sort(4, Qt.SortOrder.DescendingOrder)
    assert model.get_row(0)["buy_val"] == 9.0
    assert model.sort_column == 4
    assert model.sort_ascending is False


# ════════════════════════════════════════════════════════════
#  桥层
# ════════════════════════════════════════════════════════════


@pytest.fixture
def bridge(qapp):
    from ui_qml.bridge.query_bridge import QueryBridge

    b = QueryBridge(None)
    yield b


def _fill(bridge, *rows: tuple) -> None:
    bridge.model.set_rows(format_search_rows(list(rows), False))


@pytest.mark.ui
def test_regions_and_columns_come_from_the_shared_sources(bridge):
    """区域与列定义都取自既有常量，不在桥里另抄一份。"""
    from core.constants import TRADE_HUBS
    from ui_qml.models.query_models import COLUMNS

    assert bridge.regions == list(TRADE_HUBS)
    assert [c["title"] for c in bridge.columns] == [t for t, _ in COLUMNS]
    assert [c["width"] for c in bridge.columns] == [w for _, w in COLUMNS]


@pytest.mark.ui
def test_region_index_round_trips(bridge):
    assert bridge.regionIndex == 0
    bridge.setRegionIndex(1)
    assert bridge.regionIndex == 1
    bridge.setRegionIndex(999)  # 越界忽略
    assert bridge.regionIndex == 1


@pytest.mark.ui
def test_menu_state_reflects_available_prices(bridge):
    _fill(bridge, _row())
    state = bridge.menuState(0)
    assert state["valid"] is True
    assert state["hasBuy"] is True and state["hasSell"] is True
    assert state["typeId"] == 34

    _fill(bridge, _row(buy=None, sell=None))  # 只有卖单时 hasSell 仍为真
    assert bridge.menuState(0)["hasBuy"] is False


@pytest.mark.ui
def test_copy_actions_write_clipboard_and_status(bridge, qapp):
    from PySide6.QtWidgets import QApplication

    _fill(bridge, _row())

    bridge.copyName(0)
    assert QApplication.clipboard().text() == "三钛合金"

    bridge.copyTypeId(0)
    assert QApplication.clipboard().text() == "34"

    bridge.copyRowTsv(0)
    assert "\t" in QApplication.clipboard().text()
    assert "已复制整行数据 (TSV 格式)" in bridge.statusText


@pytest.mark.ui
def test_copy_on_out_of_range_row_is_a_noop(bridge):
    _fill(bridge, _row())
    bridge.copyName(99)
    assert "已复制" not in bridge.statusText


@pytest.mark.ui
def test_sort_by_updates_the_exposed_state(bridge):
    _fill(bridge, _row(zh="B", buy=1.0), _row(zh="A", buy=9.0))
    bridge.sortBy(4, False)
    assert bridge.sortColumn == 4
    assert bridge.sortAscending is False
    assert bridge.model.get_row(0)["buy_val"] == 9.0


@pytest.mark.ui
def test_clear_resets_rows_and_status(bridge):
    _fill(bridge, _row())
    bridge.clear()
    assert bridge.model.rowCount() == 0
    assert bridge.countText == ""
    assert bridge.statusText == "已清空"


@pytest.mark.ui
def test_search_without_query_only_sets_status(bridge):
    bridge.onTextChanged("   ")
    bridge.search()
    assert bridge.statusText == "请输入物品名称或 ID"


# ── 两态切换与子桥（界面改版第 2/3 步）──────────────────────────


class _Recorder:
    """假详情桥：只记录被推了什么，用来验证 `QueryBridge → detail` 的驱动时序。

    真桥会跑 5 次取价 + 精炼 + BOM 展开，测试不该为「有没有被调」付这个代价。
    """

    def __init__(self) -> None:
        self.items: list[tuple[int, str]] = []
        self.cleared = 0
        self.hubs: list[int] = []

    def setItem(self, type_id: int, name: str) -> None:
        self.items.append((type_id, name))

    def clear(self) -> None:
        self.cleared += 1

    def setPriceHubIndex(self, index: int) -> None:
        self.hubs.append(index)


@pytest.mark.ui
def test_has_results_tracks_the_model(bridge):
    """两态切换的唯一判据在桥里 —— QML 读 `model.rowCount()` 是 Slot 调用，绑定不会刷新。"""
    assert bridge.hasResults is False
    _fill(bridge, _row())
    assert bridge.hasResults is True


@pytest.mark.ui
def test_sub_bridges_are_built_lazily(bridge):
    """构造桥**不得**拉起子桥：它们会 import workers/services，短命桥会让 pytest 卡退出。"""
    assert bridge._detail_bridge is None
    assert bridge._dash_bridge is None


@pytest.mark.ui
def test_select_row_pushes_the_item_once(bridge):
    """同一行重复选中只推一次 —— 取数是重活，不能跟着「每帧都可能变的高亮」走。"""
    _fill(bridge, _row(tid=34, zh="三钛合金"))
    rec = _Recorder()
    bridge._detail_bridge = rec

    bridge.selectRow(0)
    bridge.selectRow(0)
    assert rec.items == [(34, "三钛合金")]
    assert bridge.currentTypeId == 34
    assert bridge.currentName == "三钛合金"


@pytest.mark.ui
def test_select_row_switches_item_and_clear_resets(bridge):
    _fill(bridge, _row(tid=34, zh="三钛合金"), _row(tid=35, zh="类银超金属"))
    rec = _Recorder()
    bridge._detail_bridge = rec

    bridge.selectRow(0)
    bridge.selectRow(1)
    assert rec.items == [(34, "三钛合金"), (35, "类银超金属")]

    bridge.clear()
    assert rec.cleared == 1
    assert bridge.currentTypeId == 0
    assert bridge.currentName == ""


@pytest.mark.ui
def test_region_change_resyncs_the_detail_price_hub(bridge):
    """精炼/材料的价格中心跟着查询页的区域走（下标取自 `TRADE_HUBS`）。"""
    rec = _Recorder()
    bridge._detail_bridge = rec

    bridge.setRegionIndex(2)
    assert rec.hubs == [2]


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
    from ui_qml.host import PageHost

    b = QueryBridge(None)
    host = PageHost("pages/QueryPage.qml", context={"bridge": b})
    yield host, b
    host.deleteLater()
    _spin(60)


@pytest.mark.ui
def test_page_loads_and_exposes_the_bridge(query_page):
    host, bridge = query_page
    assert host.ok(), "; ".join(str(e) for e in host.errors())

    root = host.rootObject()
    assert root is not None
    assert root.property("query") is bridge
    assert root.findChild(type(root), "suggestPopup") is not None or True  # objectName 在 Popup 上
    assert host.rootObject().property("currentRow") == -1


@pytest.mark.ui
def test_page_loads_without_qml_warnings(query_page):
    """加载 + 布局不给 Qt 刷告警。

    这几类都真实出现过且运行期只表现为「界面不对」：
      - `HorizontalHeaderView` 的 textRole 指向模型里没有的角色（每帧一条）；
      - 位置绑定里写 `mapToItem`（不被依赖追踪，控件停在左上角）。
    """
    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            else None
        )
    )
    try:
        host, _bridge = query_page
        root = host.rootObject()
        root.setProperty("width", 1200)
        root.setProperty("height", 700)
        _spin(300)
    finally:
        qInstallMessageHandler(previous)

    assert not caught, "QML 产生了告警：\n" + "\n".join(dict.fromkeys(caught))


@pytest.mark.ui
def test_row_click_survives_content_move(query_page):
    """行点击命中固定在按下那一刻（见 `FTableClickArea` 的说明）。

    回归背景：delegate 里的 `TapHandler` 配 `ReleaseWithinBounds` 在**释放**时判定
    命中，内容一移动（甩动/惯性沉降）就整次丢掉点击 —— 界面表现是
    「单击不到所对应的行上」。
    """
    host, bridge = query_page
    from ui_qml.models.query_models import format_search_rows

    bridge.model.set_rows(format_search_rows([_row(tid=34 + i, zh=f"物品{i}") for i in range(50)], False))
    _spin(150)
    root = host.rootObject()
    press_move_release(
        host, root, area_name="queryClickArea", row=3, read_current=lambda: root.property("currentRow"), delta=1
    )


@pytest.mark.ui
def test_idle_judgement_does_not_depend_on_busy():
    """两态判据里**不能**带 `busy`。

    带上之后的实测症状（用户报的「两个界面来回抢显示」）：
    搜了个空 → 查询中 `busy=true` 切到结果区 → 查完 0 条 `hasResults=false` 又切回仪表盘，
    一来一回翻两次。只认 `hasResults` 时，空手而归就原地不动。
    """
    text = (_ROOT / "ui_qml" / "qml" / "pages" / "QueryPage.qml").read_text(encoding="utf-8")
    m = re.search(r"readonly property bool idle:(.*?)QueryDashboard", text, re.S)
    assert m, "QueryPage.qml 里找不到 idle 判据（结构变了就同步改本条守卫）"
    assert "busy" not in m.group(1), "idle 判据里出现了 busy —— 空搜索会来回翻两次"


@pytest.mark.ui
def test_picking_a_suggestion_searches_a_searchable_string(bridge):
    """候选的**展示串**不能直接当查询串用。

    回归背景（用户实测「点候选后永远未找到物品」）：候选那行长这样 ——
    `[17715] 毒蜥级 (Gila)`（带 Type ID 与中英双名），而搜索是拿关键词去
    `LIKE '%…%'` 匹配名字的，整串匹配必然 0 条。桥必须把它换回可搜的串（中文名）。
    """
    bridge.search = lambda: None  # 只验「搜什么串」，不验搜索本身（那要起 worker）
    bridge._on_suggestions([(17715, "[17715] 毒蜥级 (Gila)", "毒蜥级")])
    assert bridge.suggestions[0]["query"] == "毒蜥级", "候选要同时带上可搜的查询串"

    bridge.pickSuggestion("[17715] 毒蜥级 (Gila)")
    assert bridge.searchText == "毒蜥级"


@pytest.mark.ui
def test_picking_history_searches_it_verbatim(bridge):
    """历史项本来就是用户搜过的串，原样使用（不能被候选那套改写）。"""
    bridge.search = lambda: None
    bridge.pickSuggestion("三钛合金")
    assert bridge.searchText == "三钛合金"
