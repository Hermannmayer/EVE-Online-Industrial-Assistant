# ui_qml.workers.order_workers

> 源文件 `ui_qml/workers/order_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

订单取数的共享部分：缓存 + ESI 线程。

原先在 `ui_pyside6/views/query/query_order_popup.py`，与 OrderPopup（Widgets 悬浮窗）同处一文件；
QML 版订单弹窗复用同一份缓存与线程，故拆出来。

## 函数

### `get_order_name`

```python
def get_order_name(page, type_id: int) -> str
```

根据 type_id 从页面的模型中查找物品名称

定义行：`100`

### `_on_orders_fetched`

```python
def _on_orders_fetched(page, type_id: int, buy_orders: list, sell_orders: list)
```

订单获取完成后的处理

定义行：`114`

### `_on_order_error`

```python
def _on_order_error(page, type_id: int, error: str)
```

订单获取出错处理

定义行：`123`

## 类

### `class OrderFetchWorker`（继承 `QThread`）

后台获取 ESI 订单数据

定义行：`19`

#### 方法

##### `__init__`

```python
def __init__(self, type_id: int, region_id: int=10000002, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`25`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`30`
##### `_fetch`

```python
async def _fetch(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`49`
##### `_resolve_names`

```python
async def _resolve_names(self, location_ids: list[int])
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`77`
