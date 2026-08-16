# services.procurement_service

> 源文件 `services/procurement_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

待采购计算服务 — 从生产计划/库存/价格计算采购清单。

## 函数

### `_resolve_item_name`

```python
def _resolve_item_name(mid: int, zh_name: str | None, en_name: str | None) -> str
```

统一物品名解析：item 表 → terminology.json → str(id)

定义行：`13`

### `calculate_procurement`

```python
def calculate_procurement(active_plans: list[dict], *, hangar_id: int, hub: str, price_type: str) -> tuple[list[dict], float, float]
```

计算待采购清单。

定义行：`25`
