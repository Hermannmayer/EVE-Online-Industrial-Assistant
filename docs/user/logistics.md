# 物流规划

物流规划功能帮助你评估跨区域货物运输的成本与利润。

## 核心概念

`services/logistics.py` 的 `LogisticsService` 提供：

1. **运费估算** — 根据体积、距离、抵押计算运输费用
2. **利润计算** — 综合考虑运费后的净利润
3. **路线距离** — 预置的贸易中心间跳跃数

## 运输模式

### 公开货运（第三方物流）

按 **体积 + 抵押价值** 计价，模拟 PushX、Red Frog 等公开货运公司：

```
运费 = 体积(m³) × 单价/跳 + 抵押价值 × 百分比
```

### 自有运输

按 **跳跃数** 计价，模拟自有货船运输：

```
运费 = 跳跃数 × 单跳燃料成本
```

## 预置贸易中心距离

应用内置了高安贸易中心之间的跳跃数（`TRADE_HUB_DISTANCES`）：

| 路线 | 跳跃数 |
|------|--------|
| Jita → Amarr | 72 |
| Jita → Dodixie | 12 |
| Jita → Rens | 18 |
| Amarr → Dodixie | 62 |
| Amarr → Rens | 60 |
| Dodixie → Rens | 30 |
| Hek → Amarr | 76 |
| Hek → Jita | 21 |
| Hek → Rens | 5 |

> 所有距离双向对称。

## 利润计算

完整利润计算考虑：

1. **商品买价** — 从来源 Hub 购入的价格
2. **商品卖价** — 在目标 Hub 卖出的价格
3. **运费** — 按上述模式估算
4. **交易税** — 经纪人费 + 销售税（受技能影响）
5. **净利润** = 卖出收入 - 买入成本 - 运费 - 交易税

## API 文档

详见 [`services/logistics.py`](/api/services/logistics) 的完整函数列表，包括：

- `get_distance_jumps(source, destination)` — 获取跳跃数
- `estimate_freight_cost(...)` — 运费估算
- `calc_trade_profit(...)` — 贸易利润计算
