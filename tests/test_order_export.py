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


# ════════════════════════════════════════════════════════════════
#  国服客户端的**真实**导出格式（2026-09 实测样本）
#
#  样本来源：`Documents\EVE\logs\Marketlogs\个人订单-2026.09.16 1232.txt`
#  四个与直觉不同的点，全是实测踩出来的：
#    ① 文件是 **UTF-8 带 BOM**；② 位置名包在 `<localized hint="英文">中文</localized>` 里；
#    ③ `volRemaining` 是**浮点串**（`340.0`）；④ 时间列叫 `issueDate` 而不是 `issued`。
# ════════════════════════════════════════════════════════════════

_REAL_HEADER = (
    "orderID,typeID,charID,charName,regionID,regionName,solarSystemID,solarSystemName,"
    "stationID,stationName,range,bid,price,volEntered,volRemaining,minVolume,issueDate,"
    "orderState,duration,escrow,isCorp,accountID,accountOwnerID,accountKey,"
)
_REAL_ROW = (
    '7422573405,3989,2115252966,Meyer Hermann,10000002,'
    '<localized hint="The Forge">多美星域*</localized>,30000142,'
    '<localized hint="Jita">吉他*</localized>,60003760,'
    '<localized hint="Jita IV - Moon 4 - Caldari Navy Assembly Plant">吉他 IV - 卫星 4 - 加达里海军组装车间*</localized>,'
    "32767,False,2183000.0,394,340.0,1,2026-09-16 12:00:43.000,0,90,0.0,True,102228901,98795184,1000,"
)


def test_real_client_export_is_parsed_field_by_field():
    """国服真实导出：BOM + localized 包装 + 浮点剩余量 + issueDate 一次全中"""
    orders, unparsed = parse_order_export("\ufeff" + _REAL_HEADER + "\n" + _REAL_ROW + "\n")

    assert unparsed == 0, "真实格式不该有识别不出的行"
    assert len(orders) == 1
    o = orders[0]
    assert o["order_id"] == 7422573405
    assert o["type_id"] == 3989
    assert o["is_buy"] == 0, "bid=False 是卖单"
    assert o["price"] == 2183000.0
    assert o["volume_total"] == 394
    assert o["volume_remain"] == 340, "`volRemaining` 是浮点串（340.0），不能静默变 0"
    assert o["location_id"] == 60003760
    assert o["duration"] == 90
    assert o["issued"] == "2026-09-16 12:00:43.000", "真实列名是 issueDate"


def test_localized_wrapper_is_unwrapped_to_the_games_own_text():
    """`<localized>` 拆成游戏里显示的中文名，而不是把整段标签存进库"""
    orders, _ = parse_order_export(_REAL_HEADER + "\n" + _REAL_ROW)
    assert orders[0]["location_name"] == "吉他 IV - 卫星 4 - 加达里海军组装车间"
    assert "<localized" not in orders[0]["location_name"]


def test_localized_without_inner_text_falls_back_to_hint():
    raw = f"{_REAL_HEADER}\n7422573405,3989,1,x,10000002,,30000142,,60003760,<localized hint=\"Jita IV-4\"></localized>,1,False,5.0,1,1.0,1,2026-09-16 12:00:00,0,90,0,True,1,1,1000,"
    orders, _ = parse_order_export(raw)
    assert orders[0]["location_name"] == "Jita IV-4"


def test_bom_prefixed_header_is_still_recognised():
    """BOM 不能把首列名污染成 `\ufefforderID`，否则整份文件退化成启发式解析"""
    without_bom = _REAL_HEADER + "\n" + _REAL_ROW
    with_bom = "\ufeff" + without_bom
    assert parse_order_export(with_bom) == parse_order_export(without_bom)


def test_heuristic_path_still_requires_plain_integers(tmp_path):
    """字段级的「浮点串当整数」放宽**不得**渗进启发式路径。

    否则无表头时 `14730000.0`（价格）会被认成整数、挤掉真正的挂单量/剩余，
    是「价格填到数量列」这类静默串列。
    """
    orders, _ = parse_order_export("三钛合金  14730000.0  340  2026-09-16 12:00:00")
    assert orders[0]["price"] == 14730000.0
    assert orders[0]["volume_remain"] != 14730000


def test_find_latest_export_matches_chinese_filenames(tmp_path):
    """国服导出文件名是中文的（个人订单 / 军团订单），只认 `order` 会永远找不到"""
    (tmp_path / "个人订单-2026.09.16 1232.txt").write_text("x", encoding="utf-8")
    assert find_latest_export(str(tmp_path)) == str(tmp_path / "个人订单-2026.09.16 1232.txt")


def test_read_export_text_handles_bom_and_utf16(tmp_path):
    from services.order_export import read_export_text

    utf8_bom = tmp_path / "a.txt"
    utf8_bom.write_bytes(b"\xef\xbb\xbf" + "订单ID,价格\n1,2".encode())
    assert read_export_text(utf8_bom).lstrip("\ufeff").startswith("订单ID")

    utf16 = tmp_path / "b.txt"
    utf16.write_bytes("orderID,price\n1,2".encode("utf-16"))
    assert "orderID" in read_export_text(utf16)
