import sqlite3
import os

def test_search():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database', 'items.db')
    print(f'数据库路径: {db_path}')
    if not os.path.exists(db_path):
        print(f'数据库不存在: {db_path}')
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查 item 表结构
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='item'")
    row = cursor.fetchone()
    if row:
        print('item 表结构:', row[0])
    else:
        print('item 表不存在')
    
    # 检查 item 表行数
    cursor.execute('SELECT COUNT(*) FROM item')
    cnt = cursor.fetchone()[0]
    print(f'item 表行数: {cnt}')
    
    # 检查列名
    cursor.execute('PRAGMA table_info(item)')
    cols = cursor.fetchall()
    print('item 列:', [(c[1], c[2]) for c in cols])
    
    # 检查 market_prices 表结构
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='market_prices'")
    row = cursor.fetchone()
    if row:
        print('market_prices 表结构:', row[0])
    else:
        print('market_prices 表不存在')
    
    cursor.execute('SELECT COUNT(*) FROM market_prices')
    cnt = cursor.fetchone()[0]
    print(f'market_prices 行数: {cnt}')
    
    cursor.execute('PRAGMA table_info(market_prices)')
    cols = cursor.fetchall()
    print('market_prices 列:', [(c[1], c[2]) for c in cols])
    
    # 测试几个 ID 搜索
    cursor.execute("SELECT type_id, zh_name, en_name FROM item WHERE type_id=34")
    rows = cursor.fetchall()
    print(f"搜索 type_id=34 结果: {rows}")
    
    # 测试 LIKE 搜索
    for q in ['三钛', 'Tritanium']:
        cursor.execute("SELECT type_id, zh_name, en_name FROM item WHERE en_name LIKE ? OR zh_name LIKE ? LIMIT 5", (f'%{q}%', f'%{q}%'))
        rows = cursor.fetchall()
        print(f"搜索 '{q}' 结果: {rows}")
    
    # 测试完整搜索 SQL - 查看 market_prices 有没有数据
    cursor.execute('SELECT type_id, buy_price, sell_price FROM market_prices LIMIT 5')
    rows = cursor.fetchall()
    print(f'market_prices 示例: {rows}')
    
    # 检查一下 group 搜索逻辑
    print('\n--- 测试 group 搜索 ---')
    cursor.execute("SELECT DISTINCT en_group_name, zh_group_name FROM item WHERE group_id IS NOT NULL LIMIT 10")
    groups = cursor.fetchall()
    print(f'示例类别: {groups}')
    
    cursor.execute("SELECT COUNT(DISTINCT group_id) FROM item WHERE group_id IS NOT NULL")
    cnt = cursor.fetchone()[0]
    print(f'不同 group_id 数: {cnt}')
    
    # 测试用中文类别名搜索
    for g in groups[:5]:
        q = g[1] or g[0]
        if q:
            cursor.execute('''
                SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name
                FROM item i
                WHERE i.en_group_name LIKE ? OR i.zh_group_name LIKE ?
                LIMIT 3
            ''', (f'%{q}%', f'%{q}%'))
            rows = cursor.fetchall()
            print(f"类别搜索 '{q}': {len(rows)} 条")
    
    # 测试 _db_execute_search 使用的完整查询
    print('\n--- 测试完整搜索 SQL ---')
    q = '三钛'
    cursor.execute('''
        SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
               mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
        FROM item i
        LEFT JOIN market_prices mp ON i.type_id = mp.type_id
            AND mp.fetch_time = (SELECT MAX(mp2.fetch_time) FROM market_prices mp2 WHERE mp2.type_id = i.type_id)
        WHERE i.en_name LIKE ? OR i.zh_name LIKE ?
        ORDER BY i.type_id LIMIT 300
    ''', (f'%{q}%', f'%{q}%'))
    rows = cursor.fetchall()
    print(f"完整搜索 '{q}' 结果数: {len(rows)}")
    if rows:
        print(f'第一条 ({len(rows[0])} 列): {rows[0]}')
    
    conn.close()

test_search()
