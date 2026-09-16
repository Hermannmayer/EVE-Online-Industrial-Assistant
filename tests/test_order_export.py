"""挂单导出解析测试 —— services/order_export.py

覆盖：表头驱动 CSV（买/卖）、表头顺序打乱、友好列名、只有 stationID、
启发式兜底（无表头）、千分位（英式/欧式）、表头行与空行跳过、未识别行计数、
`find_latest_export` 的目录/文件名筛选与 mtime 取新。
"""

import os

from services.order_export import find_latest_export, parse_order_export

_ORDER_KEYS = {
    "order_id",
    "is_buy",
    "price",
    "volume_total",
    "volume_remain",
    "location_id",
    "location_name",
    "type_id",
    "type_name",
    "issued",
    "duration",
}

# 真实的「My Orders」表头（列序固定，range/minVolume/regionID 等与解析无关）
_MY_ORDERS_HEADER = (
    "price,volRemaining,typeID,range,orderID,volEntered,minVolume,bid,"
    "issued,duration,stationID,regionID,solarSystemID,jumps"
)


def test_parse_standard_csv_header_sell():
    """标准「My Orders」CSV：表头驱动解析出各字段（bid=False → 卖单）"""
    raw = f"{_MY_ORDERS_HEADER}\n1234.56,800,34,-1,123456789,1000,1,False,2026-09-10 12:00:00,30,60003760,10000002,30000142,5"
    orders, unparsed = parse_order_export(raw)

    assert unparsed == 0
    assert len(orders) == 1
    o = orders[0]
    assert set(o) == _ORDER_KEYS
    assert o["order_id"] == 123456789
    assert o["price"] == 1234.56
    assert o["volume_total"] == 1000
    assert o["volume_remain"] == 800
    assert o["type_id"] == 34
    assert o["is_buy"] == 0, "bid=False → 卖单"
    assert o["issued"] == "2026-09-10 12:00:00", "issued 原样存字符串"
    assert o["duration"] == 30
    assert o["location_id"] == 60003760
    assert o["location_name"] == "", "导出无名字 → 留空串"


def test_parse_buy_order():
    """bid=True → 买单（is_buy=1）"""
    raw = f"{_MY_ORDERS_HEADER}\n5.50,150,35,-1,999,200,1,True,2026-09-11 09:00:00,90,60003760,10000002,30000142,2"
    orders, _ = parse_order_export(raw)
    assert orders[0]["is_buy"] == 1
    assert orders[0]["order_id"] == 999


def test_header_order_shuffled():
    """表头顺序打乱：按列名前位置取值，不受顺序影响"""
    raw = "orderID,price,bid,volEntered,volRemaining,typeID\n999,5.50,True,200,150,35"
    orders, unparsed = parse_order_export(raw)
    assert unparsed == 0
    o = orders[0]
    assert (o["order_id"], o["price"], o["is_buy"]) == (999, 5.5, 1)
    assert (o["volume_total"], o["volume_remain"], o["type_id"]) == (200, 150, 35)


def test_friendly_column_names():
    """带友好列名 typeName/stationName 的导出"""
    raw = (
        "typeName,stationName,orderID,price,volRemaining,volEntered,bid\n"
        "Tritanium,Jita IV - Moon 4,555,6.00,300,500,False"
    )
    orders, unparsed = parse_order_export(raw)
    assert unparsed == 0
    o = orders[0]
    assert o["type_name"] == "Tritanium"
    assert o["location_name"] == "Jita IV - Moon 4"
    assert o["order_id"] == 555
    assert o["volume_total"] == 500 and o["volume_remain"] == 300


def test_station_id_without_name():
    """只有 stationID 没有名字：location_id 有值、location_name 空串"""
    raw = "orderID,stationID,price,volRemaining,volEntered,bid\n777,60003760,10.0,50,60,False"
    orders, _ = parse_order_export(raw)
    o = orders[0]
    assert o["location_id"] == 60003760
    assert o["location_name"] == ""


def test_header_row_not_counted_as_unparsed():
    """表头行既不计入订单、也不计入未识别"""
    raw = f"{_MY_ORDERS_HEADER}\n1234.56,800,34,-1,123456789,1000,1,False,2026-09-10 12:00:00,30,60003760,10000002,30000142,5"
    orders, unparsed = parse_order_export(raw)
    assert len(orders) == 1
    assert unparsed == 0


def test_unparseable_line_counted():
    """完全无法解析的行计入未识别（无表头 → 启发式路径）"""
    raw = "完全无法解析的一行文字\n123456789  卖  1000.50  1000  800  吉他"
    orders, unparsed = parse_order_export(raw)
    assert unparsed == 1
    assert len(orders) == 1
    assert orders[0]["order_id"] == 123456789


def test_header_mode_unparsed_when_no_order_id():
    """表头模式下缺订单 ID 的行计入未识别"""
    raw = "orderID,price\n42,5.0\n,5.0"
    orders, unparsed = parse_order_export(raw)
    assert len(orders) == 1 and orders[0]["order_id"] == 42
    assert unparsed == 1


def test_empty_and_blank_input():
    """空/纯空白输入 → ([], 0)"""
    assert parse_order_export("") == ([], 0)
    assert parse_order_export("   \n\n  ") == ([], 0)


def test_thousands_separator_us():
    """英式千分位 1,234.56（制表符分隔的 CSV 单元格内）"""
    raw = "orderID\tprice\tvolEntered\tvolRemaining\tbid\n123\t1,234.56\t1000\t800\tFalse"
    orders, unparsed = parse_order_export(raw)
    assert unparsed == 0
    assert orders[0]["price"] == 1234.56


def test_thousands_separator_euro():
    """欧式千分位 1 234,56"""
    raw = "orderID\tprice\tvolEntered\tvolRemaining\tbid\n123\t1 234,56\t1000\t800\tFalse"
    orders, _ = parse_order_export(raw)
    assert orders[0]["price"] == 1234.56


def test_heuristic_chinese_header_and_row():
    """纯中文表头 + 一行数据（启发式路径，表头行被跳过）"""
    raw = (
        "订单ID  类型  价格  挂单量  剩余  位置  有效期\n"
        "123456789  卖  1000.50  1000  800  吉他  30 天"
    )
    orders, unparsed = parse_order_export(raw)
    assert unparsed == 0
    assert len(orders) == 1
    o = orders[0]
    assert (o["order_id"], o["is_buy"], o["price"]) == (123456789, 0, 1000.5)
    assert (o["volume_total"], o["volume_remain"]) == (1000, 800)
    assert o["location_name"] == "吉他"
    assert o["duration"] == 30


def test_heuristic_buy_direction():
    """启发式：'买' 判为买单，千分位价格可解析"""
    raw = "123456789  买  1,234.56  1000  800  Jita"
    orders, unparsed = parse_order_export(raw)
    assert unparsed == 0
    o = orders[0]
    assert o["is_buy"] == 1
    assert o["price"] == 1234.56
    assert o["location_name"] == "Jita"


# ════════════════════════════════════════════════════════════════
#  find_latest_export
# ════════════════════════════════════════════════════════════════


def test_find_latest_export_empty_dir(tmp_path):
    assert find_latest_export(str(tmp_path)) is None


def test_find_latest_export_missing_dir(tmp_path):
    assert find_latest_export(str(tmp_path / "does_not_exist")) is None


def test_find_latest_export_picks_newest_by_mtime(tmp_path):
    old = tmp_path / "orders_old.txt"
    new = tmp_path / "orders_new.csv"
    old.write_text("x", encoding="utf-8")
    new.write_text("y", encoding="utf-8")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))

    assert find_latest_export(str(tmp_path)) == str(new)


def test_find_latest_export_ignores_non_order_files(tmp_path):
    """名字不含 order 或后缀不符的文件被忽略"""
    (tmp_path / "marketlog.txt").write_text("x", encoding="utf-8")
    (tmp_path / "orders.txt").write_text("y", encoding="utf-8")

    assert find_latest_export(str(tmp_path)) == str(tmp_path / "orders.txt")
