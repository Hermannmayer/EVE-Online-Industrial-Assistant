# services.importers.getitems

> 源文件 `services/importers/getitems.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

物品数据拉取 — 从 SDE zip 本地解析 typeIDs.yaml / groupIDs.yaml / marketGroups.yaml

流程：
  1. 检查本地缓存 data/typeIDs.yaml 等是否存在
  2. 若不存在 → 下载 SDE zip(~112MB)，提取所需的 YAML 文件并缓存
  3. 解析 YAML → 批量写入 reference.db 的 item 表 + market_tree 表

首次拉取需要下载一次 SDE zip，后续跳过。

## 函数

### `_ref_db`

```python
async def _ref_db()
```

reference.db 写库上下文：per-DB 写锁 + 连接。

定义行：`31`

### `initialize_database`

```python
async def initialize_database()
```

初始化数据库结构

定义行：`46`

### `_build_group_lookup`

```python
def _build_group_lookup(data: dict) -> dict[int, tuple[str, str]]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`73`

### `write_items`

```python
async def write_items(progress_cb: Callable[[int, str], None] | None=None)
```

从缓存的 typeIDs.yaml + groupIDs.yaml + marketGroups.yaml 批量写入 item 表

定义行：`84`

### `write_market_tree`

```python
async def write_market_tree()
```

从 marketGroups.yaml 写入 market_tree 表

定义行：`173`

### `main`

```python
async def main(progress_cb: Callable[[int, str], None] | None=None)
```

主流程：检查数据状态 → 如需更新则下载 SDE zip → 解析 YAML → 批量写入

定义行：`206`

### `fill_missing_blueprint_names`

```python
async def fill_missing_blueprint_names()
```

补充 item 表中缺失的蓝图名称

定义行：`262`

### `fill_missing_item_names_from_esi`

```python
async def fill_missing_item_names_from_esi(progress_cb: Callable[[int, str], None] | None=None)
```

从 ESI 补拉 item 表中缺失名称的物品（并发 + 全局限流）。

定义行：`347`
