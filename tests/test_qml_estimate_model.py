"""EstimateQmlModel 契约测试 —— QML 表格模型的样板。

重点验证两件容易静默出错的事：
1. **QML 靠命名角色取值**（`roleNames()`），缺一个角色 QML delegate 就拿到 undefined；
2. **图标必须给 URL 而不是 QPixmap**，后者 QML 渲染不了。
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt

from ui_qml.icon_cache import item_icon_path
from ui_qml.models import EstimateQmlModel
from ui_qml.models.estimate_qml_model import ROLE_NAMES, _icon_url

# 按名字取角色号的便捷映射（测试里反复用）
ROLE = {name.decode(): role for role, name in ROLE_NAMES.items()}

# roleNames() 里必须存在的名字（QML delegate 直接引用）
EXPECTED_ROLES = {
    "typeId",
    "iconUrl",
    "name",
    "qty",
    "qtyText",
    "unitPriceText",
    "sellTotalText",
    "buyTotalText",
    "volumeText",
    "rowIndex",
    "refineValueText",
}


def _model_with_rows() -> EstimateQmlModel:
    model = EstimateQmlModel()
    model.set_rows(
        [
            {
                "type_id": 34,
                "name": "Tritanium",
                "qty": 1000,
                "sell_price": 5.0,
                "buy_price": 4.0,
                "unit_price": 5.0,
                "sell_total": 5000.0,
                "buy_total": 4000.0,
                "volume": 10.0,
                "_volume": 0.01,
                "bp_me": 0,
                "bp_te": 0,
            },
            {
                "type_id": 35,
                "name": "Pyerite",
                "qty": 0,
                "sell_price": 0,
                "buy_price": 0,
                "unit_price": 0,
                "sell_total": 0,
                "buy_total": 0,
                "volume": 0,
                "_volume": 0.01,
            },
        ]
    )
    return model


def test_role_names_cover_qml_contract():
    assert set(ROLE_NAMES.values()) == {n.encode() for n in EXPECTED_ROLES}


def test_role_names_are_unique_and_in_user_range():
    roles = list(ROLE_NAMES)
    assert len(roles) == len(set(roles)), "角色号重复会让两个名字指向同一列数据"
    assert all(r > Qt.ItemDataRole.UserRole for r in roles)


def test_named_roles_resolve_per_row():
    model = _model_with_rows()
    idx = model.index(0, 0)

    assert model.data(idx, ROLE["typeId"]) == 34
    assert model.data(idx, ROLE["name"]) == "Tritanium"
    assert model.data(idx, ROLE["qty"]) == 1000
    assert model.data(idx, ROLE["qtyText"]) == "1,000"
    assert model.data(idx, ROLE["sellTotalText"]) == "5,000.00"
    assert model.data(idx, ROLE["rowIndex"]) == 0


def test_missing_values_render_as_placeholder():
    """与 Widgets 版一致：0 值显示 `---` 而不是 `0.00`。"""
    model = _model_with_rows()
    idx = model.index(1, 0)
    assert model.data(idx, ROLE["sellTotalText"]) == "---"
    assert model.data(idx, ROLE["unitPriceText"]) == "---"
    assert model.data(idx, ROLE["volumeText"]) == "---"


def test_icon_url_is_url_not_pixmap():
    """图标必须给 `file://` URL —— QML 的 Image 吃 URL，吃不了 QPixmap。"""
    existing = next(
        (int(f[:-4]) for f in os.listdir(os.path.dirname(item_icon_path(0))) if f.endswith(".png")),
        None,
    )
    if existing is None:
        # 没有图标缓存时只能验证「缺失 → 空串」这一半
        assert _icon_url(123456789) == ""
        return

    url = _icon_url(existing)
    assert url.startswith("file:///"), f"不是 QML 可用的 URL: {url}"
    assert url.endswith(".png")


def test_icon_url_empty_when_file_missing():
    """文件不存在必须返回空串，否则 QML 会刷一堆加载失败警告。"""
    assert _icon_url(999999999) == ""
    assert _icon_url(None) == ""


def test_widgets_roles_still_work():
    """父类（QWidgets 版）的角色必须保持可用——迁移期两个视图共用一个模型。"""
    model = _model_with_rows()
    idx = model.index(0, 1)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "Tritanium"
    # 行数据仍可从 UserRole 取（Widgets 版右键菜单依赖它）
    row = model.data(model.index(0, 0), Qt.ItemDataRole.UserRole)
    assert isinstance(row, dict) and row["type_id"] == 34


def test_discount_recalculates_totals():
    model = _model_with_rows()
    model.set_discount(0.5)
    assert model.data(model.index(0, 0), ROLE["sellTotalText"]) == "2,500.00"


def test_sort_keeps_row_index_consistent():
    """排序后行号全变，模型必须通知 QML 重取 rowIndex。"""
    model = _model_with_rows()
    changed: list[tuple] = []
    model.dataChanged.connect(lambda tl, br, roles=None: changed.append((tl.row(), br.row())))

    model.sort(1, Qt.SortOrder.DescendingOrder)  # 按 name 降序
    assert model.data(model.index(0, 0), ROLE["name"]) == "Tritanium"
    assert model.data(model.index(1, 0), ROLE["rowIndex"]) == 1
    assert changed, "排序后未发 dataChanged，QML 的行号会全部错位"


def test_sort_by_icon_column_is_noop():
    """图标列不可排序（_SORT_KEYS[0] 为 None）。"""
    model = _model_with_rows()
    before = [model.data(model.index(r, 0), ROLE["name"]) for r in range(model.rowCount())]
    model.sort(0, Qt.SortOrder.DescendingOrder)
    after = [model.data(model.index(r, 0), ROLE["name"]) for r in range(model.rowCount())]
    assert before == after
