# ui_pyside6.workers.estimate_workers

> 源文件 `ui_pyside6/workers/estimate_workers.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

估价页面 — 剪贴板解析 Worker + 物品搜索

## 函数

### `_parse_clipboard`

```python
def _parse_clipboard(text: str) -> list[tuple[str, int, float]]
```

解析 EVE 剪贴板格式，返回 [(物品名, 数量), ...]

定义行：`8`

### `_search_item_by_name`

```python
def _search_item_by_name(name: str) -> dict | None
```

按中文/英文名搜索物品，返回 &#123;type_id, zh_name, en_name, iconID, volume&#125; 或 None

定义行：`65`

## 类

### `class ClipboardParseWorker`（继承 `QThread`）

后台解析剪贴板并查找物品/价格

定义行：`72`

#### 方法

##### `__init__`

```python
def __init__(self, text: str, price_type: str, hub: str, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`78`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`84`
