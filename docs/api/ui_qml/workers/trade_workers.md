# ui_qml.workers.trade_workers

> 源文件 `ui_qml/workers/trade_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

贸易页面 — 后台 Worker 线程

## 类

### `class CrossRegionRankWorker`（继承 `QThread`）

A → B 全品类价差排行（含 B 侧挂单变化）。

定义行：`8`

#### 方法

##### `__init__`

```python
def __init__(self, region_a: int, region_b: int, side_a: str='sell', side_b: str='buy', group_ids: list[int] | None=None, change_days: int=7, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`13`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`31`
