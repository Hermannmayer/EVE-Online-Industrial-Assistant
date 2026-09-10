# services.item_kind

> 源文件 `services/item_kind.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

物品种类判定 — 蓝图 / 材料（供剪贴板导入按仓库类型校验）。

蓝图判定依据 reference.db ``item`` 表的 group 名后缀（实测 database/reference.db
50219 件物品、CCP 分类 9 共 5044 件蓝图：命中 5044，0 误 0 漏）：

- ``en_group_name`` 以 Blueprint(s) / Formula(s) 结尾
- ``zh_group_name`` 以 蓝图 / 公式 / 配方 结尾

不用其它来源的原因：

- ``item.category_id``：随包 reference.db 该列全为 NULL（sde_loader 的 category
  步骤未跑），不能作为唯一依据。
- ``bp.blueprint_activities/products``：含发明源遗物（如「完整的推进器」）、漏部分
  真实蓝图；且 6 个「屹立…改装件 - 蓝图拷贝优化」名字含「蓝图」却并非蓝图，
  后缀谓词正好把这类名字排除。

## 函数

### `looks_like_blueprint_name`

```python
def looks_like_blueprint_name(name: str | None) -> bool
```

名字是否带蓝图标记（蓝图 / Blueprint / 公式 / 配方 / Formula，忽略大小写）。

定义行：`32`

### `blueprint_type_ids`

```python
def blueprint_type_ids(conn: sqlite3.Connection | sqlite3.Cursor, type_ids: Iterable[int | None]) -> set[int]
```

从 type_ids 中挑出蓝图 id（单次批量查询）。

定义行：`40`

### `is_material_name`

```python
def is_material_name(conn: sqlite3.Connection | sqlite3.Cursor, name: str) -> bool
```

名字是否可判定为「材料行」（蓝图导入按仓库类型过滤用）。

定义行：`71`
