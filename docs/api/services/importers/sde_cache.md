# services.importers.sde_cache

> 源文件 `services/importers/sde_cache.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

SDE zip 缓存共享工具 — 下载/缓存/加载 SDE 的 YAML 数据文件

被 getitems.py、geticon.py、getimplantdata.py、sde_loader.py 等模块共用。

## 函数

### `cache_path`

```python
def cache_path(name: str) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`80`

### `_all_cached`

```python
def _all_cached() -> bool
```

YAML 缓存是否完整：完成标记存在 + 标记内文件集合与当前 YAML_FILES 一致 + 每个文件非空。

定义行：`84`

### `_write_yaml_atomic`

```python
def _write_yaml_atomic(fname: str, raw: str) -> None
```

写 <目标>.part 后原子替换 —— 中断只留 .part，目标文件不会是半写状态。

定义行：`105`

### `_write_manifest`

```python
def _write_manifest() -> None
```

原子写完成标记（临时文件名唯一，多进程互踩不影响正确性）

定义行：`123`

### `_backfill_manifest_from_zip`

```python
def _backfill_manifest_from_zip() -> bool
```

升级兼容：老缓存没有标记 → 用 zip 中央目录里的成员大小逐个比对，全对才补写标记。

定义行：`138`

### `_universe_cache_has_names`

```python
def _universe_cache_has_names(systems: list) -> bool
```

universe JSON 缓存有效性：至少一个星系带非空名。

定义行：`164`

### `_validate_and_finalize`

```python
def _validate_and_finalize() -> None
```

校验 zip 完整性并原子 rename；损坏则删 .part 抛错（下次从头下载）。

定义行：`175`

### `_retry_after_seconds`

```python
def _retry_after_seconds(resp: aiohttp.ClientResponse) -> float
```

429/503 的等待时长：优先服务端 Retry-After（秒），缺失/非法则用默认退避。

定义行：`187`

### `_download_zip`

```python
async def _download_zip(progress_cb: Callable[[int, str], None] | None=None) -> str
```

下载 SDE zip 到 .part（断点续传 + 流式写盘）。由 _zip_dl_lock 保证串行。

定义行：`195`

### `_sync_ensure_zip`

```python
def _sync_ensure_zip(progress_cb: Callable[[int, str], None] | None=None) -> str
```

线程安全的 zip 下载（threading.Lock 串行，跨线程/事件循环安全）。

定义行：`261`

### `ensure_sde_zip`

```python
async def ensure_sde_zip(progress_cb: Callable[[int, str], None] | None=None) -> str
```

确保 data/sde.zip 完整存在（断点续传 + 流式写盘 + 跨线程串行单飞）。

定义行：`270`

### `_sync_ensure_sde_cache`

```python
def _sync_ensure_sde_cache(progress_cb: Callable[[int, str], None] | None=None) -> None
```

线程安全的下载+提取（threading.Lock 串行）。

定义行：`284`

### `_zip_is_usable`

```python
def _zip_is_usable() -> bool
```

本地 sde.zip 能否直接复用：存在且成员校验通过。

定义行：`295`

### `_download_and_extract`

```python
async def _download_and_extract(progress_cb: Callable[[int, str], None] | None=None) -> None
```

下载 SDE zip + 提取所需 YAML（由 _zip_dl_lock 保证串行）。

定义行：`317`

### `ensure_sde_cache`

```python
async def ensure_sde_cache(progress_cb: Callable[[int, str], None] | None=None)
```

确保 SDE zip 中所需的 YAML 文件已缓存到本地

定义行：`360`

### `_build_name_map`

```python
def _build_name_map(zip_path: str) -> dict[int, str]
```

从 bsd/invNames.yaml 构建 &#123;itemID: itemName&#125; 映射（名称按 itemID 索引）。

定义行：`382`

### `_parse_universe_chunk`

```python
def _parse_universe_chunk(paths: list[str], zip_path: str, name_map: dict[int, str] | None=None) -> tuple[list, list, list, list]
```

在线程池/进程池 worker 中解析一批 universe YAML 文件（CSafeLoader）

定义行：`438`

### `_parse_universe_chunk_with_names`

```python
def _parse_universe_chunk_with_names(paths: list[str], zip_path: str) -> tuple[list, list, list, list]
```

进程池 worker：先加载名称映射（pkl 缓存秒级），再解析一批星系 YAML。

定义行：`545`

### `ensure_universe_cache`

```python
async def ensure_universe_cache(progress_cb: Callable[[int, str], None] | None=None)
```

确保 SDE zip 已缓存，解析 universe/ 下全部星系并返回星系数据

定义行：`555`

### `load_yaml`

```python
def load_yaml(name: str) -> dict
```

从本地缓存加载 SDE YAML 文件（CSafeLoader 加速；≥1MB 走磁盘 pickle 缓存；进程内二次缓存）

定义行：`656`

### `_pickle_cache_path`

```python
def _pickle_cache_path(name: str) -> str
```

YAML 解析结果的磁盘缓存路径（name.yaml → name.pkl）

定义行：`678`

### `_load_yaml_from_disk`

```python
def _load_yaml_from_disk(name: str, path: str) -> dict
```

解析 YAML，优先命中磁盘 pickle 缓存（缓存不可用/损坏时静默回退正常解析）

定义行：`683`

### `load_yaml_async`

```python
async def load_yaml_async(name: str) -> dict
```

异步加载 SDE YAML：首次大文件（typeIDs.yaml 148MB 约 29s）在
to_thread 中解析，不阻塞事件循环；二次命中进程内缓存（瞬时）。

定义行：`720`

### `clear_yaml_cache`

```python
def clear_yaml_cache() -> None
```

释放 YAML 解析缓存（初始化完成后调用，释放 typeIDs.yaml 等大文件内存）

定义行：`737`

### `reset_async_locks`

```python
def reset_async_locks() -> None
```

重置模块级 asyncio.Lock（_load_lock）。

定义行：`743`
