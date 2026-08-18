# services.importers.sde_cache

> 源文件 `services/importers/sde_cache.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

SDE zip 缓存共享工具 — 下载/缓存/加载 SDE 的 YAML 数据文件

## 函数

### `cache_path`

```python
def cache_path(name: str) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`70`

### `_all_cached`

```python
def _all_cached() -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`74`

### `_universe_cache_has_names`

```python
def _universe_cache_has_names(systems: list) -> bool
```

universe JSON 缓存有效性：至少一个星系带非空名。

定义行：`78`

### `_validate_and_finalize`

```python
def _validate_and_finalize() -> None
```

校验 zip 完整性并原子 rename；损坏则删 .part 抛错（下次从头下载）。

定义行：`89`

### `_download_zip`

```python
async def _download_zip(progress_cb: Callable[[int, str], None] | None=None) -> str
```

下载 SDE zip 到 .part（断点续传 + 流式写盘）。由 _zip_dl_lock 保证串行。

定义行：`101`

### `_sync_ensure_zip`

```python
def _sync_ensure_zip(progress_cb: Callable[[int, str], None] | None=None) -> str
```

线程安全的 zip 下载（threading.Lock 串行，跨线程/事件循环安全）。

定义行：`145`

### `ensure_sde_zip`

```python
async def ensure_sde_zip(progress_cb: Callable[[int, str], None] | None=None) -> str
```

确保 data/sde.zip 完整存在（断点续传 + 流式写盘 + 跨线程串行单飞）。

定义行：`154`

### `_sync_ensure_sde_cache`

```python
def _sync_ensure_sde_cache(progress_cb: Callable[[int, str], None] | None=None) -> None
```

线程安全的下载+提取（threading.Lock 串行）。

定义行：`168`

### `_download_and_extract`

```python
async def _download_and_extract(progress_cb: Callable[[int, str], None] | None=None) -> None
```

下载 SDE zip + 提取所需 YAML（由 _zip_dl_lock 保证串行）。

定义行：`176`

### `ensure_sde_cache`

```python
async def ensure_sde_cache(progress_cb: Callable[[int, str], None] | None=None)
```

确保 SDE zip 中所需的 YAML 文件已缓存到本地

定义行：`197`

### `_build_name_map`

```python
def _build_name_map(zip_path: str) -> dict[int, str]
```

从 bsd/invNames.yaml 构建 &#123;itemID: itemName&#125; 映射（名称按 itemID 索引）。

定义行：`219`

### `_parse_universe_chunk`

```python
def _parse_universe_chunk(paths: list[str], zip_path: str, name_map: dict[int, str] | None=None) -> tuple[list, list, list, list]
```

在线程池/进程池 worker 中解析一批 universe YAML 文件（CSafeLoader）

定义行：`275`

### `_parse_universe_chunk_with_names`

```python
def _parse_universe_chunk_with_names(paths: list[str], zip_path: str) -> tuple[list, list, list, list]
```

进程池 worker：先加载名称映射（pkl 缓存秒级），再解析一批星系 YAML。

定义行：`382`

### `ensure_universe_cache`

```python
async def ensure_universe_cache(progress_cb: Callable[[int, str], None] | None=None)
```

确保 SDE zip 已缓存，解析 universe/ 下全部星系并返回星系数据

定义行：`392`

### `load_yaml`

```python
def load_yaml(name: str) -> dict
```

从本地缓存加载 SDE YAML 文件（CSafeLoader 加速；≥1MB 走磁盘 pickle 缓存；进程内二次缓存）

定义行：`493`

### `_pickle_cache_path`

```python
def _pickle_cache_path(name: str) -> str
```

YAML 解析结果的磁盘缓存路径（name.yaml → name.pkl）

定义行：`515`

### `_load_yaml_from_disk`

```python
def _load_yaml_from_disk(name: str, path: str) -> dict
```

解析 YAML，优先命中磁盘 pickle 缓存（缓存不可用/损坏时静默回退正常解析）

定义行：`520`

### `load_yaml_async`

```python
async def load_yaml_async(name: str) -> dict
```

异步加载 SDE YAML：首次大文件（typeIDs.yaml 148MB 约 29s）在
to_thread 中解析，不阻塞事件循环；二次命中进程内缓存（瞬时）。

定义行：`557`

### `clear_yaml_cache`

```python
def clear_yaml_cache() -> None
```

释放 YAML 解析缓存（初始化完成后调用，释放 typeIDs.yaml 等大文件内存）

定义行：`574`

### `reset_async_locks`

```python
def reset_async_locks() -> None
```

重置模块级 asyncio.Lock（_load_lock）。

定义行：`580`
