import sqlite3
import requests
import json


def create_tables():
    
    conn = sqlite3.connect('./Datas/iteamdata.db')
    cursor = conn.cursor()

    # 主表：存储类型基本信息
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS types (
            type_id INTEGER PRIMARY KEY,
            en_name TEXT,
            zh_name TEXT,
            group_id INTEGER,
            group_name TEXT,
            market_group_id INTEGER,
            market_group_name TEXT,
            mass REAL,
            volume REAL,
            published BOOLEAN
        )
        ''')
    conn.commit()
    conn.close()
def getidapi():
    idapi='https://sde.jita.space/universe/types'
    response=requests.get(idapi)
    if response.status_code != 200:
        
        

    #cursor.execute("""
        


#""")

 

    
    
if __name__ == "__main__":
    create_tables()
