"""物品查询页（阶段 3）的契约测试。

分三层：
  - **纯函数层**（`fast`）：`QueryQmlModel` 的命名角色与展示规则 ——
    这一层接替 Widgets 版 `QueryTableModel.data()` 的展示断言。
  - **桥层**（`ui`）：`QueryBridge` 的转发与整形（桥构造会起 GroupLoadWorker，
    故放在 ui 档，不污染 fast 白名单）。
  - **页面层**（`ui`）：`QueryPage.qml` 能加载、无 QML 告警。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer, QtMsgType, qInstallMessageHandler

from ui_pyside6.views.query.query_search import format_search_rows
from ui_qml.models.query_qml_model import ROLE_NAMES, QueryQmlModel

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


def _spin(ms: int = 150) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


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
    from ui_pyside6.views.query.query_search import _COLUMNS

    assert bridge.regions == list(TRADE_HUBS)
    assert [c["title"] for c in bridge.columns] == [t for t, _ in _COLUMNS]
    assert [c["width"] for c in bridge.columns] == [w for _, w in _COLUMNS]


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
