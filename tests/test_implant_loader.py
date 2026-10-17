"""`services.implant_loader` 纯函数测试（05-7）：加成文案 + 插槽归类。"""

from __future__ import annotations

import pytest

from services.implant_loader import _implant_slot, _parse_implant_bonus

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ([{"attribute_id": 440, "value": -5}], "制造时间 -5%"),
        ([{"attribute_id": 379, "value": 10}], "精炼产出 +10%"),
        ([{"attribute_id": 440, "value": 0}, {"attribute_id": 999, "value": 5}], ""),  # 0 与未知属性都不输出
        ([{"attribute_id": 440, "value": -5}, {"attribute_id": 434, "value": 3}], "制造时间 -5%, 采矿量 +3%"),
    ],
)
def test_parse_implant_bonus(attrs, expected):
    assert _parse_implant_bonus(attrs) == expected


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ([{"attribute_id": 440}], "A"),
        ([{"attribute_id": 379}], "B"),
        ([{"attribute_id": 440}, {"attribute_id": 379}], "A"),  # 多组命中按 A→B→C 取第一个
        ([{"attribute_id": 999}], "C"),  # 未知 → 通用
    ],
)
def test_implant_slot(attrs, expected):
    assert _implant_slot(attrs) == expected
