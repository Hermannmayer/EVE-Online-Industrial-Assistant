# 外部数据依赖报告

## ESI API（7 个端点）

所有请求通过 `services/client.py` APIClient，基址 `esi.evetech.net/latest`。

| 端点 | 文件 | 用途 | 量级 |
|------|------|------|------|
| `/markets/{region}/orders/` | `getprices.py` | 4 贸易中心订单簿 | ~500 页/区域 |
| `/markets/prices/` | `getprices.py` | 全服均价兜底 | 1 次 |
| `/markets/{region}/history/` | `price_history.py` | 单物品历史价 | 按需 |
| `/contracts/public/{region}/` | `getcontracts.py` | 公开合同列表 | 分页 |
| `/contracts/public/items/{id}/` | `getcontracts.py` | 合同内物品 | 每合同 1 次 |
| `/industry/systems/` | `getindustry.py` | 全星系工业成本指数 | 1 次 |
| `/universe/names/` | 多点引用 | type_id → 名称反查 | 按需 |

问题：resolve_item_name 分散在 scoring_service、bom_expander、production_scheduler 多份实现，无统一层。

## SDE 静态数据

从 `https://eve-static-data-export.s3-eu-west-1.amazonaws.com/tranquility/sde.zip` 下载（~112MB），解析写入 reference.db。

### 已导入

| 表 | YAML 源 | 被谁用 |
|----|---------|--------|
| item | typeIDs.yaml | 全局名称查询 |
| blueprint_products/materials/activities | blueprints 包 | BOM 展开、制造评分 |
| market_groups | marketGroups.yaml | UI 物品树 |
| type_materials | typeMaterials.yaml | 精炼计算 |

### SDE 扩展（spec 已写但未实现）

文件 `specs/sde-integration-impl-spec.json` 已定方案，代码未落地。

| 表 | YAML 源 | 滞后影响 |
|----|---------|---------|
| region/constellation/solar_system/stargate | universe/ | **高** — logistics.py 跳数表硬编码 5 个 hub，无法扩展 |
| reprocessing_materials | typeMaterials.yaml | **高** — calc_refining_value 读 type_materials 表，字段名可能不匹配 |
| meta_group / category | metaGroups.yaml / categories.yaml | **中** — 评分系统无法按科技等级/类别过滤 |
| station | staStations.yaml | 低 — 物流缺准确位置 |
| dogma_attribute/effect | dogmaAttributes/Effects.yaml | 低 |
| icon_ids | iconIDs.yaml | 低 — UI 缺图标 |
| research_agent/npc_corporation/agent | researchAgents/Agents.yaml | 低 |

## 用户配置（本地，不联网）

| 来源 | 用途 |
|------|------|
| user.db → user_skills | 角色技能等级 |
| char_config.json | 市场设置（standing、经纪关系） |
| user.db → production_plans | 生产排程计划 |
| user.db → inventory_items | 库存 |
| user.db → watchlist_items | 价格监控 |
| user.db → user_blueprints | 蓝图（ME/TE） |

## 优先级

1. **SDE universe（星系+星门）** — 物流硬编码跳数表无法扩展，影响产品搜索的"距离过滤"
2. **SDE reprocessing_materials** — calc_refining_value 当前数据路径不确定
3. **用户头像下载（已有工作流）** — 现有方案
4. SDE meta/category — 过滤功能增强
5. SDE station/dogma/icon — 次要
