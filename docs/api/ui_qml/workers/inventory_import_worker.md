# ui_qml.workers.inventory_import_worker

> 源文件 `ui_qml/workers/inventory_import_worker.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

库存剪贴板导入的后台线程 —— 解析/取数与落库/差异汇总都不再压主线程。

用户报障：「库存修正会导致整个软件**卡死**并进行计算。这个计算应该放在后台，不应该阻塞主界面。」

主线程原先同步做完这些活（整仓粘贴时都是秒级）：
1. ``parse_clipboard(raw)`` → ``search_item_type_ids_batch``（几百行名字批量匹配）+ 蓝图行过滤；
2. ``get_items(hangar, include_derived=False)`` 的导入前快照（名称 JOIN + 排序）；
3. 预览对话框里的整库现存量与整仓卖价取数；
4. 确认后的 ``apply_inventory_import``（几百行一个事务）+ 导入后快照 + ``compute_import_diff``。

现在 1–3 走 `InventoryImportFetchWorker`、4 走 `InventoryImportApplyWorker`：
主线程只负责弹预览/汇总对话框与忙碌光标，DB 与解析全在 worker 线程里跑。

**为什么用「起线程 + 等结果」而不是像蓝图那样 fire-and-forget**：两个现成调用方
（``ui_qml/bridge/inventory_bridge.py::runClipboardImport``、``ui_qml/views/procurement_tab.py``）
都在 ``run_clipboard_import(...)`` 返回后紧接着刷新自己的列表，即**依赖它是同步返回**的。
改成完全异步就得让调用方在回调里刷新，而那两个文件不在本任务的写范围里；
``review_bridge._wait_worker`` 用嵌套 ``QEventLoop`` 等 worker 结束（不是
``processEvents()`` 硬撑）—— UI 仍能重绘/响应定时器，只是本函数要到整个导入流程结束才返回，
调用方语义与改动前一字不差。

## 函数

### `item_display_name`

```python
def item_display_name(item: dict) -> str
```

统一显示名：display_name（terminology 覆盖优先）→ zh → en → str(type_id)。

定义行：`37`

### `snapshot_hangar`

```python
def snapshot_hangar(hangar_id: int) -> tuple[dict[int, tuple[int, float]], dict[int, str]]
```

机库快照：``(&#123;type_id: (数量, 成本价)&#125;, &#123;type_id: 显示名&#125;)``。

定义行：`46`

### `build_import_preview`

```python
def build_import_preview(raw: str, target_hangar_id: int) -> dict
```

解析剪贴板 + 取预览所需的全部数据（**阻塞活，只许在 worker 线程里调**）。

定义行：`57`

### `apply_import_and_diff`

```python
def apply_import_and_diff(hangar_id: int, data: list[tuple[int, int, float, int | None]], mode: str, targets: dict[int, int] | None, clear_missing: dict[int, int] | None, before: dict[int, tuple[int, float]], names_before: dict[int, str]) -> dict
```

落库 + 导入后快照 + 变动对比（**阻塞活，只许在 worker 线程里调**）。

定义行：`84`

## 类

### `class InventoryImportFetchWorker`（继承 `QThread`）

后台线程：解析剪贴板 + 取预览所需数据（见 ``build_import_preview``）。

定义行：`105`

#### 方法

##### `__init__`

```python
def __init__(self, raw: str, target_hangar_id: int, parent: Any=None) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`111`
##### `run`

```python
def run(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`116`

### `class InventoryImportApplyWorker`（继承 `QThread`）

后台线程：落库 + 导入后快照 + 变动对比（见 ``apply_import_and_diff``）。

定义行：`126`

#### 方法

##### `__init__`

```python
def __init__(self, hangar_id: int, data: list[tuple[int, int, float, int | None]], mode: str, targets: dict[int, int] | None, clear_missing: dict[int, int] | None, before: dict[int, tuple[int, float]], names_before: dict[int, str], parent: Any=None) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`132`
##### `run`

```python
def run(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`146`
