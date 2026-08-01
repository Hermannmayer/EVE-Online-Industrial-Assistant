# services.init_check

> 源文件 `services/init_check.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

数据初始化检测 — 检查各组件是否已就绪

## 函数

### `check_items`

```python
def check_items() -> int
```

返回 item 表中 **已填写名称** 的行数，<10000 视为未初始化

定义行：`11`

### `check_item_names_ratio`

```python
def check_item_names_ratio() -> float
```

返回 item 表中缺名的比例（0~1），< 5% 视为可接受

定义行：`22`

### `check_prices`

```python
def check_prices() -> int
```

返回 market_prices 行数

定义行：`38`

### `check_blueprints`

```python
def check_blueprints() -> int
```

返回 blueprint_activities 行数，>1000 视为已初始化

定义行：`49`

### `check_blueprint_names`

```python
def check_blueprint_names() -> int
```

返回蓝图 type_id 在 item 表中缺名的数量

定义行：`63`

### `check_implants`

```python
def check_implants() -> int
```

返回 item_dogma 行数，>20 视为已初始化（约 32 个工业/发明植入体有 dogma）

定义行：`84`

### `check_market_tree`

```python
def check_market_tree() -> int
```

返回 market_tree 行数，>500 视为已初始化

定义行：`98`

### `check_industry`

```python
def check_industry() -> int
```

返回 industry_system_costs 行数，>100 视为已初始化

定义行：`112`

### `check_icons`

```python
def check_icons() -> tuple[int, int]
```

返回 (已缓存/免下载数, 总数)，缓存达到 80% 视为已初始化

定义行：`126`

### `check_meta_groups`

```python
def check_meta_groups() -> int
```

返回 meta_group 表行数

定义行：`145`

### `check_type_materials`

```python
def check_type_materials() -> int
```

返回 reprocessing_materials 表行数

定义行：`156`

### `check_dogma_attrs`

```python
def check_dogma_attrs() -> int
```

返回 dogma_attribute 表行数

定义行：`167`

### `check_stations`

```python
def check_stations() -> int
```

返回 station 表行数

定义行：`178`

### `check_universe`

```python
def check_universe() -> int
```

返回 solar_system 表行数，>0 视为 universe 星系数据已加载。

定义行：`189`

### `check_structure_rigs`

```python
def check_structure_rigs() -> int
```

返回 structure_rigs 行数，>80 视为改件加成已初始化

定义行：`208`

### `check_schema`

```python
def check_schema() -> bool
```

检查已存在的库的 schema 版本是否匹配预期

定义行：`222`

### `check_all`

```python
def check_all() -> dict
```

返回各组件状态 &#123; "items": bool, "prices": bool, "blueprints": bool, ... &#125;

定义行：`240`

### `missing_count`

```python
def missing_count() -> int
```

返回未就绪的组件数量

定义行：`262`
