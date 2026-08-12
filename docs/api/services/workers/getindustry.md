# services.workers.getindustry

> 源文件 `services/workers/getindustry.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

从 ESI 拉取工业系统成本指数和设施数据写入 reference.db 和 user.db
用法: python -m services.workers.getindustry

## 函数

### `_ref_db`

```python
async def _ref_db()
```

reference.db 写库上下文：per-DB 写锁 + 连接。

定义行：`23`

### `create_tables`

```python
async def create_tables()
```

创建 reference.db 和 user.db 中的表

定义行：`50`

### `run_industry_update`

```python
async def run_industry_update(progress_cb=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`94`

### `industry_data_is_fresh`

```python
def industry_data_is_fresh(db_path: str, max_age_days: int=1) -> bool
```

判断工业数据（成本指数/设施）是否就绪且新鲜。

定义行：`162`
