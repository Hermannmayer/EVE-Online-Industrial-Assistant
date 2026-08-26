# ui_pyside6.workers.main_window_workers

> 源文件 `ui_pyside6/workers/main_window_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

主窗口后台 Worker — 价格更新与价格时效检查。

从 ui_pyside6/main_window.py 拆出，降低主窗口上帝类体积。

## 函数

### `needs_price_update`

```python
def needs_price_update(diff_seconds: float, interval_minutes: int) -> bool
```

价格是否过期需要更新（纯函数）。

定义行：`14`

## 类

### `class PriceUpdateWorker`（继承 `QThread`）

后台线程执行价格更新

定义行：`24`

#### 方法

##### `__init__`

```python
def __init__(self, regions: list[str] | None=None, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`29`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`33`

### `class PriceCheckWorker`（继承 `QThread`）

后台线程检查价格数据时效

定义行：`44`

#### 方法

##### `__init__`

```python
def __init__(self, interval_minutes: int=30, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`49`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`53`
