# services.importers.getrigdata

> 源文件 `services/importers/getrigdata.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

拉取结构改装件（Standup Engineering Rigs）的制造加成（从 ESI /universe/types/ 并发拉取）

## 函数

### `init_db`

```python
def init_db(db_path: str)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`86`

### `get_rig_type_ids`

```python
def get_rig_type_ids(db_path: str) -> list[int]
```

从 item 表按改装件组查询 type_id 列表

定义行：`102`

### `fetch_rig_bonuses`

```python
async def fetch_rig_bonuses(client, type_id: int) -> dict | None
```

从 ESI 获取 type 的材料/时间加成

定义行：`116`

### `main`

```python
async def main(progress_cb=None)
```

初始化表 → 查已缓存 → 增量并发拉取缺失 → 写入 structure_rigs

定义行：`134`
