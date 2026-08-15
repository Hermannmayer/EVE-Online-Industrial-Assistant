# services.importers.getblueprints

> 源文件 `services/importers/getblueprints.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

蓝图数据拉取 — 从 SDE 解析 blueprints.yaml

## 函数

### `create_tables`

```python
async def create_tables(db: aiosqlite.Connection)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`65`

### `_extract_blueprints_yaml`

```python
def _extract_blueprints_yaml() -> str
```

从共享 SDE zip 提取 blueprints.yaml 写入缓存，返回缓存文件路径。

定义行：`70`

### `ensure_cache`

```python
async def ensure_cache(progress_cb=None) -> str
```

确保 blueprints.yaml 缓存文件存在。
返回缓存文件路径。

定义行：`85`

### `parse_activities`

```python
def parse_activities(bp_id: int, bp_data: dict)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`109`

### `_load_blueprints_yaml`

```python
def _load_blueprints_yaml(path: str, loader) -> dict
```

同步解析 blueprints.yaml（在 to_thread 中运行，避免阻塞事件循环）。

定义行：`139`

### `run_blueprint_update`

```python
async def run_blueprint_update(progress_cb=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`145`
