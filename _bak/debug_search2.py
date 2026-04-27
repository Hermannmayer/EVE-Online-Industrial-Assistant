"""
Test the exact search flow that the app uses.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database', 'items.db')

print("=== 1. Testing _db_fetch_suggestions (real-time dropdown) ===")
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

test_queries = ['3', '三', '34', '矿', '钛']

for q in test_queries:
    if q.isdigit():
        cursor.execute("SELECT type_id, en_name, zh_name FROM item WHERE type_id = ? LIMIT 10", (int(q),))
    else:
        cursor.execute(
            "SELECT type_id, en_name, zh_name FROM item "
            "WHERE en_name LIKE ? OR zh_name LIKE ? "
            "ORDER BY CASE WHEN en_name LIKE ? THEN 0 WHEN zh_name LIKE ? THEN 1 ELSE 2 END, LENGTH(en_name), type_id LIMIT 10",
            (f"{q}%", f"{q}%", f"{q}%", f"{q}%")
        )
    rows = cursor.fetchall()
    # Note the prefix match: f"{q}%" not f"%{q}%"
    print(f"  _db_fetch_suggestions('{q}'): {len(rows)} results")
    if rows:
        for r in rows[:3]:
            print(f"    [{r[0]}] {r[2]} ({r[1]})")
print()

print("=== 2. Testing _db_execute_search (full search) ===")
test_full_queries = ['3', '三钛', '34', '矿', 'Tritanium']

for q in test_full_queries:
    like_pattern = f"%{q}%"
    group_match = None
    groups_cursor = conn.cursor()
    groups_cursor.execute(
        "SELECT DISTINCT e.group_id, e.en_group_name, e.zh_group_name "
        "FROM item e WHERE e.group_id IS NOT NULL "
        "ORDER BY e.zh_group_name, e.en_group_name"
    )
    all_groups = groups_cursor.fetchall()
    
    for gid, en, zh in all_groups:
        if (zh and str(q) in zh) or (en and str(q) in en):
            group_match = gid
            break
    
    if q.isdigit():
        cursor.execute("""
            SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
                   mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
            FROM item i
            LEFT JOIN market_prices mp ON i.type_id = mp.type_id
                AND mp.fetch_time = (SELECT MAX(mp2.fetch_time) FROM market_prices mp2 WHERE mp2.type_id = i.type_id)
            WHERE i.type_id = ?
            ORDER BY i.type_id LIMIT 100
        """, (int(q),))
    elif group_match is not None:
        cursor.execute("""
            SELECT sub.type_id, sub.zh_name, sub.en_name, sub.en_group_name, sub.zh_group_name, sub.volume,
                   mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
            FROM (
                SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume
                FROM item i
                WHERE i.group_id = ?
                UNION
                SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume
                FROM item i
                WHERE (i.en_name LIKE ? OR i.zh_name LIKE ?)
            ) sub
            LEFT JOIN market_prices mp ON sub.type_id = mp.type_id
                AND mp.fetch_time = (SELECT MAX(mp2.fetch_time) FROM market_prices mp2 WHERE mp2.type_id = sub.type_id)
            ORDER BY sub.type_id LIMIT 300
        """, (group_match, like_pattern, like_pattern))
    else:
        cursor.execute("""
            SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
                   mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
            FROM item i
            LEFT JOIN market_prices mp ON i.type_id = mp.type_id
                AND mp.fetch_time = (SELECT MAX(mp2.fetch_time) FROM market_prices mp2 WHERE mp2.type_id = i.type_id)
            WHERE i.en_name LIKE ? OR i.zh_name LIKE ?
            ORDER BY i.type_id LIMIT 300
        """, (like_pattern, like_pattern))
    rows = cursor.fetchall()
    print(f"  _db_execute_search('{q}'): {len(rows)} results (group_match={group_match})")
    if rows:
        for r in rows[:3]:
            print(f"    [{r[0]}] {r[2]} ({r[1]}) | buy={r[6]}, sell={r[7]}")

conn.close()

print()
print("=== 3. CHECKING POTENTIAL ISSUES ===")

# Check if some expected items exist
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Check basic minerals
for tid in [34, 35, 36, 37, 38, 39, 40]:
    cursor.execute("SELECT type_id, zh_name, en_name FROM item WHERE type_id=?", (tid,))
    row = cursor.fetchone()
    if row:
        print(f"  Min ID {tid} FOUND: {row[1]} ({row[2]})")
    else:
        print(f"  Min ID {tid} NOT FOUND in item table")

# Check for the string 'Tritanium' (not 'Tritanium%')
# EVE Online type_id 34 = Tritanium
print()
# Check if the item table has any item starting with 'Tri'
cursor.execute("SELECT type_id, en_name, zh_name FROM item WHERE en_name LIKE 'Tri%' LIMIT 5")
rows = cursor.fetchall()
print(f"  Items starting with 'Tri': {len(rows)}")
for r in rows:
    print(f"    [{r[0]}] {r[1]} ({r[2]})")

# Check if there's an issue with type_id 34 in market_prices
cursor.execute("SELECT type_id, buy_price, sell_price FROM market_prices WHERE type_id=34 LIMIT 5")
rows = cursor.fetchall()
print(f"  market_prices for type_id=34: {len(rows)} rows")
if rows:
    for r in rows[:3]:
        print(f"    [{r[0]}] buy={r[1]}, sell={r[2]}")

conn.close()

print()
print("=== 4. SIMULATING ACTUAL UI FLOW ===")
# User types "三钛", presses Enter
# _do_search -> _do_search_async -> _db_execute_search
# Let's check if the full join works correctly
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

query = "三钛"
like_pattern = f"%{query}%"
cursor.execute("""
    SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
           mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
    FROM item i
    LEFT JOIN market_prices mp ON i.type_id = mp.type_id
        AND mp.fetch_time = (SELECT MAX(mp2.fetch_time) FROM market_prices mp2 WHERE mp2.type_id = i.type_id)
    WHERE i.en_name LIKE ? OR i.zh_name LIKE ?
    ORDER BY i.type_id LIMIT 300
""", (like_pattern, like_pattern))
rows = cursor.fetchall()

# Simulate the exact same processing in _do_search_async
if rows:
    for idx, row in enumerate(rows):
        tid, zh, en, en_group, zh_group, volume, buy_p, sell_p, buy_v, sell_v = row
        buy_v = buy_v or 0
        sell_v = sell_v or 0
        vol = volume or 0.0
        group = zh_group or en_group or "—"
        # Format prices
        buy_str = "—"
        if buy_p is not None and buy_v > 0:
            buy_str = f"{buy_p:,.2f} ({buy_v:,})"
        elif buy_p is not None:
            buy_str = f"{buy_p:,.2f}"
        sell_str = "—"
        if sell_p is not None and sell_v > 0:
            sell_str = f"{sell_p:,.2f} ({sell_v:,})"
        elif sell_p is not None:
            sell_str = f"{sell_p:,.2f}"
        
        if idx == 0:
            print(f"  First result formatted: ID={tid}, Name={zh}({en}), Group={group}, "
                  f"Buy={buy_str}, Sell={sell_str}, Vol={vol}")
    
    print(f"  Total formatted results: {len(rows)}")
    print("  ✓ Search flow works correctly!")
else:
    print("  × Search returned no results!")

conn.close()
