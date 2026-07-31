# core.container

> 源文件 `core/container.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

IOC 容器 — 持有所有依赖，由 Main.py 组装

## 函数

### `get_container`

```python
def get_container() -> AppContainer
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`227`

### `init_container`

```python
def init_container() -> AppContainer
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`236`

## 类

### `class AppContainer`

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`11`

#### 方法

##### `__init__`

```python
def __init__(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`12`
##### `db`

```python
def db(self) -> DatabaseManager
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`35`
##### `scoring_cache`

```python
def scoring_cache(self) -> TtlLRUCache
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`43`
##### `item_repo`

```python
def item_repo(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`51`
##### `market_repo`

```python
def market_repo(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`61`
##### `blueprint_repo`

```python
def blueprint_repo(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`71`
##### `plan_repo`

```python
def plan_repo(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`81`
##### `pricing_service`

```python
def pricing_service(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`91`
##### `bom_expander`

```python
def bom_expander(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`101`
##### `logistics_service`

```python
def logistics_service(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`111`
##### `scheduler`

```python
def scheduler(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`121`
##### `watchlist_manager`

```python
def watchlist_manager(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`131`
##### `inventory_manager`

```python
def inventory_manager(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`141`
##### `price_history_service`

```python
def price_history_service(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`151`
##### `scoring_service`

```python
def scoring_service(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`160`
##### `manufacturing_calculator`

```python
def manufacturing_calculator(self)
```

制造计算器（纯函数模块，无状态）

定义行：`170`
##### `char_config_resolver`

```python
def char_config_resolver(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`181`
##### `refining_service`

```python
def refining_service(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`212`
