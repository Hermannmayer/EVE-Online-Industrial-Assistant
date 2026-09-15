# ui_pyside6.workers.npc_seller_workers

> 源文件 `ui_pyside6/workers/npc_seller_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

蓝图 NPC 卖家查询的后台 Worker。

原先定义在 `ui_pyside6/dialogs/npc_seller_dialog.py` 里（对话框与线程同文件）。
对话框迁到 QML 后那个模块被删除，线程按项目约定挪到 `ui_pyside6/workers/`。

## 函数

### `npc_seller_rows`

```python
def npc_seller_rows(orders: list[dict], npc_ids: set[int], corp_names: dict[int, str], stations: dict[int, tuple[str, str]]) -> list[dict]
```

ESI 卖单 → 表格行（按价格升序）。纯函数，便于单测。

定义行：`26`

## 类

### `class NpcOrderWorker`（继承 `QThread`）

后台拉取指定蓝图的 ESI 卖单并按 NPC 公司过滤。

定义行：`57`

#### 方法

##### `__init__`

```python
def __init__(self, region_id: int, blueprint_type_id: int, parent: Any=None) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`62`
##### `run`

```python
def run(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`67`
