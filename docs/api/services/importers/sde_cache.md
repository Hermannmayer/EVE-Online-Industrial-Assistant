# services.importers.sde_cache

> 源文件 `services/importers/sde_cache.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

SDE zip 缓存共享工具 — 下载/缓存/加载 SDE 的 YAML 数据文件

被 getitems.py、geticon.py、getimplantdata.py、sde_loader.py 等模块共用。

## 函数

### `sde_source`

```python
def sde_source() -> str
```

当前 SDE 发布源（`EVE_SDE_SOURCE`，非法值回退 legacy 并告警）。

定义行：`123`

### `yaml_files_for`

```python
def yaml_files_for(source: str | None=None) -> set[str]
```

某发布源需要提取到 `data/` 的缓存文件集合（新源少了 agents/researchAgents）。

定义行：`134`

### `_zip_member_name`

```python
def _zip_member_name(zf: zipfile.ZipFile, cache_name: str, source: str) -> str | None
```

缓存文件名 → zip 内成员名（兼容新旧两种布局；找不到 → None）。

定义行：`142`

### `_zip_layout_source`

```python
def _zip_layout_source(zf: zipfile.ZipFile) -> str
```

从 zip 中央目录判断布局来源：根目录有 types.yaml/_sde.yaml → 新扁平包。

定义行：`157`

### `_resolve_sde_zip_url_sync`

```python
def _resolve_sde_zip_url_sync() -> tuple[str, int | None]
```

同步解析当前源应下载的 zip URL（+ 新源的 build 号）。

定义行：`165`

### `cache_path`

```python
def cache_path(name: str) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`221`

### `_all_cached`

```python
def _all_cached() -> bool
```

YAML 缓存是否完整：完成标记存在 + 标记内文件集合与当前 YAML_FILES 一致 + 每个文件非空。

定义行：`225`

### `_write_yaml_atomic`

```python
def _write_yaml_atomic(fname: str, raw: str) -> None
```

写 <目标>.part 后原子替换 —— 中断只留 .part，目标文件不会是半写状态。

定义行：`250`

### `_read_manifest`

```python
def _read_manifest() -> dict
```

读完成标记；缺失/损坏/版本不符 → 空 dict。

定义行：`268`

### `cached_sde_build`

```python
def cached_sde_build() -> int | None
```

本地缓存对应的 SDE build 号；旧 manifest 没记过 → None（= 未知，视同过期）。

定义行：`278`

### `is_sde_stale`

```python
def is_sde_stale(remote_build: int | None, local_build: int | None) -> bool
```

官方 build 比本地新（或本地未知）⇒ 过期。官方拿不到时不判过期（离线可用）。

定义行：`287`

### `_zip_build_number`

```python
def _zip_build_number(zf: zipfile.ZipFile) -> int | None
```

从 zip 的 `_sde.yaml`（新发布源的 build 元数据）读 build 号；旧包没有 → None。

定义行：`294`

### `_write_manifest`

```python
def _write_manifest(build: int | None=None, source: str | None=None) -> None
```

原子写完成标记（临时文件名唯一，多进程互踩不影响正确性）。

定义行：`305`

### `_backfill_manifest_from_zip`

```python
def _backfill_manifest_from_zip() -> bool
```

升级兼容：老缓存没有标记 → 用 zip 中央目录里的成员大小逐个比对，全对才补写标记。

定义行：`328`

### `_universe_cache_has_names`

```python
def _universe_cache_has_names(systems: list) -> bool
```

universe JSON 缓存有效性：至少一个星系带非空名。

定义行：`363`

### `_validate_and_finalize`

```python
def _validate_and_finalize() -> None
```

校验 zip 完整性并原子 rename；损坏则删 .part 抛错（下次从头下载）。

定义行：`374`

### `_retry_after_seconds`

```python
def _retry_after_seconds(resp: aiohttp.ClientResponse) -> float
```

429/503 的等待时长：优先服务端 Retry-After（秒），缺失/非法则用默认退避。

定义行：`386`

### `_download_zip`

```python
async def _download_zip(progress_cb: Callable[[int, str], None] | None=None, url: str | None=None) -> str
```

下载 SDE zip 到 .part（断点续传 + 流式写盘）。由 _zip_dl_lock 保证串行。

定义行：`394`

### `_cached_zip_matches_source`

```python
def _cached_zip_matches_source() -> bool
```

本地 sde.zip 的**布局**是否与当前源一致（换源后必须重下，不能拿旧包当新源）。

定义行：`462`

### `_drop_stale_zip`

```python
def _drop_stale_zip() -> None
```

换源时删掉与当前源布局不符的旧 zip/.part（可重下；不删已提取的 YAML）。

定义行：`473`

### `_sync_ensure_zip`

```python
def _sync_ensure_zip(progress_cb: Callable[[int, str], None] | None=None) -> str
```

线程安全的 zip 下载（threading.Lock 串行，跨线程/事件循环安全）。

定义行：`483`

### `ensure_sde_zip`

```python
async def ensure_sde_zip(progress_cb: Callable[[int, str], None] | None=None) -> str
```

确保 data/sde.zip 完整存在（断点续传 + 流式写盘 + 跨线程串行单飞）。

定义行：`497`

### `_sync_ensure_sde_cache`

```python
def _sync_ensure_sde_cache(progress_cb: Callable[[int, str], None] | None=None) -> None
```

线程安全的下载+提取（threading.Lock 串行）。

定义行：`511`

### `_zip_is_usable`

```python
def _zip_is_usable() -> bool
```

本地 sde.zip 能否直接复用：存在且成员校验通过。

定义行：`522`

### `_download_and_extract`

```python
async def _download_and_extract(progress_cb: Callable[[int, str], None] | None=None) -> None
```

下载 SDE zip + 提取所需 YAML（由 _zip_dl_lock 保证串行）。

定义行：`544`

### `_zip_layout_source_quiet`

```python
def _zip_layout_source_quiet() -> str
```

日志用：本地 zip 布局（读不到 → unknown）。

定义行：`602`

### `ensure_sde_cache`

```python
async def ensure_sde_cache(progress_cb: Callable[[int, str], None] | None=None)
```

确保 SDE zip 中所需的 YAML 文件已缓存到本地

定义行：`611`

### `fetch_latest_sde_build`

```python
async def fetch_latest_sde_build(timeout: int=10) -> int | None
```

官方 `latest.jsonl` 的当前 build 号（1 次小请求）。失败/离线 → None。

定义行：`633`

### `warn_if_sde_stale`

```python
async def warn_if_sde_stale() -> dict
```

02-03 A 段：检测本地 SDE build 是否落后官方并告警（不触发重下/重导）。

定义行：`659`

### `get_sde_freshness`

```python
def get_sde_freshness() -> dict
```

最近一次 SDE 新鲜度检查结果（未检查过 → 空 dict）。

定义行：`684`

### `_localized_name`

```python
def _localized_name(data: Mapping) -> str
```

取本地化名称里的 `en`（再退 `zh`/纯字符串）；没有 → 空串。

定义行：`694`

### `_flat_zip_systems`

```python
def _flat_zip_systems(zf: zipfile.ZipFile) -> list[dict]
```

新源（扁平布局）`mapSolarSystems.yaml` → 与旧 universe 解析同形的 systems 列表。

定义行：`707`

### `_flat_name_map`

```python
def _flat_name_map(zf: zipfile.ZipFile) -> dict[int, str]
```

新源：从 mapRegions/mapConstellations/mapSolarSystems 的名称内联字段建 `&#123;id: en名&#125;`。

定义行：`750`

### `_build_name_map`

```python
def _build_name_map(zip_path: str) -> dict[int, str]
```

从 bsd/invNames.yaml 构建 &#123;itemID: itemName&#125; 映射（名称按 itemID 索引）。

定义行：`772`

### `_normalize_system_dir`

```python
def _normalize_system_dir(name: str) -> str
```

星系目录名 ↔ 库内星系名的宽松匹配键（去空格/大小写/标点）。

定义行：`854`

### `_universe_geo_maps`

```python
def _universe_geo_maps(zf: zipfile.ZipFile) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str, str], int]]
```

只读 region.yaml + constellation.yaml，返回「路径目录 → ID」两张映射。

定义行：`863`

### `load_universe_geo_maps`

```python
def load_universe_geo_maps(zip_path: str) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str, str], int]]
```

`_universe_geo_maps` 的路径版（供 `asyncio.to_thread` 在后台线程调用）。

定义行：`888`

### `_universe_path_geo`

```python
def _universe_path_geo(path: str, geo_maps: tuple[dict[tuple[str, str], int], dict[tuple[str, str, str], int]] | None) -> tuple[int | None, int | None]
```

一条 universe 路径 → `(region_id, constellation_id)`（推不出 → None）。

定义行：`894`

### `load_universe_geo`

```python
def load_universe_geo(zip_path: str, name_to_id: Mapping[str, int] | None=None) -> dict[int, tuple[int | None, int | None]]
```

从 SDE zip 的 universe 路径层级解析 `&#123;solar_system_id: (region_id, constellation_id)&#125;`。

定义行：`908`

### `_attach_universe_geo`

```python
def _attach_universe_geo(systems: list[dict], geo: Mapping[int, tuple[int | None, int | None]]) -> int
```

给 systems 附上 `region_id`/`constellation_id`（只填 None，不覆盖已有值）。

定义行：`965`

### `_parse_universe_chunk`

```python
def _parse_universe_chunk(paths: list[str], zip_path: str, name_map: dict[int, str] | None=None, geo_maps: tuple[dict[tuple[str, str], int], dict[tuple[str, str, str], int]] | None=None) -> tuple[list, list, list, list]
```

在线程池/进程池 worker 中解析一批 universe YAML 文件（CSafeLoader）

定义行：`989`

### `_parse_universe_chunk_with_names`

```python
def _parse_universe_chunk_with_names(paths: list[str], zip_path: str, geo_maps: tuple[dict[tuple[str, str], int], dict[tuple[str, str, str], int]] | None=None) -> tuple[list, list, list, list]
```

进程池 worker：先加载名称映射（pkl 缓存秒级），再解析一批星系 YAML。

定义行：`1107`

### `ensure_universe_cache`

```python
async def ensure_universe_cache(progress_cb: Callable[[int, str], None] | None=None)
```

确保 SDE zip 已缓存，解析 universe/ 下全部星系并返回星系数据

定义行：`1121`

### `load_yaml`

```python
def load_yaml(name: str) -> dict
```

从本地缓存加载 SDE YAML 文件（CSafeLoader 加速；≥1MB 走磁盘 pickle 缓存；进程内二次缓存）

定义行：`1268`

### `_pickle_cache_path`

```python
def _pickle_cache_path(name: str) -> str
```

YAML 解析结果的磁盘缓存路径（name.yaml → name.pkl）

定义行：`1290`

### `_load_yaml_from_disk`

```python
def _load_yaml_from_disk(name: str, path: str) -> dict
```

解析 YAML，优先命中磁盘 pickle 缓存（缓存不可用/损坏时静默回退正常解析）

定义行：`1295`

### `load_yaml_async`

```python
async def load_yaml_async(name: str) -> dict
```

异步加载 SDE YAML：首次大文件（typeIDs.yaml 148MB 约 29s）在
to_thread 中解析，不阻塞事件循环；二次命中进程内缓存（瞬时）。

定义行：`1336`

### `clear_yaml_cache`

```python
def clear_yaml_cache() -> None
```

释放 YAML 解析缓存（初始化完成后调用，释放 typeIDs.yaml 等大文件内存）

定义行：`1353`

### `reset_async_locks`

```python
def reset_async_locks() -> None
```

重置模块级 asyncio.Lock（_load_lock）。

定义行：`1359`
