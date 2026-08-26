# services.bom_expander

> 源文件 `services/bom_expander.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

BOM 递归展开 — 支持 T2/T3 产业链的完整材料树

从目标成品 type_id 开始，递归查找蓝图 → 材料 → 子蓝图 → 子材料，
构建完整的制造材料树。叶子节点为可直接购买的原材料。

用法:
    from services.bom_expander import expand_bom

    result = expand_bom(type_id=30013, quantity=10, bp_me=10)
    print(result["full_cost"])          # 总材料成本
    print(result["raw_materials"])      # 叶子节点列表

## 函数

### `_default_db`

```python
def _default_db()
```

惰性获取 DatabaseManager（经容器）。

定义行：`25`

### `_default_pricing`

```python
def _default_pricing()
```

惰性获取 PricingService（经容器）。

定义行：`30`

### `_resolve_name`

```python
def _resolve_name(c, type_id: int) -> str
```

解析物品名称 — 委托给 name_resolver

定义行：`61`

### `_find_blueprint_for_product`

```python
def _find_blueprint_for_product(conn, product_type_id: int, activity: str='manufacturing')
```

查找产出指定物品的蓝图 → (bp_id, output_qty, base_time)

定义行：`68`

### `_get_materials`

```python
def _get_materials(conn, bp_id: int, activity: str='manufacturing')
```

获取蓝图材料列表 → [(material_type_id, quantity), ...]

定义行：`85`

### `_expand`

```python
def _expand(conn, type_id: int, needed_qty: float, bp_me: int, price_hub: str, price_type: str, depth: int, max_depth: int, seen: set[int], cache: dict[int, BomNode]) -> BomNode
```

内部递归展开。

定义行：`103`

### `expand_bom`

```python
def expand_bom(type_id: int, quantity: int=1, bp_me: int=0, price_hub: str='Jita', price_type: str='sell', max_depth: int=5, char_config: dict | None=None) -> dict
```

递归展开 BOM 树，返回完整的材料层级结构。

定义行：`260`

### `get_material_tree`

```python
def get_material_tree(type_id: int, quantity: int=1, bp_me: int=0, price_hub: str='Jita', price_type: str='sell') -> BomNode
```

返回 BOM 树根节点（简洁接口）

定义行：`381`

### `get_flat_materials`

```python
def get_flat_materials(type_id: int, quantity: int=1, bp_me: int=0, price_hub: str='Jita', price_type: str='sell') -> list[dict]
```

返回扁平化的所有叶子材料列表（购物清单）

定义行：`399`

### `print_tree`

```python
def print_tree(node: BomNode, indent: int=0) -> str
```

调试用：打印 BOM 树结构

定义行：`417`

## 类

### `class BomNode`

BOM 树节点 — 描述一个材料/中间产品的层级信息

定义行：`41`
