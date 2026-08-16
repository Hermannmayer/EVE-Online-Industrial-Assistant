# services.terminology

> 源文件 `services/terminology.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

统一术语服务 — 加载 terminology.yaml 提供游戏术语查询。

## 类

### `class Terminology`

单例术语表，线程安全（只读加载后不变）。

定义行：`29`

#### 方法

##### `__init__`

```python
def __init__(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`32`
##### `_ensure`

```python
def _ensure(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`36`
##### `activity`

```python
def activity(self, key: str) -> str
```

蓝图活动名英译中，未知 key 返回原文。

定义行：`48`
##### `item_override`

```python
def item_override(self, type_id: int) -> str | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`55`
##### `group_override`

```python
def group_override(self, group_id: int) -> str | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`62`
##### `label`

```python
def label(self, key: str) -> str
```

UI 标签翻译。

定义行：`69`
##### `market_category`

```python
def market_category(self, key: str) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`76`
##### `skill_alias`

```python
def skill_alias(self, en_name: str) -> str | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`82`
##### `skill_name`

```python
def skill_name(self, en_name: str) -> str | None
```

获取技能官方中文名。

定义行：`88`
##### `system_name`

```python
def system_name(self, en_name: str) -> str | None
```

星系中文名（按英文名查表）。未知返回 None，显示层回退英文名。

定义行：`103`
##### `search_system_names`

```python
def search_system_names(self, keyword: str) -> list[str]
```

按中文名关键词反查星系英文名（用于星系搜索对话框中文输入）。

定义行：`111`
##### `rig_category`

```python
def rig_category(self, key: str) -> str | None
```

结构改件制造类别标签（me_research→材料效率研究 等）。未知返回 None。

定义行：`118`
##### `reload`

```python
def reload(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`125`
