import sqlite3

conn = sqlite3.connect('./database/items.db')
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("数据库中的表:")
for t in tables:
    print(f"  - {t[0]}")

count = conn.execute("SELECT COUNT(*) FROM market_prices").fetchone()[0]
print(f"\nmarket_prices 表记录数: {count}")

if count > 0:
    sample = conn.execute("SELECT type_id, buy_price, sell_price, buy_volume, sell_volume, fetch_time FROM market_prices LIMIT 5").fetchall()
    print("\n示例数据:")
    for row in sample:
        print(f"  type_id={row[0]}, buy={row[1]}, sell={row[2]}, buy_vol={row[3]}, sell_vol={row[4]}, time={row[5]}")

    max_time = conn.execute("SELECT fetch_time, COUNT(*) FROM market_prices GROUP BY fetch_time ORDER BY fetch_time DESC LIMIT 3").fetchall()
    print(f"\n最近抓取批次:")
    for t in max_time:
        print(f"  {t[0]}: {t[1]} 条")
else:
    # 检查表结构
    cols = conn.execute("PRAGMA table_info(market_prices)").fetchall()
    print("\n表结构:")
    for c in cols:
        print(f"  {c[1]} ({c[2]})")

conn.close()
