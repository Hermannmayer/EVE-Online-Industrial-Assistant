import urllib.request, json

url = 'https://esi.evetech.net/latest/markets/10000002/orders/?type_id=44992&order_type=buy'
req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'EveDataCrawler/1.0'})

try:
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    print(f'PLEX 买单数: {len(data)}')
    if data:
        print(f'  最高价: {max(d["price"] for d in data):.2f}')
        print(f'  最低价: {min(d["price"] for d in data):.2f}')
        print(f'  第一个: {data[0]}')
    else:
        print('PLEX 在伏尔戈星域没有任何买单')
except Exception as e:
    print(f'错误: {e}')
