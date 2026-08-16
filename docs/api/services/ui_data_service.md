# services.ui_data_service

> 源文件 `services/ui_data_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

UI 层常用数据库查询/写入的小型服务函数。

## 函数

### `_resolve_db`

```python
def _resolve_db(db)
```

返回调用方传入的 DatabaseManager；未传时使用容器中的全局实例。

定义行：`21`

### `search_item_by_name`

```python
def search_item_by_name(name: str, db=None) -> dict | None
```

按中文/英文名搜索物品，返回 &#123;type_id, zh_name, en_name, iconID, volume&#125; 或 None。

定义行：`29`

### `query_search_items`

```python
def query_search_items(query: str, all_groups: list, region_id: int=10000002, db=None) -> list[Any]
```

查询页完整搜索：item + market_prices，返回原始行。

定义行：`72`

### `query_search_items_basic`

```python
def query_search_items_basic(query: str, db=None) -> list[Any]
```

查询页降级搜索：只查 reference.item，返回原始行。

定义行：`130`

### `query_suggest_items`

```python
def query_suggest_items(query: str, db=None) -> list[Any]
```

候选搜索：返回 item 表原始行 (type_id, en_name, zh_name)。

定义行：`148`

### `load_item_groups`

```python
def load_item_groups(db=None) -> list[Any]
```

加载查询页类别列表。

定义行：`172`

### `has_solar_system_data`

```python
def has_solar_system_data(db=None) -> bool
```

reference.solar_system 表是否已有数据。

定义行：`187`

### `search_solar_systems`

```python
def search_solar_systems(query: str, db=None) -> list[tuple[int, str, float]]
```

按名称搜索星系，返回 [(solar_system_id, display_name, security), ...]。

定义行：`197`

### `get_item_names_batch`

```python
def get_item_names_batch(type_ids: list[int], db=None) -> dict[int, str]
```

批量查询 item 名称，返回 &#123;type_id: zh_name or en_name or str(type_id)&#125;。

定义行：`229`

### `parse_blueprint_clipboard`

```python
def parse_blueprint_clipboard(raw: str, conn) -> list[dict]
```

解析 EVE 蓝图剪贴板 → [&#123;blueprint_type_id, name, is_bpo, me, te, runs&#125;]。

定义行：`246`

### `parse_blueprint_clipboard_text`

```python
def parse_blueprint_clipboard_text(raw: str, db=None) -> list[dict]
```

打开 ref/bp 连接并解析剪贴板蓝图。

定义行：`291`

### `_lookup_bpid`

```python
def _lookup_bpid(c, name_part)
```

蓝图名/产物名 → blueprint_type_id（先精确匹配蓝图，再产物反查）

定义行：`297`

### `_lookup_name`

```python
def _lookup_name(c, bpid: int, fallback: str) -> str
```

蓝图类型 ID → 显示名（找不到用剪贴板名兜底）

定义行：`339`

### `apply_blueprint_diff`

```python
def apply_blueprint_diff(diff_rows: list[dict], hangar_id: int, mode: str='full', *, db=None) -> tuple[int, int]
```

按勾选行应用增删，返回 (added, removed)。

定义行：`346`

### `search_manufacturable_items`

```python
def search_manufacturable_items(query: str, db=None) -> list[dict]
```

搜索可制造物品（item 表），返回 [&#123;type_id, zh_name, en_name&#125;, ...]。

定义行：`396`

### `get_all_manufacturable_product_ids`

```python
def get_all_manufacturable_product_ids(db=None) -> list[int]
```

获取所有制造活动蓝图的产品 type_id。

定义行：`414`

### `aggregate_procurement_summary`

```python
def aggregate_procurement_summary(plans: list[dict], *, default_mat_hangar_id: int | None=None, region_id: int=10000002, price_type: str='sell', db=None) -> tuple[float, float]
```

按统计条模式聚合备料中计划的采购金额/体积。

定义行：`426`
