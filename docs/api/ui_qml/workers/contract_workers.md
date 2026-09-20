# ui_qml.workers.contract_workers

> 源文件 `ui_qml/workers/contract_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

合同市场 — 后台 Worker 线程。

**两类写库任务互斥**：`ContractFetchWorker`（拉列表）与 `ContractFillWorker`（补物品）
都写 market.db，SQLite 是单写者 —— 桥在同一时刻只允许跑一个，见
`ui_qml/bridge/contract_bridge.py` 的 `_busy_worker`。

**只给真正慢的事开线程**：查库（最重一档实测 49 ms）走同步，不再开线程 ——
异步结果回来时视图可能正在销毁，实测会让 ui 档后续用例 `access violation`。
留在本模块的两件事都要打 ESI：拉列表（几十秒）与补物品（几万次请求、可中断）。

**线程生命周期与桥解耦**：桥随页面销毁，线程若还在跑会被连带析构，Qt 直接 abort。
所以 worker 一律 `parent=None`，由本模块的 `spawn()` 持强引用、跑完自摘；
对已销毁桥的信号投递由 Qt 自动断连兜底。

## 函数

### `spawn`

```python
def spawn(worker: QThread) -> QThread
```

启动 worker 并由本模块持有，直到它跑完。

定义行：`27`

## 类

### `class ContractFetchWorker`（继承 `QThread`）

拉取合同**列表**（不含物品）—— 每个星域拉完立刻落库。

定义行：`35`

#### 方法

##### `__init__`

```python
def __init__(self, region_ids: list[int], parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`40`
##### `run`

```python
def run(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`44`

### `class ContractFillWorker`（继承 `QThread`）

后台补齐 —— **先补发布者名字，再补物品详情**，分批拉、分批回写、可随时中断。

物品是「价差」列与图标列的前提，发布者名字是「去游戏里按发布者搜合同」的前提
（ESI 的合同端点只给 `issuer_id`，名字得另问 `/universe/names/`）。

两件事都可以由调用方**收窄范围**：自动补齐传当前列表的 id（一个星域 3.4 万份合同，
逐个打 ESI 没人等得起）；两个都不传则补整个星域 —— 手动「补齐全部」走这条。

定义行：`56`

#### 方法

##### `__init__`

```python
def __init__(self, region_id: int, contract_type: str, issuer_ids: list[int] | None=None, contract_ids: list[int] | None=None, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`69`
##### `stop`

```python
def stop(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`84`
##### `run`

```python
def run(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`87`

### `class ContractItemsLoadWorker`（继承 `QThread`）

加载某份合同的物品明细（含市价，供详情面板显示）。

定义行：`116`

#### 方法

##### `__init__`

```python
def __init__(self, contract_id: int, region_id: int=0, price_type: str='sell', parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`121`
##### `run`

```python
def run(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`127`
