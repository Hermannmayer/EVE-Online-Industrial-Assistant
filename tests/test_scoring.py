"""测试评分模块"""

def test_get_price_none():
    """无数据库时返回 None"""
    from services.scoring import get_price
    # 不存在的 type_id 应返回 None
    price = get_price(99999999, "buy")
    assert price is None
