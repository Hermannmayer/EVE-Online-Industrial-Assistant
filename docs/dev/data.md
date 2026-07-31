# 数据格式

## SQLite 数据库结构

4 个独立 SQLite 文件，通过 `ATTACH DATABASE` 支持跨库查询。

### reference.db — 静态参考数据

从 CCP 官方 SDE 导入，只读：

| 表 | 关键字段 | 说明 |
|----|----------|------|
| `item` | type_id, zh_name, en_name, category_id, group_id, volume, icon_id, ... | 物品基础信息（16 字段） |
| `market_tree` | node_id, parent_id, name | 市场分类树 |
| `industry_system_costs` | solar_system_id, activity, cost_index | 工业系统成本指数 |
| `item_dogma` | type_id, attribute_id, value | 物品 dogma 属性 |
| `type_materials` | type_id, material_type_id, quantity | 矿石精炼材料表 |

### market.db — 市场价格数据

频繁覆写，~18 MB：

| 表 | 字段 | 说明 |
|----|------|------|
| `market_prices` | type_id, buy_price, sell_price, buy_volume, sell_volume, fetch_time | 实时订单价格快照 |
| `market_volume_snapshots` | type_id, volume, fetch_time | 成交量快照 |

### blueprint.db — 蓝图数据

从 SDE 导入，只读：

| 表 | 说明 |
|----|------|
| `blueprint_activities` | 蓝图活动信息（manufacturing/invention/copying 等） |
| `blueprint_materials` | 蓝图材料清单（含数量和 ME 信息） |
| `blueprint_products` | 蓝图产出（物品 ID、产出数量） |
| `blueprint_skills` | 蓝图所需技能 |

### user.db — 用户数据

增删改，随使用增长：

| 表 | 说明 |
|----|------|
| `hangars` | 机库定义（矿仓/组件仓/产品仓/通用仓库） |
| `inventory_items` | 库存物品（type_id, 数量, 加权平均成本） |
| `user_blueprints` | 用户蓝图（BPO/BPC, ME/TE, runs, quantity） |
| `production_plans` | 生产计划 |
| `user_skills` | 角色技能数据 |

## data/ 目录

运行时配置与缓存文件：

| 文件 | 说明 | 格式 |
|------|------|------|
| `data/settings.json` | 用户设置（主题、自动更新间隔等） | JSON |
| `data/char_config.json` | 多角色配置（技能、所在地、资金） | JSON |
| `data/score_settings.json` | 评分参数设置 | JSON |
| `data/search_history.json` | 搜索历史（最近 20 条） | JSON |
| `data/window_geometry.json` | 窗口位置和大小 | JSON |
| `data/update_progress.json` | 数据更新进度 | JSON |
| `data/caches/icons/` | 物品图标缓存 | PNG |
| `data/terminology.json` | EVE 术语映射表（技能名翻译等） | JSON |

## Schema 迁移

所有数据库 Schema 变更通过 `services/schema_migrations.py` 注册：

```python
# 全局版本号
DB_SCHEMA_VERSIONS = {"ref": 2, "mkt": 1, "bp": 1, "usr": 2}

# 迁移函数注册
MIGRATIONS = {
    "usr": {
        1: _migrate_user_v1_to_v2,  # 添加 cost_per_run 列
    },
    "ref": {
        1: _migrate_ref_v1_to_v2,
    },
}
```

启动时调用 `ensure_all_schemas()` 自动执行待应用的迁移。

> ⚠️ 禁止在业务代码中直接写 `ALTER TABLE`，必须通过迁移系统。

## SDE 数据来源

- **地址**：`https://sde.jita.space/latest`
- **格式**：ZIP 压缩包（含 YAML/JSON 数据）
- **首次启动**自动下载并导入 `reference.db` 和 `blueprint.db`

## ESI API 使用

| 接口 | 用途 |
|------|------|
| `/markets/{region_id}/orders/` | 市场订单簿（买单/卖单） |
| `/markets/{region_id}/history/` | 每日成交量历史 |
| `/markets/prices/` | ESI 调整价格（7日均价） |
| `/industry/systems/` | 工业系统成本指数 |
| `/universe/types/{type_id}/` | 物品详细信息 |
