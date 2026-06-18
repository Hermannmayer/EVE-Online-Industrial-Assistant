# items.db 拆分计划

> 当前 `database/items.db` 大小为 51 MB，单一 SQLite 文件包含 16 张表。
> 目标是拆分为多个独立的数据库文件，按数据生命周期和变更频率分离。

---

## 1. 当前状态分析

### 表大小分布

| 表 | 行数 | 估算大小 | 类别 |
|----|------|----------|------|
| market_volume_snapshots | 59,201 | ~10 MB | **价格历史** — 频繁覆写 |
| market_prices | 69,854 | ~8 MB | **实时价格** — 频繁覆写 |
| blueprint_materials | 36,193 | ~1.1 MB | **参考数据** — 一次性写入 |
| industry_system_costs | 32,910 | ~1.0 MB | **参考数据** — 一次性写入 |
| blueprint_skills | 22,252 | ~0.7 MB | **参考数据** — 一次性写入 |
| blueprint_activities | 19,023 | ~0.6 MB | **参考数据** — 一次性写入 |
| item | 18,373 | ~1.5 MB | **参考数据** — 一次性写入 |
| blueprint_products | 6,266 | ~0.2 MB | **参考数据** — 一次性写入 |
| market_tree | 2,092 | ~0.1 MB | **参考数据** — 一次性写入 |
| industry_facilities | 2,288 | ~0.1 MB | **参考数据** — 一次性写入 |
| user_skills | 13 | <0.1 MB | **用户数据** |
| hangars | 1 | <0.1 MB | **用户数据** |
| inventory_items | 0 | <0.1 MB | **用户数据** |
| production_plans | 0 | <0.1 MB | **用户数据** |

### 访问模式

- **参考数据** (item, blueprint_*, market_tree, industry_*, item_dogma) — 只读，一次性写入后永不修改
- **实时价格** (market_prices, market_volume_snapshots) — 频繁整表覆写
- **用户数据** (hangars, inventory_items, production_plans, user_skills) — 随用户操作增删改

---

## 2. 拆分方案

### 2.1 三个独立数据库

```text
database/
├── reference.db    ← 静态参考数据（SDE 数据，~4 MB）
├── market.db       ← 市场价格数据（可频繁覆写，~18 MB）
└── user.db         ← 用户自有数据（持久化，<1 MB）
```

### 2.2 表分配

| 目标库 | 包含的表 | 变更频率 | 当前大小 |
|--------|----------|----------|----------|
| **reference.db** | `item`, `market_tree`, `blueprint_activities`, `blueprint_materials`, `blueprint_products`, `blueprint_skills`, `industry_system_costs`, `industry_facilities`, `item_dogma` | 永不修改（除非 SDE 更新） | ~4 MB |
| **market.db** | `market_prices`, `market_prices_new`, `market_volume_snapshots` | 每次价格更新时重建 | ~18 MB |
| **user.db** | `hangars`, `inventory_items`, `production_plans`, `user_skills` | 随用户操作修改 | <1 MB |

### 2.3 拆分收益

| 效果 | 说明 |
|------|------|
| **数据库体积** | 从 51 MB → 各自独立，update/backup 只涉及关心的部分 |
| **更新时无需复制用户数据** | market.db 重建时不影响 user.db, reference.db |
| **用户数据持久化** | 重新安装/更新时只带 reference.db，user.db 保留 |
| **并发友好** | 写入 market.db 时不影响读 reference.db 的 UI |

---

## 3. 跨库查询分析

目前代码中有大量跨类别 JOIN，这是拆分的最大挑战。

### 3.1 跨库 JOIN 清单

| 涉及查询 | 跨库范围 | 出现在 | 处理方式 |
|----------|----------|--------|----------|
| item + market_prices | reference + market | `query_view.py`, `all_items_view.py`, `scoring.py`, `inventory_view.py` | ATTACH 或 Python 层 JOIN |
| blueprint_materials + market_prices + item | reference + market | `scoring.py`, `industry_view.py`, `all_items_view.py` | Python 层分步查询 |
| inventory_items + market_prices + item | user + market + reference | `inventory_manager.py`, `inventory_view.py` | ATTACH 或 Python 层 JOIN |
| production_plans + blueprint_products + blueprint_materials + market_prices + item | user + reference + market | `industry_view.py` | Python 层分步查询 |

### 3.2 推荐方案：ATTACH DATABASE

SQLite 支持在连接后附加其他数据库：

```python
conn = sqlite3.connect("database/user.db")
conn.execute("ATTACH DATABASE 'database/reference.db' AS ref")
conn.execute("ATTACH DATABASE 'database/market.db' AS mkt")

# 跨库查询
cur = conn.execute("""
    SELECT i.type_id, i.en_name, p.buy_price, p.sell_price
    FROM ref.item i
    JOIN mkt.market_prices p ON i.type_id = p.type_id
""")
```

这样修改最小，只需在连接后增加 ATTACH 语句，表名加上库名前缀。

---

## 4. 迁移方案

### 4.1 核心改造点

| 文件 | 修改内容 |
|------|----------|
| `core/paths.py` | 新增 `REFERENCE_DB`, `MARKET_DB`, `USER_DB` 三个路径变量 |
| `services/database_manager.py` | **新建** — 数据库管理器，封装多库连接和 ATTACH 逻辑 |
| `services/workers/getitems.py` | 改为写入 `reference.db`（去掉 `item`, `market_tree`） |
| `services/workers/getblueprints.py` | 改为写入 `reference.db`（去掉 `blueprint_*`） |
| `services/workers/getindustry.py` | 改为写入 `reference.db`（去掉 `industry_*`） |
| `services/workers/getimplantdata.py` | 改为写入 `reference.db`（去掉 `item_dogma`） |
| `services/workers/getprices.py` | 改为写入 `market.db`（去掉 `market_prices`, `market_volume_snapshots`） |
| `services/inventory_manager.py` | 改为读写 `user.db`，ATTACH `reference.db` 和 `market.db` |
| `services/scoring.py` | 改为使用 `database_manager` 获取连接 |
| `services/init_check.py` | 分别检查三个库 |
| `Main.py` | 迁移逻辑改为分库迁移 |
| `ui_pyside6/*.py` | 全部改为通过 `database_manager` 获取连接 |

### 4.2 推荐：新建 DatabaseManager 层

创建 `services/database_manager.py`，集中管理所有数据库连接：

```python
# 核心接口
class DatabaseManager:
    def __init__(self, ref_path, mkt_path, user_path):
        self.paths = {"ref": ref_path, "mkt": mkt_path, "user": user_path}

    def get_connection(self, *dbs):
        """获取连接，自动 ATTACH 需要的库。
        用法: get_connection('ref', 'mkt') 返回 conn，ref 和 mkt 已附加
        """
        primary = dbs[0]
        conn = sqlite3.connect(self.paths[primary])
        for db in dbs[1:]:
            conn.execute(f"ATTACH DATABASE '{self.paths[db]}' AS {db}")
        conn.row_factory = sqlite3.Row
        return conn
```

### 4.3 渐进式迁移步骤

**Phase 1 — 基础设施（不动业务逻辑）**
1. `core/paths.py` 新增三个路径
2. 新建 `services/database_manager.py`
3. 所有 UI 文件从 `sqlite3.connect(DB_PATH)` 切换到 `db_manager.get_connection()`
4. 通过 ATTACH 保持跨库 JOIN 正常工作

**Phase 2 — 数据迁移脚本**
1. `scripts/migrate_split_db.py` — 从旧 `items.db` 导出数据到三个新库
2. 保留原 `items.db` 作为回退

**Phase 3 — 改写 Worker（数据写入层）**
1. `getitems.py` → 只写入 `reference.db`
2. `getblueprints.py` → 只写入 `reference.db`
3. `getindustry.py` → 只写入 `reference.db`
4. `getimplantdata.py` → 只写入 `reference.db`
5. `getprices.py` → 只写入 `market.db`

**Phase 4 — 改写 Service 层（数据读取层）**
1. `inventory_manager.py` → 使用 ATTACH 读写 user + ref + mkt
2. `scoring.py` → 使用 ATTACH

**Phase 5 — 清理**
1. 更新 `init_check.py`
2. 更新 `.gitignore`（如果 database 目录的文件需要改动）
3. 更新 `Main.py` 启动逻辑

---

## 5. 风险和避坑

| 风险 | 缓解措施 |
|------|----------|
| Windows 路径问题 | `ATTACH` 要求路径用正斜杠或转义反斜杠，用 `pathlib.Path.as_posix()` |
| 事务跨库 | SQLite 不支持跨文件事务。所有写入操作需保持在单一库内 |
| 并发写入 | 三个独立文件，每个支持单独 WAL 模式。`PRAGMA journal_mode=WAL` |
| item_dogma 表可能不存在 | 由 getimplantdata.py 按需创建，参考库的 init 逻辑需兼容 |
| 引用模式的改动范围 | 全部 16+ Python 文件都需要改 import/connection 调用 |

---

## 6. 不拆分但也可行的替代方案

如果觉得改造量太大，也可以考虑：

1. **VACUUM + WAL 模式** — 打开 `PRAGMA journal_mode=WAL`，定期 VACUUM
2. **备份时排除 market_prices** — 在 build_release.py 中备份时跳过价格表
3. **.gitignore 细分** — 将 market_prices/volume_snapshots 排除出版本控制（虽然现在也没进 git）

这些方案改动量约为拆分方案的 10%，但不能解决"更新时重写整库"和"用户数据与参考数据混在一起"的根本问题。

---

## 7. 文件改动清单（完整）

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `core/paths.py` | **修改** | 新增 3 个 DB 路径常量 |
| `services/database_manager.py` | **新建** | 核心多库连接管理器 |
| `services/inventory_manager.py` | **修改** | 改用 manager，ATTACH 价格/参考库 |
| `services/scoring.py` | **修改** | 改用 manager |
| `services/init_check.py` | **修改** | 3 个库分别检查 |
| `services/workers/getitems.py` | **修改** | 改为写 reference.db |
| `services/workers/getblueprints.py` | **修改** | 改为写 reference.db |
| `services/workers/getprices.py` | **修改** | 改为写 market.db |
| `services/workers/getindustry.py` | **修改** | 改为写 reference.db |
| `services/workers/getimplantdata.py` | **修改** | 改为写 reference.db |
| `services/workers/geticon.py` | **修改** | 只用 reference.db 的 item 表 |
| `Main.py` | **修改** | 启动/迁移逻辑 |
| `ui_pyside6/main_window.py` | **修改** | 改为 manager 连接 |
| `ui_pyside6/views/query_view.py` | **修改** | 改为 manager 连接 |
| `ui_pyside6/views/all_items_view.py` | **修改** | 改为 manager 连接 |
| `ui_pyside6/views/industry_view.py` | **修改** | 改为 manager 连接 |
| `ui_pyside6/views/inventory_view.py` | **修改** | 改为 manager 连接 |
| `ui_pyside6/views/char_settings_view.py` | **修改** | 改为 manager 连接 |
| `scripts/migrate_split_db.py` | **新建** | 数据迁移脚本 |
| `build_release.py` | **修改** | 更新打包逻辑，包含 3 个库 |
| `.gitignore` | **检查** | market.db 可放进 gitignore |
