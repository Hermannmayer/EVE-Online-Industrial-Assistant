# ECC 代码审查报告 — EVE Online Industrial Assistant

**审查时间**: 2026-06-15  
**审查范围**: 全项目源代码

---

## 总体评估

项目是一个功能完整的 EVE Online 市场交易辅助工具，使用 PySide6 构建桌面界面。整体架构清晰（MVC风格），但存在多处值得改进的问题。

---

## 🔴 CRITICAL（严重）

### C1 — SQL 注入风险：f-string 拼接表名列名

**文件**: `services/scoring.py:54-68`  
**风险**: 函数 `get_price()` 和 `get_volume()` 使用 f-string 拼接 `price_type` 参数直接到 SQL 查询的列名位置：

```python
c.execute(f"SELECT {col} FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1", ...)
```

虽然当前调用方只有 `"buy"` / `"sell"`，但若未来通过 UI/API 接受用户输入，可被 SQL 注入攻击。

**修复建议**: 使用白名单验证 `price_type`:
```python
VALID_COLS = {"buy": "buy_price", "sell": "sell_price"}
col = VALID_COLS.get(price_type)
if not col:
    return None
```

---

### C2 — getitems.py 中的 f-string SQL 查询

**文件**: `services/workers/getitems.py:276`  
**风险**:

```python
cursor = await db.execute(f'''
    SELECT type_id FROM item 
    WHERE type_id >= {START_TYPE_ID}
    AND (en_name IS NULL OR market_group_id IS NULL)
''')
```

`START_TYPE_ID` 是常量 `178`，当前安全。但模式容易退化。

**修复建议**: 使用参数化查询 `WHERE type_id >= ?`。

---

## 🟠 HIGH（高风险）

### H1 — 数据库连接未复用，频繁开闭

**文件**: `services/scoring.py`  
**问题**: `get_price` 每调用一次就 `sqlite3.connect`/`close`。`calc_manufacturing_score` 开了独立连接，内部又调用 `get_price` 再开新连接。每个评分请求开 3-5 次数据库连接。

**修复建议**: 所有函数接收一个已打开的 `connection` 参数，或使用连接池。

---

### H2 — getitems.py 工作协程退出逻辑混乱

**文件**: `services/workers/getitems.py:293-304`  
**问题**:
```python
await queue.join()       # 所有任务完成
for task in workers:
    task.cancel()        # 第296行: 第一次 cancel
await asyncio.gather(*workers, return_exceptions=True)  # 第298行: 第一次 gather
await client.session.__aexit__(None, None, None)  # 第301行: 手动关闭 session
for task in workers:
    task.cancel()        # 第303行: 重复 cancel
await asyncio.gather(*workers, return_exceptions=True)  # 重复 gather
```

**修复建议**: 删除第295-304行中重复的 cancel/gather 逻辑。

---

### H3 — scoring_cache 缓存无并发保护

**文件**: `services/scoring_cache.py`  
**问题**: `_cache` 在 `QThread` + 异步 worker 多线程环境下读写，`invalidate()` 清除缓存时另一个线程可能读到 `None`。

**修复建议**: 使用 `threading.Lock` 保护读写。

---

### H4 — Emoji 在代码和 UI 中使用

**文件**: `dev.py`、`build_release.py`、`main_window.py`、各 view  
**问题**: emoji 在 Windows 不同版本上渲染不一致（可能显示为方块）。依赖平台字体渲染。

**修复建议**: 在 PySide6 中使用图标/图片替代 emoji。脚本中使用纯文本。

---

## 🟡 MEDIUM（中等风险）

### M1 — getimplantdata.py 绕过标准路径管理

**文件**: `services/workers/getimplantdata.py:16-17`  
**问题**: 用 3 层 `os.path.dirname` 手工拼接 `DB_PATH`，绕过 `core/paths.py` 的标准化路径函数。

**修复建议**: 使用 `from core.paths import database_path`。

---

### M2 — launch.json 指向不存在的入口文件

**文件**: `.claude/launch.json:6`  
**问题**: `"runtimeArgs": ["main_pyside6.py"]` — 此文件不存在。项目入口为 `Main.py`。

---

### M3 — 测试覆盖率严重不足

**文件**: `tests/`（总共 7 个测试）  
**覆盖**:
- `test_core.py`: 2 个（路径存在检查）
- `test_logger.py`: 2 个（日志输出）
- `test_scoring.py`: 1 个（不存在 type_id）
- `test_scoring_cache.py`: 2 个（缓存基本操作）

**缺失**: 无 UI 测试，无 services/workers 测试，无 ESI 集成测试覆盖率达到 80%+ 要求。

---

### M4 — `scoring.py` 中 `_RACE_ME` 数据不完整

**文件**: `services/scoring.py:23`  
**问题**: `_RACE_ME = {4247: "****残余物", 4312: "****残余物"}` — `****` 为占位符，只有 2 条，可能导致某些材料名称无法正确显示。

---

## 🟢 LOW（低风险 / 建议）

### L1 — Magic number 10000002 硬编码

**文件**: `Main.py:48,71`  
**问题**: Jita region_id 在迁移函数中硬编码。应引用 `TRADE_HUB_IDS["Jita"]`。

### L2 — 少量函数缺少 type hints

**文件**: `_replace_systems.py`、`build_release.py` 部分函数

---

## ✅ 验证结果

| 检查项 | 结果 | 备注 |
|---|---|---|
| ruff lint | ⏭ 跳过 | 建议运行 `ruff check .` |
| pytest | ⏭ 跳过 | 当前 7 个测试 |
| ruff format | ⏭ 跳过 | `ruff format . --check` |

---

## 📋 行动建议

**优先级 🔴 🟠:**
1. 立即修复 `scoring.py` 的白名单验证（C1）
2. 清理 `getitems.py` 重复 cancel（H2）
3. scoring 模块连接复用（H1）
4. 缓存加锁（H3）

**中等优先级 🟡:**
5. 路径标准化（M1）
6. 修复 launch.json（M2）
7. 补充测试（M3）

**建议 🟢:**
8. 常量提取（L1）
9. 丰富 type hints（L2）
