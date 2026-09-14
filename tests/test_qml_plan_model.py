"""`PlanQmlModel` / `PlanTableBridge` 契约测试。

对应阶段 2a：生产计划表从 Widgets 迁到 QML 后，原 `plan_table_delegate.py`
的**展示规则**（染色/图标/勾选/折叠）搬进了模型的命名角色，本文件接替
`tests/test_industry_view.py` 与 `tests/test_industry_dialogs.py` 里那批
针对 delegate 的断言。

多数用例不依赖 QApplication：颜色 token 与图标 URL 都是纯字符串计算。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

import ui_pyside6.theme as theme
from ui_pyside6.views.industry.plan_table_constants import (
    COL_BLUEPRINT,
    COL_CATEGORY,
    COL_ICON,
    COL_PRODUCT,
    COL_PROFIT,
    COL_STATUS,
)
from ui_qml.models.plan_qml_model import ROLE_NAMES, PlanQmlModel

_TEXT = Qt.ItemDataRole.UserRole + 1
_FG = Qt.ItemDataRole.UserRole + 2
_BG = Qt.ItemDataRole.UserRole + 3
_ICON_URL = Qt.ItemDataRole.UserRole + 4
_CHECKED = Qt.ItemDataRole.UserRole + 5
_EDITABLE = Qt.ItemDataRole.UserRole + 6
_STATUS_KEY = Qt.ItemDataRole.UserRole + 7
_FOLD_STATE = Qt.ItemDataRole.UserRole + 9
_TOOLTIP = Qt.ItemDataRole.UserRole + 11


def _plan(**kw) -> dict:
    base = {
        "product_type_id": 621,
        "product_name": "狂怒级",
        "category": "manufacturing",
        "status": "pending",
        "runs": 3,
        "parallels": 1,
    }
    base.update(kw)
    return base


def _cell(model: PlanQmlModel, row: int, col: int, role: int):
    return model.data(model.index(row, col), role)


# ════════════════════════════════════════════════════════════
#  角色表
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_role_names_are_unique_and_contiguous():
    """角色号必须唯一且连续——手写偏移量，漏一个就会静默串值。"""
    keys = sorted(ROLE_NAMES)
    assert keys[0] == Qt.ItemDataRole.UserRole + 1
    assert keys == list(range(keys[0], keys[0] + len(keys)))
    assert len(set(ROLE_NAMES.values())) == len(ROLE_NAMES)


@pytest.mark.fast
def test_all_roles_return_something_for_a_plain_row():
    """任意列取任意角色都不能抛异常（QML delegate 每格都会读）。"""
    model = PlanQmlModel([_plan()])
    for col in range(model.columnCount()):
        for role in ROLE_NAMES:
            model.data(model.index(0, col), role)


# ════════════════════════════════════════════════════════════
#  前景色（原 PlanTableDelegate._foreground）
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_profit_positive_is_green_negative_is_red_zero_is_default():
    model = PlanQmlModel(
        [
            _plan(profit=1_000.0),
            _plan(profit=-1_000.0),
            _plan(profit=0.0),
        ]
    )
    assert _cell(model, 0, COL_PROFIT, _FG) == theme.GREEN
    assert _cell(model, 1, COL_PROFIT, _FG) == theme.RED
    assert _cell(model, 2, COL_PROFIT, _FG) == "", "利润为零不应染色"


@pytest.mark.fast
@pytest.mark.parametrize(
    ("status", "expected_token"),
    [
        ("completed", "GREEN"),
        ("done", "GREEN"),
        ("in_progress", "PRIMARY"),
        ("running", "PRIMARY"),
        ("ready", "ACCENT_ORANGE"),
        ("pending", "TEXT_SECONDARY"),
    ],
)
def test_status_column_colors(status: str, expected_token: str):
    model = PlanQmlModel([_plan(status=status)])
    assert _cell(model, 0, COL_STATUS, _FG) == getattr(theme, expected_token)


@pytest.mark.fast
def test_ready_status_column_keeps_status_key_for_the_button():
    """状态列的「待下线」在 QML 里画成按钮，靠 `statusKey` 判定。"""
    model = PlanQmlModel([_plan(status="READY")])
    assert _cell(model, 0, COL_STATUS, _STATUS_KEY) == "ready", "statusKey 必须小写归一"


@pytest.mark.fast
def test_blueprint_shortfall_is_red_until_completed():
    short = _plan(status="pending", bound_blueprint_ids=[1], need_blueprints=3)
    ok = _plan(status="pending", bound_blueprint_ids=[1, 2, 3], need_blueprints=3)
    done = _plan(status="completed", bound_blueprint_ids=[], need_blueprints=3)
    model = PlanQmlModel([short, ok, done])
    assert _cell(model, 0, COL_BLUEPRINT, _FG) == theme.ACCENT_RED
    assert _cell(model, 1, COL_BLUEPRINT, _FG) == ""
    assert _cell(model, 2, COL_BLUEPRINT, _FG) == "", "已完成的计划不再标红"


# ════════════════════════════════════════════════════════════
#  类别染色 / 图标
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
@pytest.mark.parametrize("category", ["copying", "invention", "reaction"])
def test_category_tint_is_translucent(category: str):
    """类别底色必须带透明度。

    旧 Widgets 版把类别色当 100% 饱和的整行底色，文字压在上面读不出来
    （实测绿底上的「生产中」）；这里锁死 alpha < 255，防止回归。
    """
    model = PlanQmlModel([_plan(category=category)])
    tint = _cell(model, 0, 4, _BG)
    assert tint.startswith("#"), f"{category} 应有底色，实得 {tint!r}"
    assert len(tint) == 9, f"应为 #AARRGGBB，实得 {tint!r}"
    assert QColor(tint).alpha() < 255, "类别底色必须半透明"


@pytest.mark.fast
def test_manufacturing_has_no_tint():
    """制造（默认类别）不染色——旧实现只给复制/发明/反应上色。"""
    model = PlanQmlModel([_plan(category="manufacturing")])
    assert _cell(model, 0, 4, _BG) == ""


@pytest.mark.fast
@pytest.mark.parametrize("category", ["manufacturing", "copying", "invention", "reaction"])
def test_category_icon_url_goes_through_phosphor_provider(category: str):
    """QML 拿到的是 image://phosphor/... 而不是 file:// —— 原始 SVG 未染色。

    （Phosphor 的 fill 写在 <svg> 根上，QML 的 Image 不会继承给 <path>。）
    """
    model = PlanQmlModel([_plan(category=category)])
    url = _cell(model, 0, COL_CATEGORY, _ICON_URL)
    assert url.startswith("image://phosphor/"), url
    assert "?c=%23" in url, f"颜色必须以 #rrggbb 形式编进查询串，实得 {url!r}"


@pytest.mark.fast
def test_unknown_category_has_no_icon():
    model = PlanQmlModel([_plan(category="not_a_category")])
    assert _cell(model, 0, COL_CATEGORY, _ICON_URL) == ""


@pytest.mark.fast
def test_level_arrow_only_for_child_rows():
    """子项在产品列显示层级箭头，母项不显示。"""
    model = PlanQmlModel([_plan(child_level=0), _plan(child_level=1)])
    assert _cell(model, 0, COL_PRODUCT, _ICON_URL) == ""
    assert "caret-right" in _cell(model, 1, COL_PRODUCT, _ICON_URL)


@pytest.mark.fast
def test_missing_item_icon_file_yields_empty_url():
    """不存在的 type_id 给空串——QML 的 Image 拿到空串不加载也不刷警告。"""
    model = PlanQmlModel([_plan(product_type_id=999_999_999)])
    assert _cell(model, 0, COL_ICON, _ICON_URL) == ""


# ════════════════════════════════════════════════════════════
#  勾选 / 折叠 / 可编辑
# ════════════════════════════════════════════════════════════


@pytest.mark.fast
def test_checked_role_tracks_materials_ready():
    model = PlanQmlModel([_plan(materials_ready=1), _plan(materials_ready=0)])
    assert _cell(model, 0, 0, _CHECKED) is True
    assert _cell(model, 1, 0, _CHECKED) is False


@pytest.mark.fast
def test_fold_state_marks_only_parents_with_children():
    plans = [
        _plan(group_id=7, child_level=0),
        _plan(group_id=7, child_level=1),
        _plan(group_id=9, child_level=0),  # 组 9 无子项
    ]
    model = PlanQmlModel(plans)
    assert _cell(model, 0, COL_PRODUCT, _FOLD_STATE) == "expanded"
    assert _cell(model, 1, COL_PRODUCT, _FOLD_STATE) == "", "子项本身不可折叠"
    assert _cell(model, 2, COL_PRODUCT, _FOLD_STATE) == "", "无子项的母项不可折叠"

    model.toggle_collapse(7)
    assert _cell(model, 0, COL_PRODUCT, _FOLD_STATE) == "collapsed"


@pytest.mark.fast
def test_product_text_drops_the_fold_glyph():
    """折叠图标改由 QML 画，文本角色不能再带 ▼/▶（否则会画两遍）。"""
    model = PlanQmlModel([_plan(group_id=7, child_level=0), _plan(group_id=7, child_level=1)])
    assert _cell(model, 0, COL_PRODUCT, _TEXT) == "狂怒级"


@pytest.mark.fast
def test_editable_role_matches_model_editable_columns():
    from ui_pyside6.models.industry_models import PlanTableModel

    model = PlanQmlModel([_plan(status="pending")])
    for col in range(model.columnCount()):
        expected = col in PlanTableModel._EDITABLE_COLS
        assert _cell(model, 0, col, _EDITABLE) is expected, f"列 {col} 可编辑性不符"


@pytest.mark.fast
def test_completed_rows_are_not_editable():
    model = PlanQmlModel([_plan(status="completed")])
    notes_col = 4
    assert _cell(model, 0, notes_col, _EDITABLE) is False


@pytest.mark.fast
def test_blueprint_tooltip_only_when_line_levels_differ():
    """逐线 ME/TE 不一致时蓝图列才给 tooltip（旧 `_levels_tooltip` 的行为）。"""
    same = _plan(me_level=10, te_level=20, line_levels=[(10, 20), (10, 20)])
    mixed = _plan(me_level=10, te_level=20, line_levels=[(10, 20), (8, 18)])
    model = PlanQmlModel([same, mixed])
    assert _cell(model, 0, COL_BLUEPRINT, _TOOLTIP) == ""
    assert "第 2 条线" in _cell(model, 1, COL_BLUEPRINT, _TOOLTIP)


@pytest.mark.fast
def test_refresh_colors_emits_data_changed():
    """主题切换要重算已解析的 hex 颜色（模型的颜色不是 token，不会自己跟着变）。"""
    model = PlanQmlModel([_plan(profit=1.0)])
    seen: list[tuple] = []
    model.dataChanged.connect(lambda tl, br, roles=None: seen.append((tl.row(), br.row())))
    model.refresh_colors()
    assert seen, "refresh_colors 未发 dataChanged"


@pytest.mark.fast
def test_refresh_colors_on_empty_model_is_noop():
    PlanQmlModel([]).refresh_colors()


# ════════════════════════════════════════════════════════════
#  列宽自适应（PlanTableBridge.autofitWidths）
# ════════════════════════════════════════════════════════════


class _StubTable:
    """只提供 `get_model()` 的最小替身（autofitWidths 只用到这一个方法）。"""

    def __init__(self, model: PlanQmlModel) -> None:
        self._model = model

    def get_model(self) -> PlanQmlModel:
        return self._model


@pytest.mark.ui
def test_autofit_measures_cjk_content_not_char_count(qapp):
    """列宽必须**实测**中文宽度，不能按「字数 × 字号」估。

    回归背景：固定 80px 的状态列装不下「生产中」——Microsoft YaHei UI 下
    一个中文字符约占 1.34 倍字号（12px 时「生产中」实测 48px，不是 36px），
    估算出来的宽度会让三字值被省略成「生产…」。
    """
    from ui_qml.bridge.plan_table_bridge import PlanTableBridge

    model = PlanQmlModel([_plan(status="in_progress"), _plan(status="completed")])
    bridge = PlanTableBridge(_StubTable(model))

    widths = bridge.autofitWidths()
    assert len(widths) == model.columnCount()

    # 固定窄列与产品列不参与自适应（返回 0 = 保持原值）
    assert widths[COL_ICON] == 0
    assert widths[COL_PRODUCT] == 0

    # 状态列：至少要装得下「生产中」三个中文
    from PySide6.QtGui import QFont, QFontMetrics

    import ui_pyside6.theme as theme

    font = QFont(theme.FONT_FAMILY)
    font.setPixelSize(theme.fs(12))
    need = QFontMetrics(font).horizontalAdvance("生产中")
    assert widths[COL_STATUS] >= need, f"状态列宽 {widths[COL_STATUS]} 装不下「生产中」({need}px)"


@pytest.mark.ui
def test_autofit_respects_max_content_width_caps(qapp):
    """超长内容要按 MAX_CONTENT_WIDTHS 封顶，否则一列把整张表推出视口。"""
    from ui_pyside6.views.industry.plan_table_constants import COL_NOTES, MAX_CONTENT_WIDTHS
    from ui_qml.bridge.plan_table_bridge import PlanTableBridge

    model = PlanQmlModel([_plan(notes="很长" * 200)])
    widths = PlanTableBridge(_StubTable(model)).autofitWidths()

    assert widths[COL_NOTES] <= MAX_CONTENT_WIDTHS[COL_NOTES]


@pytest.mark.ui
def test_autofit_without_model_is_empty():
    from ui_qml.bridge.plan_table_bridge import PlanTableBridge

    assert PlanTableBridge(_StubTable(None)).autofitWidths() == []  # type: ignore[arg-type]
