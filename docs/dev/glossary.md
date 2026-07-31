# 术语表

EVE Online 游戏术语与本项目内部术语的中英文对照。

## 工业制造

| 中文 | 英文 | 说明 |
|------|------|------|
| 材料效率 | Material Efficiency (ME) | 蓝图 ME 等级，减少材料用量 |
| 技术效率 | Technical Efficiency (TE) | 蓝图 TE 等级，缩短生产时间 |
| 安装费 | Installation Fee | 制造任务的安装费用 |
| 系统成本指数 | System Cost Index (SCI) | 物流系统工业制造的成本倍率 |
| 设施税 | Facility Tax | 设施收取的制造税 |
| SCC 附加费 | SCC Surcharge | 共同商会上缴的额外费用 |
| 废品率 | Waste Factor | 制造过程中的材料浪费系数 |
| 预估物品价值 | Estimated Item Value (EIV) | 基于 adjusted_price 计算的物品价值 |
| 调整价格 | Adjusted Price | ESI 提供的 7 日加权平均价格 |
| 蓝图原件 | Blueprint Original (BPO) | 不可复制的蓝图原件 |
| 蓝图拷贝 | Blueprint Copy (BPC) | 可使用的蓝图副本 |
| 反应 | Reaction | 制造活动类型（混合/化合等） |
| 制造 | Manufacturing | 标准制造活动 |

## 贸易

| 中文 | 英文 | 说明 |
|------|------|------|
| 经纪人费 | Broker Fee | 卖单/买单挂单费用 |
| 销售税 | Sales Tax | 成交后缴纳的税 |
| 订单数 | Volume | 某价格方向的订单数量 |
| 买单 | Buy Order | 购买挂单 |
| 卖单 | Sell Order | 出售挂单 |
| 均价 | Average Price | 买卖加权平均价 |
| 贸易评分 | Trade Score | 多维度商品机会评分 |

## 物流

| 中文 | 英文 | 说明 |
|------|------|------|
| 跳跃数 | Jumps | 星系间航行次数 |
| 抵押价值 | Collateral | 公开货运要求的货物抵押 |
| 公开货运 | Public Freight | PushX / Red Frog 等第三方物流 |
| 自有运输 | Self Hauling | 用自己的货船运输 |

## 精炼

| 中文 | 英文 | 说明 |
|------|------|------|
| 精炼产出率 | Refining Yield | 矿石精炼为矿物的百分比 |
| 精炼技能 | Refining Skill | 角色精炼效率技能 |
| 植入体 | Implant | 工业植入体（精炼加成） |

## 数据源

| 中文 | 英文 | 说明 |
|------|------|------|
| 静态数据导出 | Static Data Export (SDE) | CCP 官方游戏数据库 |
| EVE 跨接口 | EVE Swagger Interface (ESI) | EVE Online REST API |
| 伏尔戈 | The Forge | Jita 所在星域（区域 ID: 10000002） |

## 项目内部术语

| 术语 | 说明 |
|------|------|
| Hub | 贸易中心（Jita / Amarr / Dodixie / Rens / Hek）|
| 个人利润率 | 考虑库存成本的综合利润率 |
| 定向刷新 | 仅拉取活跃计划涉及物品的价格 |
| 甘特图 | 生产进度时间线可视化 |
| 四库分离 | reference.db / market.db / blueprint.db / user.db |
| ATTACH DATABASE | SQLite 跨库联合查询机制 |
| IOC 容器 | AppContainer 统一管理服务依赖注入 |
| Conventional Commits | 语义化提交信息格式（feat:/fix:/…）|
| TtlLRUCache | 线程安全的 TTL + LRU 淘汰缓存 |
