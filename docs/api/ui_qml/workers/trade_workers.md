# ui_qml.workers.trade_workers

> 源文件 `ui_qml/workers/trade_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

贸易页面 — 后台 Worker 线程

## 函数

### `spawn`

```python
def spawn(worker: QThread) -> QThread
```

保活运行中的排行线程，避免桥替换引用时 QThread 被提前析构。

定义行：`11`

## 类

### `class CrossRegionRankWorker`（继承 `QThread`）

A → B 全品类价差排行（含 B 侧挂单变化 + 两端的日成交量）。

定义行：`19`

#### 方法

##### `__init__`

```python
def __init__(self, region_a: int, region_b: int, side_a: str='sell', side_b: str='buy', group_ids: list[int] | None=None, change_days: int=7, parent=None)
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

定义行：`43`
##### `_attach_volumes`

```python
def _attach_volumes(self, rows: list[dict]) -> None
```

两端各自的近 7 日平均成交量 —— **只读本地 `price_history`，零 ESI 请求**。

定义行：`64`
