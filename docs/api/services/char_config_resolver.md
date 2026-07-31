# services.char_config_resolver

> 源文件 `services/char_config_resolver.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

角色配置统一解析 — 四种来源合并，消除对 UI 层的反依赖。

## 函数

### `char_config_path`

```python
def char_config_path() -> str
```

char_config.json 文件路径

定义行：`25`

### `load_all_data`

```python
def load_all_data() -> dict
```

加载完整角色配置

定义行：`30`

### `save_all_data`

```python
def save_all_data(data: dict) -> None
```

保存完整角色配置

定义行：`35`

### `get_character`

```python
def get_character(name: str) -> dict | None
```

获取指定角色的完整配置

定义行：`43`

### `get_character_list`

```python
def get_character_list() -> list[str]
```

获取所有角色名列表

定义行：`49`

### `get_default_resolver`

```python
def get_default_resolver() -> CharConfigResolver
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`87`

### `resolve_char_config`

```python
def resolve_char_config(char_name: str | None=None, char_data: dict | None=None, skills: dict | None=None) -> dict
```

模块级便利函数（向后兼容），使用默认解析器

定义行：`94`

## 类

### `class CharConfigResolver`

角色配置解析器 — 注入回调避免反依赖 UI 层

定义行：`55`

#### 方法

##### `__init__`

```python
def __init__(self, char_data_provider: Callable[[str], dict | None] | None=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`58`
##### `resolve`

```python
def resolve(self, char_name: str | None=None, char_data: dict | None=None, skills: dict | None=None) -> dict
```

返回保证包含 'skills' 和 'market' 键的配置 dict

定义行：`61`
