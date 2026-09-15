# ui_qml.workers.blueprint_import_worker

> 源文件 `ui_qml/workers/blueprint_import_worker.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

仓库页面 — 蓝图导入后台线程

## 函数

### `parse_blueprint_clipboard`

```python
def parse_blueprint_clipboard(raw: str, conn) -> tuple[list[dict], int, int]
```

解析 EVE 蓝图剪贴板 → (蓝图行, 被过滤材料行数, 未识别蓝图行数)

定义行：`11`

### `build_blueprint_changes`

```python
def build_blueprint_changes(before: dict[tuple, tuple[int, tuple[int, ...]]], after: dict[tuple, tuple[int, tuple[int, ...]]], names: dict[int, str]) -> list[dict]
```

对比导入前后蓝图库，返回变化行列表（对齐材料 compute_import_diff）。

定义行：`23`

### `snapshot_blueprints`

```python
def snapshot_blueprints(hangar_id: int) -> dict[tuple, tuple[int, tuple[int, ...]]]
```

机库蓝图快照：组键 → (张数合计, 各张流程数排序元组)。

定义行：`62`

### `apply_blueprint_diff`

```python
def apply_blueprint_diff(diff_rows: list[dict], hangar_id: int, mode: str='full') -> tuple[int, int, int]
```

按勾选组应用增删，返回 (added, removed, blocked)。

定义行：`146`

## 类

### `class _BlueprintImportWorker`（继承 `QThread`）

后台线程：解析剪贴板 → 比对库 → 产出 diff（增/删/更新）供预览确认

定义行：`79`

#### 方法

##### `__init__`

```python
def __init__(self, raw: str, hangar_id: int, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`87`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`94`
