# 数据库 ER 图

## 四库关系总览

```mermaid
erDiagram
    %% ── reference.db（静态参考数据）──
    item {
        INTEGER type_id PK
        TEXT zh_name
        TEXT en_name
        INTEGER category_id
        INTEGER group_id
        REAL volume
        INTEGER icon_id
        INTEGER market_group_id
        INTEGER meta_group_id
    }
    market_tree {
        INTEGER node_id PK
        INTEGER parent_id
        TEXT name
    }
    industry_system_costs {
        INTEGER solar_system_id
        TEXT activity
        REAL cost_index
    }
    item_dogma {
        INTEGER type_id FK
        INTEGER attribute_id
        REAL value
    }
    type_materials {
        INTEGER type_id FK
        INTEGER material_type_id FK
        INTEGER quantity
    }

    %% ── market.db（市场价格）──
    market_prices {
        INTEGER type_id FK
        REAL buy_price
        REAL sell_price
        INTEGER buy_volume
        INTEGER sell_volume
        TEXT fetch_time
    }
    market_volume_snapshots {
        INTEGER type_id FK
        INTEGER volume
        TEXT fetch_time
    }

    %% ── blueprint.db（蓝图数据）──
    blueprint_activities {
        INTEGER blueprint_type_id FK
        TEXT activity
        INTEGER time
    }
    blueprint_materials {
        INTEGER blueprint_type_id FK
        TEXT activity
        INTEGER type_id FK
        INTEGER quantity
    }
    blueprint_products {
        INTEGER blueprint_type_id FK
        TEXT activity
        INTEGER type_id FK
        INTEGER quantity
    }
    blueprint_skills {
        INTEGER blueprint_type_id FK
        TEXT activity
        INTEGER skill_id FK
        INTEGER level
    }

    %% ── user.db（用户数据）──
    hangars {
        INTEGER id PK
        TEXT name UK
        TEXT notes
    }
    inventory_items {
        INTEGER id PK
        INTEGER hangar_id FK
        INTEGER type_id FK
        INTEGER quantity
        REAL cost_price
        TEXT created_at
    }
    user_blueprints {
        INTEGER id PK
        INTEGER hangar_id FK
        INTEGER blueprint_type_id FK
        INTEGER is_bpo
        INTEGER me_level
        INTEGER te_level
        INTEGER runs
        INTEGER quantity
        TEXT notes
    }
    production_plans {
        INTEGER id PK
        TEXT plan_name
        INTEGER blueprint_type_id FK
        INTEGER quantity
        INTEGER me_level
    }
    user_skills {
        INTEGER id PK
        TEXT skill_name
        INTEGER level
    }

    %% ── 关系 ──
    item ||--o{ item_dogma : "has dogma"
    item ||--o{ type_materials : "refines into"
    item ||--o{ market_prices : "priced at"
    item ||--o{ market_volume_snapshots : "volumed at"
    market_tree ||--o{ item : "categorizes"
    item ||--o{ blueprint_products : "produced by"
    item ||--o{ blueprint_materials : "required by"
    blueprint_activities ||--o{ blueprint_materials : "has materials"
    blueprint_activities ||--o{ blueprint_products : "has products"
    blueprint_activities ||--o{ blueprint_skills : "requires skills"
    hangars ||--o{ inventory_items : "stores"
    hangars ||--o{ user_blueprints : "stores"
    type_materials }o--|| item : "material is item"
```

## 跨库查询

`services/database_manager.py` 通过 `ATTACH DATABASE` 统一管理 4 个库的连接别名：

| 别名 | 库文件 | 示例跨库查询 |
|------|--------|-------------|
| `ref` | reference.db | `SELECT zh_name FROM ref.item WHERE type_id = ?` |
| `mkt` | market.db | `SELECT sell_price FROM mkt.market_prices WHERE type_id = ?` |
| `bp` | blueprint.db | `SELECT * FROM bp.blueprint_materials WHERE blueprint_type_id = ?` |
| `usr` | user.db | `SELECT * FROM usr.inventory_items WHERE hangar_id = ?` |

跨库 JOIN 示例：
```sql
SELECT i.zh_name, mp.sell_price, ui.quantity
FROM ref.item i
JOIN mkt.market_prices mp ON i.type_id = mp.type_id
LEFT JOIN usr.inventory_items ui ON i.type_id = ui.type_id AND ui.hangar_id = 1
WHERE i.type_id = 34
```
