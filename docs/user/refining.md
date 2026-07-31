# 精炼计算

精炼计算功能帮助你评估将矿石/冰矿精炼为矿物的价值与利润。

## 核心功能

`services/refining_service.py` 的 `RefiningService` 提供：

- **精炼产出率计算** — 基于角色技能、设施类型、植入体加成
- **精炼价值计算** — 输入物品精炼后的矿物价值
- **利润评估** — 精炼产出价值 vs 原矿买入成本

## 精炼产出率

产出率受以下因素影响（`core.eve_formulas.calc_refining_yield()`）：

| 因素 | 说明 |
|------|------|
| 角色精炼技能 | 基础产出率的主要影响 |
| 玩家设施加成 | 玩家拥有的设施额外加成 |
| 站点基础产出率 | 空间站基础精炼效率 |
| 植入体加成 | 工业植入体的额外产出率 |
| 矿石处理技能 | 每级 +2% 产出率加成 |
| 上限 | 产出率上限 85% |

## 使用示例

```python
from services.refining_service import RefiningService

service = RefiningService(db)
result = service.calc_value(
    type_id=1230,        # 矿石 type_id
    quantity=1000,       # 数量
    skills={"精炼": 5, "精炼效率": 5},
    price_hub="Jita",
)
print(result["yield_rate"])     # 产出率
print(result["output"])         # 精炼产出矿物列表
print(result["total_value"])    # 产出总价值
print(result["profit"])         # 精炼利润
print(result["margin_pct"])     # 利润率百分比
```

## 返回结构

| 字段 | 说明 |
|------|------|
| `yield_rate` | 最终产出率（0.0~0.85） |
| `output` | 输出矿物列表，每项含 `type_id`、`name`、`quantity`、`value` |
| `total_value` | 精炼产出的总市场价值 |
| `input_value` | 输入原矿的市场价值 |
| `profit` | 精炼利润 = total_value - input_value |
| `margin_pct` | 利润率百分比 |

## API 参考

详见 [`services/refining_service.py`](/api/services/refining_service)。
