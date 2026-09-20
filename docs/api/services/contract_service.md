# services.contract_service

> 源文件 `services/contract_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

合同市场数据访问 —— 供 UI Worker 调用的只读查询 + 判定。

三个子页各一个入口，内部走同一条流水线：

    1. 按星域/类型/筛选条件查 `public_contracts`（**筛选下推到 SQL**，先筛再 LIMIT；
       否则「取前 N 条再本地筛」会把真正想看的合同挡在外面）
    2. 取这些合同的物品（只取 `items_fetched_at` 非空的 —— 没拉过就是还没拉到，不是没有）
    3. 批量查市价（分块防 SQLite 变量上限；本星域缺价回落到 Jita）
    4. 起止点 → 站名/星系/安全等级
    5. 交给 `domain/contract_analysis` 算判定

判定逻辑一律不写在这里 —— 本模块只负责取数与拼装，算术全在 `domain/` 且已单测覆盖。

## 函数

### `_chunks`

```python
def _chunks(ids: list[int]) -> Iterable[list[int]]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`63`

### `_build_where`

```python
def _build_where(region_id: int, contract_type: str, filters: dict[str, Any] | None) -> tuple[str, list]
```

把筛选条件下推成 SQL —— 先筛再 LIMIT，语义才正确。

定义行：`68`

### `_contract_rows`

```python
def _contract_rows(region_id: int, contract_type: str, filters: dict[str, Any] | None, limit: int) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`102`

### `_items_by_contract`

```python
def _items_by_contract(contract_ids: Sequence[int]) -> dict[int, list[dict]]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`121`

### `price_map_for`

```python
def price_map_for(type_ids: Iterable[int], region_id: int, price_type: str='sell') -> dict[int, float]
```

`&#123;type_id: 单价&#125;` —— 本星域缺价的回落到 Jita。

定义行：`140`

### `_station_lookup`

```python
def _station_lookup(location_ids: Iterable[int]) -> dict[int, dict]
```

location_id → 站名 / 星系名 / 安全等级。

定义行：`158`

### `_blueprint_type_ids`

```python
def _blueprint_type_ids(type_ids: Iterable[int]) -> set[int]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`183`

### `_recipes_for`

```python
def _recipes_for(blueprint_ids: Iterable[int]) -> dict[int, dict]
```

`&#123;蓝图 type_id: &#123;product_type_id, output_qty, materials: [(mat_id, 基础量)]&#125;&#125;`。

定义行：`194`

### `_attach_places`

```python
def _attach_places(rows: list[dict]) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`225`

### `_attach_icons`

```python
def _attach_icons(rows: list[dict], items: dict[int, list[dict]], price_map: dict[int, float]) -> None
```

给合同行补「里面是什么」：主物品名 + 图标 + 件数。

定义行：`235`

### `_attach_issuers`

```python
def _attach_issuers(rows: list[dict]) -> None
```

给合同行补 `issuer_name`（查不到给空串）。

定义行：`254`

### `count_tab`

```python
def count_tab(region_id: int, contract_type: str, filters: dict[str, Any] | None=None) -> int
```

当前筛选下这个页签有多少条 —— 页签上的条数徽标用。

定义行：`279`

### `load_auction_contracts`

```python
def load_auction_contracts(region_id: int, price_type: str='sell', filters: dict[str, Any] | None=None, limit: int=DEFAULT_LIMIT) -> list[dict]
```

拍卖合同 —— 内容物市价 vs 一口价（无一口价则按当前出价）。

定义行：`296`

### `load_exchange_contracts`

```python
def load_exchange_contracts(region_id: int, price_type: str='sell', filters: dict[str, Any] | None=None, limit: int=DEFAULT_LIMIT) -> list[dict]
```

物品交换合同 —— 含蓝图的走「蓝图市价 + 制造利润」，其余走内容物市价。

定义行：`314`

### `load_courier_contracts`

```python
def load_courier_contracts(region_id: int, jump_mode: str='none', min_security: float | None=None, filters: dict[str, Any] | None=None, limit: int=DEFAULT_LIMIT) -> list[dict]
```

运输合同 —— 报酬摊到每跳 / 每方每跳。

定义行：`351`

### `_system_ids_for`

```python
def _system_ids_for(rows: list[dict]) -> dict[int, int]
```

location_id → 星系 id（跳数计算的起点/终点）。

定义行：`388`

### `list_regions`

```python
def list_regions(query: str='', limit: int=30) -> list[dict]
```

按名称搜星域 → `[&#123;region_id, name, en_name&#125;]`。中英文都能匹配。

定义行：`410`

### `region_name`

```python
def region_name(region_id: int) -> str
```

星域显示名（中文优先）。查不到就返回 id 本身 —— 界面上总得显示点什么。

定义行：`434`

### `load_contracts`

```python
def load_contracts(region_id: int, contract_type: str='all') -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`463`

### `load_contract_items`

```python
def load_contract_items(contract_id: int) -> list[dict]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`475`
