# 价格与评分

## 价格查询

### 定价服务

`services/pricing_service.py` 的 `PricingService` 是所有价格查询的统一入口：

```python
from services.pricing_service import PricingService

pricing = PricingService(db)

# 查询单个物品价格
price = pricing.get_price(type_id=34, hub="Jita")
# 返回 {"sell_price": 5.2, "buy_price": 4.8, ...}

# 查询成交量
volume = pricing.get_volume(type_id=34, hub="Jita")

# 查询系统成本指数
sci = pricing.get_system_cost_index(solar_system_id=30000142, activity="manufacturing")

# 查询 ESI adjusted_price（7日均价）
adj_price = pricing.get_adjusted_price(type_id=34)
```

### 价格数据来源

| 数据 | 来源 | 说明 |
|------|------|------|
| 买单/卖单价格 | ESI `/markets/{region_id}/orders/` | 实时订单簿快照 |
| 成交量 | ESI `/markets/{region_id}/history/` | 每日成交量 |
| 调整价格 | ESI `/markets/prices/` | 7 日加权均价 |
| 系统成本指数 | ESI `/industry/systems/` | 各系统的工业制造成本指数 |

### 价格走势图

查询页面（`views/query/`）支持价格走势图功能：

- 从订单弹窗 → 点击「走势图」按钮
- 基于 `services/price_history.py` 的历史价格缓存
- 显示时间序列价格趋势

## 贸易评分

### 评分算法

`services/scoring_service.py` 的 `ScoringService` 提供多维度评分：

| 评分维度 | 公式 | 说明 |
|----------|------|------|
| 跨区域价差 | `(sell_price - buy_price) / buy_price` | 买入-卖出价差百分比 |
| 日均成交量 | ESI 历史数据平均值 | 流动性指标 |
| 税后利润 | 考虑经纪人费 + 销售税 | 实际可获利润 |
| 综合评分 | 加权各维度 | 0-100 分 |

### 角色技能影响

评分考虑角色技能等级：

- **贸易技能** → 影响经纪人费率
- **会计技能** → 影响销售税率
- **工业理论** → 影响制造时间与安装费

通过 `char_config.json` 管理多角色配置。

### 关注列表

`services/watchlist_manager.py` 提供关注列表功能：

- 添加关注物品，60 秒定时器检测价格变化
- 自动通知价格变动
- 保存关注列表到本地

## API 参考

- [`services/pricing_service.py`](/api/services/pricing_service)
- [`services/scoring_service.py`](/api/services/scoring_service)
- [`services/price_history.py`](/api/services/price_history)
