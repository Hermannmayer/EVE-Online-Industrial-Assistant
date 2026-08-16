# ui_pyside6.workers.industry_page_workers

> 源文件 `ui_pyside6/workers/industry_page_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

工业页专用后台 Worker 与初始化辅助。

## 函数

### `init_plan_db`

```python
def init_plan_db()
```

初始化 production_plans 表。

定义行：`29`

## 类

### `class IndustryDataWorker`（继承 `QThread`）

后台线程拉取工业系统成本指数 + 设施数据

定义行：`13`

#### 方法

##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`18`

### `class PlanPriceRefreshWorker`（继承 `QThread`）

定向拉取计划涉及物品的 ESI 市场价格——带 5 分钟缓存

定义行：`41`

#### 方法

##### `__init__`

```python
def __init__(self, type_ids: set[int], parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`46`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`50`
##### `_fetch_and_save`

```python
async def _fetch_and_save(self) -> int
```

异步拉取 ESI + 写入 market.db（仅拉取缓存过期的物品）

定义行：`61`
