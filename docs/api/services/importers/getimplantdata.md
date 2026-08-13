# services.importers.getimplantdata

> 源文件 `services/importers/getimplantdata.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

拉取工业/发明相关植入体的 dogma 属性（从 ESI /universe/types/ 并发拉取）

## 函数

### `init_db`

```python
def init_db(db_path)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`35`

### `get_industry_type_ids`

```python
def get_industry_type_ids(db_path)
```

从数据库获取工业相关 type_id 列表

定义行：`50`

### `fetch_type_dogma`

```python
async def fetch_type_dogma(client, type_id: int) -> dict | None
```

从 ESI 获取 type 的 dogma 属性

定义行：`67`

### `fetch_attribute_name`

```python
async def fetch_attribute_name(client, attribute_id: int) -> tuple[int, str]
```

从 ESI 获取 dogma attribute 的名称

定义行：`88`

### `main`

```python
async def main(progress_cb=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`105`
