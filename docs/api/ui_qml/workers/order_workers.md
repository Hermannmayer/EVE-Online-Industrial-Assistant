# ui_qml.workers.order_workers

> 源文件 `ui_qml/workers/order_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

订单取数的共享部分：名称缓存 + ESI 线程。

原先是 `ui_pyside6/views/query/query_order_popup.py` 里订单弹窗的配套部分（6.0 拆到这里）。
订单弹窗已删除，本模块仍服务物品查询页的「订单列表」详情面板
（`QueryDetailBridge`）。`order_cache` 的**唯一写入方**是
`QueryDetailBridge._on_orders_fetched`。

## 类

### `class OrderFetchWorker`（继承 `QThread`）

后台获取 ESI 订单数据

定义行：`25`

#### 方法

##### `__init__`

```python
def __init__(self, type_id: int, region_id: int=10000002, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`31`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`36`
##### `_fetch`

```python
async def _fetch(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`55`
##### `_resolve_names`

```python
async def _resolve_names(self, location_ids: list[int]) -> None
```

location_id → 站名：**先查本地 SDE，只有本地没有的才打 ESI**。

定义行：`85`
##### `_resolve_names_remote`

```python
async def _resolve_names_remote(self, ids: list[int]) -> None
```

ESI `/universe/names/` 兜底（实际只会走到玩家建筑）。

定义行：`112`
##### `_resolve_names_one_by_one`

```python
async def _resolve_names_one_by_one(self, client, ids: list[int], url: str) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`143`
##### `_absorb`

```python
def _absorb(payload: list) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`160`
