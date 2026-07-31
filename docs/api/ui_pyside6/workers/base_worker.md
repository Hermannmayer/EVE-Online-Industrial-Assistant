# ui_pyside6.workers.base_worker

> 源文件 `ui_pyside6/workers/base_worker.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

评分 Worker 基类 — 统一 QThread 模板，消除重复代码

## 类

### `class BaseScoreWorker`（继承 `QThread`）

单物品评分 Worker 基类 — 子类实现 _compute() → dict

定义行：`15`

#### 方法

##### `__init__`

```python
def __init__(self, type_id: int, *, char_config=None, char_name=None, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`20`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`25`
##### `_compute`

```python
def _compute(self) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`32`

### `class BaseBatchScoreWorker`（继承 `QThread`）

批量评分 Worker 基类 — 子类实现 _batch_calc(item) → dict

定义行：`36`

#### 方法

##### `__init__`

```python
def __init__(self, items: list, *, char_config=None, char_name=None, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`43`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`48`
##### `_calc_item`

```python
def _calc_item(self, item) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`67`
