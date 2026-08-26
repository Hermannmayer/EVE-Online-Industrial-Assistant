# services.importers.geticon

> 源文件 `services/importers/geticon.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

geticon.py — 从 EVE Image Server 批量拉取物品图标

用共享的 SDE 缓存（typeIDs.yaml）预筛出有图标的物品，跳过无图标条目。
按 iconID 去重，相同图标只下载一次后复制到其余 type_id。

图标缓存位置：data/caches/icons/&#123;type_id&#125;.png

## 函数

### `_load_type_ids_with_icons`

```python
def _load_type_ids_with_icons() -> set[int]
```

从 SDE 缓存（typeIDs.yaml）读取有 iconID 的 type_id，避免无效请求

定义行：`29`

### `_get_type_ids_from_db`

```python
def _get_type_ids_from_db() -> list[int]
```

从数据库获取所有可交易物品（兜底方案）

定义行：`52`

### `_load_type_icon_map`

```python
def _load_type_icon_map() -> dict[int, int]
```

从 typeIDs.yaml 构建 &#123;type_id: iconID&#125; 映射，用于 iconID 去重

定义行：`69`

### `_build_icon_groups`

```python
def _build_icon_groups(type_ids: list[int], type_icon_map: dict[int, int]) -> dict[int, list[int]]
```

按 iconID 对 type_id 分组，相同 iconID 的 type 共享同一个图标文件

定义行：`92`

### `download_icon`

```python
async def download_icon(session: aiohttp.ClientSession, type_id: int, semaphore: asyncio.Semaphore, progress: list) -> bool
```

为单个 type_id 下载图标（向后兼容包装，委托给 download_icon_for_group）

定义行：`101`

### `download_icon_for_group`

```python
async def download_icon_for_group(session: aiohttp.ClientSession, icon_id: int, type_ids: list[int], semaphore: asyncio.Semaphore, progress: list) -> bool
```

为同一 iconID 的一组 type_id 下载/复制图标（组内只下载一次）。

定义行：`111`

### `download_all`

```python
async def download_all(session: aiohttp.ClientSession, type_ids: list, progress_cb=None)
```

批量下载所有图标（按 iconID 去重，相同图标只下载一次）

定义行：`188`

### `main`

```python
async def main(progress_cb=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`222`
