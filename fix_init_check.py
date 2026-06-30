import os

fpath = r'services/init_check.py'
with open(fpath, 'rb') as f:
    raw = f.read()

for enc in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
    try:
        content = raw.decode(enc)
        detected_enc = enc
        break
    except:
        continue
else:
    detected_enc = 'utf-8'
    content = raw.decode('utf-8', errors='replace')

print(f'Encoding: {detected_enc}')

eol = chr(13)+chr(10) if chr(13)+chr(10) in content else chr(10)

# Fix 1: SQL query
if 'iconID' in content:
    old_q = 'SELECT COUNT(*) FROM item WHERE iconID > 0'
    new_q = 'SELECT COUNT(*) FROM item WHERE market_group_id IS NOT NULL AND market_group_id > 0'
    content = content.replace(old_q, new_q)
    print('Fixed SQL query')
else:
    print('SQL query already fixed')

# Fix 2: check_all() function - find and replace
lines = content.split(eol)
start = None
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith('def check_all() -> dict:'):
        start = i
        break

assert start is not None, 'check_all() not found!'

brace_depth = 0
end = None
for i in range(start, len(lines)):
    l = lines[i]
    brace_depth += l.count('{') - l.count('}')
    if brace_depth == 0 and i > start:
        end = i + 1
        break

assert end is not None, 'Could not find end of check_all()'

old_block = eol.join(lines[start:end])

indent = '    '
new_block_lines = [
    'def check_all() -> dict:',
    indent + '"""\u8fd4\u56de\u5404\u7ec4\u4ef6\u72b6\u6001 { "items": bool, "prices": bool, "blueprints": bool, "implants": bool, "icons": bool }"""',
    indent + 'cached, total = check_icons()',
    indent + 'return {',
    indent*2 + '"items": check_items() >= 10000,',
    indent*2 + '"prices": check_prices() > 0,',
    indent*2 + '"blueprints": check_blueprints() >= 1000,',
    indent*2 + '"implants": check_implants() > 0,',
    indent*2 + '"icons": cached >= total,',
    indent + '}',
]
new_block = eol.join(new_block_lines)

assert old_block in content, 'old_block not in content!'
content = content.replace(old_block, new_block)
print('Fixed check_all()')

# Write back
with open(fpath, 'wb') as f:
    f.write(content.encode(detected_enc))
print('Write complete')

# Verify
check = open(fpath, 'r', encoding=detected_enc).read()
print('SQL fixed:', 'market_group_id' in check)
print('No double call:', 'check_icons()[0]' not in check)
print('Has cached,total:', 'cached, total' in check)