# core.search_history

> 源文件 `core/search_history.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

查询页的搜索历史（纯文件 I/O，零 Qt）。

原先在 `ui_pyside6/views/query/query_search.py`：它只依赖 `core.paths`，
放在 UI 层里没有道理，QML 侧也要用。

## 函数

### `add_search_history`

```python
def add_search_history(query: str)
```

保存搜索历史到文件

定义行：`17`

### `load_search_history`

```python
def load_search_history() -> list
```

从文件加载搜索历史

定义行：`33`

### `clear_search_history`

```python
def clear_search_history()
```

清空搜索历史文件

定义行：`43`
