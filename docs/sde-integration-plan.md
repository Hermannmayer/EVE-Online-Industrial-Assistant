# SDE 数据集成 — 功能补全与开发路线图

> 基于三个 Agent 对现有代码库的交叉分析
> - 🔵 sde-industry: metaGroups / typeMaterials / categories / graphicIDs
> - 🟢 sde-logistics: staStations / stationOperations / universe / dogmaEffects
> - 🟡 sde-data: dogmaAttributes / iconIDs / researchAgents / npcCorporations / agents

---

## 架构总览

```
sde_cache.py (共享)
  ├── ensure_sde_cache()    ← 一次性下载 112MB zip，缓存所有 YAML
  ├── load_yaml(filename)   ← CLoader 解析
  └── YAML_FILES 集合       ← 在此新增文件名即可自动缓存

各 Worker 在 init_db/ensure_sde_cache 后调用新增的 write_*_tables() 函数
所有新表写入 reference.db（DatabaseManager DB_PATH_MAP["ref"]）
```

---

## Phase 1 — 数据增强（不改 UI 结构）

### 1.1 metaGroups.yaml (5.5KB) — 科技等级

**Agent 发现**:
- `inventory_manager.py:502-514` 现有 `get_blueprint_tech_levels()` 通过「是否有 invention 活动」推导 T1/T2/T3，漏掉了势力/死亡/官员
- `all_items_view.py:696-703` 用 `LIKE '%Navy%'` 模糊匹配识别势力装备，脆弱
- `char_settings_view.py:259-310` 也只是用了 item 表查询，没有科技等级过滤

**新表**:
```sql
CREATE TABLE meta_group (
    meta_group_id INTEGER PRIMARY KEY,
    en_name TEXT, zh_name TEXT
);
-- item 表加 meta_group_id 列（ALTER TABLE）
```

**写入**: `getitems.py` 的 `write_items()` 中从 `typeIDs.yaml` 提取 `metaGroupID` 字段（已在 YAML 中但未读取）。

**替换**:
- `inventory_manager.get_blueprint_tech_levels()` → 直接 `SELECT meta_group_id FROM item WHERE type_id=?`
- `all_items_view` 的 `LIKE '%Navy%'` → `WHERE meta_group_id = ?`

**工作量**: ~30 行

---

### 1.2 typeMaterials.yaml (2.0MB) — 分解材料

**Agent 发现**: 全代码库不存在任何分解/精炼逻辑。`bom_expander.py`, `procurement_tab.py`, `scoring_service.py` 全部只管制造材料。

**新表**:
```sql
CREATE TABLE reprocessing_materials (
    type_id INTEGER NOT NULL,
    material_type_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (type_id, material_type_id)
);
```

**影响**:
- `scoring_service.py`: 分解价值作为制造评分中的价格下限（Price Floor）
- `procurement_tab.py`: 比较「买原料做」vs「买成品拆」
- 后续：分解计算器 UI

**写入**: 新增 `write_type_materials()`，从 `typeMaterials.yaml` 逐条写入。

**工作量**: ~50 行

---

### 1.3 dogmaAttributes.yaml (1.1MB) — 属性名称

**Agent 发现**:
- `char_settings_view.py:283-310` 硬编码了**仅 10 个** attribute ID 到中文名的映射字典
- 其他所有植入体属性显示为原始数字
- `item_dogma` 表存的是 JSON，包含所有 attribute_id + value，但缺名称

**新表**:
```sql
CREATE TABLE dogma_attribute (
    attribute_id INTEGER PRIMARY KEY,
    name TEXT,
    display_name TEXT,
    unit_id INTEGER
);
```

**影响**:
- `_parse_implant_bonus()` 改为从 `dogma_attribute` 表查询名称 + 单位
- 所有植入体属性可读显示，不再只有 10 个
- 后续舰船/装备属性面板同理

**工作量**: ~80 行（新 worker `getdogmaattrs.py`）+ 30 行 UI 重构

---

### 1.4 iconIDs.yaml (547KB) — 图标去重

**Agent 发现**:
- `geticon.py` 下载 `{type_id}.png`，但相同 iconID 的 type_id 会重复下载
- `typeIDs.yaml` 已存 `iconID` 字段，`getitems` 已写入 `item.iconID` 列
- `iconIDs.yaml` 提供 iconID → iconFile 映射

**做法**: 保留 `{type_id}.png` 文件名（不破坏现有引用），下载前 GROUP BY `item.iconID` 去重，相同 iconID 只下载一次后复制/硬链接。

**不要改成 `{iconID}.png`** — 所有现有 UI 代码引用 `{type_id}.png` 路径（inventory 页面、all_items_view、manufacturable_items_dialog），改动面太大。

**写入**: `icon_ids` 表（iconID → iconFile），供后续其他用途。

**工作量**: ~30 行

---

## Phase 2 — 物流基础设施

### 2.1 staStations.yaml (2.4MB) — 空间站

**Agent 发现**:
- `query_order_popup.py:77-98` 用 `_station_name_cache: dict[int, str] = {}` 调 ESI `/universe/names/` 按需查空间站名，重启丢失
- `industry_dialogs.py:54-56` 的设施字段是 `QLineEdit` 自由输入，无验证
- `plan_edit_dialog.py:79-82` 同理
- `industry_facilities` 表（来自 ESI）有 facility_id 但没有 station_name

**新表**:
```sql
CREATE TABLE station (
    station_id INTEGER PRIMARY KEY,
    station_name TEXT,
    solar_system_id INTEGER,
    operation_id INTEGER,
    station_type_id INTEGER,
    corporation_id INTEGER
);
```

**影响**:
- 替换 `query_order_popup.py` 的 ESI 名称解析（仅对玩家建筑降级到 ESI）
- 工业设施选择从 `QLineEdit` 改为 `QComboBox`，列出有制造服务的空间站

**工作量**: ~80 行

### 2.2 stationOperations.yaml (137KB) + stationServices.yaml (6KB)

**新表**:
```sql
CREATE TABLE station_operation (
    operation_id INTEGER PRIMARY KEY,
    en_name TEXT, zh_name TEXT
);
CREATE TABLE station_operation_service (
    operation_id INTEGER,
    service_id INTEGER,
    PRIMARY KEY (operation_id, service_id)
);
CREATE TABLE station_service (
    service_id INTEGER PRIMARY KEY,
    service_name TEXT
);
```

**影响**: 筛选有 `Manufacturing` 服务的空间站作为设施选项。

**工作量**: ~30 行（合并在 station worker 中）

### 2.3 universe/ 星系数据 (~50000 YAMLs)

**Agent 发现**:
- `_replace_systems.py` 用 `solar_system_id` 当 `type_id` 查 item 表——很多星系查不到
- `core/constants.py` 的 `TRADE_HUB_IDS` 硬编码 5 个区域
- `services/logistics.py:27-42` 的 `TRADE_HUB_DISTANCES` 硬编码 10 条距离，只覆盖 5 个 hub
- `core/eve_formulas.py:75-79` 的 `_hub_region_id()` 也是硬编码

**新表**:
```sql
CREATE TABLE region (
    region_id INTEGER PRIMARY KEY, region_name TEXT
);
CREATE TABLE constellation (
    constellation_id INTEGER PRIMARY KEY, constellation_name TEXT, region_id INTEGER
);
CREATE TABLE solar_system (
    solar_system_id INTEGER PRIMARY KEY, solar_system_name TEXT,
    region_id INTEGER, constellation_id INTEGER, security_status REAL
);
CREATE TABLE stargate (
    stargate_id INTEGER PRIMARY KEY,
    solar_system_id INTEGER, destination_system_id INTEGER
);
```

**写入方式**: 遍历 zip 中的 `universe/` 目录，不是展开 50000 个文件到磁盘。

**影响**:
- `services/logistics.py`: 用 Dijkstra/A\* 在 stargate 图上算真实路由，替代硬编码距离
- 物流支持任意两个星系间的路线计算
- 删除 `_replace_systems.py`

**工作量**: ~150 行

---

## Phase 3 — 高级功能

### 3.1 researchAgents.yaml (28KB) + npcCorporations.yaml (1.7MB) + agents.yaml (1.3MB)

**Agent 发现**: 全代码库不存在发明成本计算。`scoring_service.py` 有 `calc_manufacturing_score()` 和 `calc_reaction_score()` 但没有 `calc_invention_score()`。

**用途**:
- `blueprint_materials WHERE activity='invention'` 已有数据核心的需求量
- 市场价查询已有（`get_price()`）
- `blueprint_products.probability` 已有成功率
- 缺的是数据核心的 base cost（来自 `researchAgents.researchCostModifier`）

**新表**:
```sql
CREATE TABLE research_agent (
    agent_id INTEGER PRIMARY KEY,
    corporation_id INTEGER,
    skill_type_id INTEGER,
    research_cost_modifier REAL
);
```

**影响**:
- 新增 `calc_invention_score()` → T2 评分时加入：数据核心成本 × 需求量 / 成功率 + 解密器具成本
- `cost_breakdown_dialog.py` 可展开显示发明成本明细

**工作量**: ~300 行（数据层 + 评分逻辑 + UI 展示）

### 3.2 dogmaEffects.yaml (1.9MB)

**用途**: 配合 dogmaAttributes 实现完整可读的植入体/装备属性面板。

**新表**:
```sql
CREATE TABLE dogma_effect (
    effect_id INTEGER PRIMARY KEY,
    effect_name TEXT,
    description TEXT,
    icon_id INTEGER
);
```

**工作量**: ~50 行

---

## Phase 4 — 现有表增强

### 4.1 categories.yaml (9.6KB) — 物品分类

**Agent 发现**: `groups.yaml` 中每个 group 已有 `categoryID` 字段，但 `write_items()` 的 `_build_group_lookup()` 只提取了名称丢弃了 categoryID。

**做法**: 不需要额外文件。在 `write_items()` 中构建 `{group_id → category_id}` 查找表即可。
如果要 categories 表：
```sql
CREATE TABLE category (
    category_id INTEGER PRIMARY KEY,
    en_name TEXT, zh_name TEXT
);
```

**影响**:
- `getimplantdata.py` 的硬编码 `INDUSTRY_GROUP_NAMES` 可改为 `category_id=20`
- `all_items_view.py` 可加分类过滤

**工作量**: ~20 行

---

## 汇总：总工作量 ~900 行

| 序号 | 功能 | 文件 | 工作量 | 前置 | 优先级 |
|------|------|------|--------|------|--------|
| 1.1 | metaGroups 科技等级 | `getitems.py` + `inventory_manager.py` + `all_items_view.py` | ~30 | 无 | **P0** |
| 1.2 | typeMaterials 分解材料 | `getitems.py` + `scoring_service.py` | ~50 | 无 | **P1** |
| 1.3 | dogmaAttributes 属性名称 | `sde_cache.py` + 新 `getdogmaattrs.py` + `char_settings_view.py` | ~110 | 无 | **P1** |
| 1.4 | iconIDs 图标去重 | `sde_cache.py` + `geticon.py` | ~30 | getitems typeIDs 写完 | **P0** |
| 2.1 | staStations 空间站 | `sde_cache.py` + 新 `getstations.py` + `query_order_popup.py` | ~110 | 无 | **P2** |
| 2.2 | stationOperations 设施选择 | 同上 | ~30 | 2.1 | P2 |
| 2.3 | universe 星系路由 | 新 `getuniverse.py` + `logistics.py` + `_replace_systems.py`(删) | ~150 | 2.1 | **P2** |
| 3.1 | researchAgents 发明评分 | 新 `getagentdata.py` + `scoring_service.py` + `cost_breakdown_dialog.py` | ~300 | 1.1 (T2判定) | P3 |
| 3.2 | dogmaEffects 效果可读 | `sde_cache.py` + 合入 getdogmaattrs | ~50 | 1.3 | P3 |
| 4.1 | categories 分类 | `getitems.py`（复用已有 groupIDs 数据）| ~20 | 无 | P4 |

---

## 关键发现汇总（三个 Agent 交叉确认）

| 问题 | Agent | 现有代码位置 | 修复方式 |
|------|-------|-------------|---------|
| 科技等级用推导不准确 | 🔵 sde-industry | `inventory_manager.py:502-514` | `metaGroups.yaml` 直接查 |
| 势力物品用 LIKE 模糊匹配 | 🔵 sde-industry | `all_items_view.py:696-703` | 替换为 `meta_group_id` 查询 |
| 分解价值完全不存在 | 🔵 sde-industry | 全代码库 | `typeMaterials.yaml` 新表 |
| 属性名称仅 10 个硬编码 | 🟡 sde-data | `char_settings_view.py:283-310` | `dogmaAttributes.yaml` 替换 |
| 图标按 type_id 重复下载 | 🟡 sde-data | `geticon.py` | `iconIDs.yaml` 去重 |
| 空间站名调 ESI 重启丢失 | 🟢 sde-logistics | `query_order_popup.py:77-98` | `staStations.yaml` 本地化 |
| 设施字段是自由输入 | 🟢 sde-logistics | `industry_dialogs.py:54-56` | 改为 QComboBox + 空间站列表 |
| 星系名称查 item 表不可靠 | 🟢 sde-logistics | `_replace_systems.py` | `universe/` 数据 |
| 物流距离硬编码 10 条 | 🟢 sde-logistics | `logistics.py:27-42` | stargate 图路由 |

---

## 推荐实施批次

```
Batch 1（本次会话）: sde_cache.py 扩展现有 YAML_FILES + metaGroups 写入 + iconIDs 写入
Batch 2: typeMaterials 写入 + dogmaAttributes 写入 + char_settings 可读化
Batch 3: staStations 写入 + stationOperations 写入 + query_order_popup 改造 + 设施下拉
Batch 4: universe 星系写入 + logistics 路由重写
Batch 5: researchAgents 写入 + invention scoring
Batch 6: dogmaEffects + categories 收尾
```
